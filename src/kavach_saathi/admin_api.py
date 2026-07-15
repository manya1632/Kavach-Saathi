from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kavach_saathi.auth import require_role
from kavach_saathi.db.base import get_session
from kavach_saathi.db.models import (
    AgentLog,
    BuyerTrustSignal,
    Order,
    OrderItem,
    Product,
    ReturnRecord,
    Review,
    SellerProfile,
    SellerTrustScoreRecord,
    User,
)
from kavach_saathi.models import AdminReturnResolution, AdminTrustScoreOverride
from kavach_saathi.trust_jobs import compute_buyer_trust_signal, compute_seller_trust_score, recompute_all_trust_scores

router = APIRouter()
_require_admin = require_role("admin")


@router.get("/admin/inspection-queue")
async def inspection_queue(
    user: Annotated[User, Depends(_require_admin)],
    session: Session = Depends(get_session),
):
    """Real manual-inspection queue (final target plan.md admin console requirement):
    every return Agent 8 genuinely sent to human review, not a fixture list."""
    rows = session.execute(
        select(ReturnRecord)
        .where(ReturnRecord.decision == "manual_inspection")
        .order_by(ReturnRecord.decided_at.desc())
    ).scalars().all()
    return [
        {
            "return_id": record.id,
            "order_id": record.order_id,
            "buyer_id": record.buyer_id,
            "confidence_score": record.confidence_score,
            "video_url": record.video_url,
            "decided_at": record.decided_at,
        }
        for record in rows
    ]


@router.post("/admin/returns/{return_id}/resolve")
async def resolve_return(
    return_id: str,
    payload: AdminReturnResolution,
    user: Annotated[User, Depends(_require_admin)],
    session: Session = Depends(get_session),
):
    """Closes the loop Agent 8 opens with a `manual_inspection` decision: an admin's
    real approve/reject overwrites the return record and order outcome, then feeds
    straight back into the trust-score jobs so the override actually affects future
    scoring instead of sitting inert."""
    record = session.get(ReturnRecord, return_id)
    if not record:
        raise HTTPException(status_code=404, detail="Return not found")

    resolved_decision = "approve" if payload.decision == "approve" else "reject"
    record.decision = resolved_decision
    record.decided_at = datetime.now(UTC)

    order = session.get(Order, record.order_id)
    if order:
        order.return_outcome = resolved_decision
    session.flush()

    if order:
        item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalars().first()
        if item:
            compute_seller_trust_score(session, item.seller_id)
        compute_buyer_trust_signal(session, order.buyer_id)
    session.commit()

    return {"return_id": record.id, "decision": record.decision, "notes": payload.notes}


@router.get("/admin/fraud-cases")
async def fraud_cases(
    user: Annotated[User, Depends(_require_admin)],
    session: Session = Depends(get_session),
):
    """Real fraud signals already computed elsewhere in the pipeline (Agent 1's
    stolen-photo reverse-image check, Agent 8's manual_inspection returns) surfaced in
    one admin view -- not a synthetic case list."""
    flagged_products = session.execute(
        select(Product).where(Product.stolen_photo_flag.is_(True))
    ).scalars().all()
    flagged_returns = session.execute(
        select(ReturnRecord).where(ReturnRecord.decision == "manual_inspection")
    ).scalars().all()
    flagged_sellers = session.execute(
        select(SellerTrustScoreRecord).where(SellerTrustScoreRecord.fraud_flags > 0)
    ).scalars().all()
    flagged_buyers = session.execute(
        select(BuyerTrustSignal).where(BuyerTrustSignal.fraud_flags > 0)
    ).scalars().all()
    return {
        "stolen_photo_products": [
            {"product_id": p.id, "seller_id": p.seller_id, "title": p.title} for p in flagged_products
        ],
        "manual_inspection_returns": [
            {"return_id": r.id, "order_id": r.order_id, "buyer_id": r.buyer_id} for r in flagged_returns
        ],
        "flagged_sellers": [
            {"seller_id": s.seller_id, "fraud_flags": s.fraud_flags, "rto_rate": s.rto_rate} for s in flagged_sellers
        ],
        "flagged_buyers": [
            {"buyer_id": b.buyer_id, "fraud_flags": b.fraud_flags, "return_rate": b.return_rate}
            for b in flagged_buyers
        ],
    }


@router.get("/admin/analytics")
async def analytics(
    user: Annotated[User, Depends(_require_admin)],
    session: Session = Depends(get_session),
):
    """Platform-wide dashboard built from real table counts and real agent_logs
    confidence averages -- no seeded/fixture numbers."""
    total_orders = session.scalar(select(func.count()).select_from(Order)) or 0
    total_revenue = session.scalar(select(func.sum(Order.total_amount)).where(Order.status != "CANCELLED")) or 0.0
    total_reviews = session.scalar(select(func.count()).select_from(Review)) or 0
    hidden_reviews = (
        session.scalar(select(func.count()).select_from(Review).where(Review.is_hidden_by_agent.is_(True))) or 0
    )
    total_returns = session.scalar(select(func.count()).select_from(ReturnRecord)) or 0
    manual_review_returns = session.scalar(
        select(func.count()).select_from(ReturnRecord).where(ReturnRecord.decision == "manual_inspection")
    ) or 0

    avg_confidence_by_agent = dict(
        session.execute(select(AgentLog.agent_name, func.avg(AgentLog.confidence)).group_by(AgentLog.agent_name)).all()
    )

    return {
        "total_orders": total_orders,
        "total_revenue": round(float(total_revenue), 2),
        "total_reviews": total_reviews,
        "hidden_reviews": hidden_reviews,
        "total_returns": total_returns,
        "manual_review_returns": manual_review_returns,
        "avg_confidence_by_agent": {name: round(float(value), 2) for name, value in avg_confidence_by_agent.items()},
    }


@router.patch("/admin/sellers/{seller_id}/trust-score")
async def override_seller_trust_score(
    seller_id: str,
    payload: AdminTrustScoreOverride,
    user: Annotated[User, Depends(_require_admin)],
    session: Session = Depends(get_session),
):
    profile = session.get(SellerProfile, seller_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Seller not found")
    if payload.trust_score is not None:
        profile.trust_score = payload.trust_score
    if payload.verified is not None:
        profile.verified = payload.verified
    session.commit()
    return {"seller_id": seller_id, "trust_score": profile.trust_score, "verified": profile.verified}


@router.post("/admin/trust-scores/recompute")
async def recompute_trust_scores(
    user: Annotated[User, Depends(_require_admin)],
    session: Session = Depends(get_session),
):
    """Manual batch-recompute entry point (final target plan.md "trust jobs") --
    the closest equivalent to a scheduled job without standing up a real task
    scheduler; runs the same real computation Agent 8 already triggers per-order."""
    return recompute_all_trust_scores(session)
