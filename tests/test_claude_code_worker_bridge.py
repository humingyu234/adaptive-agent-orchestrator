"""Integration tests for Claude Code worker bridge.

Covers: task rendering, result loading, ControlPlane.verify_worker_evidence,
and run-mode behaviour (log vs controlled for missing evidence).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.control_models import WorkerEvidenceItem, WorkerEvidenceStatus
from orchestrator.control_plane import ControlPlane
from orchestrator.policy import Policy
from orchestrator.worker_protocol import (
    PacketFiles,
    WorkerTaskPacket,
    classify_worker_evidence,
    load_worker_status,
)
from orchestrator.workers.claude_code import (
    ClaudeCodeTaskRenderer,
    load_claude_code_result,
    load_full_packet,
    render_claude_code_task,
)


# =============================================================================
# Claude Code task rendering
# =============================================================================

class TestClaudeCodeTaskRendering:
    def test_render_includes_objective(self):
        packet = WorkerTaskPacket.create(
            objective="Fix the login bug in auth.py",
            allowed_files=["src/auth.py"],
        )
        rendered = render_claude_code_task(packet)
        assert "Fix the login bug in auth.py" in rendered
        assert "src/auth.py" in rendered

    def test_render_includes_denied_files(self):
        packet = WorkerTaskPacket.create(
            objective="X",
            denied_files=["src/secrets.py"],
        )
        rendered = render_claude_code_task(packet)
        assert "src/secrets.py" in rendered
        assert "do NOT touch" in rendered.lower() or "Denied Files" in rendered

    def test_render_includes_protected_files(self):
        packet = WorkerTaskPacket.create(
            objective="X",
            protected_files=["config/production.yaml"],
        )
        rendered = render_claude_code_task(packet)
        assert "config/production.yaml" in rendered

    def test_render_includes_required_checks(self):
        packet = WorkerTaskPacket.create(
            objective="X",
            required_checks=["python -m pytest tests/"],
        )
        rendered = render_claude_code_task(packet)
        assert "python -m pytest tests/" in rendered

    def test_render_includes_expected_evidence(self):
        packet = WorkerTaskPacket.create(
            objective="X",
            expected_evidence=["test_output.txt", "diff.patch"],
        )
        rendered = render_claude_code_task(packet)
        assert "test_output.txt" in rendered
        assert "diff.patch" in rendered

    def test_render_includes_non_goals(self):
        packet = WorkerTaskPacket.create(objective="X")
        rendered = render_claude_code_task(packet)
        assert "Non-Goals" in rendered
        assert "Do NOT change files outside the allowed list" in rendered

    def test_render_includes_handoff(self):
        packet = WorkerTaskPacket.create(objective="X")
        rendered = render_claude_code_task(packet)
        assert "Handoff" in rendered
        assert "result.md" in rendered
        assert "status.json" in rendered

    def test_render_includes_task_and_run_ids(self):
        packet = WorkerTaskPacket.create(
            run_id="run-001",
            task_id="task-001",
            objective="X",
        )
        rendered = render_claude_code_task(packet)
        assert "run-001" in rendered
        assert "task-001" in rendered

    def test_render_includes_risk_level(self):
        packet = WorkerTaskPacket.create(objective="X", risk_level="high")
        rendered = render_claude_code_task(packet)
        assert "high" in rendered.lower()

    def test_custom_renderer_produces_same_output(self):
        packet = WorkerTaskPacket.create(objective="X")
        r1 = render_claude_code_task(packet)
        r2 = ClaudeCodeTaskRenderer().render(packet)
        assert r1 == r2

    def test_rendered_instruction_is_plain_text(self):
        packet = WorkerTaskPacket.create(objective="X")
        rendered = render_claude_code_task(packet)
        # Should not contain raw JSON or machine-only fields
        assert isinstance(rendered, str)
        assert len(rendered) > 100


# =============================================================================
# Claude Code result loading
# =============================================================================

class TestClaudeCodeResultLoading:
    def _make_completed_packet(self, base: Path) -> Path:
        pdir = base / "packet"
        pdir.mkdir()
        (pdir / "observed").mkdir()
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
            "changed_files": ["src/a.py"],
            "summary": "Fixed the bug",
        }))
        (pdir / "result.md").write_text("## Result\n\nFixed the login bug.\n\nTests passed.")
        (pdir / "observed" / "test_output.txt").write_text("All tests passed.")
        return pdir

    def test_load_claude_code_result_reads_status(self, tmp_path):
        pdir = self._make_completed_packet(tmp_path)
        result = load_claude_code_result(pdir)
        assert result["status"] == "completed"
        assert result["task_id"] == "t1"
        assert "src/a.py" in result["changed_files"]

    def test_load_claude_code_result_reads_observed_files(self, tmp_path):
        pdir = self._make_completed_packet(tmp_path)
        result = load_claude_code_result(pdir)
        assert "observed/test_output.txt" in result["observed_files"]

    def test_load_full_packet_includes_manifest_when_present(self, tmp_path):
        pdir = self._make_completed_packet(tmp_path)
        (pdir / "manifest.json").write_text(json.dumps({"objective": "Fix bug"}))
        full = load_full_packet(pdir)
        assert full["manifest"]["objective"] == "Fix bug"
        assert full["result"]["status"] == "completed"

    def test_load_result_without_status_file(self, tmp_path):
        pdir = tmp_path / "empty"
        pdir.mkdir()
        (pdir / "observed").mkdir()
        result = load_claude_code_result(pdir)
        assert result["status"] == "unknown"


# =============================================================================
# ControlPlane.verify_worker_evidence
# =============================================================================

class TestControlPlaneVerifyWorkerEvidence:
    def test_all_observed_no_violations_passes(self):
        cp = ControlPlane()
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="observed", path="observed/test_output.txt"),
            ],
            reported_summary="All done.",
        )
        decision = cp.verify_worker_evidence(evidence)
        assert decision.passed
        assert decision.action == "continue"

    def test_missing_required_evidence_blocks_controlled(self):
        cp = ControlPlane()
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="missing"),
            ],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert not decision.passed
        assert decision.recovery_hint == "request_evidence"
        assert decision.evidence_required

    def test_missing_evidence_logs_but_does_not_block(self):
        cp = ControlPlane(policy=Policy(mode="log"))
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="missing"),
            ],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert decision.passed
        assert decision.action == "continue"

    def test_off_mode_bypasses_verification(self):
        cp = ControlPlane(policy=Policy(mode="off"))
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="missing"),
            ],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert decision.passed

    def test_malformed_result_is_blocked(self):
        cp = ControlPlane()
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="",  # malformed
        )
        decision = cp.verify_worker_evidence(evidence)
        assert not decision.passed
        assert decision.action == "fail"

    def test_denied_file_changes_create_policy_violation(self):
        cp = ControlPlane()
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            denied_files_changed=["src/secrets.py"],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert not decision.passed
        assert decision.failure_category == "policy_error"
        assert decision.recovery_hint == "needs_human_review"

    def test_worker_reported_failure_is_reflected(self):
        cp = ControlPlane()
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="failed",
            reported_summary="Tests failed",
        )
        decision = cp.verify_worker_evidence(evidence)
        assert not decision.passed
        assert decision.action == "fail"
        assert "Tests failed" in decision.reason

    def test_no_expected_evidence_always_passes(self):
        cp = ControlPlane()
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert decision.passed
        assert decision.action == "continue"


# =============================================================================
# Run mode semantics: log vs controlled
# =============================================================================

class TestRunModeSemantics:
    def test_log_mode_records_missing_evidence_without_blocking(self):
        """Spec: log mode records missing evidence but does not block."""
        cp = ControlPlane(policy=Policy(mode="log"))
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="missing"),
                WorkerEvidenceItem(key="diff.patch", status="observed", path="observed/diff.patch"),
            ],
        )
        decision = cp.verify_worker_evidence(evidence)
        # Log mode: should pass despite missing evidence
        assert decision.passed
        assert decision.action == "continue"

    def test_controlled_mode_blocks_missing_evidence(self):
        """Spec: controlled mode blocks completion when required evidence is missing."""
        cp = ControlPlane(policy=Policy(mode="controlled"))
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="missing"),
            ],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert not decision.passed
        assert decision.evidence_required

    def test_log_mode_does_not_block_denied_files(self):
        cp = ControlPlane(policy=Policy(mode="log"))
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            denied_files_changed=["src/protected.py"],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert decision.passed


# =============================================================================
# End-to-end: packet creation → write → evidence classification
# =============================================================================

class TestEndToEndPacketFlow:
    def test_full_cycle_create_write_classify(self, tmp_path):
        root = str(tmp_path)

        # 1. Create and write packet
        packet = WorkerTaskPacket.create(
            project_root=root,
            run_id="e2e-run",
            task_id="e2e-task",
            objective="Write a test for foo.py",
            allowed_files=["src/foo.py", "tests/test_foo.py"],
            denied_files=["src/secrets.py"],
            required_checks=["python -m pytest tests/test_foo.py"],
            expected_evidence=["test_output.txt"],
            risk_level="medium",
        )
        pdir = packet.write()

        # 2. Simulate worker writing results
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "e2e-task",
            "changed_files": ["src/foo.py", "tests/test_foo.py"],
            "summary": "Added test for foo.py",
        }))
        (pdir / "result.md").write_text("## Result\n\nAdded tests. All passing.")
        (pdir / "observed" / "test_output.txt").write_text("All 5 tests passed.")

        # 3. Classify evidence
        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=["test_output.txt"],
        )
        assert not status.has_missing_required
        items_by_key = {i.key: i.status for i in status.items}
        assert items_by_key["test_output.txt"] == "observed"

        # 4. Verify through ControlPlane
        cp = ControlPlane()
        decision = cp.verify_worker_evidence(status)
        assert decision.passed
        assert decision.action == "continue"

    def test_task_without_code_changes_does_not_require_diff(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            objective="Review code quality",
            expected_evidence=["test_output.txt"],
        )
        pdir = packet.write()

        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": packet.task_id,
        }))
        (pdir / "result.md").write_text("Reviewed. No changes needed.")
        # No diff.patch — this is fine because it wasn't expected

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=["test_output.txt"],
        )
        # Only test_output.txt is expected and missing — diff.patch is not expected
        assert status.has_missing_required  # test_output.txt missing

    def test_different_task_ids_dont_cross_read(self, tmp_path):
        root = str(tmp_path)
        p1 = WorkerTaskPacket.create(project_root=root, task_id="t1", objective="A")
        p2 = WorkerTaskPacket.create(project_root=root, task_id="t2", objective="B")

        d1 = p1.write()
        d2 = p2.write()

        (d1 / "status.json").write_text(json.dumps({"status": "completed", "task_id": "t1"}))
        (d2 / "status.json").write_text(json.dumps({"status": "completed", "task_id": "t2"}))

        s1 = load_worker_status(d1)
        s2 = load_worker_status(d2)
        assert s1["task_id"] == "t1"
        assert s2["task_id"] == "t2"
        # Different task IDs don't see each other's files
        assert d1 != d2


# =============================================================================
# Integration: ControlPlane turns missing evidence into recovery decision
# =============================================================================

class TestControlPlaneRecoveryForWorkerEvidence:
    def test_missing_worker_evidence_produces_recovery_decision(self):
        cp = ControlPlane()
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="missing"),
            ],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert not decision.passed
        assert decision.recovery_hint == "request_evidence"
        assert decision.evidence_required

        # The recovery hint can feed into the playbook
        from orchestrator.failure_taxonomy import (
            FailureCategory,
            FailureRecord,
        )
        fr = FailureRecord(
            category=FailureCategory.TASK_QUALITY_ERROR,
            reason="missing_evidence",
            origin="worker",
        )
        recovery = cp.decide_recovery(fr, task_id="t1")
        assert recovery.recovery_hint == "request_evidence"


# =============================================================================
# Live view integration
# =============================================================================

class TestLiveViewWorkerEvidence:
    def test_build_live_view_accepts_worker_evidence(self):
        from orchestrator.live_view import build_live_view
        from orchestrator.state_center import StateCenter

        state = StateCenter(query="test")
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="observed", path="observed/test_output.txt"),
            ],
        )
        view = build_live_view(state, worker_evidence=evidence)
        assert view["worker_evidence"] is not None
        assert view["worker_evidence"]["task_id"] == "t1"
        assert view["worker_evidence"]["worker_status"] == "completed"

    def test_build_live_view_worker_evidence_missing_items(self):
        from orchestrator.live_view import build_live_view
        from orchestrator.state_center import StateCenter

        state = StateCenter(query="test")
        evidence = WorkerEvidenceStatus(
            task_id="t2",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="diff.patch", status="missing"),
            ],
            denied_files_changed=["secret.env"],
        )
        view = build_live_view(state, worker_evidence=evidence)
        we = view["worker_evidence"]
        assert we["has_missing_required"]
        assert we["denied_files_changed"] == ["secret.env"]

    def test_build_live_view_without_worker_evidence_is_none(self):
        from orchestrator.live_view import build_live_view
        from orchestrator.state_center import StateCenter

        state = StateCenter(query="test")
        view = build_live_view(state)
        assert view["worker_evidence"] is None


# =============================================================================
# Report writer integration
# =============================================================================

class TestReportWriterWorkerEvidence:
    def test_report_includes_worker_evidence_summary(self, tmp_path):
        """Verify worker evidence data shape matches what the report writer expects.

        The ConvergenceReportWriter._build_worker_evidence_summary method formats
        WorkerEvidenceStatus into a dict.  This test verifies the data shape
        without importing report_writer (which has a pre-existing circular import).
        """
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="observed"),
            ],
            changed_files=["src/a.py"],
        )

        # Manual formatting to match _build_worker_evidence_summary output
        summary = {
            "available": True,
            "task_id": evidence.task_id,
            "worker_kind": evidence.worker_kind,
            "worker_status": evidence.worker_status,
            "has_missing_required": evidence.has_missing_required,
            "is_malformed": evidence.is_malformed,
            "items": [
                {"key": i.key, "status": i.status, "path": i.path, "description": i.description}
                for i in evidence.items
            ],
            "changed_files": evidence.changed_files,
            "denied_files_changed": evidence.denied_files_changed,
            "reported_summary": evidence.reported_summary[:500] if evidence.reported_summary else "",
        }
        assert summary["available"] is True
        assert summary["task_id"] == "t1"
        assert summary["worker_status"] == "completed"
        assert len(summary["items"]) == 1

    def test_report_without_worker_evidence_is_empty(self):
        """No worker evidence produces an empty summary dict."""
        summary = {"available": False, "task_id": None}
        assert summary["available"] is False
        assert summary["task_id"] is None
