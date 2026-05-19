# Phase 14 - Memory Layer

## Goal

Add lightweight, inspectable project memory so AAO can reuse approved
constraints, design decisions, failure lessons, review outcomes, and run
summaries across sessions.

After this phase, AAO should remember useful project knowledge without treating
memory as truth. Memory is a hint with provenance, not evidence by itself.

Mental model:

```text
Run finishes / review happens / user approves a decision
  -> AAO proposes a memory item
  -> memory item records source type and provenance
  -> memory is stored in local inspectable files
  -> future planning/control may read it as a hint
  -> live evidence still decides whether the current run is valid
```

This phase is about continuity and learning. It is not about adding a hidden
semantic memory brain.

## Why This Phase Exists

AAO now has planning, policy, recovery, worker packets, evidence, and live
visibility. The next problem is repetition:

```text
same project constraints get rediscovered
same failures get re-debugged
same review decisions get forgotten
same user preferences need to be repeated
```

Memory should reduce repeated work, but it must not contaminate ControlPlane.

Important distinction:

```text
Evidence:
  Something AAO observed in the current run, such as test output, file diff,
  control event, worker result file, or an audit artifact.

Memory:
  Something AAO remembers from a previous run, review, decision, or user
  instruction. It may guide planning, but it does not prove the current run.
```

If this distinction is lost, AAO will start accepting stale memories as proof.
That would weaken the whole control layer.

## Preflight

Before editing, read:

```text
CLAUDE.md
.claude/phase-specs/phase-11-recovery-playbook.md
.claude/phase-specs/phase-12-claude-code-worker-bridge.md
.claude/phase-specs/phase-13-planning-council.md
.claude/project-skills/aao-scope-guard.md
.claude/project-skills/aao-boundary-test-designer.md
.claude/project-skills/aao-reviewer-mode.md
.claude/project-skills/aao-tutor-explanation.md
```

Then inspect:

```text
src/orchestrator/memory_manager.py
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/evidence.py
src/orchestrator/recovery.py
src/orchestrator/planning.py
src/orchestrator/scheduler.py
src/orchestrator/report_writer.py
src/orchestrator/live_view.py
tests/
```

Run first:

```bash
git status --short
```

Name unrelated dirty files in the handoff. Do not use `git add .`.

## Non-Goals

- No vector database.
- No semantic retrieval system.
- No hidden memory that users cannot inspect.
- No raw chain-of-thought storage.
- No storing API keys, secrets, private tokens, or `.env` values.
- No automatic edits to `CLAUDE.md` or project skills.
- No new LLM call in the default memory path.
- No automatic belief that memory is current truth.
- No treating worker-reported claims as observed evidence.
- No large rewrite of scheduler.
- No LangGraph, Langfuse, DeepEval, OPA, Casbin, or external memory service.
- No Hermes memory system integration.

Hermes background review / reflection prompts may be studied as design
references, but this phase must implement AAO's own small local memory
contract.

## Allowed Files

Prefer this write set:

```text
src/orchestrator/memory_manager.py
src/orchestrator/memory.py
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/planning.py
src/orchestrator/scheduler.py
src/orchestrator/report_writer.py
src/orchestrator/live_view.py
tests/test_memory.py
tests/test_planning_council.py
tests/test_control_plane.py
tests/test_runtime_smoke.py
```

Rules:

- Prefer extending or refactoring existing `memory_manager.py`.
- Add `memory.py` only if shared models/helpers make the design cleaner.
- Do not leave two competing memory managers with overlapping responsibility.
- Touch `scheduler.py` only for minimal wiring: load memory hints before complex
  planning and record memory after a run/review when appropriate.
- Do not introduce a new dependency for this phase.

## Storage Contract

Canonical memory lives in local inspectable files:

```text
.aao/memory/project.md
.aao/memory/decisions/*.md
.aao/memory/failures/*.json
.aao/memory/runs/*.json
.aao/memory/reviews/*.json
.aao/memory/index.json
```

If older code writes to `outputs/memory/`, keep it backward compatible only as a
legacy run-capture path. Do not make `outputs/memory/` the new canonical memory
contract unless there is a strong reason and the handoff explains it.

Memory files must be human-readable and safe to commit only when appropriate.
Do not commit generated `.aao/memory/` contents by default unless the user
explicitly wants example fixtures.

## Core Models

### MemorySourceType

Every memory item must declare where it came from:

