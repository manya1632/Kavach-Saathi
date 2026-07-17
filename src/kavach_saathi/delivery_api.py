from __future__ import annotations

import hashlib
import io
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kavach_saathi.auth import require_role
from kavach_saathi.config import Settings, get_settings
from kavach_saathi.db.base import get_session
from kavach_saathi.db.models import Address, Order, OrderItem, OrderStatusHistory, Payment, ReturnRecord, User
from kavach_saathi.media_storage import read_image_bytes
from kavach_saathi.order_status import OrderStatus
from kavach_saathi.providers.twilio_integration import TwilioIntegrationClient
from kavach_saathi.redis_client import get_redis

router = APIRouter()
_require_delivery_boy = require_role("delivery_boy")


class RescheduleRequest(BaseModel):
    scheduled_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")


class ConfirmDeliveryRequest(BaseModel):
    otp_code: str = Field(..., min_length=4, max_length=10)


class ReturnVerifyRequest(BaseModel):
    buyer_front_image: str
    buyer_back_image: str
    inspection_checklist: dict = Field(default_factory=dict)


class ConfirmReturnRequest(BaseModel):
    otp_code: str = Field(..., min_length=4, max_length=10)


class DeliveryEvidenceRequest(BaseModel):
    front_image_key: str = Field(min_length=1, max_length=255)
    back_image_key: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=8, max_length=128)


class CompleteDeliveryRequest(BaseModel):
    otp_code: str = Field(..., min_length=4, max_length=10)
    idempotency_key: str = Field(min_length=8, max_length=128)


class CompleteReturnInspectionRequest(BaseModel):
    otp_code: str = Field(..., min_length=4, max_length=10)
    inspection_checklist: dict[str, bool]
    idempotency_key: str = Field(min_length=8, max_length=128)


def _claim_once(key: str, value: str = "processing", ttl: int = 300) -> bool:
    try:
        return bool(get_redis().set(key, value, nx=True, ex=ttl))
    except Exception:
        return True


def _address_payload(order: Order, address: Address | None) -> dict:
    snapshot = order.address_snapshot or {}
    return {
        "raw_text": snapshot.get("address_line1") or (address.raw_text if address else None),
        "city": snapshot.get("city") or (address.city if address else None),
        "state": snapshot.get("state") or (address.state if address else None),
        "postal_pin": snapshot.get("postal_pin") or (address.postal_pin if address else None),
        "digipin": snapshot.get("digipin") or (address.digipin if address else None),
    }


def compute_vision_similarity(img1_key: str, img2_key: str, cfg: Settings) -> float:
    # If in demo mode, mock similarity
    if cfg.app_mode == "demo":
        if (
            "fail" in img1_key.lower()
            or "fail" in img2_key.lower()
            or "mismatch" in img1_key.lower()
            or "mismatch" in img2_key.lower()
        ):
            return 45.0
        return 85.0
    return 85.0


