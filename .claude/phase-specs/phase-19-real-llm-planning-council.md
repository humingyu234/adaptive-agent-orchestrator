# Phase 19 - Real LLM Planning Council

## Goal

Make Planning Council real. For complex tasks, AAO should ask multiple
provider-backed advisors to produce and challenge a plan, merge the result into
a PlanContract, and require user approval before execution.

This phase closes the second major gap in the original blueprint:

```text
before:
  deterministic/local advisors can prove structure

after:
  real LLM advisors discuss the task, challenge risks, and produce an execution
  plan that AAO can turn into worker tasks
```

## Hard Rule

Do not count deterministic advisors as the real Planning Council. They remain
valid for unit tests, offline demos, and fallback, but not for the complete
landing path.

Do not count "the model returned something" as success either. Phase 19 is only
landed when real advisor prompts repeatedly produce valid, worker-ready,
control-friendly PlanContracts under a small golden test set.

## Preflight

Read:

```text
CLAUDE.md
.claude/phase-specs/phase-13-planning-council.md
.claude/phase-specs/phase-18-real-claude-code-worker-bridge.md
src/orchestrator/planning.py
src/orchestrator/llm_providers.py
src/orchestrator/control_plane.py
src/orchestrator/mainline_executor.py
src/orchestrator/__main__.py
tests/test_planning*.py
```

Run:

```bash
git status --short
```

Name unrelated dirty files in the handoff. Do not use `git add .`.

## Non-Goals

- No multi-worker execution in this phase. Phase 20 handles execution fan-out.
- No LangGraph rewrite.
- No direct AutoGen/CrewAI/LangGraph council integration in this phase.
- No new provider SDK unless the existing provider abstraction cannot support
  the minimum needed calls.
- No hard-coded API keys.
- No replacing ControlPlane with an LLM judge.
- No endless debate loop. The council must be bounded and deterministic in
  shape even when advisors are LLM-backed.

Existing role-discussion frameworks are useful references, not the acceptance
target for Phase 19:

```text
Borrow from AutoGen:
  bounded group-chat / critic / human-in-the-loop patterns

Borrow from CrewAI:
  role + goal + task + expected_output prompt structure

Borrow from LangGraph supervisor:
  supervisor decides next step; workers do not self-route freely

Do not integrate these frameworks directly before Phase 21.
AAO must keep the final PlanContract, approval gate, evidence requirements, and
ControlPlane validation as its own contract.
```

Reason: those frameworks can host a discussion, but AAO needs an engineering
acceptance contract. A "good discussion" is not enough. The output must be
safe to hand to workers.

## Advisor Roles

Implement or wire exactly three required advisor roles first:

```text
Planner
  proposes the main plan and step breakdown

Risk Reviewer
  challenges missing evidence, unsafe scope, protected files, unclear tests,
  dependency ordering, and likely failure modes

Execution Planner
  turns the final plan into worker-ready tasks: objective, allowed files,
  required checks, expected evidence, dependencies, and risk level
```

Optional later roles are allowed only after the three required roles work:

```text
Cost Reviewer
Security Reviewer
Domain Reviewer
```

Do not add optional roles during Phase 19 unless tests already pass and the
three core roles remain simple.

## Prompt Quality Gate

Prompt quality is part of the implementation, not a nice-to-have.

Create a small prompt-evaluation harness for the three advisor prompts before
calling Phase 19 complete. The harness may be local pytest first; optional
LangSmith integration is allowed only if it does not replace local tests.

Required files or equivalent structure:

```text
src/orchestrator/planning_prompts.py
  centralized Planner / Risk Reviewer / Execution Planner prompt templates

tests/golden/planning_cases.yaml
  at least 10 planning cases

tests/test_planning_prompt_quality.py
  local prompt-output validators and fake-provider cases
```

Golden cases must cover:

```text
simple one-file code change
multi-file code change
research task
code review task
protected file request
missing test/evidence risk
parallel-safe two-step task
parallel-unsafe overlapping write task
task that should require human review
task that should be rejected or revised before execution
```

Each golden case should define expected shape, not exact prose:

```text
expected_risk_level
expected_min_steps
expected_required_checks
expected_evidence
expected_blocking_concerns
expected_worker_task_count
expected_human_review_gate
```

Quality checks must verify:

```text
JSON / schema parse success
required fields are present
worker_tasks are actually executable by Phase 20
allowed_files / denied_files are specific enough
required_checks are non-empty for code-changing tasks
expected_evidence is non-empty and observable
blocking concerns are specific, not generic filler
critic findings are preserved in the final PlanContract
protected-file or high-risk tasks require review
```

Use live provider smoke tests aggressively but bounded:

```text
CI / normal tests:
  fake provider, deterministic fixtures, no live key required

local landing smoke:
  at least 3 real LLM planning tasks
  all three advisor roles must run
  outputs must pass the same prompt-quality validators

release confidence run:
  10 golden cases x configurable repeat count
  default repeat count can be small for cost, but the command must exist
```

Suggested command shape:

```bash
python -m orchestrator eval-prompts planning \
  --mode llm \
  --cases tests/golden/planning_cases.yaml \
  --repeat 1
```

If the command name differs, document the actual command in the handoff.

LangSmith / Promptfoo / Braintrust:

