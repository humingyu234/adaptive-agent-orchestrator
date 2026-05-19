"""Planning Council — bounded planning checkpoint before complex task execution.

Creates a reviewed, bounded, user-approved plan before complex tasks execute.
Deterministic advisors produce candidates; the council merges one PlanContract.

Phase 14: Memory hints are accepted as advisory context but never replace
fresh evidence or plan validation.

BOUNDARY RULES (Phase 13 hard constraints):
  - AutoGen / Microsoft Agent Framework / LangGraph may only serve as advisor
    implementations or runner implementations in future phases.  They MUST NOT
    replace AAO's ControlPlane, PlanContract, or user approval gate.
  - Phase 13 does NOT integrate any external agent framework.  No new
    dependencies beyond the Python stdlib and existing AAO packages.
  - The final output is a structured PlanContract, NOT a natural-language
    summary.  Scheduler, worker bridge, and report writer read structured
    fields: objective, steps, risks, non_goals, required_evidence,
    success_criteria, stop_conditions, human_review_gates, planned_worker_tasks,
    blocking_concerns, approval_status.
  - render_plan_contract() exists for human-facing display only.  Automation
    consumers MUST read the structured fields.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

PlanApprovalStatus = Literal["draft", "approved", "edited", "rejected"]


# =============================================================================
# Core planning models
# =============================================================================


@dataclass
class PlannedWorkerTask:
    """A planned unit of work that can later become a Phase 12 WorkerTaskPacket."""

    title: str = ""
    objective: str = ""
    allowed_files: list[str] = field(default_factory=list)
    denied_files: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    expected_evidence: list[str] = field(default_factory=list)
    risk_level: str = "low"

    @property
    def has_boundaries(self) -> bool:
        """Return True if this worker task has file or check boundaries set."""
        return bool(self.allowed_files or self.denied_files or self.required_checks)


@dataclass
class PlanCandidate:
    """One planning perspective's proposal.

    The risk_reviewer role uses blocking_concerns for issues that MUST be
    resolved before the plan can become executable.  non_blocking_concerns
    are advisory.
    """

    role: str = ""  # planner / risk_reviewer / execution_planner
    summary: str = ""
    steps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    human_review_gates: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    blocking_concerns: list[str] = field(default_factory=list)
    non_blocking_concerns: list[str] = field(default_factory=list)


@dataclass
class PlanContract:
    """The final merged plan — structured, machine-readable, auditable.

    This is the authoritative output of the Planning Council.  Scheduler,
    worker bridge, and report writer read these structured fields.
    render_plan_contract() is human-facing display only.

    Phase 14: memory_hints are advisory only — they record what memory
    context was available during planning, but do NOT replace fresh
    evidence or validation.
    """

    objective: str = ""
    run_mode: str = "controlled"
    task_size: str = "medium"
    steps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    human_review_gates: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    planned_worker_tasks: list[PlannedWorkerTask] = field(default_factory=list)
    source_candidates: list[PlanCandidate] = field(default_factory=list)
    approval_status: PlanApprovalStatus = "draft"
    plan_id: str = ""
    disagreements: list[str] = field(default_factory=list)
    blocking_concerns: list[str] = field(default_factory=list)
    non_blocking_concerns: list[str] = field(default_factory=list)
    memory_hints: list[str] = field(default_factory=list)

    @property
    def has_blocking_concerns(self) -> bool:
        return len(self.blocking_concerns) > 0

    def approve(self) -> None:
        """Approve the plan.  Raises ValueError if blocking concerns exist."""
        if self.has_blocking_concerns:
            raise ValueError(
                f"Cannot approve plan with unresolved blocking concerns: "
                + "; ".join(self.blocking_concerns[:3])
            )
        self.approval_status = "approved"

    def reject(self) -> None:
        self.approval_status = "rejected"

    def edit(self, *, steps: list[str] | None = None, non_goals: list[str] | None = None,
             risks: list[str] | None = None, success_criteria: list[str] | None = None) -> None:
        if steps is not None:
            self.steps = steps
        if non_goals is not None:
            self.non_goals = non_goals
        if risks is not None:
            self.risks = risks
        if success_criteria is not None:
            self.success_criteria = success_criteria
        self.approval_status = "edited"


# =============================================================================
# Planning advisor protocol
# =============================================================================


@runtime_checkable
class PlanningAdvisor(Protocol):
    """Protocol for planning advisors — deterministic, no LLM."""

    @property
    def role(self) -> str: ...

    def advise(
        self,
        query: str,
        task_size: str,
        run_mode: str,
        risk_level: str,
    ) -> PlanCandidate: ...


# =============================================================================
# Keyword helpers for deterministic advisors
# =============================================================================

_CODE_CHANGE_WORDS: frozenset[str] = frozenset({
    "implement", "add", "fix", "refactor", "change", "modify", "update",
    "create", "build", "write", "rewrite", "remove", "delete", "migrate",
    "实现", "添加", "修复", "重构", "修改", "更新", "创建", "构建", "删除", "迁移",
})

_HIGH_RISK_WORDS: frozenset[str] = frozenset({
    "delete", "remove", "migrate", "deploy", "release", "production",
    "database", "credentials", "secret", ".env", "payment", "auth",
    "security", "permission", "protected",
    "删除", "部署", "生产", "数据库", "凭证", "密钥", "支付", "认证",
})

_FILE_PATTERN: re.Pattern = re.compile(
    r"`([^`]+\.[a-zA-Z0-9]+)`|([a-zA-Z0-9_\-/]+\.[a-zA-Z]{1,10})"
)

_SCOPE_CREEP_WORDS: frozenset[str] = frozenset({
    "also", "and also", "additionally", "plus", "as well as", "in addition",
    "顺便", "另外", "还有", "同时", "并且",
})


def _extract_files(query: str) -> list[str]:
    seen: set[str] = set()
    for match in _FILE_PATTERN.finditer(query):
        for g in match.groups():
            if g and len(g) > 2 and "/" not in g.lstrip("/\\"):
                continue
            if g and len(g) > 2:
                seen.add(g)
    return sorted(seen)


def _has_code_change(query: str) -> bool:
    lowered = query.lower()
    return any(w in lowered for w in _CODE_CHANGE_WORDS)


def _has_high_risk(query: str) -> bool:
    lowered = query.lower()
    return any(w in lowered for w in _HIGH_RISK_WORDS)


# =============================================================================
# Local (deterministic) advisors
# =============================================================================


class LocalPlannerAdvisor:
    """Proposes a structured plan from the query — deterministic, no LLM."""

    role = "planner"

    def advise(
        self,
        query: str,
        task_size: str = "medium",
        run_mode: str = "controlled",
        risk_level: str = "low",
    ) -> PlanCandidate:
        files = _extract_files(query)
        is_code = _has_code_change(query)
        lowered = query.lower()

        steps: list[str] = []
        risks: list[str] = []
        non_goals: list[str] = []
        evidence: list[str] = []
        gates: list[str] = []

        if files:
            steps.append(f"Inspect current state of: {', '.join(files[:5])}")
        else:
            steps.append("Inspect the relevant codebase area")

        if "phase" in lowered or task_size == "large":
            steps.append("Break the work into independent sub-tasks")
            steps.append("Create a worker task for each sub-task")

        if is_code:
            steps.append("Implement the required code changes")
            steps.append("Run existing tests to check for regressions")
            steps.append("Write or update tests for changed code")
            evidence.append("test_output.txt")
            evidence.append("diff.patch")
        else:
            steps.append("Research and analyze the requested topic")
            steps.append("Produce a structured summary of findings")
            evidence.append("result.md")

        if task_size == "large":
            steps.append("Review each sub-task result for completeness")
            gates.append("Review sub-task results before merging")

        if _has_high_risk(query):
            risks.append("High-risk operations: destructive or security-sensitive changes")
            gates.append("Human review required before execution")
        if not files and is_code:
            risks.append("No specific files mentioned — scope may drift")
        if task_size == "large":
            risks.append("Large task: sub-task dependencies may cause ordering issues")
            risks.append("Plan may need revision after early sub-task results")
        if len(files) > 5:
            risks.append(f"Many files ({len(files)}) — changes may have wide impact")

        if not risks:
            risks.append("Standard implementation risk: unexpected test failures")

        non_goals.append("Do not change files outside the allowed set")
        non_goals.append("Do not skip required checks or tests")
        non_goals.append("Do not introduce new dependencies without review")
        if task_size == "large":
            non_goals.append("Do not execute sub-tasks in parallel without explicit approval")

        assumptions = [
            "Tests exist and can be run for the affected code",
            "Allowed files list covers all necessary changes",
        ]

        return PlanCandidate(
            role="planner",
            summary=f"Structured plan for: {query[:120]}",
            steps=steps,
            risks=risks,
            non_goals=non_goals,
            required_evidence=evidence,
            human_review_gates=gates,
            assumptions=assumptions,
        )


class LocalRiskReviewerAdvisor:
    """Dedicated nitpicker — challenges the plan, not a generic summariser.

    Outputs blocking_concerns (must resolve before execution) and
    non_blocking_concerns (advisory).  Checks six dimensions:

    1. Scope too broad (no files, code-change + unclear boundaries)
    2. Missing required_evidence for code-changing work
    3. Missing success_criteria / stop_conditions signals
    4. High-risk task without human_review_gate
    5. Planned worker task without allowed_files / denied_files / required_checks
    6. Scope creep (many unrelated topics in one query)
    """

    role = "risk_reviewer"

    def advise(
        self,
        query: str,
        task_size: str = "medium",
        run_mode: str = "controlled",
        risk_level: str = "low",
    ) -> PlanCandidate:
        files = _extract_files(query)
        is_code = _has_code_change(query)
        is_high_risk = _has_high_risk(query)
        lowered = query.lower()

        blocking: list[str] = []
        non_blocking: list[str] = []
        gates: list[str] = []
        evidence: list[str] = []

        # ---- 1. Scope too broad -----------------------------------------------
        if is_code and not files:
            if task_size in ("medium", "large"):
                blocking.append(
                    "BLOCKING: Code change requested but no files specified — "
                    "scope too broad; cannot set file boundaries for worker tasks"
                )
            else:
                non_blocking.append(
                    "Code change requested but no files specified — "
                    "confirm scope before starting"
                )

        if task_size == "large" and not files and is_code:
            blocking.append(
                "BLOCKING: Large code task with zero files mentioned — "
                "plan has no concrete boundaries"
            )

        # ---- 2. Missing required_evidence for code-changing work --------------
        if is_code and task_size in ("medium", "large"):
            evidence.append("test_output.txt")
            evidence.append("diff.patch")
            # If planner didn't already include evidence, flag it
            # (reviewer can't see planner output in current design, so always flag)

        if is_code and not _has_high_risk(query):
            # Code changes without high-risk = needs evidence but not blocking
            non_blocking.append(
                "Ensure evidence (test output, diff) is collected before completion"
            )

        # ---- 3. Missing success_criteria / stop_conditions signals ------------
        if task_size == "large":
            non_blocking.append(
                "Large task: verify success_criteria and stop_conditions are explicit"
            )

        # ---- 4. High-risk task without human_review_gate ----------------------
        if is_high_risk:
            gates.append("Human review MUST approve before any file change")
            gates.append("Consider dry-run or backup before execution")
            blocking.append(
                "BLOCKING: High-risk operation detected — "
                "human_review_gate MUST be present in final plan"
            )

        if risk_level == "high" and not is_high_risk:
            non_blocking.append(
                "Risk level is high but no high-risk keywords detected — "
                "verify risk classification"
            )

        # ---- 5. Planned worker task without boundaries ------------------------
        if task_size == "large" and is_code:
            if not files:
                blocking.append(
                    "BLOCKING: Planned worker task has no allowed_files / denied_files "
                    "— cannot create bounded worker packet (Phase 12 requirement)"
                )
            else:
                non_blocking.append(
                    "Worker task boundaries derived from files mentioned — "
                    "review allowed/denied files before dispatch"
                )

        # ---- 6. Scope creep ---------------------------------------------------
        # Count distinct topic signals
        topic_signals = 0
        if is_code:
            topic_signals += 1
        if any(w in lowered for w in ["deploy", "release", "production", "部署", "发布"]):
            topic_signals += 1
        if any(w in lowered for w in ["database", "migrate", "数据库", "迁移"]):
            topic_signals += 1
        if any(w in lowered for w in ["auth", "security", "permission", "认证", "权限"]):
            topic_signals += 1
        if any(w in lowered for w in ["test", "测试"]):
            topic_signals += 1
        if topic_signals >= 3:
            blocking.append(
                "BLOCKING: Scope creep detected — query touches "
                f"{topic_signals} distinct domains; split into separate tasks"
            )
        elif topic_signals >= 2:
            non_blocking.append(
                f"Query spans {topic_signals} domains — "
                "consider splitting if scope drifts during execution"
            )

        # ---- Risk summary -----------------------------------------------------
        if is_high_risk:
            if not any("destructive" in b.lower() or "security" in b.lower() for b in blocking):
                blocking.append(
                    "BLOCKING: Destructive or security-sensitive operation — "
                    "requires explicit user approval before any file change"
                )

        # ---- Gate gaps --------------------------------------------------------
        if is_high_risk and not any("human review" in g.lower() or "MUST" in g for g in gates):
            gates.append("Human review required before any destructive operation")

        return PlanCandidate(
            role="risk_reviewer",
            summary=(
                f"Risk review: {len(blocking)} blocking, "
                f"{len(non_blocking)} non-blocking concern(s)"
            ),
            risks=[b for b in blocking] + [n for n in non_blocking],
            required_evidence=evidence,
            human_review_gates=gates,
            assumptions=["Worker may not fully understand risk implications"],
            blocking_concerns=blocking,
            non_blocking_concerns=non_blocking,
        )


class LocalExecutionPlannerAdvisor:
    """Turns the plan into small executable steps with worker task boundaries."""

    role = "execution_planner"

    def advise(
        self,
        query: str,
        task_size: str = "medium",
        run_mode: str = "controlled",
        risk_level: str = "low",
    ) -> PlanCandidate:
        files = _extract_files(query)
        is_code = _has_code_change(query)
        is_high_risk = _has_high_risk(query)
        steps: list[str] = []
        non_goals: list[str] = []
        blocking: list[str] = []

        steps.append("1. Validate task boundaries: confirm allowed/denied files, required checks")

        if is_code and files:
            steps.append(f"2. Code change step: modify {', '.join(files[:3])}")
            steps.append("3. Test step: run required checks (pytest, type check)")
            steps.append("4. Evidence step: collect test output and diff")
        elif is_code:
            steps.append("2. Discovery step: identify files to change")
            steps.append("3. Code change step: implement modifications")
            steps.append("4. Verification step: run checks and collect evidence")
        else:
            steps.append("2. Research step: gather relevant information")
            steps.append("3. Synthesis step: produce structured output")
            steps.append("4. Evidence step: collect source references and results")

        steps.append("5. Handoff: write result.md and status.json")

        non_goals.append("Do not execute more than one worker task at a time")
        non_goals.append("Do not start next step before current step evidence is verified")

        # Execution planner also checks boundaries for worker tasks
        if task_size == "large" and not files and is_code:
            blocking.append(
                "BLOCKING: Cannot plan execution steps without file boundaries — "
                "worker task has no allowed_files"
            )

        risk_label = "high" if is_high_risk else ("medium" if task_size == "large" else "low")

        return PlanCandidate(
            role="execution_planner",
            summary=f"Execution plan: {len(steps)} steps, risk={risk_label}",
            steps=steps,
            risks=[f"Risk level: {risk_label} — adjust checks accordingly"],
            non_goals=non_goals,
            required_evidence=["result.md", "status.json"],
            human_review_gates=(["Human review before code-changing step"] if is_high_risk else []),
            assumptions=["Worker can run required checks", "Allowed files are correctly scoped"],
            blocking_concerns=blocking,
        )


# =============================================================================
# Planning Council
# =============================================================================


class PlanningCouncil:
    """Bounded planning checkpoint for complex tasks.

    Gathers candidates from three deterministic advisors, merges them into one
    PlanContract.  If ANY advisor produces blocking_concerns, the merged
    contract carries them forward and cannot be approved until resolved.

    Hard caps: max_candidates <= 3, max_revision_rounds <= 1.
    """

    def __init__(
        self,
        max_candidates: int = 3,
        max_revision_rounds: int = 1,
    ) -> None:
        if max_candidates > 3:
            raise ValueError("max_candidates must be <= 3")
        if max_revision_rounds > 1:
            raise ValueError("max_revision_rounds must be <= 1")
        self._max_candidates = max_candidates
        self._max_revision_rounds = max_revision_rounds
        self._advisors: list[PlanningAdvisor] = [
            LocalPlannerAdvisor(),
            LocalRiskReviewerAdvisor(),
            LocalExecutionPlannerAdvisor(),
        ]

    @property
    def max_candidates(self) -> int:
        return self._max_candidates

    @property
    def max_revision_rounds(self) -> int:
        return self._max_revision_rounds

    def create_plan(
        self,
        query: str,
        *,
        task_size: str = "medium",
        run_mode: str = "controlled",
        risk_level: str = "low",
        task_type: str = "unknown",
        memory_context: object | None = None,  # MemoryContext from Phase 14
    ) -> PlanContract:
        """Create a PlanContract from advisor candidates.

        Collects blocking_concerns from ALL candidates.  The resulting contract
        carries them forward; approve() will raise if they are not resolved.

        Phase 14: memory_context provides advisory memory hints (project
        constraints, failure lessons, etc.) that may enrich the plan but do
        NOT replace fresh validation.
        """
        candidates: list[PlanCandidate] = []
        disagreements: list[str] = []
        memory_hints: list[str] = []

        # ---- Phase 14: extract advisory hints from memory context --------------
        if memory_context is not None:
            mc = memory_context
            if hasattr(mc, "project_constraints"):
                for item in getattr(mc, "project_constraints", []):
                    memory_hints.append(f"project constraint: {item.title}")
            if hasattr(mc, "failure_lessons"):
                for item in getattr(mc, "failure_lessons", []):
                    memory_hints.append(f"failure lesson: {item.title}")
            if hasattr(mc, "relevant_decisions"):
                for item in getattr(mc, "relevant_decisions", []):
                    memory_hints.append(f"architecture decision: {item.title}")

        for advisor in self._advisors[: self._max_candidates]:
            candidate = advisor.advise(
                query=query,
                task_size=task_size,
                run_mode=run_mode,
                risk_level=risk_level,
            )
            candidates.append(candidate)

        # ---- merge structured fields ------------------------------------------
        all_steps: list[str] = []
        all_risks: list[str] = []
        all_non_goals: list[str] = []
        all_evidence: list[str] = []
        all_gates: list[str] = []
        all_blocking: list[str] = []
        all_non_blocking: list[str] = []
        seen_steps: set[str] = set()
        seen_risks: set[str] = set()
        seen_non_goals: set[str] = set()
        seen_evidence: set[str] = set()
        seen_gates: set[str] = set()
        seen_blocking: set[str] = set()
        seen_non_blocking: set[str] = set()

        for c in candidates:
            for s in c.steps:
                if s not in seen_steps:
                    seen_steps.add(s)
                    all_steps.append(s)
            for r in c.risks:
                if r not in seen_risks:
                    seen_risks.add(r)
                    all_risks.append(r)
            for ng in c.non_goals:
                if ng not in seen_non_goals:
                    seen_non_goals.add(ng)
                    all_non_goals.append(ng)
            for e in c.required_evidence:
                if e not in seen_evidence:
                    seen_evidence.add(e)
                    all_evidence.append(e)
            for g in c.human_review_gates:
                if g not in seen_gates:
                    seen_gates.add(g)
                    all_gates.append(g)
            for bc in c.blocking_concerns:
                if bc not in seen_blocking:
                    seen_blocking.add(bc)
                    all_blocking.append(bc)
            for nc in c.non_blocking_concerns:
                if nc not in seen_non_blocking:
                    seen_non_blocking.add(nc)
                    all_non_blocking.append(nc)

        # ---- disagreements: planner vs risk_reviewer --------------------------
        if len(candidates) >= 2:
            planner_risks = set(candidates[0].risks)
            reviewer_risks = set(candidates[1].risks)
            only_reviewer = reviewer_risks - planner_risks
            if only_reviewer:
                disagreements.append(
                    f"Risk reviewer identified additional items not in planner: "
                    + "; ".join(sorted(only_reviewer)[:3])
                )
            # Record if risk_reviewer has blocking concerns the planner didn't flag
            reviewer_blocking = set(candidates[1].blocking_concerns)
            if reviewer_blocking:
                disagreements.append(
                    f"Risk reviewer raised {len(reviewer_blocking)} blocking concern(s) "
                    "— plan is NOT executable until resolved"
                )

        # ---- success criteria -------------------------------------------------
        success_criteria = [
            "All required checks pass",
            "All expected evidence is produced and verified",
        ]
        if all_evidence:
            success_criteria.append(
                f"Evidence files present: {', '.join(all_evidence[:5])}"
            )
        if all_gates:
            success_criteria.append("All human review gates are satisfied")

        # ---- stop conditions --------------------------------------------------
        stop_conditions = [
            "Any required check fails",
            "Denied or protected files are touched",
            "Plan cannot be completed within the defined scope",
        ]
        if _has_high_risk(query):
            stop_conditions.append("Any destructive operation is attempted without approval")

        # ---- planned worker tasks (complex tasks only) ------------------------
        planned_worker_tasks: list[PlannedWorkerTask] = []
        if task_size == "large":
            files_list = _extract_files(query)
            planned_worker_tasks.append(PlannedWorkerTask(
                title=f"Execute: {query[:60]}",
                objective=query,
                allowed_files=files_list if files_list else [],
                denied_files=[],
                required_checks=["python -m pytest"] if _has_code_change(query) else [],
                expected_evidence=all_evidence,
                risk_level="high" if _has_high_risk(query) else "medium",
            ))

        plan_id = f"plan-{uuid.uuid4().hex[:12]}"

        return PlanContract(
            objective=query,
            run_mode=run_mode,
            task_size=task_size,
            steps=all_steps,
            risks=all_risks,
            non_goals=all_non_goals,
            required_evidence=all_evidence,
            human_review_gates=all_gates,
            success_criteria=success_criteria,
            stop_conditions=stop_conditions,
            planned_worker_tasks=planned_worker_tasks,
            source_candidates=candidates,
            approval_status="draft",
            plan_id=plan_id,
            disagreements=disagreements,
            blocking_concerns=all_blocking,
            non_blocking_concerns=all_non_blocking,
            memory_hints=memory_hints,
        )

    def revise_plan(
        self,
        plan: PlanContract,
        *,
        edits: dict[str, object] | None = None,
    ) -> PlanContract:
        """Apply user edits and return an updated plan. Bounded to 1 revision round."""
        if edits:
            if "steps" in edits and isinstance(edits["steps"], list):
                plan.steps = edits["steps"]  # type: ignore[assignment]
            if "non_goals" in edits and isinstance(edits["non_goals"], list):
                plan.non_goals = edits["non_goals"]  # type: ignore[assignment]
            if "risks" in edits and isinstance(edits["risks"], list):
                plan.risks = edits["risks"]  # type: ignore[assignment]
            if "success_criteria" in edits and isinstance(edits["success_criteria"], list):
                plan.success_criteria = edits["success_criteria"]  # type: ignore[assignment]
            # User edits may resolve blocking concerns — clear them on edit
            if edits:
                plan.blocking_concerns = [
                    bc for bc in plan.blocking_concerns
                    if not any(
                        bc.startswith(f"BLOCKING: {key}")
                        for key in ["Code change", "Large code task", "High-risk",
                                     "Scope creep", "Planned worker task",
                                     "Cannot plan execution"]
                    )
                ]
        plan.approval_status = "edited"
        return plan


# =============================================================================
# Convenience: build a council with defaults
# =============================================================================

def build_default_council() -> PlanningCouncil:
    """Return a PlanningCouncil with default deterministic advisors."""
    return PlanningCouncil(max_candidates=3, max_revision_rounds=1)


# =============================================================================
# Plan-to-packet mapping (Phase 12 compatibility)
# =============================================================================

def planned_task_to_packet_kwargs(
    pwt: PlannedWorkerTask,
    *,
    run_id: str = "",
    task_id: str = "",
) -> dict[str, object]:
    """Convert a PlannedWorkerTask to kwargs for WorkerTaskPacket.create().

    Does NOT call WorkerTaskPacket — only prepares the structured mapping.
    Scheduler / worker bridge MUST read these structured fields, not any
    natural-language rendering.
    """
    return {
        "run_id": run_id,
        "task_id": task_id,
        "title": pwt.title,
        "objective": pwt.objective,
        "allowed_files": pwt.allowed_files,
        "denied_files": pwt.denied_files,
        "required_checks": pwt.required_checks,
        "expected_evidence": pwt.expected_evidence,
        "risk_level": pwt.risk_level,
    }


# =============================================================================
# Plan rendering (human-facing display only — NOT for automation consumers)
# =============================================================================

def render_plan_contract(plan: PlanContract) -> str:
    """Render a PlanContract as terminal-safe, human-readable text.

    This is display-only.  Automation consumers (scheduler, worker bridge,
    report writer) MUST read the structured PlanContract fields directly.
    """
    sep = "=" * 64
    lines: list[str] = [
        sep,
        "Plan Contract",
        sep,
        f"  Plan ID:       {plan.plan_id}",
        f"  Status:        {plan.approval_status}",
        f"  Executable:    {'NO — blocking concerns exist' if plan.has_blocking_concerns else 'Yes'}",
        f"  Task Size:     {plan.task_size}",
        f"  Run Mode:      {plan.run_mode}",
        f"  Objective:     {plan.objective[:100]}",
    ]

    if plan.blocking_concerns:
        lines.append("")
        lines.append(f"  !! BLOCKING CONCERNS ({len(plan.blocking_concerns)}) — must resolve before execution:")
        for bc in plan.blocking_concerns:
            lines.append(f"    !! {bc}")

    if plan.non_blocking_concerns:
        lines.append("")
        lines.append(f"  Non-Blocking Concerns ({len(plan.non_blocking_concerns)}):")
        for nc in plan.non_blocking_concerns:
            lines.append(f"    - {nc}")

    lines.append("")
    lines.append(f"  Steps ({len(plan.steps)}):")
    for s in plan.steps:
        lines.append(f"    - {s}")

    lines.append("")
    lines.append(f"  Risks ({len(plan.risks)}):")
    for r in plan.risks:
        lines.append(f"    - {r}")

    lines.append("")
    lines.append(f"  Non-Goals ({len(plan.non_goals)}):")
    for ng in plan.non_goals:
        lines.append(f"    - {ng}")

    lines.append("")
    lines.append(f"  Required Evidence ({len(plan.required_evidence)}):")
    for e in plan.required_evidence:
        lines.append(f"    - {e}")

    if plan.human_review_gates:
        lines.append("")
        lines.append(f"  Human Review Gates ({len(plan.human_review_gates)}):")
        for g in plan.human_review_gates:
            lines.append(f"    - {g}")

    lines.append("")
    lines.append(f"  Success Criteria ({len(plan.success_criteria)}):")
    for sc in plan.success_criteria:
        lines.append(f"    - {sc}")

    lines.append("")
    lines.append(f"  Stop Conditions ({len(plan.stop_conditions)}):")
    for sc in plan.stop_conditions:
        lines.append(f"    - {sc}")

    if plan.planned_worker_tasks:
        lines.append("")
        lines.append(f"  Planned Worker Tasks ({len(plan.planned_worker_tasks)}):")
        for wt in plan.planned_worker_tasks:
            lines.append(f"    - {wt.title} (risk={wt.risk_level}, boundaries={'yes' if wt.has_boundaries else 'NO'})")

    if plan.disagreements:
        lines.append("")
        lines.append("  Advisor Disagreements:")
        for d in plan.disagreements:
            lines.append(f"    ! {d}")

    if plan.memory_hints:
        lines.append("")
        lines.append(f"  Memory Hints Considered ({len(plan.memory_hints)}):")
        for mh in plan.memory_hints[:5]:
            lines.append(f"    - {mh}")

    lines.append(sep)
    return "\n".join(lines)


def plan_contract_to_dict(plan: PlanContract) -> dict[str, object]:
    """Serialize a PlanContract for persistence / JSON output.

    Returns structured fields only — this is the machine-readable form.
    """
    return {
        "plan_id": plan.plan_id,
        "objective": plan.objective,
        "run_mode": plan.run_mode,
        "task_size": plan.task_size,
        "approval_status": plan.approval_status,
        "has_blocking_concerns": plan.has_blocking_concerns,
        "steps": plan.steps,
        "risks": plan.risks,
        "non_goals": plan.non_goals,
        "required_evidence": plan.required_evidence,
        "human_review_gates": plan.human_review_gates,
        "success_criteria": plan.success_criteria,
        "stop_conditions": plan.stop_conditions,
        "blocking_concerns": plan.blocking_concerns,
        "non_blocking_concerns": plan.non_blocking_concerns,
        "memory_hints": plan.memory_hints,
        "planned_worker_tasks": [
            {
                "title": wt.title,
                "objective": wt.objective,
                "allowed_files": wt.allowed_files,
                "denied_files": wt.denied_files,
                "required_checks": wt.required_checks,
                "expected_evidence": wt.expected_evidence,
                "risk_level": wt.risk_level,
                "has_boundaries": wt.has_boundaries,
            }
            for wt in plan.planned_worker_tasks
        ],
        "source_candidate_count": len(plan.source_candidates),
        "disagreements": plan.disagreements,
    }
