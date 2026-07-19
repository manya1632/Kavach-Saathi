"""add phone_verified to users

Revision ID: 6a2f37d9c841
Revises: f7c4d8a1e6b2
Create Date: 2026-07-19 17:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6a2f37d9c841"
down_revision: str | Sequence[str] | None = "f7c4d8a1e6b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("phone_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("users", "phone_verified", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "phone_verified")
