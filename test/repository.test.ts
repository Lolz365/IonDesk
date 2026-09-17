import assert from "node:assert/strict";
import test from "node:test";

import {
  createAndSaveTicket,
  createAndSaveTicketWithPhotos,
  createTicket,
  listTicketsPage,
  resolveTicket,
  type Ticket,
} from "../src/index.ts";
import { InMemoryPhotoStorage } from "../src/photo-storage.ts";
import {
  DuplicateRecordError,
  InMemoryTicketRepository,
} from "../src/repository.ts";

test("ticket application creates and saves through a repository", async () => {
  const repository = new InMemoryTicketRepository();

  const ticket = await createAndSaveTicket(repository, {
    id: "ticket-1",
    title: "  Leaking valve  ",
    photoIds: ["photo-1"],
  });

  assert.equal(ticket.title, "Leaking valve");
  assert.deepEqual(await repository.findById("ticket-1"), ticket);
});

test("ticket application rejects a missing photo before saving", async () => {
  const repository = new InMemoryTicketRepository();
  const photoStorage = new InMemoryPhotoStorage();

  await assert.rejects(
    createAndSaveTicketWithPhotos(repository, photoStorage, {
      id: "ticket-1",
      title: "Leaking valve",
      photoIds: ["photo-missing"],
    }),
    /Photo with id "photo-missing" does not exist/,
  );
  assert.equal(await repository.findById("ticket-1"), undefined);
});

test("ticket application resolves a saved ticket through a repository", async () => {
  const repository = new InMemoryTicketRepository();
  const ticket = createTicket({
    id: "ticket-1",
    title: "Leaking valve",
    photoIds: ["photo-1"],
  });
  await repository.save(ticket);

  const resolvedTicket = await resolveTicket(repository, "ticket-1");

  assert.deepEqual(resolvedTicket, { ...ticket, status: "resolved" });
});

test("ticket application rejects resolving an already-resolved ticket without mutation", async () => {
  const repository = new InMemoryTicketRepository();
  const ticket = createTicket({
    id: "ticket-1",
    title: "Leaking valve",
    photoIds: ["photo-1"],
  });
  await repository.save(ticket);
  const resolvedTicket = await resolveTicket(repository, "ticket-1");

  await assert.rejects(
    resolveTicket(repository, "ticket-1"),
    /Ticket with id "ticket-1" is already resolved/,
  );
  assert.strictEqual(await repository.findById("ticket-1"), resolvedTicket);
});

test("ticket application rejects a blank ticket id when resolving", async () => {
  const repository = new InMemoryTicketRepository();

  await assert.rejects(resolveTicket(repository, "  "), /id is required/);
});

test("ticket application rejects resolving a missing ticket", async () => {
  const repository = new InMemoryTicketRepository();

  await assert.rejects(
    resolveTicket(repository, "ticket-missing"),
    /Ticket with id "ticket-missing" does not exist/,
  );
});

test("ticket application trims a cursor when listing a page", async () => {
  const repository = new InMemoryTicketRepository();
  const expectedPage = Object.freeze({ tickets: Object.freeze([]) });
  let receivedInput: unknown;
  repository.listPage = async (input) => {
    receivedInput = input;
    return expectedPage;
  };

  const page = await listTicketsPage(repository, {
    limit: 5,
    cursor: "  ticket-1  ",
  });

  assert.strictEqual(page, expectedPage);
  assert.deepEqual(receivedInput, { limit: 5, cursor: "ticket-1" });
});

test("ticket application rejects a blank pagination cursor before querying the repository", async () => {
  const repository = new InMemoryTicketRepository();
  let listPageCallCount = 0;
  repository.listPage = async () => {
    listPageCallCount += 1;
    return { tickets: [] };
  };

  await assert.rejects(
    listTicketsPage(repository, { limit: 5, cursor: "   " }),
    /cursor is required/,
  );
  assert.equal(listPageCallCount, 0);
});

test("ticket application rejects an invalid page limit before querying the repository", async () => {
  const repository = new InMemoryTicketRepository();
  let listPageCallCount = 0;
  repository.listPage = async () => {
    listPageCallCount += 1;
    return { tickets: [] };
  };

  await assert.rejects(
    listTicketsPage(repository, { limit: 0 }),
    /limit must be a positive integer/,
  );
  assert.equal(listPageCallCount, 0);
});

test("ticket application rejects a page limit above 100 before querying the repository", async () => {
  const repository = new InMemoryTicketRepository();
  let listPageCallCount = 0;
  repository.listPage = async () => {
    listPageCallCount += 1;
    return { tickets: [] };
  };

  await assert.rejects(
    listTicketsPage(repository, { limit: 101 }),
    /limit must not exceed 100/,
  );
  assert.equal(listPageCallCount, 0);
});

test("ticket repository saves snapshots and lists them in insertion order", async () => {
  const repository = new InMemoryTicketRepository();
  const first = createTicket({
    id: "ticket-1",
    title: "First",
    photoIds: ["photo-1"],
  });
  const second = createTicket({
    id: "ticket-2",
    title: "Second",
    photoIds: [],
  });

  await repository.save(first);
  await repository.save(second);

  assert.deepEqual(await repository.list(), [first, second]);
  assert.deepEqual(await repository.findById("ticket-1"), first);
  assert.equal(await repository.findById("missing"), undefined);
});

