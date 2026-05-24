# Opus Review Follow-Up

Source reviewed: `C:\Users\Administrator\Desktop\aao-review-output\aao-review-handoff`

Updated: 2026-05-25

## Plain-Language Takeaway

Opus did not say AAO is a toy. It said AAO has a real control-plane skeleton, but its central promise is not fully enforced yet:

```text
AAO should trust evidence over worker claims.
```

The weak point is that some current evidence is still written by the worker itself:

- `status.json`
- `test_output.txt`
- `diff.patch`

That means a worker that lies consistently could claim success, write clean-looking logs, hide changed files, and pass through parts of the system.

## Main Recommendation To Absorb

AAO should independently verify the worker result after real worker execution:

- run `git status --porcelain`;
- run `git diff HEAD`;
- run the packet's `required_checks`;
- write AAO-owned files:
  - `observed/aao_test_output.txt`
  - `observed/aao_diff.patch`

Worker-written evidence should be treated as reported evidence. AAO-generated evidence should be treated as observed evidence.

## Patch Status

The review package includes:

- `02-CHANGE-evidence-integrity.md`
- `evidence-integrity.patch`
- `new-files/independent_evidence.py`
- `new-files/test_independent_evidence.py`

Current repo status on 2026-05-25:

- `src/orchestrator/independent_evidence.py` has been added.
- `tests/test_independent_evidence.py` has been added.
- Mainline `claude-code` execution now captures AAO-owned evidence after worker execution.
- Mainline captures `observed/aao_baseline.json` before worker execution and reports only baseline-relative file changes/diff afterward.
- The baseline also records Git `HEAD` and staged-index state; changing either during a real worker run is a policy violation.
- Both RuleBasedReviewer and CodexReviewer now consume the same bundle, preferring `observed/aao_diff.patch` and `observed/aao_test_output.txt`.
- `required_checks` are filtered to bounded test/lint command families before real worker launch, and AAO-run checks share one total timeout budget.
- Real `claude-code` execution without a git baseline is blocked before launch instead of falling back to worker-reported evidence.
- Validation after follow-up fixes: `1356 passed, 2 skipped, 32 subtests passed`.

## Acceptance Tests Needed

- A worker claims success and writes a passing-looking `test_output.txt`, but AAO's own check exits non-zero -> AAO blocks/retries.
- A worker reports `changed_files: []`, but actually modifies a denied file -> AAO catches it via `git status`.
- A normal passing check produces a clean decision.
- Non-git projects degrade honestly instead of pretending to have independent git evidence.

## Remaining Boundaries

- The first integration is for the real `claude-code` mainline path.
- Packet/fake/multi-worker/langgraph evidence labeling still needs explicit follow-up.
- Real auto-repair now independently verifies its fix packet; the final audit representation of multi-round repair still needs an acceptance test.
- An allowlisted test command can still execute repository test code; command filtering prevents arbitrary launcher commands but is not a sandbox.

## Relationship To Worker Doctor

Independent Evidence is post-run verification:

```text
Did the worker actually do the job correctly?
```

Worker Doctor is pre-run verification:

```text
Can the real worker start and talk to its model/API before we wait on a long task?
```

Both are P0, but they solve different failure points.