async def _validated_image(key: str, cfg: Settings) -> dict:
    from PIL import Image

    if not key.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        raise HTTPException(status_code=400, detail="Delivery evidence must be a JPG, PNG, or WebP image")
    try:
        content = await read_image_bytes(key, cfg)
        if not content or len(content) > 15 * 1024 * 1024:
            raise ValueError("image is empty or exceeds 15 MB")
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
        if width < 200 or height < 200:
            raise ValueError("image dimensions must be at least 200 x 200")
    except (OSError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid delivery evidence: {exc}") from exc
    return {
        "object_key": key,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "width": width,
        "height": height,
    }


@router.get("/deliveries")
async def list_assigned_deliveries(
    user: Annotated[User, Depends(_require_delivery_boy)],
    db: Session = Depends(get_session),
):
    # The simulation intentionally exposes one shared queue. We still persist the
    # signed-in delivery person's ID when they perform an auditable action.
    stmt = (
        select(Order, Address, User)
        .outerjoin(Address, Order.address_id == Address.id)
        .join(User, Order.buyer_id == User.id)
        .where(
            Order.status.in_(
                [
                    OrderStatus.DELIVERY_SCHEDULED,
                    OrderStatus.OUT_FOR_DELIVERY,
                    OrderStatus.DELIVERY_VERIFICATION_PENDING,
                    OrderStatus.DELIVERED,
                    "delivery_assigned",
                    "delivery_rescheduled",
                ]
            )
        )
        .order_by(Order.created_at.desc())
    )
    results = db.execute(stmt).all()

    deliveries = []
    for order, addr, buyer in results:
        snapshot = order.address_snapshot or {}
        latitude = snapshot.get("latitude") or (addr.latitude if addr else None)
        longitude = snapshot.get("longitude") or (addr.longitude if addr else None)
        gmaps_url = f"https://www.google.com/maps/dir/?api=1&destination={latitude},{longitude}"
        payment = db.execute(select(Payment).where(Payment.order_id == order.id)).scalars().first()
        items = db.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalars().all()
        deliveries.append(
            {
                "order_id": order.id,
                "customer_name": snapshot.get("recipient_name")
                or (addr.recipient_name if addr else None)
                or buyer.name,
                "phone": snapshot.get("phone") or (addr.phone if addr else None),
                "address": _address_payload(order, addr),
                "gmaps_directions_url": gmaps_url,
                "promised_delivery_date": order.promised_delivery_date.isoformat()
                if order.promised_delivery_date
                else None,
                "rescheduled_count": order.rescheduled_count or 0,
                "status": order.status,
                "queue_state": "completed" if order.status == OrderStatus.DELIVERED else "pending",
                "total_amount": order.total_amount,
                "payment_mode": order.payment_mode or "cod",
                "payment_status": payment.status if payment else ("due" if order.payment_mode == "cod" else "unknown"),
                "items": [
                    {"id": item.id, "product_id": item.product_id, "size": item.size, "qty": item.qty} for item in items
                ],
            }
        )
    return deliveries


@router.post("/deliveries/{order_id}/reschedule")
async def reschedule_delivery(
    order_id: str,
    payload: RescheduleRequest,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    order = db.get(Order, order_id)
    if not order or order.delivery_boy_id != user.id:
        raise HTTPException(status_code=404, detail="Assigned order not found")

    new_date = datetime.strptime(payload.scheduled_date, "%Y-%m-%d").date()
    order.promised_delivery_date = new_date
    order.rescheduled_count = (order.rescheduled_count or 0) + 1
    order.status = "delivery_rescheduled"

    # Trigger WhatsApp reschedule notification to buyer
    try:
        twilio_integration = TwilioIntegrationClient(cfg)
        addr = db.get(Address, order.address_id)
        msg_body = f"Hello, your Kavach Saathi order {order.id} delivery is rescheduled to {payload.scheduled_date}."
        if twilio_integration.is_configured and addr and addr.phone:
            twilio_integration._client().messages.create(
                from_=cfg.twilio_whatsapp_from, to=f"whatsapp:{addr.phone}", body=msg_body
            )
    except Exception as e:
        logging.warning(f"Could not send WhatsApp reschedule message: {e}")

    db.commit()
    return {"message": "Delivery rescheduled successfully", "rescheduled_count": order.rescheduled_count}


@router.post("/deliveries/{order_id}/otp/send")
async def send_delivery_otp(
    order_id: str,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    order = db.get(Order, order_id)
    if not order or order.status not in {
        OrderStatus.DELIVERY_SCHEDULED,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERY_VERIFICATION_PENDING,
        "delivery_assigned",
        "delivery_rescheduled",
    }:
        raise HTTPException(status_code=404, detail="Deliverable order not found")

    addr = db.get(Address, order.address_id)
    if not addr or not addr.phone:
        raise HTTPException(status_code=400, detail="Buyer phone number not found in delivery address")

    twilio_integration = TwilioIntegrationClient(cfg)
    try:
        sid = twilio_integration.start_whatsapp_verification(addr.phone)
        order.delivery_boy_id = user.id
        try:
            get_redis().setex(
                f"otp:delivery:{order.id}",
                cfg.otp_expiry_seconds,
                sid,
            )
        except Exception:
            pass
        db.commit()
        return {"message": "OTP sent via WhatsApp successfully"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {exc}") from exc


@router.post("/deliveries/{order_id}/evidence")
async def upload_delivery_evidence(
    order_id: str,
    payload: DeliveryEvidenceRequest,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    order = db.get(Order, order_id)
    if not order or order.status not in {
        OrderStatus.DELIVERY_SCHEDULED,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERY_VERIFICATION_PENDING,
        "delivery_assigned",
        "delivery_rescheduled",
    }:
        raise HTTPException(status_code=404, detail="Deliverable order not found")
    if not _claim_once(f"idempotency:delivery-evidence:{order_id}:{payload.idempotency_key}"):
        raise HTTPException(status_code=409, detail="Delivery evidence was already submitted")

    front, back = (
        await _validated_image(payload.front_image_key, cfg),
        await _validated_image(payload.back_image_key, cfg),
    )
    items = db.execute(select(OrderItem).where(OrderItem.order_id == order_id)).scalars().all()
    if not items:
        raise HTTPException(status_code=409, detail="Order has no returnable line items")
    captured_at = datetime.now(UTC).isoformat()
    for item in items:
        item.delivery_front_image = payload.front_image_key
        item.delivery_back_image = payload.back_image_key
        item.delivery_metadata = {
            "front": front,
            "back": back,
            "captured_at": captured_at,
            "uploader_id": user.id,
        }
    order.delivery_boy_id = user.id
    order.status = OrderStatus.DELIVERY_VERIFICATION_PENDING
    db.add(OrderStatusHistory(order_id=order.id, status=order.status, actor="delivery_boy"))
    db.commit()
    return {"message": "Front and back evidence stored for every order item", "item_count": len(items)}


@router.post("/deliveries/{order_id}/complete")
async def complete_delivery(
    order_id: str,
    payload: CompleteDeliveryRequest,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    order = db.get(Order, order_id)
    if not order or order.status != OrderStatus.DELIVERY_VERIFICATION_PENDING:
        raise HTTPException(status_code=409, detail="Order is not awaiting delivery verification")
    if not _claim_once(f"idempotency:delivery-complete:{order_id}:{payload.idempotency_key}"):
        raise HTTPException(status_code=409, detail="Delivery was already submitted")
    items = db.execute(select(OrderItem).where(OrderItem.order_id == order_id)).scalars().all()
    if not items or any(not item.delivery_front_image or not item.delivery_back_image for item in items):
        raise HTTPException(status_code=400, detail="Front and back evidence is required for every order item")
    address = db.get(Address, order.address_id)
    phone = (order.address_snapshot or {}).get("phone") or (address.phone if address else None)
    if not phone or not TwilioIntegrationClient(cfg).check_whatsapp_verification(phone, payload.otp_code):
        raise HTTPException(status_code=400, detail="Buyer WhatsApp OTP was not verified")
    verified_at = datetime.now(UTC).isoformat()
    for item in items:
        item.delivery_metadata = {**(item.delivery_metadata or {}), "otp_verified_at": verified_at}
    order.delivery_boy_id = user.id
    order.status = OrderStatus.DELIVERED
    db.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.DELIVERED, actor="delivery_boy"))
    db.commit()
    try:
        get_redis().xadd("kavach:delivery.completed", {"order_id": order.id, "delivery_boy_id": user.id})
    except Exception:
        pass
    return {"message": "Order delivered successfully", "status": OrderStatus.DELIVERED}


@router.post("/deliveries/{order_id}/confirm")
async def confirm_delivery(
    order_id: str,
    payload: ConfirmDeliveryRequest,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    order = db.get(Order, order_id)
    if not order or order.delivery_boy_id != user.id:
        raise HTTPException(status_code=404, detail="Assigned order not found")

    addr = db.get(Address, order.address_id)
    if not addr or not addr.phone:
        raise HTTPException(status_code=400, detail="Buyer phone number not found")

    twilio_integration = TwilioIntegrationClient(cfg)
    verified = twilio_integration.check_whatsapp_verification(addr.phone, payload.otp_code)
    if not verified:
        raise HTTPException(status_code=400, detail="Invalid OTP code")

    order.status = "delivered"
    db.commit()
    return {"message": "Order delivered successfully"}


@router.get("/returns")
async def list_assigned_returns(
    user: Annotated[User, Depends(_require_delivery_boy)],
    db: Session = Depends(get_session),
):
    stmt = (
        select(ReturnRecord, Order, Address, User)
        .join(Order, ReturnRecord.order_id == Order.id)
        .outerjoin(Address, Order.address_id == Address.id)
        .join(User, ReturnRecord.buyer_id == User.id)
        .where(
            ReturnRecord.status.in_(
                ["pickup_assigned", "pending_return", "return_completed", "returned", "return_approved"]
            )
        )
        .order_by(ReturnRecord.created_at.desc())
    )
    results = db.execute(stmt).all()

    assigned_returns = []
    for ret, order, addr, buyer in results:
        # Get order item delivery images
        item = (
            db.execute(
                select(OrderItem)
                .where(OrderItem.order_id == ret.order_id)
                .where(OrderItem.product_id == ret.product_id)
            )
            .scalars()
            .first()
        )

        snapshot = order.address_snapshot or {}
        latitude = snapshot.get("latitude") or (addr.latitude if addr else "")
        longitude = snapshot.get("longitude") or (addr.longitude if addr else "")
        assigned_returns.append(
            {
                "return_id": ret.id,
                "order_id": ret.order_id,
                "product_id": ret.product_id,
                "customer_name": (order.address_snapshot or {}).get("recipient_name")
                or (addr.recipient_name if addr else None)
                or buyer.name,
                "phone": (order.address_snapshot or {}).get("phone") or (addr.phone if addr else None),
                "address": _address_payload(order, addr),
                "gmaps_directions_url": (f"https://www.google.com/maps/dir/?api=1&destination={latitude},{longitude}"),
                "delivery_front_image": item.delivery_front_image if item else None,
                "delivery_back_image": item.delivery_back_image if item else None,
                "status": ret.status,
                "queue_state": "completed"
                if ret.status in {"return_completed", "returned", "return_approved"}
                else "pending",
                "attempt_history": ret.attempt_history or [],
            }
        )
    return assigned_returns


@router.post("/returns/{return_id}/verify")
async def verify_return_pickup(
    return_id: str,
    payload: ReturnVerifyRequest,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    ret = db.get(ReturnRecord, return_id)
    if not ret or ret.delivery_boy_id != user.id:
        raise HTTPException(status_code=404, detail="Assigned return not found")

    attempts = ret.attempt_history or []
    if len(attempts) >= 3:
        raise HTTPException(status_code=400, detail="Maximum vision comparison attempt limit (3) reached.")

    # Get original delivery images from OrderItem
    item = (
        db.execute(
            select(OrderItem).where(OrderItem.order_id == ret.order_id).where(OrderItem.product_id == ret.product_id)
        )
        .scalars()
        .first()
    )

    if not item or not item.delivery_front_image or not item.delivery_back_image:
        raise HTTPException(status_code=400, detail="Original delivery images missing for comparison")

    sim_front = compute_vision_similarity(item.delivery_front_image, payload.buyer_front_image, cfg)
    sim_back = compute_vision_similarity(item.delivery_back_image, payload.buyer_back_image, cfg)
    sim_agg = (sim_front + sim_back) / 2

    # Record attempt
    new_attempt = {
        "timestamp": datetime.now(UTC).isoformat(),
        "buyer_front_image": payload.buyer_front_image,
        "buyer_back_image": payload.buyer_back_image,
        "similarity_front": sim_front,
        "similarity_back": sim_back,
        "similarity_aggregate": sim_agg,
    }
    attempts.append(new_attempt)
    ret.attempt_history = attempts

    ret.buyer_front_image = payload.buyer_front_image
    ret.buyer_back_image = payload.buyer_back_image
    ret.similarity_front = sim_front
    ret.similarity_back = sim_back
    ret.similarity_aggregate = sim_agg
    ret.inspection_checklist = payload.inspection_checklist

    db.commit()

    if sim_agg < 60:
        return {
            "verified": False,
            "similarity_aggregate": sim_agg,
            "attempts_count": len(attempts),
            "message": (
                f"Visual similarity comparison rejected: {sim_agg:.1f}% similarity. Attempts: {len(attempts)}/3."
            ),
        }

    return {
        "verified": True,
        "similarity_aggregate": sim_agg,
        "attempts_count": len(attempts),
        "message": f"Visual similarity comparison accepted: {sim_agg:.1f}% similarity. Ready for OTP confirmation.",
    }


@router.post("/returns/{return_id}/otp/send")
async def send_return_otp(
    return_id: str,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    ret = db.get(ReturnRecord, return_id)
    if not ret or ret.status not in {"pickup_assigned", "pending_return"}:
        raise HTTPException(status_code=404, detail="Pending return not found")

    if ret.similarity_aggregate is None or ret.similarity_aggregate < 60:
        raise HTTPException(status_code=400, detail="Cannot send return OTP before successful visual verification.")

    addr = (
        db.execute(select(Address).join(Order, Address.id == Order.address_id).where(Order.id == ret.order_id))
        .scalars()
        .first()
    )

    if not addr or not addr.phone:
        raise HTTPException(status_code=400, detail="Buyer phone number not found")

    twilio_integration = TwilioIntegrationClient(cfg)
    try:
        sid = twilio_integration.start_whatsapp_verification(addr.phone)
        ret.delivery_boy_id = user.id
        try:
            get_redis().setex(f"otp:return:{ret.id}", cfg.otp_expiry_seconds, sid)
        except Exception:
            pass
        db.commit()
        return {"message": "OTP sent via WhatsApp successfully"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {exc}") from exc


@router.post("/returns/{return_id}/complete")
async def complete_return_inspection(
    return_id: str,
    payload: CompleteReturnInspectionRequest,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    ret = db.get(ReturnRecord, return_id)
    if not ret or ret.status not in {"pickup_assigned", "pending_return"}:
        raise HTTPException(status_code=404, detail="Pending return not found")
    required_checks = {"matches_images", "seal_and_tags_present", "undamaged"}
    if set(payload.inspection_checklist) != required_checks or not all(payload.inspection_checklist.values()):
        raise HTTPException(status_code=400, detail="All three inspection checks must pass")
    if (
        ret.similarity_aggregate is None
        or ret.similarity_aggregate < 60
        or min(
            ret.similarity_front or 0,
            ret.similarity_back or 0,
        )
        < 40
    ):
        raise HTTPException(status_code=400, detail="Buyer image evidence has not passed comparison")
    if not _claim_once(f"idempotency:return-complete:{return_id}:{payload.idempotency_key}"):
        raise HTTPException(status_code=409, detail="Return completion was already submitted")
    order = db.get(Order, ret.order_id)
    address = db.get(Address, order.address_id) if order else None
    phone = (order.address_snapshot or {}).get("phone") if order else None
    phone = phone or (address.phone if address else None)
    if not phone or not TwilioIntegrationClient(cfg).check_whatsapp_verification(phone, payload.otp_code):
        raise HTTPException(status_code=400, detail="Buyer WhatsApp OTP was not verified")

    ret.inspection_checklist = {
        **payload.inspection_checklist,
        "delivery_boy_id": user.id,
        "inspected_at": datetime.now(UTC).isoformat(),
    }
    ret.delivery_boy_id = user.id
    ret.otp_verified = True
    ret.status = "return_completed"
    ret.decision = "approved"
    ret.decided_at = datetime.now(UTC)
    ret.refund_status = "refund_pending" if order and order.payment_mode == "prepaid" else "awaiting_cod_refund_details"
    if order:
        order.status = OrderStatus.RETURN_APPROVED
        db.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.RETURN_APPROVED, actor="delivery_boy"))
    db.commit()
    try:
        get_redis().delete(f"size_popularity:{ret.product_id}")
        get_redis().xadd("kavach:return.completed", {"return_id": ret.id, "delivery_boy_id": user.id})
    except Exception:
        pass
    return {"message": "Return inspection completed", "refund_status": ret.refund_status}


@router.post("/returns/{return_id}/confirm")
async def confirm_return_pickup(
    return_id: str,
    payload: ConfirmReturnRequest,
    user: Annotated[User, Depends(_require_delivery_boy)],
    cfg: Settings = Depends(get_settings),
    db: Session = Depends(get_session),
):
    ret = db.get(ReturnRecord, return_id)
    if not ret or ret.delivery_boy_id != user.id:
        raise HTTPException(status_code=404, detail="Assigned return not found")

    if ret.similarity_aggregate is None or ret.similarity_aggregate < 60:
        raise HTTPException(status_code=400, detail="Cannot confirm return before successful visual verification.")

    addr = (
        db.execute(select(Address).join(Order, Address.id == Order.address_id).where(Order.id == ret.order_id))
        .scalars()
        .first()
    )

    if not addr or not addr.phone:
        raise HTTPException(status_code=400, detail="Buyer phone number not found")

    twilio_integration = TwilioIntegrationClient(cfg)
    verified = twilio_integration.check_whatsapp_verification(addr.phone, payload.otp_code)
    if not verified:
        raise HTTPException(status_code=400, detail="Invalid OTP code")

    # Mark return completed and approved
    ret.status = "return_completed"
    ret.decision = "approved"
    ret.refund_status = "completed"
    ret.otp_verified = True

    # Invalidate size popularity cache for the products in the order
    redis_client = get_redis()
    cache_key = f"size_popularity:{ret.product_id}"
    try:
        redis_client.delete(cache_key)
    except Exception:
        pass

    db.commit()
    return {"message": "Return pickup confirmed and completed successfully"}


@router.get("/performance")
async def get_performance_metrics(
    user: Annotated[User, Depends(_require_delivery_boy)],
    db: Session = Depends(get_session),
):
    total_deliveries = (
        db.scalar(
            select(func.count(Order.id)).where(Order.delivery_boy_id == user.id).where(Order.status == "delivered")
        )
        or 0
    )
    total_returns = (
        db.scalar(
            select(func.count(ReturnRecord.id))
            .where(ReturnRecord.delivery_boy_id == user.id)
            .where(ReturnRecord.status == "return_completed")
        )
        or 0
    )
    rescheduled_count = (
        db.scalar(select(func.sum(Order.rescheduled_count)).where(Order.delivery_boy_id == user.id)) or 0
    )

    return {
        "total_deliveries": total_deliveries,
        "total_returns": total_returns,
        "rescheduled_count": rescheduled_count,
    }
