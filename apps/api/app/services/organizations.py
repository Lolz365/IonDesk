from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyRecord, Organization
from app.services.audit import enqueue_outbox_event, record_audit_event
from app.services.authorization import TenantContext


class OrganizationNotFound(Exception):
    """Raised without exposing whether another tenant owns a guessed ID."""


class TransactionConflict(Exception):
    """Raised when a transaction violates a uniqueness/concurrency invariant."""


IDEMPOTENCY_TTL = timedelta(hours=24)


def _rename_request_hash(name: str) -> str:
    request = json.dumps(
        {"operation": "organization.rename", "name": name},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(request.encode()).hexdigest()


def _stored_response(record: IdempotencyRecord, request_hash: str) -> dict[str, object]:
    if (
        record.request_hash != request_hash
        or record.response_status != 200
        or record.response_body is None
    ):
        raise TransactionConflict
    return record.response_body


async def _find_idempotency_record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    key: str,
) -> IdempotencyRecord | None:
    return cast(
        IdempotencyRecord | None,
        await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.key == key,
            )
        ),
    )


async def get_tenant_organization(
    session: AsyncSession,
    *,
    context: TenantContext,
    organization_id: uuid.UUID,
) -> Organization:
    organization = await session.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.id == context.organization_id,
        )
    )
    if organization is None:
        raise OrganizationNotFound
    return organization


async def rename_current_organization(
    session: AsyncSession,
    *,
    context: TenantContext,
    name: str,
    correlation_id: uuid.UUID,
    source_ip: str | None,
    user_agent: str | None,
    idempotency_key: str | None = None,
) -> Organization | dict[str, object]:
    request_hash = _rename_request_hash(name)
    try:
        async with session.begin():
            idempotency_record = None
            if idempotency_key is not None:
                idempotency_record = await _find_idempotency_record(
                    session,
                    organization_id=context.organization_id,
                    key=idempotency_key,
                )
                if idempotency_record is not None:
                    expires_at = idempotency_record.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=UTC)
                    if expires_at > datetime.now(UTC):
                        return _stored_response(idempotency_record, request_hash)
                    await session.delete(idempotency_record)
                    await session.flush()

                idempotency_record = IdempotencyRecord(
                    organization_id=context.organization_id,
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=None,
                    response_body=None,
                    expires_at=datetime.now(UTC) + IDEMPOTENCY_TTL,
                )
                session.add(idempotency_record)
                await session.flush()

            organization = await get_tenant_organization(
                session,
                context=context,
                organization_id=context.organization_id,
            )
            before: dict[str, object] = {"name": organization.name}
            organization.name = name
            record_audit_event(
                session,
                context=context,
                object_type="organization",
                object_id=organization.id,
                action="organization.renamed",
                before=before,
                after={"name": name},
                correlation_id=correlation_id,
                source_ip=source_ip,
                user_agent=user_agent,
            )
            enqueue_outbox_event(
                session,
                organization_id=context.organization_id,
                aggregate_type="organization",
                aggregate_id=organization.id,
                event_type="organization.renamed",
                payload={"organization_id": str(organization.id), "name": name},
                idempotency_key=f"organization.renamed:{correlation_id}",
            )
            await session.flush()
            if idempotency_record is not None:
                idempotency_record.response_status = 200
                idempotency_record.response_body = {
                    "id": str(organization.id),
                    "identifier": organization.identifier,
                    "name": organization.name,
                }
        return organization
    except IntegrityError as error:
        if idempotency_key is not None:
            async with session.begin():
                existing_record = await _find_idempotency_record(
                    session,
                    organization_id=context.organization_id,
                    key=idempotency_key,
                )
                if existing_record is not None:
                    return _stored_response(existing_record, request_hash)
        raise TransactionConflict from error
