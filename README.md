# VisualOps

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
