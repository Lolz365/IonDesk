import type { PhotoUpload } from "./index.ts";
import { DuplicateRecordError } from "./repository.ts";

export { DuplicateRecordError } from "./repository.ts";

export interface PhotoStorage {
  save(upload: PhotoUpload): Promise<void>;
  findById(id: string): Promise<PhotoUpload | undefined>;
}

export class InMemoryPhotoStorage implements PhotoStorage {
  readonly #uploads = new Map<string, PhotoUpload>();

  async save(upload: PhotoUpload): Promise<void> {
    if (!upload.id.trim()) {
      throw new Error("id is required");
    }
    if (this.#uploads.has(upload.id)) {
      throw new DuplicateRecordError(upload.id);
    }

    const snapshot = Object.freeze({ ...upload });
    this.#uploads.set(snapshot.id, snapshot);
  }

  async findById(id: string): Promise<PhotoUpload | undefined> {
    return this.#uploads.get(id);
  }
}
