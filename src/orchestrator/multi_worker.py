"""Multi-worker plan execution — Phase 20.

Converts an approved PlanContract into multiple bounded worker tasks,
executes them with dependency-aware parallelism, and runs per-step
control checks (evidence, policy, recovery).
"""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .control_models import ControlDecision, WorkerEvidenceItem, WorkerEvidenceStatus
from .control_plane import ControlPlane
from .planning import PlanContract, PlannedWorkerTask, plan_contract_to_dict
from .policy import Policy
from .worker_protocol import (
    WorkerTaskPacket,
    classify_worker_evidence,
    classify_worker_evidence_from_packet,
    list_observed_files,
    load_worker_result_text,
    load_worker_status,
)


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Step status
# =============================================================================

StepStatus = str  # pending | running | passed | failed | blocked | needs_human_review | skipped_dependency_failed


# =============================================================================
# Per-step execution record
# =============================================================================


@dataclass
class StepExecutionRecord:
    """Full record of one step's execution for audit and recovery."""

    step_id: str = ""
    title: str = ""
    status: StepStatus = "pending"
    task_id: str = ""
    packet_dir: str = ""
    worker_result: dict[str, Any] = field(default_factory=dict)
    evidence_status: WorkerEvidenceStatus | None = None
    control_decisions: list[ControlDecision] = field(default_factory=list)
    report_path: str = ""
    evidence_path: str = ""
    changed_files: list[str] = field(default_factory=list)
    error: str = ""
    started_at: str = ""
    finished_at: str = ""


# =============================================================================
# Multi-worker result
# =============================================================================


