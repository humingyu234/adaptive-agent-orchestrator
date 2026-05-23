"""Worker protocol — file-based task packet contract.

Owns packet file names, serialization, loading, validation, and schema shape.
Runner-independent.  Claude Code specifics live in workers/claude_code.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .control_models import WorkerEvidenceItem, WorkerEvidenceStatus


# =============================================================================
# Packet paths
# =============================================================================

PACKET_ROOT_DIR = ".aao/tasks"


def packet_dir(root: str | Path, run_id: str, task_id: str) -> Path:
    """Return the packet directory for a given run and task."""
    return Path(root) / PACKET_ROOT_DIR / run_id / task_id


def sanitize_path(value: str) -> str:
    """Sanitize a path segment so it stays under the task root.

    Rejects '..' and absolute paths. Only safe relative segments allowed.
    """
    if value.startswith("/") or value.startswith("\\"):
        raise ValueError(f"Absolute path rejected: {value!r}")
    if ".." in value:
        raise ValueError(f"Path traversal rejected: {value!r}")
    return value


# =============================================================================
# File names inside a packet directory
# =============================================================================

class PacketFiles:
    """File names used within a task packet directory."""

    MANIFEST = "manifest.json"
    TASK = "task.md"
    CONSTRAINTS = "constraints.md"
    EXPECTED_EVIDENCE = "expected_evidence.md"
    RESULT = "result.md"
    STATUS = "status.json"
    DIFF = "observed/diff.patch"
    TEST_OUTPUT = "observed/test_output.txt"
    COMMANDS = "observed/commands.jsonl"


# =============================================================================
# Task packet creation
# =============================================================================

@dataclass
class WorkerTaskPacket:
    """A bounded task packet written to disk for an external worker."""

    run_id: str
    task_id: str
    title: str = ""
    objective: str = ""
    worker_kind: str = "claude_code"
    allowed_files: list[str] = field(default_factory=list)
    denied_files: list[str] = field(default_factory=list)
    protected_files: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    expected_evidence: list[str] = field(default_factory=list)
    risk_level: str = "low"
    run_mode: str = "controlled"
    timeout_seconds: int = 600
    project_root: str = "."
    created_at: str = ""

    # ---- creation ----

    @classmethod
    def create(
        cls,
        *,
        project_root: str = ".",
        run_id: str = "",
        task_id: str = "",
        title: str = "",
        objective: str = "",
        worker_kind: str = "claude_code",
        allowed_files: list[str] | None = None,
        denied_files: list[str] | None = None,
        protected_files: list[str] | None = None,
        required_checks: list[str] | None = None,
        expected_evidence: list[str] | None = None,
        risk_level: str = "low",
        run_mode: str = "controlled",
        timeout_seconds: int = 600,
    ) -> WorkerTaskPacket:
        run_id = run_id or _utc_now_compact()
        task_id = task_id or f"task-{_utc_now_compact()}"
        return cls(
            run_id=run_id,
            task_id=task_id,
            title=title or objective[:80],
            objective=objective,
            worker_kind=worker_kind,
            allowed_files=[sanitize_path(f) for f in (allowed_files or [])],
            denied_files=[sanitize_path(f) for f in (denied_files or [])],
            protected_files=[sanitize_path(f) for f in (protected_files or [])],
            required_checks=required_checks or [],
            expected_evidence=expected_evidence or [],
            risk_level=risk_level,
            run_mode=run_mode,
            timeout_seconds=timeout_seconds,
            project_root=project_root,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @property
    def packet_root(self) -> Path:
        return packet_dir(self.project_root, self.run_id, self.task_id)

    # ---- write to disk ----

    def write(self) -> Path:
        """Write the full packet to disk. Returns the packet directory path."""
        root = self.packet_root
        root.mkdir(parents=True, exist_ok=True)
        (root / "observed").mkdir(exist_ok=True)

        _write_text(root / PacketFiles.MANIFEST, json.dumps(self._build_manifest(), indent=2))
        _write_text(root / PacketFiles.TASK, self._render_task_md())
        _write_text(root / PacketFiles.CONSTRAINTS, self._render_constraints_md())
        _write_text(root / PacketFiles.EXPECTED_EVIDENCE, self._render_expected_evidence_md())
        return root

    def _build_manifest(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "title": self.title,
            "objective": self.objective,
            "worker_kind": self.worker_kind,
            "allowed_files": self.allowed_files,
            "denied_files": self.denied_files,
            "protected_files": self.protected_files,
            "required_checks": self.required_checks,
            "expected_evidence": self.expected_evidence,
            "risk_level": self.risk_level,
            "run_mode": self.run_mode,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
        }

    def _render_task_md(self) -> str:
        lines = [
            "# Task",
            "",
            f"**Objective**: {self.objective}",
            "",
            "## Allowed files",
            "",
        ]
        for f in self.allowed_files:
            lines.append(f"- `{f}`")
        if not self.allowed_files:
            lines.append("- (none specified)")
        lines.extend([
            "",
            "## Non-goals",
            "",
            "- Do not change files outside the allowed list.",
            "- Do not bypass permission prompts.",
        ])
        return "\n".join(lines) + "\n"

    def _render_constraints_md(self) -> str:
        lines = [
            "# Constraints",
            "",
            f"**Risk level**: {self.risk_level}",
            "",
            "## Denied files (do not touch)",
            "",
        ]
        for f in self.denied_files:
            lines.append(f"- `{f}`")
        if not self.denied_files:
            lines.append("- (none specified)")
        if self.protected_files:
            lines.extend([
                "",
                "## Protected files (reviewer must approve)",
                "",
            ])
            for f in self.protected_files:
                lines.append(f"- `{f}`")
        if self.required_checks:
            lines.extend([
                "",
                "## Required checks",
                "",
            ])
            for c in self.required_checks:
                lines.append(f"- `{c}`")
        return "\n".join(lines) + "\n"

    def _render_expected_evidence_md(self) -> str:
        lines = [
            "# Expected Evidence",
            "",
            "After completing the task, write the following:",
            "",
            "## result.md (required)",
            "",
            "- What you changed and why",
            "- What tests ran and their outcomes",
            "- What risks remain",
            "- Follow-up recommendations",
            "",
        ]
        for e in self.expected_evidence:
            lines.append(f"- `{e}`")
        if not self.expected_evidence:
            lines.append("- (no specific evidence files required)")
        return "\n".join(lines) + "\n"


# =============================================================================
# Result loading
# =============================================================================

def load_worker_status(packet_path: Path) -> dict[str, Any]:
    """Load status.json from a completed packet. Returns empty dict if missing."""
    status_path = packet_path / PacketFiles.STATUS
    if not status_path.exists():
        return {}
    return json.loads(status_path.read_text(encoding="utf-8"))


def load_worker_result_text(packet_path: Path) -> str:
    """Load result.md text. Returns '' if missing."""
    result_path = packet_path / PacketFiles.RESULT
    if not result_path.exists():
        return ""
    return result_path.read_text(encoding="utf-8")


def load_observed_file(packet_path: Path, relative_path: str) -> str | None:
    """Load an observed evidence file. Returns None if missing."""
    safe = sanitize_path(relative_path)
    full = packet_path / safe
    if not full.exists() or not full.is_file():
        return None
    return full.read_text(encoding="utf-8", errors="replace")


def list_observed_files(packet_path: Path) -> list[str]:
    """List all files under observed/ relative to packet root."""
    observed_dir = packet_path / "observed"
    if not observed_dir.is_dir():
        return []
    result: list[str] = []
    for f in observed_dir.rglob("*"):
        if f.is_file():
            result.append(str(f.relative_to(packet_path)).replace("\\", "/"))
    return sorted(result)


# =============================================================================
# Evidence classification
# =============================================================================

def classify_worker_evidence(
    *,
    packet_path: Path,
    expected_evidence: list[str],
    worker_kind: str = "claude_code",
    denied_files: list[str] | None = None,
) -> WorkerEvidenceStatus:
    """Inspect a completed packet and classify evidence status.

    Observed: file exists on disk under observed/.
    Reported: worker claims it in status.json but no file on disk.
    Missing: required by expected_evidence but neither observed nor reported.

    *denied_files* is the authoritative deny-list from the manifest (AAO-side).
    When provided, it replaces the worker-reported list in status.json so that
    a worker cannot hide a denied-file change by omitting the field.
    """
    status_data = load_worker_status(packet_path)
    result_text = load_worker_result_text(packet_path)
    observed_files = list_observed_files(packet_path)

    worker_status = status_data.get("status", "unknown")

    changed_files = status_data.get("changed_files", [])
    if not changed_files and result_text:
        changed_files = _extract_changed_files_from_result(result_text)

    items: list[WorkerEvidenceItem] = []
    for key in expected_evidence:
        observed_path = _find_observed_path(observed_files, key)
        if observed_path:
            items.append(WorkerEvidenceItem(
                key=key, status="observed", path=observed_path,
                description=f"Found at {observed_path}",
            ))
        elif status_data.get(key):
            items.append(WorkerEvidenceItem(
                key=key, status="reported", path="",
                description="Worker claims this exists but no file found",
            ))
        else:
            items.append(WorkerEvidenceItem(
                key=key, status="missing", path="",
                description=f"Required evidence '{key}' not found",
            ))

    # Detect denied file changes — use caller-supplied deny-list when available,
    # falling back to worker-reported list only when the caller provides nothing.
    denied_changed: list[str] = []
    deny_list = denied_files if denied_files is not None else status_data.get("denied_files", [])
    for f in changed_files:
        if _matches_any(f, deny_list):
            denied_changed.append(f)

    return WorkerEvidenceStatus(
        task_id=status_data.get("task_id", packet_path.name),
        worker_kind=worker_kind,
        worker_status=worker_status,
        items=items,
        reported_summary=result_text[:500] if result_text else "",
        changed_files=changed_files,
        denied_files_changed=denied_changed,
    )


def classify_worker_evidence_from_packet(
    packet: WorkerTaskPacket,
) -> WorkerEvidenceStatus:
    """Shorthand: classify evidence from a WorkerTaskPacket."""
    return classify_worker_evidence(
        packet_path=packet.packet_root,
        expected_evidence=packet.expected_evidence,
        worker_kind=packet.worker_kind,
        denied_files=packet.denied_files,
    )


def load_manifest(packet_path: Path) -> dict[str, Any]:
    """Load manifest.json from a packet directory."""
    manifest_path = packet_path / PacketFiles.MANIFEST
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


# =============================================================================
# Helpers
# =============================================================================

def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _find_observed_path(observed_files: list[str], key: str) -> str | None:
    """Match an expected evidence key to an observed file path."""
    key_lower = key.lower().replace(" ", "_").replace("-", "_")
    for f in observed_files:
        f_lower = f.lower().replace(" ", "_").replace("-", "_")
        if key_lower in f_lower or f_lower.endswith("/" + key_lower):
            return f
    return None


def _matches_any(filepath: str, denied: list[str]) -> bool:
    """Check if a filepath matches any denied pattern."""
    for pattern in denied:
        if filepath == pattern or filepath.startswith(pattern.rstrip("/") + "/"):
            return True
    return False


def _extract_changed_files_from_result(result_text: str) -> list[str]:
    """Extract changed file paths from result.md when status.json is sparse."""
    files: list[str] = []
    for line in result_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- `") and stripped.endswith("`"):
            path = stripped[3:-1].strip()
            if path and not path.startswith("#"):
                files.append(path)
    return files
