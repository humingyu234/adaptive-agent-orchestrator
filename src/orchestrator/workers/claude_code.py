"""Claude Code worker adapter — task rendering, result loading, and subprocess execution.

Owns Claude Code specific instruction formatting and real subprocess worker launch.
Does NOT own policy, recovery, evaluation, or evidence classification — those
live in the orchestrator layer.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..worker_protocol import (
    PacketFiles,
    WorkerTaskPacket,
    load_manifest,
    load_observed_file,
    load_worker_result_text,
    load_worker_status,
)


# =============================================================================
# Task rendering
# =============================================================================


def render_claude_code_task(packet: WorkerTaskPacket) -> str:
    """Render a WorkerTaskPacket as a Claude Code natural-language instruction.

    Returns a string the user can paste directly into Claude Code or that
    Claude Code can read from task.md.
    """
    return _DEFAULT_RENDERER.render(packet)


@dataclass
class ClaudeCodeTaskRenderer:
    """Renders WorkerTaskPacket -> Claude Code natural-language task."""

    def render(self, packet: WorkerTaskPacket) -> str:
        lines: list[str] = []
        self._append_header(lines, packet)
        self._append_worker_rules(lines)
        self._append_objective(lines, packet)
        self._append_allowed_files(lines, packet)
        self._append_denied_files(lines, packet)
        self._append_protected_files(lines, packet)
        self._append_required_checks(lines, packet)
        self._append_evidence(lines, packet)
        self._append_non_goals(lines, packet)
        self._append_handoff(lines, packet)
        return "\n".join(lines) + "\n"

    # -- sections ----------------------------------------------------------

    def _append_header(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        lines.extend([
            f"# Task: {packet.title or packet.objective[:80]}",
            "",
            f"**Task ID**: `{packet.task_id}`",
            f"**Run ID**: `{packet.run_id}`",
            f"**Risk level**: {packet.risk_level}",
            f"**Mode**: {packet.run_mode}",
            "",
        ])

    def _append_worker_rules(self, lines: list[str]) -> None:
        lines.extend([
            "你是 AAO worker，非交互模式。用工具验证信息，不要猜。写完 result.md 就停。",
            "",
        ])

    def _append_objective(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        lines.extend([
            "## Objective",
            "",
            packet.objective or "(no objective specified)",
            "",
        ])

    def _append_allowed_files(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        lines.append("## Allowed Files")
        lines.append("")
        if packet.allowed_files:
            lines.append("Only modify files in this list:")
            lines.append("")
            for f in packet.allowed_files:
                lines.append(f"- `{f}`")
        elif _is_read_only_packet(packet):
            lines.append("- Read-only task. Do not modify project files.")
        else:
            lines.append("- (no allowlist — all files may be in scope)")
        lines.append("")

    def _append_denied_files(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        lines.append("## Denied Files (do NOT touch)")
        lines.append("")
        if packet.denied_files:
            for f in packet.denied_files:
                lines.append(f"- `{f}`")
        else:
            lines.append("- (none specified)")
        lines.append("")

    def _append_protected_files(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        if not packet.protected_files:
            return
        lines.append("## Protected Files (reviewer must approve changes)")
        lines.append("")
        for f in packet.protected_files:
            lines.append(f"- `{f}`")
        lines.append("")

    def _append_required_checks(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        if not packet.required_checks:
            return
        lines.append("## Required Checks")
        lines.append("")
        lines.append("Run these commands and capture their output:")
        lines.append("")
        for c in packet.required_checks:
            lines.append(f"- `{c}`")
        lines.append("")

    def _append_evidence(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        lines.extend([
            "## Evidence to Write Back",
            "",
            "After completing the task, write the following files in the packet directory:",
            "",
            "### Required: result.md",
            "",
            "Write a summary covering:",
            "- What you changed and why",
            "- What tests ran and their outcomes",
            "- What risks remain",
            "- Follow-up recommendations",
            "",
            "### Required: status.json",
            "",
            "Write a JSON file with at minimum:",
            '```json',
            '{',
            '  "status": "completed" | "failed" | "needs_human_review",',
            '  "task_id": "<task_id>",',
            '  "changed_files": ["path/to/file.py", ...],',
            '  "summary": "<one-line summary>"',
            '}',
            '```',
            "",
            "### If tests were run: observed/test_output.txt",
            "",
            "Capture the full test output.",
            "",
            "### If code was changed: observed/diff.patch",
            "",
            "Capture the diff of all changes.",
            "",
        ])
        if packet.expected_evidence:
            lines.append("### Additional expected evidence")
            lines.append("")
            for e in packet.expected_evidence:
                lines.append(f"- `{e}`")
            lines.append("")

    def _append_non_goals(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        lines.extend([
            "## Non-Goals",
            "",
            "- Do NOT change files outside the allowed list.",
            "- Do NOT bypass permission prompts.",
            "- Do NOT modify denied or protected files.",
            "- Do NOT implement features beyond the stated objective.",
            "",
        ])

    def _append_handoff(self, lines: list[str], packet: WorkerTaskPacket) -> None:
        lines.extend([
            "## Handoff",
            "",
            "When finished:",
            "1. Write `result.md` explaining what changed, what was validated, what remains risky.",
            "2. Write `status.json` with machine-readable status.",
            "3. Write observed evidence files (test output, diff) to the `observed/` directory.",
            "4. Do NOT delete the task packet — AAO will inspect it.",
            "",
            f"Packet directory: `{packet.packet_root}`",
            "",
        ])


_DEFAULT_RENDERER = ClaudeCodeTaskRenderer()


def _is_read_only_packet(packet: WorkerTaskPacket) -> bool:
    return (
        not packet.allowed_files
        and not packet.required_checks
        and not packet.expected_evidence
    )


# =============================================================================
# Result loading
# =============================================================================


def load_claude_code_result(packet_path: Path) -> dict[str, Any]:
    """Load a completed Claude Code worker result from a packet directory.

    Returns a dict with status, result text, changed files, and observed
    evidence paths.  Missing files become empty values — callers must decide
    whether that counts as success.
    """
    status_data = load_worker_status(packet_path)
    result_text = load_worker_result_text(packet_path)
    observed_files = _list_observed_relative(packet_path)

    return {
        "task_id": status_data.get("task_id", packet_path.name),
        "status": status_data.get("status", "unknown"),
        "summary": status_data.get("summary", result_text[:200] if result_text else ""),
        "result_text": result_text,
        "changed_files": status_data.get("changed_files", []),
        "observed_files": observed_files,
        "error": status_data.get("error", ""),
        "worker_kind": "claude_code",
    }


def load_full_packet(packet_path: Path) -> dict[str, Any]:
    """Load everything from a packet directory into one dict.

    Includes manifest, task, constraints, result, status, and observed files.
    """
    manifest = load_manifest(packet_path)
    result = load_claude_code_result(packet_path)

    return {
        "manifest": manifest,
        "result": result,
        "task_md": _read_text_or_empty(packet_path / PacketFiles.TASK),
        "constraints_md": _read_text_or_empty(packet_path / PacketFiles.CONSTRAINTS),
        "expected_evidence_md": _read_text_or_empty(packet_path / PacketFiles.EXPECTED_EVIDENCE),
    }


def _list_observed_relative(packet_path: Path) -> list[str]:
    """List observed files as relative paths from packet root."""
    observed_dir = packet_path / "observed"
    if not observed_dir.is_dir():
        return []
    result: list[str] = []
    for f in observed_dir.rglob("*"):
        if f.is_file():
            result.append(str(f.relative_to(packet_path)).replace("\\", "/"))
    return sorted(result)


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# =============================================================================
# Real subprocess worker (Phase 18)
# =============================================================================


@dataclass
class ClaudeCodeWorkerConfig:
    """Configuration for launching a real Claude Code worker subprocess."""

    command: str = "claude"
    timeout_seconds: int = 600
    prompt_mode: str = "stdin"  # stdin | file
    project_root: str = ""
    extra_args: list[str] = field(default_factory=lambda: ["-p", "--verbose"])

    @classmethod
    def from_env(cls, project_root: str = "") -> "ClaudeCodeWorkerConfig":
        return cls(
            command=os.environ.get("AAO_CLAUDE_CODE_COMMAND", "claude"),
            timeout_seconds=int(os.environ.get("AAO_CLAUDE_CODE_TIMEOUT_SECONDS", "600")),
            prompt_mode=os.environ.get("AAO_CLAUDE_CODE_PROMPT_MODE", "stdin"),
            project_root=project_root,
        )


@dataclass
class WorkerRunResult:
    """Result of a real Claude Code subprocess worker execution."""

    run_id: str = ""
    task_id: str = ""
    packet_dir: str = ""
    exit_code: int = -1
    timed_out: bool = False
    stdout_path: str = ""
    stderr_path: str = ""
    transcript_path: str = ""
    result_md_path: str = ""
    status_json_path: str = ""
    observed_paths: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    summary: str = ""
    worker_status: str = "unknown"
    error: str = ""
    command: str = ""

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_claude_code_worker(
    packet: WorkerTaskPacket,
    *,
    config: ClaudeCodeWorkerConfig | None = None,
) -> WorkerRunResult:
    """Launch a real Claude Code subprocess as a bounded worker.

    1. Renders the packet into a strict task prompt.
    2. Writes the prompt into the task directory for auditability.
    3. Launches the configured Claude Code command via subprocess.
    4. Passes the prompt via stdin (or file, depending on config).
    5. Captures stdout/stderr to observed files.
    6. Waits with timeout.
    7. Loads worker result/status/evidence from the task directory.
    8. Returns WorkerRunResult for ControlPlane/evidence/audit to consume.

    Does NOT call ControlPlane directly — that is the caller's responsibility.
    """
    if config is None:
        config = ClaudeCodeWorkerConfig.from_env()

    pdir = packet.packet_root
    pdir.mkdir(parents=True, exist_ok=True)
    observed_dir = pdir / "observed"
    observed_dir.mkdir(parents=True, exist_ok=True)

    cwd = config.project_root or str(Path.cwd())

    # 1. Render the task prompt
    prompt = render_claude_code_task(packet)

    # 2. Write prompt to task directory for auditability
    task_prompt_path = pdir / "worker_prompt.txt"
    task_prompt_path.write_text(prompt, encoding="utf-8")

    # 3–4. Build the subprocess command
    # -p: print/non-interactive mode
    # --output-format text: plain text output (easier to capture)
    # --verbose: include tool calls in output
    cmd = _build_worker_command(config, prompt, task_prompt_path)
    cmd_display = " ".join(cmd)

    # Setup output capture files
    stdout_path = observed_dir / "worker_stdout.txt"
    stderr_path = observed_dir / "worker_stderr.txt"
    transcript_path = observed_dir / "worker_transcript.txt"
    exit_json_path = observed_dir / "worker_exit.json"

    start_time = time.monotonic()
    timed_out = False
    exit_code = -1
    stdout_text = ""
    stderr_text = ""
    error = ""

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout_text, stderr_text = proc.communicate(
                input=prompt,
                timeout=config.timeout_seconds,
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_text, stderr_text = proc.communicate(timeout=10)
            timed_out = True
            exit_code = -1
            error = f"Worker timed out after {config.timeout_seconds}s"
    except FileNotFoundError:
        error = f"Claude Code command not found: {config.command!r}"
        exit_code = -2
    except PermissionError:
        error = f"Permission denied executing: {config.command!r}"
        exit_code = -3
    except OSError as exc:
        error = f"OS error launching worker: {exc}"
        exit_code = -4

    elapsed = time.monotonic() - start_time

    # 5. Write captured output to observed files
    stdout_path.write_text(stdout_text or "", encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr_text or "", encoding="utf-8", errors="replace")

    # Transcript: combined output
    transcript = (
        f"=== AAO Worker Transcript ===\n"
        f"Command: {cmd_display}\n"
        f"Exit code: {exit_code}\n"
        f"Timed out: {timed_out}\n"
        f"Elapsed: {elapsed:.1f}s\n"
        f"=== STDOUT ===\n{stdout_text}\n"
        f"=== STDERR ===\n{stderr_text}\n"
        f"=== END ===\n"
    )
    transcript_path.write_text(transcript, encoding="utf-8", errors="replace")

    # Exit metadata
    exit_json_path.write_text(
        json.dumps({
            "exit_code": exit_code,
            "timed_out": timed_out,
            "elapsed_seconds": round(elapsed, 2),
            "command": cmd_display,
        }, indent=2),
        encoding="utf-8",
    )

    # 7. Load worker result/status/evidence from the task directory
    result_data = load_claude_code_result(pdir)
    observed = _list_observed_relative(pdir)

    result_md = pdir / "result.md"
    status_json = pdir / "status.json"

    return WorkerRunResult(
        run_id=packet.run_id,
        task_id=packet.task_id,
        packet_dir=str(pdir),
        exit_code=exit_code,
        timed_out=timed_out,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        transcript_path=str(transcript_path),
        result_md_path=str(result_md) if result_md.exists() else "",
        status_json_path=str(status_json) if status_json.exists() else "",
        observed_paths=observed,
        changed_files=result_data.get("changed_files", []),
        summary=result_data.get("summary", ""),
        worker_status=result_data.get("status", "unknown"),
        error=error,
        command=cmd_display,
    )


def _build_worker_command(
    config: ClaudeCodeWorkerConfig,
    prompt: str,
    prompt_file: Path,
) -> list[str]:
    """Build the subprocess command argv list.

    Uses `claude -p` for non-interactive print mode.  The prompt is passed
    via stdin regardless of prompt_mode — the command is always `claude -p -`
    (read from stdin) in its simplest form.

    When prompt_mode == "file", we write the prompt to a file and pass
    `claude -p @file` if the Claude Code version supports it.  Otherwise
    stdin is the safe default.
    """
    # Split the command into argv list so callers can pass "python3 script.py --arg"
    # as a single string without shell=True.
    cmd = shlex.split(config.command) + config.extra_args

    if config.prompt_mode == "file":
        cmd.extend([f"@<{prompt_file}"])
    # stdin mode: -p alone reads from the subprocess stdin pipe

    return cmd
