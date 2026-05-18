# AAO Reviewer Mode

Use in a separate read-only session. The reviewer must not edit files.

## Reviewer Jobs

1. Find real engineering risks.
2. Explain important risks plainly enough for the user to decide.
3. Verify that the implementation satisfies the architecture contract, not only
   that tests are green.

Reviewer input should include only:

- current phase goal
- relevant phase spec / architecture contract
- git diff
- test output
- relevant file paths

## Severity

```text
P0
  Blocking correctness, data loss, false evidence, broken tests, broken runtime,
  or architecture-direction issues.

P1
  Should-fix design, boundary, or maintainability issues.

P2
  Follow-up improvements that do not block this phase.
```

## Finding Shape

Each finding should include:

- file/function
- plain-language explanation
- runtime impact
- concrete break example
- smallest fix
- whether it blocks the next phase
- architecture contract affected, if any
- what existing test would still pass even if this implementation is wrong
- user translation for P0/P1 findings

## Architecture Contract Review

Before judging a change, name the contract it is supposed to satisfy.

Examples:

```text
Known failure categories must be propagated explicitly.
infer_failure_category may be used only for unknown fallback paths.

ControlPlane must stay runner-independent.

Evidence marked observed must come from system-observed output, not worker
claims.

Reviewer workers must be read-only.
```

Then trace the runtime path:

```text
source event -> control decision -> scheduler/runner -> state -> report/audit
```

Do not accept "the final value looks correct" as enough proof. A guessed value
can look correct while violating the contract.

## Anti-False-Green Tests

For every important review, ask:

```text
What test would still pass if the implementation were secretly wrong?
```

If such a test exists, request a stronger test that checks the path, not only
the final value.

Examples:

```text
Weak:
  assert failure_record.category == GUARDRAIL_BLOCKED

Stronger:
  known guardrail failures propagate the explicit category and do not call the
  infer fallback.

Weak:
  report contains evidence

Stronger:
  observed evidence is created only from captured command output, not from a
  worker saying "tests passed".
```

Use monkeypatch/spies when needed to prove a forbidden fallback was not called.

## Checklist

- Did the change stay within the current phase?
- Did it avoid package-wide moves?
- Did ControlPlane remain runner-independent?
- Are tests behavior-based?
- Is evidence real, not invented?
- Did existing runtime behavior remain stable?
- Are there hidden slow paths or extra LLM calls?
- Does this make simple tasks heavier?
- Did the implementation actually follow the phase architecture contract?
- Did the review trace the runtime path end to end?
- Are known facts propagated directly instead of being re-inferred from text?
- Is any deprecated/fallback path still used as the main path?
- Would the current tests pass if the new design were only superficially wired?

## Explanation Standard

When reporting a P0/P1 issue, explain it like this:

```text
The symptom:
  What looks okay from the outside.

The hidden path:
  The actual source -> decision -> report path.

Why it matters:
  What can go wrong in real runs.

Smallest fix:
  The minimal code/test change.
```

Keep the wording natural and concrete. The user should be able to explain the
bug back in plain language after reading the review.
