"""add persistent verified-purchase order link to reviews

Revision ID: b4c9f2a710de
Revises: 5b0ede91dc5b
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c9f2a710de"
down_revision: str | Sequence[str] | None = "5b0ede91dc5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("order_id", sa.String(length=32), nullable=True))
    op.create_foreign_key(
        "fk_reviews_order_id_orders",
        "reviews",
        "orders",
        ["order_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_reviews_order_id_orders", "reviews", type_="foreignkey")
    op.drop_column("reviews", "order_id")
