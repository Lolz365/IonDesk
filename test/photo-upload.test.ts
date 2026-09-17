import assert from "node:assert/strict";
import test from "node:test";

import { validatePhotoUpload } from "../src/index.ts";

test("validates and normalizes an immutable photo upload", () => {
  const upload = validatePhotoUpload({
    id: "  photo-1  ",
    contentType: "  IMAGE/WEBP  ",
    sizeBytes: 42,
  });

  assert.deepEqual(upload, {
    id: "photo-1",
    contentType: "image/webp",
    sizeBytes: 42,
  });
  assert.equal(Object.isFrozen(upload), true);
  assert.throws(() => Object.assign(upload, { sizeBytes: 43 }), TypeError);

  for (const [contentType, normalizedContentType] of [
    ["IMAGE/JPEG", "image/jpeg"],
    ["image/png", "image/png"],
  ] as const) {
    assert.equal(
      validatePhotoUpload({ id: "photo-2", contentType, sizeBytes: 1 })
        .contentType,
      normalizedContentType,
    );
  }

  assert.throws(
    () =>
      validatePhotoUpload({
        id: "photo-2",
        contentType: "image/gif",
        sizeBytes: 42,
      }),
    /unsupported contentType: image\/gif/,
  );

  for (const sizeBytes of [0, -1, 1.5]) {
    assert.throws(
      () =>
        validatePhotoUpload({
          id: "photo-2",
          contentType: "image/jpeg",
          sizeBytes,
        }),
      /sizeBytes must be a positive integer/,
    );
  }
});
