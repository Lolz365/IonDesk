# VisualOps

VisualOps is evolving into an enterprise operations command center. Facilities
and property operations is the confirmed initial product vertical.

## Repository status

The dependency-free Node.js application at the repository root remains the
deployed `legacy-demo`. Its root `Dockerfile`, `docker-compose.yml`, and current
Tailscale route remain independent of the enterprise foundation and must not be
changed during this phase.

The production-shaped foundation lives alongside it:

- `apps/api`: FastAPI, tenant context, SQLAlchemy models, and Alembic migrations
- `apps/worker`: Celery queue and scheduler configuration
- `apps/web`: protected-edge command-center placeholder (no product workflows)
- `infra/compose`: isolated PostgreSQL, Redis, MinIO, application, and Caddy
  staging topology

Architecture decisions are in `docs/architecture`. The current enterprise
foundation includes tenant-scoped organization access, validated OIDC access
tokens, scoped service API keys, capability-based roles, append-only audit
records, rate limits, and a transactional outbox. Work orders and UI workflows
remain later phases. Keycloak is not deployed by this phase; configure an
existing OIDC issuer, audience, and JWKS URL through environment variables.

## Enterprise foundation validation

Copy the variable names from `infra/compose/.env.example` into an ignored
`infra/compose/.env` and supply locally generated staging secrets and connection
URLs. The example intentionally contains no values. Generate a Caddy-compatible
password hash with `docker run --rm caddy:2.11.4-alpine caddy hash-password`.

Validate without starting the stack:

```sh
docker compose -f infra/compose/compose.staging.yml config
docker compose -f infra/compose/compose.staging.yml build api worker web
```

Caddy is the only published service, at `127.0.0.1:3181`. No Tailscale setup is
part of this repository. See `CONTRIBUTING.md` for quality and change policies.

## Database migrations

API and worker processes never modify the schema. Staging Compose uses a
separate one-shot `migrate` service and will not start the API until it succeeds.
Set the required values in an ignored environment file, take a database backup,
and inspect the pending revision before applying it once from `apps/api`:

```sh
uv sync --frozen --all-groups
uv run alembic current
uv run alembic upgrade head --sql > /tmp/visualops-upgrade.sql
uv run alembic upgrade head
uv run alembic current
```

For the staging image, build first and run the same one-off operation without
starting dependencies or publishing ports:

```sh
docker compose -f infra/compose/compose.staging.yml build api
docker compose -f infra/compose/compose.staging.yml run --rm --no-deps api alembic upgrade head
```

Run `alembic downgrade base` only against a disposable database when rehearsing
rollback; it removes all foundation tables. Never run concurrent migrations
from API or worker replicas. Tests use a temporary SQLite database for the fast
transaction suite. To exercise the marked PostgreSQL suite, migrate a disposable
PostgreSQL database with Alembic, then point `VISUALOPS_TEST_DATABASE_URL` at it.
The proof checks the migration revision and tests the migrated schema directly.

## Legacy demo

VisualOps is a dependency-free Node.js vertical slice for maintenance tickets.
It stores ticket records, photo metadata, and uploaded JPEG/PNG/WebP bytes on
disk. Photo analysis is deterministic: the caller supplies labels and
confidence scores; no vision service is contacted.

## Run locally

Node.js 22 or newer is required. From the repository root:

```sh
DATA_DIR=./data npm start
```

Open <http://127.0.0.1:3081>. `HOST`, `PORT`, and `DATA_DIR` are configurable;
their defaults are `127.0.0.1`, `3081`, and `./data`.

Run the domain and process-level integration tests with:

```sh
npm test
```

## REST API

All errors use `{ "error": { "code": "…", "message": "…" } }` JSON.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness response |
| `POST` | `/api/photos` | Upload raw image bytes; set `Content-Type` to `image/jpeg`, `image/png`, or `image/webp` (10 MiB maximum) |
| `GET` | `/api/photos/:id` | Retrieve original image bytes |
| `POST` | `/api/tickets` | Create from JSON `{ "title", "description"?, "photoIds"? }` |
| `GET` | `/api/tickets` | List tickets |
| `GET` | `/api/tickets/:id` | Get one ticket |
| `POST` | `/api/tickets/:id/resolve` | Resolve an open ticket |
| `POST` | `/api/tickets/:ticketId/photos/:photoId/analyze` | Analyze JSON `{ "signals": [{ "label", "confidence" }] }` |

Confidence values from `0.80` through `1.00` are findings, values from `0.50`
through `0.79` require review, and lower values are ignored. The photo must
already be attached to the open ticket.

## Deploy with Docker

Build directly with `docker build -t visualops .`, or run
`docker compose up -d --build`. Compose publishes only
`127.0.0.1:3081`, persists `/data` in the `visualops-data` named volume, and
uses the `unless-stopped` restart policy. The image runs as the non-root
`node` user on `node:26.7.0-alpine`.
