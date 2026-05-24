# AAO Current State

Updated: 2026-05-25

## Current Judgment

AAO is not broken or thrown away. It is a production-minded prototype with a real control-plane skeleton, but it still needs two hardening steps before it can be trusted for real project work:

1. Independent evidence integrity: AAO must verify worker results itself.
2. Worker reliability: AAO must preflight real Claude Code workers before launching long tasks.

## What Is Real Today

- Mainline execution path exists: task -> plan -> worker packet -> worker -> evidence -> ControlPlane -> reviewer -> audit.
- ControlPlane, policy, guardrails, recovery, failure taxonomy, project session, resume, audit report, and fake/packet workers have broad test coverage.
- Claude Code worker bridge is a real subprocess path, not only an in-memory mock.
- Project session and milestone flow exist, but still need real medium/large validation with observed evidence.

## Current Weak Spots

- Some evidence still depends on worker-written files such as `status.json`, `test_output.txt`, and `diff.patch`.
- AAO does not yet have a merged independent evidence module that always runs `git status`, `git diff`, and `required_checks` itself.
- Real Claude Code worker execution can fail or hang because CLI/env/API/proxy state is not checked before milestone execution.
- Fake/dry-run paths are useful for tests, but they must stay clearly labeled as fake evidence.
- Memory/OpenViking work is useful later, but it is not the current blocker.

## Recent Local Fixes Pending In Worktree

- Reverted default Claude worker args from `--permission-mode auto` back to `-p --verbose`, because a real worker run timed out after 600s with no stdout/stderr after adding the flag.
- Added read-only packet handling so read-only milestones do not require diff/test evidence or policy checks.
- Project session start now defers missing file-boundary concerns into open risks instead of blocking milestone creation immediately.
- Fake worker can now complete explicit read-only packets without pretending to change files.

## Current Priority

Do not expand features yet. Stabilize the path that matters:

```text
real worker can start
-> AAO independently verifies evidence
-> medium task runs end to end
-> large project session runs with resume/audit
```

