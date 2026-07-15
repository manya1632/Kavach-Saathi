from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from kavach_saathi.auth import require_role
from kavach_saathi.config import Settings, get_settings
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
    ReturnRecord,
    Review,
    User,
    WishlistItem,
)
from kavach_saathi.events import ORDER_PLACED_STREAM, REVIEW_SUBMITTED_STREAM, publish_event
from kavach_saathi.models import (
    CartItemAdd,
    CartItemUpdate,
    OrderCreateRequest,
    PaymentVerifyRequest,
    ReturnCreateRequest,
    ReviewCreateRequest,
)
from kavach_saathi.order_status import OrderStatus
from kavach_saathi.providers.razorpay_provider import RazorpayClient, RazorpayUnavailable

router = APIRouter()
_require_buyer = require_role("buyer")


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
    existing = session.execute(
        select(CartItem).where(
            CartItem.user_id == user.id, CartItem.product_variant_id == payload.product_variant_id
        )
    ).scalars().first()
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
    rows = session.execute(
        select(WishlistItem).where(WishlistItem.user_id == user.id).order_by(WishlistItem.created_at.desc())
    ).scalars().all()
    items = []
    for row in rows:
        product = session.get(Product, row.product_id)
        if product:
            items.append({"id": row.id, "created_at": row.created_at, "product": _product_summary(product)})
    return {"items": items}


