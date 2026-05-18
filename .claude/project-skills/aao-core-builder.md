# AAO Core Builder

Use when modifying AAO core architecture.

## Rules

- State the current phase before editing.
- State the one behavior this phase adds.
- State non-goals.
- List expected files before editing.
- Keep changes inside the phase boundary.
- Prefer adding a small facade over moving many files.
- Preserve existing CLI and workflow behavior.
- Do not add heavy dependencies in core phases.
- After editing, run targeted tests and report results.

## Phase Output

```text
Phase:
Goal:
Files changed:
Tests added:
Commands run:
Result:
Remaining risk:
Next phase:
```
