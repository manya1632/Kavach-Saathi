from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kavach_saathi.db.models import (
    AgentLog,
    BuyerTrustSignal,
    Order,
    OrderItem,
    Product,
    ReturnRecord,
    SellerProfile,
    SellerTrustScoreRecord,
    User,
)

# "Trusted Returner" badge thresholds (final target plan.md Section 4/6) -- a buyer
# needs a real order history before the badge means anything, and a low real return
# rate with zero flagged returns.
_TRUSTED_RETURNER_MIN_ORDERS = 3
_TRUSTED_RETURNER_MAX_RETURN_RATE = 0.15


def compute_seller_trust_score(session: Session, seller_id: str) -> SellerTrustScoreRecord | None:
    """Real trust-score computation (final target plan.md Section 4 `seller_trust_score`
    table) from genuinely-logged agent decisions and order outcomes, replacing the
    previously-never-written table with actual data: catalog accuracy from Agent 2's
    real spec_enforcer confidence scores, RTO rate from real order statuses, fraud
    flags from Agent 1's real stolen-photo detections.
    """
    profile = session.get(SellerProfile, seller_id)
    if profile is None:
        return None

    product_ids = list(session.execute(select(Product.id).where(Product.seller_id == seller_id)).scalars())

    catalog_accuracy = 0.0
    if product_ids:
        avg_confidence = session.scalar(
            select(func.avg(AgentLog.confidence)).where(
                AgentLog.agent_name == "spec_enforcer", AgentLog.entity_id.in_(product_ids)
            )
        )
        catalog_accuracy = round(float(avg_confidence), 2) if avg_confidence is not None else 0.0

    order_ids = list(
        session.execute(select(OrderItem.order_id).where(OrderItem.seller_id == seller_id)).scalars()
    )
    rto_rate = 0.0
    if order_ids:
        statuses = list(session.execute(select(Order.status).where(Order.id.in_(order_ids))).scalars())
        rto_rate = round(sum(1 for status in statuses if status == "RTO") / len(statuses) * 100, 2)

    fraud_flags = (
        session.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.seller_id == seller_id, Product.stolen_photo_flag.is_(True))
        )
        or 0
    )

    record = session.get(SellerTrustScoreRecord, seller_id)
    if record is None:
        record = SellerTrustScoreRecord(seller_id=seller_id)
        session.add(record)
    record.catalog_accuracy_score = catalog_accuracy
    record.rto_rate = rto_rate
    record.fraud_flags = fraud_flags
    record.computed_at = datetime.now(UTC)

    # Blended score feeding the seller-facing trust_score/return_rate/verified fields
    # already read by /seller/profile and the storefront -- catalog accuracy carries
    # the most weight, RTO and fraud flags pull it down.
    blended = catalog_accuracy - rto_rate * 0.5 - fraud_flags * 5
    profile.trust_score = round(max(0.0, min(100.0, blended)), 2)
    profile.return_rate = round(rto_rate)
    if fraud_flags == 0 and profile.digilocker_kyc_status == "verified":
        profile.verified = True

    session.flush()
    return record


def compute_buyer_trust_signal(session: Session, buyer_id: str) -> BuyerTrustSignal | None:
    """Real trust-signal computation (final target plan.md Section 4
    `buyer_trust_signals` table + "Trusted Returner" badge), driven by Agent 8's
    genuinely-recorded return decisions instead of a field nobody ever wrote to.
    """
    user = session.get(User, buyer_id)
    if user is None:
        return None

    orders = session.execute(select(Order).where(Order.buyer_id == buyer_id)).scalars().all()
    finished = [order for order in orders if order.status in ("CLOSED", "DELIVERED") or order.return_outcome]
    returned = [order for order in orders if order.return_outcome]
    return_rate = round(len(returned) / len(finished), 4) if finished else 0.0

    fraud_flags = (
        session.scalar(
            select(func.count())
            .select_from(ReturnRecord)
            .where(ReturnRecord.buyer_id == buyer_id, ReturnRecord.decision == "manual_inspection")
        )
        or 0
    )

    trusted = (
        len(finished) >= _TRUSTED_RETURNER_MIN_ORDERS
        and return_rate <= _TRUSTED_RETURNER_MAX_RETURN_RATE
        and fraud_flags == 0
    )

    signal = session.get(BuyerTrustSignal, buyer_id)
    if signal is None:
        signal = BuyerTrustSignal(buyer_id=buyer_id)
        session.add(signal)
    signal.return_rate = return_rate
    signal.fraud_flags = fraud_flags
    signal.trusted_returner_badge_bool = trusted
    signal.updated_at = datetime.now(UTC)
    user.trusted_returner = trusted

    session.flush()
    return signal


def recompute_all_trust_scores(session: Session) -> dict[str, int]:
    """Batch entry point for the admin console's "recompute trust scores" action --
    the closest equivalent to a scheduled trust-score job without standing up a real
    task scheduler for this project.
    """
    seller_ids = list(session.execute(select(SellerProfile.user_id)).scalars())
    buyer_ids = list(session.execute(select(User.id).where(User.role == "buyer")).scalars())
    for seller_id in seller_ids:
        compute_seller_trust_score(session, seller_id)
    for buyer_id in buyer_ids:
        compute_buyer_trust_signal(session, buyer_id)
    session.commit()
    return {"sellers_updated": len(seller_ids), "buyers_updated": len(buyer_ids)}
