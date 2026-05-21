# Adaptive Agent Orchestrator - Claude Code Working Guide

This file is the project-level operating guide for Claude Code when working on
Adaptive Agent Orchestrator (AAO).

Read this before making changes. Follow it unless the user explicitly overrides
the plan.

---

## 0. Final Product Direction

AAO is an Agent Runtime Control Plane.

It is not:

- a Claude Code replacement
- a LangGraph replacement
- a generic all-in-one agent framework
- a tracing platform
- an eval SaaS
- a heavyweight workflow platform for every tiny task

It is:

- a control layer for agent workflows
- a runtime judge for whether a step should continue, retry, replan, pause for
  human review, roll back, or fail
- a system for evidence, live progress, failure classification, and audit
  reports

Why this position:

Better models and workers improve agent capability. AAO improves agent
reliability by judging whether a step is correct, risky, incomplete, or
recoverable independent of which model or worker produced it. These are
different problems; keep the control layer independent from the worker layer.

Final intended shape:

```text
Human
  -> Claude Code frontend
  -> AAO command protocol
  -> AAO Control Plane
      -> Task sizing
      -> Plan contract
      -> Policy engine
      -> Evaluator gate
      -> Guardrails
      -> Failure taxonomy
      -> Human review gate
      -> Evidence pack
      -> Live run view
      -> Audit report
      -> Regression compare
  -> Runner layer
      -> NativeRunner
      -> LangGraphRunner
      -> ClaudeCodeWorker
      -> TestWorker
      -> ReviewWorker
```

The user should still communicate with Claude Code naturally. AAO should work in
the background as the control, visibility, and audit layer.

Layer terminology:

```text
Claude Code frontend
  The user's primary conversation and coding interface.

AAO Control Plane
  The runtime control layer: task sizing, plan contracts, policy, evaluator
  gates, guardrails, failure taxonomy, recovery decisions, evidence, live view,
  human review, audit reports, and regression comparison.

Runner / Execution Engine
  The system that executes workflow structure. NativeRunner and LangGraphRunner
  are runners. They are not workers.

Worker
  The actor that performs work inside a step: Claude Code, an LLM provider, a
  search/tool worker, TestWorker, ReviewWorker, or HumanReviewer.

ECC / Everything Claude Code
  A Claude Code worker-discipline pack: commands, hooks, agents, rules, and
  skills that make Claude Code behave more predictably. It can strengthen the
  Claude Code worker, but it is not the AAO control layer.

Claude Code Agent View
  A multi-session view for Claude Code workers. It shows which sessions are
  running, waiting, or complete. It is not a quality/evidence/control monitor.

AAO Live Watch
  A control-layer view. It shows task progress, current step, last decision,
  evidence, failure classification, recovery action, and human-review state.
```

Keep these terms strict. Do not call NativeRunner or LangGraphRunner workers.
Do not turn AAO Live Watch into a clone of Claude Code Agent View.

---

## 1. Hard Constraints

Do not do these unless the user explicitly asks:

- Do not create a new top-level `aao/` package yet.
- Do not move `agents`, `llm`, `cli`, `models`, `workflow`, `state`, or
  `scheduler` into a new package in one large step.
- Do not rewrite `scheduler.py` from scratch.
- Do not remove or reset existing user changes.
- Do not edit `.env`, secrets, generated outputs, `.venv`, or `tmp/` unless the
  task explicitly requires it.
- Do not add LangGraph, Langfuse, DeepEval, LiteLLM, OPA, or Casbin in the core
  phases.
- Do not add extra LLM calls to the default control path.
- Do not make simple tasks slower by forcing them through heavyweight workflow
  machinery.
- Do not claim evidence exists unless the code actually records it.

Default principle:

```text
AAO core must be lightweight by default and extensible by adapter.
```

Over-design filter:

Before adding any new subsystem, ask whether it clearly helps at least one of
these product goals:

```text
- make AI task execution less likely to drift
- detect failure earlier
- reduce wasted time or tokens
- make evidence more trustworthy
- make runtime progress more visible
- make human review safer and better timed
- make the project easier to demonstrate, review, or use
```

If the answer is not a clear yes, defer the idea. Prefer a thin adapter over a
new platform.

External wheel intake rule:

AAO is not a wheel collector. External projects such as Hermes Agent,
LangGraph, Claude Code, ECC, Langfuse, LangSmith, Braintrust, Guardrails AI,
or OpenTelemetry may be studied only through this filter:

```text
Does this strengthen AAO's control loop?

control loop:
observe execution
  -> detect abnormal behavior
  -> classify the failure
  -> choose bounded recovery
  -> record evidence
  -> expose progress/audit state
```

Only take an external idea if it clearly improves one of these control-loop
links. Do not take features just because they are impressive.

Allowed intake forms:

```text
learn a failure mode
learn a small control primitive
write a thin adapter
add a deterministic test scenario
```

Forbidden intake forms:

```text
merge another agent framework into AAO core
copy an entire conversation loop
copy an entire gateway/TUI/memory/plugin platform
make AAO depend on a large external system before its own core contract is stable
```

Stop adding wheels when AAO can prove its own core value:

```text
one real worker can be controlled
20+ golden reliability scenarios can run
false completion can be blocked
failure categories map to recovery actions
evidence and audit reports are real, not claimed
the 3-5 minute demo is clear to a new reviewer
```

---

## 2. Work Modes

AAO should support these final modes:

```text
off
  Use Claude Code directly. No AAO involvement.

log
  AAO records the task and outcome but does not block or route execution.

controlled
  AAO performs control checks, evidence collection, failure classification,
  human gates, live status, and audit reporting.

orchestrated
  AAO uses a runner such as LangGraph for complex multi-stage workflows with
  checkpoint, resume, branching, parallel work, and human interrupt.
```

Task sizing rule:

```text
small task
  1-2 files, low risk, easy to inspect, under about 30 minutes.
  Use off/log.

medium task
  one feature slice, several files, tests required, review needed.
  Use controlled.

large task
  multi-stage, multi-worker, long-running, resumable, or needs branching.
  Use orchestrated.
```

Do not force AAO onto small tasks.

---

## 3. Current Implementation Reality

The current AAO implementation already has useful control pieces, but they are
spread across the runtime:

- `src/orchestrator/scheduler.py`
  - currently acts as the native runtime loop
  - owns much of execution, evaluation, failure handling, checkpoints, and final
    reporting
- `src/orchestrator/evaluator.py`
  - L1 structural evaluation and optional L2 semantic evaluation
- `src/orchestrator/guardrails.py`
  - input and output guardrails
- `src/orchestrator/failure_taxonomy.py`
  - failure categories, severity, and failure records
- `src/orchestrator/report_writer.py`
  - convergence/audit report generation
- `src/orchestrator/agents/base.py`
  - tool declaration and trust-level tool permission checks

The next architectural move is not a big package migration. The next move is to
create a stable ControlPlane facade that can reuse these pieces.

---

## 4. Target Core Contracts

The project needs a small set of common contracts that every runner and worker
can speak.

Suggested models:

```text
TaskSize
  small | medium | large

RunMode
  off | log | controlled | orchestrated

ControlAction
  continue | retry | replan | rollback | needs_human_review | fail

ControlDecision
  action
  passed
  reason
  severity
  failure_category
  evidence_required
  next_step_hint

WorkerTask
  task_id
  objective
  allowed_files
  required_checks
  risk_level
  mode

WorkerResult
  task_id
  worker_name
  status
  output
  files_changed
  commands_run
  tests_run
  errors

EvidencePack
  task_id
  step_name
  files_changed
  commands_run
  test_results
  diff_summary
  notes
```

These contracts should be small, typed, serializable, and runner-independent.

---

## 5. Construction Plan

