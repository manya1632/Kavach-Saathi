from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from kavach_saathi.auth import require_role
from kavach_saathi.config import Settings, get_settings
from kavach_saathi.db.base import get_session
from kavach_saathi.db.models import (
    Order,
    OrderItem,
    OrderStatusHistory,
    Product,
    ProductVariant,
    SellerProfile,
    SellerTrustScoreRecord,
    User,
)
from kavach_saathi.digilocker import DigiLockerNotConfigured, build_authorize_url, exchange_code
from kavach_saathi.models import (
    KYCCompleteRequest,
    KYCStartResponse,
    SellerOrderStatusUpdate,
    SellerProductCreate,
    SellerProductUpdate,
    SellerVariantCreate,
)
from kavach_saathi.order_status import InvalidOrderTransition, OrderStatus, validate_transition

router = APIRouter()
_require_seller = require_role("seller")


def _seller_profile(session: Session, user: User) -> SellerProfile:
    profile = session.get(SellerProfile, user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Seller profile not found")
    return profile


@router.get("/seller/profile")
async def seller_profile(
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    profile = _seller_profile(session, user)
    trust = session.get(SellerTrustScoreRecord, user.id)
    return {
        "user_id": user.id,
        "name": user.name,
        "business_name": profile.business_name,
        "digilocker_kyc_status": profile.digilocker_kyc_status,
        "gstin": profile.gstin,
        "trust_score": profile.trust_score,
        "verified": profile.verified,
        "catalog_accuracy_score": trust.catalog_accuracy_score if trust else None,
        "rto_rate": trust.rto_rate if trust else None,
        "fraud_flags": trust.fraud_flags if trust else None,
    }


@router.post("/seller/kyc/start", response_model=KYCStartResponse)
async def kyc_start(
    redirect_uri: str,
    user: Annotated[User, Depends(_require_seller)],
    cfg: Settings = Depends(get_settings),
):
    try:
        url = build_authorize_url(cfg, redirect_uri=redirect_uri, state=user.id)
    except DigiLockerNotConfigured:
        return KYCStartResponse(authorize_url=None, configured=False, status="not_configured")
    return KYCStartResponse(authorize_url=url, configured=True, status="pending")


@router.post("/seller/kyc/complete")
async def kyc_complete(
    payload: KYCCompleteRequest,
    user: Annotated[User, Depends(_require_seller)],
    cfg: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    profile = _seller_profile(session, user)
    try:
        tokens = await exchange_code(cfg, code=payload.code, redirect_uri=payload.redirect_uri)
    except DigiLockerNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    profile.digilocker_kyc_status = "verified" if tokens.access_token else "failed"
    session.flush()
    return {"digilocker_kyc_status": profile.digilocker_kyc_status}


@router.get("/seller/products")
async def list_seller_products(
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    products = session.execute(
        select(Product).where(Product.seller_id == user.id).order_by(Product.created_at.desc())
    ).scalars().all()
    variants_by_product: dict[str, list[ProductVariant]] = {}
    for variant in session.execute(
        select(ProductVariant).where(ProductVariant.product_id.in_([p.id for p in products]))
    ).scalars():
        variants_by_product.setdefault(variant.product_id, []).append(variant)
    return [
        {
            "id": product.id,
            "title": product.title,
            "category": product.category,
            "status": product.status,
            "price": product.price,
            "spec_source": product.spec_source,
            "stolen_photo_flag": product.stolen_photo_flag,
            "variants": [
                {"id": v.id, "size": v.size, "stock_qty": v.stock_qty, "price": v.price}
                for v in variants_by_product.get(product.id, [])
            ],
        }
        for product in products
    ]


@router.post("/seller/products", status_code=201)
async def create_seller_product(
    payload: SellerProductCreate,
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    _seller_profile(session, user)
    product_id = f"P-{uuid4().hex[:10].upper()}"
    product = Product(
        id=product_id,
        seller_id=user.id,
        title=payload.title,
        brand=payload.brand,
        description=payload.description,
        category=payload.category,
        audience=payload.audience,
        occasion=payload.occasion,
        material=payload.material,
        price=payload.price,
        original_price=payload.original_price,
        status="draft",
        spec_json=payload.seller_specs,
        spec_source="seller_form",
        media_primary=payload.image_keys[0],
    )
    session.add(product)
    session.flush()
    return {
        "id": product.id,
        "seller_id": product.seller_id,
        "status": product.status,
        "image_keys": payload.image_keys,
        "next_step": "POST /v1/listings/analyze with this product_id to run Agent 1 + Agent 2",
    }


@router.patch("/seller/products/{product_id}")
async def update_seller_product(
    product_id: str,
    payload: SellerProductUpdate,
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status_code=404, detail="Product not found")
    if payload.price is not None:
        product.price = payload.price
    if payload.status is not None:
        product.status = payload.status
    session.flush()
    return {"id": product.id, "price": product.price, "status": product.status}


@router.post("/seller/products/{product_id}/variants", status_code=201)
async def add_seller_variant(
    product_id: str,
    payload: SellerVariantCreate,
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status_code=404, detail="Product not found")
    variant_id = f"{product_id}-{payload.size}"
    existing = session.get(ProductVariant, variant_id)
    price = payload.price if payload.price is not None else product.price
    if existing:
        existing.stock_qty = payload.stock_qty
        existing.price = price
    else:
        session.add(
            ProductVariant(
                id=variant_id,
                product_id=product_id,
                size=payload.size,
                sku=variant_id,
                stock_qty=payload.stock_qty,
                price=price,
            )
        )
    session.flush()
    return {"id": variant_id, "size": payload.size, "stock_qty": payload.stock_qty, "price": price}


@router.get("/seller/orders")
async def list_seller_orders(
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    items = session.execute(select(OrderItem).where(OrderItem.seller_id == user.id)).scalars().all()
    order_ids = list({item.order_id for item in items})
    orders_by_id = {
        order.id: order
        for order in session.execute(select(Order).where(Order.id.in_(order_ids))).scalars()
    }
    return [
        {
            "order_id": item.order_id,
            "product_id": item.product_id,
            "size": item.size,
            "qty": item.qty,
            "price_at_purchase": item.price_at_purchase,
            "status": orders_by_id[item.order_id].status if item.order_id in orders_by_id else None,
        }
        for item in items
    ]


@router.patch("/seller/orders/{order_id}/status")
async def update_seller_order_status(
    order_id: str,
    payload: SellerOrderStatusUpdate,
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    owns_item = session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id, OrderItem.seller_id == user.id)
    ).scalars().first()
    if not owns_item:
        raise HTTPException(status_code=404, detail="Order not found for this seller")
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        current = OrderStatus(order.status)
        target = OrderStatus(payload.status)
        validate_transition(current, target)
    except (ValueError, InvalidOrderTransition) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    order.status = target
    order.updated_at = datetime.now(UTC)
    session.add(OrderStatusHistory(order_id=order_id, status=target, actor="seller"))
    session.flush()
    return {"order_id": order_id, "status": order.status}
