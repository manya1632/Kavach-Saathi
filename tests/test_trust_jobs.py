from __future__ import annotations

from kavach_saathi.db.base import SessionLocal
from kavach_saathi.trust_jobs import compute_buyer_trust_signal, compute_seller_trust_score


def test_compute_seller_trust_score_writes_real_row() -> None:
    with SessionLocal() as session:
        record = compute_seller_trust_score(session, "S-001")
        session.commit()
    assert record is not None
    assert record.seller_id == "S-001"
    assert 0.0 <= record.catalog_accuracy_score <= 100.0
    assert record.rto_rate >= 0.0


def test_compute_seller_trust_score_returns_none_for_unknown_seller() -> None:
    with SessionLocal() as session:
        record = compute_seller_trust_score(session, "S-DOES-NOT-EXIST")
    assert record is None


def test_compute_buyer_trust_signal_writes_real_row() -> None:
    with SessionLocal() as session:
        signal = compute_buyer_trust_signal(session, "B-001")
        session.commit()
    assert signal is not None
    assert signal.buyer_id == "B-001"
    assert 0.0 <= signal.return_rate <= 1.0


def test_compute_buyer_trust_signal_returns_none_for_unknown_buyer() -> None:
    with SessionLocal() as session:
        signal = compute_buyer_trust_signal(session, "B-DOES-NOT-EXIST")
    assert signal is None
