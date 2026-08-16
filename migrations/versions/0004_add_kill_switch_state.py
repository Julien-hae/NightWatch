"""Add kill_switch_state table for durability past JetStream control-stream retention.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add kill_switch_state singleton table.

    JetStream's CONTROL stream is bounded (10k messages / 24h max age), so a
    kill command that stays in effect longer than that window can silently
    disappear from the backlog. This table mirrors the latest known
    kill-switch state in Postgres so a restart can fall back to it when the
    JetStream backlog is empty, instead of defaulting to trading enabled.
    """
    op.create_table(
        "kill_switch_state",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_kill_switch_state"),
        sa.CheckConstraint("id = 1", name="ck_kill_switch_state_singleton"),
    )


def downgrade() -> None:
    """Drop kill_switch_state table."""
    op.drop_table("kill_switch_state")
