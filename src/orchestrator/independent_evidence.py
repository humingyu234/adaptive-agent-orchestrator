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

import difflib
import hashlib
import json
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_GIT_TIMEOUT = 30
_SHELL_OPERATOR_TOKENS = {"|", "||", "&&", ";", "&", ">", ">>", "<", "2>", "2>>"}
_PYTHON_MODULE_CHECKS = {"pytest", "unittest", "ruff", "mypy", "compileall"}
_DIRECT_CHECKS = {"pytest", "ruff", "mypy"}
_NODE_CHECKS = {"test", "lint", "typecheck", "check"}
_AAO_RUNTIME_PREFIXES = (".aao/",)


@dataclass(frozen=True)
class FileSnapshot:
    """Content state for a path at one observation point."""

    content: bytes | None
    mode: int | None = None
    kind: str = "missing"


@dataclass
class GitBaseline:
    """AAO's pre-worker view of a git work tree.

    Only already-dirty paths require stored content.  Files clean before the
    worker can be reconstructed from ``head_sha`` when they later change.
    """

    head_sha: str
    index_diff: bytes = b""
    preexisting_changed_files: list[str] = field(default_factory=list)
    states: dict[str, FileSnapshot] = field(default_factory=dict)


@dataclass
class CheckResult:
    """Outcome of one required check that AAO ran itself."""

    command: str
    exit_code: int
    timed_out: bool
    output_excerpt: str  # tail of combined stdout+stderr, for the audit trail
    rejected: bool = False

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
    baseline_path: str = ""       # observed/aao_baseline.json
    baseline_violations: list[str] = field(default_factory=list)

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


def _git_head(root: Path) -> str:
    r = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def _git_changed_files(root: Path) -> list[str]:
    """Return real changed paths from ``git status --porcelain -z``.

    Captures modified, added, deleted, renamed and untracked files — i.e. the
    real on-disk delta, regardless of what the worker chose to report.
    """
    r = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True, timeout=_GIT_TIMEOUT,
    )
    entries = r.stdout.split(b"\0")
    files: set[str] = set()
    idx = 0
    while idx < len(entries):
        entry = entries[idx]
        idx += 1
        if not entry:
            continue
        status = entry[:2].decode("ascii", errors="replace")
        path = entry[3:].decode("utf-8", errors="replace")
        if not path.startswith(_AAO_RUNTIME_PREFIXES):
            files.add(path)
        if "R" in status or "C" in status:
            if idx < len(entries) and entries[idx]:
                renamed_path = entries[idx].decode("utf-8", errors="replace")
                if not renamed_path.startswith(_AAO_RUNTIME_PREFIXES):
                    files.add(renamed_path)
                idx += 1
    return sorted(files)


def _git_diff(root: Path) -> str:
    """Best-effort patch text vs HEAD (content for tracked changes)."""
    r = subprocess.run(
        ["git", "-C", str(root), "diff", "HEAD"],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT, errors="replace",
    )
    return r.stdout


def _git_index_diff(root: Path) -> bytes:
    """Return the staged/index delta so workers cannot stage existing edits."""
    r = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--binary"],
        capture_output=True, timeout=_GIT_TIMEOUT,
    )
    return r.stdout


def _git_ref_changed_files(root: Path, before_ref: str, after_ref: str) -> list[str]:
    if not before_ref or not after_ref or before_ref == after_ref:
        return []
    r = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "-z", before_ref, after_ref],
        capture_output=True, timeout=_GIT_TIMEOUT,
    )
    return sorted({
        p.decode("utf-8", errors="replace")
        for p in r.stdout.split(b"\0") if p
        and not p.decode("utf-8", errors="replace").startswith(_AAO_RUNTIME_PREFIXES)
    })


def _snapshot_path(path: Path) -> FileSnapshot:
    if not path.exists() and not path.is_symlink():
        return FileSnapshot(None)
    if path.is_symlink():
        return FileSnapshot(str(path.readlink()).encode("utf-8"), kind="symlink")
    if path.is_file():
        return FileSnapshot(
            path.read_bytes(),
            mode=path.stat().st_mode & 0o777,
            kind="file",
        )
    return FileSnapshot(None, kind="directory")


def _snapshot_at_ref(root: Path, ref: str, relative_path: str) -> FileSnapshot:
    r = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{relative_path}"],
        capture_output=True, timeout=_GIT_TIMEOUT,
    )
    if r.returncode != 0:
        return FileSnapshot(None)
    return FileSnapshot(r.stdout, kind="file")


