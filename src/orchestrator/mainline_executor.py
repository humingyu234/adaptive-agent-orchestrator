"""MainlineExecutor — drives the full AAO control chain from plan to audit.

Wires: PlanContract → WorkerTaskPacket → worker execution → evidence
classification → ControlPlane decisions → audit report.

This is THE integration point that connects all AAO components.  The old
YAML-workflow path through Scheduler is preserved for legacy/native mode.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .control_models import ControlDecision, WorkerEvidenceStatus
from .planning import PlanContract, PlannedWorkerTask, plan_contract_to_dict
from .worker_protocol import (
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
    status: str = "unknown"  # completed, blocked, failed
    worker_mode: str = "fake"
    worker_result: dict[str, Any] = field(default_factory=dict)
    evidence_status: dict[str, Any] | None = None
    control_decisions: list[dict[str, Any]] = field(default_factory=list)
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
            "worker_result": self.worker_result,
            "evidence_status": self.evidence_status,
            "control_decisions": self.control_decisions,
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
    1. Converts plan to WorkerTaskPacket(s)
    2. Executes worker (fake writes files; packet writes to disk)
    3. Classifies evidence
    4. Runs ControlPlane checks (evidence, policy, guardrails)
    5. Generates audit report
    6. Returns MainlineResult
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path.cwd()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def execute(
        self,
        plan: PlanContract,
        *,
        worker_mode: str = "fake",
    ) -> MainlineResult:
        """Execute a plan through the mainline chain.

        Args:
            plan: An approved PlanContract.
            worker_mode: "fake" (deterministic, writes files) or "packet" (writes
                         packet to disk for external worker).

        Returns:
            MainlineResult with all paths, decisions, and status.
        """
        run_id = _utc_now_compact() + "-" + uuid.uuid4().hex[:6]
        task_id = f"task-{run_id}"

        # 1. Convert plan to WorkerTaskPacket
        packet = self._plan_to_packet(plan, run_id=run_id, task_id=task_id)

        # 2. Execute worker
        worker_result = self._execute_worker(packet, worker_mode=worker_mode)

        # 3. Classify evidence
        evidence_status = classify_worker_evidence_from_packet(packet)

        # 4. Run ControlPlane checks
        control_decisions = self._run_control_checks(packet, evidence_status, worker_result)

        # 5. Generate audit report
        report_path, evidence_path = self._generate_report(
            plan=plan,
            packet=packet,
            worker_result=worker_result,
            evidence_status=evidence_status,
            control_decisions=control_decisions,
        )

        # 6. Determine overall status
        overall_status = self._determine_status(control_decisions, evidence_status)

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
    ) -> MainlineResult:
        """Execute a simple query directly without a PlanContract.

        For small/medium tasks that don't go through Planning Council but the
        user still wants the mainline path (--worker-mode flag).
        """
        from .planning import PlanningCouncil, build_default_council

        council = build_default_council()
        plan = council.create_plan(
            query,
            task_size=task_size,
            run_mode=run_mode,
        )
        try:
            plan.approve()
        except ValueError:
            return MainlineResult(
                run_id="",
                task_id="",
                plan_id=plan.plan_id,
                status="blocked_needs_review",
                worker_mode=worker_mode,
                worker_result={"behaviour": "blocked", "summary": "Plan has blocking concerns"},
                evidence_status=None,
                control_decisions=[{
                    "action": "needs_human_review",
                    "passed": False,
                    "reason": f"Plan has {len(plan.blocking_concerns)} blocking concern(s)",
                }],
                summary=f"Plan blocked: {plan.blocking_concerns[0] if plan.blocking_concerns else 'unknown'}",
            )
        return self.execute(plan, worker_mode=worker_mode)

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
        """Convert a PlanContract to a WorkerTaskPacket."""

        # Gather file boundaries from planned_worker_tasks or extract from steps
        allowed_files: list[str] = []
        denied_files: list[str] = []
        required_checks: list[str] = []
        expected_evidence: list[str] = list(plan.required_evidence)

        if plan.planned_worker_tasks:
            pwt = plan.planned_worker_tasks[0]
            allowed_files = list(pwt.allowed_files)
            denied_files = list(pwt.denied_files)
            required_checks = list(pwt.required_checks)
            if pwt.expected_evidence:
                expected_evidence = list(pwt.expected_evidence)

        # Fallback: extract from objective/steps
        if not allowed_files:
            allowed_files = self._extract_files_from_plan(plan)
        if not required_checks:
            required_checks = self._infer_required_checks(plan)
        if not expected_evidence:
            expected_evidence = ["test_output.txt", "diff.patch"]

        # Filter out standard packet outputs — these live at the packet root
        # and are verified via load_worker_status/load_worker_result_text, not
        # the observed/ evidence classifier.
        expected_evidence = [
            e for e in expected_evidence
            if e not in ("result.md", "status.json")
        ]
        if not expected_evidence:
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
            protected_files=[],
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

    # ------------------------------------------------------------------
    # Control checks
    # ------------------------------------------------------------------

    def _run_control_checks(
        self,
        packet: WorkerTaskPacket,
        evidence_status: WorkerEvidenceStatus,
        worker_result: dict[str, Any],
    ) -> list[ControlDecision]:
        """Run all relevant ControlPlane checks."""
        from .control_plane import ControlPlane

        cp = ControlPlane()
        decisions: list[ControlDecision] = []

        # 1. Worker evidence verification
        evidence_decision = cp.verify_worker_evidence(evidence_status)
        decisions.append(evidence_decision)

        # 2. Policy check for file changes
        changed_files = evidence_status.changed_files
        if changed_files:
            policy_decision = cp.check_policy_for_file_changes(files_changed=changed_files)
            decisions.append(policy_decision)

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
        import re

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


# =============================================================================
# Serialization helpers
# =============================================================================


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
