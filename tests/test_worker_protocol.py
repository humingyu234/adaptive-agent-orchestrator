"""Tests for worker_protocol — packet creation, loading, evidence classification."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from orchestrator.worker_protocol import (
    PacketFiles,
    WorkerTaskPacket,
    classify_worker_evidence,
    classify_worker_evidence_from_packet,
    list_observed_files,
    load_manifest,
    load_observed_file,
    load_worker_result_text,
    load_worker_status,
    packet_dir,
    sanitize_path,
)


# =============================================================================
# sanitize_path
# =============================================================================

class TestSanitizePath:
    def test_normal_relative_path_passes(self):
        assert sanitize_path("src/foo.py") == "src/foo.py"

    def test_absolute_path_rejected(self):
        with pytest.raises(ValueError, match="Absolute path rejected"):
            sanitize_path("/etc/passwd")

    def test_backslash_absolute_path_rejected(self):
        with pytest.raises(ValueError, match="Absolute path rejected"):
            sanitize_path("\\windows\\system32")

    def test_dot_dot_rejected(self):
        with pytest.raises(ValueError, match="Path traversal rejected"):
            sanitize_path("../outside")

    def test_dot_dot_mid_path_rejected(self):
        with pytest.raises(ValueError, match="Path traversal rejected"):
            sanitize_path("foo/../../etc/passwd")


# =============================================================================
# packet_dir
# =============================================================================

class TestPacketDir:
    def test_returns_expected_structure(self):
        result = packet_dir("/project", "run-001", "task-001")
        assert result == Path("/project/.aao/tasks/run-001/task-001")

    def test_works_with_strings(self):
        result = packet_dir(".", "r1", "t1")
        assert result == Path(".aao/tasks/r1/t1")


# =============================================================================
# PacketFiles
# =============================================================================

class TestPacketFiles:
    def test_manifest_name(self):
        assert PacketFiles.MANIFEST == "manifest.json"

    def test_task_name(self):
        assert PacketFiles.TASK == "task.md"

    def test_constraints_name(self):
        assert PacketFiles.CONSTRAINTS == "constraints.md"

    def test_result_name(self):
        assert PacketFiles.RESULT == "result.md"

    def test_status_name(self):
        assert PacketFiles.STATUS == "status.json"

    def test_diff_path(self):
        assert "observed" in PacketFiles.DIFF
        assert PacketFiles.DIFF == "observed/diff.patch"

    def test_test_output_path(self):
        assert PacketFiles.TEST_OUTPUT == "observed/test_output.txt"


# =============================================================================
# WorkerTaskPacket — creation
# =============================================================================

class TestWorkerTaskPacketCreate:
    def test_packet_created_with_defaults(self):
        packet = WorkerTaskPacket.create(objective="Test task", project_root="/tmp")
        assert packet.objective == "Test task"
        assert packet.title == "Test task"
        assert packet.worker_kind == "claude_code"
        assert packet.risk_level == "low"
        assert packet.run_mode == "controlled"
        assert packet.project_root == "/tmp"
        assert packet.run_id != ""
        assert packet.task_id != ""
        assert packet.created_at != ""

    def test_packet_uses_provided_ids(self):
        packet = WorkerTaskPacket.create(
            objective="X",
            run_id="my-run",
            task_id="my-task",
        )
        assert packet.run_id == "my-run"
        assert packet.task_id == "my-task"

    def test_packet_sanitizes_allowed_files(self):
        packet = WorkerTaskPacket.create(
            objective="X",
            allowed_files=["src/foo.py", "tests/test_foo.py"],
            denied_files=["src/bar.py"],
        )
        assert "src/foo.py" in packet.allowed_files
        assert "tests/test_foo.py" in packet.allowed_files
        assert "src/bar.py" in packet.denied_files

    def test_packet_title_falls_back_to_objective_prefix(self):
        packet = WorkerTaskPacket.create(
            objective="A" * 100 + "B",
        )
        assert packet.title == ("A" * 80)

    def test_packet_with_all_fields(self):
        packet = WorkerTaskPacket.create(
            project_root=".",
            run_id="r1",
            task_id="t1",
            title="My Task",
            objective="Do something useful",
            allowed_files=["src/a.py"],
            denied_files=["src/b.py"],
            protected_files=["src/c.py"],
            required_checks=["pytest"],
            expected_evidence=["test_output.txt", "diff.patch"],
            risk_level="high",
            run_mode="controlled",
        )
        assert packet.title == "My Task"
        assert "src/a.py" in packet.allowed_files
        assert "src/b.py" in packet.denied_files
        assert "src/c.py" in packet.protected_files
        assert "pytest" in packet.required_checks
        assert "test_output.txt" in packet.expected_evidence
        assert "diff.patch" in packet.expected_evidence
        assert packet.risk_level == "high"


# =============================================================================
# WorkerTaskPacket — write to disk
# =============================================================================

class TestWorkerTaskPacketWrite:
    def test_write_creates_manifest_and_markdown_files(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            run_id="run-01",
            task_id="task-01",
            objective="Write a test",
            allowed_files=["src/test.py"],
            denied_files=["src/secrets.py"],
            required_checks=["python -m pytest"],
            expected_evidence=["test_output.txt"],
        )
        packet_dir = packet.write()

        assert packet_dir.exists()
        assert (packet_dir / "manifest.json").exists()
        assert (packet_dir / "task.md").exists()
        assert (packet_dir / "constraints.md").exists()
        assert (packet_dir / "expected_evidence.md").exists()
        assert (packet_dir / "observed").is_dir()

    def test_manifest_contains_all_fields(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            run_id="r1",
            task_id="t1",
            objective="Do work",
            allowed_files=["a.py"],
            denied_files=["b.py"],
            protected_files=["c.py"],
            required_checks=["check1"],
            expected_evidence=["ev1"],
            risk_level="medium",
        )
        packet_dir = packet.write()
        manifest = json.loads((packet_dir / "manifest.json").read_text())

        assert manifest["run_id"] == "r1"
        assert manifest["task_id"] == "t1"
        assert manifest["objective"] == "Do work"
        assert manifest["worker_kind"] == "claude_code"
        assert manifest["allowed_files"] == ["a.py"]
        assert manifest["denied_files"] == ["b.py"]
        assert manifest["protected_files"] == ["c.py"]
        assert manifest["required_checks"] == ["check1"]
        assert manifest["expected_evidence"] == ["ev1"]
        assert manifest["risk_level"] == "medium"

    def test_task_md_includes_objective_and_allowed_files(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            objective="Fix the bug",
            allowed_files=["src/fix.py"],
        )
        packet_dir = packet.write()
        task_md = (packet_dir / "task.md").read_text()

        assert "Fix the bug" in task_md
        assert "src/fix.py" in task_md

    def test_constraints_md_includes_denied_files(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            objective="X",
            denied_files=["secret.env"],
        )
        packet_dir = packet.write()
        constraints = (packet_dir / "constraints.md").read_text()

        assert "secret.env" in constraints

    def test_constraints_md_includes_protected_files(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            objective="X",
            protected_files=["config.yaml"],
        )
        packet_dir = packet.write()
        constraints = (packet_dir / "constraints.md").read_text()

        assert "config.yaml" in constraints

    def test_constraints_md_includes_required_checks(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            objective="X",
            required_checks=["python -m pytest"],
        )
        packet_dir = packet.write()
        constraints = (packet_dir / "constraints.md").read_text()

        assert "python -m pytest" in constraints


# =============================================================================
# Result loading
# =============================================================================

class TestResultLoading:
    def test_load_worker_status_returns_dict(self, tmp_path):
        status_path = tmp_path / "status.json"
        status_path.write_text(json.dumps({"status": "completed", "task_id": "t1"}))
        result = load_worker_status(tmp_path)
        assert result == {"status": "completed", "task_id": "t1"}

    def test_load_worker_status_missing_file_returns_empty(self, tmp_path):
        result = load_worker_status(tmp_path)
        assert result == {}

    def test_load_worker_result_text_returns_content(self, tmp_path):
        (tmp_path / "result.md").write_text("All tests passed.")
        assert load_worker_result_text(tmp_path) == "All tests passed."

    def test_load_worker_result_text_missing_returns_empty(self, tmp_path):
        assert load_worker_result_text(tmp_path) == ""

    def test_load_observed_file_returns_content(self, tmp_path):
        obs = tmp_path / "observed"
        obs.mkdir()
        (obs / "test_output.txt").write_text("OK")
        assert load_observed_file(tmp_path, "observed/test_output.txt") == "OK"

    def test_load_observed_file_missing_returns_none(self, tmp_path):
        assert load_observed_file(tmp_path, "observed/nope.txt") is None

    def test_load_observed_file_rejects_traversal(self, tmp_path):
        with pytest.raises(ValueError):
            load_observed_file(tmp_path, "../etc/passwd")

    def test_list_observed_files_returns_sorted(self, tmp_path):
        obs = tmp_path / "observed"
        obs.mkdir()
        (obs / "b.txt").write_text("b")
        (obs / "a.txt").write_text("a")
        files = list_observed_files(tmp_path)
        assert files == ["observed/a.txt", "observed/b.txt"]

    def test_list_observed_files_missing_dir_returns_empty(self, tmp_path):
        assert list_observed_files(tmp_path) == []

    def test_load_manifest_returns_dict(self, tmp_path):
        (tmp_path / "manifest.json").write_text(json.dumps({"task_id": "t1"}))
        assert load_manifest(tmp_path) == {"task_id": "t1"}

    def test_load_manifest_missing_returns_empty(self, tmp_path):
        assert load_manifest(tmp_path) == {}


# =============================================================================
# Evidence classification
# =============================================================================

class TestClassifyWorkerEvidence:
    def _make_packet_dir(self, base: Path) -> Path:
        p = base / "packet"
        p.mkdir()
        (p / "observed").mkdir()
        return p

    def test_observed_evidence_is_classified_correctly(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
        }))
        (pdir / "observed" / "test_output.txt").write_text("All tests passed.")

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=["test_output.txt"],
        )
        assert not status.has_missing_required
        items_by_key = {i.key: i.status for i in status.items}
        assert items_by_key["test_output.txt"] == "observed"

    def test_missing_evidence_is_classified_as_missing(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
        }))

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=["test_output.txt"],
        )
        assert status.has_missing_required
        items_by_key = {i.key: i.status for i in status.items}
        assert items_by_key["test_output.txt"] == "missing"

    def test_reported_evidence_without_file_is_reported(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
            "test_output.txt": True,  # worker claims it
        }))

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=["test_output.txt"],
        )
        items_by_key = {i.key: i.status for i in status.items}
        assert items_by_key["test_output.txt"] == "reported"

    def test_diff_patch_counts_as_observed_when_present(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
        }))
        (pdir / "observed" / "diff.patch").write_text("+changed line")

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=["diff.patch"],
        )
        items_by_key = {i.key: i.status for i in status.items}
        assert items_by_key["diff.patch"] == "observed"

    def test_fuzzy_match_finds_evidence(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
        }))
        (pdir / "observed" / "Test_Output.txt").write_text("ok")

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=["test_output.txt"],
        )
        items_by_key = {i.key: i.status for i in status.items}
        assert items_by_key["test_output.txt"] == "observed"

    def test_malformed_status_is_detected(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        # No status.json at all
        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=[],
        )
        assert status.is_malformed

    def test_denied_file_changes_detected_from_caller_list(self, tmp_path):
        """Denied files passed by caller (from manifest) take priority."""
        pdir = self._make_packet_dir(tmp_path)
        # Worker changes a denied file but omits denied_files from status.json
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
            "changed_files": ["src/secrets.py"],
        }))

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=[],
            denied_files=["src/secrets.py", "config/prod.yaml"],
        )
        assert "src/secrets.py" in status.denied_files_changed

    def test_denied_file_changes_detected_fallback_to_status(self, tmp_path):
        """When caller doesn't provide denied_files, fall back to status.json."""
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
            "changed_files": ["src/secrets.py"],
            "denied_files": ["src/secrets.py"],
        }))

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=[],
        )
        assert "src/secrets.py" in status.denied_files_changed

    def test_worker_omitting_denied_files_is_still_caught(self, tmp_path):
        """Worker changes denied file and omits denied_files — caller list catches it."""
        pdir = self._make_packet_dir(tmp_path)
        # status.json has changed_files but NO denied_files field
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
            "changed_files": ["config/prod.yaml"],
        }))

        # Caller passes the real deny-list from manifest
        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=[],
            denied_files=["config/prod.yaml"],
        )
        assert "config/prod.yaml" in status.denied_files_changed

    def test_denied_file_not_changed_passes(self, tmp_path):
        """Worker changes allowed file only — no denied change detected."""
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
            "changed_files": ["src/allowed.py"],
        }))

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=[],
            denied_files=["config/prod.yaml"],
        )
        assert status.denied_files_changed == []

    def test_changed_files_extracted_from_result_when_status_sparse(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
        }))
        (pdir / "result.md").write_text("Changed files:\n- `src/a.py`\n- `src/b.py`")

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=[],
        )
        assert "src/a.py" in status.changed_files
        assert "src/b.py" in status.changed_files

    def test_classify_from_packet_shorthand(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            run_id="r1",
            task_id="t1",
            objective="X",
            expected_evidence=["test_output.txt"],
        )
        packet.write()

        status = classify_worker_evidence_from_packet(packet)
        assert status.has_missing_required

    def test_no_expected_evidence_all_present_is_success(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "completed",
            "task_id": "t1",
        }))

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=[],
        )
        assert not status.has_missing_required
        assert status.items == []

    def test_worker_status_failed_is_reflected(self, tmp_path):
        pdir = self._make_packet_dir(tmp_path)
        (pdir / "status.json").write_text(json.dumps({
            "status": "failed",
            "task_id": "t1",
        }))

        status = classify_worker_evidence(
            packet_path=pdir,
            expected_evidence=[],
        )
        assert status.worker_status == "failed"


# =============================================================================
# Path sanitization integration
# =============================================================================

class TestPathSanitizationIntegration:
    def test_packet_paths_stay_under_task_root(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            objective="X",
            allowed_files=["src/a.py"],
            denied_files=["src/b.py"],
        )
        pdir = packet.write()

        # All paths are relative and within the project root
        assert str(pdir).startswith(root)
        assert ".aao/tasks" in str(pdir)

    def test_task_ids_are_isolated(self, tmp_path):
        root = str(tmp_path)
        p1 = WorkerTaskPacket.create(project_root=root, task_id="t1", objective="A")
        p2 = WorkerTaskPacket.create(project_root=root, task_id="t2", objective="B")

        d1 = p1.write()
        d2 = p2.write()

        assert d1 != d2
        assert str(d1) != str(d2)
