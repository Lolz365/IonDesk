from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import cast

import httpx
import jwt
from jwt import PyJWK
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership, User
from app.services.authorization import (
    Role,
    TenantContext,
    capabilities_for_role,
)

JWKS = Mapping[str, object]
JWKSFetcher = Callable[[str], JWKS | Awaitable[JWKS]]


class InvalidCredential(Exception):
    """A deliberately detail-free authentication failure."""


async def _default_fetch_jwks(url: str) -> JWKS:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        value = response.json()
    if not isinstance(value, dict):
        raise InvalidCredential
    return cast(JWKS, value)


class OIDCJWTValidator:
    """Validates signed OIDC access tokens against a bounded JWKS cache."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        cache_seconds: int,
        fetch_jwks: JWKSFetcher | None = None,
        algorithms: tuple[str, ...] = ("RS256",),
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks_url = jwks_url
        self._cache_seconds = cache_seconds
        self._fetch_jwks = fetch_jwks or _default_fetch_jwks
        self._algorithms = algorithms
        self._keys: dict[str, PyJWK] = {}
        self._cache_until = 0.0

    async def _refresh(self) -> None:
        result = self._fetch_jwks(self._jwks_url)
        document = await result if inspect.isawaitable(result) else result
        keys = document.get("keys")
        if not isinstance(keys, list):
            raise InvalidCredential
        parsed: dict[str, PyJWK] = {}
        try:
            for value in keys:
                if not isinstance(value, dict) or not isinstance(value.get("kid"), str):
                    continue
                jwk = PyJWK.from_dict(value)
                if jwk.algorithm_name in self._algorithms:
                    parsed[value["kid"]] = jwk
        except (ValueError, jwt.PyJWTError) as error:
            raise InvalidCredential from error
        self._keys = parsed
        self._cache_until = time.monotonic() + self._cache_seconds

    async def validate(self, token: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            algorithm = header.get("alg")
            if not isinstance(kid, str) or algorithm not in self._algorithms:
                raise InvalidCredential
            if time.monotonic() >= self._cache_until:
                await self._refresh()
            key = self._keys.get(kid)
            if key is None:
                raise InvalidCredential
            claims = jwt.decode(
                token,
                key.key,
                algorithms=list(self._algorithms),
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": ["sub", "iss", "aud", "exp", "nbf"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject or len(subject) > 255:
                raise InvalidCredential
            return subject
        except InvalidCredential:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, httpx.HTTPError) as error:
            raise InvalidCredential from error


async def resolve_oidc_context(
    session: AsyncSession, *, subject: str, organization_id: uuid.UUID
) -> TenantContext:
    result = await session.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(
            User.oidc_subject == subject,
            User.is_active.is_(True),
            Membership.organization_id == organization_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise InvalidCredential
    user, membership = row
    try:
        role = Role(membership.role)
    except ValueError as error:
        raise InvalidCredential from error
    return TenantContext(
        organization_id=membership.organization_id,
        user_id=user.id,
        membership_id=membership.id,
        role=role,
        capabilities=capabilities_for_role(role),
        credential_id=f"oidc:{user.id}",
    )