Work in phases. Do not skip phase gates. Each phase must have targeted tests and
must preserve existing behavior unless the phase explicitly changes it.

CLAUDE.md keeps the product map and hard constraints. Detailed construction
specs live in `.claude/phase-specs/`. For any phase, read the matching phase
spec before editing files.

### Core Phases (0-7B) — AAO Core Foundation

| Phase | Name | Spec File |
|-------|------|-----------|
| 0 | Baseline Inspection | `.claude/phase-specs/phase-00-baseline-inspection.md` |
| 1 | Core Models | `.claude/phase-specs/phase-01-core-models.md` |
| 2 | ControlPlane Facade | `.claude/phase-specs/phase-02-control-plane-facade.md` |
| 3 | Scheduler Uses ControlPlane | `.claude/phase-specs/phase-03-scheduler-uses-control-plane.md` |
| 4 | EvidencePack | `.claude/phase-specs/phase-04-evidence-pack.md` |
| 5 | Live Run View | `.claude/phase-specs/phase-05-live-run-view.md` |
| 6 | Policy YAML | `.claude/phase-specs/phase-06-policy-yaml.md` |
| 7 | Final Integration Gate | `.claude/phase-specs/phase-07-final-integration-gate.md` |
| 7A | Core Closure Gate | `.claude/phase-specs/phase-07a-core-closure-gate.md` |
| 7B | Hermes-Informed Hardening | `.claude/phase-specs/phase-07b-hermes-informed-hardening.md` |

---

## 5B. AAO v1 Product Release Plan

Phase 0-7B closes AAO Core. Phase 8-17 make that core visible, routed,
policy-aware, recoverable, planned, memory-backed, tested, and demo-ready.

Important: Phase 8-17 do not prove the original end-to-end blueprint by
themselves if the Claude Code worker path is still fake, packet-only, or manual.
Phase 18 is the real-worker hard landing gate.

After Phase 18 passes real smoke, the remaining landing work is not "more
features". It is exactly three integration gaps:

```text
Phase 19  real LLM Planning Council
Phase 20  multi-worker execution from an approved plan
Phase 21  end-to-end blueprint acceptance
```

Do not add new roadmap phases or optional integrations before these three are
done. The goal is to make the user's original workflow real, not to keep growing
the framework sideways.

CLAUDE.md keeps the product map and hard constraints. Detailed construction
specs live in .claude/phase-specs/. For Phase 8+, always read the matching
phase spec before editing files.

Product-release phases:

