# VisualOps

The first VisualOps vertical slice models maintenance tickets and turns supplied
photo signals into a deterministic analysis draft. It does not call a vision
provider: callers supply labels and confidence scores, and the domain service
classifies them consistently.

Confidence policy:

- `0.80`–`1.00`: included as a finding.
- `0.50`–`0.79`: included as uncertain and forces `needs_review`.
- Below `0.50`: ignored.
- Draft confidence is the mean of retained signals, rounded to two decimals.

## Requirements

- Node.js 22.18 or newer (native TypeScript execution is used).
- npm 10 or newer.

## Verify

From the repository root, run exactly:

```sh
npm test
```

No dependency installation, environment variables, external accounts, or
network access are required.
