import assert from "node:assert/strict";
import test from "node:test";

import {
  analyzePhotoDraft,
  createTicket,
  type PhotoSignal,
} from "../src/index.ts";

test("creates a ticket with normalized text and immutable photo ids", () => {
  const ticket = createTicket({
    id: "ticket-001",
    title: "  Leaking valve  ",
    description: "  Water beneath valve B. ",
    photoIds: ["photo-2", "photo-1"],
  });

  assert.deepEqual(ticket, {
    id: "ticket-001",
    title: "Leaking valve",
    description: "Water beneath valve B.",
    status: "open",
    photoIds: ["photo-2", "photo-1"],
  });
  assert.throws(() => ticket.photoIds.push("photo-3"), TypeError);
});

test("rejects a ticket without a meaningful title", () => {
  assert.throws(
    () => createTicket({ id: "ticket-001", title: "   ", photoIds: [] }),
    /title is required/,
  );
});

test("rejects a ticket with a blank photo id", () => {
  assert.throws(
    () =>
      createTicket({
        id: "ticket-001",
        title: "Leaking valve",
        photoIds: ["photo-1", "   "],
      }),
    /photoIds\[1\] is required/,
  );
});

test("produces a deterministic confidence-aware analysis draft", () => {
  const signals: PhotoSignal[] = [
    { label: "standing water", confidence: 0.91 },
    { label: "corrosion", confidence: 0.62 },
    { label: "pipe", confidence: 0.98 },
    { label: "blur", confidence: 0.2 },
  ];

  const first = analyzePhotoDraft({
    ticketId: "ticket-001",
    photoId: "photo-1",
    signals,
  });
  const second = analyzePhotoDraft({
    ticketId: "ticket-001",
    photoId: "photo-1",
    signals: [...signals].reverse(),
  });

  assert.deepEqual(first, second);
  assert.deepEqual(first, {
    ticketId: "ticket-001",
    photoId: "photo-1",
    status: "needs_review",
    findings: [
      { label: "pipe", confidence: 0.98 },
      { label: "standing water", confidence: 0.91 },
    ],
    uncertainFindings: [{ label: "corrosion", confidence: 0.62 }],
    ignoredSignalCount: 1,
    confidence: 0.84,
    summary: "Detected pipe, standing water; review corrosion.",
  });
});

test("marks a draft ready when every retained signal is high confidence", () => {
  const draft = analyzePhotoDraft({
    ticketId: "ticket-002",
    photoId: "photo-4",
    signals: [
      { label: "crack", confidence: 0.8 },
      { label: "rust", confidence: 0.9 },
    ],
  });

  assert.equal(draft.status, "ready");
  assert.equal(draft.confidence, 0.85);
  assert.equal(draft.summary, "Detected rust, crack.");
});

test("validates signal confidence and labels", () => {
  assert.throws(
    () =>
      analyzePhotoDraft({
        ticketId: "ticket-001",
        photoId: "photo-1",
        signals: [{ label: "leak", confidence: 1.1 }],
      }),
    /confidence must be between 0 and 1/,
  );

  assert.throws(
    () =>
      analyzePhotoDraft({
        ticketId: "ticket-001",
        photoId: "photo-1",
        signals: [{ label: " ", confidence: 0.9 }],
      }),
    /label is required/,
  );
});
