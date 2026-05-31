"""MainlineExecutor — drives the full AAO control chain from plan to audit.

Wires: PlanContract → WorkerTaskPacket → worker execution → evidence
classification → ControlPlane decisions → audit report.

This is THE integration point that connects all AAO components.  The old
YAML-workflow path through Scheduler is preserved for legacy/native mode.
"""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .auto_repair import AutoRepairLoop, FixTask, ReviewFinding
from .control_models import ControlDecision, WorkerEvidenceStatus
from .control_plane import ControlPlane
from .failure_taxonomy import FailureCategory, FailureReason
from .independent_evidence import (
    GitBaseline,
    IndependentEvidence,
    capture_git_baseline,
    capture_independent_evidence,
    rejected_required_checks,
)
from .planning import PlanContract, PlannedWorkerTask, plan_contract_to_dict
from .policy import Policy
from .worker_protocol import (
    PacketFiles,
    WorkerTaskPacket,
    classify_worker_evidence,
    classify_worker_evidence_from_packet,
    list_observed_files,
    load_worker_result_text,
    load_worker_status,
    packet_dir,
)


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Mainline result
# =============================================================================


@dataclass
class MainlineResult:
    """Structured result from a mainline execution."""

    run_id: str = ""
    task_id: str = ""
    plan_id: str = ""
    status: str = "unknown"  # completed, blocked_needs_review, blocked_failed, pending_external
    worker_mode: str = "fake"
    retry_count: int = 0
    worker_result: dict[str, Any] = field(default_factory=dict)
    evidence_status: dict[str, Any] | None = None
    control_decisions: list[dict[str, Any]] = field(default_factory=list)
    repair_rounds: list[dict[str, Any]] = field(default_factory=list)
    review_findings: list[dict[str, Any]] = field(default_factory=list)
    report_path: str = ""
    evidence_path: str = ""
    worker_packet_path: str = ""
    changed_files: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "worker_mode": self.worker_mode,
            "retry_count": self.retry_count,
            "worker_result": self.worker_result,
            "evidence_status": self.evidence_status,
            "control_decisions": self.control_decisions,
            "repair_rounds": self.repair_rounds,
            "review_findings": self.review_findings,
            "report_path": self.report_path,
            "evidence_path": self.evidence_path,
            "worker_packet_path": self.worker_packet_path,
            "changed_files": self.changed_files,
            "summary": self.summary,
        }


# =============================================================================
# MainlineExecutor
# =============================================================================


