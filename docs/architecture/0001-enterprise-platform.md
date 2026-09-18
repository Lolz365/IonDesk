# ADR 0001: Incrementally replace the prototype with an enterprise platform

- Status: Accepted
- Date: 2026-09-18
- Initial vertical: Facilities and property operations

## Context

The root Node application is a useful single-user maintenance-ticket demo. Its
anonymous access, JSON-file persistence, synchronous processing, and unversioned
API are not an acceptable base for tenant-isolated enterprise operations. The
currently deployed demo and its Tailscale route are still needed as a reference
during migration.

## Decision

Build a separate enterprise foundation alongside the root demo:

- Next.js provides the eventual authenticated browser application.
- FastAPI owns a versioned HTTP contract and synchronous application behavior.
- PostgreSQL 16 is the future system of record.
- Redis 7 carries Celery messages and operational result data, never business
  truth.
- Celery workers and Beat isolate slow and scheduled work.
- Private S3-compatible storage holds attachments; staging uses MinIO.
- Caddy is the only host-published service, on `127.0.0.1:3181`.

The enterprise Compose project is named `visualops-enterprise`, uses its own
network and named volumes, and does not alter the root Compose project. The
existing route at `https://lolz365.tail717b77.ts.net:3081/` remains the
`legacy-demo` until an explicit cutover decision. This repository does not
configure Tailscale.

The edge requires staging basic authentication. This is only a foundation
control; Phase 3 will introduce validated OIDC identities and tenant-aware
authorization before business APIs are exposed.

## Consequences

- The two implementations coexist temporarily, which adds build and operating
  overhead but makes rollback straightforward.
- Phase 1 proves service boundaries and dependency health only. It does not
  claim identity, tenancy, auditability, or work-order workflows.
- Cutover requires acceptance tests, data migration and rollback plans,
  security review, and a separately approved route change.

## Rejected alternatives

- Extending JSON files and anonymous root-demo endpoints would preserve the
  constraints that make the prototype unsuitable.
- A big-bang replacement would remove the current acceptance reference too
  early.
- Publishing databases, Redis, or object storage to the host would expand the
  staging attack surface without a product need.
