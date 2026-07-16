import asyncio
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
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
    ProductImage,
    ProductSpecification,
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
    SellerProductInitialize,
    SellerProductPublish,
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
    products = (
        session.execute(select(Product).where(Product.seller_id == user.id).order_by(Product.created_at.desc()))
        .scalars()
        .all()
    )
    variants_by_product: dict[str, list[ProductVariant]] = {}
    for variant in session.execute(
        select(ProductVariant).where(ProductVariant.product_id.in_([p.id for p in products]))
    ).scalars():
        variants_by_product.setdefault(variant.product_id, []).append(variant)
    specs_by_product: dict[str, list[ProductSpecification]] = {}
    if products:
        for spec in session.execute(
            select(ProductSpecification).where(ProductSpecification.product_id.in_([p.id for p in products]))
        ).scalars():
            specs_by_product.setdefault(spec.product_id, []).append(spec)
    return [
        {
            "id": product.id,
            "title": product.title,
            "category": product.category,
            "status": product.status,
            "price": product.price,
            "spec_source": product.spec_source,
            "stolen_photo_flag": product.stolen_photo_flag,
            "specifications": [
                {"key": s.key, "label": s.label, "value": s.value_json, "unit": s.unit}
                for s in specs_by_product.get(product.id, [])
            ],
            "size_chart": product.size_chart,
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
    structured_specs = {item.key: item.value for item in payload.specifications}
    size_chart = {row.size: row.dimensions_cm for row in payload.size_chart}
    total_stock = sum(row.stock_qty for row in payload.size_chart) if payload.size_chart else payload.stock_qty
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
        spec_json={**payload.seller_specs, **structured_specs},
        spec_source="seller_form",
        size_chart=size_chart,
        stock=total_stock,
        media_primary=payload.image_keys[0],
    )
    session.add(product)
    session.flush()
    for item in payload.specifications:
        session.add(
            ProductSpecification(
                product_id=product_id,
                key=item.key,
                label=item.label,
                value_json=item.value,
                value_type=item.value_type,
                unit=item.unit,
                comparison_group=item.comparison_group,
                comparable=item.comparable,
                source="seller_form",
                verified=False,
            )
        )
    for angle in ("front", "back", "left", "right"):
        session.add(
            ProductImage(
                id=f"{product_id}-{angle}",
                product_id=product_id,
                url=payload.image_keys[0],
                type="seller_upload",
                angle=angle,
                is_verified=False,
            )
        )
    if payload.size_chart:
        for row in payload.size_chart:
            variant_id = f"{product_id}-{row.size}"
            session.add(
                ProductVariant(
                    id=variant_id,
                    product_id=product_id,
                    size=row.size,
                    sku=variant_id,
                    stock_qty=row.stock_qty,
                    price=row.price or payload.price,
                )
            )
    else:
        session.add(
            ProductVariant(
                id=f"{product_id}-STD",
                product_id=product_id,
                size="Standard",
                sku=f"{product_id}-STD",
                stock_qty=payload.stock_qty,
                price=payload.price,
            )
        )
    session.flush()
    return {
        "id": product.id,
        "seller_id": product.seller_id,
        "status": product.status,
        "image_keys": payload.image_keys,
        "specifications": len(payload.specifications),
        "variants": len(payload.size_chart) or 1,
        "next_step": "POST /v1/listings/analyze with this product_id to run Agent 1 + Agent 2",
    }


def _run_workflow_in_background(coro_factory) -> None:
    def _run() -> None:
        try:
            asyncio.run(coro_factory())
        except Exception:
            logging.getLogger(__name__).exception("Background workflow task failed")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


@router.post("/seller/products/initialize", status_code=201)
async def initialize_seller_product(
    payload: SellerProductInitialize,
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    from kavach_saathi.container import get_container
    from kavach_saathi.media_storage import _local_path
    from kavach_saathi.models import WorkflowType

    _seller_profile(session, user)
    settings = get_settings()

    all_keys = payload.product_image_keys + payload.catalogue_image_keys
    for key in all_keys:
        suffix = Path(key).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(
                status_code=400,
                detail=f"Image key '{key}' has invalid extension. Only JPG, JPEG, PNG, WEBP are allowed."
            )

        if settings.is_live:
            import boto3
            s3 = boto3.client("s3", region_name=settings.aws_region)
            try:
                head = s3.head_object(Bucket=settings.media_bucket, Key=key)
                size = head.get("ContentLength", 0)
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image key '{key}' not found or inaccessible in S3"
                ) from exc
        else:
            try:
                path = _local_path(key, settings)
                size = path.stat().st_size
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image key '{key}' not found locally"
                ) from exc

        if size <= 0:
            raise HTTPException(status_code=400, detail=f"Image key '{key}' is empty")
        if size > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"Image key '{key}' exceeds maximum size of 10MB")

    product_id = f"P-{uuid4().hex[:10].upper()}"
    primary_image_key = payload.product_image_keys[0]

    product = Product(
        id=product_id,
        seller_id=user.id,
        title="Draft Image-First Listing",
        brand=None,
        description="",
        category="Kurti, Saree & Lehenga",
        price=0.0,
        original_price=0.0,
        status="extracting",
        product_images=payload.product_image_keys,
        catalogue_images=payload.catalogue_image_keys,
        media_primary=primary_image_key,
        stock=0,
    )
    session.add(product)

    for angle in ("front", "back", "left", "right"):
        session.add(
            ProductImage(
                id=f"{product_id}-{angle}",
                product_id=product_id,
                url=primary_image_key,
                type="seller_upload",
                angle=angle,
                is_verified=False,
            )
        )

    session.add(
        ProductVariant(
            id=f"{product_id}-STD",
            product_id=product_id,
            size="Standard",
            sku=f"{product_id}-STD",
            stock_qty=0,
            price=0.0,
        )
    )
    session.flush()
    session.commit()

    container = get_container()
    data = {
        "seller_id": user.id,
        "product_id": product_id,
        "image_keys": [primary_image_key],
        "seller_specs": {},
    }

    record = container.service.start(
        WorkflowType.LISTING,
        data,
    )

    if settings.is_live and settings.state_machine_arn:
        import boto3
        step_functions = boto3.client("stepfunctions", region_name=settings.aws_region)
        step_functions.start_execution(
            stateMachineArn=settings.state_machine_arn,
            name=str(record.run_id),
            input=json.dumps(
                {
                    "run_id": str(record.run_id),
                    "order_id": None,
                }
            ),
        )
    else:
        _run_workflow_in_background(
            lambda: container.service.resume(record.run_id)
        )

    return {
        "product_id": product_id,
        "run_id": str(record.run_id),
        "status": "extracting"
    }


