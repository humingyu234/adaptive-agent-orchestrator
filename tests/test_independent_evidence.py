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

from orchestrator.independent_evidence import (
    IndependentEvidence,
    capture_git_baseline,
    capture_independent_evidence,
    validate_required_check,
)
from orchestrator.mainline_executor import MainlineExecutor
from orchestrator.planning import PlanContract, PlannedWorkerTask
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

    (tmp_path / "test_failure.py").write_text("def test_failure():\n    assert False\n")
    packet = _packet(tmp_path, required_checks=["python -m pytest test_failure.py -q"])

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

    (tmp_path / "test_success.py").write_text("def test_success():\n    assert True\n")
    packet = _packet(tmp_path, required_checks=["python -m pytest test_success.py -q"])
    ev = capture_independent_evidence(packet, tmp_path)
    assert ev is not None
    assert not ev.any_check_failed
    assert MainlineExecutor(tmp_path)._check_independent_results(ev)[0].passed is True


def test_baseline_excludes_dirty_files_untouched_by_worker(tmp_path: Path):
    """A pre-existing local edit must not be attributed to this worker run."""
    _init_repo(tmp_path)
    (tmp_path / "old.py").write_text("value = 1\n")
    (tmp_path / "new.py").write_text("value = 1\n")
    _commit_all(tmp_path)

    (tmp_path / "old.py").write_text("value = 'already dirty'\n")
    packet = _packet(tmp_path)
    baseline = capture_git_baseline(packet, tmp_path)
    (tmp_path / "new.py").write_text("value = 'worker edit'\n")

    ev = capture_independent_evidence(packet, tmp_path, baseline=baseline, run_checks=False)
    assert ev is not None
    assert ev.changed_files == ["new.py"]
    assert "old.py" not in Path(ev.diff_path).read_text(encoding="utf-8")


def test_baseline_detects_worker_edit_to_already_dirty_file(tmp_path: Path):
    """If the worker edits a dirty file again, that new delta is still caught."""
    _init_repo(tmp_path)
    (tmp_path / "shared.py").write_text("value = 1\n")
    _commit_all(tmp_path)

    (tmp_path / "shared.py").write_text("value = 'user edit'\n")
    packet = _packet(tmp_path)
    baseline = capture_git_baseline(packet, tmp_path)
    (tmp_path / "shared.py").write_text("value = 'worker edit'\n")

    ev = capture_independent_evidence(packet, tmp_path, baseline=baseline, run_checks=False)
    assert ev is not None
    assert ev.changed_files == ["shared.py"]
    diff = Path(ev.diff_path).read_text(encoding="utf-8")
    assert "-value = 'user edit'" in diff
    assert "+value = 'worker edit'" in diff


def test_baseline_detects_worker_staging_preexisting_dirty_file(tmp_path: Path):
    """A worker cannot hide activity by staging a user's existing dirty edit."""
    _init_repo(tmp_path)
    (tmp_path / "shared.py").write_text("value = 1\n")
    _commit_all(tmp_path)
    (tmp_path / "shared.py").write_text("value = 'user edit'\n")
    packet = _packet(tmp_path)
    baseline = capture_git_baseline(packet, tmp_path)

    subprocess.run(["git", "-C", str(tmp_path), "add", "shared.py"], check=True)
    ev = capture_independent_evidence(packet, tmp_path, baseline=baseline, run_checks=False)

    assert ev is not None
    assert "worker changed the git index during execution" in ev.baseline_violations
    decision = MainlineExecutor(tmp_path)._check_baseline_integrity(ev)[0]
    assert decision.action == "needs_human_review"


