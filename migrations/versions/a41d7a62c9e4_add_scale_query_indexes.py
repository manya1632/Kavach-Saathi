"""add scale query indexes

Revision ID: a41d7a62c9e4
Revises: f93d6ec748d1
Create Date: 2026-07-18 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a41d7a62c9e4"
down_revision: str | Sequence[str] | None = "f93d6ec748d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES = (
    ("ix_addresses_user_default", "addresses", ["user_id", "is_default"]),
    ("ix_products_status_category_activation", "products", ["status", "category", "activation_timestamp"]),
    ("ix_products_seller_created", "products", ["seller_id", "created_at"]),
    ("ix_product_images_product_angle_verified", "product_images", ["product_id", "angle", "is_verified"]),
    ("ix_product_variants_product", "product_variants", ["product_id"]),
    ("ix_cart_items_user", "cart_items", ["user_id"]),
    ("ix_orders_buyer_status_created", "orders", ["buyer_id", "status", "created_at"]),
    ("ix_orders_status_created", "orders", ["status", "created_at"]),
    ("ix_order_items_order", "order_items", ["order_id"]),
    ("ix_order_items_seller_order", "order_items", ["seller_id", "order_id"]),
    ("ix_order_history_order_changed", "order_status_history", ["order_id", "changed_at"]),
    ("ix_payments_order", "payments", ["order_id"]),
    ("ix_reviews_product_created", "reviews", ["product_id", "created_at"]),
    ("ix_returns_buyer_created", "returns", ["buyer_id", "created_at"]),
    ("ix_returns_status_created", "returns", ["status", "created_at"]),
    ("ix_agent_logs_entity_created", "agent_logs", ["agent_name", "entity_id", "created_at"]),
    ("ix_chat_conversations_user_status_updated", "chat_conversations", ["user_id", "status", "updated_at"]),
    ("ix_chat_messages_conversation_created", "chat_messages", ["conversation_id", "created_at"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
