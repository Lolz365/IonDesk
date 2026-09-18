from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import APIKey
from app.services.audit import record_audit_event
from app.services.authorization import Capability, TenantContext

PBKDF2_ITERATIONS = 600_000
TOKEN_PREFIX = "vo_sk_"


class InvalidAPIKey(Exception):
    pass


class APIKeyExpired(InvalidAPIKey):
    pass


class APIKeyRevoked(InvalidAPIKey):
    pass


class APIKeyNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class IssuedAPIKey:
    id: uuid.UUID
    name: str
    prefix: str
    token: str
    scopes: frozenset[Capability]
    expires_at: datetime | None


def hash_api_key_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", secret.encode(), salt, PBKDF2_ITERATIONS, dklen=32
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(digest).decode(),
        )
    )


def verify_api_key_secret(secret: str, encoded: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if iterations != PBKDF2_ITERATIONS:
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256", secret.encode(), salt, iterations, dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _split_token(token: str) -> tuple[str, str]:
    if not token.startswith(TOKEN_PREFIX) or "." not in token:
        raise InvalidAPIKey
    visible, secret = token[len(TOKEN_PREFIX) :].split(".", 1)
    if len(visible) != 12 or len(secret) < 32:
        raise InvalidAPIKey
    return visible, secret


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def create_api_key(
    session: AsyncSession,
    *,
    context: TenantContext,
    name: str,
    scopes: frozenset[Capability],
    expires_at: datetime | None,
    correlation_id: uuid.UUID,
    source_ip: str | None,
    user_agent: str | None,
) -> IssuedAPIKey:
    if not scopes or not scopes.issubset(context.capabilities):
        raise ValueError("scopes must be a non-empty subset of actor capabilities")
    prefix = secrets.token_urlsafe(9)[:12]
    secret = secrets.token_urlsafe(32)
    model = APIKey(
        organization_id=context.organization_id,
        created_by_user_id=context.user_id,
        name=name,
        key_prefix=prefix,
        secret_hash=hash_api_key_secret(secret),
        scopes=sorted(scope.value for scope in scopes),
        expires_at=expires_at,
    )
    session.add(model)
    await session.flush()
    record_audit_event(
        session,
        context=context,
        object_type="api_key",
        object_id=model.id,
        action="api_key.created",
        before=None,
        after={"name": name, "prefix": prefix, "scopes": model.scopes},
        correlation_id=correlation_id,
        source_ip=source_ip,
        user_agent=user_agent,
    )
    return IssuedAPIKey(
        id=model.id,
        name=name,
        prefix=prefix,
        token=f"{TOKEN_PREFIX}{prefix}.{secret}",
        scopes=scopes,
        expires_at=expires_at,
    )


async def list_api_keys(
    session: AsyncSession, *, context: TenantContext
) -> list[APIKey]:
    return list(
        await session.scalars(
            select(APIKey)
            .where(APIKey.organization_id == context.organization_id)
            .order_by(APIKey.created_at, APIKey.id)
        )
    )


async def authenticate_api_key(
    session: AsyncSession, token: str, *, now: datetime | None = None
) -> TenantContext:
    prefix, secret = _split_token(token)
    model = await session.scalar(select(APIKey).where(APIKey.key_prefix == prefix))
    if model is None or not verify_api_key_secret(secret, model.secret_hash):
        raise InvalidAPIKey
    if model.revoked_at is not None:
        raise APIKeyRevoked
    checked_at = now or datetime.now(UTC)
    if model.expires_at is not None and _aware(model.expires_at) <= checked_at:
        raise APIKeyExpired
    try:
        scopes = frozenset(Capability(value) for value in model.scopes)
    except ValueError as error:
        raise InvalidAPIKey from error
    model.last_used_at = checked_at
    await session.flush()
    return TenantContext(
        organization_id=model.organization_id,
        user_id=model.created_by_user_id,
        membership_id=None,
        role=None,
        capabilities=scopes,
        credential_id=f"api_key:{model.id}",
    )


async def revoke_api_key(
    session: AsyncSession,
    *,
    context: TenantContext,
    api_key_id: uuid.UUID,
    correlation_id: uuid.UUID,
    source_ip: str | None,
    user_agent: str | None,
) -> APIKey:
    model = await session.scalar(
        select(APIKey).where(
            APIKey.id == api_key_id,
            APIKey.organization_id == context.organization_id,
        )
    )
    if model is None:
        raise APIKeyNotFound
    if model.revoked_at is None:
        model.revoked_at = datetime.now(UTC)
        record_audit_event(
            session,
            context=context,
            object_type="api_key",
            object_id=model.id,
            action="api_key.revoked",
            before={"revoked": False},
            after={"revoked": True},
            correlation_id=correlation_id,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        await session.flush()
    return model
