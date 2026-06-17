"""Create paper-trading tables.

Revision ID: 0001
Revises:
Create Date: 2026-06-17 11:35:17.594973
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create paper-trading tables."""
    op.create_table(
        "signals",
        sa.Column("signal_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(255), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("strength", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("strategy", sa.String(255), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("signal_id", name="pk_signals"),
    )

    op.create_table(
        "orders",
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.UUID(), nullable=False),
        sa.Column("signal_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(255), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("qty", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("order_id", name="pk_orders"),
        sa.UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
    )

    op.create_table(
        "fills",
        sa.Column("fill_id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(255), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("qty", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("fee", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("fill_id", name="pk_fills"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"], name="fk_fills_order_id"),
    )

    op.create_table(
        "positions",
        sa.Column("symbol", sa.String(255), nullable=False),
        sa.Column("qty", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", name="pk_positions"),
    )

    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("equity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("cash", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_equity_snapshots"),
    )


def downgrade() -> None:
    """Drop paper-trading tables."""
    op.drop_table("equity_snapshots")
    op.drop_table("positions")
    op.drop_table("fills")
    op.drop_table("orders")
    op.drop_table("signals")
