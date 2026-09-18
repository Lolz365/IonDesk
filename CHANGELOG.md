# Changelog

All notable changes to VisualOps will be documented here.

## Unreleased

- Prevented caching of API-key creation responses that contain one-time secrets.
- Added `Cross-Origin-Resource-Policy: same-origin` to every API response.
- Fixed ticket creation to reject non-string descriptions with a stable
  validation error instead of silently discarding them.
- Fixed oversized ticket JSON requests to return a stable 413
  `payload_too_large` error.
- Fixed ticket creation to reject non-string photo IDs with a stable validation
  error instead of exposing an internal type error.
- Added the Phase 3 identity boundary: validated OIDC JWTs, tenant membership
  resolution, scoped one-time service API keys, audit events, and Redis-backed
  per-credential and anonymous API rate limits.
- Added the tenant-aware PostgreSQL foundation, initial Alembic migration,
  capability roles, append-only audit log, and transactional outbox.

### Added

- Enterprise foundation for the facilities and property operations vertical.
