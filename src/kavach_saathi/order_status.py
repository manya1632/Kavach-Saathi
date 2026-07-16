from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    """Section 4 order lifecycle state machine (final target plan.md, line 109-111)."""

    CART = "CART"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    RETURN_INITIATED = "RETURN_INITIATED"
    RETURN_UNDER_REVIEW = "RETURN_UNDER_REVIEW"
    RETURN_APPROVED = "RETURN_APPROVED"
    RETURN_REJECTED = "RETURN_REJECTED"
    MANUAL_INSPECTION = "MANUAL_INSPECTION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    RTO = "RTO"
    AWAITING_BUYER_CONFIRMATION = "AWAITING_BUYER_CONFIRMATION"
    DELIVERY_SCHEDULED = "DELIVERY_SCHEDULED"
    DELIVERY_VERIFICATION_PENDING = "DELIVERY_VERIFICATION_PENDING"


ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CART: {OrderStatus.PLACED, OrderStatus.CANCELLED},
    OrderStatus.PLACED: {OrderStatus.AWAITING_BUYER_CONFIRMATION, OrderStatus.CONFIRMED, OrderStatus.CANCELLED, OrderStatus.RTO},
    OrderStatus.AWAITING_BUYER_CONFIRMATION: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.DELIVERY_SCHEDULED, OrderStatus.PACKED, OrderStatus.CANCELLED},
    OrderStatus.DELIVERY_SCHEDULED: {OrderStatus.PACKED, OrderStatus.CANCELLED},
    OrderStatus.PACKED: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.OUT_FOR_DELIVERY, OrderStatus.RTO},
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.DELIVERY_VERIFICATION_PENDING, OrderStatus.DELIVERED, OrderStatus.RTO},
    OrderStatus.DELIVERY_VERIFICATION_PENDING: {OrderStatus.DELIVERED, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.RTO},
    OrderStatus.DELIVERED: {OrderStatus.RETURN_INITIATED, OrderStatus.CLOSED},
    OrderStatus.RETURN_INITIATED: {OrderStatus.RETURN_UNDER_REVIEW},
    OrderStatus.RETURN_UNDER_REVIEW: {
        OrderStatus.RETURN_APPROVED,
        OrderStatus.RETURN_REJECTED,
        OrderStatus.MANUAL_INSPECTION,
    },
    OrderStatus.MANUAL_INSPECTION: {OrderStatus.RETURN_APPROVED, OrderStatus.RETURN_REJECTED},
    OrderStatus.RETURN_APPROVED: {OrderStatus.CLOSED},
    OrderStatus.RETURN_REJECTED: {OrderStatus.CLOSED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.RTO: {OrderStatus.CLOSED},
    OrderStatus.CLOSED: set(),
}


class InvalidOrderTransition(ValueError):
    pass


def validate_transition(current: OrderStatus, target: OrderStatus) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidOrderTransition(f"Cannot move order from {current} to {target}")
