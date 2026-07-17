from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from kavach_saathi.auth import require_role
from kavach_saathi.config import Settings, get_settings
from kavach_saathi.container import get_container
from kavach_saathi.db.base import get_session
from kavach_saathi.db.models import (
    Address,
    CartItem,
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
    Product,
    ProductVariant,
    RazorpayWebhookEvent,
    ReturnRecord,
    Review,
    SupportInteraction,
    User,
    WishlistItem,
)
from kavach_saathi.events import ORDER_PLACED_STREAM, REVIEW_SUBMITTED_STREAM, publish_event
from kavach_saathi.media_storage import read_image_bytes
from kavach_saathi.models import (
    AddressCreateRequest,
    AddressGeocodeRequest,
    AddressUpdateRequest,
    AddressVerifyRequest,
    CartItemAdd,
    CartItemUpdate,
    Coordinates,
    FitFeedbackRequest,
    OrderCreateRequest,
    OtpSendRequest,
    OtpVerifyRequest,
    PaymentVerifyRequest,
    ReturnCreateRequest,
    ReturnImageAttemptRequest,
    ReviewCreateRequest,
    WorkflowType,
)
from kavach_saathi.order_status import OrderStatus
from kavach_saathi.providers.google_maps import GoogleMapsUnavailable
from kavach_saathi.providers.razorpay_provider import RazorpayClient, RazorpayUnavailable
from kavach_saathi.providers.return_vision import ReturnVisionVerifier
from kavach_saathi.redis_client import get_redis

router = APIRouter()
_require_buyer = require_role("buyer")


def validate_phone_with_lookup(phone: str, country: str | None, cfg: Settings) -> dict:
    from kavach_saathi.providers.twilio_integration import TwilioIntegrationClient

    twilio_integration = TwilioIntegrationClient(cfg)

    country_map = {
        "india": "IN",
        "united states": "US",
        "us": "US",
        "united kingdom": "GB",
        "uk": "GB",
    }
    selected_country = (country or "India").strip().lower()
    country_code = country_map.get(selected_country, "IN")

    try:
        lookup_res = twilio_integration.lookup_phone(phone, country_code)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    is_valid = (
        lookup_res.get("valid") is True
        and lookup_res.get("country_code", "").upper() == country_code.upper()
        and lookup_res.get("line_type")
        in (
            "mobile",
            "voip",
            "personal",
            "fixed_line_or_mobile",
            "fixed-line-or-mobile",
        )
    )
    if lookup_res.get("valid") is not True:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid phone number according to carrier validation.",
                "errors": {"phone": "Invalid phone number according to carrier validation."}
            }
        )
    if lookup_res.get("country_code", "").upper() != country_code.upper():
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Phone number country code mismatch: expected {country_code}, got {lookup_res.get('country_code') or 'unknown'}.",
                "errors": {"phone": f"Phone number country code mismatch: expected {country_code}, got {lookup_res.get('country_code') or 'unknown'}."}
            }
        )
    valid_line_types = (
        "mobile",
        "voip",
        "personal",
        "fixed_line_or_mobile",
        "fixed-line-or-mobile",
    )
    if lookup_res.get("line_type") not in valid_line_types:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Unsupported line type: {lookup_res.get('line_type') or 'unknown'}.",
                "errors": {"phone": f"Unsupported line type: {lookup_res.get('line_type') or 'unknown'}."}
            }
        )
    return lookup_res


# A per-item return can move the whole order out of DELIVERED (e.g. into
# RETURN_INITIATED) while other items in the same order are still eligible for
# their own return/exchange/fit-feedback -- any of these statuses still means the
# order was delivered at some point.
_POST_DELIVERY_STATUSES = {
    OrderStatus.DELIVERED,
    OrderStatus.RETURN_INITIATED,
    OrderStatus.RETURN_UNDER_REVIEW,
    OrderStatus.RETURN_APPROVED,
    OrderStatus.RETURN_REJECTED,
    OrderStatus.MANUAL_INSPECTION,
    OrderStatus.CLOSED,
}


def _address_out(address: Address) -> dict:
    return {
        "id": address.id,
        "recipient_name": address.recipient_name,
        "phone": address.phone,
        "address_line1": address.address_line1,
        "address_line2": address.address_line2,
        "locality": address.locality,
        "city": address.city,
        "district": address.district,
        "state": address.state,
        "postal_pin": address.postal_pin,
        "country": address.country,
        "latitude": address.latitude,
        "longitude": address.longitude,
        "digipin": address.digipin,
        "address_type": address.address_type,
        "phone_verified": address.phone_verified,
        "phone_lookup_validated": address.phone_lookup_validated,
        "lookup_status": address.lookup_status,
        "validation_status": address.validation_status,
        "validation_explanation": address.validation_explanation,
        "is_default": address.is_default,
        "created_at": address.created_at,
        "updated_at": address.updated_at,
    }


def _address_snapshot(address: Address, recipient_fallback: str) -> dict:
    return {
        "recipient_name": address.recipient_name or recipient_fallback,
        "phone": address.phone,
        "address_line1": address.address_line1 or address.raw_text,
        "address_line2": address.address_line2,
        "locality": address.locality,
        "city": address.city,
        "district": address.district or address.city,
        "state": address.state,
        "postal_pin": address.postal_pin,
        "country": address.country or "India",
        "digipin": address.digipin,
        "latitude": address.latitude,
        "longitude": address.longitude,
        "address_type": address.address_type or "Home",
    }


def _product_summary(product: Product) -> dict:
    return {
        "id": product.id,
        "name": product.title,
        "brand": product.brand,
        "price": product.price,
        "original_price": product.original_price,
        "image_url": product.media_primary,
        "stock": product.stock,
        "size_chart": product.size_chart,
    }


def _cart_item_out(item: CartItem, variant: ProductVariant, product: Product) -> dict:
    return {
        "id": item.id,
        "product_id": product.id,
        "product_name": product.title,
        "image_url": product.media_primary,
        "product_variant_id": variant.id,
        "size": variant.size,
        "qty": item.qty,
        "unit_price": variant.price,
        "line_total": round(variant.price * item.qty, 2),
        "stock_qty": variant.stock_qty,
    }