def test_baseline_detects_worker_committing_preexisting_dirty_file(tmp_path: Path):
    """A worker commit is visible even if worktree content matches the baseline."""
    _init_repo(tmp_path)
    (tmp_path / "shared.py").write_text("value = 1\n")
    _commit_all(tmp_path)
    (tmp_path / "shared.py").write_text("value = 'user edit'\n")
    packet = _packet(tmp_path)
    baseline = capture_git_baseline(packet, tmp_path)

    subprocess.run(["git", "-C", str(tmp_path), "add", "shared.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "worker commit"], check=True)
    ev = capture_independent_evidence(packet, tmp_path, baseline=baseline, run_checks=False)

    assert ev is not None
    assert ev.changed_files == []
    assert "worker changed git HEAD during execution" in ev.baseline_violations
    assert MainlineExecutor(tmp_path)._check_baseline_integrity(ev)[0].passed is False


def test_unsafe_required_check_is_rejected_without_execution(tmp_path: Path):
    """AAO must not execute arbitrary shell commands presented as checks."""
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)
    packet = _packet(tmp_path, required_checks=["rm -rf ."])

    ev = capture_independent_evidence(packet, tmp_path)
    assert ev is not None
    assert ev.checks[0].rejected is True
    assert (tmp_path / "a.py").exists()
    decisions = MainlineExecutor(tmp_path)._check_independent_results(ev)
    assert decisions[0].action == "needs_human_review"
    assert decisions[0].failure_category == "policy_error"


def test_required_check_policy_accepts_bounded_test_commands():
    assert validate_required_check("pytest -q") is None
    assert validate_required_check("python -m pytest tests/test_one.py -q") is None
    assert validate_required_check("python -c 'print(1)'") is not None


def test_required_checks_share_one_total_timeout_budget(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)
    packet = _packet(tmp_path, required_checks=["python -m pytest -q"])

    ev = capture_independent_evidence(packet, tmp_path, check_timeout=0)

    assert ev is not None
    assert ev.checks[0].timed_out is True
    assert "budget exhausted" in ev.checks[0].output_excerpt


def test_mainline_blocks_unsafe_check_before_worker_launch(tmp_path: Path, monkeypatch):
    """A poisoned plan is rejected before a real Claude worker is dispatched."""
    plan = PlanContract(
        objective="Modify src/app.py",
        run_mode="controlled",
        task_size="medium",
        steps=["Implement"],
        required_evidence=["test_output.txt", "diff.patch"],
        success_criteria=["Checks pass"],
        planned_worker_tasks=[PlannedWorkerTask(
            title="Modify app",
            objective="Modify src/app.py",
            allowed_files=["src/app.py"],
            required_checks=["rm -rf ."],
            expected_evidence=["test_output.txt", "diff.patch"],
        )],
    )
    plan.approve()
    executor = MainlineExecutor(tmp_path)
    monkeypatch.setattr(
        executor,
        "_execute_claude_code_worker",
        lambda _packet: pytest.fail("worker must not start for unsafe required_checks"),
    )

    result = executor.execute(plan, worker_mode="claude-code")

    assert result.status == "blocked_needs_review"
    assert "Unsafe required_checks" in result.summary


def test_mainline_requires_git_baseline_before_real_worker_launch(tmp_path: Path, monkeypatch):
    """A non-git project cannot claim independently attributed code evidence."""
    plan = PlanContract(
        objective="Modify src/app.py",
        run_mode="controlled",
        task_size="medium",
        steps=["Implement"],
        required_evidence=["test_output.txt", "diff.patch"],
        success_criteria=["Checks pass"],
        planned_worker_tasks=[PlannedWorkerTask(
            title="Modify app",
            objective="Modify src/app.py",
            allowed_files=["src/app.py"],
            required_checks=["pytest -q"],
            expected_evidence=["test_output.txt", "diff.patch"],
        )],
    )
    plan.approve()
    executor = MainlineExecutor(tmp_path)
    monkeypatch.setattr(
        executor,
        "_execute_claude_code_worker",
        lambda _packet: pytest.fail("worker must not start without a git baseline"),
    )

    result = executor.execute(plan, worker_mode="claude-code")

    assert result.status == "blocked_needs_review"
    assert "requires a git worktree" in result.summary


def test_both_reviewer_layers_use_aao_owned_evidence(tmp_path: Path, monkeypatch):
    """Rule and Codex reviewers must receive the same AAO-owned snapshot."""
    packet = _packet(tmp_path)
    observed = packet.packet_root / "observed"
    observed.mkdir(parents=True)
    (observed / "diff.patch").write_text("worker fake diff", encoding="utf-8")
    (observed / "test_output.txt").write_text("worker fake tests", encoding="utf-8")
    (observed / "aao_diff.patch").write_text("AAO real diff", encoding="utf-8")
    (observed / "aao_test_output.txt").write_text("AAO real tests", encoding="utf-8")
    (packet.packet_root / "status.json").write_text(
        '{"status": "completed", "changed_files": ["worker_fake.py"]}',
        encoding="utf-8",
    )
    independent = IndependentEvidence(changed_files=["aao_real.py"])
    captured: list[object] = []

    class CaptureReviewer:
        def review(self, bundle):
            captured.append(bundle)
            return []

    executor = MainlineExecutor(tmp_path, reviewer=CaptureReviewer())
    executor._run_reviewer(packet, independent)

    from orchestrator.reviewer import CodexReviewer
    monkeypatch.setattr(CodexReviewer, "review", lambda self, bundle: captured.append(bundle) or [])
    executor._run_codex_reviewer(packet, independent)

    assert len(captured) == 2
    for bundle in captured:
        assert bundle.diff_content == "AAO real diff"
        assert bundle.test_output == "AAO real tests"
        assert bundle.changed_files == ["aao_real.py"]
