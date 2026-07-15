from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kavach_saathi.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    """Section 4: users — buyers, sellers, and admins share one identity table."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # buyer | seller | admin
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    measurements_cm: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    trusted_returner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    seller_profile: Mapped[SellerProfile | None] = relationship(back_populates="user", uselist=False)


class RefreshToken(Base):
    """Rotating refresh tokens for JWT auth (Sub-phase 1)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SellerProfile(Base):
    __tablename__ = "seller_profiles"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), primary_key=True)
    business_name: Mapped[str] = mapped_column(String(160), nullable=False)
    digilocker_kyc_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_started")
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    on_time_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    return_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped[User] = relationship(back_populates="seller_profile")


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_pin: Mapped[str | None] = mapped_column(String(6), nullable=True)
    digipin: Mapped[str | None] = mapped_column(String(10), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified_bool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    seller_id: Mapped[str] = mapped_column(String(32), ForeignKey("seller_profiles.user_id"), nullable=False)
    title: Mapped[str] = mapped_column("name", String(200), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    audience: Mapped[str] = mapped_column(String(40), nullable=False, default="All")
    occasion: Mapped[str | None] = mapped_column(String(80), nullable=True)
    material: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    original_price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    spec_json: Mapped[dict[str, Any]] = mapped_column("specs", JSONB, nullable=False, default=dict)
    label_backed_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    spec_source: Mapped[str] = mapped_column(String(24), nullable=False, default="seller_form")
    stolen_photo_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_days: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    free_delivery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cod_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    return_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    highlights: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    badges: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    presentation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    size_chart: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    media_primary: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    media_care_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)  # seller_upload | ai_generated
    angle: Mapped[str] = mapped_column(String(16), nullable=False)  # front | back | left | right
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProductSpecification(Base):
    """A flexible, typed and queryable specification attached to one product."""

    __tablename__ = "product_specifications"
    __table_args__ = (UniqueConstraint("product_id", "key", name="uq_product_specification_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSONB, nullable=False)
    value_type: Mapped[str] = mapped_column(String(24), nullable=False, default="text")
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    comparison_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comparable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="seller_form")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), nullable=False)
    size: Mapped[str] = mapped_column(String(16), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    stock_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price: Mapped[float] = mapped_column(Float, nullable=False)


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    product_variant_id: Mapped[str] = mapped_column(String(48), ForeignKey("product_variants.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_wishlist_user_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    buyer_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    address_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("addresses.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CART")
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    payment_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)  # cod | prepaid
    fit_feedback: Mapped[str | None] = mapped_column(String(24), nullable=True)
    return_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), nullable=False)
    product_variant_id: Mapped[str | None] = mapped_column(
        String(48), ForeignKey("product_variants.id"), nullable=True
    )
    seller_id: Mapped[str] = mapped_column(String(32), ForeignKey("seller_profiles.user_id"), nullable=False)
    size: Mapped[str | None] = mapped_column(String(16), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_at_purchase: Mapped[float] = mapped_column(Float, nullable=False)


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    actor: Mapped[str] = mapped_column(String(16), nullable=False, default="system")  # system | agent | user


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="cod")  # razorpay | cod
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    transaction_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), nullable=False)
    buyer_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_hidden_by_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hide_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReturnRecord(Base):
    __tablename__ = "returns"
    __table_args__ = (UniqueConstraint("order_id", name="uq_returns_order_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False)
    buyer_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    video_url: Mapped[str | None] = mapped_column("video", String(255), nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentLog(Base):
    """Section 4: agent_logs — every agent decision, real and queryable."""

    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BuyerTrustSignal(Base):
    __tablename__ = "buyer_trust_signals"

    buyer_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), primary_key=True)
    return_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fraud_flags: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trusted_returner_badge_bool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class SellerTrustScoreRecord(Base):
    __tablename__ = "seller_trust_score"

    seller_id: Mapped[str] = mapped_column(String(32), ForeignKey("seller_profiles.user_id"), primary_key=True)
    catalog_accuracy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rto_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fraud_flags: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class EvalFixture(Base):
    """Not a Section-4 table: holds the ground-truth/expected_* fixture answers stripped
    out of the real commerce tables so agent logic can never read them. Used only by
    scripts/evaluate_demo.py to score agent accuracy offline."""

    __tablename__ = "eval_fixtures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
