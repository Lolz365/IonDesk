import assert from "node:assert/strict";
import test from "node:test";

import { analyzeTicketPhoto } from "../src/index.ts";
import {
  FallbackVisionProvider,
  type VisionProvider,
} from "../src/vision-provider.ts";

test("fallback vision analysis returns a needs-review draft without inferred signals", async () => {
  const provider: VisionProvider = new FallbackVisionProvider();

  const draft = await analyzeTicketPhoto(provider, {
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
