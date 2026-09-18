from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.api_keys import create_api_key, revoke_api_key
from app.services.authorization import (
    AuthorizationDenied,
    Capability,
    TenantContext,
    get_tenant_context,
    require_capability,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
TenantDependency = Annotated[TenantContext, Depends(get_tenant_context)]


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Capability] = Field(min_length=1)
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: list[Capability]) -> list[Capability]:
        if len(value) != len(set(value)):
            raise ValueError("scopes must be unique")
        return value

    @model_validator(mode="after")
    def expiry_is_future(self) -> APIKeyCreate:
        if self.expires_at is not None:
            from datetime import UTC

            candidate = self.expires_at
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=UTC)
            if candidate <= datetime.now(UTC):
                raise ValueError("expires_at must be in the future")
        return self


class APIKeyCreated(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    token: str
    scopes: list[Capability]
    expires_at: datetime | None


class APIKeyRevokedResponse(BaseModel):
    id: uuid.UUID
    revoked: bool


@router.post("", response_model=APIKeyCreated)
async def issue_api_key(
    body: APIKeyCreate,
    request: Request,
    session: SessionDependency,
    context: TenantDependency,
) -> APIKeyCreated:
    require_capability(context, Capability.API_KEY_MANAGE)
    scopes = frozenset(body.scopes)
    if not scopes.issubset(context.capabilities):
        raise AuthorizationDenied
    issued = await create_api_key(
        session,
        context=context,
        name=body.name,
        scopes=scopes,
        expires_at=body.expires_at,
        correlation_id=uuid.UUID(request.state.request_id),
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    return APIKeyCreated(
        id=issued.id,
        name=issued.name,
        prefix=issued.prefix,
        token=issued.token,
        scopes=sorted(issued.scopes, key=lambda item: item.value),
        expires_at=issued.expires_at,
    )


@router.post("/{api_key_id}/revoke", response_model=APIKeyRevokedResponse)
async def revoke_current_api_key(
    api_key_id: uuid.UUID,
    request: Request,
    session: SessionDependency,
    context: TenantDependency,
) -> APIKeyRevokedResponse:
    require_capability(context, Capability.API_KEY_MANAGE)
    model = await revoke_api_key(
        session,
        context=context,
        api_key_id=api_key_id,
        correlation_id=uuid.UUID(request.state.request_id),
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    return APIKeyRevokedResponse(id=model.id, revoked=True)