@router.post("/seller/products/{product_id}/publish")
async def publish_seller_product(
    product_id: str,
    payload: SellerProductPublish,
    user: Annotated[User, Depends(_require_seller)],
    session: Session = Depends(get_session),
):
    _seller_profile(session, user)
    product = session.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status_code=404, detail="Product not found")

    if product.status == "inconsistent":
        raise HTTPException(status_code=400, detail="Cannot publish listing with unresolved spec conflicts")

    product.title = payload.title
    product.brand = payload.brand
    product.description = payload.description
    product.category = payload.category
    product.audience = payload.audience
    product.occasion = payload.occasion
    product.material = payload.material
    product.price = payload.price
    product.original_price = payload.original_price
    product.seller_corrections = payload.seller_corrections
    product.activation_timestamp = datetime.now(UTC)
    product.status = "active"

    # Save specifications
    structured_specs = {item.key: item.value for item in payload.specifications}
    product.spec_json = {**payload.seller_specs, **structured_specs}

    # Delete existing specifications for this product to prevent duplicates/conflicts
    from sqlalchemy import delete
    session.execute(delete(ProductSpecification).where(ProductSpecification.product_id == product_id))

    for item in payload.specifications:
        session.add(
            ProductSpecification(
                product_id=product_id,
                key=item.key,
                label=item.label,
                value_json=item.value,
                value_type=item.value_type,
                unit=item.unit,
                comparison_group=item.comparison_group,
                comparable=item.comparable,
                source="seller_form",
                verified=False,
            )
        )

    # Delete existing variants
    session.execute(delete(ProductVariant).where(ProductVariant.product_id == product_id))

    size_chart = {row.size: row.dimensions_cm for row in payload.size_chart}
    product.size_chart = size_chart
    total_stock = sum(row.stock_qty for row in payload.size_chart) if payload.size_chart else payload.stock_qty
    product.stock = total_stock

    if payload.size_chart:
        for row in payload.size_chart:
            variant_id = f"{product_id}-{row.size}"
            session.add(
                ProductVariant(
                    id=variant_id,
                    product_id=product_id,
                    size=row.size,
                    sku=variant_id,
                    stock_qty=row.stock_qty,
                    price=row.price or payload.price,
                )
            )
    else:
        session.add(
            ProductVariant(
                id=f"{product_id}-STD",
                product_id=product_id,
                size="Standard",
                sku=f"{product_id}-STD",
                stock_qty=payload.stock_qty,
                price=payload.price,
            )
        )

    session.flush()
    session.commit()
    return {"id": product.id, "status": product.status}



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
        order.id: order for order in session.execute(select(Order).where(Order.id.in_(order_ids))).scalars()
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
    owns_item = (
        session.execute(select(OrderItem).where(OrderItem.order_id == order_id, OrderItem.seller_id == user.id))
        .scalars()
        .first()
    )
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
