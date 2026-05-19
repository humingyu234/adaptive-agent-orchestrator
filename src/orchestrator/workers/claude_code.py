"""Claude Code worker adapter — task rendering and result loading.

Owns Claude Code specific instruction formatting.  Does NOT own policy,
recovery, evaluation, or evidence classification — those live in the
orchestrator layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
