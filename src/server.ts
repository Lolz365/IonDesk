import { randomUUID } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { analyzeTicketPhoto, createAndSaveTicketWithPhotos, listTicketsPage, resolveTicket, validateAndSavePhotoUpload, type PhotoSignal } from "./index.ts";
import { FilePhotoStorage, FileTicketRepository, validateResourceId } from "./file-storage.ts";

const MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024;

class HttpError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const UI = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>VisualOps</title>
  <style>
    :root { color-scheme: light dark; font: 16px/1.5 system-ui, sans-serif; }
    body { margin: 0; background: #eef2f6; color: #172033; }
    main { width: min(64rem, calc(100% - 2rem)); margin: 2rem auto; }
    section { background: white; border-radius: .75rem; padding: 1.25rem; margin-block: 1rem; box-shadow: 0 .15rem .8rem #17203318; }
    label { display: block; font-weight: 650; margin-top: .75rem; }
    input, textarea, button { box-sizing: border-box; font: inherit; }
    input, textarea { width: 100%; padding: .6rem; border: 1px solid #8994a7; border-radius: .35rem; }
    button { margin-top: 1rem; padding: .6rem 1rem; border: 0; border-radius: .35rem; background: #075bc7; color: white; cursor: pointer; }
    .hint { color: #4a5568; } .ticket-list { list-style: none; padding: 0; } .ticket-list button { width: 100%; text-align: left; } pre { white-space: pre-wrap; }
    @media (prefers-color-scheme: dark) { body { background: #111827; color: #eef2f6; } section { background: #1f2937; } .hint { color: #cbd5e1; } }
  </style>
</head>
<body><main>
  <h1>VisualOps</h1>
  <section aria-labelledby="create-heading">
    <h2 id="create-heading">Create ticket</h2>
    <form id="ticket-form">
      <label for="ticket-title">Title</label><input id="ticket-title" name="title" required>
      <label for="ticket-description">Description</label><textarea id="ticket-description" name="description"></textarea>
      <label for="ticket-photo">Photo (JPEG, PNG, or WebP; max 10 MiB)</label><input id="ticket-photo" name="photo" type="file" accept="image/jpeg,image/png,image/webp">
      <button type="submit">Create ticket</button>
    </form>
  </section>
  <section aria-labelledby="tickets-heading"><h2 id="tickets-heading">Tickets</h2><div id="tickets" aria-live="polite">No tickets yet.</div></section>
  <section aria-labelledby="detail-heading"><h2 id="detail-heading">Ticket details</h2><div id="ticket-detail">Select a ticket.</div><button id="resolve" type="button" disabled>Resolve ticket</button></section>
  <section aria-labelledby="signals-heading">
    <h2 id="signals-heading">Photo signals</h2>
    <p class="hint">Signals are user-supplied labels and confidence values (0–1). VisualOps applies deterministic domain rules; no vision API is called.</p>
    <label for="signal-label">Signal label</label><input id="signal-label" placeholder="e.g. standing water">
    <label for="signal-confidence">Confidence</label><input id="signal-confidence" type="number" min="0" max="1" step="0.01" value="0.8">
    <button id="analyze" type="button" disabled>Analyze supplied signal</button>
    <pre id="analysis-result" aria-live="polite"></pre>
  </section>
  <div id="status" role="status" aria-live="polite"></div>
</main>
<script type="module">
  const form = document.querySelector("#ticket-form");
  const ticketsView = document.querySelector("#tickets");
  const detail = document.querySelector("#ticket-detail");
  const resolveButton = document.querySelector("#resolve");
  const analyzeButton = document.querySelector("#analyze");
  const status = document.querySelector("#status");
  let selected;

  async function request(path, options) {
    const response = await fetch(path, options);
    const value = await response.json();
    if (!response.ok) throw new Error(value.error?.message || "Request failed");
    return value;
  }

  function showTicket(ticket) {
    selected = ticket;
    detail.textContent = ticket.title + " — " + ticket.status + (ticket.description ? ": " + ticket.description : "");
    resolveButton.disabled = ticket.status !== "open";
    analyzeButton.disabled = ticket.status !== "open" || ticket.photoIds.length === 0;
  }

  async function loadTickets() {
    const page = await request("/api/tickets");
    ticketsView.replaceChildren();
    if (page.tickets.length === 0) { ticketsView.textContent = "No tickets yet."; return; }
    const list = document.createElement("ul"); list.className = "ticket-list";
    for (const ticket of page.tickets) {
      const item = document.createElement("li"); const button = document.createElement("button");
      button.type = "button"; button.textContent = ticket.title + " (" + ticket.status + ")";
      button.addEventListener("click", async () => showTicket(await request("/api/tickets/" + encodeURIComponent(ticket.id))));
      item.append(button); list.append(item);
    }
    ticketsView.append(list);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault(); status.textContent = "Creating ticket…";
    try {
      const photo = document.querySelector("#ticket-photo").files[0];
      const photoIds = [];
      if (photo) {
        const uploaded = await request("/api/photos", { method: "POST", headers: { "content-type": photo.type }, body: photo });
        photoIds.push(uploaded.id);
      }
      const ticket = await request("/api/tickets", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
        title: document.querySelector("#ticket-title").value,
        description: document.querySelector("#ticket-description").value,
        photoIds
      }) });
      form.reset(); showTicket(ticket); await loadTickets(); status.textContent = "Ticket created.";
    } catch (error) { status.textContent = error.message; }
  });

  resolveButton.addEventListener("click", async () => {
    if (!selected) return;
    try { showTicket(await request("/api/tickets/" + encodeURIComponent(selected.id) + "/resolve", { method: "POST" })); await loadTickets(); status.textContent = "Ticket resolved."; }
    catch (error) { status.textContent = error.message; }
  });

  analyzeButton.addEventListener("click", async () => {
    if (!selected?.photoIds[0]) return;
    try {
      const signals = [{ label: document.querySelector("#signal-label").value, confidence: Number(document.querySelector("#signal-confidence").value) }];
      const result = await request("/api/tickets/" + encodeURIComponent(selected.id) + "/photos/" + encodeURIComponent(selected.photoIds[0]) + "/analyze", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ signals }) });
      document.querySelector("#analysis-result").textContent = result.summary + " Confidence: " + result.confidence;
    } catch (error) { status.textContent = error.message; }
  });

  loadTickets().catch((error) => { status.textContent = error.message; });
