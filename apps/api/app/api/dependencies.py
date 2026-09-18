from __future__ import annotations

import uuid
from typing import Annotated, Protocol

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.api_keys import InvalidAPIKey, authenticate_api_key
from app.services.authentication import InvalidCredential, resolve_oidc_context
from app.services.authorization import AuthenticationRequired, TenantContext
from app.services.rate_limits import RateLimiter


class TokenValidator(Protocol):
    async def validate(self, token: str) -> str: ...


def _anonymous_bucket(request: Request) -> str:
    address = request.client.host if request.client else "unknown"
    return f"anonymous:{address}"


async def authenticate_request(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantContext:
    settings = request.app.state.settings
    limiter: RateLimiter = request.app.state.rate_limiter
    authorization = request.headers.get("authorization", "")
    try:
        scheme, token = authorization.split(" ", 1)
        if not token or " " in token:
            raise InvalidCredential
        if scheme.lower() == "bearer":
            organization_id = uuid.UUID(request.headers.get("x-organization-id", ""))
            validator: TokenValidator = request.app.state.oidc_validator
            subject = await validator.validate(token)
            context = await resolve_oidc_context(
                session, subject=subject, organization_id=organization_id
            )
        elif scheme.lower() == "apikey":
            context = await authenticate_api_key(session, token)
        else:
            raise InvalidCredential
    except (InvalidAPIKey, InvalidCredential, ValueError):
        try:
            await limiter.check(
                _anonymous_bucket(request),
                limit=settings.anonymous_rate_limit,
                window_seconds=settings.rate_limit_window_seconds,
            )
        except Exception as rate_error:
            from app.services.rate_limits import RateLimitExceeded

            if isinstance(rate_error, RateLimitExceeded):
                raise
            raise RateLimitPassthrough from rate_error
        raise AuthenticationRequired from None

    await limiter.check(
        context.credential_id,
        limit=settings.authenticated_rate_limit,
        window_seconds=settings.rate_limit_window_seconds,
    )
    await session.commit()
    request.state.tenant_context = context
    return context


class RateLimitPassthrough(Exception):
    """Internal marker for an unavailable rate-limit backend."""
