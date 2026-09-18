from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.authorization import (
    Capability,
    TenantContext,
    get_tenant_context,
    require_capability,
)
from app.services.organizations import (
    get_tenant_organization,
    rename_current_organization,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
TenantDependency = Annotated[TenantContext, Depends(get_tenant_context)]


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    identifier: str
    name: str


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: uuid.UUID,
    session: SessionDependency,
    context: TenantDependency,
) -> OrganizationResponse:
    require_capability(context, Capability.ORGANIZATION_READ)
    organization = await get_tenant_organization(
        session, context=context, organization_id=organization_id
    )
    return OrganizationResponse.model_validate(organization)


@router.patch("/current", response_model=OrganizationResponse)
async def update_current_organization(
    body: OrganizationUpdate,
    request: Request,
    session: SessionDependency,
    context: TenantDependency,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=200,
            pattern=r"\S",
        ),
    ] = None,
) -> OrganizationResponse:
    require_capability(context, Capability.ORGANIZATION_UPDATE)
    request_id = uuid.UUID(request.state.request_id)
    organization = await rename_current_organization(
        session,
        context=context,
        name=body.name,
        correlation_id=request_id,
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        idempotency_key=idempotency_key,
    )
    return OrganizationResponse.model_validate(organization)