</script>
</body></html>`;

function send(response: ServerResponse, status: number, contentType: string, body: string): void {
  response.writeHead(status, { "content-type": contentType, "content-length": Buffer.byteLength(body) });
  response.end(body);
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  send(response, status, "application/json; charset=utf-8", JSON.stringify(value));
}

async function readJson(request: IncomingMessage): Promise<Record<string, unknown>> {
  const contentType = (request.headers["content-type"] ?? "")
    .split(";", 1)[0]
    .trim()
    .toLowerCase();
  if (contentType !== "application/json") {
    throw new Error("content-type must be application/json");
  }
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.from(chunk);
    size += buffer.length;
    if (size > 1024 * 1024) {
      throw new HttpError(413, "payload_too_large", "JSON body must not exceed 1 MiB");
    }
    chunks.push(buffer);
  }
  try {
    const value: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    return value as Record<string, unknown>;
  } catch {
    throw new Error("body must be a JSON object");
  }
}

function errorStatus(message: string): number {
  return message.includes("does not exist") ? 404 : 400;
}

function safeId(encoded: string): string {
  return validateResourceId(decodeURIComponent(encoded));
}

async function readPhoto(request: IncomingMessage): Promise<Buffer> {
  const declaredSize = Number(request.headers["content-length"] ?? 0);
  if (declaredSize > MAX_PHOTO_SIZE_BYTES) {
    throw new HttpError(413, "payload_too_large", "photo must not exceed 10 MiB");
  }
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_PHOTO_SIZE_BYTES) {
      throw new HttpError(413, "payload_too_large", "photo must not exceed 10 MiB");
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks);
}

function photoBytesMatchContentType(bytes: Buffer, contentType: string): boolean {
  if (contentType === "image/jpeg") {
    return bytes.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff]));
  }
  if (contentType === "image/png") {
    return bytes.subarray(0, 8).equals(
      Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    );
  }
  if (contentType === "image/webp") {
    return bytes.subarray(0, 4).toString("ascii") === "RIFF"
      && bytes.subarray(8, 12).toString("ascii") === "WEBP";
  }
  return true;
}

async function main(): Promise<void> {
  const host = process.env.HOST || "127.0.0.1";
  const port = Number(process.env.PORT || "3081");
  if (!Number.isInteger(port) || port < 0 || port > 65_535) throw new Error("PORT must be an integer between 0 and 65535");
  const dataDir = process.env.DATA_DIR || "./data";
  const repository = await FileTicketRepository.open(dataDir);
  const photoStorage = await FilePhotoStorage.open(dataDir);

  const server = createServer(async (request, response) => {
    response.setHeader("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");
    response.setHeader("X-Content-Type-Options", "nosniff");
    response.setHeader("X-Frame-Options", "DENY");
    response.setHeader("Referrer-Policy", "no-referrer");
    const url = new URL(request.url ?? "/", "http://localhost");
    const pathname = url.pathname;
    try {
      if (request.method === "GET" && pathname === "/health") {
        sendJson(response, 200, { status: "ok" });
        return;
      }
      if (pathname === "/health") {
        response.setHeader("Allow", "GET");
        sendJson(response, 405, {
          error: {
            code: "method_not_allowed",
            message: `Method ${request.method} is not allowed for /health`,
          },
        });
        return;
      }
      if (request.method === "GET" && pathname === "/") {
        response.setHeader("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'");
        send(response, 200, "text/html; charset=utf-8", UI);
        return;
      }
      if (pathname === "/") {
        response.setHeader("Allow", "GET");
        sendJson(response, 405, {
          error: {
            code: "method_not_allowed",
            message: `Method ${request.method} is not allowed for /`,
          },
        });
        return;
      }
      if (request.method === "POST" && pathname === "/api/tickets") {
        const body = await readJson(request);
        if ("photoIds" in body && !Array.isArray(body.photoIds)) throw new Error("photoIds must be an array");
        const ticket = await createAndSaveTicketWithPhotos(repository, photoStorage, {
          id: randomUUID(),
          title: typeof body.title === "string" ? body.title : "",
          ...(typeof body.description === "string" ? { description: body.description } : {}),
          photoIds: Array.isArray(body.photoIds) ? body.photoIds as string[] : [],
        });
        sendJson(response, 201, ticket);
        return;
      }
      if (request.method === "GET" && pathname === "/api/tickets") {
        if (url.searchParams.has("cursor") && !url.searchParams.has("limit")) {
          throw new HttpError(400, "validation_error", "cursor requires an explicit limit");
        }
        if (url.searchParams.has("limit")) {
          const limit = Number(url.searchParams.get("limit"));
          const cursor = url.searchParams.get("cursor");
          sendJson(response, 200, await listTicketsPage(repository, {
            limit,
            ...(cursor === null ? {} : { cursor }),
          }));
          return;
        }
        sendJson(response, 200, { tickets: await repository.list() });
        return;
      }
      if (pathname === "/api/tickets") {
        response.setHeader("Allow", "GET, POST");
        sendJson(response, 405, {
          error: {
            code: "method_not_allowed",
            message: `Method ${request.method} is not allowed for /api/tickets`,
          },
        });
        return;
      }
      if (request.method === "POST" && pathname === "/api/photos") {
        const contentType = (request.headers["content-type"] ?? "")
          .split(";", 1)[0]
          .trim()
          .toLowerCase();
        const bytes = await readPhoto(request);
        if (!photoBytesMatchContentType(bytes, contentType)) {
          throw new Error(`photo bytes do not match contentType ${contentType}`);
        }
        const photo = await validateAndSavePhotoUpload(photoStorage, {
          id: randomUUID(), contentType, sizeBytes: bytes.length,
        });
        await photoStorage.saveBytes(photo.id, bytes);
        sendJson(response, 201, photo);
        return;
      }
      if (pathname === "/api/photos") {
        response.setHeader("Allow", "POST");
        sendJson(response, 405, {
          error: {
            code: "method_not_allowed",
            message: `Method ${request.method} is not allowed for /api/photos`,
          },
        });
        return;
      }
      const photoMatch = pathname.match(/^\/api\/photos\/([^/]+)$/);
      if (request.method === "GET" && photoMatch) {
        const id = safeId(photoMatch[1]);
        const photo = await photoStorage.findById(id);
        const bytes = await photoStorage.readBytes(id);
        if (!photo || !bytes) throw new Error(`Photo with id "${id}" does not exist`);
        response.writeHead(200, { "content-type": photo.contentType, "content-length": bytes.length });
        response.end(bytes);
        return;
      }
      if (photoMatch && request.method !== "GET") {
        let validPhotoId = true;
        try {
          safeId(photoMatch[1]);
        } catch {
          validPhotoId = false;
        }
        if (validPhotoId) {
          response.setHeader("Allow", "GET");
          sendJson(response, 405, {
            error: {
              code: "method_not_allowed",
              message: `Method ${request.method} is not allowed for /api/photos/:id`,
            },
          });
          return;
        }
      }
      const analysisMatch = pathname.match(/^\/api\/tickets\/([^/]+)\/photos\/([^/]+)\/analyze$/);
      if (request.method === "POST" && analysisMatch) {
        const body = await readJson(request);
        if (!Array.isArray(body.signals)) throw new Error("signals must be an array");
        const signals = body.signals as PhotoSignal[];
        const draft = await analyzeTicketPhoto(repository, {
          async analyzePhoto() { return signals; },
        }, { ticketId: safeId(analysisMatch[1]), photoId: safeId(analysisMatch[2]) });
        sendJson(response, 200, draft);
        return;
      }
      if (analysisMatch) {
        response.setHeader("Allow", "POST");
        sendJson(response, 405, {
          error: {
            code: "method_not_allowed",
            message: `Method ${request.method} is not allowed for /api/tickets/:ticketId/photos/:photoId/analyze`,
          },
        });
        return;
      }
      const resolveMatch = pathname.match(/^\/api\/tickets\/([^/]+)\/resolve$/);
      if (request.method === "POST" && resolveMatch) {
        sendJson(response, 200, await resolveTicket(repository, safeId(resolveMatch[1])));
        return;
      }
      if (resolveMatch) {
        let validTicketId = true;
        try {
          safeId(resolveMatch[1]);
        } catch {
          validTicketId = false;
        }
        if (validTicketId) {
          response.setHeader("Allow", "POST");
          sendJson(response, 405, {
            error: {
              code: "method_not_allowed",
              message: `Method ${request.method} is not allowed for /api/tickets/:id/resolve`,
            },
          });
          return;
        }
      }
      const ticketMatch = pathname.match(/^\/api\/tickets\/([^/]+)$/);
      if (request.method === "GET" && ticketMatch) {
        const id = safeId(ticketMatch[1]);
        const ticket = await repository.findById(id);
        if (!ticket) throw new Error(`Ticket with id "${id}" does not exist`);
        sendJson(response, 200, ticket);
        return;
      }
      if (ticketMatch && request.method !== "GET") {
        let validTicketId = true;
        try {
          safeId(ticketMatch[1]);
        } catch {
          validTicketId = false;
        }
        if (validTicketId) {
          response.setHeader("Allow", "GET");
          sendJson(response, 405, {
            error: {
              code: "method_not_allowed",
              message: `Method ${request.method} is not allowed for /api/tickets/:id`,
            },
          });
          return;
        }
      }
      sendJson(response, 404, { error: { code: "not_found", message: "Route not found" } });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Invalid request";
      const status = error instanceof HttpError ? error.status : errorStatus(message);
      const code = error instanceof HttpError ? error.code : status === 404 ? "not_found" : "validation_error";
      sendJson(response, status, { error: { code, message } });
    }
  });

  server.listen(port, host, () => {
    const address = server.address();
    const actualPort = typeof address === "object" && address ? address.port : port;
    console.log(`Listening on http://${host}:${actualPort}`);
  });
  const close = () => server.close(() => process.exit(0));
  process.on("SIGTERM", close);
  process.on("SIGINT", close);
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
