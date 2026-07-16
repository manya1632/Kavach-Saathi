"""add product_id to returns and scope uniqueness to (order_id, product_id)

Revision ID: d3a91fe58c21
Revises: c7d3e91a62bf
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a91fe58c21"
down_revision: str | Sequence[str] | None = "c7d3e91a62bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("returns", sa.Column("product_id", sa.String(length=32), nullable=True))
    op.create_foreign_key(
        "fk_returns_product_id_products",
        "returns",
        "products",
        ["product_id"],
        ["id"],
    )
    # Backfill existing single-item-order returns from that order's one line item so
    # the new uniqueness rule has a real value to key on instead of NULL.
    op.execute(
        """
        UPDATE returns
        SET product_id = order_items.product_id
        FROM (
            SELECT DISTINCT ON (order_id) order_id, product_id
            FROM order_items
            ORDER BY order_id, id
        ) AS order_items
        WHERE returns.order_id = order_items.order_id AND returns.product_id IS NULL
        """
    )
    op.drop_constraint("uq_returns_order_id", "returns", type_="unique")
    op.create_unique_constraint("uq_returns_order_id_product_id", "returns", ["order_id", "product_id"])


def downgrade() -> None:
    op.drop_constraint("uq_returns_order_id_product_id", "returns", type_="unique")
    op.create_unique_constraint("uq_returns_order_id", "returns", ["order_id"])
    op.drop_constraint("fk_returns_product_id_products", "returns", type_="foreignkey")
    op.drop_column("returns", "product_id")