def capture_git_baseline(packet, project_root: str | Path) -> GitBaseline | None:
    """Capture the worktree state immediately before a real worker runs."""
    root = Path(project_root)
    if not _is_git_repo(root):
        return None

    preexisting = _git_changed_files(root)
    baseline = GitBaseline(
        head_sha=_git_head(root),
        index_diff=_git_index_diff(root),
        preexisting_changed_files=preexisting,
        states={path: _snapshot_path(root / path) for path in preexisting},
    )
    observed_dir = packet.packet_root / "observed"
    observed_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = observed_dir / "aao_baseline.json"
    baseline_path.write_text(
        json.dumps({
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "head_sha": baseline.head_sha,
            "index_diff_sha256": hashlib.sha256(baseline.index_diff).hexdigest(),
            "preexisting_changed_files": preexisting,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return baseline


def _changed_since_baseline(root: Path, baseline: GitBaseline) -> tuple[list[str], dict[str, FileSnapshot]]:
    after_head = _git_head(root)
    candidates = set(baseline.preexisting_changed_files)
    candidates.update(_git_changed_files(root))
    candidates.update(_git_ref_changed_files(root, baseline.head_sha, after_head))

    before_states: dict[str, FileSnapshot] = {}
    changed: list[str] = []
    for path in sorted(candidates):
        before = baseline.states.get(path) or _snapshot_at_ref(root, baseline.head_sha, path)
        after = _snapshot_path(root / path)
        before_states[path] = before
        if before != after:
            changed.append(path)
    return changed, before_states


def _render_baseline_diff(
    root: Path,
    changed_files: list[str],
    before_states: dict[str, FileSnapshot],
) -> str:
    chunks: list[str] = []
    for path in changed_files:
        before = before_states[path]
        after = _snapshot_path(root / path)
        if b"\0" in (before.content or b"") or b"\0" in (after.content or b""):
            chunks.append(f"Binary file changed during worker run: {path}\n")
            continue
        before_text = (before.content or b"").decode("utf-8", errors="replace").splitlines(True)
        after_text = (after.content or b"").decode("utf-8", errors="replace").splitlines(True)
        chunks.extend(difflib.unified_diff(
            before_text,
            after_text,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        ))
        if before.mode != after.mode and before.kind == after.kind == "file":
            chunks.append(f"mode change {path}: {before.mode!s} -> {after.mode!s}\n")
    return "".join(chunks)


def validate_required_check(command: str) -> str | None:
    """Return a refusal reason unless *command* is a bounded test/lint check."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"unparseable required check: {exc}"
    if not argv:
        return "empty required check"
    if any(token in _SHELL_OPERATOR_TOKENS for token in argv):
        return "shell operators are not permitted in required checks"

    executable = Path(argv[0]).name
    if executable in _DIRECT_CHECKS:
        return None
    if executable in {"python", "python3", "py"}:
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] in _PYTHON_MODULE_CHECKS:
            return None
        return "python required checks must use an allowed -m test/lint module"
    if executable in {"npm", "pnpm", "yarn"}:
        target = argv[1:3] if len(argv) >= 3 and argv[1] == "run" else argv[1:2]
        if target and target[-1] in _NODE_CHECKS:
            return None
        return "package-manager required checks must run test/lint/typecheck/check"
    return f"command is not an approved required-check runner: {executable}"


def rejected_required_checks(commands: list[str]) -> list[tuple[str, str]]:
    """Return ``(command, reason)`` pairs for checks AAO must not execute."""
    rejected: list[tuple[str, str]] = []
    for command in commands:
        reason = validate_required_check(command)
        if reason:
            rejected.append((command, reason))
    return rejected


def _run_check(command: str, root: Path, timeout: int) -> CheckResult:
    refusal = validate_required_check(command)
    if refusal:
        return CheckResult(command, 126, False, f"rejected required check: {refusal}", True)
    argv = shlex.split(command)
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
    baseline: GitBaseline | None = None,
    run_checks: bool = True,
    check_timeout: int = 300,
) -> IndependentEvidence | None:
    """Observe ground truth in *project_root* after a real worker has run.

    AAO computes the diff and runs the packet's required checks itself, writing
    AAO-owned files into the packet's ``observed/`` directory.  ``check_timeout``
    is the total budget for all required checks in this capture, not a
    per-command allowance.

    Returns ``None`` when *project_root* is not a git work tree, so the caller
    can fall back to worker-reported evidence.
    """
    root = Path(project_root)
    if not _is_git_repo(root):
        return None

    observed_dir = packet.packet_root / "observed"
    observed_dir.mkdir(parents=True, exist_ok=True)

    if baseline is None:
        changed = _git_changed_files(root)
        diff_content = _git_diff(root)
        baseline_path = ""
        baseline_violations: list[str] = []
    else:
        changed, before_states = _changed_since_baseline(root, baseline)
        diff_content = _render_baseline_diff(root, changed, before_states)
        baseline_path = str(observed_dir / "aao_baseline.json")
        baseline_violations = []
        if _git_head(root) != baseline.head_sha:
            baseline_violations.append("worker changed git HEAD during execution")
        if _git_index_diff(root) != baseline.index_diff:
            baseline_violations.append("worker changed the git index during execution")
    diff_path = observed_dir / "aao_diff.patch"
    diff_path.write_text(diff_content, encoding="utf-8")

    checks: list[CheckResult] = []
    test_output_path = ""
    if run_checks and packet.required_checks:
        lines: list[str] = []
        checks_started = time.monotonic()
        for cmd in packet.required_checks:
            remaining = check_timeout - int(time.monotonic() - checks_started)
            if remaining <= 0:
                res = CheckResult(
                    cmd, -1, True,
                    f"not run: AAO required-check budget exhausted after {check_timeout}s",
                )
            else:
                res = _run_check(cmd, root, remaining)
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
        baseline_path=baseline_path,
        baseline_violations=baseline_violations,
    )
