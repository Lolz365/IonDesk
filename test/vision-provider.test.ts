import assert from "node:assert/strict";
import test from "node:test";

import { analyzeTicketPhoto, createTicket } from "../src/index.ts";
import {
  FallbackVisionProvider,
  type VisionProvider,
} from "../src/vision-provider.ts";
import { InMemoryTicketRepository } from "../src/repository.ts";

test("vision analysis rejects a missing ticket before calling the provider", async () => {
  const repository = new InMemoryTicketRepository();
  let providerCallCount = 0;
  const provider: VisionProvider = {
    async analyzePhoto() {
      providerCallCount += 1;
      return [];
    },
  };

  await assert.rejects(
    analyzeTicketPhoto(repository, provider, {
      ticketId: "ticket-missing",
      photoId: "photo-1",
    }),
    /Ticket with id "ticket-missing" does not exist/,
  );
  assert.equal(providerCallCount, 0);
});

test("fallback vision analysis returns a needs-review draft without inferred signals", async () => {
  const repository = new InMemoryTicketRepository();
  const provider: VisionProvider = new FallbackVisionProvider();
  await repository.save(
    createTicket({
      id: "ticket-001",
      title: "Leaking valve",
      photoIds: ["photo-1"],
    }),
  );

  const draft = await analyzeTicketPhoto(repository, provider, {
    ticketId: "ticket-001",
    photoId: "photo-1",
  });

  assert.deepEqual(draft, {
    ticketId: "ticket-001",
    photoId: "photo-1",
    status: "needs_review",
    findings: [],
    uncertainFindings: [],
    ignoredSignalCount: 0,
    confidence: 0,
    summary: "No high-confidence findings.",
  });
});
