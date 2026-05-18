# AAO Phase Handoff

Use at the end of every phase or before stopping work.

The next Claude Code session should be able to continue without guessing what
happened. The handoff must be factual, short, and grounded in files and test
results.

Include:

- current phase
- phase goal
- completed work
- changed files
- dirty files outside the current phase scope
- tests added or changed
- exact test commands run
- test result
- reviewer result if a reviewer session was used
- known risks
- deferred ideas
- next recommended step
- whether it is safe to proceed
- recommended next commit slice

Good handoff:

```text
Current phase: Phase 2 - ControlPlane Facade
Completed: added ControlPlane.evaluate_output / guard_input / guard_output
Changed files: ...
Dirty files outside phase scope: docs/... and .claude/... only
Tests: python -m pytest tests/test_control_plane.py -> passed
Reviewer: no P0, one P1 deferred
Risks: scheduler not integrated yet
Next: Phase 3, wire Scheduler to ControlPlane for evaluation only
Safe to proceed: yes
Next commit slice: stage src/orchestrator/control_plane.py and tests/test_control_plane.py only
```

Do not use vague status like "mostly done" without file and test evidence.
Do not hide a messy working tree. If unrelated files are modified, name them.
