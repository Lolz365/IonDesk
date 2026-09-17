import type { TicketRepository } from "./repository.ts";
import type { PhotoStorage } from "./photo-storage.ts";
import type {
  VisionAnalysisInput,
  VisionProvider,
} from "./vision-provider.ts";

export type TicketStatus = "open" | "resolved";

export interface Ticket {
  readonly id: string;
  readonly title: string;
  readonly description?: string;
  readonly status: TicketStatus;
  readonly photoIds: readonly string[];
}

export interface CreateTicketInput {
  readonly id: string;
  readonly title: string;
  readonly description?: string;
  readonly photoIds: readonly string[];
}

export interface PhotoSignal {
  readonly label: string;
  readonly confidence: number;
}

export interface PhotoAnalysisInput {
  readonly ticketId: string;
  readonly photoId: string;
  readonly signals: readonly PhotoSignal[];
}

export interface PhotoAnalysisDraft {
  readonly ticketId: string;
  readonly photoId: string;
  readonly status: "ready" | "needs_review";
  readonly findings: readonly PhotoSignal[];
  readonly uncertainFindings: readonly PhotoSignal[];
  readonly ignoredSignalCount: number;
  readonly confidence: number;
  readonly summary: string;
}

const PHOTO_CONTENT_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

export type PhotoContentType = (typeof PHOTO_CONTENT_TYPES)[number];

export interface PhotoUploadInput {
  readonly id: string;
  readonly contentType: string;
  readonly sizeBytes: number;
}

export interface PhotoUpload {
  readonly id: string;
  readonly contentType: PhotoContentType;
  readonly sizeBytes: number;
}

const HIGH_CONFIDENCE = 0.8;
const REVIEW_CONFIDENCE = 0.5;
const MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024;

function required(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) {
    throw new Error(`${field} is required`);
  }
  return normalized;
}

function isPhotoContentType(value: string): value is PhotoContentType {
  return PHOTO_CONTENT_TYPES.some((supported) => supported === value);
}

export function validatePhotoUpload(input: PhotoUploadInput): PhotoUpload {
  const contentType = required(input.contentType, "contentType").toLowerCase();
  if (!isPhotoContentType(contentType)) {
    throw new Error(`unsupported contentType: ${contentType}`);
  }
  if (!Number.isInteger(input.sizeBytes) || input.sizeBytes <= 0) {
    throw new Error("sizeBytes must be a positive integer");
  }
  if (input.sizeBytes > MAX_PHOTO_SIZE_BYTES) {
    throw new Error("sizeBytes must not exceed 10 MiB");
  }

  return Object.freeze({
    id: required(input.id, "id"),
    contentType,
    sizeBytes: input.sizeBytes,
  });
}

export function createTicket(input: CreateTicketInput): Ticket {
  const description = input.description?.trim();
  const photoIds = input.photoIds.map((photoId, index) =>
    required(photoId, `photoIds[${index}]`),
  );
  const photoIdIndexes = new Map<string, number>();
  photoIds.forEach((photoId, index) => {
    const duplicateIndex = photoIdIndexes.get(photoId);
    if (duplicateIndex !== undefined) {
      throw new Error(`photoIds[${index}] duplicates photoIds[${duplicateIndex}]`);
    }
    photoIdIndexes.set(photoId, index);
  });

  return Object.freeze({
    id: required(input.id, "id"),
    title: required(input.title, "title"),
    ...(description ? { description } : {}),
    status: "open" as const,
    photoIds: Object.freeze(photoIds),
  });
}

export async function createAndSaveTicket(
  repository: TicketRepository,
  input: CreateTicketInput,
): Promise<Ticket> {
  const ticket = createTicket(input);
  await repository.save(ticket);
  return ticket;
}

export async function createAndSaveTicketWithPhotos(
  repository: TicketRepository,
  photoStorage: PhotoStorage,
  input: CreateTicketInput,
): Promise<Ticket> {
  const ticket = createTicket(input);
  for (const photoId of ticket.photoIds) {
    if (!(await photoStorage.findById(photoId))) {
      throw new Error(`Photo with id "${photoId}" does not exist`);
    }
  }
  await repository.save(ticket);
  return ticket;
}

export async function resolveTicket(
  repository: TicketRepository,
  id: string,
): Promise<Ticket | undefined> {
  return repository.resolve(required(id, "id"));
}

export function analyzePhotoDraft(
  input: PhotoAnalysisInput,
): PhotoAnalysisDraft {
  const signals = input.signals.map((signal) => {
    const label = required(signal.label, "label");
    if (
      !Number.isFinite(signal.confidence) ||
      signal.confidence < 0 ||
      signal.confidence > 1
    ) {
      throw new Error("confidence must be between 0 and 1");
    }
    return Object.freeze({ label, confidence: signal.confidence });
  });

  signals.sort(
    (left, right) =>
      right.confidence - left.confidence || left.label.localeCompare(right.label),
  );

  const findings = Object.freeze(
    signals.filter((signal) => signal.confidence >= HIGH_CONFIDENCE),
  );
  const uncertainFindings = Object.freeze(
    signals.filter(
      (signal) =>
        signal.confidence >= REVIEW_CONFIDENCE &&
        signal.confidence < HIGH_CONFIDENCE,
    ),
  );
  const retained = [...findings, ...uncertainFindings];
  const confidence = retained.length
    ? Math.round(
        (retained.reduce((sum, signal) => sum + signal.confidence, 0) /
          retained.length) *
          100,
      ) / 100
    : 0;

  const detected = findings.length
    ? `Detected ${findings.map(({ label }) => label).join(", ")}`
    : "No high-confidence findings";
  const review = uncertainFindings.length
    ? `; review ${uncertainFindings.map(({ label }) => label).join(", ")}`
    : "";

  return Object.freeze({
    ticketId: required(input.ticketId, "ticketId"),
    photoId: required(input.photoId, "photoId"),
    status:
      findings.length > 0 && uncertainFindings.length === 0
        ? "ready"
        : "needs_review",
    findings,
    uncertainFindings,
    ignoredSignalCount: signals.length - retained.length,
    confidence,
    summary: `${detected}${review}.`,
  });
}

export async function analyzeTicketPhoto(
  repository: TicketRepository,
  provider: VisionProvider,
  input: VisionAnalysisInput,
): Promise<PhotoAnalysisDraft> {
  const normalizedInput = Object.freeze({
    ticketId: required(input.ticketId, "ticketId"),
    photoId: required(input.photoId, "photoId"),
  });
  const ticket = await repository.findById(normalizedInput.ticketId);
  if (!ticket) {
    throw new Error(
      `Ticket with id "${normalizedInput.ticketId}" does not exist`,
    );
  }
  if (!ticket.photoIds.includes(normalizedInput.photoId)) {
    throw new Error(
      `Photo with id "${normalizedInput.photoId}" is not attached to ticket "${normalizedInput.ticketId}"`,
    );
  }
  const signals = await provider.analyzePhoto(normalizedInput);
  return analyzePhotoDraft({ ...normalizedInput, signals });
}
