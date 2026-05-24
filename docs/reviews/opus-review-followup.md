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

Current repo check on 2026-05-25:

- `src/orchestrator/independent_evidence.py` is not yet present.
- `aao_test_output` / `aao_diff` markers are not present in current source.
- `git apply --check evidence-integrity.patch` succeeded, but the worktree already has unrelated local changes, so this should be absorbed after current changes are committed or otherwise separated.

## Acceptance Tests Needed

- A worker claims success and writes a passing-looking `test_output.txt`, but AAO's own check exits non-zero -> AAO blocks/retries.
- A worker reports `changed_files: []`, but actually modifies a denied file -> AAO catches it via `git status`.
- A normal passing check produces a clean decision.
- Non-git projects degrade honestly instead of pretending to have independent git evidence.

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