```text
observed
  AAO directly observed this through local artifacts: test output, file diff,
  control event, worker result file, evidence pack, report, or user-approved
  plan.

reported
  A worker, model, external tool, or human message claimed this.

inferred
  AAO derived this from patterns or repeated events.
```

Never silently upgrade `reported` or `inferred` memory to `observed`.

### MemoryKind

Use a small explicit set:

```text
project_constraint
architecture_decision
failure_lesson
review_decision
run_summary
user_preference
worker_lesson
```

Do not create unlimited free-form memory categories.

### MemoryItem

Expected fields:

```text
id
kind
source_type
title
content
created_at
updated_at
task_id
run_id
source_path
evidence_path
tags
confidence
expires_at optional
```

`source_path` or `evidence_path` should be present when the memory claims to be
based on an artifact. If neither exists, the item should usually be `reported`.

### MemoryContext

The runtime object passed into planning/control should be small:

```text
project_constraints
relevant_decisions
failure_lessons
review_decisions
user_preferences
run_summaries
source_paths
```

Cap the number of loaded items. Do not dump the whole memory folder into a
prompt or plan.

## What To Remember

Good memory candidates:

```text
approved project constraints
  "Never edit tmp/ or generated outputs."

architecture decisions
  "ControlPlane must remain independent from Runner and Worker layers."

failure lessons
  "When worker reports tests passed without observed output, request evidence."

review decisions
  "Reviewer classified this as P1 because scheduler still inferred known
   failure categories."

run summaries
  "Phase 12 worker bridge implemented worker packets and evidence validation."

user preferences
  "Explain complex AAO concepts with concrete runtime paths and plain Chinese."
```

Memory should make future work safer and faster.

## What Not To Remember

Reject or redact:

```text
API keys, tokens, passwords, secrets
raw chain-of-thought
temporary network failures without lasting lesson
one-off local environment glitches
unverified worker claims
negative global claims such as "tool X never works"
private personal information not needed for the project
large raw logs that should be linked as evidence instead
```

If a memory item is useful but contains sensitive text, store the lesson and
redact the sensitive value.

## Required Behavior

### 1. Memory is explicit and inspectable

AAO must be able to create, list, load, and reference local memory files. Missing
memory files must not crash a run.

### 2. Memory has provenance

Every memory item must carry:

```text
kind
source_type
source path or explanation
created timestamp
```

If source type is missing, reject the item.

### 3. Memory is not evidence

ControlPlane may use memory to shape a plan or warning, but it must not treat
memory as proof that the current run passed.

Example:

```text
Memory says: "pytest usually catches this."
Current run still needs observed pytest output to count as tested.
```

### 4. Memory retrieval is bounded

Implement simple deterministic retrieval first:

```text
keyword/tag/task-kind matching
top_k cap
source-type filtering
kind filtering
```

No vector search in this phase.

### 5. Planning Council can receive memory hints

For complex/orchestrated tasks, Phase 13 planning may receive a small
`MemoryContext`.

The plan should be allowed to say:

```text
Memory hints considered:
  - project constraint: protected files
  - failure lesson: do not accept reported tests as observed evidence
```

But the plan must still include fresh success criteria and required evidence.

### 6. ControlPlane can record failure lessons

When a failure is classified and a recovery decision is chosen, AAO may record a
failure lesson if it is durable enough to help later.

Minimum fields:

```text
failure_category
reason
recovery_hint
what_prevents_repeat
source_type
evidence_path or run_id
```

Do not record every transient failure as a permanent lesson.

### 7. Reports disclose memory usage

Audit/report output should include a compact section:

```text
Memory used:
  - project constraints: 2
  - failure lessons: 1
  - source types: observed=2 reported=1 inferred=0
```

Reports should not pretend memory is current evidence.

### 8. User can inspect memory

Add minimal CLI or helper surface if the existing CLI structure supports it.
Prefer simple commands or functions:

```text
memory list
memory show <id>
memory add-decision
memory record-failure
```

If adding CLI commands would create too much churn, implement the underlying
API and document the deferred CLI work in the handoff.

## Reflection Rules

Use this as a small deterministic reflection gate, not an extra LLM agent.

After a run/review, ask:

```text
Is there a durable lesson?
Is it project-specific or generally useful?
Is the source observed/reported/inferred?
Does storing it reduce future risk?
Does it contain secrets or private data?
Could it become stale?
```

Only write memory if the answer is clear.

Do not update project skills automatically. If a repeated lesson suggests a
skill update, record a `review_decision` or `worker_lesson` memory item and list
the proposed skill change in the handoff.

