import type { TicketRepository } from "./repository.ts";

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

const HIGH_CONFIDENCE = 0.8;
const REVIEW_CONFIDENCE = 0.5;

function required(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) {
    throw new Error(`${field} is required`);
  }
  return normalized;
}

export function createTicket(input: CreateTicketInput): Ticket {
  const description = input.description?.trim();

  return Object.freeze({
    id: required(input.id, "id"),
    title: required(input.title, "title"),
    ...(description ? { description } : {}),
    status: "open" as const,
    photoIds: Object.freeze([...input.photoIds]),
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