test("ticket repository lists immutable deterministic pages", async () => {
  const repository = new InMemoryTicketRepository();
  const tickets = [
    createTicket({ id: "ticket-1", title: "First", photoIds: [] }),
    createTicket({ id: "ticket-2", title: "Second", photoIds: [] }),
    createTicket({ id: "ticket-3", title: "Third", photoIds: [] }),
  ];
  for (const ticket of tickets) {
    await repository.save(ticket);
  }

  const firstPage = await repository.listPage({ limit: 2 });
  assert.deepEqual(firstPage, {
    tickets: [tickets[0], tickets[1]],
    nextCursor: "ticket-2",
  });
  assert.throws(
    () => Object.assign(firstPage, { nextCursor: "ticket-1" }),
    TypeError,
  );
  assert.throws(
    () => (firstPage.tickets as Ticket[]).push(tickets[2]),
    TypeError,
  );

  assert.deepEqual(
    await repository.listPage({ limit: 2, cursor: firstPage.nextCursor }),
    { tickets: [tickets[2]] },
  );
  await assert.rejects(
    repository.listPage({ limit: 1, cursor: "ticket-missing" }),
    /Cursor ticket with id "ticket-missing" does not exist/,
  );
  await assert.rejects(
    repository.listPage({ limit: 0 }),
    /limit must be a positive integer/,
  );
  await assert.rejects(
    repository.listPage({ limit: 1.5 }),
    /limit must be a positive integer/,
  );
});

test("ticket repository rejects a blank pagination cursor", async () => {
  const repository = new InMemoryTicketRepository();

  await assert.rejects(
    repository.listPage({ limit: 1, cursor: "   " }),
    /cursor is required/,
  );
});

test("ticket repository rejects resolving an id with surrounding whitespace without mutation", async () => {
  const repository = new InMemoryTicketRepository();
  const ticket = createTicket({
    id: "ticket-1",
    title: "Leaking valve",
    photoIds: [],
  });
  await repository.save(ticket);

  await assert.rejects(
    repository.resolve(" ticket-1 "),
    /id must not contain surrounding whitespace/,
  );
  assert.equal((await repository.findById("ticket-1"))?.status, "open");
});

test("ticket repository rejects a page limit above 100", async () => {
  const repository = new InMemoryTicketRepository();

  await assert.rejects(
    repository.listPage({ limit: 101 }),
    /limit must not exceed 100/,
  );
});

test("ticket repository rejects duplicate ids", async () => {
  const repository = new InMemoryTicketRepository();
  const ticket = createTicket({ id: "ticket-1", title: "First", photoIds: [] });

  await repository.save(ticket);

  await assert.rejects(
    repository.save(ticket),
    (error: unknown) =>
      error instanceof DuplicateRecordError && error.id === "ticket-1",
  );
});

test("ticket repository rejects a blank id without persisting the ticket", async () => {
  const repository = new InMemoryTicketRepository();
  const ticket: Ticket = {
    id: "   ",
    title: "Invalid persistence input",
    status: "open",
    photoIds: [],
  };

  await assert.rejects(repository.save(ticket), /id is required/);
  assert.deepEqual(await repository.list(), []);
});

test("ticket repository rejects an id with surrounding whitespace", async () => {
  const repository = new InMemoryTicketRepository();
  const ticket: Ticket = {
    id: " ticket-1 ",
    title: "Invalid persistence input",
    status: "open",
    photoIds: [],
  };

  await assert.rejects(
    repository.save(ticket),
    /id must not contain surrounding whitespace/,
  );
  assert.deepEqual(await repository.list(), []);
});

test("ticket repository rejects duplicate photo ids after normalization", async () => {
  const repository = new InMemoryTicketRepository();
  const ticket: Ticket = {
    id: "ticket-1",
    title: "Invalid persistence input",
    status: "open",
    photoIds: ["photo-1", " photo-1 "],
  };

  await assert.rejects(
    repository.save(ticket),
    /photoIds\[1\] duplicates photoIds\[0\]/,
  );
  assert.deepEqual(await repository.list(), []);
});

test("ticket repository resolves a previously saved open ticket immutably", async () => {
  const repository = new InMemoryTicketRepository();
  const openTicket = createTicket({
    id: "ticket-1",
    title: "Leaking valve",
    photoIds: ["photo-1"],
  });

  await repository.save(openTicket);

  const resolvedTicket = await repository.resolve("ticket-1");

  assert.deepEqual(resolvedTicket, { ...openTicket, status: "resolved" });
  assert.deepEqual(await repository.findById("ticket-1"), resolvedTicket);
  assert.equal(openTicket.status, "open");
  assert.notEqual(resolvedTicket, openTicket);
  assert.throws(
    () => Object.assign(resolvedTicket, { status: "open" }),
    TypeError,
  );
});
