"""add postgres catalogue search

Revision ID: b72f184ad630
Revises: a41d7a62c9e4
Create Date: 2026-07-18 17:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b72f184ad630"
down_revision: str | Sequence[str] | None = "a41d7a62c9e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_products_search_document
        ON products USING gin (
            to_tsvector(
                'simple',
                COALESCE(name, '') || ' ' || COALESCE(brand, '') || ' ' ||
                COALESCE(category, '') || ' ' || COALESCE(material, '') || ' ' ||
                COALESCE(occasion, '') || ' ' || COALESCE(description, '')
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_name_trgm ON products USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_brand_trgm ON products USING gin (brand gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_brand_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_search_document")
