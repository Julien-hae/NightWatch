"""Add portfolio_state table for persisting cash balance across restarts.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-17 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add portfolio_state table."""
    op.create_table(
        "portfolio_state",
        sa.Column("cash", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cash", name="uq_portfolio_state_single_row"),
    )


def downgrade() -> None:
    """Drop portfolio_state table."""
    op.drop_table("portfolio_state")