@router.post("/wishlist/{product_id}", status_code=201)
async def add_wishlist(product_id: str, user: Annotated[User, Depends(_require_buyer)], session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product or product.status != "active":
        raise HTTPException(status_code=404, detail="Product not found")
    item = session.execute(select(WishlistItem).where(
        WishlistItem.user_id == user.id, WishlistItem.product_id == product_id
    )).scalars().first()
    if item is None:
        item = WishlistItem(user_id=user.id, product_id=product_id)
        session.add(item)
        session.flush()
    return {"id": item.id, "product": _product_summary(product)}


@router.delete("/wishlist/{product_id}")
async def remove_wishlist(product_id: str, user: Annotated[User, Depends(_require_buyer)], session: Session = Depends(get_session)):
    item = session.execute(select(WishlistItem).where(
        WishlistItem.user_id == user.id, WishlistItem.product_id == product_id
    )).scalars().first()
    if item:
        session.delete(item)
        session.flush()
    return {"removed": bool(item), "product_id": product_id}


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

    cart_rows = session.execute(select(CartItem).where(CartItem.user_id == user.id)).scalars().all()
    if not cart_rows:
        raise HTTPException(status_code=400, detail="Cart is empty")

    razorpay_order: dict | None = None
    if payload.payment_mode == "prepaid" and not RazorpayClient(cfg).is_configured:
        # Fail honestly before writing anything if Razorpay isn't configured -- never
        # silently downgrade a buyer's chosen payment method to a fake success.
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
    order = Order(
        id=order_id,
        buyer_id=user.id,
        address_id=address.id,
        status=OrderStatus.PLACED,
        total_amount=total_amount,
        payment_mode=payload.payment_mode,
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
        variant.stock_qty -= cart_item.qty
        session.delete(cart_item)

    session.add(OrderStatusHistory(order_id=order_id, status=OrderStatus.PLACED, actor="system"))

    if payload.payment_mode == "prepaid":
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
                amount=total_amount,
            )
        )
    # Commit before publishing: the Redis Streams consumer that reacts to this event
    # can pick it up and query the order in a separate connection almost immediately,
    # and a flush alone is only visible inside this transaction -- publishing before
    # commit let the consumer race the commit and 404 on an order it can't see yet
    # (observed live as a DataNotFoundError in Agent 7's background worker).
    session.commit()

    if payload.payment_mode == "cod":
        publish_event(ORDER_PLACED_STREAM, {"order_id": order_id, "buyer_id": user.id})

    return {
        "order_id": order_id,
        "status": order.status,
        "total_amount": total_amount,
        "payment_mode": payload.payment_mode,
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
        session.flush()
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    payment.status = "captured"
    payment.transaction_ref = payload.razorpay_payment_id
    # Commit before publishing -- see the matching comment in create_order() above;
    # the same consumer-races-the-commit failure applies here for the prepaid path.
    session.commit()
    publish_event(ORDER_PLACED_STREAM, {"order_id": order_id, "buyer_id": user.id})
    return {"order_id": order_id, "payment_status": payment.status}


@router.get("/orders")
async def list_my_orders(user: Annotated[User, Depends(_require_buyer)], session: Session = Depends(get_session)):
    orders = session.execute(
        select(Order).where(Order.buyer_id == user.id).order_by(Order.created_at.desc())
    ).scalars().all()
    order_ids = [o.id for o in orders]
    items_by_order: dict[str, list[OrderItem]] = {}
    if order_ids:
        for item in session.execute(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).scalars():
            items_by_order.setdefault(item.order_id, []).append(item)
    return [
        {
            "id": order.id,
            "status": order.status,
            "total_amount": order.total_amount,
            "payment_mode": order.payment_mode,
            "created_at": order.created_at,
            "items": [
                {"product_id": i.product_id, "product_name": session.get(Product, i.product_id).title,
                 "image_url": session.get(Product, i.product_id).media_primary,
                 "size": i.size, "qty": i.qty, "price_at_purchase": i.price_at_purchase}
                for i in items_by_order.get(order.id, [])
            ],
        }
        for order in orders
    ]


@router.get("/returns")
async def list_my_returns(user: Annotated[User, Depends(_require_buyer)], session: Session = Depends(get_session)):
    rows = session.execute(
        select(ReturnRecord).where(ReturnRecord.buyer_id == user.id).order_by(ReturnRecord.created_at.desc())
    ).scalars().all()
    return [{"id": row.id, "order_id": row.order_id, "reason": row.reason,
             "status": row.decision or "pending_evidence", "decision": row.decision,
             "confidence_score": row.confidence_score, "created_at": row.created_at} for row in rows]


@router.post("/returns", status_code=201)
async def create_return_request(payload: ReturnCreateRequest, user: Annotated[User, Depends(_require_buyer)], session: Session = Depends(get_session)):
    order = session.get(Order, payload.order_id)
    if not order or order.buyer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(status_code=409, detail="Returns can only be requested after delivery")
    existing = session.execute(select(ReturnRecord).where(ReturnRecord.order_id == order.id)).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="A return already exists for this order")
    record = ReturnRecord(
        id=f"RT-{uuid4().hex[:10].upper()}", order_id=order.id, buyer_id=user.id,
        reason=payload.reason, decision=None,
    )
    session.add(record)
    order.status = OrderStatus.RETURN_INITIATED
    session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.RETURN_INITIATED, actor="user"))
    session.flush()
    return {"id": record.id, "order_id": record.order_id, "reason": record.reason, "status": "pending_evidence"}


@router.post("/reviews", status_code=201)
async def create_review(
    payload: ReviewCreateRequest,
    user: Annotated[User, Depends(_require_buyer)],
    session: Session = Depends(get_session),
):
    product = session.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if payload.order_id:
        owns_order = session.execute(
            select(OrderItem).where(
                OrderItem.order_id == payload.order_id, OrderItem.product_id == payload.product_id
            )
        ).scalars().first()
        order = session.get(Order, payload.order_id)
        if not owns_order or not order or order.buyer_id != user.id:
            raise HTTPException(status_code=403, detail="This order doesn't match your purchase of this product")

    review_id = f"RV-{uuid4().hex[:10].upper()}"
    review = Review(
        id=review_id,
        product_id=payload.product_id,
        buyer_id=user.id,
        rating=payload.rating,
        text=payload.text,
        media=payload.image_key,
        is_hidden_by_agent=False,
    )
    session.add(review)

    total_rating = product.rating * product.review_count + payload.rating
    product.review_count += 1
    product.rating = round(total_rating / product.review_count, 2)
    # Commit before publishing -- see the matching comment in create_order() above;
    # Agent 4's review-truth consumer can otherwise query this review before it's
    # durably committed.
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
