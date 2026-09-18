import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import test from "node:test";

interface RunningServer {
  readonly baseUrl: string;
  readonly process: ChildProcess;
}

async function startServer(dataDir: string): Promise<RunningServer> {
  const child = spawn(process.execPath, ["src/server.ts"], {
    cwd: new URL("..", import.meta.url),
    env: { ...process.env, HOST: "127.0.0.1", PORT: "0", DATA_DIR: dataDir },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const errors: Buffer[] = [];
  child.stderr!.on("data", (chunk: Buffer) => errors.push(chunk));

  return await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      child.kill();
      reject(new Error(`server did not start: ${Buffer.concat(errors)}`));
    }, 5_000);
    child.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`server exited with ${code}: ${Buffer.concat(errors)}`));
    });
    child.stdout!.on("data", (chunk: Buffer) => {
      const match = chunk.toString().match(/Listening on (http:\/\/[^\s]+)/);
      if (match) {
        clearTimeout(timeout);
        resolve({ baseUrl: match[1], process: child });
      }
    });
  });
}

async function stopServer(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await once(child, "exit");
}

test("serves health and an accessible single-page UI from the actual server", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const health = await fetch(`${server.baseUrl}/health`);
    assert.equal(health.status, 200);
    assert.deepEqual(await health.json(), { status: "ok" });

    const ui = await fetch(server.baseUrl);
    assert.equal(ui.status, 200);
    assert.match(ui.headers.get("content-type") ?? "", /^text\/html/);
    const html = await ui.text();
    assert.match(html, /<h1[^>]*>VisualOps<\/h1>/);
    assert.match(html, /<main/);
    assert.match(html, /<label[^>]*for="ticket-title"/);
    assert.match(html, /Create ticket/);
    assert.match(html, /Resolve ticket/);
    assert.match(html, /Signals are user-supplied/);
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("sends baseline security headers for health responses", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/health`);

    assert.deepEqual(
      Object.fromEntries(
        ["x-content-type-options", "x-frame-options", "referrer-policy"]
          .map((name) => [name, response.headers.get(name)]),
      ),
      {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
      },
    );
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("isolates health responses from cross-origin opener contexts", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/health`);

    assert.equal(response.headers.get("cross-origin-opener-policy"), "same-origin");
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("sends a restrictive Content-Security-Policy for health responses", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/health`);

    assert.equal(
      response.headers.get("content-security-policy"),
      "default-src 'none'; frame-ancestors 'none'",
    );
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("allows the inline UI assets in the root Content-Security-Policy", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(server.baseUrl);

    assert.equal(
      response.headers.get("content-security-policy"),
      "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'",
    );
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("sets no-store on API responses without affecting the public UI or health", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const ticketResponse = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "Inspect cache headers" }),
    });
    const photoUploadResponse = await fetch(`${server.baseUrl}/api/photos`, {
      method: "POST",
      headers: { "content-type": "image/png" },
      body: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    });
    const photo = await photoUploadResponse.json() as { id: string };
    const photoDownloadResponse = await fetch(`${server.baseUrl}/api/photos/${photo.id}`);
    const errorResponse = await fetch(`${server.baseUrl}/api/tickets/missing`);

    for (const response of [ticketResponse, photoUploadResponse, photoDownloadResponse, errorResponse]) {
      assert.equal(response.headers.get("cache-control"), "no-store");
    }

    assert.equal((await fetch(server.baseUrl)).headers.get("cache-control"), null);
    assert.equal((await fetch(`${server.baseUrl}/health`)).headers.get("cache-control"), null);
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("prevents cross-origin embedding of uploaded photo responses", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const uploadResponse = await fetch(`${server.baseUrl}/api/photos`, {
      method: "POST",
      headers: { "content-type": "image/png" },
      body: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    });
    const photo = await uploadResponse.json() as { id: string };

    const response = await fetch(`${server.baseUrl}/api/photos/${photo.id}`);

    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cross-origin-resource-policy"), "same-origin");
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("serves a browser workflow wired to every ticket operation", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const html = await (await fetch(server.baseUrl)).text();
    assert.match(html, /id="signal-label"/);
    assert.match(html, /id="signal-confidence"/);
    assert.match(html, /id="analyze"/);
    assert.match(html, /role="status"/);
    for (const endpoint of ["/api/photos", "/api/tickets", "/resolve", "/analyze"]) {
      assert.ok(html.includes(endpoint), `UI should call ${endpoint}`);
    }
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("creates, lists, gets, and resolves tickets with JSON errors", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const createdResponse = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "  Leaking valve  ", description: "  Bay 2  " }),
    });
    assert.equal(createdResponse.status, 201);
    const created = await createdResponse.json() as Record<string, unknown>;
    assert.match(String(created.id), /^[0-9a-f-]{36}$/);
    assert.deepEqual(created, {
      id: created.id,
      title: "Leaking valve",
      description: "Bay 2",
      status: "open",
      photoIds: [],
    });

    const listResponse = await fetch(`${server.baseUrl}/api/tickets`);
    assert.equal(listResponse.status, 200);
    assert.deepEqual(await listResponse.json(), { tickets: [created] });

    const getResponse = await fetch(`${server.baseUrl}/api/tickets/${created.id}`);
    assert.equal(getResponse.status, 200);
    assert.deepEqual(await getResponse.json(), created);

    const resolvedResponse = await fetch(`${server.baseUrl}/api/tickets/${created.id}/resolve`, { method: "POST" });
    assert.equal(resolvedResponse.status, 200);
    assert.deepEqual(await resolvedResponse.json(), { ...created, status: "resolved" });

    const invalidResponse = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "   " }),
    });
    assert.equal(invalidResponse.status, 400);
    assert.deepEqual(await invalidResponse.json(), {
      error: { code: "validation_error", message: "title is required" },
    });

    const missingResponse = await fetch(`${server.baseUrl}/api/tickets/missing`);
    assert.equal(missingResponse.status, 404);
    assert.deepEqual(await missingResponse.json(), {
      error: { code: "not_found", message: 'Ticket with id "missing" does not exist' },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("returns method not allowed for PUT on an individual ticket route", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/tickets/missing`, { method: "PUT" });

    assert.equal(response.status, 405);
    assert.equal(response.headers.get("allow"), "GET");
    assert.deepEqual(await response.json(), {
      error: {
        code: "method_not_allowed",
        message: "Method PUT is not allowed for /api/tickets/:id",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("rejects a non-array photoIds field when creating a ticket", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "Inspect pipe", photoIds: "photo-1" }),
    });

    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), {
      error: { code: "validation_error", message: "photoIds must be an array" },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("rejects a non-application/json Content-Type when creating a ticket", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/jsonp" },
      body: JSON.stringify({ title: "Inspect pipe" }),
    });

    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), {
      error: {
        code: "validation_error",
        message: "content-type must be application/json",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("rejects non-string photo IDs when creating a ticket", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "Inspect pipe", photoIds: [42] }),
    });

    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), {
      error: {
        code: "validation_error",
        message: "photoIds[0] must be a string",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("rejects duplicate normalized photo IDs when creating a ticket", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        title: "Inspect pipe",
        photoIds: ["photo-1", "  photo-1 "],
      }),
    });

    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), {
      error: {
        code: "validation_error",
        message: "photoIds[1] duplicates photoIds[0]",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("rejects oversized ticket JSON with a payload-too-large error", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "Inspect pipe", description: "x".repeat(1024 * 1024) }),
    });

    assert.equal(response.status, 413);
    assert.deepEqual(await response.json(), {
      error: {
        code: "payload_too_large",
        message: "JSON body must not exceed 1 MiB",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("lists a bounded ticket page with a continuation cursor", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const createdTickets: Record<string, unknown>[] = [];
    for (const title of ["First", "Second", "Third"]) {
      const response = await fetch(`${server.baseUrl}/api/tickets`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title }),
      });
      createdTickets.push(await response.json() as Record<string, unknown>);
    }

    const response = await fetch(`${server.baseUrl}/api/tickets?limit=2`);

    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      tickets: createdTickets.slice(0, 2),
      nextCursor: createdTickets[1].id,
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("rejects a ticket cursor without an explicit page limit", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/tickets?cursor=ticket-1`);

    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), {
      error: {
        code: "validation_error",
        message: "cursor requires an explicit limit",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("uploads and retrieves supported photos while rejecting unsafe input", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const bytes = Buffer.from([0xff, 0xd8, 0xff, 0xdb, 0x01, 0x02]);
    const uploadResponse = await fetch(`${server.baseUrl}/api/photos`, {
      method: "POST",
      headers: { "content-type": "image/jpeg" },
      body: bytes,
    });
    assert.equal(uploadResponse.status, 201);
    const photo = await uploadResponse.json() as Record<string, unknown>;
    assert.match(String(photo.id), /^[0-9a-f-]{36}$/);
    assert.deepEqual(photo, { id: photo.id, contentType: "image/jpeg", sizeBytes: bytes.length });

    const downloadResponse = await fetch(`${server.baseUrl}/api/photos/${photo.id}`);
    assert.equal(downloadResponse.status, 200);
    assert.equal(downloadResponse.headers.get("content-type"), "image/jpeg");
    assert.deepEqual(Buffer.from(await downloadResponse.arrayBuffer()), bytes);

    const unsupportedResponse = await fetch(`${server.baseUrl}/api/photos`, {
      method: "POST",
      headers: { "content-type": "image/gif" },
      body: Buffer.from("GIF89a"),
    });
    assert.equal(unsupportedResponse.status, 400);
    assert.deepEqual(await unsupportedResponse.json(), {
      error: { code: "validation_error", message: "unsupported contentType: image/gif" },
    });

    const oversizedResponse = await fetch(`${server.baseUrl}/api/photos`, {
      method: "POST",
      headers: { "content-type": "image/png" },
      body: Buffer.alloc(10 * 1024 * 1024 + 1),
    });
    assert.equal(oversizedResponse.status, 413);
    assert.deepEqual(await oversizedResponse.json(), {
      error: { code: "payload_too_large", message: "photo must not exceed 10 MiB" },
    });

    const traversalResponse = await fetch(`${server.baseUrl}/api/photos/%2e%2e%2fsecret`);
    assert.ok([400, 404].includes(traversalResponse.status));
    assert.match(traversalResponse.headers.get("content-type") ?? "", /^application\/json/);
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("rejects photo bytes that do not match the declared content type", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/photos`, {
      method: "POST",
      headers: { "content-type": "image/jpeg" },
      body: Buffer.from("not a jpeg"),
    });

    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), {
      error: {
        code: "validation_error",
        message: "photo bytes do not match contentType image/jpeg",
      },
    });
    assert.equal(
      await readFile(join(dataDir, "photos.json"), "utf8").catch(() => undefined),
      undefined,
    );
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("analyzes client-supplied signals with existing domain logic", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const uploadResponse = await fetch(`${server.baseUrl}/api/photos`, {
      method: "POST",
      headers: { "content-type": "image/png" },
      body: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    });
    const photo = await uploadResponse.json() as { id: string };
    const ticketResponse = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "Inspect pipe", photoIds: [photo.id] }),
    });
    const ticket = await ticketResponse.json() as { id: string };

    const analysisResponse = await fetch(`${server.baseUrl}/api/tickets/${ticket.id}/photos/${photo.id}/analyze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ signals: [
        { label: "corrosion", confidence: 0.62 },
        { label: "standing water", confidence: 0.91 },
        { label: "blur", confidence: 0.2 },
      ] }),
    });
    assert.equal(analysisResponse.status, 200);
    assert.deepEqual(await analysisResponse.json(), {
      ticketId: ticket.id,
      photoId: photo.id,
      status: "needs_review",
      findings: [{ label: "standing water", confidence: 0.91 }],
      uncertainFindings: [{ label: "corrosion", confidence: 0.62 }],
      ignoredSignalCount: 1,
      confidence: 0.77,
      summary: "Detected standing water; review corrosion.",
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("persists ticket state, photo metadata, and image bytes across restart", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-server-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const bytes = Buffer.from([
      0x52, 0x49, 0x46, 0x46, 0x04, 0x00, 0x00, 0x00,
      0x57, 0x45, 0x42, 0x50,
    ]);
    const uploadResponse = await fetch(`${server.baseUrl}/api/photos`, {
      method: "POST",
      headers: { "content-type": "image/webp" },
      body: bytes,
    });
    const photo = await uploadResponse.json() as { id: string };
    const createResponse = await fetch(`${server.baseUrl}/api/tickets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "Persistent ticket", photoIds: [photo.id] }),
    });
    const ticket = await createResponse.json() as { id: string };
    const resolveResponse = await fetch(`${server.baseUrl}/api/tickets/${ticket.id}/resolve`, { method: "POST" });
    assert.equal(resolveResponse.status, 200);
    await stopServer(server.process);
    server = undefined;

    server = await startServer(dataDir);
    const listResponse = await fetch(`${server.baseUrl}/api/tickets`);
    assert.deepEqual(await listResponse.json(), {
      tickets: [{ id: ticket.id, title: "Persistent ticket", status: "resolved", photoIds: [photo.id] }],
    });
    const downloadResponse = await fetch(`${server.baseUrl}/api/photos/${photo.id}`);
    assert.equal(downloadResponse.status, 200);
    assert.equal(downloadResponse.headers.get("content-type"), "image/webp");
    assert.deepEqual(Buffer.from(await downloadResponse.arrayBuffer()), bytes);
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("declares the supported runtime and production container contract", async () => {
  const root = new URL("..", import.meta.url);
  const packageJson = JSON.parse(await readFile(new URL("package.json", root), "utf8"));
  assert.equal(packageJson.engines.node, ">=22");
  assert.equal(packageJson.scripts.start, "node src/server.ts");

  const dockerfile = await readFile(new URL("Dockerfile", root), "utf8");
  assert.match(dockerfile, /^FROM node:26\.7\.0-alpine$/m);
  assert.match(dockerfile, /^USER node$/m);
  assert.match(dockerfile, /^EXPOSE 3081$/m);

  const compose = await readFile(new URL("docker-compose.yml", root), "utf8");
  assert.match(compose, /127\.0\.0\.1:3081:3081/);
  assert.match(compose, /restart: unless-stopped/);
  assert.match(compose, /visualops-data:\/data/);
});
