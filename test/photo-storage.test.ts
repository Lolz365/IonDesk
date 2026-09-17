import assert from "node:assert/strict";
import test from "node:test";

import {
  validateAndSavePhotoUpload,
  validatePhotoUpload,
} from "../src/index.ts";
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
