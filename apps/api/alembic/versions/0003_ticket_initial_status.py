"""Persist the initial ticket lifecycle status."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_ticket_initial_status"
down_revision: str | None = "0002_ticket_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("status", sa.String(32), server_default="new", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tickets", "status")
