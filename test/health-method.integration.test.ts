import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
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

test("POST /health returns a method-not-allowed JSON error", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-health-method-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/health`, { method: "POST" });

    assert.equal(response.status, 405);
    assert.deepEqual(await response.json(), {
      error: {
        code: "method_not_allowed",
        message: "Method POST is not allowed for /health",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("DELETE /health returns allowed methods with its method-not-allowed JSON error", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-health-method-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/health`, { method: "DELETE" });

    assert.equal(response.status, 405);
    assert.equal(response.headers.get("allow"), "GET");
    assert.deepEqual(await response.json(), {
      error: {
        code: "method_not_allowed",
        message: "Method DELETE is not allowed for /health",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("HEAD /health returns the GET health headers without a response body", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-health-method-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const getResponse = await fetch(`${server.baseUrl}/health`);
    const headResponse = await fetch(`${server.baseUrl}/health`, { method: "HEAD" });
    const healthHeaders = (response: Response) => Object.fromEntries(
      [...response.headers].filter(([name]) => !["connection", "date", "keep-alive"].includes(name)),
    );

    assert.equal(headResponse.status, 200);
    assert.equal(headResponse.headers.get("content-type"), "application/json; charset=utf-8");
    assert.deepEqual(healthHeaders(headResponse), healthHeaders(getResponse));
    assert.equal(await headResponse.text(), "");
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});
