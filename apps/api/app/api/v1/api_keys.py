from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.api_keys import create_api_key, list_api_keys, revoke_api_key
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

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()

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
            self.expires_at = candidate
        return self


class APIKeyCreated(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    token: str
    scopes: list[Capability]
    expires_at: datetime | None


class APIKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[Capability]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class APIKeyRevokedResponse(BaseModel):
    id: uuid.UUID
    revoked: bool


@router.post("", response_model=APIKeyCreated)
async def issue_api_key(
    body: APIKeyCreate,
    request: Request,
    response: Response,
    session: SessionDependency,
    context: TenantDependency,
) -> APIKeyCreated:
    require_capability(context, Capability.API_KEY_MANAGE)
    if context.membership_id is None:
        raise AuthorizationDenied
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
    response.headers["Cache-Control"] = "no-store"
    return APIKeyCreated(
        id=issued.id,
        name=issued.name,
        prefix=issued.prefix,
        token=issued.token,
        scopes=sorted(issued.scopes, key=lambda item: item.value),
        expires_at=issued.expires_at,
    )


@router.get("", response_model=list[APIKeyResponse])
async def get_api_keys(
    response: Response,
    session: SessionDependency,
    context: TenantDependency,
) -> list[APIKeyResponse]:
    require_capability(context, Capability.API_KEY_MANAGE)
    models = await list_api_keys(session, context=context)
    response.headers["Cache-Control"] = "no-store"
    return [
        APIKeyResponse(
            id=model.id,
            name=model.name,
            prefix=model.key_prefix,
            scopes=model.scopes,
            expires_at=model.expires_at,
            revoked_at=model.revoked_at,
            last_used_at=model.last_used_at,
            created_at=model.created_at,
        )
        for model in models
    ]


@router.post("/{api_key_id}/revoke", response_model=APIKeyRevokedResponse)
async def revoke_current_api_key(
    api_key_id: uuid.UUID,
    request: Request,
    response: Response,
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
    response.headers["Cache-Control"] = "no-store"
    return APIKeyRevokedResponse(id=model.id, revoked=True)
