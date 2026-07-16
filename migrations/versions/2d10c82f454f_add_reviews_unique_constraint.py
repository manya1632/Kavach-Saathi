"""add_reviews_unique_constraint

Revision ID: 2d10c82f454f
Revises: d3a91fe58c21
Create Date: 2026-07-16 14:33:20.050321

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d10c82f454f"
down_revision: str | Sequence[str] | None = "d3a91fe58c21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enforce one review per buyer and product."""
    op.create_unique_constraint("uq_reviews_buyer_id_product_id", "reviews", ["buyer_id", "product_id"])


def downgrade() -> None:
    """Remove review uniqueness enforcement."""
    op.drop_constraint("uq_reviews_buyer_id_product_id", "reviews", type_="unique")
