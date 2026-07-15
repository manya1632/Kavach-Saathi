"""add flexible product specifications and buyer wishlists

Revision ID: c824f7ce913a
Revises: ad71cae0a028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c824f7ce913a"
down_revision: str | Sequence[str] | None = "ad71cae0a028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_returns_order_id", "returns", ["order_id"])
    op.create_table(
        "product_specifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("value_type", sa.String(length=24), nullable=False),
        sa.Column("unit", sa.String(length=24), nullable=True),
        sa.Column("comparison_group", sa.String(length=64), nullable=True),
        sa.Column("comparable", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "key", name="uq_product_specification_key"),
    )
    op.create_index("ix_product_specifications_product", "product_specifications", ["product_id"])
    op.create_index("ix_product_specifications_key", "product_specifications", ["key"])
    op.execute(
        """
        INSERT INTO product_specifications
            (product_id, key, label, value_json, value_type, unit, comparison_group,
             comparable, source, verified, created_at)
        SELECT p.id, e.key, initcap(replace(e.key, '_', ' ')), e.value,
               CASE WHEN jsonb_typeof(e.value) = 'number' THEN 'number' ELSE 'text' END,
               CASE WHEN e.key = 'gsm' THEN 'GSM' WHEN e.key LIKE '%_cm' THEN 'cm' ELSE NULL END,
               CASE WHEN e.key IN ('fabric', 'gsm') THEN 'fabric'
                    WHEN e.key LIKE '%color%' THEN 'color'
                    WHEN e.key LIKE '%care%' THEN 'care'
                    ELSE 'general' END,
               true, p.spec_source, e.key = ANY(
                   SELECT jsonb_array_elements_text(p.label_backed_fields)
               ), p.created_at
        FROM products p CROSS JOIN LATERAL jsonb_each(p.specs) AS e
        ON CONFLICT (product_id, key) DO NOTHING
        """
    )
    op.create_table(
        "wishlist_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("product_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "product_id", name="uq_wishlist_user_product"),
    )
    op.create_index("ix_wishlist_user", "wishlist_items", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_wishlist_user", table_name="wishlist_items")
    op.drop_table("wishlist_items")
    op.drop_index("ix_product_specifications_key", table_name="product_specifications")
    op.drop_index("ix_product_specifications_product", table_name="product_specifications")
    op.drop_table("product_specifications")
    op.drop_constraint("uq_returns_order_id", "returns", type_="unique")
