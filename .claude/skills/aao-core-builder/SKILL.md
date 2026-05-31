---
name: aao-core-builder
description: Use when changing AAO core runtime, ControlPlane, evidence, worker bridge, reviewer, recovery, project session, or execution routing code.
---

# AAO Core Builder

Before editing:

- Read `CLAUDE.md`, `docs/current_state.md`, and `docs/next_steps.md`.
- State the current runtime path and the one behavior this change affects.
- Name non-goals and expected files.
- Prefer small adapters over package-wide rewrites.
- Do not add heavy dependencies unless they directly unblock the current path.

During editing:

- Keep worker, runner, reviewer, and ControlPlane roles distinct.
- Preserve fake/packet/real evidence labels.
- Do not trust worker self-reported evidence as observed evidence.
- Keep simple tasks lightweight.

Before finishing:

```text
Files changed:
Runtime path affected:
Tests run:
Result:
Remaining risk:
Next step:
```