```text
Phase 8   Real-Time Watch
          Make runtime progress, evidence, failures, recovery, and human-review
          state visible while a task is running.

Phase 9   Task Router
          Route small/medium/large work into off/log/controlled/orchestrated
          modes without making simple tasks heavy.

Phase 9A  Runtime Mode + Cleanup Contract
          Turn the routing labels into explicit runtime semantics and stop the
          CLI/scheduler from accumulating more mixed responsibilities before
          policy, recovery, worker, and LangGraph phases add more pressure.

Phase 10  Runtime Policy Enforcement
          Turn declarative policy into minimal real runtime blocking/review
          behavior for protected files, high-risk tools, failed checks, and
          missing evidence.

Phase 11  Recovery Playbook
          Map failure categories to bounded actions such as retry, request
          evidence, replan, human review, or fail.

Phase 12  Claude Code Worker Bridge
          Let AAO create task packets for Claude Code workers and verify the
          returned evidence/result files.

Phase 12A ECC Integration Pack
          Use ECC-style commands, hooks, and worker rules to make Claude Code
          workers more disciplined without replacing AAO ControlPlane.

Phase 13  Planning Council
          For complex tasks, create a plan, challenge risks, merge a final plan,
          and require user approval before execution.

Phase 14  Memory Layer
          Add lightweight inspectable project memory for decisions, constraints,
          failures, and runs, with observed/reported/inferred source labels.

Phase 15  LangGraph Runner
          Add LangGraph as an optional orchestrated-mode runner for complex DAG,
          checkpoint, resume, branching, and human interrupt.

Phase 16  Golden Scenario Suite
          Prove AAO's control behavior with deterministic scenarios such as
          missing evidence, policy deny, human review, recovery, and audit.

Phase 17  Demo, README, and Release
          Make AAO easy to understand, run, trust, and record in a 3-5 minute
          demo.

Phase 18  Real Claude Code Worker Bridge
          Prove the real path: ask -> route -> plan -> user approval ->
          launch Claude Code worker -> collect observed evidence -> apply
          ControlPlane -> audit report. No fake worker may satisfy this gate.

Phase 19  Real LLM Planning Council
          Replace deterministic advisor-only planning with provider-backed
          planner / critic / execution-planner advisors, while keeping local
          deterministic advisors only for tests and fallback. This phase also
          owns the Prompt Quality Gate: centralized advisor prompts, golden
          planning cases, local validators, and real-provider smoke tests. A
          model response that is not worker-ready does not count.

Phase 20  Multi-Worker Plan Execution
          Turn the approved plan into one or more bounded worker tasks, execute
          independent tasks in parallel where safe, and keep per-worker evidence,
          policy, recovery, and audit decisions separate.

Phase 21  Blueprint End-to-End Acceptance
          Prove the original user workflow with real commands: task -> multi-LLM
          planning -> user approval -> real worker execution -> control gates ->
          evidence -> audit report. No mock-only success may pass this phase.
```

Phase spec index:

```text
.claude/phase-specs/phase-00-baseline-inspection.md
.claude/phase-specs/phase-01-core-models.md
.claude/phase-specs/phase-02-control-plane-facade.md
.claude/phase-specs/phase-03-scheduler-uses-control-plane.md
.claude/phase-specs/phase-04-evidence-pack.md
.claude/phase-specs/phase-05-live-run-view.md
.claude/phase-specs/phase-06-policy-yaml.md
.claude/phase-specs/phase-07-final-integration-gate.md
.claude/phase-specs/phase-07a-core-closure-gate.md
.claude/phase-specs/phase-07b-hermes-informed-hardening.md
.claude/phase-specs/phase-08-real-time-watch.md
.claude/phase-specs/phase-09-task-router.md
.claude/phase-specs/phase-09a-runtime-mode-cleanup-contract.md
.claude/phase-specs/phase-10-runtime-policy-enforcement.md
.claude/phase-specs/phase-11-recovery-playbook.md
.claude/phase-specs/phase-12-claude-code-worker-bridge.md
.claude/phase-specs/phase-12a-ecc-integration-pack.md
.claude/phase-specs/phase-13-planning-council.md
.claude/phase-specs/phase-14-memory-layer.md
.claude/phase-specs/phase-15-langgraph-runner.md
.claude/phase-specs/phase-16-golden-scenario-suite.md
.claude/phase-specs/phase-17-demo-readme-release.md
.claude/phase-specs/phase-18-real-claude-code-worker-bridge.md
.claude/phase-specs/phase-19-real-llm-planning-council.md
.claude/phase-specs/phase-20-multi-worker-plan-execution.md
.claude/phase-specs/phase-21-blueprint-e2e-acceptance.md
```

Do not ask Claude Code to implement Phase 8-21 in one pass. Start exactly one
phase at a time, read that phase spec, implement it, test it, hand it off, and
review it before moving on.

Do not start Phase 8 until Phase 7B is reviewed. Phase 8 is a visibility phase;
it should display real control decisions, not compensate for a shallow
ControlPlane.

Do not claim "complete landing" after Phase 17 if `--worker-mode claude-code`
does not launch a real Claude Code worker process. Passing fake-worker, packet,
demo, or golden-scenario tests proves the control chain; it does not prove the
real daily-use workflow.

Do not claim "original blueprint complete" after Phase 18 either. Phase 18 proves
one real worker can execute. The blueprint is complete only after Phase 21 proves:

```text
real planning council
  -> explicit user approval
  -> real worker execution
  -> evidence-gated control decisions
  -> audit/report output
```

---

## 6. Optional Integrations - Not Core Phases

These are future adapters. Do not add them during Phase 0-7B. When a later
product-release phase introduces one, use it as a thin adapter, not as the AAO
brain.

```text
LangGraph
  Use later for complex DAG, parallelism, checkpoint, resume, and human
  interrupt. It should be a runner, not the AAO brain.

Langfuse
  Use later as trace/export dashboard. It should receive AAO events, not control
  AAO decisions.

DeepEval
  Use later for offline regression/eval suites. It should test AAO outputs, not
  replace ControlPlane.

LiteLLM
  Use later for model gateway, provider routing, fallback, and cost tracking.

Guardrails AI
  Use later as optional validator adapters. Keep AAO GuardrailManager as the
  control entry point.

OPA/Casbin
  Use much later only if enterprise policy needs justify it. Start with YAML
  policy.

Hermes Agent
  Do not integrate Hermes as a whole system. Treat it as a mature execution
  project to study for failure modes and small control primitives. Acceptable
  references: error classification, tool-loop guardrails, jittered retry, and
  worker isolation checklists. Future support may be a thin HermesWorker
  adapter, not a Hermes-based AAO core.
```

---

## 7. Project Skills

Use project skills as operating modes. CLAUDE.md keeps the index and global
communication rule; detailed project-skill instructions live in
.claude/project-skills/.

Communication rule for all project skills:

```text
Use the skill as an internal operating checklist, not a rigid answer template.
Be strict about evidence, tests, scope, file paths, and validation.
Be natural in explanation and teaching.
Use structured checklists when risk is high, when reviewing code, or when
handing off a phase. For quick explanations, use clear prose first.
```

If the user says they do not understand, slow down and explain the concrete
runtime path before adding more abstraction.

Project-skill index:

```text
.claude/project-skills/aao-core-builder.md
  Use when modifying AAO core architecture.

.claude/project-skills/aao-boundary-test-designer.md
  Use before adding or changing runtime behavior.

.claude/project-skills/aao-reviewer-mode.md
  Use in a separate read-only review session. Reviewer must check final
  behavior, runtime path, architecture contract, and false-green tests.

.claude/project-skills/aao-tutor-explanation.md
  Use after every phase, feature slice, bug fix, or important design decision.

.claude/project-skills/aao-scope-guard.md
  Use when the task starts expanding or a dependency/feature feels tempting.

.claude/project-skills/aao-live-visibility.md
  Use when implementing runtime status, progress, evidence, or reporting.

.claude/project-skills/aao-phase-handoff.md
  Use before stopping work or moving to the next phase.
```

Before starting a phase, read the matching phase spec and any relevant
project-skill file. Do not load every phase spec or every project skill by
default.

---

## 8. Repository Hygiene And Phase Commit Discipline

Product-release phases must not blur into one giant working tree.

If `git status --short` shows many unrelated changes, do not keep piling on new
work blindly. First classify what is in the tree.

Use these buckets:

```text
A. phase spec / project rules
   CLAUDE.md
   .claude/phase-specs/
   .claude/project-skills/

B. current phase source + tests
   the smallest code/test set that implements the active phase

C. supporting docs
   docs/, README notes, ADRs, demo scripts

D. local or generated noise
   .claude/projects/
   tmp/
   outputs/
   caches
   local settings
```

Rules:

1. Do not use `git add .` in this project.
2. Stage explicit file lists only.
3. Keep phase-rule/docs commits separate from code commits when practical.
4. Do not start the next phase if the current phase code is not tested and
   handoff-reviewed.
5. If the tree is already messy, stop and report the buckets before adding more
   changes.

Preferred commit slicing:

```text
Commit 1
  phase rules / phase spec / CLAUDE.md updates

Commit 2
  current phase code + tests

Commit 3
  optional supporting docs or demo material
```

Before any commit, run:

```bash
git status --short
git diff --check
python -m compileall -q src tests
python -m pytest -q
```

Use the equivalent `py -m ...` commands on Windows if needed.

If full pytest is too expensive for the current step, run targeted tests first
and say clearly what full-suite coverage is still pending.

---

## 9. Reviewer Workflow

For each phase:

1. Implementation session makes the smallest phase-bounded change.
2. Implementation session runs targeted tests.
3. Implementation session runs full tests when practical.
4. Separate reviewer session reviews the diff in read-only mode.
5. Reviewer names the architecture contract for the phase.
6. Reviewer traces the runtime path from source event to final report/audit.
7. Reviewer asks what current tests would still pass if the design were only
   superficially wired.
8. P0 issues must be fixed before moving on.
9. P1 issues should be fixed unless clearly deferred with reason.
10. P2 issues are recorded as follow-up.
11. User approves before the next phase begins.

Do not let one session both implement and approve its own work.

---

## 10. Testing Standard

For any runtime-control change, tests must include:

- bad case fails safely
- normal case still passes
- boundary case
- false-positive guard
- nearby regression path
- contract/path test when the phase promises a specific runtime path

Use targeted tests first, then full tests.

For control-layer changes, do not only test the final value. Add at least one
test that would fail if the implementation merely guessed the right result at
the end.

Examples:

- Known failure categories are propagated explicitly; `infer_failure_category`
  is used only for unknown fallback paths.
- Observed evidence comes from captured command/test output, not from worker
  claims.
- A read-only reviewer path cannot call write tools even if the final report
  would look valid.

Preferred command order:

```bash
python -m pytest tests/<target_test_file>.py
python -m pytest
```

If pytest is unavailable:

```bash
python -m unittest discover -s tests
```

Report the exact command and result. Do not say tests passed unless the command
actually passed.

---

## 10. Final Definition of Done

AAO has two definitions of done: Core Done and v1 Product/Portfolio Release
Done.

AAO Core is considered done only when:

- Control models exist and are tested.
- ControlPlane exists and is runner-independent.
- Scheduler delegates relevant decisions to ControlPlane without breaking
  current CLI/workflows.
- Known failure categories are propagated explicitly instead of being guessed
  through fallback inference.
- Failure classification includes enough reason/recovery information to decide
  whether to retry, back off, request evidence, replan, ask for human review, or
  fail.
- Transient provider failures and non-retryable control failures are clearly
  separated.
- Tool-loop/no-progress guardrails exist as pure tested control primitives.
- EvidencePack records real runtime evidence.
- LiveRunView can show task progress and human-review state.
- Policy YAML can express basic allowed/protected files, required checks, and
  human-review triggers.
- Integration tests cover normal, guardrail, human-review, evaluator-failure,
  failure-taxonomy, recovery-hint, and tool-loop paths.
- Full test suite passes or any skipped tests are clearly explained.
- Reviewer session has no blocking P0 findings.

Only after this should the project move into product-release phases such as:

- Real-Time Watch
- Task Router
- Runtime Policy Enforcement
- Recovery Playbook
- Claude Code Worker Bridge
- LangGraphRunner
- Golden Scenario Suite
- Demo/README release work

AAO v1 Product/Portfolio Release is considered done only when:

- a real task can be run through the Claude Code worker bridge
- Live Watch shows task progress and control decisions while the task runs
- false completion can be blocked by missing tests/evidence/policy
- failures are classified and mapped to recovery actions
- human review can pause and resume a risky run
- Audit Report includes real observed evidence and clear limitations
- Golden Scenario Suite passes
- README quickstart works from a clean clone
- the demo script can show AAO's value in 3-5 minutes

Do not claim AAO v1 is complete just because the core tests pass. Core tests
prove the control foundation; product-release tests prove it is usable and
showable.