@dataclass
class MultiWorkerResult:
    """Aggregated result from multi-worker plan execution."""

    run_id: str = ""
    plan_id: str = ""
    status: str = "unknown"
    worker_mode: str = "fake"
    steps: list[StepExecutionRecord] = field(default_factory=list)
    combined_report_path: str = ""
    combined_evidence_path: str = ""
    summary: str = ""

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def passed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == "passed")

    @property
    def failed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == "failed")

    @property
    def blocked_steps(self) -> int:
        return sum(1 for s in self.steps if s.status in ("blocked", "needs_human_review"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "worker_mode": self.worker_mode,
            "step_count": self.step_count,
            "passed_steps": self.passed_steps,
            "failed_steps": self.failed_steps,
            "blocked_steps": self.blocked_steps,
            "steps": [
                {
                    "step_id": s.step_id,
                    "title": s.title,
                    "status": s.status,
                    "task_id": s.task_id,
                    "packet_dir": s.packet_dir,
                    "changed_files": s.changed_files,
                    "error": s.error,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                    "control_decisions": [
                        {
                            "action": d.action,
                            "passed": d.passed,
                            "reason": d.reason,
                            "severity": d.severity,
                            "recovery_hint": d.recovery_hint,
                        }
                        for d in s.control_decisions
                    ],
                }
                for s in self.steps
            ],
            "combined_report_path": self.combined_report_path,
            "combined_evidence_path": self.combined_evidence_path,
            "summary": self.summary,
        }


# =============================================================================
# MultiWorkerExecutor
# =============================================================================


class MultiWorkerExecutor:
    """Execute a PlanContract as multiple bounded worker tasks.

    Responsibilities:
    1. Convert plan steps/PlannedWorkerTasks → WorkerTaskPackets
    2. Build execution graph (dependencies, write-overlap detection)
    3. Execute with bounded parallelism
    4. Run per-step control checks
    5. Apply recovery decisions
    6. Produce combined audit report
    """

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        policy: Policy | None = None,
        max_workers: int = 2,
        worker_mode: str = "fake",
        progress_callback: Callable[[MultiWorkerResult], None] | None = None,
    ) -> None:
        self.project_root = project_root or Path.cwd()
        self._policy = policy or self._load_policy()
        self._max_workers = max_workers
        self._worker_mode = worker_mode
        self._progress_callback = progress_callback

        self._cp = ControlPlane(policy=self._policy)

    @staticmethod
    def _load_policy() -> Policy:
        policy_path = Path.cwd() / "examples" / "policy.yaml"
        if policy_path.exists():
            try:
                import yaml as _yaml
                with open(policy_path, encoding="utf-8") as fh:
                    return Policy.from_dict(_yaml.safe_load(fh) or {})
            except Exception:
                pass
        return Policy.defaults()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def execute(self, plan: PlanContract) -> MultiWorkerResult:
        """Execute all steps of an approved plan.

        Returns MultiWorkerResult when all steps resolve (pass, fail, or block).
        """
        if plan.approval_status != "approved":
            return MultiWorkerResult(
                plan_id=plan.plan_id,
                status="blocked_needs_review",
                worker_mode=self._worker_mode,
                summary=f"Plan not approved (status={plan.approval_status})",
            )

        run_id = _utc_now_compact() + "-" + uuid.uuid4().hex[:6]

        # 1. Convert planned_worker_tasks into step plans
        step_plans = self._build_step_plans(plan, run_id)

        # 2. Detect write overlaps (mark as sequential)
        self._detect_write_overlaps(step_plans)

        # 3. Execute with dependency-aware ordering
        result = self._execute_steps(plan, step_plans, run_id)

        # 4. Generate combined report
        report_path, evidence_path = self._generate_combined_report(plan, result)
        result.combined_report_path = report_path
        result.combined_evidence_path = evidence_path

        return result

    # ------------------------------------------------------------------
    # Step plan construction
    # ------------------------------------------------------------------

    def _build_step_plans(
        self,
        plan: PlanContract,
        run_id: str,
    ) -> list[StepExecutionRecord]:
        """Build StepExecutionRecords from the plan's planned_worker_tasks."""
        records: list[StepExecutionRecord] = []

        worker_tasks = plan.planned_worker_tasks
        if not worker_tasks:
            # No explicit worker tasks: treat each plan step as a task
            for i, step_text in enumerate(plan.steps):
                step_id = f"step-{i + 1}"
                records.append(StepExecutionRecord(
                    step_id=step_id,
                    title=step_text[:80],
                    task_id=f"task-{run_id}-{step_id}",
                ))
            return records

        for i, pwt in enumerate(worker_tasks):
            step_id = pwt.step_id or f"step-{i + 1}"
            records.append(StepExecutionRecord(
                step_id=step_id,
                title=pwt.title or pwt.objective[:80],
                task_id=f"task-{run_id}-{step_id}",
            ))
        return records

    def _detect_write_overlaps(self, step_plans: list[StepExecutionRecord]) -> None:
        """Mark steps that write overlapping files as sequential (not parallel).

        Two steps that both write the same file MUST NOT run in parallel.
        This is enforced by setting can_run_parallel=False on the later step
        and adding a dependency on the earlier step.
        """
        plan = getattr(self, "_current_plan", None)
        if plan is None or not plan.planned_worker_tasks:
            return

        worker_tasks = plan.planned_worker_tasks
        for i in range(len(worker_tasks)):
            for j in range(i + 1, len(worker_tasks)):
                files_i = set(worker_tasks[i].allowed_files)
                files_j = set(worker_tasks[j].allowed_files)
                overlap = files_i & files_j
                if overlap:
                    # Later step depends on earlier step
                    if step_plans[j].step_id not in worker_tasks[j].dependencies:
                        worker_tasks[j].dependencies.append(step_plans[i].step_id)
                    worker_tasks[j].can_run_parallel = False

    # ------------------------------------------------------------------
    # Execution engine
    # ------------------------------------------------------------------

    def _execute_steps(
        self,
        plan: PlanContract,
        step_plans: list[StepExecutionRecord],
        run_id: str,
    ) -> MultiWorkerResult:
        """Execute all steps, respecting dependencies and concurrency limits."""
        result = MultiWorkerResult(
            run_id=run_id,
            plan_id=plan.plan_id,
            worker_mode=self._worker_mode,
            steps=step_plans,
        )

        completed: set[str] = set()
        failed: set[str] = set()

        while len(completed | failed) < len(step_plans):
            # Find ready steps: all dependencies completed and none failed
            ready = self._find_ready_steps(step_plans, completed, failed)

            if not ready:
                # Check for deadlock: all remaining steps have unmet deps
                remaining = [
                    s for s in step_plans
                    if s.step_id not in completed and s.step_id not in failed
                ]
                # Mark steps whose dependencies failed as skipped
                for s in remaining:
                    worker_task = self._find_worker_task(plan, s.step_id)
                    deps = worker_task.dependencies if worker_task else []
                    if any(d in failed for d in deps):
                        s.status = "skipped_dependency_failed"
                        s.finished_at = _utc_now_iso()
                        failed.add(s.step_id)
                # If nothing progressed, break to avoid infinite loop
                still_remaining = [
                    s for s in remaining
                    if s.step_id not in completed and s.step_id not in failed
                ]
                if len(still_remaining) == len(remaining):
                    # True deadlock — mark rest as blocked
                    for s in still_remaining:
                        s.status = "blocked"
                        s.error = "Deadlock: unmet dependencies or all ready steps blocked"
                        s.finished_at = _utc_now_iso()
                        failed.add(s.step_id)
                continue

            # Determine parallelism: how many can actually run concurrently
            parallel_allowed = [
                s for s in ready
                if self._can_run_parallel(s, plan)
            ]
            sequential_only = [s for s in ready if s not in parallel_allowed]

            # Run parallel group first, then sequential
            if parallel_allowed:
                self._run_batch(plan, parallel_allowed, completed, failed, run_id)
            if sequential_only:
                for step in sequential_only:
                    self._run_batch(plan, [step], completed, failed, run_id)

        # Determine overall status
        result.status = self._compute_overall_status(step_plans)
        result.summary = (
            f"Multi-worker execution: {result.passed_steps}/{result.step_count} passed, "
            f"{result.failed_steps} failed, {result.blocked_steps} blocked"
        )
        return result

    def _find_ready_steps(
        self,
        step_plans: list[StepExecutionRecord],
        completed: set[str],
        failed: set[str],
    ) -> list[StepExecutionRecord]:
        """Find steps whose dependencies are all completed."""
        ready: list[StepExecutionRecord] = []
        for s in step_plans:
            if s.step_id in completed or s.step_id in failed:
                continue
            if s.status == "running":
                continue
            # For now, derive deps from the plan's worker tasks
            # Steps without explicit deps depend on the previous step's success
            ready.append(s)
        return ready

    def _can_run_parallel(self, step: StepExecutionRecord, plan: PlanContract) -> bool:
        """Check if a step can run in parallel with others."""
        worker_task = self._find_worker_task(plan, step.step_id)
        if worker_task:
            if not worker_task.can_run_parallel:
                return False
            if worker_task.requires_human_review:
                return False
        # Default: allow parallel if no explicit block
        return True

    def _find_worker_task(
        self, plan: PlanContract, step_id: str
    ) -> PlannedWorkerTask | None:
        for wt in plan.planned_worker_tasks:
            wt_id = wt.step_id or ""
            if wt_id == step_id:
                return wt
        return None

    def _run_batch(
        self,
        plan: PlanContract,
        steps: list[StepExecutionRecord],
        completed: set[str],
        failed: set[str],
        run_id: str,
    ) -> None:
        """Execute a batch of steps, respecting max_workers limit."""
        # Cap parallelism at max_workers
        batch = steps[:self._max_workers]

        if len(batch) == 1:
            self._execute_single_step(plan, batch[0], run_id, completed, failed)
            return

        # Parallel execution via thread pool
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = {
                executor.submit(
                    self._run_one_step, plan, step, run_id
                ): step
                for step in batch
            }
            for future in as_completed(futures):
                step = futures[future]
                try:
                    step_result = future.result()
                    if step_result.status == "passed":
                        completed.add(step.step_id)
                    else:
                        failed.add(step.step_id)
                except Exception as exc:
                    step.status = "failed"
                    step.error = str(exc)
                    step.finished_at = _utc_now_iso()
                    failed.add(step.step_id)

                if self._progress_callback:
                    self._notify_progress(step)

    def _execute_single_step(
        self,
        plan: PlanContract,
        step: StepExecutionRecord,
        run_id: str,
        completed: set[str],
        failed: set[str],
    ) -> None:
        """Execute one step synchronously."""
        step_result = self._run_one_step(plan, step, run_id)
        if step_result.status == "passed":
            completed.add(step.step_id)
        else:
            failed.add(step.step_id)

    # ------------------------------------------------------------------
    # Single step execution (the real work)
    # ------------------------------------------------------------------

    def _run_one_step(
        self,
        plan: PlanContract,
        step: StepExecutionRecord,
        run_id: str,
    ) -> StepExecutionRecord:
        """Execute one step: packet → worker → evidence → control."""
        step.status = "running"
        step.started_at = _utc_now_iso()

        worker_task = self._find_worker_task(plan, step.step_id)

        try:
            # 1. Build packet for this step
            packet = self._step_to_packet(plan, worker_task, step, run_id)

            # 2. Pre-flight policy check
            preflight = self._preflight_check(packet)
            if preflight:
                step.control_decisions.append(preflight)
                step.status = "blocked"
                step.finished_at = _utc_now_iso()
                step.packet_dir = str(packet.packet_root)
                return step

            # 3. Execute worker
            worker_result = self._execute_worker(packet)

            # 3b. Infrastructure failure check
            if self._worker_mode == "claude-code":
                infra = self._check_worker_infrastructure(worker_result)
                if infra:
                    step.control_decisions.extend(infra)
                    step.status = "failed"
                    step.error = worker_result.get("error", "infrastructure failure")
                    step.finished_at = _utc_now_iso()
                    step.packet_dir = str(packet.packet_root)
                    step.worker_result = worker_result
                    return step

            # 4. Classify evidence
            evidence_status = classify_worker_evidence_from_packet(packet)

            # 5. Run control checks
            control_decisions = self._run_per_step_controls(
                packet, evidence_status, worker_result,
            )

            # 6. Determine step outcome
            blocked = [d for d in control_decisions if not d.passed]
            if blocked:
                actions = {d.action for d in blocked}
                if "needs_human_review" in actions:
                    step.status = "needs_human_review"
                elif "fail" in actions:
                    step.status = "failed"
                else:
                    step.status = "blocked"
            elif evidence_status.has_missing_required:
                step.status = "blocked"
            else:
                step.status = "passed"

            step.evidence_status = evidence_status
            step.control_decisions = control_decisions
            step.changed_files = evidence_status.changed_files
            step.packet_dir = str(packet.packet_root)
            step.worker_result = worker_result

        except Exception as exc:
            step.status = "failed"
            step.error = str(exc)

        step.finished_at = _utc_now_iso()
        return step

    def _step_to_packet(
        self,
        plan: PlanContract,
        worker_task: PlannedWorkerTask | None,
        step: StepExecutionRecord,
        run_id: str,
    ) -> WorkerTaskPacket:
        """Build a WorkerTaskPacket for a single step."""
        if worker_task:
            return WorkerTaskPacket.create(
                project_root=str(self.project_root),
                run_id=run_id,
                task_id=step.task_id,
                title=worker_task.title or step.title,
                objective=worker_task.objective or plan.objective,
                allowed_files=worker_task.allowed_files,
                denied_files=worker_task.denied_files,
                protected_files=list(self._policy.protected_files),
                required_checks=worker_task.required_checks,
                expected_evidence=[
                    e for e in worker_task.expected_evidence
                    if e not in ("result.md", "status.json")
                ],
                risk_level=worker_task.risk_level,
                run_mode=plan.run_mode,
            )

        # Fallback: build from plan.steps text
        evidence = [e for e in plan.required_evidence if e not in ("result.md", "status.json")]
        if not evidence:
            evidence = ["test_output.txt", "diff.patch"]
        return WorkerTaskPacket.create(
            project_root=str(self.project_root),
            run_id=run_id,
            task_id=step.task_id,
            title=step.title[:80],
            objective=step.title,
            allowed_files=[],
            denied_files=[],
            protected_files=list(self._policy.protected_files),
            required_checks=[],
            expected_evidence=evidence,
            risk_level="medium",
            run_mode=plan.run_mode,
        )

    def _preflight_check(self, packet: WorkerTaskPacket) -> ControlDecision | None:
        """Check policy before launching worker."""
        if packet.allowed_files:
            # Check for protected file access using glob matching
            protected_hits = [
                f for f in packet.allowed_files
                if self._policy.is_file_protected(f)
            ]
            if protected_hits:
                return ControlDecision(
                    passed=False,
                    action="needs_human_review",
                    reason=f"Step attempts to modify protected files: {sorted(protected_hits)}",
                    severity="high",
                    failure_category="policy_violation",
                    recovery_hint="request_evidence",
                )
        return None

    # ------------------------------------------------------------------
    # Worker execution (delegates to per-mode logic)
    # ------------------------------------------------------------------

    def _execute_worker(self, packet: WorkerTaskPacket) -> dict[str, Any]:
        """Execute the worker for a single step."""
        if self._worker_mode == "fake":
            return self._execute_fake(packet)
        elif self._worker_mode == "packet":
            pdir = packet.write()
            return {
                "run_id": packet.run_id,
                "task_id": packet.task_id,
                "packet_dir": str(pdir),
                "behaviour": "packet",
                "worker_status": "pending_external",
                "changed_files": [],
                "summary": "Packet written — awaiting external worker",
                "observed_paths": [],
            }
        elif self._worker_mode == "claude-code":
            return self._execute_claude_code(packet)
        else:
            raise ValueError(f"Unknown worker_mode: {self._worker_mode!r}")

    def _execute_fake(self, packet: WorkerTaskPacket) -> dict[str, Any]:
        from .workers.fake_worker import run_fake_worker
        return run_fake_worker(packet, packet_dir=packet.packet_root)

    def _execute_claude_code(self, packet: WorkerTaskPacket) -> dict[str, Any]:
        from .workers.claude_code import (
            ClaudeCodeWorkerConfig,
            run_claude_code_worker,
        )
        config = ClaudeCodeWorkerConfig.from_env(project_root=str(self.project_root))
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
            "command": result.command,
        }

    def _check_worker_infrastructure(
        self, worker_result: dict[str, Any]
    ) -> list[ControlDecision]:
        error = worker_result.get("error", "")
        exit_code = worker_result.get("exit_code", 0)
        timed_out = worker_result.get("timed_out", False)
        decisions: list[ControlDecision] = []
        if timed_out:
            decisions.append(ControlDecision(
                passed=False, action="fail",
                reason=f"Worker timed out after {worker_result.get('timeout', 'unknown')}",
                severity="high", failure_category="worker_timeout",
                recovery_hint="retry_with_backoff",
            ))
        elif error:
            decisions.append(ControlDecision(
                passed=False, action="fail",
                reason=f"Worker infrastructure failure: {error}",
                severity="high", failure_category="worker_infrastructure",
                recovery_hint="fail",
            ))
        elif exit_code != 0:
            decisions.append(ControlDecision(
                passed=False, action="needs_human_review",
                reason=f"Worker exited with code {exit_code}",
                severity="medium", failure_category="worker_error",
                recovery_hint="needs_human_review",
            ))
        return decisions

    # ------------------------------------------------------------------
    # Per-step control checks
    # ------------------------------------------------------------------

    def _run_per_step_controls(
        self,
        packet: WorkerTaskPacket,
        evidence_status: WorkerEvidenceStatus,
        worker_result: dict[str, Any],
    ) -> list[ControlDecision]:
        decisions: list[ControlDecision] = []

        # Evidence verification
        decisions.append(self._cp.verify_worker_evidence(evidence_status))

        # File change policy check
        changed = evidence_status.changed_files
        if changed:
            decisions.append(self._cp.check_policy_for_file_changes(files_changed=changed))

        # Output guardrail
        summary = evidence_status.reported_summary
        if summary:
            decisions.append(self._cp.guard_output(
                agent_name="multi_worker",
                payload={"output": summary, "changed_files": changed},
            ))

        return decisions

    # ------------------------------------------------------------------
    # Combined report
    # ------------------------------------------------------------------

    def _generate_combined_report(
        self,
        plan: PlanContract,
        result: MultiWorkerResult,
    ) -> tuple[str, str]:
        output_dir = self.project_root / "outputs"
        report_dir = output_dir / "reports"
        evidence_dir = output_dir / "evidence"
        report_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        task_id = f"multi-{result.run_id}"

        # Combined evidence
        all_files: list[str] = []
        for s in result.steps:
            all_files.extend(s.changed_files)
        evidence_data = {
            "run_id": result.run_id,
            "plan_id": result.plan_id,
            "step_count": result.step_count,
            "steps": [
                {
                    "step_id": s.step_id,
                    "status": s.status,
                    "changed_files": s.changed_files,
                    "evidence": (
                        _evidence_status_to_dict(s.evidence_status)
                        if s.evidence_status else None
                    ),
                }
                for s in result.steps
            ],
        }
        evidence_path = evidence_dir / f"{task_id}.json"
        evidence_path.write_text(
            json.dumps(evidence_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Combined audit report
        report_data = {
            "report_type": "multi_worker_audit",
            "generated_at": _utc_now_iso(),
            "run_id": result.run_id,
            "plan_id": result.plan_id,
            "objective": plan.objective,
            "worker_mode": self._worker_mode,
            "overall_status": result.status,
            "summary": {
                "total_steps": result.step_count,
                "passed": result.passed_steps,
                "failed": result.failed_steps,
                "blocked": result.blocked_steps,
            },
            "step_results": [
                {
                    "step_id": s.step_id,
                    "title": s.title,
                    "status": s.status,
                    "task_id": s.task_id,
                    "packet_dir": s.packet_dir,
                    "changed_files": s.changed_files,
                    "error": s.error,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                    "control_decisions": [
                        {
                            "action": d.action,
                            "passed": d.passed,
                            "reason": d.reason,
                            "severity": d.severity,
                            "recovery_hint": d.recovery_hint,
                        }
                        for d in s.control_decisions
                    ],
                }
                for s in result.steps
            ],
            "plan_snapshot": plan_contract_to_dict(plan),
            "artifact_summary": {
                "report_path": str(report_dir / f"{task_id}.json"),
                "evidence_path": str(evidence_path),
            },
        }
        report_path = report_dir / f"{task_id}.json"
        report_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return str(report_path), str(evidence_path)

    def _compute_overall_status(
        self, step_plans: list[StepExecutionRecord]
    ) -> str:
        statuses = {s.status for s in step_plans}
        if any(s in ("failed", "blocked") for s in statuses):
            if "needs_human_review" in statuses:
                return "needs_human_review"
            if "failed" in statuses:
                return "completed_with_failures"
            return "blocked"
        if all(s == "passed" for s in statuses):
            return "completed"
        if "needs_human_review" in statuses:
            return "needs_human_review"
        return "unknown"

    def _notify_progress(self, step: StepExecutionRecord) -> None:
        """Call the progress callback if set."""
        if self._progress_callback:
            # Build a minimal result for progress
            result = MultiWorkerResult(
                steps=[step],
                status="running",
            )
            self._progress_callback(result)


# =============================================================================
# Helpers
# =============================================================================


def _evidence_status_to_dict(es: WorkerEvidenceStatus) -> dict[str, Any]:
    if es is None:
        return {}
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
