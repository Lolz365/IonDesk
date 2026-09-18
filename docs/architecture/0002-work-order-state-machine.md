# ADR 0002: Versioned work-order state machine

- Status: Accepted for implementation in Phase 4
- Date: 2026-09-18

## Context

Facilities and property operations require a durable lifecycle with assignment,
field execution, review, SLA handling, and an auditable completion record. The
prototype's open/resolved flag cannot represent that process safely.

## Decision

The first state-machine version is:

```text
new -> triaged -> scheduled -> assigned -> in_progress -> awaiting_review
                                                        -> resolved -> closed
```

Allowed exceptions are:

- `new`, `triaged`, `scheduled`, `assigned`, or `in_progress` to `cancelled`
- `awaiting_review` to `in_progress`
- `resolved` to `reopened`
- `reopened` to `triaged`

`closed` and `cancelled` are terminal in this version. A transition is an
explicit server-side command, never a generic status-field update. Each command
must validate the expected resource version, actor capability, tenant context,
required transition data, and current state. A successful transition writes its
work-order event and audit event in the same transaction. Side effects leave
through a transactional outbox.

Stable external work-order numbers (for example `WO-1042`) remain distinct from
internal UUID primary keys. The state-machine version is retained with history
so later process changes do not reinterpret earlier events.

## Consequences

- Invalid and stale transitions can be rejected consistently.
- Reporting can use immutable transition history rather than inferred dates.
- Phase 1 contains no implementation of this state machine; this ADR constrains
  the later work rather than claiming it exists today.
