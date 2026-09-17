import type { Ticket } from "./index.ts";

export class DuplicateRecordError extends Error {
  readonly id: string;

  constructor(id: string) {
    super(`Record with id "${id}" already exists`);
    this.name = "DuplicateRecordError";
    this.id = id;
  }
}

export class InMemoryTicketRepository {
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

  async findById(id: string): Promise<Ticket | undefined> {
    return this.#tickets.get(id);
  }
}
