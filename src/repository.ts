import type { Ticket } from "./index.ts";

export interface ListTicketsPageInput {
  readonly limit: number;
  readonly cursor?: string;
}

export interface TicketPage {
  readonly tickets: readonly Ticket[];
  readonly nextCursor?: string;
}

export interface TicketRepository {
  save(ticket: Ticket): Promise<void>;
  list(): Promise<readonly Ticket[]>;
  listPage(input: ListTicketsPageInput): Promise<TicketPage>;
  findById(id: string): Promise<Ticket | undefined>;
  resolve(id: string): Promise<Ticket | undefined>;
}

export class DuplicateRecordError extends Error {
  readonly id: string;

  constructor(id: string) {
    super(`Record with id "${id}" already exists`);
    this.name = "DuplicateRecordError";
    this.id = id;
  }
}

export class InMemoryTicketRepository implements TicketRepository {
  readonly #tickets = new Map<string, Ticket>();

  async save(ticket: Ticket): Promise<void> {
    if (this.#tickets.has(ticket.id)) {
      throw new DuplicateRecordError(ticket.id);
    }

    const snapshot = Object.freeze({
      ...ticket,
      photoIds: Object.freeze([...ticket.photoIds]),
    });

    this.#tickets.set(snapshot.id, snapshot);
  }

  async list(): Promise<readonly Ticket[]> {
    return Object.freeze([...this.#tickets.values()]);
  }

  async listPage(input: ListTicketsPageInput): Promise<TicketPage> {
    if (!Number.isInteger(input.limit) || input.limit <= 0) {
      throw new Error("limit must be a positive integer");
    }
    if (input.limit > 100) {
      throw new Error("limit must not exceed 100");
    }
    if (input.cursor !== undefined && !input.cursor.trim()) {
      throw new Error("cursor is required");
    }

    const tickets = [...this.#tickets.values()];
    let startIndex = 0;
    if (input.cursor !== undefined) {
      const cursorIndex = tickets.findIndex(({ id }) => id === input.cursor);
      if (cursorIndex === -1) {
        throw new Error(`Cursor ticket with id "${input.cursor}" does not exist`);
      }
      startIndex = cursorIndex + 1;
    }

    const pageTickets = Object.freeze(
      tickets.slice(startIndex, startIndex + input.limit),
    );
    const hasNextPage = startIndex + pageTickets.length < tickets.length;
    return Object.freeze({
      tickets: pageTickets,
      ...(hasNextPage
        ? { nextCursor: pageTickets[pageTickets.length - 1].id }
        : {}),
    });
  }

  async findById(id: string): Promise<Ticket | undefined> {
    return this.#tickets.get(id);
  }

  async resolve(id: string): Promise<Ticket | undefined> {
    const ticket = this.#tickets.get(id);
    if (!ticket) {
      return undefined;
    }
    if (ticket.status === "resolved") {
      throw new Error(`Ticket with id "${id}" is already resolved`);
    }

    const snapshot = Object.freeze({ ...ticket, status: "resolved" as const });
    this.#tickets.set(id, snapshot);
    return snapshot;
  }
}
