# AAO Current State

Updated: 2026-05-25

## Current Judgment

AAO is not broken or thrown away. It is a production-minded prototype with a real control-plane skeleton. The first evidence-hardening step has now been absorbed from the Opus review; the next hardening step is worker preflight.

1. Independent evidence integrity: AAO now has a first merged path for AAO-owned checks/diff after real `claude-code` worker execution.
2. Worker reliability: AAO still needs to preflight real Claude Code workers before launching long tasks.

## What Is Real Today

- Mainline execution path exists: task -> plan -> worker packet -> worker -> evidence -> ControlPlane -> reviewer -> audit.
- ControlPlane, policy, guardrails, recovery, failure taxonomy, project session, resume, audit report, and fake/packet workers have broad test coverage.
- Claude Code worker bridge is a real subprocess path, not only an in-memory mock.
- Project session and milestone flow exist, but still need real medium/large validation with observed evidence.

## Current Weak Spots

- Independent evidence is currently integrated for the `claude-code` mainline path. Packet/fake/multi-worker/langgraph paths still need explicit boundary decisions.
- Independent git evidence is based on the current git worktree. Real task runs should start from a known baseline, or a future baseline snapshot should be added.
- Real Claude Code worker execution can fail or hang because CLI/env/API/proxy state is not checked before milestone execution.
- Fake/dry-run paths are useful for tests, but they must stay clearly labeled as fake evidence.
- Memory/OpenViking work is useful later, but it is not the current blocker.

## Recent Local Fixes Pending In Worktree

- Reverted default Claude worker args from `--permission-mode auto` back to `-p --verbose`, because a real worker run timed out after 600s with no stdout/stderr after adding the flag.
- Added read-only packet handling so read-only milestones do not require diff/test evidence or policy checks.
- Project session start now defers missing file-boundary concerns into open risks instead of blocking milestone creation immediately.
- Fake worker can now complete explicit read-only packets without pretending to change files.
- Added independent evidence capture for real `claude-code` worker runs:
  `observed/aao_test_output.txt`, `observed/aao_diff.patch`, AAO-owned `git status`, and AAO-run `required_checks`.

## Current Priority

Do not expand features yet. Stabilize the path that matters:

```text
real worker can start
-> AAO independently verifies evidence
-> medium task runs end to end
-> large project session runs with resume/audit
```
