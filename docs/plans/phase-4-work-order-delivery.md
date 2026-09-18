# Phase 4 work-order delivery plan

## Objective

Turn the tenant-scoped ticket foundation into the first reliable facilities work-order workflow without changing the legacy demo or its deployment route.

## Architectural boundary

The FastAPI service remains the synchronous command/query boundary. PostgreSQL remains the source of truth; audit and outbox entries are written in the same transaction as a successful command. Celery publishes or processes asynchronous side effects only after the outbox handoff. The Next.js application consumes the versioned API rather than duplicating domain rules.

The existing `tickets` endpoint is a foundation API. Phase 4 must align its lifecycle with ADR 0002 before representing it as the product work-order workflow. In particular, a generic status patch is not the long-term command contract.

## Delivery sequence

1. **Keep the quality gate executable.**
   - Repair CI configuration, formatting drift, and known runtime dependency vulnerabilities.
   - Require API tests, static analysis, OpenAPI validation, container build validation, and dependency audit to pass before feature work is merged.

2. **Define the work-order aggregate.**
   - Add a stable external work-order number, optimistic version, lifecycle version, timestamps, priority, site/location reference, requester, assignee, and cancellation/resolution data.
   - Add an immutable transition/event history. Keep UUIDs as internal IDs.
   - Add a forward-only Alembic migration and PostgreSQL migration proof; do not alter the legacy JSON store.

3. **Replace generic state mutation with explicit commands.**
   - Implement typed commands for triage, scheduling, assignment, start, submit for review, resolve, close, cancel, reopen, and return to work.
   - Validate tenant scope, resource version, capability, required transition fields, and current state inside one transaction.
   - Preserve audit and transactional-outbox writes for every successful command.

4. **Provide contract-first read models.**
   - Add tenant-scoped list filters for lifecycle state, assignee, site, priority, and time window.
   - Use stable sorting and cursor pagination; return resource version and lifecycle metadata.
   - Publish the revised OpenAPI contract and deprecate the foundation ticket endpoints only after consumers migrate.

5. **Build a vertical web slice.**
   - Implement authenticated work-order list, detail, and role-aware command actions in `apps/web`.
   - Surface command conflicts and authorization denials clearly; do not expose internal identifiers or cross-tenant data.
   - Test browser-visible workflows against the API contract.

6. **Operationalize before cutover.**
   - Add outbox delivery observability, retry/dead-letter handling, structured correlation IDs, and SLA event hooks.
   - Exercise migrations and rollback on a disposable PostgreSQL environment.
   - Keep the enterprise topology unpublished except through Caddy on its existing loopback binding until an explicit cutover decision.

## Quality gates per increment

- Write a failing API/integration test before domain behavior.
- Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`, and `uv run pytest -W error` from `apps/api`.
- Validate the generated OpenAPI document and build API, worker, and web containers.
- Run dependency and secret scans in CI.
- Keep each independently reviewable increment in a focused commit and pull request.

## Non-goals for this phase

- No replacement of the root legacy demo or its Tailscale route.
- No direct public exposure of PostgreSQL, Redis, or object storage.
- No external OIDC-provider deployment or production-route cutover without a separate approval.
