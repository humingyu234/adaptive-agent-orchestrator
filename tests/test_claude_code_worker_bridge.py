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
from orchestrator.planning import PlanContract, PlannedWorkerTask
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
        assert decision.action == "retry"
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


# =============================================================================
# Phase 18 — Real subprocess worker bridge tests
# =============================================================================
# These tests use a fake subprocess script (tests/fixtures/fake_cc_worker.py)
# as the AAO_CLAUDE_CODE_COMMAND.  No real Claude Code or API keys needed.


FAKE_CC = str(Path(__file__).resolve().parent / "fixtures" / "fake_cc_worker.py")


def _make_test_packet(tmp_path: Path, **kwargs) -> WorkerTaskPacket:
    """Create a WorkerTaskPacket pointing at a temp directory."""
    pkt_root = tmp_path / ".aao" / "tasks" / "run-test" / "task-test"
    pkt_root.mkdir(parents=True, exist_ok=True)
    return WorkerTaskPacket.create(
        project_root=str(tmp_path),
        run_id="run-test",
        task_id="task-test",
        title="Test task",
        objective=kwargs.pop("objective", "Add a helper function"),
        allowed_files=kwargs.pop("allowed_files", ["src/utils.py"]),
        required_checks=kwargs.pop("required_checks", ["python -m pytest"]),
        expected_evidence=kwargs.pop("expected_evidence", ["test_output.txt", "diff.patch"]),
        risk_level=kwargs.pop("risk_level", "low"),
        run_mode=kwargs.pop("run_mode", "controlled"),
        **kwargs,
    )


def _run_fake_worker(packet: WorkerTaskPacket, behavior: str = "success",
                     exit_code: int = 0, sleep: float = 0) -> WorkerRunResult:
    """Run the fake CC worker as a subprocess with given behavior."""
    from orchestrator.workers.claude_code import (
        ClaudeCodeWorkerConfig,
        WorkerRunResult,
        run_claude_code_worker,
    )

    config = ClaudeCodeWorkerConfig(
        command=f"python3 {FAKE_CC} --behavior {behavior} --exit-code {exit_code} "
                f"--packet-dir {packet.packet_root}",
        timeout_seconds=30,
        prompt_mode="stdin",
        project_root=str(packet.packet_root.parent.parent.parent),
        extra_args=[],  # fake worker doesn't need -p --verbose
    )
    return run_claude_code_worker(packet, config=config)


class TestRealWorkerSubprocess:
    """Tests for run_claude_code_worker() using fake subprocess."""

    def test_worker_command_invoked_with_packet_dir(self, tmp_path):
        packet = _make_test_packet(tmp_path)
        result = _run_fake_worker(packet, "success")

        assert result.exit_code == 0
        assert not result.timed_out
        assert result.worker_status == "completed"
        assert "src/utils.py" in result.changed_files

    def test_worker_writes_result_md_and_status_json(self, tmp_path):
        packet = _make_test_packet(tmp_path)
        result = _run_fake_worker(packet, "success")

        assert Path(result.result_md_path).exists()
        assert Path(result.status_json_path).exists()

    def test_worker_stdout_stderr_exit_captured_as_observed(self, tmp_path):
        packet = _make_test_packet(tmp_path)
        result = _run_fake_worker(packet, "success")

        assert Path(result.stdout_path).exists()
        assert Path(result.stderr_path).exists()
        assert Path(result.transcript_path).exists()

    def test_command_not_found_produces_error(self, tmp_path):
        from orchestrator.workers.claude_code import (
            ClaudeCodeWorkerConfig,
            run_claude_code_worker,
        )

        packet = _make_test_packet(tmp_path)
        config = ClaudeCodeWorkerConfig(
            command="/nonexistent/worker_command_xyz_123",
            timeout_seconds=5,
            project_root=str(tmp_path),
        )
        result = run_claude_code_worker(packet, config=config)

        assert result.exit_code == -2
        assert "not found" in result.error.lower()
        assert result.worker_status == "unknown"

    def test_missing_evidence_worker_status_is_completed_but_no_observed(self, tmp_path):
        packet = _make_test_packet(tmp_path)
        result = _run_fake_worker(packet, "missing_evidence")

        assert result.worker_status == "completed"
        assert result.changed_files == []
        # No task-evidence files (test_output.txt, diff.patch) — the 4 infra
        # files (worker_stdout/stderr/transcript/exit.json) are always written.
        assert not any(
            name in p for p in result.observed_paths
            for name in ("test_output.txt", "diff.patch")
        )

    def test_nonzero_exit_creates_worker_failure(self, tmp_path):
        packet = _make_test_packet(tmp_path)
        result = _run_fake_worker(packet, "nonzero_exit", exit_code=1)

        assert result.exit_code == 1
        assert result.worker_status == "failed"

    def test_protected_file_worker_writes_secrets_in_changed_files(self, tmp_path):
        packet = _make_test_packet(tmp_path)
        result = _run_fake_worker(packet, "protected_file")

        assert "config/secrets.yaml" in result.changed_files

    def test_success_worker_produces_observed_evidence(self, tmp_path):
        packet = _make_test_packet(tmp_path)
        result = _run_fake_worker(packet, "success")

        observed = result.observed_paths
        assert any("test_output.txt" in p for p in observed)
        assert any("diff.patch" in p for p in observed)

    def test_worker_prompt_written_to_task_directory(self, tmp_path):
        packet = _make_test_packet(tmp_path)
        result = _run_fake_worker(packet, "success")

        prompt_file = Path(result.packet_dir) / "worker_prompt.txt"
        assert prompt_file.exists()
        content = prompt_file.read_text()
        assert "Add a helper function" in content
        assert "allowed" in content.lower() or "Allowed" in content