def _load_cart(session: Session, user_id: str) -> list[dict]:
    rows = session.execute(select(CartItem).where(CartItem.user_id == user_id).order_by(CartItem.id)).scalars().all()
    out = []
    for item in rows:
        variant = session.get(ProductVariant, item.product_variant_id)
        if not variant:
            continue
        product = session.get(Product, variant.product_id)
        if not product:
            continue
        out.append(_cart_item_out(item, variant, product))
    return out


@router.get("/cart")
async def get_cart(user: Annotated[User, Depends(_require_buyer)], session: Session = Depends(get_session)):
    items = _load_cart(session, user.id)
    return {"items": items, "subtotal": round(sum(item["line_total"] for item in items), 2)}


@router.post("/cart", status_code=201)
async def add_to_cart(
    payload: CartItemAdd,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    variant = session.get(ProductVariant, payload.product_variant_id)
    if not variant:
        raise HTTPException(status_code=404, detail="Product variant not found")
    existing = (
        session.execute(
            select(CartItem).where(
                CartItem.user_id == user.id, CartItem.product_variant_id == payload.product_variant_id
            )
        )
        .scalars()
        .first()
    )
    requested_qty = payload.qty + (existing.qty if existing else 0)
    if requested_qty > 10:
        raise HTTPException(status_code=409, detail="A maximum of 10 units is allowed per cart item")
    if requested_qty > variant.stock_qty:
        raise HTTPException(status_code=409, detail=f"Only {variant.stock_qty} units are currently available")
    if existing:
        existing.qty = requested_qty
    else:
        session.add(CartItem(user_id=user.id, product_variant_id=payload.product_variant_id, qty=payload.qty))
    session.flush()
    return {"items": _load_cart(session, user.id)}


@router.patch("/cart/{item_id}")
async def update_cart_item(
    item_id: int,
    payload: CartItemUpdate,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    item = session.get(CartItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Cart item not found")
    if payload.qty == 0:
        session.delete(item)
        session.flush()
        return {"items": _load_cart(session, user.id)}
    variant = session.get(ProductVariant, item.product_variant_id)
    if not variant:
        raise HTTPException(status_code=404, detail="Product variant not found")
    if payload.qty > variant.stock_qty:
        raise HTTPException(status_code=409, detail=f"Only {variant.stock_qty} units are currently available")
    item.qty = payload.qty
    session.flush()
    return {"items": _load_cart(session, user.id)}


@router.delete("/cart/{item_id}")
async def remove_cart_item(
    item_id: int,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    item = session.get(CartItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Cart item not found")
    session.delete(item)
    session.flush()
    return {"items": _load_cart(session, user.id)}


@router.get("/wishlist")
async def list_wishlist(user: Annotated[User, Depends(_require_buyer)], session: Session = Depends(get_session)):
    rows = (
        session.execute(
            select(WishlistItem).where(WishlistItem.user_id == user.id).order_by(WishlistItem.created_at.desc())
        )
        .scalars()
        .all()
    )
    items = []
    for row in rows:
        product = session.get(Product, row.product_id)
        if product:
            items.append({"id": row.id, "created_at": row.created_at, "product": _product_summary(product)})
    return {"items": items}


@router.post("/wishlist/{product_id}", status_code=201)
async def add_wishlist(
    product_id: str,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if not product or product.status != "active":
        raise HTTPException(status_code=404, detail="Product not found")
    item = (
        session.execute(
            select(WishlistItem).where(WishlistItem.user_id == user.id, WishlistItem.product_id == product_id)
        )
        .scalars()
        .first()
    )
    if item is None:
        item = WishlistItem(user_id=user.id, product_id=product_id)
        session.add(item)
        session.flush()
    return {"id": item.id, "product": _product_summary(product)}


@router.delete("/wishlist/{product_id}")
async def remove_wishlist(
    product_id: str,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    item = (
        session.execute(
            select(WishlistItem).where(WishlistItem.user_id == user.id, WishlistItem.product_id == product_id)
        )
        .scalars()
        .first()
    )
    if item:
        session.delete(item)
        session.flush()
    return {"removed": bool(item), "product_id": product_id}


def _finalize_prepaid_order(session: Session, order: Order, payment: Payment, payment_id: str) -> bool:
    if order.status != OrderStatus.CART:
        return False

    order_items = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalars().all()

    variant_ids = [item.product_variant_id for item in order_items]
    locked_variants = {
        variant.id: variant
        for variant in session.execute(
            select(ProductVariant).where(ProductVariant.id.in_(variant_ids)).with_for_update()
        ).scalars()
    }
    for item in order_items:
        variant = locked_variants.get(item.product_variant_id)
        if not variant or variant.stock_qty < item.qty:
            raise HTTPException(status_code=409, detail=f"Insufficient stock for variant {item.product_variant_id}")

    for item in order_items:
        # Delete from cart
        cart_item = (
            session.execute(
                select(CartItem).where(
                    CartItem.user_id == order.buyer_id, CartItem.product_variant_id == item.product_variant_id
                )
            )
            .scalars()
            .first()
        )
        if cart_item:
            session.delete(cart_item)

    order.status = OrderStatus.AWAITING_BUYER_CONFIRMATION
    order.whatsapp_workflow_state = "awaiting_order_confirmation"
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=OrderStatus.AWAITING_BUYER_CONFIRMATION,
            actor="system",
        )
    )

    payment.status = "captured"
    payment.provider_payment_id = payment_id
    payment.transaction_ref = payment_id
    return True


@router.post("/orders", status_code=201)
async def create_order(
    payload: OrderCreateRequest,
    user: Annotated[User, Depends(_require_buyer)],
    cfg: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    address = session.get(Address, payload.address_id)
    if not address or address.user_id != user.id:
        raise HTTPException(status_code=404, detail="Address not found")

    # Checkout validation rules (phone validated by carrier lookup, valid status, digipin present)
    if not address.phone_lookup_validated:
        raise HTTPException(status_code=400, detail="Address phone number is not validated by carrier lookup")
    if address.validation_status != "valid":
        raise HTTPException(status_code=400, detail="Address has not passed validation agent check")
    if not address.digipin:
        raise HTTPException(status_code=400, detail="Required DIGIPIN is missing from address")

    cart_rows = session.execute(select(CartItem).where(CartItem.user_id == user.id)).scalars().all()
    if not cart_rows:
        raise HTTPException(status_code=400, detail="Cart is empty")

    razorpay_order: dict | None = None
    if payload.payment_mode == "prepaid" and not RazorpayClient(cfg).is_configured:
        raise HTTPException(status_code=503, detail="Prepaid payment unavailable: Razorpay is not configured")

    resolved: list[tuple[CartItem, ProductVariant, Product]] = []
    for cart_item in cart_rows:
        variant = session.get(ProductVariant, cart_item.product_variant_id)
        if not variant:
            raise HTTPException(status_code=409, detail="A cart item's product variant no longer exists")
        if variant.stock_qty < cart_item.qty:
            raise HTTPException(status_code=409, detail=f"Insufficient stock for {variant.id}")
        product = session.get(Product, variant.product_id)
        resolved.append((cart_item, variant, product))

    order_id = f"O-{uuid4().hex[:10].upper()}"
    total_amount = round(sum(variant.price * cart_item.qty for cart_item, variant, _ in resolved), 2)

    # Prepaid orders remain drafts until payment is captured. COD orders immediately
    # enter the persisted WhatsApp confirmation workflow; neither path is delivered
    # until delivery evidence and buyer OTP verification are complete.
    status = OrderStatus.CART if payload.payment_mode == "prepaid" else OrderStatus.AWAITING_BUYER_CONFIRMATION

    order = Order(
        id=order_id,
        buyer_id=user.id,
        address_id=address.id,
        status=status,
        total_amount=total_amount,
        payment_mode=payload.payment_mode,
        address_snapshot=_address_snapshot(address, user.name),
        whatsapp_workflow_state=("awaiting_order_confirmation" if payload.payment_mode == "cod" else None),
    )

    session.add(order)
    session.flush()

    for cart_item, variant, product in resolved:
        session.add(
            OrderItem(
                order_id=order_id,
                product_id=product.id,
                product_variant_id=variant.id,
                seller_id=product.seller_id,
                size=variant.size,
                qty=cart_item.qty,
                price_at_purchase=variant.price,
            )
        )
        if payload.payment_mode == "cod":
            session.delete(cart_item)

    delivery_confirmation_queued = False
    if payload.payment_mode == "cod":
        session.add(
            OrderStatusHistory(
                order_id=order_id,
                status=OrderStatus.AWAITING_BUYER_CONFIRMATION,
                actor="system",
            )
        )
        session.commit()
        delivery_confirmation_queued = bool(
            publish_event(ORDER_PLACED_STREAM, {"order_id": order_id, "buyer_id": user.id})
        )
    else:
        try:
            razorpay_order = RazorpayClient(cfg).create_order(amount_rupees=total_amount, receipt=order_id)
        except RazorpayUnavailable as exc:
            raise HTTPException(status_code=503, detail=f"Prepaid payment unavailable: {exc}") from exc
        session.add(
            Payment(
                id=f"PAY-{order_id}",
                order_id=order_id,
                provider="razorpay",
                status="pending",
                transaction_ref=razorpay_order.get("id"),
                provider_order_id=razorpay_order.get("id"),
                amount=total_amount,
                currency=razorpay_order.get("currency", "INR"),
            )
        )
        session.commit()

    return {
        "order_id": order_id,
        "status": order.status,
        "total_amount": total_amount,
        "payment_mode": payload.payment_mode,
        "delivery_confirmation_queued": delivery_confirmation_queued,
        "razorpay": (
            {
                "razorpay_order_id": razorpay_order["id"],
                "amount": razorpay_order["amount"],
                "currency": razorpay_order["currency"],
                "key_id": cfg.razorpay_key_id,
            }
            if razorpay_order
            else None
        ),
    }


@router.post("/orders/{order_id}/verify-payment")
async def verify_payment(
    order_id: str,
    payload: PaymentVerifyRequest,
    user: Annotated[User, Depends(_require_buyer)],
    cfg: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    order = session.get(Order, order_id)
    if not order or order.buyer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    payment = session.execute(select(Payment).where(Payment.order_id == order_id)).scalars().first()
    if not payment:
        raise HTTPException(status_code=404, detail="No payment record for this order")
    if payment.provider_order_id != payload.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Payment order ID does not match this checkout")

    try:
        client = RazorpayClient(cfg)
        verified = client.verify_payment_signature(
            razorpay_order_id=payload.razorpay_order_id,
            razorpay_payment_id=payload.razorpay_payment_id,
            razorpay_signature=payload.razorpay_signature,
        )
    except RazorpayUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not verified:
        payment.status = "failed"
        payment.failure_reason = "signature_verification_failed"
        session.commit()
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    finalized = _finalize_prepaid_order(session, order, payment, payload.razorpay_payment_id)
    session.commit()
    delivery_confirmation_queued = False
    if finalized:
        delivery_confirmation_queued = bool(
            publish_event(ORDER_PLACED_STREAM, {"order_id": order_id, "buyer_id": user.id})
        )
    return {
        "order_id": order_id,
        "payment_status": payment.status,
        "status": order.status,
        "delivery_confirmation_queued": delivery_confirmation_queued,
    }


class DemoPaymentRequest(BaseModel):
    card_number: str
    expiry_date: str  # MM/YY
    cvv: str


@router.post("/orders/{order_id}/verify-demo-payment")
async def verify_demo_payment(
    order_id: str,
    payload: DemoPaymentRequest,
    user: Annotated[User, Depends(_require_buyer)],
    cfg: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    if cfg.app_mode != "demo":
        raise HTTPException(status_code=403, detail="Demo payments are disabled in live mode")

    order = session.get(Order, order_id)
    if not order or order.buyer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")

    payment = session.execute(select(Payment).where(Payment.order_id == order_id)).scalars().first()
    if not payment:
        raise HTTPException(status_code=404, detail="No payment record for this order")

    # Validate card details
    card_num = payload.card_number.replace(" ", "").replace("-", "")
    if len(card_num) != 16 or not card_num.isdigit():
        raise HTTPException(status_code=400, detail="Invalid card number. Must be 16 digits.")

    if len(payload.cvv) != 3 or not payload.cvv.isdigit():
        raise HTTPException(status_code=400, detail="Invalid CVV. Must be 3 digits.")

    import re

    if not re.match(r"^(0[1-9]|1[0-2])/\d{2}$", payload.expiry_date):
        raise HTTPException(status_code=400, detail="Invalid expiry date format. Use MM/YY.")

    month_str, year_str = payload.expiry_date.split("/")
    month = int(month_str)
    year = int("20" + year_str)

    now = datetime.now()
    cur_year = now.year
    cur_month = now.month

    if year < cur_year or (year == cur_year and month < cur_month):
        raise HTTPException(status_code=400, detail="Card has expired.")

    # Finalize prepaid order
    finalized = _finalize_prepaid_order(session, order, payment, f"demo_pay_{order_id}")
    session.commit()

    delivery_confirmation_queued = False
    if finalized:
        delivery_confirmation_queued = bool(
            publish_event(ORDER_PLACED_STREAM, {"order_id": order_id, "buyer_id": user.id})
        )

    return {
        "order_id": order_id,
        "payment_status": payment.status,
        "status": order.status,
        "delivery_confirmation_queued": delivery_confirmation_queued,
    }


@router.get("/orders/{order_id}/payment-status")
async def payment_status(
    order_id: str,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    order = session.get(Order, order_id)
    if not order or order.buyer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    payment = session.execute(select(Payment).where(Payment.order_id == order_id)).scalars().first()
    return {
        "order_id": order.id,
        "order_status": order.status,
        "payment_status": payment.status if payment else "not_required",
        "amount": order.total_amount,
    }


@router.get("/orders")
async def list_my_orders(user: Annotated[User, Depends(_require_buyer)], session: Session = Depends(get_session)):
    orders = (
        session.execute(
            select(Order)
            .where(Order.buyer_id == user.id, Order.status != OrderStatus.CART)
            .order_by(Order.created_at.desc())
        )
        .scalars()
        .all()
    )
    order_ids = [o.id for o in orders]
    items_by_order: dict[str, list[OrderItem]] = {}
    if order_ids:
        for item in session.execute(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).scalars():
            items_by_order.setdefault(item.order_id, []).append(item)

    # Batch-load return records (keyed per line item, not per order -- a return only
    # ever covers the one product it was filed for) and reviews for all relevant orders
    returns_by_order_item: dict[tuple[str, str], ReturnRecord] = {}
    if order_ids:
        for rr in session.execute(select(ReturnRecord).where(ReturnRecord.order_id.in_(order_ids))).scalars():
            returns_by_order_item[(rr.order_id, rr.product_id)] = rr

    result = []
    for order in orders:
        order_items = items_by_order.get(order.id, [])
        # Check if buyer has already reviewed any product in this order
        product_ids = list({i.product_id for i in order_items})
        reviewed_products: set[str] = set()
        POST_DELIVERY_STATUSES = {
            OrderStatus.DELIVERED,
            OrderStatus.RETURN_INITIATED,
            OrderStatus.RETURN_UNDER_REVIEW,
            OrderStatus.MANUAL_INSPECTION,
            OrderStatus.RETURN_APPROVED,
            OrderStatus.RETURN_REJECTED,
            OrderStatus.CLOSED,
        }
        if product_ids and order.status in POST_DELIVERY_STATUSES:
            for rv in session.execute(
                select(Review).where(Review.buyer_id == user.id, Review.product_id.in_(product_ids))
            ).scalars():
                reviewed_products.add(rv.product_id)

        def _return_info(rr: ReturnRecord | None) -> dict | None:
            if not rr:
                return None
            return {
                "id": rr.id,
                "return_type": rr.return_type,
                "status": rr.status,
                "decision": rr.decision,
                "confidence_score": rr.confidence_score,
                "pickup_date": rr.pickup_date,
                "refund_status": rr.refund_status,
                "replacement_order_id": rr.replacement_order_id,
                "created_at": rr.created_at,
            }

        result.append(
            {
                "id": order.id,
                "status": order.status,
                "total_amount": order.total_amount,
                "payment_mode": order.payment_mode,
                "exchange_tag": order.exchange_tag,
                "original_order_id": order.original_order_id,
                "created_at": order.created_at,
                "fit_feedback": order.fit_feedback,
                "items": [
                    {
                        "product_id": i.product_id,
                        "product_name": session.get(Product, i.product_id).title
                        if session.get(Product, i.product_id)
                        else "Unknown",
                        "image_url": session.get(Product, i.product_id).media_primary
                        if session.get(Product, i.product_id)
                        else "",
                        "size": i.size,
                        "qty": i.qty,
                        "price_at_purchase": i.price_at_purchase,
                        "already_reviewed": i.product_id in reviewed_products,
                        "return_info": _return_info(returns_by_order_item.get((order.id, i.product_id))),
                    }
                    for i in order_items
                ],
            }
        )
    return result


@router.post("/orders/{order_id}/fit-feedback")
async def submit_fit_feedback(
    order_id: str,
    payload: FitFeedbackRequest,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    order = session.get(Order, order_id)
    if not order or order.buyer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in _POST_DELIVERY_STATUSES:
        raise HTTPException(status_code=409, detail="Fit feedback can only be given after delivery")
    order.fit_feedback = payload.feedback
    session.commit()
    return {"order_id": order.id, "fit_feedback": order.fit_feedback}


@router.get("/returns")
async def list_my_returns(
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    rows = (
        session.execute(
            select(ReturnRecord).where(ReturnRecord.buyer_id == user.id).order_by(ReturnRecord.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "order_id": row.order_id,
            "product_id": row.product_id,
            "reason": row.reason,
            "return_type": row.return_type,
            "status": row.status,
            "decision": row.decision,
            "confidence_score": row.confidence_score,
            "pickup_date": row.pickup_date,
            "pickup_status": row.pickup_status,
            "refund_status": row.refund_status,
            "refund_masked_details": row.refund_masked_details,
            "replacement_order_id": row.replacement_order_id,
            "evidence_images": row.evidence_images,
            "evidence_checks": row.evidence_checks,
            "buyer_front_image": row.buyer_front_image,
            "buyer_back_image": row.buyer_back_image,
            "similarity_front": row.similarity_front,
            "similarity_back": row.similarity_back,
            "similarity_aggregate": row.similarity_aggregate,
            "attempt_history": row.attempt_history,
            "status_timeline": row.status_timeline,
            "decided_at": row.decided_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/returns", status_code=201)
async def create_return_request(
    payload: ReturnCreateRequest,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    order = session.get(Order, payload.order_id)
    if not order or order.buyer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in _POST_DELIVERY_STATUSES:
        raise HTTPException(status_code=409, detail="Returns can only be requested after delivery")
    item = (
        session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id, OrderItem.product_id == payload.product_id)
        )
        .scalars()
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="This product is not part of that order")
    existing = (
        session.execute(
            select(ReturnRecord).where(ReturnRecord.order_id == order.id, ReturnRecord.product_id == payload.product_id)
        )
        .scalars()
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A return already exists for this product")

    return_type = getattr(payload, "return_type", "refund") or "refund"
    if return_type not in ("refund", "exchange"):
        return_type = "refund"

    record = ReturnRecord(
        id=f"RT-{uuid4().hex[:10].upper()}",
        order_id=order.id,
        product_id=payload.product_id,
        buyer_id=user.id,
        reason=payload.reason,
        return_type=return_type,
        status="pending_evidence",
        decision=None,
    )
    session.add(record)
    # Order status still reflects "a return is in progress" at the whole-order level
    # -- a full per-item order status machine is out of scope here; multiple returns
    # on the same order all share this one coarse status.
    order.status = OrderStatus.RETURN_INITIATED
    session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.RETURN_INITIATED, actor="user"))
    session.flush()
    return {
        "id": record.id,
        "order_id": record.order_id,
        "product_id": record.product_id,
        "reason": record.reason,
        "return_type": record.return_type,
        "status": record.status,
    }


async def _read_valid_return_image(key: str, cfg: Settings) -> bytes:
    from PIL import Image

    if not key.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        raise HTTPException(status_code=400, detail="Return evidence must be a JPG, PNG, or WebP image")
    try:
        content = await read_image_bytes(key, cfg)
        if not content or len(content) > 15 * 1024 * 1024:
            raise ValueError("image is empty or exceeds 15 MB")
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            if image.width < 200 or image.height < 200:
                raise ValueError("image dimensions must be at least 200 x 200")
    except (OSError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid return image: {exc}") from exc
    return content


def _return_similarity(reference: bytes, candidate: bytes) -> float:
    score, _ = ReturnVisionVerifier().best_match([candidate], reference)
    return round(max(0.0, min(1.0, score)) * 100, 2)


@router.post("/returns/{return_id}/image-attempt")
async def submit_return_image_attempt(
    return_id: str,
    payload: ReturnImageAttemptRequest,
    user: Annotated[User, Depends(_require_buyer)],
    cfg: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    record = session.get(ReturnRecord, return_id)
    if not record or record.buyer_id != user.id:
        raise HTTPException(status_code=404, detail="Return request not found")
    if record.status not in {"pending_evidence", "needs_evidence"}:
        raise HTTPException(status_code=409, detail="This return no longer accepts evidence")
    attempts = list(record.attempt_history or [])
    if len(attempts) >= 3:
        raise HTTPException(status_code=409, detail="Maximum of three evidence attempts reached")
    try:
        accepted = get_redis().set(
            f"idempotency:return-attempt:{return_id}:{payload.idempotency_key}",
            "processing",
            nx=True,
            ex=600,
        )
        if not accepted:
            raise HTTPException(status_code=409, detail="This evidence attempt is already being processed")
    except HTTPException:
        raise
    except Exception:
        pass

    item = (
        session.execute(
            select(OrderItem).where(
                OrderItem.order_id == record.order_id,
                OrderItem.product_id == record.product_id,
            )
        )
        .scalars()
        .first()
    )
    if not item or not item.delivery_front_image or not item.delivery_back_image:
        raise HTTPException(status_code=409, detail="Delivery front/back evidence is unavailable for this item")

    buyer_front, buyer_back, delivery_front, delivery_back = await asyncio.gather(
        _read_valid_return_image(payload.front_image_key, cfg),
        _read_valid_return_image(payload.back_image_key, cfg),
        _read_valid_return_image(item.delivery_front_image, cfg),
        _read_valid_return_image(item.delivery_back_image, cfg),
    )

    from kavach_saathi.providers.return_provider import ReturnComparisonProvider

    comparison_provider = ReturnComparisonProvider(cfg)
    try:
        front_res, back_res = await asyncio.gather(
            comparison_provider.compare(
                delivered_image_bytes=delivery_front,
                returned_image_bytes=buyer_front,
                comparison_type="front",
            ),
            comparison_provider.compare(
                delivered_image_bytes=delivery_back,
                returned_image_bytes=buyer_back,
                comparison_type="back",
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Image verification is temporarily unavailable. Please retry; this attempt was not counted.", "code": "provider_unavailable"},
        ) from exc

    front_score = front_res.visual_similarity_score
    back_score = back_res.visual_similarity_score
    aggregate = round((front_score + back_score) / 2, 2)
    passed = aggregate >= 60

    attempt = {
        "attempt": len(attempts) + 1,
        "created_at": datetime.now(UTC).isoformat(),
        "front_image_key": payload.front_image_key,
        "back_image_key": payload.back_image_key,
        "front_sha256": hashlib.sha256(buyer_front).hexdigest(),
        "back_sha256": hashlib.sha256(buyer_back).hexdigest(),
        "similarity_front": front_score,
        "similarity_back": back_score,
        "similarity_aggregate": aggregate,
        "front_provider": front_res.provider,
        "front_model": front_res.model,
        "back_provider": back_res.provider,
        "back_model": back_res.model,
        "front_differences": front_res.visible_differences,
        "back_differences": back_res.visible_differences,
        "passed": passed,
    }
    attempts.append(attempt)
    record.attempt_history = attempts
    record.buyer_front_image = payload.front_image_key
    record.buyer_back_image = payload.back_image_key
    record.evidence_images = [payload.front_image_key, payload.back_image_key]
    record.similarity_front = front_score
    record.similarity_back = back_score
    record.similarity_aggregate = aggregate
    record.confidence_score = round(aggregate)
    if passed:
        record.status = "pending_return"
        record.pickup_status = "pending"
        record.decision = "evidence_matched"
    elif len(attempts) >= 3:
        record.status = "evidence_mismatch"
        record.decision = "declined_evidence_mismatch"
        record.decided_at = datetime.now(UTC)
    else:
        record.status = "needs_evidence"
    session.commit()

    remaining = max(0, 3 - len(attempts))
    if passed:
        message = "Images matched. Return pickup is now pending."
    elif remaining:
        message = "The images do not clearly match. Retake clear, well-lit front and back photos."
    else:
        message = "Return declined after three mismatched attempts. Contact customer care for help."
    return {
        "passed": passed,
        "status": record.status,
        "attempts_used": len(attempts),
        "attempts_remaining": remaining,
        "similarity_front": front_score,
        "similarity_back": back_score,
        "similarity_aggregate": aggregate,
        "message": message,
        "support_path": "/support" if record.status == "evidence_mismatch" else None,
    }


@router.post("/reviews", status_code=201)
async def create_review(
    payload: ReviewCreateRequest,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
    container: Container = Depends(get_container),
):
    product = session.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Before validation: check text length and image requirements
    trimmed_text = payload.text.strip() if payload.text else ""
    if not trimmed_text or len(trimmed_text) < 10:
        raise HTTPException(status_code=400, detail="Review text must be at least 10 characters long.")
    if not payload.image_key or not payload.image_key.strip():
        raise HTTPException(status_code=400, detail="Exactly one review image is required.")

    # Check that the user has a confirmed delivered order containing this product
    POST_DELIVERY_STATUSES = {
        OrderStatus.DELIVERED,
        OrderStatus.RETURN_INITIATED,
        OrderStatus.RETURN_UNDER_REVIEW,
        OrderStatus.MANUAL_INSPECTION,
        OrderStatus.RETURN_APPROVED,
        OrderStatus.RETURN_REJECTED,
        OrderStatus.CLOSED,
    }
    has_delivered_order = (
        session.execute(
            select(Order)
            .join(OrderItem, Order.id == OrderItem.order_id)
            .where(
                Order.buyer_id == user.id,
                Order.id == payload.order_id,
                Order.status.in_(POST_DELIVERY_STATUSES),
                OrderItem.product_id == payload.product_id,
            )
        )
        .scalars()
        .first()
    )
    if not has_delivered_order:
        raise HTTPException(
            status_code=400, detail="You can only review products you have purchased and had delivered."
        )

    # Check for duplicate review by the same buyer for this product
    duplicate = (
        session.execute(select(Review).where(Review.buyer_id == user.id, Review.product_id == payload.product_id))
        .scalars()
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="You have already submitted a review for this product.")

    # Fetch image bytes for verification
    from kavach_saathi.media_storage import read_image_bytes
    from kavach_saathi.providers.review_provider import ReviewVerificationProvider

    try:
        catalogue_bytes = await read_image_bytes(product.media_primary, container.settings)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to load catalogue primary image: {exc}"
        )

    try:
        review_image_bytes = await read_image_bytes(payload.image_key, container.settings)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to load uploaded review image: {exc}"
        )

    provider = ReviewVerificationProvider(container.settings)
    try:
        res = await provider.verify(
            catalogue_image_bytes=catalogue_bytes,
            review_image_bytes=review_image_bytes,
            product_title=product.title,
            product_specs=json.dumps(product.spec_json or {}),
            review_text=payload.text,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": "Review verification is temporarily unavailable. Please retry later.", "code": "provider_unavailable"},
        ) from exc

    if not res.overall_passed:
        errors = {}
        if not res.product_image_match_passed:
            errors["image_key"] = "The uploaded image does not appear to show this product."
        if not res.text_quality_passed:
            errors["text"] = "Please replace unrelated, random, or incomplete text with your actual product experience."
        if not res.image_text_match_passed:
            errors["text"] = "Your text describes a different item than the uploaded image."
        raise HTTPException(status_code=422, detail={"message": "Please correct the highlighted review fields.", "errors": errors})

    review_id = f"RV-{uuid4().hex[:10].upper()}"
    review = Review(
        id=review_id,
        product_id=payload.product_id,
        buyer_id=user.id,
        order_id=payload.order_id,
        rating=payload.rating,
        text=payload.text,
        media=payload.image_key,
        is_hidden_by_agent=False,
        awaiting_analysis=False,
        validation_provider=res.provider,
        validation_model=res.model,
        product_image_match_passed=res.product_image_match_passed,
        product_image_match_confidence=res.product_image_match_confidence,
        product_image_match_reason=res.product_image_match_reason,
        image_text_match_passed=res.image_text_match_passed,
        image_text_match_confidence=res.image_text_match_confidence,
        image_text_match_reason=res.image_text_match_reason,
        text_quality_passed=res.text_quality_passed,
        text_quality_classification=res.text_quality_classification,
        text_quality_reason=res.text_quality_reason,
        overall_passed=res.overall_passed,
    )
    session.add(review)

    total_rating = product.rating * product.review_count + payload.rating
    product.review_count += 1
    product.rating = round(total_rating / product.review_count, 2)
    session.commit()

    event_published = publish_event(
        REVIEW_SUBMITTED_STREAM,
        {"review_id": review_id, "product_id": payload.product_id, "image_key": payload.image_key},
    )

    return {
        "id": review_id,
        "product_id": payload.product_id,
        "rating": payload.rating,
        "text": payload.text,
        "media": payload.image_key,
        "agent4_queued": event_published is not None,
    }


@router.post("/addresses/otp/send")
async def send_otp(
    payload: OtpSendRequest,
    user: Annotated[User, Depends(_require_buyer)],
    cfg: Settings = Depends(get_settings),
    container=Depends(get_container),
):
    phone = payload.phone
    active_session = container.repository.get_active_otp_session(user.id, phone, payload.address_session_id)
    if active_session:
        time_elapsed = datetime.now(UTC) - active_session.last_sent_at.replace(tzinfo=UTC)
        cooldown = cfg.otp_resend_cooldown_seconds
        if time_elapsed < timedelta(seconds=cooldown):
            wait_sec = cooldown - int(time_elapsed.total_seconds())
            raise HTTPException(status_code=429, detail=f"Please wait {wait_sec} seconds before requesting a new OTP")

    demo_otp = cfg.otp_demo_code if cfg.app_mode == "demo" else None
    otp_code = demo_otp or str(secrets.randbelow(900000) + 100000)
    otp_hash = container.address_agent.otp_digest(otp_code)
    expires_at = datetime.now(UTC) + timedelta(seconds=cfg.otp_expiry_seconds)

    verification = container.repository.create_otp_session(
        user.id, phone, payload.address_session_id, otp_hash, expires_at
    )

    twilio_configured = cfg.twilio_account_sid and cfg.twilio_auth_token and cfg.twilio_from_number
    sent = False
    if twilio_configured and not demo_otp:
        try:
            from twilio.rest import Client as TwilioClient

            client = TwilioClient(cfg.twilio_account_sid, cfg.twilio_auth_token)
            client.messages.create(
                body=f"Your Kavach Saathi verification code is: {otp_code}. It expires shortly.",
                from_=cfg.twilio_from_number,
                to=phone,
            )
            sent = True
            logging.info("Address verification OTP sent via Twilio")
        except Exception:
            logging.exception("Failed to send address verification OTP via Twilio")

    if not sent and not demo_otp:
        raise HTTPException(status_code=503, detail="OTP delivery is temporarily unavailable")

    result = {
        "message": "OTP sent successfully",
        "verification_session_id": verification.id,
        "expires_in": cfg.otp_expiry_seconds,
        "resend_after": cfg.otp_resend_cooldown_seconds,
    }
    if demo_otp:
        result["demo_otp"] = demo_otp
    return result


@router.post("/addresses/otp/verify")
async def verify_otp(
    payload: OtpVerifyRequest,
    user: Annotated[User, Depends(_require_buyer)],
    cfg: Settings = Depends(get_settings),
    container=Depends(get_container),
):
    phone = payload.phone
    otp = payload.otp

    session = container.repository.get_active_otp_session(user.id, phone, payload.address_session_id)
    if not session:
        raise HTTPException(status_code=400, detail="No active verification session found for this phone")

    if session.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

    if session.attempts >= cfg.otp_max_attempts:
        raise HTTPException(status_code=400, detail="Too many failed attempts. Please request a new OTP.")

    if not container.address_agent.otp_matches(session.otp_hash, otp):
        attempts = container.repository.increment_otp_attempts(session.id)
        if attempts >= cfg.otp_max_attempts:
            raise HTTPException(status_code=400, detail="Too many failed attempts. Please request a new OTP.")
        raise HTTPException(status_code=400, detail="Incorrect verification code")

    container.repository.mark_otp_verified(session.id)
    return {"message": "Phone number verified successfully", "verification_session_id": session.id}


@router.get("/addresses")
async def get_addresses(
    user: Annotated[User, Depends(_require_buyer)],
    container=Depends(get_container),
):
    addresses = container.repository.get_user_addresses(user.id)
    return [_address_out(address) for address in addresses]


@router.post("/addresses/validate")
async def validate_address_endpoint(
    payload: AddressVerifyRequest,
    user: Annotated[User, Depends(_require_buyer)],
    container=Depends(get_container),
):
    payload.buyer_id = user.id
    run_record = await container.service.execute(WorkflowType.ADDRESS, payload.model_dump(mode="json"))
    res = run_record.results.get("address_guardian")
    if not res:
        raise HTTPException(status_code=500, detail="Address validation agent failed to run")
    return res.data


@router.post("/addresses/geocode")
async def geocode_address(
    payload: AddressGeocodeRequest,
    user: Annotated[User, Depends(_require_buyer)],
    container=Depends(get_container),
):
    del user
    text = ", ".join(
        part
        for part in (
            payload.address_line1,
            payload.address_line2,
            payload.locality,
            payload.city,
            payload.district,
            payload.state,
            payload.postal_pin,
            payload.country,
        )
        if part
    )
    try:
        return await container.address_agent.resolve_manual_address(text)
    except GoogleMapsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/addresses/reverse-geocode")
async def reverse_geocode_address(
    payload: Coordinates,
    user: Annotated[User, Depends(_require_buyer)],
    container=Depends(get_container),
):
    del user
    try:
        return await container.address_agent.resolve_coordinates(payload.latitude, payload.longitude)
    except GoogleMapsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/addresses", status_code=201)
async def add_address(
    payload: AddressCreateRequest,
    user: Annotated[User, Depends(_require_buyer)],
    cfg: Settings = Depends(get_settings),
    container=Depends(get_container),
):
    lookup_res = validate_phone_with_lookup(payload.phone, payload.country, cfg)

    verify_req = AddressVerifyRequest(
        buyer_id=user.id,
        postal_pin=payload.postal_pin,
        coordinates=Coordinates(latitude=payload.latitude, longitude=payload.longitude),
        recipient_name=payload.recipient_name,
        phone=lookup_res["normalized_number"],
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        locality=payload.locality,
        city=payload.city,
        district=payload.district,
        state=payload.state,
        country=payload.country,
        address_type=payload.address_type,
    )

    run_record = await container.service.execute(WorkflowType.ADDRESS, verify_req.model_dump(mode="json"))
    res = run_record.results.get("address_guardian")
    if not res:
        raise HTTPException(status_code=500, detail="Address validation agent failed")

    validation_status = res.data.get("status", "needs_correction")
    validation_explanation = res.data.get("reason", "")

    if validation_status != "valid":
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Address verification failed. Please correct the fields.",
                "errors": res.data.get("field_errors"),
                "suggested": res.data.get("suggested_address"),
                "explanation": validation_explanation,
            },
        )

    existing = container.repository.get_user_addresses(user.id)
    address_id = container.repository.save_verified_address(
        user.id,
        raw_address=res.data["normalized_address"],
        city=payload.city,
        state=payload.state,
        postal_pin=payload.postal_pin,
        latitude=res.data["latitude"],
        longitude=res.data["longitude"],
        digipin=res.data["digipin"],
        recipient_name=payload.recipient_name,
        phone=lookup_res["normalized_number"],
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        locality=payload.locality,
        district=payload.district,
        country=payload.country,
        address_type=payload.address_type,
        phone_verified=False,
        phone_lookup_validated=True,
        lookup_status="lookup_validated",
        lookup_data=lookup_res,
        validation_status=validation_status,
        validation_explanation=validation_explanation,
        is_default=payload.is_default or not existing,
    )
    addr = container.repository.get_address(address_id)
    return _address_out(addr)


@router.put("/addresses/{address_id}")
async def update_address(
    address_id: str,
    payload: AddressUpdateRequest,
    user: Annotated[User, Depends(_require_buyer)],
    cfg: Settings = Depends(get_settings),
    container=Depends(get_container),
):
    addr = container.repository.get_address(address_id)
    if not addr or addr.user_id != user.id:
        raise HTTPException(status_code=404, detail="Address not found")

    lookup_res = None
    if payload.phone and payload.phone != addr.phone:
        lookup_res = validate_phone_with_lookup(payload.phone, payload.country or addr.country, cfg)

    fields_changed = any(
        getattr(payload, k) is not None and getattr(payload, k) != getattr(addr, k)
        for k in ["address_line1", "city", "state", "postal_pin", "latitude", "longitude"]
    )

    validation_status = addr.validation_status
    validation_explanation = addr.validation_explanation

    if fields_changed:
        verify_req = AddressVerifyRequest(
            buyer_id=user.id,
            postal_pin=payload.postal_pin or addr.postal_pin,
            coordinates=Coordinates(
                latitude=payload.latitude if payload.latitude is not None else addr.latitude,
                longitude=payload.longitude if payload.longitude is not None else addr.longitude,
            ),
            recipient_name=payload.recipient_name or addr.recipient_name,
            phone=payload.phone or addr.phone,
            address_line1=payload.address_line1 or addr.address_line1,
            address_line2=payload.address_line2 if payload.address_line2 is not None else addr.address_line2,
            locality=payload.locality if payload.locality is not None else addr.locality,
            city=payload.city or addr.city,
            district=payload.district or addr.district,
            state=payload.state or addr.state,
            country=payload.country or addr.country,
            address_type=payload.address_type or addr.address_type,
        )
        run_record = await container.service.execute(WorkflowType.ADDRESS, verify_req.model_dump(mode="json"))
        res = run_record.results.get("address_guardian")
        if not res:
            raise HTTPException(status_code=500, detail="Address re-validation failed")

        validation_status = res.data.get("status", "needs_correction")
        validation_explanation = res.data.get("reason", "")

        if validation_status != "valid":
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Re-validation failed. Please correct details.",
                    "errors": res.data.get("field_errors"),
                    "suggested": res.data.get("suggested_address"),
                    "explanation": validation_explanation,
                },
            )

    with container.repository._session() as db_session:
        db_addr = db_session.get(Address, address_id)
        for k, v in payload.model_dump(exclude_unset=True).items():
            if k in {"is_default", "verification_session_id"}:
                continue
            setattr(db_addr, k, v)
        if fields_changed:
            db_addr.raw_text = res.data["normalized_address"]
            db_addr.latitude = res.data["latitude"]
            db_addr.longitude = res.data["longitude"]
            db_addr.digipin = res.data["digipin"]
            db_addr.verified_bool = True
        if lookup_res:
            db_addr.phone = lookup_res["normalized_number"]
            db_addr.phone_verified = False
            db_addr.phone_lookup_validated = True
            db_addr.lookup_status = "lookup_validated"
            db_addr.lookup_data = lookup_res
        db_addr.validation_status = validation_status
        db_addr.validation_explanation = validation_explanation
        db_session.commit()

    if payload.is_default:
        container.repository.set_default_address(user.id, address_id)

    updated_addr = container.repository.get_address(address_id)
    return _address_out(updated_addr)


@router.delete("/addresses/{address_id}")
async def delete_address_endpoint(
    address_id: str,
    user: Annotated[User, Depends(_require_buyer)],
    container=Depends(get_container),
):
    addr = container.repository.get_address(address_id)
    if not addr or addr.user_id != user.id:
        raise HTTPException(status_code=404, detail="Address not found")
    try:
        container.repository.delete_address(address_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Address deleted successfully"}


@router.post("/addresses/{address_id}/default")
async def make_address_default(
    address_id: str,
    user: Annotated[User, Depends(_require_buyer)],
    container=Depends(get_container),
):
    addr = container.repository.get_address(address_id)
    if not addr or addr.user_id != user.id:
        raise HTTPException(status_code=404, detail="Address not found")
    container.repository.set_default_address(user.id, address_id)
    return {"message": "Address set as default"}


@router.post("/payments/razorpay-webhook")
async def razorpay_webhook(
    request: Request,
    cfg: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    signature = request.headers.get("X-Razorpay-Signature", "")
    body = await request.body()

    if not cfg.razorpay_webhook_secret:
        raise HTTPException(status_code=503, detail="Razorpay webhook verification is not configured")
    expected = hmac.new(cfg.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    event = payload.get("event")
    payload_hash = hashlib.sha256(body).hexdigest()
    event_id = request.headers.get("X-Razorpay-Event-Id") or payload.get("id") or payload_hash
    existing_event = (
        session.execute(select(RazorpayWebhookEvent).where(RazorpayWebhookEvent.event_id == event_id)).scalars().first()
    )
    if existing_event:
        return {"status": "ok", "duplicate": True}

    event_record = RazorpayWebhookEvent(
        event_id=event_id,
        event_type=event or "unknown",
        payload_hash=payload_hash,
        status="processing",
    )
    session.add(event_record)
    session.flush()

    finalized_order: Order | None = None
    if event in ("order.paid", "payment.captured"):
        payment_payload = payload.get("payload", {}).get("payment", {}).get("entity", {})
        razorpay_order_id = payment_payload.get("order_id")
        razorpay_payment_id = payment_payload.get("id")

        if razorpay_order_id and razorpay_payment_id:
            payment = (
                session.execute(select(Payment).where(Payment.provider_order_id == razorpay_order_id)).scalars().first()
            )
            if payment:
                order = session.get(Order, payment.order_id)
                if order and order.status == OrderStatus.CART:
                    if _finalize_prepaid_order(session, order, payment, razorpay_payment_id):
                        finalized_order = order
    elif event == "payment.failed":
        payment_payload = payload.get("payload", {}).get("payment", {}).get("entity", {})
        razorpay_order_id = payment_payload.get("order_id")
        payment = (
            session.execute(select(Payment).where(Payment.provider_order_id == razorpay_order_id)).scalars().first()
        )
        if payment and payment.status != "captured":
            payment.status = "failed"
            payment.failure_reason = payment_payload.get("error_description") or "provider_reported_failure"

    event_record.status = "processed"
    event_record.processed_at = datetime.now(UTC)
    session.commit()
    if finalized_order:
        publish_event(
            ORDER_PLACED_STREAM,
            {"order_id": finalized_order.id, "buyer_id": finalized_order.buyer_id},
        )
    return {"status": "ok", "duplicate": False}


class SupportLogRequest(BaseModel):
    channel: Literal["call", "email"]


@router.get("/support/info")
async def get_support_info():
    return {"phone": "+91-9748572321", "email": "manyagupta.123.ag@gmail.com"}


@router.post("/support/log")
async def log_support_interaction(
    payload: SupportLogRequest,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    interaction = SupportInteraction(
        user_id=user.id,
        channel=payload.channel,
    )
    session.add(interaction)
    session.commit()
    return {"status": "logged", "id": interaction.id}
