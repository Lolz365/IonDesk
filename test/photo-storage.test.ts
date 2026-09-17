import assert from "node:assert/strict";
import test from "node:test";

import {
  validateAndSavePhotoUpload,
  validatePhotoUpload,
} from "../src/index.ts";
import type { PhotoUpload } from "../src/index.ts";
import {
  DuplicateRecordError,
  InMemoryPhotoStorage,
} from "../src/photo-storage.ts";

test("photo storage snapshots validated metadata and rejects duplicate ids", async () => {
  const storage = new InMemoryPhotoStorage();
  const upload = validatePhotoUpload({
    id: "photo-1",
    contentType: "image/jpeg",
    sizeBytes: 42,
  });

  await storage.save(upload);

  const stored = await storage.findById("photo-1");
  assert.deepEqual(stored, upload);
  assert.notEqual(stored, upload);
  assert.equal(Object.isFrozen(stored), true);
  assert.equal(await storage.findById("missing"), undefined);
  assert.throws(() => Object.assign(stored!, { sizeBytes: 43 }), TypeError);

  await assert.rejects(
    storage.save(upload),
    (error: unknown) =>
      error instanceof DuplicateRecordError && error.id === "photo-1",
  );
});

test("photo storage rejects a blank id without persisting the upload", async () => {
  const storage = new InMemoryPhotoStorage();
  const upload: PhotoUpload = {
    id: "   ",
    contentType: "image/jpeg",
    sizeBytes: 42,
  };

  await assert.rejects(storage.save(upload), /id is required/);
  assert.equal(await storage.findById("   "), undefined);
});

test("photo storage rejects an id with surrounding whitespace", async () => {
  const storage = new InMemoryPhotoStorage();
  const upload: PhotoUpload = {
    id: " photo-1 ",
    contentType: "image/jpeg",
    sizeBytes: 42,
  };

  await assert.rejects(
    storage.save(upload),
    /id must not contain surrounding whitespace/,
  );
  assert.equal(await storage.findById(" photo-1 "), undefined);
});

test("photo storage rejects forged metadata without persisting it", async () => {
  const storage = new InMemoryPhotoStorage();
  const upload = {
    id: "photo-unsafe",
    contentType: "image/gif",
    sizeBytes: 42,
  } as unknown as PhotoUpload;

  await assert.rejects(storage.save(upload), /unsupported contentType: image\/gif/);
  assert.equal(await storage.findById("photo-unsafe"), undefined);
});

test("photo upload application validates and saves through storage", async () => {
  const storage = new InMemoryPhotoStorage();

  const upload = await validateAndSavePhotoUpload(storage, {
    id: "  photo-2  ",
    contentType: "  IMAGE/PNG  ",
    sizeBytes: 84,
  });

  assert.deepEqual(upload, {
    id: "photo-2",
    contentType: "image/png",
    sizeBytes: 84,
  });
  assert.deepEqual(await storage.findById("photo-2"), upload);
});
