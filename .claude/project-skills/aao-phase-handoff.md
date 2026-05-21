# AAO Phase Handoff

Use at the end of every phase or before stopping work.

The next Claude Code session should be able to continue without guessing what
happened. The handoff must be factual, short, and grounded in files and test
results.

Include:

- current phase
- phase goal
- 完成了哪条主链路（具体 runtime path）
- 哪些是 real（真 worker / 真 LLM / 真 reviewer）
- 哪些是 mock（fake worker / fake reviewer / deterministic planner）
- 哪些还只是 artifact（spec 写了但代码未接）
- changed files
- dirty files outside the current phase scope
- tests added or changed
- exact test commands run
- test result
- reviewer result if a reviewer session was used
- known risks
- 下一步缺口是什么
- deferred ideas
- next recommended step
- whether it is safe to proceed
- recommended next commit slice

Good handoff:

```text
Current phase: Phase 22 - Task Auto Repair Loop
主链路: worker fail → ReviewFinding → FixTask → retest → pass
Real: RuleBasedReviewer + fake worker
Mock: Claude Code worker (用 fake subprocess)
Artifact only: LLMReviewer 接口预留但未实现
Changed files: src/orchestrator/repair.py, tests/test_repair.py
Dirty files outside phase scope: none
Tests: python -m pytest tests/test_repair.py -> 9 passed
Reviewer: no P0, one P1 deferred (FixTask 暂不支持多文件修复)
Risks: 和 Phase 11 recovery 的交互需要更明确
下一步缺口: Reviewer 还是 inline 的，没隔离（Phase 23 解决）
Next: Phase 23, isolate reviewer from worker
Safe to proceed: yes
Next commit slice: src/orchestrator/repair.py + tests/test_repair.py
```

Do not use vague status like "mostly done" without file and test evidence.
Do not hide a messy working tree. If unrelated files are modified, name them.
Do not claim "real" when the path is mock, artifact, or fake.
