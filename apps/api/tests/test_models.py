from __future__ import annotations

from typing import cast

from sqlalchemy import CheckConstraint, DateTime, Table, UniqueConstraint

from app.db.base import Base
from app.models import Membership, Organization


def test_foundation_metadata_has_tenant_keys_constraints_and_indexes() -> None:
    expected_tables = {
        "organizations",
        "users",
        "memberships",
        "api_keys",
        "audit_events",
        "outbox_events",
        "idempotency_records",
        "tickets",
    }

    assert expected_tables == set(Base.metadata.tables)

    membership_constraints = cast(Table, Membership.__table__).constraints
    assert any(isinstance(item, CheckConstraint) for item in membership_constraints)
    assert any(isinstance(item, UniqueConstraint) for item in membership_constraints)

    for table_name in expected_tables - {"organizations", "users"}:
        table = Base.metadata.tables[table_name]
        assert "organization_id" in table.c
        assert table.c.organization_id.foreign_keys
        assert cast(DateTime, table.c.created_at.type).timezone is True
        index_columns = {
            tuple(column.name for column in index.columns) for index in table.indexes
        }
        assert ("organization_id", "created_at") in index_columns
        assert ("organization_id", "id") in index_columns

    assert Organization.__table__.c.id.type.python_type.__name__ == "UUID"


def test_migrations_are_the_ordered_versioned_schema_source() -> None:
    from pathlib import Path

    versions = list((Path(__file__).parents[1] / "alembic" / "versions").glob("*.py"))

    assert [version.name for version in versions] == [
        "0001_tenant_foundation.py",
        "0002_ticket_workflow.py",
    ]
    foundation = versions[0].read_text()
    ticket_workflow = versions[1].read_text()
    assert 'revision: str = "0001_tenant_foundation"' in foundation
    assert "CREATE TRIGGER organizations_identifier_immutable" in foundation
    assert "CREATE TRIGGER audit_events_append_only" in foundation
    assert 'down_revision: str | None = "0001_tenant_foundation"' in ticket_workflow
    assert "CREATE TRIGGER tickets_tenant_immutable" in ticket_workflow
