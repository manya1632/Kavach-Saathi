"""expand WhatsApp workflow state

Revision ID: f93d6ec748d1
Revises: c65ff7497d27
Create Date: 2026-07-17 13:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f93d6ec748d1"
down_revision: str | Sequence[str] | None = "c65ff7497d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "orders",
        "whatsapp_workflow_state",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "orders",
        "whatsapp_workflow_state",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=True,
    )