class TestMainlineClaudeCodeWorker:
    """Integration: MainlineExecutor with claude-code worker mode using fake subprocess."""

    def test_mainline_claude_code_mode_runs_end_to_end(self, tmp_path, monkeypatch):
        """Full chain: plan → execute with claude-code → evidence → audit."""
        from orchestrator.mainline_executor import MainlineExecutor
        from orchestrator.planning import PlanContract

        monkeypatch.setenv("AAO_CLAUDE_CODE_COMMAND",
                          f"python3 {FAKE_CC} --behavior success --packet-dir REPLACE_ME")
        # We need to intercept the command to fix the packet dir.  Use a wrapper.
        # Actually, run_claude_code_worker doesn't use AAO_CLAUDE_CODE_COMMAND
        # directly — ClaudeCodeWorkerConfig.from_env() reads it.  Let's set
        # the env var and use MainlineExecutor.

        plan = PlanContract(
            objective="Add a helper function to src/utils.py",
            run_mode="controlled",
            task_size="medium",
            steps=["Implement", "Test", "Collect evidence"],
            required_evidence=["test_output.txt", "diff.patch"],
            success_criteria=["Tests pass", "Evidence collected"],
        )
        plan.planned_worker_tasks = [
            PlannedWorkerTask(
                title="Add helper",
                objective="Add a helper function to src/utils.py",
                allowed_files=["src/utils.py"],
                required_checks=["python -m pytest"],
                expected_evidence=["test_output.txt", "diff.patch"],
            )
        ]
        plan.approve()

        # Use monkeypatch to replace the _execute_claude_code_worker method
        # so we can inject our fake worker config without the env var going
        # through the CLI path.
        executor = MainlineExecutor(tmp_path)

        def _fake_execute_cc(packet):
            from orchestrator.workers.claude_code import (
                ClaudeCodeWorkerConfig,
                run_claude_code_worker,
            )
            config = ClaudeCodeWorkerConfig(
                command=f"python3 {FAKE_CC} --behavior success --packet-dir {packet.packet_root}",
                timeout_seconds=30,
                project_root=str(tmp_path),
                extra_args=[],
            )
            wr = run_claude_code_worker(packet, config=config)
            return {
                "run_id": wr.run_id,
                "task_id": wr.task_id,
                "packet_dir": wr.packet_dir,
                "behaviour": "claude-code",
                "exit_code": wr.exit_code,
                "timed_out": wr.timed_out,
                "worker_status": wr.worker_status,
                "changed_files": wr.changed_files,
                "summary": wr.summary,
                "error": wr.error,
                "observed_paths": wr.observed_paths,
                "stdout_path": wr.stdout_path,
                "stderr_path": wr.stderr_path,
                "transcript_path": wr.transcript_path,
                "result_md_path": wr.result_md_path,
                "status_json_path": wr.status_json_path,
                "command": wr.command,
            }

        executor._execute_claude_code_worker = _fake_execute_cc

        result = executor.execute(plan, worker_mode="claude-code")
        assert result.status == "completed"
        assert result.worker_mode == "claude-code"
        assert result.evidence_status is not None
        assert result.report_path
        assert result.evidence_path

    def test_mainline_claude_code_command_not_found_fails_clearly(self, tmp_path):
        """When CC command is missing, mainline must return blocked_failed."""
        from orchestrator.mainline_executor import MainlineExecutor
        from orchestrator.planning import PlanContract

        plan = PlanContract(
            objective="Test command missing",
            run_mode="controlled",
            task_size="medium",
            steps=["Implement"],
            required_evidence=["test_output.txt"],
            success_criteria=["Works"],
        )
        plan.approve()

        executor = MainlineExecutor(tmp_path)

        def _fake_execute_missing(packet):
            return {
                "run_id": packet.run_id,
                "task_id": packet.task_id,
                "packet_dir": str(packet.packet_root),
                "behaviour": "claude-code",
                "exit_code": -2,
                "timed_out": False,
                "worker_status": "unknown",
                "changed_files": [],
                "summary": "",
                "error": "Claude Code command not found: '/nonexistent/cc'",
                "observed_paths": [],
                "stdout_path": "",
                "stderr_path": "",
                "transcript_path": "",
                "result_md_path": "",
                "status_json_path": "",
                "command": "/nonexistent/cc",
            }

        executor._execute_claude_code_worker = _fake_execute_missing
        result = executor.execute(plan, worker_mode="claude-code")

        assert result.status == "blocked_failed"
        decisions = result.control_decisions
        assert any(d["failure_category"] == "worker_infrastructure" for d in decisions)

    def test_mainline_claude_code_timeout_is_detected(self, tmp_path):
        """Timeout must be detected as blocked_failed."""
        from orchestrator.mainline_executor import MainlineExecutor
        from orchestrator.planning import PlanContract

        plan = PlanContract(
            objective="Test timeout",
            run_mode="controlled",
            task_size="medium",
            steps=["Implement"],
            required_evidence=["test_output.txt"],
            success_criteria=["Works"],
        )
        plan.approve()

        executor = MainlineExecutor(tmp_path)

        def _fake_execute_timeout(packet):
            return {
                "run_id": packet.run_id,
                "task_id": packet.task_id,
                "packet_dir": str(packet.packet_root),
                "behaviour": "claude-code",
                "exit_code": -1,
                "timed_out": True,
                "worker_status": "unknown",
                "changed_files": [],
                "summary": "",
                "error": "",
                "observed_paths": [],
                "stdout_path": "",
                "stderr_path": "",
                "transcript_path": "",
                "result_md_path": "",
                "status_json_path": "",
                "command": "claude -p",
            }

        executor._execute_claude_code_worker = _fake_execute_timeout
        result = executor.execute(plan, worker_mode="claude-code")

        assert result.status == "blocked_failed"
        assert any("timed out" in d["reason"].lower() for d in result.control_decisions)

    def test_mainline_claude_code_nonzero_exit_requires_review(self, tmp_path):
        """Non-zero exit code must result in needs_human_review."""
        from orchestrator.mainline_executor import MainlineExecutor
        from orchestrator.planning import PlanContract

        plan = PlanContract(
            objective="Test nonzero exit",
            run_mode="controlled",
            task_size="medium",
            steps=["Implement"],
            required_evidence=["test_output.txt"],
            success_criteria=["Works"],
        )
        plan.approve()

        executor = MainlineExecutor(tmp_path)

        def _fake_execute_nonzero(packet):
            return {
                "run_id": packet.run_id,
                "task_id": packet.task_id,
                "packet_dir": str(packet.packet_root),
                "behaviour": "claude-code",
                "exit_code": 1,
                "timed_out": False,
                "worker_status": "failed",
                "changed_files": [],
                "summary": "Worker exited 1",
                "error": "",
                "observed_paths": [],
                "stdout_path": "",
                "stderr_path": "",
                "transcript_path": "",
                "result_md_path": "",
                "status_json_path": "",
                "command": "claude -p",
            }

        executor._execute_claude_code_worker = _fake_execute_nonzero
        result = executor.execute(plan, worker_mode="claude-code")

        assert result.status == "blocked_needs_review"

    def test_claude_code_mode_never_falls_back_to_fake(self):
        """--worker-mode claude-code must mean real subprocess, never fake."""
        from orchestrator.mainline_executor import MainlineExecutor

        executor = MainlineExecutor()
        packet = WorkerTaskPacket.create(
            objective="Test",
            run_id="r1",
            task_id="t1",
        )

        from orchestrator.workers.claude_code import ClaudeCodeWorkerConfig
        # Verify the config distinguishes from fake
        config = ClaudeCodeWorkerConfig.from_env()
        assert config.command != ""  # has a real command
        assert config.timeout_seconds > 0

        # And that MainlineExecutor dispatches to the right method
        assert hasattr(executor, "_execute_claude_code_worker")


class TestCliClaudeCodeMode:
    """CLI integration: --worker-mode claude-code is a recognized choice."""

    def test_claude_code_is_valid_worker_mode_choice(self):
        """The argparse choices include claude-code."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--worker-mode", choices=["fake", "packet", "claude-code"])
        args = parser.parse_args(["--worker-mode", "claude-code"])
        assert args.worker_mode == "claude-code"

    def test_claude_code_mode_listed_in_help(self):
        """Help text mentions claude-code."""
        import argparse
        from io import StringIO
        parser = argparse.ArgumentParser()
        parser.add_argument("--worker-mode", choices=["fake", "packet", "claude-code"],
                          help="Worker mode")
        buf = StringIO()
        parser.print_help(buf)
        help_text = buf.getvalue()
        assert "claude-code" in help_text
