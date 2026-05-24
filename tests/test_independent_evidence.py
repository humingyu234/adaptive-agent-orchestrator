"""Independent evidence capture — AAO observes ground truth, not worker claims.

These tests pin the control-layer thesis: AAO runs the required checks and
computes the file diff *itself*, so a worker that claims success (or hides a
change) cannot pass when reality disagrees.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from orchestrator.independent_evidence import capture_independent_evidence
from orchestrator.mainline_executor import MainlineExecutor
from orchestrator.worker_protocol import (
    WorkerTaskPacket,
    classify_worker_evidence_from_packet,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available"
)


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)


def _commit_all(root: Path, msg: str = "init") -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg], check=True)


def _packet(root: Path, **kw) -> WorkerTaskPacket:
    return WorkerTaskPacket.create(project_root=str(root), run_id="r1", task_id="t1", **kw)


def test_non_git_dir_degrades_to_none(tmp_path: Path):
    """No git work tree → return None so the caller uses reported evidence."""
    packet = _packet(tmp_path)
    assert capture_independent_evidence(packet, tmp_path) is None


def test_git_status_is_authoritative_changed_files(tmp_path: Path):
    """AAO derives changed_files from git, independent of any worker report."""
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n")      # modified
    (tmp_path / "b.py").write_text("new = True\n")  # new / untracked

    ev = capture_independent_evidence(_packet(tmp_path), tmp_path, run_checks=False)
    assert ev is not None
    assert "a.py" in ev.changed_files
    assert "b.py" in ev.changed_files            # untracked is still caught
    assert Path(ev.diff_path).exists()


def test_lying_worker_is_caught_by_real_exit_code(tmp_path: Path):
    """Worker claims success + writes a clean test log, but the real check fails.

    This is the thesis: AAO trusts the process exit code, not the worker's text.
    """
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)

    packet = _packet(tmp_path, required_checks=['python -c "import sys; sys.exit(1)"'])

    # The worker lies: deposits a passing-looking log + a success status.
    (packet.packet_root / "observed").mkdir(parents=True, exist_ok=True)
    (packet.packet_root / "observed" / "test_output.txt").write_text("1 passed in 0.01s\n")
    (packet.packet_root / "status.json").write_text('{"status": "completed"}')

    ev = capture_independent_evidence(packet, tmp_path)
    assert ev is not None
    assert ev.any_check_failed  # real exit code is 1, regardless of the worker's log

    decisions = MainlineExecutor(tmp_path)._check_independent_results(ev)
    assert decisions[0].passed is False
    assert decisions[0].action == "retry"
    assert "failed" in decisions[0].reason.lower()


def test_worker_cannot_hide_a_denied_file_change(tmp_path: Path):
    """Worker omits a denied file from status.json — git status still finds it."""
    _init_repo(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "secrets.yaml").write_text("token: old\n")
    _commit_all(tmp_path)
    (tmp_path / "config" / "secrets.yaml").write_text("token: stolen\n")  # touched

    packet = _packet(tmp_path, denied_files=["config/secrets.yaml"])
    # Worker hides the change.
    (packet.packet_root).mkdir(parents=True, exist_ok=True)
    (packet.packet_root / "status.json").write_text('{"status": "completed", "changed_files": []}')

    ev = capture_independent_evidence(packet, tmp_path, run_checks=False)
    assert ev is not None

    status = classify_worker_evidence_from_packet(
        packet, observed_changed_files=ev.changed_files
    )
    assert "config/secrets.yaml" in status.denied_files_changed


def test_passing_checks_produce_a_clean_decision(tmp_path: Path):
    """Sanity: when the real check passes, AAO reports it passed."""
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)

    packet = _packet(tmp_path, required_checks=['python -c "import sys; sys.exit(0)"'])
    ev = capture_independent_evidence(packet, tmp_path)
    assert ev is not None
    assert not ev.any_check_failed
    assert MainlineExecutor(tmp_path)._check_independent_results(ev)[0].passed is True
