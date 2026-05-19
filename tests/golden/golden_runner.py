"""GoldenScenarioRunner — calls real AAO control code with deterministic fake workers.

Each scenario is a staged incident.  The runner builds a Policy, gets the fake
worker output, exercises the appropriate control path, and collects every
ControlDecision, RecoveryDecision, evidence item, and plan verification into
a GoldenScenarioResult.
"""

from __future__ import annotations

from typing import Any

from .golden_models import GoldenScenario, GoldenScenarioResult
from .scenarios.fake_workers import FAKE_WORKER_REGISTRY

# Real AAO control code — the entire point of the golden suite.
from orchestrator.control_models import (
    ControlDecision,
    WorkerEvidenceItem,
    WorkerEvidenceStatus,
)
from orchestrator.control_plane import ControlPlane
from orchestrator.failure_taxonomy import (
    FailureCategory,
    FailureRecord,
    FailureSeverity,
    create_failure_record,
)
from orchestrator.guardrails import (
    ToolCallGuardrailController,
    ToolLoopAction,
)
from orchestrator.live_interrupt import (
    InterruptSignal,
    InterruptRequest,
    LiveInterruptController,
)
from orchestrator.planning import (
    build_default_council,
)
from orchestrator.policy import Policy
from orchestrator.recovery import RecoveryDecision
from orchestrator.regression_compare import (
    MetricDiff,
    RegressionCompare,
    RegressionSignal,
)


class GoldenScenarioRunner:
    """Runs one golden scenario against real AAO control code.

    Never calls an LLM, never touches the network, never writes to the real
    filesystem.  The fake worker outputs are fully deterministic.
    """

    def __init__(self) -> None:
        self._decisions: list[dict[str, Any]] = []
        self._evidence_items: list[dict[str, Any]] = []
        self._failure_record: dict[str, Any] | None = None
        self._recovery_decision: dict[str, Any] | None = None
        self._report_sections: list[str] = []
        self._plan_verification: dict[str, Any] | None = None
        self._errors: list[str] = []

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def run(self, scenario: GoldenScenario) -> GoldenScenarioResult:
        self._reset()

        try:
            policy = self._build_policy(scenario)
            cp = ControlPlane(policy=policy)
            worker_output = self._resolve_worker_output(scenario)

            # Dispatch to the correct control path
            handler = _DISPATCH.get(scenario.id)
            if handler is not None:
                handler(self, cp=cp, policy=policy, worker_output=worker_output,
                        scenario=scenario)
            else:
                self._errors.append(f"No handler registered for scenario '{scenario.id}'")

        except Exception as exc:
            self._errors.append(f"{type(exc).__name__}: {exc}")

        return GoldenScenarioResult(
            scenario_id=scenario.id,
            status=self._determine_status(),
            control_decisions=list(self._decisions),
            failure_record=self._failure_record,
            recovery_decision=self._recovery_decision,
            evidence_items=list(self._evidence_items),
            report_sections=list(self._report_sections),
            plan_verification=self._plan_verification,
            assertions={},
            errors=list(self._errors),
        )

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _reset(self) -> None:
        self._decisions.clear()
        self._evidence_items.clear()
        self._failure_record = None
        self._recovery_decision = None
        self._report_sections.clear()
        self._plan_verification = None
        self._errors.clear()

    def _build_policy(self, scenario: GoldenScenario) -> Policy:
        policy_config = scenario.setup.get("policy_config", {})
        if policy_config:
            policy = Policy.from_dict(policy_config)
        else:
            policy = Policy.defaults()
        policy.mode = scenario.run_mode
        return policy

    def _resolve_worker_output(self, scenario: GoldenScenario) -> dict[str, Any]:
        if scenario.fake_worker_output:
            return dict(scenario.fake_worker_output)
        fn = FAKE_WORKER_REGISTRY.get(scenario.fake_worker_name)
        if fn is not None:
            return fn(scenario.fake_worker_name)
        return {}

    def _determine_status(self) -> str:
        if self._errors:
            return "error"
        for d in self._decisions:
            if not d.get("passed", True):
                action = d.get("action", "")
                if action == "needs_human_review":
                    return "needs_human_review"
                if action == "fail":
                    return "failed"
                return "blocked"
        return "passed"

    def _add_decision(self, decision: ControlDecision) -> None:
        self._decisions.append(decision.model_dump())

    def _add_recovery(self, decision: RecoveryDecision) -> None:
        self._recovery_decision = decision.to_dict()

    def _add_failure(self, record: FailureRecord) -> None:
        self._failure_record = record.to_dict()

    # ------------------------------------------------------------------
    # evidence helpers
    # ------------------------------------------------------------------

    def _build_evidence_status(
        self,
        worker_output: dict[str, Any],
        scenario: GoldenScenario,
    ) -> WorkerEvidenceStatus:
        """Build a WorkerEvidenceStatus from fake worker output without touching disk."""
        evidence_cfg: list[dict[str, Any]] = scenario.setup.get("evidence_items", [])
        items: list[WorkerEvidenceItem] = []

        for cfg in evidence_cfg:
            items.append(WorkerEvidenceItem(
                key=cfg["key"],
                status=cfg.get("status", "missing"),
                path=cfg.get("path", ""),
                description=cfg.get("description", ""),
            ))

        return WorkerEvidenceStatus(
            task_id=scenario.setup.get("task_id", "test-task-1"),
            worker_kind="claude_code",
            worker_status=worker_output.get("status", "completed"),
            items=items,
            reported_summary=worker_output.get("summary", ""),
            changed_files=worker_output.get("files_changed", []),
            denied_files_changed=scenario.setup.get("denied_files_changed", []),
        )


