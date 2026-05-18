# Phase 17 - Demo, README, and Release

## Goal

Make AAO understandable and runnable by a stranger, and make the user's work
easy to evaluate for hiring, collaboration, and open-source use.

## Why This Phase Exists

Good engineering work still needs to be legible. This phase turns AAO from a
working system into proof of ability.

## Non-Goals

- No inflated production claims.
- No fake user adoption.
- No marketing page instead of a working quickstart.
- No demo that hides limitations.

## Allowed Files

```text
README.md
examples/
scripts/
tests/
CLAUDE.md
```

Do not rewrite core runtime logic in this phase unless a demo exposes a real
bug that must be fixed.

## Required Artifacts

```text
README first screen explains value in 30 seconds
quickstart works in a clean environment
3 demo scripts
sample Live Watch output
sample Audit Report
sample EvidencePack
3-5 minute demo video script
known limitations section
```

Demo scenarios:

```text
1. Worker says done but required tests/evidence are missing; AAO blocks success.
2. Worker touches a protected file; AAO pauses for human review.
3. Complex task goes through planning, execution, live watch, recovery, and audit.
```

## Required Tests / Checks

```text
quickstart command works from clean clone or documented venv
demo scripts run
golden scenario suite passes
README commands match real commands
sample outputs are generated from real runs or clearly marked sample
```

## Commands

```bash
python -m pytest
python -m pytest tests/golden tests/test_golden_scenarios.py
```

Add any project-specific demo command once it exists.

## Definition Of Done

- A stranger can understand what AAO does from the README first screen.
- A stranger can run the quickstart.
- The demo proves control behavior, not only happy-path generation.
- Limitations are honest.
- The user can record a 3-5 minute video from the scripts.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Focus on proof and clarity. Do not oversell.
Do not change core behavior unless a real bug blocks the demo.
