import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { validatePhotoUpload, type PhotoUpload, type Ticket, type TicketStatus } from "./index.ts";
import type { PhotoStorage } from "./photo-storage.ts";
import { DuplicateRecordError, InMemoryTicketRepository, type ListTicketsPageInput, type TicketPage, type TicketRepository } from "./repository.ts";

async function readArray(path: string): Promise<unknown[]> {
  try {
    const value: unknown = JSON.parse(await readFile(path, "utf8"));
    if (!Array.isArray(value)) throw new Error(`${path} must contain a JSON array`);
    return value;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function atomicJson(path: string, value: unknown): Promise<void> {
  const temporaryPath = `${path}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await rename(temporaryPath, path);
}

export function validateResourceId(id: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id) || id === "..") {
    throw new Error("invalid resource id");
  }
  return id;
}

export class FileTicketRepository implements TicketRepository {
  readonly #memory = new InMemoryTicketRepository();
  readonly #path: string;
  #writeQueue: Promise<void> = Promise.resolve();

  private constructor(path: string) { this.#path = path; }

  static async open(dataDir: string): Promise<FileTicketRepository> {
    await mkdir(dataDir, { recursive: true });
    const repository = new FileTicketRepository(join(dataDir, "tickets.json"));
    for (const value of await readArray(repository.#path)) {
      await repository.#memory.save(value as Ticket);
    }
    return repository;
  }

  async #persist(): Promise<void> {
    this.#writeQueue = this.#writeQueue.then(async () => atomicJson(this.#path, await this.#memory.list()));
    return this.#writeQueue;
  }

  async save(ticket: Ticket): Promise<void> {
    validateResourceId(ticket.id);
    await this.#memory.save(ticket);
    await this.#persist();
  }

  list(status?: TicketStatus): Promise<readonly Ticket[]> { return this.#memory.list(status); }
  listPage(input: ListTicketsPageInput): Promise<TicketPage> { return this.#memory.listPage(input); }
  findById(id: string): Promise<Ticket | undefined> { return this.#memory.findById(validateResourceId(id)); }

  async resolve(id: string): Promise<Ticket | undefined> {
    const ticket = await this.#memory.resolve(validateResourceId(id));
    if (ticket) await this.#persist();
    return ticket;
  }
}

export class FilePhotoStorage implements PhotoStorage {
  readonly #uploads = new Map<string, PhotoUpload>();
  readonly #metadataPath: string;
  readonly #photosDir: string;
  #writeQueue: Promise<void> = Promise.resolve();

  private constructor(dataDir: string) {
    this.#metadataPath = join(dataDir, "photos.json");
    this.#photosDir = join(dataDir, "photos");
  }

  static async open(dataDir: string): Promise<FilePhotoStorage> {
    const storage = new FilePhotoStorage(dataDir);
    await mkdir(storage.#photosDir, { recursive: true });
    for (const value of await readArray(storage.#metadataPath)) {
      const upload = validatePhotoUpload(value as PhotoUpload);
      validateResourceId(upload.id);
      storage.#uploads.set(upload.id, upload);
    }
    return storage;
  }

  async save(upload: PhotoUpload): Promise<void> {
    const validated = validatePhotoUpload(upload);
    validateResourceId(validated.id);
    if (this.#uploads.has(validated.id)) throw new DuplicateRecordError(validated.id);
    this.#uploads.set(validated.id, Object.freeze({ ...validated }));
    this.#writeQueue = this.#writeQueue.then(() => atomicJson(this.#metadataPath, [...this.#uploads.values()]));
    await this.#writeQueue;
  }

  async findById(id: string): Promise<PhotoUpload | undefined> { return this.#uploads.get(validateResourceId(id)); }

  async saveBytes(id: string, bytes: Buffer): Promise<void> {
    const photo = this.#uploads.get(validateResourceId(id));
    if (!photo) throw new Error(`Photo with id "${id}" does not exist`);
    await writeFile(join(this.#photosDir, id), bytes, { flag: "wx", mode: 0o600 });
  }

  async readBytes(id: string): Promise<Buffer | undefined> {
    try {
      return await readFile(join(this.#photosDir, validateResourceId(id)));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
      throw error;
    }
  }
}