```text
Allowed:
  optional adapter for dataset storage, experiment comparison, and prompt version
  tracking

Required:
  local pytest validators must still work without SaaS accounts or network

Do not:
  block Phase 19 on a third-party eval platform
  call a prompt "good" because one manual smoke test looked fine
```

## Provider Configuration

Planning Council must support real LLM calls through existing provider
configuration.

Suggested configuration:

```text
AAO_PLANNING_MODE = deterministic | llm
AAO_PLANNER_PROVIDER
AAO_RISK_REVIEWER_PROVIDER
AAO_EXECUTION_PLANNER_PROVIDER
AAO_PLANNING_TIMEOUT_SECONDS
```

Rules:

```text
deterministic
  used for tests, offline demo, and explicit fallback

llm
  must call real provider-backed advisors

missing provider / missing key / timeout
  produces structured planning failure, not silent deterministic fallback
```

If fallback is supported, it must be explicit in the report:

```text
planning_mode_requested=llm
planning_mode_used=deterministic_fallback
fallback_reason=<reason>
```

## Council Flow

The council must be bounded:

```text
1. Planner creates proposed plan.
2. Risk Reviewer critiques the proposed plan.
3. Execution Planner produces worker-ready plan steps.
4. AAO validates the PlanContract deterministically.
5. User approval is required before execution.
```

Do not let advisors directly execute tools or edit files. Advisors produce
planning artifacts only.

## PlanContract Requirements

The final PlanContract must include enough structure for Phase 20:

```text
objective
risk_level
run_mode
steps[]
  step_id
  title
  objective
  worker_kind
  allowed_files
  denied_files
  required_checks
  expected_evidence
  dependencies
  can_run_parallel
  requires_human_review
non_goals
approval_summary
advisor_outputs
critic_findings
```

If the current PlanContract already has these fields, reuse it. Do not duplicate
models.

## User Approval

Before execution, AAO must show the user:

```text
final plan summary
worker tasks to be created
risk notes
protected files or high-risk operations
required checks
what will run in parallel vs sequentially
```

Supported approval paths:

```text
approve
  continue to execution

edit / revise
  rerun or patch the plan, then show again

cancel
  stop without execution
```

In non-interactive tests, approval may be simulated with an explicit flag such
as `--approve`. Do not execute complex plans without approval.

## Test Plan

Use fake provider fixtures for unit tests. Do not require live model keys in
CI.

Required tests:

```text
test_llm_planning_mode_calls_three_advisors
test_deterministic_mode_does_not_call_provider
test_missing_provider_fails_clearly_without_silent_fallback
test_planner_output_is_validated_into_plan_contract
test_risk_reviewer_findings_are_preserved
test_execution_planner_generates_worker_ready_steps
test_plan_requires_user_approval_before_execution
test_cancel_stops_before_worker_packets_are_created
test_approve_allows_execution_to_continue
test_invalid_llm_plan_is_rejected_or_repaired_before_execution
test_planning_prompts_are_centralized
test_golden_planning_cases_have_expected_shape
test_prompt_quality_rejects_missing_worker_tasks
test_prompt_quality_rejects_generic_blocking_concerns
test_prompt_quality_rejects_code_plan_without_required_checks
test_prompt_quality_rejects_code_plan_without_expected_evidence
```

False-positive guards:

```text
- A local deterministic advisor passing tests does not count as LLM mode.
- An LLM response without worker-ready steps cannot pass.
- A plan with no required evidence cannot pass for code-changing tasks.
- A plan that touches protected files must require review or explicit approval.
- One lucky live prompt response does not prove prompt quality.
- A verbose advisor response with no executable worker task does not count.
```

## Manual Smoke Test

Run one real LLM planning-only task:

```bash
python -m orchestrator ask "plan a small bounded code change" \
  --planning-mode llm \
  --dry-run
```

The smoke test must show:

```text
which providers/advisors ran
advisor outputs
critic findings
final PlanContract
prompt quality validation summary
approval prompt or approval summary
no worker execution in dry-run
```

If live provider keys are unavailable, mark the phase as code-complete but
real-LLM-smoke-blocked. Do not call it fully landed.

## Definition Of Done

Phase 19 is done only when:

```text
- Planning Council has provider-backed LLM advisor mode.
- Planner, Risk Reviewer, and Execution Planner roles exist.
- Deterministic advisors remain available only for tests/fallback.
- Missing provider/key/timeout does not silently become deterministic success.
- Final PlanContract is worker-ready.
- User approval gates execution.
- Advisor prompts are centralized and versionable.
- Prompt Quality Gate exists with at least 10 golden planning cases.
- Local prompt validators reject malformed, vague, or non-executable plans.
- Tests cover real-mode plumbing with fake providers.
- At least 3 real LLM planning smoke tasks are run or explicitly blocked.
```

## Required Final Explanation To User

Explain it like this:

```text
Before Phase 19, AAO could follow a planning structure, but the "advisors" were
mostly local rules.

After Phase 19, AAO can ask real model advisors to propose, criticize, and turn
a task into worker-ready steps. AAO still owns validation and approval; the
models do not get to execute directly.

The important part is not that three models "chat". The important part is that
their discussion becomes a usable construction contract: concrete steps,
allowed files, required checks, expected evidence, risks, and human-review gates.
```

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 19. Do not execute worker
tasks in this phase. Your job is to make the Planning Council real, bounded,
provider-backed, testable, and approval-gated.
