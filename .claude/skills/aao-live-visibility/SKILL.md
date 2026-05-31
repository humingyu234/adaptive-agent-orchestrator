---
name: aao-live-visibility
description: Use when implementing AAO status views, progress summaries, evidence output, reports, audit artifacts, Control Trace, demo proof, or PR proof packs.
---

# AAO Live Visibility

Start with structured CLI/artifact output before building UI.

A useful run view should answer:

```text
Task: what is being done?
Plan: what boundaries/checks apply?
Worker: what executed, real or fake?
Observed Evidence: what did AAO see?
Control Decision: pass/block and why?
Failure: category and origin, if any?
Recovery: retry/repair/human review/fail?
Audit: where is the report?
```

Never blur:

- reported vs observed
- fake vs real
- demo sample vs live run
- worker output vs AAO-owned evidence

For hiring/demo output, prefer one clear Control Trace over a large dashboard.
