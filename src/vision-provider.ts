import type { PhotoSignal } from "./index.ts";

export interface VisionAnalysisInput {
  readonly ticketId: string;
  readonly photoId: string;
}

export interface VisionProvider {
  analyzePhoto(input: VisionAnalysisInput): Promise<readonly PhotoSignal[]>;
}

const NO_SIGNALS: readonly PhotoSignal[] = Object.freeze([]);

export class FallbackVisionProvider implements VisionProvider {
  async analyzePhoto(
    _input: VisionAnalysisInput,
  ): Promise<readonly PhotoSignal[]> {
    return NO_SIGNALS;
  }
}
