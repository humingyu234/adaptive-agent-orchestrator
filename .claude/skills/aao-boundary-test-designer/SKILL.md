---
name: aao-boundary-test-designer
description: Use before adding or changing AAO runtime behavior, especially policy, guardrails, evidence, workers, reviewers, repair, routing, or project session flow.
---

# AAO Boundary Test Designer

Design tests around the contract, not just final values.

Use this matrix for risky changes:

```text
Contract:
Bad case:
Normal case:
Boundary case:
False-positive case:
Regression path:
Contract/path case:
```

Ask:

```text
Would this test still pass if the implementation guessed the right final value?
```

If yes, strengthen the test to prove the runtime path.

Examples:

- Observed evidence must come from AAO-captured output, not worker claims.
- Known failure categories must propagate directly, not through text inference.
- Reviewers must not write files.
- Required checks must be bounded and safe.
- Fake paths must not be reported as real execution.
