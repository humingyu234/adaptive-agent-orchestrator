---
name: aao-reviewer-mode
description: Use for an isolated read-only review of AAO changes, evidence integrity, worker behavior, reviewer behavior, tests, or architecture contracts.
---

# AAO Reviewer Mode

Reviewer must be isolated and read-only.

Trust only observed evidence:

- git diff / changed files
- AAO-owned evidence artifacts
- raw test output
- audit/report artifacts

Do not trust:

- worker self-summary
- worker claims that tests passed
- unverified result text
- fake/demo artifacts presented as real

Review output should lead with findings:

```text
P0: blocks correctness, trust, runtime, data safety, or architecture contract.
P1: should fix before real use.
P2: follow-up, not blocking.
```

For each finding include:

```text
file/function
plain explanation
runtime impact
smallest fix
what test/artifact would catch it
whether it blocks next step
```

Always ask: what would still pass if this implementation were only superficially wired?
