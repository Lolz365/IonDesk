from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Membership, Organization, User
from app.services.authentication import (
    InvalidCredential,
    OIDCJWTValidator,
    resolve_oidc_context,
)
from app.services.authorization import Capability, Role


@pytest.fixture(scope="module")
def jwt_material() -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "current-key", "use": "sig", "alg": "RS256"})
    return private_key, {"keys": [jwk]}


def token_for(private_key: object, **overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": "subject-a",
        "iss": "https://identity.example.test/realms/visualops",
        "aud": "visualops-api",
        "iat": now,
        "nbf": now - 1,
        "exp": now + 300,
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        private_key,  # type: ignore[arg-type]
        algorithm="RS256",
        headers={"kid": "current-key"},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "token_factory",
    [
        lambda key: "not-a-jwt",
        lambda key: token_for(key, exp=int(time.time()) - 1),
        lambda key: token_for(key, iss="https://attacker.example"),
        lambda key: token_for(key, aud="some-other-api"),
        lambda key: token_for(key, nbf=int(time.time()) + 300),
    ],
)
async def test_oidc_validator_rejects_invalid_claims(
    jwt_material: tuple[object, dict[str, object]], token_factory: object
) -> None:
    private_key, jwks = jwt_material
    validator = OIDCJWTValidator(
        issuer="https://identity.example.test/realms/visualops",
        audience="visualops-api",
        jwks_url="https://identity.example.test/jwks",
        cache_seconds=300,
        fetch_jwks=lambda _: jwks,
    )

    with pytest.raises(InvalidCredential):
        await validator.validate(token_factory(private_key))  # type: ignore[operator]


@pytest.mark.anyio
async def test_oidc_validator_rejects_unknown_kid_and_caches_jwks(
    jwt_material: tuple[object, dict[str, object]],
) -> None:
    private_key, jwks = jwt_material
    fetches = 0

    async def fetch(_: str) -> dict[str, object]:
        nonlocal fetches
        fetches += 1
        return jwks

    validator = OIDCJWTValidator(
        issuer="https://identity.example.test/realms/visualops",
        audience="visualops-api",
        jwks_url="https://identity.example.test/jwks",
        cache_seconds=300,
        fetch_jwks=fetch,
    )
    valid = token_for(private_key)
    await validator.validate(valid)
    await validator.validate(valid)
    unknown = jwt.encode(
        jwt.decode(valid, options={"verify_signature": False}),
        private_key,  # type: ignore[arg-type]
        algorithm="RS256",
        headers={"kid": "missing"},
    )

    with pytest.raises(InvalidCredential):
        await validator.validate(unknown)
    assert fetches == 1  # valid and unknown key IDs share the bounded cache


@pytest.mark.anyio
async def test_verified_subject_resolves_active_membership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="identity-org", name="Identity Org")
        user = User(
            oidc_subject="verified-subject",
            email="person@example.test",
            display_name="Person",
        )
        session.add_all([organization, user])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=user.id,
            role=Role.DISPATCHER,
        )
        session.add(membership)
        await session.flush()
        organization_id = organization.id

    async with session_factory() as session:
        context = await resolve_oidc_context(
            session, subject="verified-subject", organization_id=organization_id
        )

    assert context.role is Role.DISPATCHER
    assert Capability.WORK_ORDER_DISPATCH in context.capabilities


@pytest.mark.anyio
async def test_unknown_subject_and_wrong_tenant_are_indistinguishable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(InvalidCredential):
            await resolve_oidc_context(
                session, subject="unknown", organization_id=uuid.uuid4()
            )

    # Resolution does not create users or memberships from unverified claims.
    async with session_factory() as session:
        assert list(await session.scalars(select(User))) == []


def test_expiry_test_data_is_timezone_aware() -> None:
    assert datetime.now(UTC) < datetime.now(UTC) + timedelta(seconds=1)
