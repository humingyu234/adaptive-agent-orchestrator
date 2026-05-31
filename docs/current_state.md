# AAO Current State

Updated: 2026-06-01

## Current Judgment

AAO is not broken or thrown away. It is a production-minded prototype with a real control-plane skeleton. The real single-worker `claude-code` mainline now has evidence-integrity hardening and Worker Doctor preflight; the next runtime blocker is a real medium-task acceptance run.

1. Independent evidence integrity: AAO now records a pre-worker git baseline, computes the worker-attributable delta, executes bounded `required_checks`, and feeds AAO-owned evidence to both reviewer layers on the real single-worker `claude-code` path.
2. Worker reliability: AAO now runs a bounded Claude Code Worker Doctor before long real worker tasks and records AAO-owned doctor evidence.

## What Is Real Today

- Mainline execution path exists: task -> plan -> worker packet -> worker -> evidence -> ControlPlane -> reviewer -> audit.
- ControlPlane, policy, guardrails, recovery, failure taxonomy, project session, resume, audit report, and fake/packet workers have broad test coverage.
- Claude Code worker bridge is a real subprocess path, not only an in-memory mock.
- Project session and milestone flow exist, but still need real medium/large validation with observed evidence.

## Current Weak Spots

- Independent evidence is currently integrated for the real single-worker `claude-code` mainline path. Packet/fake/multi-worker/langgraph paths still need explicit boundary decisions.
- Auto-repair executed by a real `claude-code` worker now uses independent evidence for fix verification, but the broader audit representation of multi-round repair still deserves acceptance validation.
- Real Claude Code worker execution now has preflight, but still needs a live medium-task acceptance run to prove the local CLI/env/API/proxy path works outside tests.
- Fake/dry-run paths are useful for tests, but they must stay clearly labeled as fake evidence.
- Memory/OpenViking work is useful later, but it is not the current blocker.

## Recent Stabilization Fixes

- Reverted default Claude worker args from `--permission-mode auto` back to `-p --verbose`, because a real worker run timed out after 600s with no stdout/stderr after adding the flag.
- Added read-only packet handling so read-only milestones do not require diff/test evidence or policy checks.
- Project session start now defers missing file-boundary concerns into open risks instead of blocking milestone creation immediately.
- Fake worker can now complete explicit read-only packets without pretending to change files.
- Added independent evidence capture for real `claude-code` worker runs:
  `observed/aao_test_output.txt`, `observed/aao_diff.patch`, AAO-owned `git status`, and AAO-run `required_checks`.
- Added `observed/aao_baseline.json` and baseline-relative diff/file attribution, so pre-existing dirty files are not blamed on the current worker.
- Baseline integrity also blocks real workers that alter Git `HEAD` or the index, so they cannot silently commit/stage pre-existing user edits.
- Unified RuleBasedReviewer and CodexReviewer on the same AAO-owned evidence bundle.
- Added a bounded required-check runner policy and one total timeout budget for AAO-run checks.
- Real controlled `claude-code` execution now requires a git worktree; otherwise it stops before worker launch rather than downgrading silently to worker-reported evidence.
- Slimmed `CLAUDE.md` into a session front door and moved detailed project operating modes into official `.claude/skills/<skill>/SKILL.md` entrypoints. Legacy `.claude/project-skills/` files are retained only for old phase specs.
- Added Claude Code Worker Doctor preflight. AAO now runs a short `claude -p` smoke test before long real worker tasks, records `observed/aao_worker_doctor.json`, `observed/aao_worker_doctor_stdout.txt`, and `observed/aao_worker_doctor_stderr.txt`, and blocks before the long worker if preflight fails.

## Verification Baseline

- Targeted evidence/reviewer/worker/doctor tests: `89 passed` on the latest Worker Doctor slice.
- Previous targeted evidence/reviewer/worker tests: `179 passed`.
- Full test suite: `1360 passed, 2 skipped, 32 subtests passed`.

## Current Priority

Do not expand features yet. Stabilize the path that matters:

```text
real worker can start
-> AAO independently verifies evidence
-> medium task runs end to end
-> large project session runs with resume/audit
```