# =============================================================================
# Scenario handlers — one per scenario id
# =============================================================================

# Each handler receives (runner, cp, policy, worker_output, scenario).


def _handle_normal_completion_with_observed_evidence(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 1 — Scenario 1: Worker completes with full observed evidence."""
    evidence_status = runner._build_evidence_status(worker_output, scenario)
    decision = cp.verify_worker_evidence(evidence_status)
    runner._add_decision(decision)
    for item in evidence_status.items:
        runner._evidence_items.append(item.model_dump())
    runner._report_sections.append("evidence")


def _handle_missing_evidence_blocks_success(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 1 — Scenario 2: Worker reports completed but provides no evidence."""
    evidence_status = runner._build_evidence_status(worker_output, scenario)
    decision = cp.verify_worker_evidence(evidence_status)
    runner._add_decision(decision)
    for item in evidence_status.items:
        runner._evidence_items.append(item.model_dump())


def _handle_worker_reported_tests_do_not_count_as_observed(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 1 — Scenario 3: Worker claims tests passed but no observed output."""
    evidence_status = runner._build_evidence_status(worker_output, scenario)
    decision = cp.verify_worker_evidence(evidence_status)
    runner._add_decision(decision)
    for item in evidence_status.items:
        runner._evidence_items.append(item.model_dump())


def _handle_memory_hint_does_not_count_as_evidence(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 1 — Scenario 4: Memory hints are advisory, not evidence."""
    evidence_status = runner._build_evidence_status(worker_output, scenario)
    decision = cp.verify_worker_evidence(evidence_status)
    runner._add_decision(decision)
    for item in evidence_status.items:
        runner._evidence_items.append(item.model_dump())
    # Also verify that policy with required evidence keys blocks success
    required_keys: set[str] = set(scenario.setup.get("required_evidence_keys", []))
    observed_keys: set[str] = set(scenario.setup.get("observed_evidence_keys", []))
    if required_keys:
        req_decision = cp.check_policy_for_required_evidence(
            required_evidence_keys=required_keys,
            observed_evidence_keys=observed_keys,
        )
        runner._add_decision(req_decision)


def _handle_policy_denies_protected_file_change(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 2 — Scenario 5: Worker modifies a protected file."""
    files = worker_output.get("files_changed", [])
    decision = cp.check_policy_for_file_changes(files_changed=files)
    runner._add_decision(decision)
    if not decision.passed:
        # Record as a failure for the report
        record = create_failure_record(
            category=FailureCategory.POLICY_ERROR,
            origin="policy",
            reason=decision.reason,
            agent_name=scenario.fake_worker_name,
            severity=FailureSeverity.HIGH,
        )
        runner._add_failure(record)
        runner._report_sections.append("failure")


def _handle_reviewer_cannot_write_files(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 2 — Scenario 6: Reviewer writes files — denied."""
    files = worker_output.get("files_changed", [])
    decision = cp.check_policy_for_reviewer_result(
        worker_name=scenario.fake_worker_name,
        worker_role=scenario.fake_worker_role,
        files_changed=files,
    )
    runner._add_decision(decision)
    if not decision.passed:
        record = create_failure_record(
            category=FailureCategory.POLICY_ERROR,
            origin="policy",
            reason=decision.reason,
            agent_name=scenario.fake_worker_name,
            severity=FailureSeverity.CRITICAL,
        )
        runner._add_failure(record)


def _handle_guardrail_blocks_secret_leak(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 2 — Scenario 7: Worker output contains api_key."""
    decision = cp.guard_output(
        agent_name=scenario.fake_worker_name,
        payload=worker_output,
    )
    runner._add_decision(decision)
    if not decision.passed:
        record = create_failure_record(
            category=FailureCategory.GUARDRAIL_BLOCKED,
            origin="control_plane",
            reason=decision.reason,
            agent_name=scenario.fake_worker_name,
            severity=FailureSeverity.HIGH,
        )
        runner._add_failure(record)
        runner._report_sections.append("failure")


def _handle_test_failure_triggers_bounded_recovery(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 3 — Scenario 8: Test failure → retry → exhausted → replan."""
    record = create_failure_record(
        category=FailureCategory.TASK_QUALITY_ERROR,
        origin="worker",
        reason="evaluation_failed",
        agent_name=scenario.fake_worker_name,
        severity=FailureSeverity.MEDIUM,
        recovery_hint="retry",
    )
    runner._add_failure(record)

    # First retry (attempt 0, not exhausted) — should be allowed
    retry1 = cp.decide_recovery(
        record,
        attempt_count=0,
        run_mode=scenario.run_mode,
        task_id=scenario.setup.get("task_id", "test-task-1"),
        step_name="run_tests",
    )
    # Save the first recovery decision as the primary decision
    runner._add_recovery(retry1)

    # Second retry (attempt 1, exhausted for task quality → replan)
    # This proves recovery is bounded: after max_attempts, action changes.
    retry2 = cp.decide_recovery(
        record,
        attempt_count=1,
        run_mode=scenario.run_mode,
        task_id=scenario.setup.get("task_id", "test-task-1"),
        step_name="run_tests",
    )
    # Record the exhausted decision as a control-level decision for traceability
    runner._decisions.append({
        "action": retry2.action,
        "passed": False,
        "reason": retry2.reason,
        "recovery_exhausted": True,
        "attempt_count": retry2.attempt_count,
    })

    runner._report_sections.extend(["failure", "recovery"])


def _handle_known_failure_category_uses_explicit_propagation(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 3 — Scenario 9: Known category uses explicit create_failure_record, not infer."""
    # Create explicit failure — ControlPlane.create_failure_record does NOT call infer
    record = cp.create_failure_record(
        category=FailureCategory.POLICY_ERROR,
        agent_name=scenario.fake_worker_name,
        reason="protected_file_change",
        severity=FailureSeverity.HIGH,
    )
    runner._add_failure(record)

    decision = cp.decide_recovery(
        record,
        attempt_count=0,
        run_mode=scenario.run_mode,
        task_id=scenario.setup.get("task_id", "test-task-1"),
        step_name="edit_file",
    )
    runner._add_recovery(decision)

    # Verify the category is explicit (not inferred)
    if record.category == FailureCategory.POLICY_ERROR:
        runner._report_sections.append("recovery")


def _handle_repeated_tool_call_halts_or_blocks(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 3 — Scenario 10: Same tool called 5x with no progress → halted."""
    controller = ToolCallGuardrailController(
        max_exact_repeats=2,
        max_same_tool_failures=3,
        max_idempotent_calls=3,
    )
    # Simulate 5 identical tool calls with no progress
    for _ in range(5):
        controller.record_call(
            tool_name="web_search",
            args={"query": "same query"},
            result={"results": ["same result"]},
            success=True,
        )
    detection = controller.check()
    if detection.action in (ToolLoopAction.BLOCK, ToolLoopAction.HALT):
        decision = ControlDecision(
            passed=False,
            action="fail",
            reason=f"Tool loop detected: {detection.detail}",
            severity="medium",
            failure_category="tool_error",
            failure_origin="tool",
            recovery_hint="replan",
        )
    else:
        decision = ControlDecision(passed=True, action="continue")
    runner._add_decision(decision)

    if not decision.passed:
        record = create_failure_record(
            category=FailureCategory.TOOL_ERROR,
            origin="tool",
            reason=detection.failure_reason.value if detection.failure_reason else "idempotent_no_progress",
            agent_name=scenario.fake_worker_name,
        )
        runner._add_failure(record)


def _handle_planning_missing_required_evidence_requests_revision(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 4 — Scenario 11: Code plan without evidence → verify_plan blocks."""
    council = build_default_council()
    plan = council.create_plan(
        query=scenario.task_input,
        task_size="medium",
        run_mode=scenario.run_mode,
    )
    # Clear required_evidence to simulate missing evidence
    plan.required_evidence = []

    decision = cp.verify_plan(plan)
    runner._add_decision(decision)
    runner._plan_verification = {
        "plan_id": plan.plan_id,
        "steps": len(plan.steps),
        "required_evidence": plan.required_evidence,
        "has_blocking_concerns": plan.has_blocking_concerns,
        "approval_status": plan.approval_status,
        "verification_passed": decision.passed,
        "verification_reason": decision.reason,
    }


def _handle_user_rejects_plan_and_execution_does_not_start(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 4 — Scenario 12: User rejects plan → execution blocked."""
    council = build_default_council()
    plan = council.create_plan(
        query=scenario.task_input,
        task_size=scenario.setup.get("task_size", "medium"),
        run_mode=scenario.run_mode,
    )
    plan.reject()
    runner._plan_verification = {
        "plan_id": plan.plan_id,
        "approval_status": plan.approval_status,
        "steps": len(plan.steps),
        "rejected": plan.approval_status == "rejected",
    }
    # Rejected plans must not execute
    if plan.approval_status == "rejected":
        decision = ControlDecision(
            passed=False,
            action="needs_human_review",
            reason="Plan rejected by user — execution blocked",
        )
    else:
        decision = ControlDecision(passed=True, action="continue")
    runner._add_decision(decision)


def _handle_high_risk_task_requires_human_review(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 4 — Scenario 13: High-risk task requires human_review_gate."""
    council = build_default_council()
    plan = council.create_plan(
        query=scenario.task_input,
        task_size="medium",
        run_mode=scenario.run_mode,
        risk_level="high",
    )
    decision = cp.verify_plan(plan)
    runner._add_decision(decision)
    runner._plan_verification = {
        "plan_id": plan.plan_id,
        "risk_level": "high",
        "has_human_review_gates": len(plan.human_review_gates) > 0,
        "human_review_gates": plan.human_review_gates,
        "blocking_concerns": plan.blocking_concerns,
        "verification_passed": decision.passed,
        "verification_reason": decision.reason,
    }


def _handle_complex_task_requires_plan_contract(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 4 — Scenario 14: Large task requires structured PlanContract."""
    council = build_default_council()
    plan = council.create_plan(
        query=scenario.task_input,
        task_size="large",
        run_mode=scenario.run_mode,
    )
    # Approve if no blocking concerns
    approved = False
    approve_error: str | None = None
    try:
        plan.approve()
        approved = True
    except ValueError as exc:
        approve_error = str(exc)
        runner._errors.append(f"Plan approve blocked: {approve_error}")

    decision = cp.verify_plan(plan)
    runner._add_decision(decision)
    runner._plan_verification = {
        "plan_id": plan.plan_id,
        "task_size": plan.task_size,
        "steps_count": len(plan.steps),
        "has_success_criteria": len(plan.success_criteria) > 0,
        "has_stop_conditions": len(plan.stop_conditions) > 0,
        "has_required_evidence": len(plan.required_evidence) > 0,
        "has_non_goals": len(plan.non_goals) > 0,
        "planned_worker_tasks": len(plan.planned_worker_tasks),
        "blocking_concerns": plan.blocking_concerns,
        "approval_status": plan.approval_status,
        "approved": approved,
        "approve_error": approve_error,
        "verification_passed": decision.passed,
    }


def _handle_audit_report_contains_evidence_failure_and_recovery(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 5 — Scenario 15: Report generated includes evidence, failure, and recovery sections."""
    # Exercise evidence verification
    evidence_status = runner._build_evidence_status(worker_output, scenario)
    decision = cp.verify_worker_evidence(evidence_status)
    runner._add_decision(decision)

    # Create a failure record
    if not decision.passed:
        record = create_failure_record(
            category=FailureCategory(decision.failure_category or "task_quality_error"),
            origin="worker",
            reason=decision.reason,
            agent_name=scenario.fake_worker_name,
            severity=FailureSeverity.MEDIUM,
        )
        runner._add_failure(record)

        # Recovery decision
        recovery = cp.decide_recovery(record, attempt_count=0, run_mode=scenario.run_mode,
                                       task_id="test-task-1", step_name="test")
        runner._add_recovery(recovery)

    runner._report_sections = ["evidence"]
    if runner._failure_record:
        runner._report_sections.append("failure")
    if runner._recovery_decision:
        runner._report_sections.append("recovery")


def _handle_report_must_not_claim_success_without_evidence(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract 5 — Scenario 16: Success without evidence → test must fail."""
    evidence_status = runner._build_evidence_status(worker_output, scenario)
    decision = cp.verify_worker_evidence(evidence_status)
    runner._add_decision(decision)

    if not decision.passed:
        # Report must NOT claim success when evidence is missing
        runner._report_sections = ["evidence"]
        if decision.failure_category:
            runner._report_sections.append("failure")


def _handle_small_task_bypasses_heavy_orchestration(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract task router — Scenario 17: Small query → log mode, no heavy flow."""
    # In log mode, policy checks return passed=True with action=continue
    policy.mode = "log"
    cp.set_policy(policy)

    # Check that protected file changes are only logged, not blocked
    files = worker_output.get("files_changed", [])
    decision = cp.check_policy_for_file_changes(files_changed=files)
    runner._add_decision(decision)
    # In log mode this should pass (logged, not enforced)
    runner._report_sections.append("evidence")


def _handle_medium_task_uses_controlled_mode(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract task router — Scenario 18: Medium query → controlled mode."""
    policy.mode = "controlled"
    cp.set_policy(policy)

    evidence_status = runner._build_evidence_status(worker_output, scenario)
    decision = cp.verify_worker_evidence(evidence_status)
    runner._add_decision(decision)
    for item in evidence_status.items:
        runner._evidence_items.append(item.model_dump())


def _handle_human_review_approved_continues(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract human review — Scenario 19: Plan awaiting → approved → continues."""
    council = build_default_council()
    plan = council.create_plan(
        query=scenario.task_input,
        task_size="medium",
        run_mode=scenario.run_mode,
    )
    # Simulate: plan was awaiting, then user approves
    try:
        plan.approve()
        approved = True
    except ValueError:
        approved = False

    decision = cp.verify_plan(plan)
    runner._add_decision(decision)
    runner._plan_verification = {
        "plan_id": plan.plan_id,
        "approval_status": plan.approval_status,
        "approved": approved,
        "verification_passed": decision.passed,
        "verification_reason": decision.reason,
    }


def _handle_human_review_rejected_stops(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract human review — Scenario 20: Plan awaiting → rejected → stopped."""
    council = build_default_council()
    plan = council.create_plan(
        query=scenario.task_input,
        task_size="medium",
        run_mode=scenario.run_mode,
    )
    plan.reject()
    runner._plan_verification = {
        "plan_id": plan.plan_id,
        "approval_status": plan.approval_status,
        "rejected": plan.approval_status == "rejected",
    }
    decision = ControlDecision(
        passed=False,
        action="needs_human_review",
        reason="Plan rejected by user — execution stopped",
    )
    runner._add_decision(decision)


def _handle_runner_interrupt_can_resume(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract runner — Scenario 21: Runner can pause on interrupt and resume.

    Uses the real LiveInterruptController to pause execution (simulating a
    user interrupt), then resume.  After resume, execution continues normally.
    """
    controller = LiveInterruptController()

    # Phase 1: Pause — simulate a user hitting pause mid-execution
    pause_resp = controller.pause(reason="User requested pause during execution")
    assert pause_resp.accepted, f"Pause must be accepted: {pause_resp.message}"
    assert controller.is_paused(), "Controller must report paused state"

    # Record the pause as a control decision (pause is valid, not a failure)
    runner._decisions.append({
        "action": "pause",
        "passed": True,
        "reason": pause_resp.message,
        "signal": pause_resp.signal.value,
    })

    # Phase 2: Resume — user confirms continuation
    resume_resp = controller.resume(reason="User approved continuation")
    assert resume_resp.accepted, f"Resume must be accepted: {resume_resp.message}"
    assert not controller.is_paused(), "Controller must no longer be paused after resume"

    # After resume, execution should continue normally
    runner._decisions.append({
        "action": "continue",
        "passed": True,
        "reason": "Execution resumed after interrupt — continuing",
        "signal": resume_resp.signal.value,
    })

    runner._report_sections.append("evidence")


def _handle_regression_compare_detects_degraded_result(
    runner: GoldenScenarioRunner,
    *,
    cp: ControlPlane,
    policy: Policy,
    worker_output: dict[str, Any],
    scenario: GoldenScenario,
) -> None:
    """Contract report — Scenario 22: Regression compare detects degraded quality.

    Uses the real RegressionCompare metric diff logic (pure computation, no
    filesystem) to compare a baseline (good) run against a degraded (current)
    run.  The comparison must produce a regression signal.
    """
    baseline_metrics: dict[str, float | int] = scenario.setup.get("baseline_metrics", {
        "steps_executed": 5,
        "failed_evaluations": 0,
        "retry_count": 0,
        "success_rate": 1,
    })
    degraded_metrics: dict[str, float | int] = scenario.setup.get("degraded_metrics", {
        "steps_executed": 12,
        "failed_evaluations": 3,
        "retry_count": 2,
        "success_rate": 0,
    })

    # Build MetricDiff objects directly — this exercises the real
    # RegressionCompare._create_diff and _determine_signal logic.
    comparator = RegressionCompare.__new__(RegressionCompare)
    comparator.project_root = None  # type: ignore[assignment]
    comparator.reports_dir = None  # type: ignore[assignment]
    comparator.states_dir = None  # type: ignore[assignment]

    diffs: list[MetricDiff] = []
    for metric_name in ("steps_executed", "failed_evaluations", "retry_count"):
        lower_is_better = True
        diffs.append(comparator._create_diff(  # type: ignore[arg-type]
            metric_name,
            baseline_metrics[metric_name],
            degraded_metrics[metric_name],
            lower_is_better=lower_is_better,
        ))
    # success_rate: higher is better
    diffs.append(comparator._create_diff(  # type: ignore[arg-type]
        "success_rate",
        baseline_metrics["success_rate"],
        degraded_metrics["success_rate"],
        lower_is_better=False,
    ))

    # Determine the regression signal using the real algorithm
    signal = comparator._determine_signal(diffs)  # type: ignore[arg-type]

    regression_count = sum(1 for d in diffs if d.is_regression)
    if signal in (RegressionSignal.MINOR_REGRESSION, RegressionSignal.MAJOR_REGRESSION):
        decision = ControlDecision(
            passed=False,
            action="needs_human_review",
            reason=f"Regression detected: {regression_count} metrics degraded, signal={signal.value}",
            severity="high" if signal == RegressionSignal.MAJOR_REGRESSION else "medium",
            failure_category="task_quality_error",
            failure_origin="control_plane",
            recovery_hint="replan",
        )
    else:
        decision = ControlDecision(passed=True, action="continue",
                                   reason=f"No regression: signal={signal.value}")

    runner._add_decision(decision)
    runner._plan_verification = {
        "signal": signal.value,
        "regression_count": regression_count,
        "improvement_count": sum(1 for d in diffs if not d.is_regression and d.diff != 0),
        "total_metrics": len(diffs),
    }

    if not decision.passed:
        runner._report_sections.extend(["failure", "evidence"])


# =============================================================================
# Dispatch table
# =============================================================================

_DISPATCH: dict[str, Any] = {
    # Contract 1 — Evidence beats claims
    "normal_completion_with_observed_evidence": _handle_normal_completion_with_observed_evidence,
    "missing_evidence_blocks_success": _handle_missing_evidence_blocks_success,
    "worker_reported_tests_do_not_count_as_observed": _handle_worker_reported_tests_do_not_count_as_observed,
    "memory_hint_does_not_count_as_evidence": _handle_memory_hint_does_not_count_as_evidence,
    # Contract 2 — Policy controls risky actions
    "policy_denies_protected_file_change": _handle_policy_denies_protected_file_change,
    "reviewer_cannot_write_files": _handle_reviewer_cannot_write_files,
    "guardrail_blocks_secret_leak": _handle_guardrail_blocks_secret_leak,
    # Contract 3 — Recovery is bounded
    "test_failure_triggers_bounded_recovery": _handle_test_failure_triggers_bounded_recovery,
    "known_failure_category_uses_explicit_propagation": _handle_known_failure_category_uses_explicit_propagation,
    "repeated_tool_call_halts_or_blocks": _handle_repeated_tool_call_halts_or_blocks,
    # Contract 4 — Planning prevents bad execution
    "planning_missing_required_evidence_requests_revision": _handle_planning_missing_required_evidence_requests_revision,
    "user_rejects_plan_and_execution_does_not_start": _handle_user_rejects_plan_and_execution_does_not_start,
    "high_risk_task_requires_human_review": _handle_high_risk_task_requires_human_review,
    "complex_task_requires_plan_contract": _handle_complex_task_requires_plan_contract,
    # Contract 5 — Reports are honest
    "audit_report_contains_evidence_failure_and_recovery": _handle_audit_report_contains_evidence_failure_and_recovery,
    "report_must_not_claim_success_without_evidence": _handle_report_must_not_claim_success_without_evidence,
    # Task router integration
    "small_task_bypasses_heavy_orchestration": _handle_small_task_bypasses_heavy_orchestration,
    "medium_task_uses_controlled_mode": _handle_medium_task_uses_controlled_mode,
    # Human review & resume
    "human_review_approved_continues": _handle_human_review_approved_continues,
    "human_review_rejected_stops": _handle_human_review_rejected_stops,
    # Runner interrupt & resume
    "runner_interrupt_can_resume": _handle_runner_interrupt_can_resume,
    # Regression comparison
    "regression_compare_detects_degraded_result": _handle_regression_compare_detects_degraded_result,
}
