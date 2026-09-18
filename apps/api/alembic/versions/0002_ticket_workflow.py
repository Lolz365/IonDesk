"""Add tenant-scoped tickets."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_ticket_workflow"
down_revision: str | None = "0001_tenant_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 200",
            name="ck_tickets_title_length",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name="fk_tickets_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_tickets_created_by_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tickets"),
    )
    op.create_index(
        "ix_tickets_organization_id_created_at",
        "tickets",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_tickets_organization_id_id", "tickets", ["organization_id", "id"]
    )
    op.execute(
        "CREATE TRIGGER tickets_tenant_immutable BEFORE UPDATE ON tickets "
        "FOR EACH ROW EXECUTE FUNCTION reject_tenant_reassignment()"
    )


def downgrade() -> None:
    op.drop_table("tickets")
