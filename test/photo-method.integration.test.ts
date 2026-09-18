import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
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

test("DELETE /api/photos reports POST for the known route", async () => {
  const dataDir = await mkdtemp(join(tmpdir(), "visualops-photo-method-"));
  let server: RunningServer | undefined;
  try {
    server = await startServer(dataDir);
    const response = await fetch(`${server.baseUrl}/api/photos`, {
      method: "DELETE",
    });

    assert.equal(response.status, 405);
    assert.equal(response.headers.get("allow"), "POST");
    assert.deepEqual(await response.json(), {
      error: {
        code: "method_not_allowed",
        message: "Method DELETE is not allowed for /api/photos",
      },
    });
  } finally {
    if (server) await stopServer(server.process);
    await rm(dataDir, { recursive: true, force: true });
  }
});
