"""Add persistent buyer addresses, OTP sessions, and payment audit data.

Revision ID: 8f59e280fa22
Revises: c824f7ce913a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "8f59e280fa22"
down_revision: str | Sequence[str] | None = "c824f7ce913a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # An early local draft of this revision only dropped these indexes. Repair them
    # if that draft was ever applied before proceeding with the real schema change.
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        product_indexes = {item["name"] for item in inspector.get_indexes("product_specifications")}
        wishlist_indexes = {item["name"] for item in inspector.get_indexes("wishlist_items")}
        if "ix_product_specifications_product" not in product_indexes:
            op.create_index("ix_product_specifications_product", "product_specifications", ["product_id"])
        if "ix_product_specifications_key" not in product_indexes:
            op.create_index("ix_product_specifications_key", "product_specifications", ["key"])
        if "ix_wishlist_user" not in wishlist_indexes:
            op.create_index("ix_wishlist_user", "wishlist_items", ["user_id"])

    op.add_column("addresses", sa.Column("recipient_name", sa.String(length=120), nullable=True))
    op.add_column("addresses", sa.Column("phone", sa.String(length=20), nullable=True))
    op.add_column("addresses", sa.Column("address_line1", sa.Text(), nullable=True))
    op.add_column("addresses", sa.Column("address_line2", sa.Text(), nullable=True))
    op.add_column("addresses", sa.Column("locality", sa.Text(), nullable=True))
    op.add_column("addresses", sa.Column("district", sa.String(length=120), nullable=True))
    op.add_column("addresses", sa.Column("country", sa.String(length=120), nullable=True))
    op.add_column(
        "addresses",
        sa.Column("address_type", sa.String(length=20), nullable=True, server_default="Home"),
    )
    op.add_column(
        "addresses",
        sa.Column("phone_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "addresses",
        sa.Column(
            "validation_status",
            sa.String(length=24),
            nullable=False,
            server_default="needs_correction",
        ),
    )
    op.add_column("addresses", sa.Column("validation_explanation", sa.Text(), nullable=True))
    op.add_column("addresses", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE addresses
        SET recipient_name = user_id,
            address_line1 = raw_text,
            district = city,
            country = 'India',
            address_type = 'Home',
            validation_status = CASE WHEN verified_bool THEN 'valid' ELSE 'needs_correction' END,
            validation_explanation = 'Migrated from legacy verified address',
            updated_at = created_at
        """
    )

    op.add_column(
        "orders",
        sa.Column("address_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.add_column("payments", sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"))
    op.add_column("payments", sa.Column("provider_order_id", sa.String(length=120), nullable=True))
    op.add_column("payments", sa.Column("provider_payment_id", sa.String(length=120), nullable=True))
    op.add_column("payments", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("payments", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_payments_provider_order_id", "payments", ["provider_order_id"])
    op.create_unique_constraint("uq_payments_provider_payment_id", "payments", ["provider_payment_id"])

    op.create_table(
        "otp_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("address_session_id", sa.String(length=64), nullable=False),
        sa.Column("otp_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_otp_sessions_lookup",
        "otp_sessions",
        ["user_id", "phone", "address_session_id", "created_at"],
    )

    op.create_table(
        "razorpay_webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_razorpay_webhook_event_id"),
    )


def downgrade() -> None:
    op.drop_table("razorpay_webhook_events")
    op.drop_index("ix_otp_sessions_lookup", table_name="otp_sessions")
    op.drop_table("otp_sessions")

    op.drop_constraint("uq_payments_provider_payment_id", "payments", type_="unique")
    op.drop_constraint("uq_payments_provider_order_id", "payments", type_="unique")
    op.drop_column("payments", "updated_at")
    op.drop_column("payments", "failure_reason")
    op.drop_column("payments", "provider_payment_id")
    op.drop_column("payments", "provider_order_id")
    op.drop_column("payments", "currency")
    op.drop_column("orders", "address_snapshot")

    op.drop_column("addresses", "updated_at")
    op.drop_column("addresses", "validation_explanation")
    op.drop_column("addresses", "validation_status")
    op.drop_column("addresses", "phone_verified")
    op.drop_column("addresses", "address_type")
    op.drop_column("addresses", "country")
    op.drop_column("addresses", "district")
    op.drop_column("addresses", "locality")
    op.drop_column("addresses", "address_line2")
    op.drop_column("addresses", "address_line1")
    op.drop_column("addresses", "phone")
    op.drop_column("addresses", "recipient_name")