class MainlineExecutor:
    """Drives the full AAO control chain for a plan.

    Takes a PlanContract and a worker_mode, then:
    0. Enforces plan approval status
    1. Converts plan to WorkerTaskPacket (with policy-derived boundaries)
    2. Executes worker (fake writes files; packet writes to disk)
    3. Classifies evidence
    4. Checks test results for failures
    5. Runs ControlPlane checks (evidence, policy, guardrails)
    6. Generates audit report
    7. Returns MainlineResult
    """

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        policy: Policy | None = None,
        reviewer: Any = None,
    ) -> None:
        self.project_root = project_root or Path.cwd()
        self._policy = policy or self._load_policy()
        self._repair_loop = AutoRepairLoop(max_attempts=2)
        self._reviewer = reviewer  # None → use RuleBasedReviewer at call time

    @staticmethod
    def _load_policy() -> Policy:
        """Load policy from the standard location, falling back to defaults."""
        policy_path = Path.cwd() / "examples" / "policy.yaml"
        if policy_path.exists():
            return Policy.from_dict(
                json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.suffix == ".json"
                else _load_yaml_policy(policy_path)
            )
        # Try YAML load
        try:
            import yaml as _yaml
            if policy_path.exists():
                with open(policy_path, encoding="utf-8") as fh:
                    return Policy.from_dict(_yaml.safe_load(fh) or {})
        except Exception:
            pass
        return Policy.defaults()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def execute(
        self,
        plan: PlanContract,
        *,
        worker_mode: str = "fake",
        max_workers: int = 2,
        execution_backend: str = "native",
    ) -> MainlineResult:
        """Execute a plan through the mainline chain.

        Args:
            plan: An **approved** PlanContract.  execute() enforces this —
                  unapproved plans are rejected.
            worker_mode: "fake" (deterministic, writes files) or "packet" (writes
                         packet to disk for external worker) or "claude-code".
            max_workers: Maximum concurrent workers (Phase 20 multi-worker).
            execution_backend: "native" (MultiWorkerExecutor/ThreadPoolExecutor)
                               or "langgraph" (LangGraphRunner).

        Returns:
            MainlineResult with all paths, decisions, and status.
        """
        # 0. Enforce plan approval — must be pre-approved, no auto-approve
        if plan.approval_status != "approved":
            return MainlineResult(
                plan_id=plan.plan_id,
                status="blocked_needs_review",
                worker_mode=worker_mode,
                worker_result={"behaviour": "blocked", "summary": "Plan not approved"},
                control_decisions=[{
                    "action": "needs_human_review",
                    "passed": False,
                    "reason": f"Plan approval_status={plan.approval_status} — must be explicitly approved before execution",
                }],
                summary=f"Blocked: plan not approved (status={plan.approval_status})",
            )

        # LangGraph backend: delegate to LangGraphRunner
        if execution_backend == "langgraph":
            return self._execute_langgraph(plan, worker_mode=worker_mode,
                                           max_workers=max_workers)

        # Native backend: Phase 20 multi-worker path or single worker
        if len(plan.planned_worker_tasks) > 1:
            return self._execute_multi_worker(plan, worker_mode=worker_mode,
                                               max_workers=max_workers)

        run_id = _utc_now_compact() + "-" + uuid.uuid4().hex[:6]
        task_id = f"task-{run_id}"

        # 1. Convert plan to WorkerTaskPacket
        packet = self._plan_to_packet(plan, run_id=run_id, task_id=task_id)

        baseline: GitBaseline | None = None
        if worker_mode == "claude-code":
            check_policy_decisions = self._check_required_check_policy(packet)
            if check_policy_decisions:
                return MainlineResult(
                    run_id=run_id,
                    task_id=task_id,
                    plan_id=plan.plan_id,
                    status="blocked_needs_review",
                    worker_mode=worker_mode,
                    control_decisions=[_decision_to_dict(d) for d in check_policy_decisions],
                    worker_packet_path=str(packet.packet_root),
                    summary=check_policy_decisions[0].reason,
                )
            baseline = capture_git_baseline(packet, self.project_root)
            if baseline is None:
                decision = self._missing_git_baseline_decision()
                return MainlineResult(
                    run_id=run_id,
                    task_id=task_id,
                    plan_id=plan.plan_id,
                    status="blocked_needs_review",
                    worker_mode=worker_mode,
                    control_decisions=[_decision_to_dict(decision)],
                    worker_packet_path=str(packet.packet_root),
                    summary=decision.reason,
                )

        # 2. Execute worker
        worker_result = self._execute_worker(packet, worker_mode=worker_mode)

        # 2b. Packet mode: stop here — awaiting external worker
        if worker_mode == "packet":
            return MainlineResult(
                run_id=run_id,
                task_id=task_id,
                plan_id=plan.plan_id,
                status="pending_external",
                worker_mode="packet",
                worker_result=worker_result,
                worker_packet_path=str(packet.packet_root),
                summary="Packet written to disk — awaiting external worker execution",
            )

        # 2c. Claude Code worker infrastructure failures — command not found,
        #     timeout, permission denied.  These are not task failures; they
        #     are worker-launch failures and must not be mistaken for success.
        if worker_mode == "claude-code":
            infra_decisions = self._check_worker_infrastructure(worker_result)
            if infra_decisions:
                # Derive status from the actual decision actions (not hardcoded):
                # command-not-found / timeout → fail → blocked_failed
                # non-zero exit → needs_human_review → blocked_needs_review
                infra_actions = {d.action for d in infra_decisions}
                if "needs_human_review" in infra_actions:
                    infra_status = "blocked_needs_review"
                elif "fail" in infra_actions:
                    infra_status = "blocked_failed"
                else:
                    infra_status = "blocked"
                return MainlineResult(
                    run_id=run_id,
                    task_id=task_id,
                    plan_id=plan.plan_id,
                    status=infra_status,
                    worker_mode=worker_mode,
                    worker_result=worker_result,
                    control_decisions=[_decision_to_dict(d) for d in infra_decisions],
                    worker_packet_path=str(packet.packet_root),
                    summary=f"Worker infrastructure failure: {worker_result.get('error', 'unknown')}",
                )

        # 3-5. Evidence → control checks → status (with retry loop)
        max_retries = 2
        retry_count = 0
        all_control_decisions: list[ControlDecision] = []
        final_evidence_status: WorkerEvidenceStatus | None = None
        final_worker_result: dict[str, Any] = worker_result
        final_independent: IndependentEvidence | None = None

        for attempt in range(max_retries + 1):
            # 2d. Independent observation (real worker modes only): AAO runs the
            #     required checks and computes the git diff itself, so evidence
            #     is ground truth rather than worker self-report.  Returns None
            #     (→ fall back to reported evidence) when not a git work tree.
            independent: IndependentEvidence | None = None
            if worker_mode == "claude-code":
                independent = capture_independent_evidence(
                    packet, self.project_root, baseline=baseline
                )
            final_independent = independent

            # 3. Classify evidence (AAO-observed changed files override self-report)
            evidence_status = classify_worker_evidence_from_packet(
                packet,
                observed_changed_files=(
                    independent.changed_files if independent is not None else None
                ),
            )
            final_evidence_status = evidence_status

            # 4. Check results — prefer AAO's real exit codes over scraping a
            #    worker-written test_output.txt.
            if independent is not None and independent.checks:
                test_decisions = self._check_independent_results(independent)
            else:
                test_decisions = self._check_test_results(packet)

            # 5. Run ControlPlane checks
            baseline_decisions = (
                self._check_baseline_integrity(independent)
                if independent is not None else []
            )
            control_decisions = test_decisions + baseline_decisions + self._run_control_checks(
                packet, evidence_status, final_worker_result,
                worker_mode=worker_mode,
            )
            all_control_decisions = control_decisions

            # 6. Determine whether this attempt is recoverable
            failed_actions = {d.action for d in control_decisions if not d.passed}
            retryable = {"retry", "retry_with_backoff"} & failed_actions
            should_replan = "replan" in failed_actions

            if (retryable or should_replan) and attempt < max_retries:
                retry_count += 1

                if should_replan:
                    # Merge failure reasons into the plan so the worker sees them
                    failure_reasons = [
                        d.reason for d in control_decisions
                        if not d.passed and d.action == "replan"
                    ]
                    plan.steps = list(plan.steps) + [
                        f"REPLAN ({retry_count}): " + "; ".join(failure_reasons[:3])
                    ]
                    # Regenerate packet with updated plan
                    packet = self._plan_to_packet(plan, run_id=run_id, task_id=task_id)

                if retryable:
                    if "retry_with_backoff" in retryable:
                        time.sleep(random.uniform(0.5, 3.0))

                # Re-execute worker for next attempt
                # Keep the original task baseline across retries so final
                # evidence contains every net change introduced by this task,
                # not only changes made during the last attempt.
                final_worker_result = self._execute_worker(packet, worker_mode=worker_mode)
                continue
            break

        # 6b. Phase 22: auto-repair loop — before giving up, try bounded fix
        #
        # Only task-quality errors whose recovery action is "retry" are
        # eligible.  "request_evidence" (missing evidence), "fail", and
        # "needs_human_review" are not fixable by a code-change worker.
        failed_decisions = [d for d in all_control_decisions if not d.passed]
        repair_rounds: list[dict[str, Any]] = []

        if failed_decisions and worker_mode != "packet":
            primary = failed_decisions[0]
            is_repairable = (
                primary.failure_category == FailureCategory.TASK_QUALITY_ERROR.value
                and primary.action == "retry"
            )
            if is_repairable:
                affected_file = (
                    packet.allowed_files[0] if packet.allowed_files
                    else (final_evidence_status.changed_files[0]
                          if final_evidence_status and final_evidence_status.changed_files
                          else "")
                )
                finding = ReviewFinding.from_control_decision(
                    step_id=task_id,
                    reason=primary.reason,
                    category=primary.failure_category,
                    location=affected_file,
                )
                repair_result, fix_packet, fix_independent, fix_worker_result = self._try_auto_repair(
                    finding=finding,
                    worker_mode=worker_mode,
                )
                repair_rounds = [r.to_dict() for r in repair_result.rounds]
                if repair_result.is_fixed:
                    all_control_decisions = [
                        ControlDecision(
                            action="continue", passed=True,
                            reason=(
                                f"Auto-repair fixed issue in "
                                f"{repair_result.total_rounds} round(s)"
                            ),
                        )
                    ] + [d for d in all_control_decisions if d.passed]
                    # Point follow-up inspection (Phase 23 reviewer) at the
                    # fix evidence, not the stale original packet.
                    if fix_packet is not None:
                        packet = fix_packet
                        final_independent = fix_independent
                        if fix_worker_result is not None:
                            final_worker_result = fix_worker_result
                        final_evidence_status = classify_worker_evidence_from_packet(
                            packet,
                            observed_changed_files=(
                                fix_independent.changed_files
                                if fix_independent is not None else None
                            ),
                        )

        # 6c. Phase 23: run reviewer on observed evidence
        #
        # The reviewer inspects the same on-disk evidence the control plane
        # checked (diff, test output, result.md).  It produces ReviewFindings
        # that are independent of worker self-assessments.  Blocking findings
        # trigger a bounded auto-repair attempt; non-blocking ones are recorded.
        review_finding_dicts: list[dict[str, Any]] = []
        if worker_mode != "packet":
            review_findings = self._run_reviewer(packet, final_independent)
            for finding in review_findings:
                finding_dict: dict[str, Any] = {
                    "finding_id": finding.finding_id,
                    "step_id": finding.step_id,
                    "severity": finding.severity,
                    "category": finding.category,
                    "description": finding.description,
                    "location": finding.location,
                    "suggested_fix": finding.suggested_fix,
                    "source": finding.source,
                }
                if finding.is_blocking:
                    repair_result, _fix_pkt, _fix_ev, _fix_wr = self._try_auto_repair(
                        finding=finding,
                        worker_mode=worker_mode,
                    )
                    repair_rounds.extend([r.to_dict() for r in repair_result.rounds])
                    finding_dict["repair_result"] = repair_result.status
                    finding_dict["repair_status"] = (
                        "fixed" if repair_result.is_fixed else "still_failing"
                    )
                else:
                    finding_dict["repair_status"] = "recorded"
                review_finding_dicts.append(finding_dict)

            # Escalate unrepaired blocking reviewer findings to human review.
            # These are evidence-level issues the auto-repair loop could not fix.
            unrepaired = [
                f for f in review_finding_dicts
                if f.get("severity") == "blocking" and f.get("repair_status") != "fixed"
            ]
            if unrepaired:
                all_control_decisions = all_control_decisions + [
                    ControlDecision(
                        passed=False,
                        action="needs_human_review",
                        reason=(
                            f"Reviewer found {len(unrepaired)} unrepaired blocking "
                            f"issue(s): "
                            + "; ".join(
                                f["description"][:80] for f in unrepaired[:3]
                            )
                        ),
                        severity="high",
                        failure_category="task_quality_error",
                        failure_origin="control_plane",
                        recovery_hint="needs_human_review",
                    )
                ]

            # 6d. Phase 30: Layer 2 — Codex LLM reviewer (conditional)
            #
            # The Codex reviewer in a read-only sandbox provides a semantic
            # second opinion.  It is only invoked when the risk/cost trade-off
            # justifies the extra LLM call (large task, high risk, or Layer 1
            # found issues).  When unavailable or skipped, the pipeline
            # continues without it.
            if worker_mode != "fake" and self._should_invoke_codex_reviewer(
                task_size=getattr(plan, "task_size", "medium"),
                risk_level=packet.risk_level,
                rule_findings=list(review_findings),
                repair_history=repair_rounds if repair_rounds else None,
                allowed_files=packet.allowed_files,
                changed_files=final_evidence_status.changed_files,
            ):
                codex_findings = self._run_codex_reviewer(packet, final_independent)
                for finding in codex_findings:
                    cf_dict: dict[str, Any] = {
                        "finding_id": finding.finding_id,
                        "step_id": finding.step_id or packet.task_id,
                        "severity": finding.severity,
                        "category": finding.category,
                        "description": finding.description,
                        "location": finding.location,
                        "suggested_fix": finding.suggested_fix,
                        "source": "codex_reviewer",
                    }
                    if finding.is_blocking:
                        repair_result, _fp, _fev, _fwr = self._try_auto_repair(
                            finding=finding,
                            worker_mode=worker_mode,
                        )
                        repair_rounds.extend(
                            [r.to_dict() for r in repair_result.rounds]
                        )
                        cf_dict["repair_result"] = repair_result.status
                        cf_dict["repair_status"] = (
                            "fixed" if repair_result.is_fixed else "still_failing"
                        )
                    else:
                        cf_dict["repair_status"] = "recorded"
                    review_finding_dicts.append(cf_dict)

        # 7. Generate audit report
        report_path, evidence_path = self._generate_report(
            plan=plan,
            packet=packet,
            worker_result=final_worker_result,
            evidence_status=final_evidence_status,
            control_decisions=all_control_decisions,
        )

        # 8. Determine overall status
        overall_status = self._determine_status(all_control_decisions, final_evidence_status)

        # 9. Persist review state when blocked for human review
        if overall_status == "blocked_needs_review":
            self._persist_review_state(
                run_id=run_id,
                task_id=task_id,
                plan=plan,
                worker_mode=worker_mode,
                max_workers=max_workers,
                packet=packet,
                result_status=overall_status,
            )

        return MainlineResult(
            run_id=run_id,
            task_id=task_id,
            plan_id=plan.plan_id,
            status=overall_status,
            worker_mode=worker_mode,
            retry_count=retry_count,
            worker_result=final_worker_result,
            evidence_status=_evidence_status_to_dict(final_evidence_status),
            control_decisions=[_decision_to_dict(d) for d in all_control_decisions],
            repair_rounds=repair_rounds,
            review_findings=review_finding_dicts,
            report_path=str(report_path),
            evidence_path=str(evidence_path),
            worker_packet_path=str(packet.packet_root),
            changed_files=final_evidence_status.changed_files,
            summary=self._build_summary(overall_status, all_control_decisions, final_evidence_status),
        )

    def complete_packet_execution(
        self,
        task_id: str,
        *,
        plan: PlanContract,
        worker_mode: str = "packet",
    ) -> MainlineResult | None:
        """Complete execution of a packet that was written to disk.

        This is the resume path for ``worker_mode="packet"``: the external
        worker has finished and written results back to the packet directory.
        This method picks up from there — evidence classification, control
        checks, and report generation.

        Returns None if the packet directory does not exist.
        """
        packet_root = packet_dir(self.project_root, task_id)
        if not packet_root.exists():
            return None

        run_id = _utc_now_compact() + "-" + uuid.uuid4().hex[:6]
        packet = WorkerTaskPacket(
            task_id=task_id,
            task_title=plan.planned_worker_tasks[0].title if plan.planned_worker_tasks else "Packet task",
            task_objective=plan.objective,
            allowed_files=plan.planned_worker_tasks[0].allowed_files if plan.planned_worker_tasks else [],
            denied_files=plan.planned_worker_tasks[0].denied_files if plan.planned_worker_tasks else [],
            required_checks=plan.planned_worker_tasks[0].required_checks if plan.planned_worker_tasks else [],
            expected_evidence=plan.planned_worker_tasks[0].expected_evidence if plan.planned_worker_tasks else [],
            packet_root=packet_root,
        )

        worker_result = load_worker_result_text(packet)
        evidence_status = classify_worker_evidence_from_packet(packet)

        # Check test results
        test_decisions = self._check_test_results(packet)

        # Run control checks
        control_decisions = test_decisions + self._run_control_checks(
            packet, evidence_status, worker_result,
            worker_mode=worker_mode,
        )

        # Generate report
        report_path, evidence_path = self._generate_report(
            plan=plan,
            packet=packet,
            worker_result=worker_result,
            evidence_status=evidence_status,
            control_decisions=control_decisions,
        )

        overall_status = self._determine_status(control_decisions, evidence_status)

        if overall_status == "blocked_needs_review":
            self._persist_review_state(
                run_id=run_id,
                task_id=task_id,
                plan=plan,
                worker_mode=worker_mode,
                max_workers=1,
                packet=packet,
                result_status=overall_status,
            )

        return MainlineResult(
            run_id=run_id,
            task_id=task_id,
            plan_id=plan.plan_id,
            status=overall_status,
            worker_mode=worker_mode,
            worker_result=worker_result,
            evidence_status=_evidence_status_to_dict(evidence_status),
            control_decisions=[_decision_to_dict(d) for d in control_decisions],
            report_path=str(report_path),
            evidence_path=str(evidence_path),
            worker_packet_path=str(packet.packet_root),
            changed_files=evidence_status.changed_files,
            summary=self._build_summary(overall_status, control_decisions, evidence_status),
        )

    def execute_from_query(
        self,
        query: str,
        *,
        worker_mode: str = "fake",
        run_mode: str = "controlled",
        task_size: str = "medium",
        max_workers: int = 2,
        execution_backend: str = "native",
    ) -> MainlineResult:
        """Execute a simple query directly without a pre-existing PlanContract.

        For small/medium tasks that don't go through Planning Council but the
        user still wants the mainline path (--worker-mode flag or auto-routed).

        For orchestrated/large tasks, LLM planning is attempted if providers
        are configured; otherwise deterministic mode is used as fallback.
        """
        from .planning import build_default_council, PlanningMode

        # Use LLM planning for orchestrated or large tasks when a provider key
        # is configured; deterministic mode for everything else.
        planning_mode: PlanningMode = "deterministic"
        if run_mode == "orchestrated" or task_size == "large":
            import os
            if (
                os.environ.get("DEEPSEEK_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("AAO_PLANNING_PROVIDER")
            ):
                planning_mode = "llm"

        council = build_default_council(mode=planning_mode)
        plan = council.create_plan(
            query,
            task_size=task_size,
            run_mode=run_mode,
        )
        if plan.has_blocking_concerns:
            return MainlineResult(
                plan_id=plan.plan_id,
                status="blocked_needs_review",
                worker_mode=worker_mode,
                worker_result={"behaviour": "blocked", "summary": "Plan has blocking concerns"},
                control_decisions=[{
                    "action": "needs_human_review",
                    "passed": False,
                    "reason": f"Plan has {len(plan.blocking_concerns)} blocking concern(s)",
                }],
                summary=f"Plan blocked: {plan.blocking_concerns[0] if plan.blocking_concerns else 'unknown'}",
            )
        try:
            plan.approve()
        except ValueError:
            return MainlineResult(
                plan_id=plan.plan_id,
                status="blocked_needs_review",
                worker_mode=worker_mode,
                worker_result={"behaviour": "blocked", "summary": "Plan has blocking concerns"},
                control_decisions=[{
                    "action": "needs_human_review",
                    "passed": False,
                    "reason": f"Plan has {len(plan.blocking_concerns)} blocking concern(s)",
                }],
                summary=f"Plan blocked: {plan.blocking_concerns[0] if plan.blocking_concerns else 'unknown'}",
            )
        return self.execute(plan, worker_mode=worker_mode, max_workers=max_workers,
                           execution_backend=execution_backend)

    # ------------------------------------------------------------------
    # Phase 20 — Multi-worker execution
    # ------------------------------------------------------------------

    def _execute_multi_worker(
        self,
        plan: PlanContract,
        *,
        worker_mode: str = "fake",
        max_workers: int = 2,
    ) -> MainlineResult:
        """Execute a plan with multiple worker tasks via MultiWorkerExecutor."""
        from .multi_worker import MultiWorkerExecutor

        executor = MultiWorkerExecutor(
            project_root=self.project_root,
            policy=self._policy,
            max_workers=max_workers,
            worker_mode=worker_mode,
        )
        mw_result = executor.execute(plan)

        return MainlineResult(
            run_id=mw_result.run_id,
            task_id=f"multi-{mw_result.run_id}",
            plan_id=mw_result.plan_id,
            status=mw_result.status,
            worker_mode=worker_mode,
            worker_result=mw_result.to_dict(),
            evidence_status={
                "passed_steps": mw_result.passed_steps,
                "failed_steps": mw_result.failed_steps,
                "blocked_steps": mw_result.blocked_steps,
                "step_count": mw_result.step_count,
            },
            control_decisions=[
                {
                    "action": "continue" if mw_result.status == "completed" else "needs_human_review",
                    "passed": mw_result.status == "completed",
                    "reason": mw_result.summary,
                },
            ],
            report_path=mw_result.combined_report_path,
            evidence_path=mw_result.combined_evidence_path,
            summary=mw_result.summary,
        )

    # ------------------------------------------------------------------
    # Phase 22 — Auto-Repair
    # ------------------------------------------------------------------

    def _try_auto_repair(
        self,
        *,
        finding: ReviewFinding,
        worker_mode: str = "fake",
    ) -> tuple[
        Any,
        WorkerTaskPacket | None,
        IndependentEvidence | None,
        dict[str, Any] | None,
    ]:
        """Attempt the auto-repair loop for a single blocking finding.

        Returns (repair_result, last_fix_packet).  *last_fix_packet* is the
        WorkerTaskPacket from the final repair round, so the caller can
        direct follow-up inspection (e.g. Phase 23 reviewer) at the fixed
        evidence instead of the stale original packet.
        """
        packets: list[WorkerTaskPacket] = []
        independent_by_task: dict[str, IndependentEvidence | None] = {}
        worker_results: dict[str, dict[str, Any]] = {}

        def _dispatch(fix_task: FixTask) -> dict[str, Any]:
            fix_packet = self._fix_task_to_packet(fix_task)
            packets.append(fix_packet)
            if worker_mode == "claude-code":
                decisions = self._check_required_check_policy(fix_packet)
                if decisions:
                    result = {
                        "behaviour": "blocked",
                        "worker_status": "blocked",
                        "summary": decisions[0].reason,
                    }
                    worker_results[fix_packet.task_id] = result
                    independent_by_task[fix_packet.task_id] = None
                    return result
                baseline = capture_git_baseline(fix_packet, self.project_root)
                if baseline is None:
                    result = {
                        "behaviour": "blocked",
                        "worker_status": "blocked",
                        "summary": self._missing_git_baseline_decision().reason,
                    }
                    worker_results[fix_packet.task_id] = result
                    independent_by_task[fix_packet.task_id] = None
                    return result
            else:
                baseline = None
            result = self._execute_worker(fix_packet, worker_mode=worker_mode)
            worker_results[fix_packet.task_id] = result
            independent_by_task[fix_packet.task_id] = (
                capture_independent_evidence(
                    fix_packet, self.project_root, baseline=baseline
                )
                if worker_mode == "claude-code" else None
            )
            return result

        def _verify(result: dict[str, Any]) -> bool:
            if not packets:
                return False
            return self._verify_fix(
                result,
                packets[-1],
                independent=independent_by_task.get(packets[-1].task_id),
            )

        repair_result = self._repair_loop.attempt_repair(
            finding,
            dispatch_fn=_dispatch,
            verify_fn=_verify,
            target_file=finding.location,
        )
        last_packet = packets[-1] if packets else None
        return (
            repair_result,
            last_packet,
            independent_by_task.get(last_packet.task_id) if last_packet else None,
            worker_results.get(last_packet.task_id) if last_packet else None,
        )

    def _verify_fix(
        self,
        worker_result: dict[str, Any],
        packet: WorkerTaskPacket,
        *,
        independent: IndependentEvidence | None = None,
    ) -> bool:
        """Verify a FixTask's output by re-running on-disk checks.

        Unlike the previous empty-criteria ControlPlane call, this re-runs
        the same checks the mainline path uses: test-output inspection and
        evidence classification.
        """
        # Worker itself reported a hard failure
        if worker_result.get("behaviour") in ("blocked", "failed"):
            return False
        if worker_result.get("worker_status") in ("blocked", "failed", "error"):
            return False
        # Prefer checks AAO ran itself for a real worker fix.
        if independent is not None and independent.checks:
            test_decisions = self._check_independent_results(independent)
        else:
            test_decisions = self._check_test_results(packet)
        if any(not d.passed for d in test_decisions):
            return False
        if independent is not None and self._check_baseline_integrity(independent):
            return False
        # Evidence classification must not report missing required checks
        evidence_status = classify_worker_evidence_from_packet(
            packet,
            observed_changed_files=(
                independent.changed_files if independent is not None else None
            ),
        )
        if evidence_status.has_missing_required:
            return False
        return True

    def _fix_task_to_packet(self, fix_task: FixTask) -> WorkerTaskPacket:
        """Convert a FixTask into a bounded WorkerTaskPacket.

        The packet is scoped to the single target file and verification
        check, so the worker cannot drift into unrelated changes.
        """
        run_id = _utc_now_compact() + "-" + uuid.uuid4().hex[:6]
        return WorkerTaskPacket.create(
            project_root=str(self.project_root),
            run_id=run_id,
            task_id=fix_task.fix_id,
            title=f"Auto-repair: {fix_task.fix_description[:80]}",
            objective=fix_task.fix_description,
            allowed_files=[fix_task.target_file],
            protected_files=list(self._policy.protected_files),
            required_checks=[fix_task.verification],
            expected_evidence=["test_output.txt", "diff.patch"],
            risk_level="low",
            run_mode="controlled",
        )

    # ------------------------------------------------------------------
    # Phase 23 — Isolated Reviewer
    # ------------------------------------------------------------------

    def _build_reviewer_bundle(
        self,
        packet: WorkerTaskPacket,
        independent: IndependentEvidence | None = None,
    ) -> Any:
        """Build the single evidence view consumed by both reviewer layers."""
        from .reviewer import EvidenceBundle

        observed = packet.packet_root / "observed"
        aao_diff = observed / "aao_diff.patch"
        aao_test_output = observed / "aao_test_output.txt"
        diff_path = aao_diff if aao_diff.exists() else packet.packet_root / PacketFiles.DIFF
        test_output_path = (
            aao_test_output if aao_test_output.exists()
            else packet.packet_root / PacketFiles.TEST_OUTPUT
        )
        result_md_path = packet.packet_root / PacketFiles.RESULT

        diff_content = (
            diff_path.read_text(encoding="utf-8", errors="replace")
            if diff_path.exists() else ""
        )
        test_output = (
            test_output_path.read_text(encoding="utf-8", errors="replace")
            if test_output_path.exists() else ""
        )
        result_md = (
            result_md_path.read_text(encoding="utf-8", errors="replace")
            if result_md_path.exists() else ""
        )
        evidence_status = classify_worker_evidence_from_packet(
            packet,
            observed_changed_files=(
                independent.changed_files if independent is not None else None
            ),
        )
        return EvidenceBundle.from_packet(
            task_id=packet.task_id,
            step_id=packet.task_id,
            changed_files=evidence_status.changed_files,
            diff_content=diff_content,
            test_output=test_output,
            result_md=result_md,
            allowed_files=packet.allowed_files,
            denied_files=packet.denied_files,
            required_checks=packet.required_checks,
            worker_status=evidence_status.worker_status,
        )

    def _run_reviewer(
        self,
        packet: WorkerTaskPacket,
        independent: IndependentEvidence | None = None,
    ) -> list[ReviewFinding]:
        """Run the reviewer on a completed packet's observed evidence.

        Builds an EvidenceBundle from on-disk files (diff, test output,
        result.md) and runs the configured reviewer (default: RuleBasedReviewer).
        The reviewer receives a read-only snapshot — it cannot mutate the
        packet or write code.
        """
        from .reviewer import RuleBasedReviewer

        reviewer = self._reviewer or RuleBasedReviewer()
        return reviewer.review(self._build_reviewer_bundle(packet, independent))

    # ------------------------------------------------------------------
    # Phase 30 — Codex LLM Reviewer (Layer 2)
    # ------------------------------------------------------------------

    def _run_codex_reviewer(
        self,
        packet: WorkerTaskPacket,
        independent: IndependentEvidence | None = None,
    ) -> list[ReviewFinding]:
        """Run Codex CLI read-only sandbox reviewer on the packet evidence.

        Returns findings from the Codex review.  Returns empty list when
        Codex is unavailable or the review fails — the caller treats this
        as "no additional findings."
        """
        from .reviewer import CodexReviewer

        reviewer = CodexReviewer()
        return reviewer.review(self._build_reviewer_bundle(packet, independent))

    @staticmethod
    def _should_invoke_codex_reviewer(
        *,
        task_size: str = "medium",
        risk_level: str = "low",
        rule_findings: list[ReviewFinding] | None = None,
        repair_history: list[dict[str, Any]] | None = None,
        allowed_files: list[str] | None = None,
        changed_files: list[str] | None = None,
    ) -> bool:
        """Determine whether Layer 2 (Codex LLM) review is warranted.

        Layer 2 is additive to Layer 1 (RuleBasedReviewer) and is only
        triggered when the risk/cost trade-off justifies an extra LLM call.

        Always-trigger conditions:
          - task_size == "large"
          - risk_level == "high"

        Suspicious-signal triggers (independent of Layer 1):
          - allowed_files is empty but changed_files is non-empty
            (read-only milestone produced file changes — Layer 1 may
            have a blind spot, so Codex gets a direct look)
          - Layer 1 found ANY finding (rules fired — worth a second look)
          - Previous repair round failed then current one "passed"
        """
        import shutil
        if not shutil.which("codex"):
            return False

        # Always invoke for high-stakes work
        if task_size == "large" or risk_level == "high":
            return True

        # Read-only milestone with file changes — independent trigger
        # that does NOT depend on Layer 1 findings (defense in depth)
        if (allowed_files is not None and changed_files is not None
                and not allowed_files and changed_files):
            return True

        # Layer 1 found something — worth a semantic second opinion
        if rule_findings:
            return True

        # Repair history: failed then "passed" — suspicious
        if repair_history and len(repair_history) >= 2:
            recent = repair_history[-2:]
            if (
                recent[0].get("retest_result") == "failed"
                and recent[-1].get("retest_result") == "passed"
            ):
                return True

        return False

    # ------------------------------------------------------------------
    # LangGraph backend
    # ------------------------------------------------------------------

    def _execute_langgraph(
        self,
        plan: PlanContract,
        *,
        worker_mode: str = "fake",
        **kwargs,
    ) -> MainlineResult:
        """Execute an approved PlanContract via LangGraphRunner.

        Each step still goes through: worker dispatch → evidence collection
        → ControlPlane check.  LangGraphRunner provides the DAG execution
        structure (checkpoint, resume, branching); it does NOT replace
        ControlPlane or worker dispatch.

        If LangGraph is not installed, returns a blocked result with a
        clear dependency-missing message.
        """
        from .runners.langgraph_runner import LangGraphRunner, _LANGGRAPH_AVAILABLE

        if not _LANGGRAPH_AVAILABLE:
            return MainlineResult(
                plan_id=plan.plan_id,
                status="blocked_needs_review",
                worker_mode=worker_mode,
                worker_result={"behaviour": "blocked",
                               "summary": "LangGraph not installed"},
                control_decisions=[{
                    "action": "needs_human_review",
                    "passed": False,
                    "reason": "Orchestrated mode requires LangGraph. "
                             "Install with: pip install langgraph",
                }],
                summary="Blocked: LangGraph not installed — dependency missing",
            )

        cp = ControlPlane(policy=self._policy)
        runner = LangGraphRunner(project_root=str(self.project_root))

        # Build worker_registry — one dispatch callable per step.
        # Each callable bridges from graph state → _execute_worker(packet).
        # Keys must match plan.steps[i] (the node names LangGraphRunner uses),
        # not pwt.step_id (the machine identifier).
        run_id = _utc_now_compact() + "-" + uuid.uuid4().hex[:6]
        worker_registry: dict[str, Any] = {}

        if len(plan.planned_worker_tasks) != len(plan.steps):
            return MainlineResult(
                plan_id=plan.plan_id,
                status="blocked_needs_review",
                worker_mode=worker_mode,
                worker_result={
                    "behaviour": "blocked",
                    "summary": (
                        f"plan.steps ({len(plan.steps)}) and "
                        f"planned_worker_tasks ({len(plan.planned_worker_tasks)}) "
                        f"length mismatch — cannot build worker_registry"
                    ),
                },
                control_decisions=[{
                    "action": "needs_human_review",
                    "passed": False,
                    "reason": "PlanContract data inconsistency: steps/tasks length mismatch",
                }],
                summary="Blocked: plan steps and worker tasks arrays must be equal length",
            )

        for i, pwt in enumerate(plan.planned_worker_tasks):
            step_name = plan.steps[i]

            # Early-binding closure: capture pwt/run_id by parameter, not by
            # loop variable, to avoid the classic late-binding footgun.
            def _make_dispatch(task: Any, rid: str) -> Any:
                def _dispatch(_graph_state: dict) -> dict[str, Any]:
                    packet = self._task_to_packet(task, run_id=rid)
                    return self._execute_worker(packet, worker_mode=worker_mode)
                return _dispatch

            worker_registry[step_name] = _make_dispatch(pwt, run_id)

        lg_result = runner.run(
            plan=plan,
            control_plane=cp,
            policy=self._policy,
            project_root=self.project_root,
            worker_mode=worker_mode,
            worker_registry=worker_registry,
            **kwargs,
        )
        return self._convert_langgraph_result(lg_result, plan, worker_mode)

    # ------------------------------------------------------------------
    # Per-task packet builder (used by _execute_langgraph)
    # ------------------------------------------------------------------

    def _task_to_packet(
        self,
        task: Any,
        *,
        run_id: str = "",
    ) -> WorkerTaskPacket:
        """Build a WorkerTaskPacket for a single PlannedWorkerTask.

        This is the per-task equivalent of _plan_to_packet (which only
        handles the first task).  Used by the LangGraph backend to
        dispatch individual steps through the same _execute_worker path
        as the native backend.
        """
        policy_required = self._policy.get_required_checks()
        checks = list(getattr(task, "required_checks", []) or [])
        for c in policy_required:
            if c not in checks:
                checks.append(c)

        evidence = [
            e for e in (getattr(task, "expected_evidence", []) or [])
            if e not in ("result.md", "status.json")
        ]
        if not evidence:
            evidence = ["test_output.txt", "diff.patch"]

        risk = (getattr(task, "risk_level", None) or "medium")

        return WorkerTaskPacket.create(
            project_root=str(self.project_root),
            run_id=run_id,
            task_id=getattr(task, "step_id", "") or f"task-{run_id[:8]}",
            title=getattr(task, "title", "") or getattr(task, "objective", "")[:80],
            objective=getattr(task, "objective", ""),
            allowed_files=list(getattr(task, "allowed_files", []) or []),
            denied_files=list(getattr(task, "denied_files", []) or []),
            protected_files=list(self._policy.protected_files),
            required_checks=checks,
            expected_evidence=evidence,
            risk_level=risk,
            run_mode="orchestrated",
        )

    @staticmethod
    def _convert_langgraph_result(
        lg_result: Any,
        plan: PlanContract,
        worker_mode: str,
    ) -> MainlineResult:
        """Convert RunnerResult from LangGraphRunner into MainlineResult."""
        return MainlineResult(
            run_id=getattr(lg_result, "run_id", ""),
            task_id=getattr(plan, "plan_id", ""),
            plan_id=plan.plan_id,
            status={
                "completed": "completed",
                "needs_human_review": "blocked_needs_review",
                "failed": "blocked_failed",
                "timed_out": "blocked_failed",
            }.get(getattr(lg_result, "status", "unknown"), "unknown"),
            worker_mode=worker_mode,
            evidence_status={
                "passed_steps": getattr(lg_result, "steps_completed", 0),
                "step_count": len(getattr(plan, "steps", [])),
            },
            control_decisions=getattr(lg_result, "control_events", []),
            report_path=getattr(lg_result, "report_path", "") or "",
            evidence_path=(
                "; ".join(str(p) for p in getattr(lg_result, "evidence_paths", []))
            ),
            summary=getattr(lg_result, "reason", ""),
        )

    # ------------------------------------------------------------------
    # Plan → Packet conversion
    # ------------------------------------------------------------------

    def _plan_to_packet(
        self,
        plan: PlanContract,
        *,
        run_id: str = "",
        task_id: str = "",
    ) -> WorkerTaskPacket:
        """Convert a PlanContract to a WorkerTaskPacket, using policy for boundaries."""

        policy = self._policy

        # Gather file boundaries from planned_worker_tasks or extract from steps.
        # IMPORTANT: planned_worker_tasks may INTENTIONALLY set allowed_files=[]
        # to signal a read-only milestone.  The fallback extraction must only
        # run when there are NO planned_worker_tasks — never when the list is
        # present but empty.
        allowed_files: list[str] = []
        denied_files: list[str] = []
        required_checks: list[str] = []
        expected_evidence: list[str] = list(plan.required_evidence)

        has_explicit_tasks = bool(plan.planned_worker_tasks)
        explicit_read_only = False

        if has_explicit_tasks:
            pwt = plan.planned_worker_tasks[0]
            allowed_files = list(pwt.allowed_files)
            denied_files = list(pwt.denied_files)
            required_checks = list(pwt.required_checks)
            if pwt.expected_evidence:
                expected_evidence = list(pwt.expected_evidence)
            explicit_read_only = (
                not pwt.allowed_files
                and not pwt.required_checks
                and not pwt.expected_evidence
            )

        # Fallback: only when no planned_worker_tasks exist.
        # When planned_worker_tasks IS present, allowed_files=[] is a
        # deliberate read-only signal — do NOT overwrite it.
        if not has_explicit_tasks:
            if not allowed_files:
                allowed_files = self._extract_files_from_plan(plan)
            if not required_checks:
                required_checks = self._infer_required_checks(plan)
        if not expected_evidence and not explicit_read_only:
            expected_evidence = ["test_output.txt", "diff.patch"]

        # Policy-driven: protected files from the loaded policy, not hardcoded
        protected_files = list(policy.protected_files)
        # Policy-driven: required checks from policy
        policy_checks = policy.get_required_checks()
        if not explicit_read_only:
            for check in policy_checks:
                if check not in required_checks:
                    required_checks.append(check)

        # Filter out standard packet outputs — these live at the packet root
        # and are verified via load_worker_status/load_worker_result_text, not
        # the observed/ evidence classifier.
        expected_evidence = [
            e for e in expected_evidence
            if e not in ("result.md", "status.json")
        ]
        if not expected_evidence and not explicit_read_only:
            expected_evidence = ["test_output.txt", "diff.patch"]

        risk_level = "high" if plan.human_review_gates else "medium"

        return WorkerTaskPacket.create(
            project_root=str(self.project_root),
            run_id=run_id,
            task_id=task_id,
            title=plan.objective[:80] if plan.objective else "AAO task",
            objective=plan.objective,
            worker_kind="claude_code",
            allowed_files=allowed_files,
            denied_files=denied_files,
            protected_files=protected_files,
            required_checks=required_checks,
            expected_evidence=expected_evidence,
            risk_level=risk_level,
            run_mode=plan.run_mode,
        )

    # ------------------------------------------------------------------
    # Worker execution
    # ------------------------------------------------------------------

    def _execute_worker(
        self,
        packet: WorkerTaskPacket,
        *,
        worker_mode: str = "fake",
    ) -> dict[str, Any]:
        """Execute the worker and return its result dict."""
        if worker_mode == "fake":
            return self._execute_fake_worker(packet)
        elif worker_mode == "packet":
            return self._execute_packet_worker(packet)
        elif worker_mode == "claude-code":
            return self._execute_claude_code_worker(packet)
        else:
            raise ValueError(f"Unknown worker_mode: {worker_mode!r}")

    def _execute_fake_worker(self, packet: WorkerTaskPacket) -> dict[str, Any]:
        """Run the deterministic fake worker."""
        from .workers.fake_worker import run_fake_worker

        return run_fake_worker(packet, packet_dir=packet.packet_root)

    def _execute_packet_worker(self, packet: WorkerTaskPacket) -> dict[str, Any]:
        """Write the packet to disk for an external worker to pick up."""
        pdir = packet.write()
        return {
            "run_id": packet.run_id,
            "task_id": packet.task_id,
            "packet_dir": str(pdir),
            "behaviour": "packet",
            "worker_status": "pending_external",
            "changed_files": [],
            "summary": "Packet written to disk — awaiting external worker execution",
            "observed_paths": [],
        }

    def _resolve_claude_code_cli(self) -> str | None:
        """Resolve the Claude Code CLI path, preferring native Linux binary.

        On WSL, Windows npm shims shadow the native Linux binary because
        WSL interop appends the Windows PATH.  We explicitly try native
        paths first so the Linux binary wins.
        """
        import shutil

        candidates: list[str] = []
        # 1. Native Linux npm-global (common for npm install -g)
        candidates.append(
            str(Path.home() / ".npm-global" / "bin" / "claude")
        )
        # 2. Standard Linux npm global
        candidates.append("/usr/local/bin/claude")
        # 3. Fallback: whatever shutil.which finds
        system = shutil.which("claude")
        if system:
            candidates.append(system)

        for c in candidates:
            if Path(c).is_file():
                return c
        return None

    def _execute_claude_code_worker(self, packet: WorkerTaskPacket) -> dict[str, Any]:
        """Launch a real Claude Code subprocess as the worker."""
        claude_cli = self._resolve_claude_code_cli()

        from .workers.claude_code import (
            ClaudeCodeWorkerConfig,
            run_claude_code_doctor,
            run_claude_code_worker,
        )

        config = ClaudeCodeWorkerConfig.from_env(
            project_root=str(self.project_root),
        )
        if claude_cli is not None:
            config.command = claude_cli  # force native Linux CLI path
        if config.doctor_enabled:
            doctor = run_claude_code_doctor(packet, config=config)
            if not doctor.ok:
                return {
                    "run_id": packet.run_id,
                    "task_id": packet.task_id,
                    "packet_dir": str(packet.packet_root),
                    "behaviour": "claude-code",
                    "exit_code": doctor.exit_code,
                    "timed_out": doctor.timed_out,
                    "worker_status": "infrastructure_error",
                    "changed_files": [],
                    "summary": "Claude Code Worker Doctor failed",
                    "error": doctor.error,
                    "observed_paths": doctor.observed_paths,
                    "stdout_path": doctor.stdout_path,
                    "stderr_path": doctor.stderr_path,
                    "transcript_path": doctor.report_path,
                    "result_md_path": "",
                    "status_json_path": "",
                    "command": doctor.command,
                    "timeout": config.doctor_timeout_seconds,
                    "doctor_report_path": doctor.report_path,
                    "doctor_env_snapshot": doctor.env_snapshot,
                }
        elif claude_cli is None and config.command == "claude":
            return {
                "run_id": _new_run_id(),
                "task_id": packet.task_id,
                "packet_dir": str(packet.packet_root),
                "behaviour": "claude-code",
                "exit_code": -1,
                "timed_out": False,
                "worker_status": "infrastructure_error",
                "changed_files": [],
                "summary": "",
                "error": "Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
                "observed_paths": [],
                "stdout_path": "",
                "stderr_path": "",
                "transcript_path": "",
                "result_md_path": "",
                "status_json_path": "",
                "command": "claude (not found)",
            }
        result = run_claude_code_worker(packet, config=config)

        return {
            "run_id": result.run_id,
            "task_id": result.task_id,
            "packet_dir": result.packet_dir,
            "behaviour": "claude-code",
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "worker_status": result.worker_status,
            "changed_files": result.changed_files,
            "summary": result.summary,
            "error": result.error,
            "observed_paths": result.observed_paths,
            "stdout_path": result.stdout_path,
            "stderr_path": result.stderr_path,
            "transcript_path": result.transcript_path,
            "result_md_path": result.result_md_path,
            "status_json_path": result.status_json_path,
            "command": result.command,
        }

    # ------------------------------------------------------------------
    # Worker infrastructure checking (Phase 18)
    # ------------------------------------------------------------------

    def _check_worker_infrastructure(
        self,
        worker_result: dict[str, Any],
    ) -> list[ControlDecision]:
        """Detect worker-launch failures: command not found, timeout, etc."""
        decisions: list[ControlDecision] = []

        error = worker_result.get("error", "")
        exit_code = worker_result.get("exit_code", 0)
        timed_out = worker_result.get("timed_out", False)

        if timed_out:
            decisions.append(ControlDecision(
                passed=False,
                action="fail",
                reason=f"Worker timed out after {worker_result.get('timeout', 'unknown')}",
                severity="high",
                failure_category="worker_timeout",
                failure_origin="worker",
                recovery_hint="retry_with_backoff",
            ))
        elif error:
            decisions.append(ControlDecision(
                passed=False,
                action="fail",
                reason=f"Worker infrastructure failure: {error}",
                severity="high",
                failure_category="worker_infrastructure",
                failure_origin="worker",
                recovery_hint="fail",
            ))
        elif exit_code != 0:
            decisions.append(ControlDecision(
                passed=False,
                action="needs_human_review",
                reason=f"Worker exited with code {exit_code}",
                severity="medium",
                failure_category="worker_error",
                failure_origin="worker",
                recovery_hint="needs_human_review",
            ))

        return decisions

    # ------------------------------------------------------------------
    # File boundary enforcement
    # ------------------------------------------------------------------

    @staticmethod
    def _check_file_boundary(
        *,
        changed_files: list[str],
        allowed_files: list[str],
        worker_mode: str = "fake",
    ) -> ControlDecision | None:
        """Detect worker file modifications outside the plan's file boundaries.

        Two enforcement modes:

        1. **Read-only** (allowed_files is empty): ANY changed_files is a
           violation — the milestone must not modify any files.  Enforced
           for ALL worker modes.

        2. **Bounded** (allowed_files has entries): every changed file must
           fall within at least one allowed prefix/glob pattern.  Only
           enforced for non-fake workers — fake workers generate synthetic
           changed_files that don't reflect real file modifications.
        """
        if not changed_files:
            return None

        if not allowed_files:
            # Read-only milestone — no files may be modified
            return ControlDecision(
                passed=False,
                action="needs_human_review",
                reason=(
                    "Milestone is read-only (allowed_files=[]) but worker "
                    f"modified files: {', '.join(changed_files)}"
                ),
                severity="high",
                failure_category="policy_error",
                failure_origin="control_plane",
                recovery_hint="needs_human_review",
            )

        # Bounded enforcement only for real workers.
        # Fake-worker changed_files are synthetic test artifacts and don't
        # represent actual file modifications — checking them against the
        # allowlist produces false positives.
        if worker_mode == "fake":
            return None

        # Bounded milestone — verify every changed file is within scope
        out_of_bounds: list[str] = []
        for f in changed_files:
            if not any(_path_within_prefix(f, prefix) for prefix in allowed_files):
                out_of_bounds.append(f)

        if out_of_bounds:
            return ControlDecision(
                passed=False,
                action="needs_human_review",
                reason=(
                    f"Worker modified files outside allowed_files: "
                    f"{', '.join(out_of_bounds)}"
                ),
                severity="high",
                failure_category="policy_error",
                failure_origin="control_plane",
                recovery_hint="needs_human_review",
            )

        return None

    # ------------------------------------------------------------------
    # Test result checking (P1.2)
    # ------------------------------------------------------------------

    _TEST_FAILURE_RE = re.compile(r"(\d+)\s+failed", re.IGNORECASE)
    _TEST_FAILED_LINE = re.compile(r"\bFAILED\b")

    def _check_required_check_policy(
        self, packet: WorkerTaskPacket
    ) -> list[ControlDecision]:
        """Block unsafe or unsupported validation commands before real execution."""
        rejected = rejected_required_checks(packet.required_checks)
        if not rejected:
            return []
        details = "; ".join(f"{cmd!r}: {reason}" for cmd, reason in rejected)
        return [ControlDecision(
            passed=False,
            action="needs_human_review",
            reason=f"Unsafe required_checks blocked before worker launch: {details}",
            severity="high",
            failure_category=FailureCategory.POLICY_ERROR.value,
            failure_origin="control_plane",
            recovery_hint="needs_human_review",
        )]

    @staticmethod
    def _check_baseline_integrity(
        independent: IndependentEvidence,
    ) -> list[ControlDecision]:
        """Block a real worker that mutates git staging/history during its task."""
        if not independent.baseline_violations:
            return []
        return [ControlDecision(
            passed=False,
            action="needs_human_review",
            reason="; ".join(independent.baseline_violations),
            severity="high",
            failure_category=FailureCategory.POLICY_ERROR.value,
            failure_origin="worker",
            recovery_hint="needs_human_review",
        )]

    @staticmethod
    def _missing_git_baseline_decision() -> ControlDecision:
        """Real controlled execution needs a git baseline for trustworthy attribution."""
        return ControlDecision(
            passed=False,
            action="needs_human_review",
            reason=(
                "Independent evidence unavailable: real claude-code execution "
                "requires a git worktree so AAO can capture a pre-worker baseline"
            ),
            severity="high",
            failure_category=FailureCategory.POLICY_ERROR.value,
            failure_origin="control_plane",
            recovery_hint="needs_human_review",
        )

    def _check_independent_results(
        self, independent: IndependentEvidence
    ) -> list[ControlDecision]:
        """Decide on required-check outcomes AAO ran itself (real exit codes).

        Unlike :meth:`_check_test_results`, this trusts process exit codes, not
        a worker-written text file — so a worker that claims success cannot pass
        when its checks actually fail.
        """
        rejected = [check for check in independent.checks if check.rejected]
        if rejected:
            names = "; ".join(c.command for c in rejected)
            return [ControlDecision(
                passed=False,
                action="needs_human_review",
                reason=f"AAO refused unsafe required check(s): {names}",
                severity="high",
                failure_category=FailureCategory.POLICY_ERROR.value,
                failure_origin="control_plane",
                recovery_hint="needs_human_review",
            )]
        failed = independent.failed_checks
        if not failed:
            return [ControlDecision(
                passed=True, action="continue",
                reason=f"AAO ran {len(independent.checks)} required check(s); all passed",
            )]
        names = "; ".join(c.command for c in failed)
        return [ControlDecision(
            passed=False,
            action="retry",
            reason=f"AAO independently ran required checks; {len(failed)} failed: {names}",
            severity="medium",
            failure_category=FailureCategory.TASK_QUALITY_ERROR.value,
            failure_origin="worker",
            recovery_hint="retry",
        )]

    def _check_test_results(self, packet: WorkerTaskPacket) -> list[ControlDecision]:
        """Parse test_output.txt for failures. Returns blocking decision if found."""
        decisions: list[ControlDecision] = []

        test_output_path = packet.packet_root / PacketFiles.TEST_OUTPUT
        if not test_output_path.exists():
            return decisions

        content = test_output_path.read_text(encoding="utf-8", errors="replace")

        # Check for FAILED lines
        if self._TEST_FAILED_LINE.search(content):
            # Count failures
            match = self._TEST_FAILURE_RE.search(content)
            failed_count = int(match.group(1)) if match else 1
            decisions.append(ControlDecision(
                passed=False,
                action="retry",
                reason=f"Test failure detected: {failed_count} test(s) failed",
                severity="medium",
                failure_category="task_quality_error",
                failure_origin="worker",
                recovery_hint="retry",
            ))
        else:
            decisions.append(ControlDecision(
                passed=True,
                action="continue",
                reason="Test output verified — no failures detected",
            ))

        return decisions

    # ------------------------------------------------------------------
    # Control checks
    # ------------------------------------------------------------------

    def _run_control_checks(
        self,
        packet: WorkerTaskPacket,
        evidence_status: WorkerEvidenceStatus,
        worker_result: dict[str, Any],
        *,
        worker_mode: str = "fake",
    ) -> list[ControlDecision]:
        """Run all relevant ControlPlane checks using the loaded policy."""
        cp = ControlPlane(policy=self._policy)
        decisions: list[ControlDecision] = []

        # 1. Worker evidence verification
        evidence_decision = cp.verify_worker_evidence(evidence_status)
        decisions.append(evidence_decision)

        # 2. Policy check for file changes (uses loaded policy with protected files)
        changed_files = evidence_status.changed_files
        if changed_files:
            policy_decision = cp.check_policy_for_file_changes(files_changed=changed_files)
            decisions.append(policy_decision)

            # 2b. Boundary check — worker must not modify files outside the
            #     plan's allowed_files.  A plan with allowed_files=[] means
            #     "read only" and any file change is a violation.
            boundary_decision = self._check_file_boundary(
                changed_files=changed_files,
                allowed_files=packet.allowed_files,
                worker_mode=worker_mode,
            )
            if boundary_decision is not None:
                decisions.append(boundary_decision)

        # 3. Output guardrail check (against result text)
        result_text = evidence_status.reported_summary
        if result_text:
            guard_decision = cp.guard_output(
                agent_name="mainline_worker",
                payload={"output": result_text, "changed_files": changed_files},
            )
            decisions.append(guard_decision)

        return decisions

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _generate_report(
        self,
        *,
        plan: PlanContract,
        packet: WorkerTaskPacket,
        worker_result: dict[str, Any],
        evidence_status: WorkerEvidenceStatus,
        control_decisions: list[ControlDecision],
    ) -> tuple[Path, Path]:
        """Generate audit report and evidence pack. Returns (report_path, evidence_path)."""
        output_dir = self.project_root / "outputs"
        report_dir = output_dir / "reports"
        evidence_dir = output_dir / "evidence"
        report_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        task_id = packet.task_id

        # Evidence pack
        evidence_data = {
            "task_id": task_id,
            "plan_id": plan.plan_id,
            "evidence_status": _evidence_status_to_dict(evidence_status),
            "observed_files": list_observed_files(packet.packet_root),
            "worker_result_summary": worker_result.get("summary", ""),
            "changed_files": evidence_status.changed_files,
        }
        evidence_path = evidence_dir / f"{task_id}.json"
        evidence_path.write_text(
            json.dumps(evidence_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Audit report
        report_data = {
            "report_type": "mainline_audit",
            "generated_at": _utc_now_iso(),
            "task_id": task_id,
            "plan_id": plan.plan_id,
            "objective": plan.objective,
            "worker_mode": worker_result.get("behaviour", "unknown"),
            "execution_summary": {
                "status": worker_result.get("worker_status", "unknown"),
                "changed_files": evidence_status.changed_files,
                "denied_files_changed": evidence_status.denied_files_changed,
                "has_missing_evidence": evidence_status.has_missing_required,
                "summary": worker_result.get("summary", ""),
            },
            "control_decisions": [_decision_to_dict(d) for d in control_decisions],
            "evidence_summary": {
                "total_items": len(evidence_status.items),
                "observed": sum(1 for i in evidence_status.items if i.status == "observed"),
                "reported": sum(1 for i in evidence_status.items if i.status == "reported"),
                "missing": sum(1 for i in evidence_status.items if i.status == "missing"),
            },
            "plan_snapshot": plan_contract_to_dict(plan),
            "artifact_summary": {
                "report_path": str(report_dir / f"{task_id}.json"),
                "evidence_path": str(evidence_path),
                "worker_packet_path": str(packet.packet_root),
            },
        }
        report_path = report_dir / f"{task_id}.json"
        report_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return report_path, evidence_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _determine_status(
        self,
        control_decisions: list[ControlDecision],
        evidence_status: WorkerEvidenceStatus,
    ) -> str:
        """Determine the overall execution status from control decisions."""
        blocked = [d for d in control_decisions if not d.passed]
        if blocked:
            actions = {d.action for d in blocked}
            if "needs_human_review" in actions:
                return "blocked_needs_review"
            if "fail" in actions:
                return "blocked_failed"
            return "blocked"
        if evidence_status.has_missing_required:
            return "completed_no_evidence"
        return "completed"

    def _build_summary(
        self,
        status: str,
        control_decisions: list[ControlDecision],
        evidence_status: WorkerEvidenceStatus,
    ) -> str:
        """Build a human-readable summary."""
        parts = [f"Mainline execution: {status}"]
        observed = sum(1 for i in evidence_status.items if i.status == "observed")
        missing = sum(1 for i in evidence_status.items if i.status == "missing")
        parts.append(
            f"Evidence: {observed} observed, {missing} missing, "
            f"{len(evidence_status.changed_files)} files changed"
        )
        blocked = [d for d in control_decisions if not d.passed]
        for d in blocked:
            parts.append(f"Block: [{d.action}] {d.reason}")
        return " | ".join(parts)

    def _extract_files_from_plan(self, plan: PlanContract) -> list[str]:
        """Extract file references from plan objective and steps."""
        combined = plan.objective + " " + " ".join(plan.steps)
        pattern = re.compile(r"`([^`]+\.[a-zA-Z0-9]+)`|([\w\-/]+\.[a-z]{1,10})")
        seen: set[str] = set()
        for match in pattern.finditer(combined):
            for g in match.groups():
                if g and len(g) > 2 and "." in g:
                    seen.add(g)
        return sorted(seen)

    def _infer_required_checks(self, plan: PlanContract) -> list[str]:
        """Infer required checks from plan content."""
        combined = " ".join(plan.steps + [plan.objective]).lower()
        checks: list[str] = []
        if any(w in combined for w in ("test", "pytest", "测试")):
            checks.append("python -m pytest")
        if any(w in combined for w in ("lint", "type", "mypy", "flake8")):
            checks.append("python -m ruff check")
        return checks

    # ------------------------------------------------------------------
    # Human Review persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _review_dir() -> Path:
        """Directory for persisted review states."""
        d = Path.cwd() / "outputs" / "reviews"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _persist_review_state(
        self,
        *,
        run_id: str,
        task_id: str,
        plan: PlanContract,
        worker_mode: str,
        max_workers: int,
        packet: WorkerTaskPacket,
        result_status: str,
    ) -> None:
        """Save blocked task state so it can be listed and resumed later."""
        review_state = {
            "run_id": run_id,
            "task_id": task_id,
            "plan_id": plan.plan_id,
            "plan": plan_contract_to_dict(plan),
            "worker_mode": worker_mode,
            "max_workers": max_workers,
            "worker_packet_path": str(packet.packet_root),
            "status": result_status,
            "created_at": _utc_now_iso(),
        }
        review_path = self._review_dir() / f"{task_id}.json"
        review_path.write_text(
            json.dumps(review_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def list_reviews(cls) -> list[dict[str, Any]]:
        """List all pending human review tasks."""
        reviews: list[dict[str, Any]] = []
        review_dir = cls._review_dir()
        if not review_dir.exists():
            return reviews
        for path in sorted(review_dir.glob("*.json")):
            try:
                reviews.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError):
                pass
        return reviews

    @classmethod
    def resume_from_review(
        cls,
        task_id: str,
        *,
        decision: str,
        reason: str = "",
        worker_mode_override: str | None = None,
    ) -> MainlineResult | None:
        """Resume a blocked human review task.

        Args:
            task_id: The task ID from the blocked result.
            decision: "approve" or "reject".
            reason: Optional human review reason.
            worker_mode_override: Override the worker mode (e.g. for testing).

        Returns:
            MainlineResult if resumed, None if task not found.
        """
        review_path = cls._review_dir() / f"{task_id}.json"
        if not review_path.exists():
            return None

        review_state = json.loads(review_path.read_text(encoding="utf-8"))

        if decision == "reject":
            return MainlineResult(
                run_id=review_state.get("run_id", ""),
                task_id=task_id,
                plan_id=review_state.get("plan_id", ""),
                status="blocked_rejected",
                worker_mode=review_state.get("worker_mode", "fake"),
                worker_result={
                    "behaviour": "human_rejected",
                    "summary": f"Human rejected: {reason}" if reason else "Human rejected",
                },
                control_decisions=[{
                    "action": "needs_human_review",
                    "passed": False,
                    "reason": f"Human rejected: {reason}" if reason else "Human rejected",
                }],
                summary=f"Blocked: human rejected ({reason})" if reason else "Blocked: human rejected",
            )

        # Reconstruct PlanContract from persisted state
        plan_dict = review_state.get("plan", {})
        plan = PlanContract(
            objective=plan_dict.get("objective", ""),
            steps=plan_dict.get("steps", []),
            planned_worker_tasks=[
                PlannedWorkerTask(
                    step_id=wt.get("step_id", f"step-{i}"),
                    title=wt.get("title", ""),
                    objective=wt.get("objective", ""),
                    allowed_files=wt.get("allowed_files", []),
                    denied_files=wt.get("denied_files", []),
                    required_checks=wt.get("required_checks", []),
                    expected_evidence=wt.get("expected_evidence", []),
                    risk_level=wt.get("risk_level", "low"),
                    dependencies=wt.get("dependencies", []),
                    can_run_parallel=wt.get("can_run_parallel", False),
                )
                for i, wt in enumerate(plan_dict.get("planned_worker_tasks", []))
            ],
            plan_id=review_state.get("plan_id", task_id),
            planning_mode=plan_dict.get("planning_mode", "deterministic"),
            blocking_concerns=plan_dict.get("blocking_concerns", []),
        )
        # Add human decision into blocking concerns so the control chain knows
        plan.blocking_concerns = [
            bc for bc in plan.blocking_concerns
            if not bc.startswith("HUMAN_OVERRIDE:")
        ]
        if reason:
            plan.blocking_concerns.append(f"HUMAN_OVERRIDE: approved by human review — {reason}")

        # Must re-approve
        plan.approval_status = "approved"

        worker_mode = worker_mode_override or review_state.get("worker_mode", "fake")
        max_workers = review_state.get("max_workers", 2)

        # Clean up the review file
        review_path.unlink(missing_ok=True)

        executor = cls()
        return executor.execute(plan, worker_mode=worker_mode, max_workers=max_workers)


# =============================================================================
# Helpers
# =============================================================================


def _load_yaml_policy(path: Path) -> dict[str, Any]:
    """Load a YAML policy file, returning empty dict on failure."""
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _evidence_status_to_dict(es: WorkerEvidenceStatus) -> dict[str, Any]:
    return {
        "task_id": es.task_id,
        "worker_kind": es.worker_kind,
        "worker_status": es.worker_status,
        "items": [
            {"key": i.key, "status": i.status, "path": i.path, "description": i.description}
            for i in es.items
        ],
        "reported_summary": es.reported_summary[:300] if es.reported_summary else "",
        "changed_files": es.changed_files,
        "denied_files_changed": es.denied_files_changed,
        "has_missing_required": es.has_missing_required,
        "is_malformed": es.is_malformed,
    }


def _path_within_prefix(path: str, prefix: str) -> bool:
    """Return True if *path* falls within the directory/file scope of *prefix*.

    Handles both exact matches and glob-style ``dir/**`` patterns.
    """
    # Normalize separators
    p = path.replace("\\", "/").rstrip("/")
    pre = prefix.replace("\\", "/").rstrip("/")

    # Exact file match
    if p == pre:
        return True

    # Glob match: "dir/**" means everything under dir/
    if pre.endswith("/**"):
        base = pre[:-3].rstrip("/") + "/"
        return p.startswith(base)

    # Directory prefix match: "dir/" means everything under dir/
    if pre.endswith("/"):
        return p.startswith(pre)

    # Partial path match (less common but valid)
    return p.startswith(pre + "/") or p.startswith(pre + ".")


def _decision_to_dict(d: ControlDecision) -> dict[str, Any]:
    return {
        "action": d.action,
        "passed": d.passed,
        "reason": d.reason,
        "severity": d.severity,
        "failure_category": d.failure_category,
        "failure_origin": d.failure_origin,
        "recovery_hint": d.recovery_hint,
        "evidence_required": d.evidence_required,
    }
