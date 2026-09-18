# Phase 2 RED/GREEN record

Commands were run from `apps/api` on 2026-09-18. Output below is the exact
pytest result summary from each TDD slice; full tracebacks remain available in
the implementation session transcript.

## Schema and migration contract

RED:

```text
$ uv run pytest tests/test_models.py -q
ERROR tests/test_models.py
E   ModuleNotFoundError: No module named 'sqlalchemy'
1 error in 0.12s
EXIT_CODE=2
```

GREEN:

```text
$ uv run pytest tests/test_models.py -q
..                                                                       [100%]
2 passed in 0.75s
EXIT_CODE=0
```

## Capability authorization and immutable tenant context

RED:

```text
$ uv run pytest tests/test_authorization.py -q
ERROR tests/test_authorization.py
E   ModuleNotFoundError: No module named 'app.services'
1 error in 0.11s
EXIT_CODE=2
```

GREEN:

```text
$ uv run pytest tests/test_authorization.py -q
........                                                                 [100%]
8 passed in 0.26s
EXIT_CODE=0
```

## Tenant-scoped API and transactional audit/outbox

The first fixture run exposed a portable-schema defect before reaching the
intended boundary (`sqlite3.OperationalError: no such function: char_length`).
The constraint was changed to portable SQL `length(...)`, then the focused RED
was rerun:

```text
$ uv run pytest tests/integration/test_tenant_isolation.py -q
ERROR tests/integration/test_tenant_isolation.py::test_organization_a_cannot_read_organization_b_by_guessed_uuid
E   TypeError: create_app() got an unexpected keyword argument 'session_factory'
1 error in 0.21s
EXIT_CODE=1
```

GREEN:

```text
$ uv run pytest tests/integration/test_tenant_isolation.py tests/integration/test_audit_events.py -q
...                                                                      [100%]
3 passed in 0.16s
EXIT_CODE=0
```

## Constraint and immutability enforcement

RED (the role check already passed; the two immutability contracts failed):

```text
$ uv run pytest tests/integration/test_constraints.py -q
.FF                                                                      [100%]
2 failed, 1 passed in 0.15s
EXIT_CODE=1
```

GREEN:

```text
$ uv run pytest tests/integration/test_constraints.py -q
...                                                                      [100%]
3 passed in 0.11s
EXIT_CODE=0
```

## PostgreSQL availability

The explicitly marked PostgreSQL proof did not run locally; no disposable URL
was supplied:

```text
$ uv run pytest tests/integration/test_postgresql_foundation.py -q -rs
s                                                                        [100%]
SKIPPED [1] tests/integration/test_postgresql_foundation.py:61: VISUALOPS_TEST_DATABASE_URL is not set
1 skipped in 0.01s
EXIT_CODE=0
```

The final formatted file moved that skip site from line 61 to line 59; the
final-suite output is reported in the implementation handoff.