## Integration Points

### Planning Council

Load memory hints before creating a `PlanContract` for complex/orchestrated
tasks.

Use memory to improve plan quality, not to skip plan validation.

### ControlPlane

Use memory as context for warnings and recovery hints. Keep live evidence as
the source of truth for pass/fail decisions.

### Scheduler

Minimal wiring only:

```text
load memory context before complex planning
pass memory context to planning/control where useful
record approved decisions, failure lessons, and run summaries after completion
```

Do not broaden scheduler if a thin helper can do it.

### ReportWriter / LiveView

Expose compact memory usage and source labels.

Do not build a memory dashboard.

## Test Requirements

Required tests:

```text
test_memory_item_requires_source_type
test_memory_item_requires_kind
test_missing_memory_files_do_not_crash
test_project_memory_can_be_loaded
test_decision_memory_can_be_recorded_and_loaded
test_failure_lesson_can_be_recorded_and_retrieved
test_memory_does_not_convert_reported_to_observed
test_memory_is_not_accepted_as_current_evidence
test_secret_like_values_are_rejected_or_redacted
test_retrieval_respects_top_k_and_kind_filter
test_planning_council_receives_bounded_memory_context
test_report_lists_memory_usage_with_source_types
```

Regression tests:

```text
existing planning council tests still pass
existing control plane policy/recovery tests still pass
existing worker bridge evidence tests still pass
existing runtime smoke tests still pass
```

Tests must not call real LLM APIs.

## Suggested Implementation Order

### Step 1 - Normalize memory models

Create or update memory models:

```text
MemorySourceType
MemoryKind
MemoryItem
MemoryContext
MemoryStore
```

Keep them small and serializable.

### Step 2 - Implement local file store

Support:

```text
create item
load item
list items
retrieve relevant items
handle missing folders
reject invalid source type
redact or reject secrets
```

### Step 3 - Migrate or wrap existing MemoryManager

`memory_manager.py` already captures run bundles. Either:

```text
extend it into the new contract
```

or:

```text
keep it as a compatibility wrapper around MemoryStore
```

Do not leave old and new memory systems disconnected.

### Step 4 - Wire memory into planning/control/report

Use a small `MemoryContext`, not raw file contents.

### Step 5 - Add tests and handoff

Run focused tests first, then broader relevant tests.

## Validation Commands

Use the project environment that actually contains the source. If running from
Windows PowerShell, prefer WSL explicitly:

```bash
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m pytest -q tests/test_memory.py"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m pytest -q tests/test_planning_council.py tests/test_control_plane.py tests/test_claude_code_worker_bridge.py"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m compileall src/orchestrator"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && git diff --check"
```

If editing directly inside WSL, equivalent local commands are fine:

```bash
python3 -m pytest -q tests/test_memory.py
python3 -m pytest -q tests/test_planning_council.py tests/test_control_plane.py tests/test_claude_code_worker_bridge.py
python3 -m compileall src/orchestrator
git diff --check
```

## Definition Of Done

- Memory is local, inspectable, and human-readable.
- Every memory item has kind, source type, timestamp, and provenance.
- Missing memory files/folders do not crash the run.
- Memory retrieval is deterministic, bounded, and testable.
- Reported/inferred memory is never upgraded to observed.
- Memory is never accepted as current-run evidence.
- Secrets are rejected or redacted.
- Planning Council can receive a bounded memory context.
- ControlPlane can record durable failure lessons.
- Reports disclose memory usage and source types.
- Existing Phase 11/12/13 tests still pass.
- Handoff lists what memory is canonical, what remains legacy, and what is
  intentionally deferred.

## Reviewer Checklist

Reviewer must check:

```text
Can a user inspect every memory item on disk?
Can memory silently change a pass/fail decision without current evidence?
Are source types enforced everywhere?
Are secrets and raw chain-of-thought excluded?
Does planning receive only bounded memory context?
Does report output distinguish memory from evidence?
Did implementation create two disconnected memory systems?
Did scheduler grow too much?
Are tests deterministic and API-free?
```

Explain any bug in plain language before the technical diagnosis.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 14.

Keep the work centered on one thing: AAO remembers useful project knowledge
without confusing memory with proof. Do not add vector search, hidden state,
external memory services, LangGraph, DeepEval, or a new LLM reflection agent.

After implementation, explain naturally what memory now stores, what it refuses
to store, how source types work, what tests prove, and what the user should
understand before moving to the next phase.
