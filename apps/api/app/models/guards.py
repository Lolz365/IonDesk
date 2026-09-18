from __future__ import annotations

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.api_key import APIKey
from app.models.audit_event import AuditEvent
from app.models.idempotency_record import IdempotencyRecord
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.outbox_event import OutboxEvent

TENANT_MODELS = (Membership, APIKey, AuditEvent, OutboxEvent, IdempotencyRecord)


@event.listens_for(Session, "before_flush")
def enforce_immutable_foundation_rows(
    session: Session, flush_context: object, instances: object
) -> None:
    del flush_context, instances
    for instance in session.dirty:
        if isinstance(instance, AuditEvent):
            raise ValueError("audit events are append-only")
        state = inspect(instance)
        if (
            isinstance(instance, Organization)
            and state.attrs.identifier.history.has_changes()
        ):
            raise ValueError("organization identifier is immutable")
        if (
            isinstance(instance, TENANT_MODELS)
            and state.attrs.organization_id.history.has_changes()
        ):
            raise ValueError("organization_id is immutable")
    if any(isinstance(instance, AuditEvent) for instance in session.deleted):
        raise ValueError("audit events are append-only")
