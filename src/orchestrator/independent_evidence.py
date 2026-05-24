"""Independent evidence capture — AAO observes ground truth, not worker claims.

The control-layer thesis is "observed beats claims".  For that to be true,
AAO must *generate* the evidence itself: run the required checks and compute
the file diff in the real working tree, rather than trusting whatever files a
worker chose to deposit under ``observed/``.

This module is the AAO-side observer.  It writes AAO-owned evidence files
(``aao_`` prefix) so they can never be confused with worker-written ones, and
returns the authoritative changed-file list plus real check exit codes.

Graceful degradation: when ``project_root`` is not a git work tree (or git is
unavailable), :func:`capture_independent_evidence` returns ``None`` and the
caller falls back to worker-reported evidence — which is then correctly
labelled "reported", not "observed".
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_GIT_TIMEOUT = 30


@dataclass
class CheckResult:
    """Outcome of one required check that AAO ran itself."""

    command: str
    exit_code: int
    timed_out: bool
    output_excerpt: str  # tail of combined stdout+stderr, for the audit trail

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class IndependentEvidence:
    """Ground truth observed by AAO itself (never the worker's self-report)."""

    changed_files: list[str] = field(default_factory=list)
    diff_path: str = ""           # observed/aao_diff.patch
    test_output_path: str = ""    # observed/aao_test_output.txt
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def any_check_failed(self) -> bool:
        return any(not c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


def _is_git_repo(root: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def _git_changed_files(root: Path) -> list[str]:
    """Authoritative changed-file list from ``git status --porcelain``.

    Captures modified, added, deleted, renamed and untracked files — i.e. the
    real on-disk delta, regardless of what the worker chose to report.
    """
    r = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT,
    )
    files: list[str] = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain v1: "XY <path>", or "XY <old> -> <new>" for renames/copies.
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip().strip('"')
        files.append(path)
    return sorted(set(files))


def _git_diff(root: Path) -> str:
    """Best-effort patch text vs HEAD (content for tracked changes)."""
    r = subprocess.run(
        ["git", "-C", str(root), "diff", "HEAD"],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT, errors="replace",
    )
    return r.stdout


def _run_check(command: str, root: Path, timeout: int) -> CheckResult:
    try:
        argv = shlex.split(command)
    except ValueError:
        return CheckResult(command, -1, False, f"unparseable command: {command!r}")
    if not argv:
        return CheckResult(command, -1, False, "empty command")
    try:
        r = subprocess.run(
            argv, cwd=str(root), capture_output=True, text=True,
            timeout=timeout, errors="replace",
        )
        combined = (r.stdout or "") + (r.stderr or "")
        return CheckResult(command, r.returncode, False, combined[-4000:])
    except subprocess.TimeoutExpired:
        return CheckResult(command, -1, True, f"timed out after {timeout}s")
    except FileNotFoundError:
        return CheckResult(command, 127, False, f"command not found: {argv[0]}")
    except OSError as exc:
        return CheckResult(command, -1, False, f"os error: {exc}")


def capture_independent_evidence(
    packet,
    project_root: str | Path,
    *,
    run_checks: bool = True,
    check_timeout: int = 300,
) -> IndependentEvidence | None:
    """Observe ground truth in *project_root* after a real worker has run.

    AAO computes the diff and runs the packet's required checks itself, writing
    AAO-owned files into the packet's ``observed/`` directory.

    Returns ``None`` when *project_root* is not a git work tree, so the caller
    can fall back to worker-reported evidence.
    """
    root = Path(project_root)
    if not _is_git_repo(root):
        return None

    observed_dir = packet.packet_root / "observed"
    observed_dir.mkdir(parents=True, exist_ok=True)

    changed = _git_changed_files(root)
    diff_path = observed_dir / "aao_diff.patch"
    diff_path.write_text(_git_diff(root), encoding="utf-8")

    checks: list[CheckResult] = []
    test_output_path = ""
    if run_checks and packet.required_checks:
        lines: list[str] = []
        for cmd in packet.required_checks:
            res = _run_check(cmd, root, check_timeout)
            checks.append(res)
            verdict = "PASS" if res.passed else "FAILED"
            lines.append(f"=== AAO CHECK: {cmd} -> {verdict} (exit {res.exit_code}) ===")
            lines.append(res.output_excerpt)
            lines.append("")
        out_path = observed_dir / "aao_test_output.txt"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        test_output_path = str(out_path)

    return IndependentEvidence(
        changed_files=changed,
        diff_path=str(diff_path),
        test_output_path=test_output_path,
        checks=checks,
    )
