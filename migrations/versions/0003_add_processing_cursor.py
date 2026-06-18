"""Add processing_cursor table for resume-after-restart.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-17 12:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add processing_cursor singleton table.

    Stores the id of the last signal whose order was committed. Combined with
    the unique ``orders.idempotency_key`` constraint, this lets the bot resume
    safely after a crash or restart.
    """
    op.create_table(
        "processing_cursor",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("last_signal_id", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_processing_cursor"),
        sa.CheckConstraint("id = 1", name="ck_processing_cursor_singleton"),
    )


def downgrade() -> None:
    """Drop processing_cursor table."""
    op.drop_table("processing_cursor")
