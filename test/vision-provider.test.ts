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

test("vision analysis rejects a photo not attached to the ticket before calling the provider", async () => {
  const repository = new InMemoryTicketRepository();
  await repository.save(
    createTicket({
      id: "ticket-001",
      title: "Leaking valve",
      photoIds: ["photo-attached"],
    }),
  );
  let providerCallCount = 0;
  const provider: VisionProvider = {
    async analyzePhoto() {
      providerCallCount += 1;
      return [];
    },
  };

  await assert.rejects(
    analyzeTicketPhoto(repository, provider, {
      ticketId: "ticket-001",
      photoId: "photo-other",
    }),
    /Photo with id "photo-other" is not attached to ticket "ticket-001"/,
  );
  assert.equal(providerCallCount, 0);
});

test("vision analysis rejects a resolved ticket before calling the provider", async () => {
  const repository = new InMemoryTicketRepository();
  await repository.save(
    createTicket({
      id: "ticket-001",
      title: "Leaking valve",
      photoIds: ["photo-1"],
    }),
  );
  await repository.resolve("ticket-001");
  let providerCallCount = 0;
  const provider: VisionProvider = {
    async analyzePhoto() {
      providerCallCount += 1;
      return [];
    },
  };

  await assert.rejects(
    analyzeTicketPhoto(repository, provider, {
      ticketId: "ticket-001",
      photoId: "photo-1",
    }),
    /Ticket with id "ticket-001" is resolved/,
  );
  assert.equal(providerCallCount, 0);
});

test("vision analysis normalizes ids before lookup and provider calls", async () => {
  const repository = new InMemoryTicketRepository();
  await repository.save(
    createTicket({
      id: "ticket-001",
      title: "Leaking valve",
      photoIds: ["photo-1"],
    }),
  );
  const providerInputs: Array<{ ticketId: string; photoId: string }> = [];
  const provider: VisionProvider = {
    async analyzePhoto(input) {
      providerInputs.push(input);
      return [];
    },
  };

  const draft = await analyzeTicketPhoto(repository, provider, {
    ticketId: "  ticket-001  ",
    photoId: "  photo-1  ",
  });

  assert.deepEqual(providerInputs, [
    { ticketId: "ticket-001", photoId: "photo-1" },
  ]);
  assert.equal(draft.ticketId, "ticket-001");
  assert.equal(draft.photoId, "photo-1");
});

test("vision analysis protects authorized ids from provider mutation", async () => {
  const repository = new InMemoryTicketRepository();
  await repository.save(
    createTicket({
      id: "ticket-001",
      title: "Leaking valve",
      photoIds: ["photo-1"],
    }),
  );
  const provider: VisionProvider = {
    async analyzePhoto(input) {
      assert.equal(Object.isFrozen(input), true);
      assert.throws(
        () =>
          Object.assign(input, {
            ticketId: "ticket-other",
            photoId: "photo-other",
          }),
        TypeError,
      );
      return [];
    },
  };

  const draft = await analyzeTicketPhoto(repository, provider, {
    ticketId: "ticket-001",
    photoId: "photo-1",
  });

  assert.equal(draft.ticketId, "ticket-001");
  assert.equal(draft.photoId, "photo-1");
});

test("vision analysis sanitizes provider failures", async () => {
  const repository = new InMemoryTicketRepository();
  await repository.save(
    createTicket({
      id: "ticket-001",
      title: "Leaking valve",
      photoIds: ["photo-1"],
    }),
  );
  const provider: VisionProvider = {
    async analyzePhoto() {
      throw new Error("vendor token abc123 expired");
    },
  };

  await assert.rejects(
    analyzeTicketPhoto(repository, provider, {
      ticketId: "ticket-001",
      photoId: "photo-1",
    }),
    (error: unknown) =>
      error instanceof Error &&
      error.message === 'Vision analysis failed for photo "photo-1"' &&
      !error.message.includes("abc123"),
  );
});

test("vision analysis sanitizes malformed provider responses", async () => {
  const repository = new InMemoryTicketRepository();
  await repository.save(
    createTicket({
      id: "ticket-001",
      title: "Leaking valve",
      photoIds: ["photo-1"],
    }),
  );
  const provider = {
    async analyzePhoto() {
      return null;
    },
  } as unknown as VisionProvider;

  await assert.rejects(
    analyzeTicketPhoto(repository, provider, {
      ticketId: "ticket-001",
      photoId: "photo-1",
    }),
    (error: unknown) =>
      error instanceof Error &&
      error.message === 'Vision analysis failed for photo "photo-1"',
  );
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
