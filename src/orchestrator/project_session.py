"""Phase 24 — Project Session Layer.

Persistent, file-based project sessions that survive process restarts.
AAO graduates from single-task executor to project collaborator —
it remembers goals, milestones, decisions, and evidence across sessions.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# =============================================================================
# Data models
# =============================================================================


@dataclass
class ProjectMilestone:
    """A named, gated stage within a project."""

    milestone_id: str
    name: str
    description: str = ""
    status: str = "pending"  # pending | in_progress | completed | blocked
    plan_step_ids: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # milestone IDs
    approval_required: bool = False
    approved_by: str | None = None  # "human" or None
    approved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "plan_step_ids": self.plan_step_ids,
            "depends_on": self.depends_on,
            "approval_required": self.approval_required,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProjectMilestone:
        return cls(
            milestone_id=d.get("milestone_id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            status=d.get("status", "pending"),
            plan_step_ids=d.get("plan_step_ids", []),
            depends_on=d.get("depends_on", []),
            approval_required=d.get("approval_required", False),
            approved_by=d.get("approved_by"),
            approved_at=d.get("approved_at", ""),
        )


@dataclass
class DecisionLog:
    """Immutable record of a decision made during the project."""

    entry_id: str
    timestamp: str
    decision: str
    reason: str
    alternatives: list[str] = field(default_factory=list)
    made_by: str = "control_plane"  # control_plane | human | planning_council
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "decision": self.decision,
            "reason": self.reason,
            "alternatives": self.alternatives,
            "made_by": self.made_by,
            "evidence_refs": self.evidence_refs,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionLog:
        return cls(
            entry_id=d.get("entry_id", ""),
            timestamp=d.get("timestamp", ""),
            decision=d.get("decision", ""),
            reason=d.get("reason", ""),
            alternatives=d.get("alternatives", []),
            made_by=d.get("made_by", "control_plane"),
            evidence_refs=d.get("evidence_refs", []),
        )


@dataclass
class ProjectRunLink:
    """Links a milestone to a specific MainlineExecutor run."""

    milestone_id: str
    run_id: str
    evidence_path: str = ""
    audit_path: str = ""
    status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "run_id": self.run_id,
            "evidence_path": self.evidence_path,
            "audit_path": self.audit_path,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProjectRunLink:
        return cls(
            milestone_id=d.get("milestone_id", ""),
            run_id=d.get("run_id", ""),
            evidence_path=d.get("evidence_path", ""),
            audit_path=d.get("audit_path", ""),
            status=d.get("status", ""),
        )


@dataclass
class MilestoneApproval:
    """Approval record for a milestone gate (Phase 25).

    Created when a milestone finishes execution.  The human reviews the
    evidence package and chooses approve / reject / request-changes.
    """

    milestone_id: str
    status: str = "awaiting_approval"  # awaiting_approval | approved | rejected | changes_requested
    approved_by: str | None = None  # "human"
    approved_at: str = ""
    rejection_reason: str = ""
    changes_requested_notes: str = ""

    # Evidence package — what the human is approving
    evidence_summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    test_results_summary: str = ""
    reviewer_findings: list[str] = field(default_factory=list)
    repair_history: list[str] = field(default_factory=list)
    open_risks: list[str] = field(default_factory=list)

    def approve(self) -> None:
        self.status = "approved"
        self.approved_by = "human"
        self.approved_at = _now()

    def reject(self, reason: str = "") -> None:
        self.status = "rejected"
        self.rejection_reason = reason
        self.approved_at = _now()

    def request_changes(self, notes: str = "") -> None:
        self.status = "changes_requested"
        self.changes_requested_notes = notes
        self.approved_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "rejection_reason": self.rejection_reason,
            "changes_requested_notes": self.changes_requested_notes,
            "evidence_summary": self.evidence_summary,
            "files_changed": self.files_changed,
            "test_results_summary": self.test_results_summary,
            "reviewer_findings": self.reviewer_findings,
            "repair_history": self.repair_history,
            "open_risks": self.open_risks,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MilestoneApproval:
        return cls(
            milestone_id=d.get("milestone_id", ""),
            status=d.get("status", "awaiting_approval"),
            approved_by=d.get("approved_by"),
            approved_at=d.get("approved_at", ""),
            rejection_reason=d.get("rejection_reason", ""),
            changes_requested_notes=d.get("changes_requested_notes", ""),
            evidence_summary=d.get("evidence_summary", ""),
            files_changed=d.get("files_changed", []),
            test_results_summary=d.get("test_results_summary", ""),
            reviewer_findings=d.get("reviewer_findings", []),
            repair_history=d.get("repair_history", []),
            open_risks=d.get("open_risks", []),
        )


@dataclass
class SessionContext:
    """Assembled at resume/ask time to answer questions.

    Named SessionContext to avoid collision with the file-tree scanner
    ``ProjectContext`` in project_context.py.
    """

    goal: str = ""
    current_milestone: ProjectMilestone | None = None
    completed_milestones: list[ProjectMilestone] = field(default_factory=list)
    recent_decisions: list[DecisionLog] = field(default_factory=list)
    important_design_choices: list[DecisionLog] = field(default_factory=list)
    open_risks: list[str] = field(default_factory=list)
    evidence_links: dict[str, str] = field(default_factory=dict)
    audit_links: dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectSession:
    """Top-level project session — persisted to session.json."""

    project_id: str
    goal: str = ""
    status: str = "active"  # active | paused | completed | abandoned
    created_at: str = ""
    last_active_at: str = ""
    current_milestone: str | None = None
    completed_milestones: list[str] = field(default_factory=list)
    pending_decisions: list[str] = field(default_factory=list)
    open_risks: list[str] = field(default_factory=list)
    next_recommended_action: str | None = None

    def __post_init__(self) -> None:
        now = _now()
        if not self.created_at:
            self.created_at = now
        if not self.last_active_at:
            self.last_active_at = now

    def touch(self) -> None:
        self.last_active_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "goal": self.goal,
            "status": self.status,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "current_milestone": self.current_milestone,
            "completed_milestones": self.completed_milestones,
            "pending_decisions": self.pending_decisions,
            "open_risks": self.open_risks,
            "next_recommended_action": self.next_recommended_action,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProjectSession:
        return cls(
            project_id=d.get("project_id", ""),
            goal=d.get("goal", ""),
            status=d.get("status", "active"),
            created_at=d.get("created_at", ""),
            last_active_at=d.get("last_active_at", ""),
            current_milestone=d.get("current_milestone"),
            completed_milestones=d.get("completed_milestones", []),
            pending_decisions=d.get("pending_decisions", []),
            open_risks=d.get("open_risks", []),
            next_recommended_action=d.get("next_recommended_action"),
        )


# =============================================================================
# Storage
# =============================================================================


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class ProjectSessionStore:
    """File-based persistence for project sessions.

    Directory layout::

        .aao/sessions/<project_id>/
          session.json
          milestones.json
          decision_log.jsonl
          run_links.jsonl
          project_context.json
    """

    def __init__(self, project_root: Path | str = ".") -> None:
        self._root = Path(project_root)
        self._sessions_dir = self._root / ".aao" / "sessions"

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _session_dir(self, project_id: str) -> Path:
        return self._sessions_dir / project_id

    def _session_path(self, project_id: str) -> Path:
        return self._session_dir(project_id) / "session.json"

    def _milestones_path(self, project_id: str) -> Path:
        return self._session_dir(project_id) / "milestones.json"

    def _decision_log_path(self, project_id: str) -> Path:
        return self._session_dir(project_id) / "decision_log.jsonl"

    def _run_links_path(self, project_id: str) -> Path:
        return self._session_dir(project_id) / "run_links.jsonl"

    def _context_path(self, project_id: str) -> Path:
        return self._session_dir(project_id) / "project_context.json"

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def create_session(self, goal: str, project_id: str | None = None) -> ProjectSession:
        """Create a new project session and persist it."""
        pid = project_id or _new_id()
        session = ProjectSession(project_id=pid, goal=goal)
        session_dir = self._session_dir(pid)
        session_dir.mkdir(parents=True, exist_ok=True)
        self._write_session(session)
        self._write_milestones(pid, [])
        return session

    def load_session(self, project_id: str) -> ProjectSession | None:
        """Load a session from disk, or None if not found."""
        path = self._session_path(project_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProjectSession.from_dict(data)

    def save_session(self, session: ProjectSession) -> None:
        """Persist an updated session."""
        session.touch()
        self._write_session(session)

    def close_session(self, project_id: str) -> ProjectSession | None:
        """Mark a session as completed. Returns None if not found."""
        session = self.load_session(project_id)
        if session is None:
            return None
        if session.status == "completed":
            return session
        session.status = "completed"
        self.save_session(session)
        return session

    def list_sessions(self) -> list[dict[str, str]]:
        """List all known project sessions."""
        if not self._sessions_dir.exists():
            return []
        result: list[dict[str, str]] = []
        for d in sorted(self._sessions_dir.iterdir()):
            if not d.is_dir():
                continue
            sp = d / "session.json"
            if not sp.exists():
                continue
            try:
                s = json.loads(sp.read_text(encoding="utf-8"))
                result.append({
                    "project_id": s.get("project_id", d.name),
                    "goal": s.get("goal", ""),
                    "status": s.get("status", "unknown"),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return result

    # ------------------------------------------------------------------
    # Milestones
    # ------------------------------------------------------------------

    def load_milestones(self, project_id: str) -> list[ProjectMilestone]:
        path = self._milestones_path(project_id)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [ProjectMilestone.from_dict(m) for m in data]

    def save_milestones(self, project_id: str, milestones: list[ProjectMilestone]) -> None:
        self._write_milestones(project_id, milestones)

    def get_current_milestone(self, project_id: str) -> ProjectMilestone | None:
        session = self.load_session(project_id)
        if session is None or session.current_milestone is None:
            return None
        milestones = self.load_milestones(project_id)
        for m in milestones:
            if m.milestone_id == session.current_milestone:
                return m
        return None

    def advance_milestone(
        self, project_id: str, milestone_id: str, new_status: str
    ) -> ProjectSession | None:
        """Transition a milestone to a new status and update the session."""
        session = self.load_session(project_id)
        if session is None:
            return None
        milestones = self.load_milestones(project_id)
        for m in milestones:
            if m.milestone_id == milestone_id:
                m.status = new_status
                break
        self.save_milestones(project_id, milestones)

        if new_status == "completed":
            if milestone_id not in session.completed_milestones:
                session.completed_milestones.append(milestone_id)
        session.current_milestone = milestone_id
        self.save_session(session)
        return session

    # ------------------------------------------------------------------
    # Milestone gate / approval (Phase 25)
    # ------------------------------------------------------------------

    def _approval_path(self, project_id: str) -> Path:
        return self._session_dir(project_id) / "milestone_approvals.json"

    def load_approvals(self, project_id: str) -> list[MilestoneApproval]:
        """Load all milestone approval records."""
        path = self._approval_path(project_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [MilestoneApproval.from_dict(a) for a in data]
        except (json.JSONDecodeError, OSError):
            return []

    def _save_approvals(self, project_id: str, approvals: list[MilestoneApproval]) -> None:
        path = self._approval_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([a.to_dict() for a in approvals], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def submit_for_approval(
        self,
        project_id: str,
        milestone_id: str,
        *,
        evidence_summary: str = "",
        files_changed: list[str] | None = None,
        test_results_summary: str = "",
        reviewer_findings: list[str] | None = None,
        repair_history: list[str] | None = None,
        open_risks: list[str] | None = None,
    ) -> MilestoneApproval | None:
        """Submit a completed milestone for human approval.

        Creates the approval record, sets the milestone status to
        ``paused_for_approval``, and pauses the session.
        Returns None if the milestone doesn't exist.
        """
        session = self.load_session(project_id)
        if session is None:
            return None

        milestones = self.load_milestones(project_id)
        found = False
        for m in milestones:
            if m.milestone_id == milestone_id:
                m.status = "paused_for_approval"
                found = True
                break
        if not found:
            return None

        self.save_milestones(project_id, milestones)

        approval = MilestoneApproval(
            milestone_id=milestone_id,
            status="awaiting_approval",
            evidence_summary=evidence_summary,
            files_changed=list(files_changed or []),
            test_results_summary=test_results_summary,
            reviewer_findings=list(reviewer_findings or []),
            repair_history=list(repair_history or []),
            open_risks=list(open_risks or []),
        )

        approvals = self.load_approvals(project_id)
        # Replace existing approval for same milestone if present
        approvals = [a for a in approvals if a.milestone_id != milestone_id]
        approvals.append(approval)
        self._save_approvals(project_id, approvals)

        session.status = "paused"
        session.pending_decisions.append(f"Approve milestone: {milestone_id}")
        self.save_session(session)

        return approval

    def approve_milestone(self, project_id: str, milestone_id: str) -> MilestoneApproval | None:
        """Approve a milestone and unlock the next one.

        Sets milestone → completed, approval → approved, session → active.
        Returns None if no awaiting approval record exists.
        """
        approvals = self.load_approvals(project_id)
        target = None
        for a in approvals:
            if a.milestone_id == milestone_id and a.status == "awaiting_approval":
                target = a
                break
        if target is None:
            return None

        target.approve()
        self._save_approvals(project_id, approvals)

        # Advance milestone
        self.advance_milestone(project_id, milestone_id, "completed")

        # Activate next pending milestone
        milestones = self.load_milestones(project_id)
        found_next = False
        for m in milestones:
            if m.status == "pending":
                m.status = "in_progress"
                session = self.load_session(project_id)
                if session:
                    session.current_milestone = m.milestone_id
                    session.status = "active"
                    session.pending_decisions = [
                        d for d in session.pending_decisions
                        if f"Approve milestone: {milestone_id}" not in d
                    ]
                    session.next_recommended_action = f"Execute milestone: {m.name}"
                    self.save_session(session)
                self.save_milestones(project_id, milestones)
                found_next = True
                break

        if not found_next:
            session = self.load_session(project_id)
            if session:
                session.current_milestone = None
                session.status = "completed"
                session.next_recommended_action = "All milestones completed."
                self.save_session(session)

        # Log the decision
        self.log_decision(project_id, DecisionLog(
            entry_id=_new_id(),
            timestamp=_now(),
            decision=f"Approved milestone: {milestone_id}",
            reason="Human approved the milestone gate",
            made_by="human",
        ))

        return target

    def reject_milestone(
        self, project_id: str, milestone_id: str, reason: str = ""
    ) -> MilestoneApproval | None:
        """Reject a milestone — generates a need for re-planning."""
        approvals = self.load_approvals(project_id)
        target = None
        for a in approvals:
            if a.milestone_id == milestone_id and a.status == "awaiting_approval":
                target = a
                break
        if target is None:
            return None

        target.reject(reason)
        self._save_approvals(project_id, approvals)

        # Mark milestone as blocked
        milestones = self.load_milestones(project_id)
        for m in milestones:
            if m.milestone_id == milestone_id:
                m.status = "blocked"
                break
        self.save_milestones(project_id, milestones)

        session = self.load_session(project_id)
        if session:
            session.status = "active"
            session.pending_decisions = [
                d for d in session.pending_decisions
                if f"Approve milestone: {milestone_id}" not in d
            ]
            session.next_recommended_action = (
                f"Milestone {milestone_id} rejected: {reason}. Re-plan required."
            )
            self.save_session(session)

        self.log_decision(project_id, DecisionLog(
            entry_id=_new_id(),
            timestamp=_now(),
            decision=f"Rejected milestone: {milestone_id}",
            reason=reason or "No reason provided",
            made_by="human",
        ))

        return target

    def request_changes_milestone(
        self, project_id: str, milestone_id: str, notes: str = ""
    ) -> MilestoneApproval | None:
        """Request changes to a milestone — enters repair path."""
        approvals = self.load_approvals(project_id)
        target = None
        for a in approvals:
            if a.milestone_id == milestone_id and a.status == "awaiting_approval":
                target = a
                break
        if target is None:
            return None

        target.request_changes(notes)
        self._save_approvals(project_id, approvals)

        # Keep milestone in_progress so it can be re-executed
        milestones = self.load_milestones(project_id)
        for m in milestones:
            if m.milestone_id == milestone_id:
                m.status = "in_progress"
                break
        self.save_milestones(project_id, milestones)

        session = self.load_session(project_id)
        if session:
            session.status = "active"
            session.pending_decisions = [
                d for d in session.pending_decisions
                if f"Approve milestone: {milestone_id}" not in d
            ]
            session.next_recommended_action = (
                f"Changes requested for milestone {milestone_id}: {notes}"
            )
            self.save_session(session)

        self.log_decision(project_id, DecisionLog(
            entry_id=_new_id(),
            timestamp=_now(),
            decision=f"Requested changes to milestone: {milestone_id}",
            reason=notes or "No details provided",
            made_by="human",
        ))

        return target

    # ------------------------------------------------------------------
    # Decisions (append-only JSONL)
    # ------------------------------------------------------------------

    def log_decision(self, project_id: str, decision: DecisionLog) -> None:
        path = self._decision_log_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")

    def load_decisions(self, project_id: str, limit: int = 50) -> list[DecisionLog]:
        path = self._decision_log_path(project_id)
        if not path.exists():
            return []
        decisions: list[DecisionLog] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    decisions.append(DecisionLog.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue
        # Return most recent first
        decisions.reverse()
        return decisions[:limit]

    # ------------------------------------------------------------------
    # Run links (append-only JSONL)
    # ------------------------------------------------------------------

    def link_run(self, project_id: str, link: ProjectRunLink) -> None:
        path = self._run_links_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(link.to_dict(), ensure_ascii=False) + "\n")

    def load_run_links(self, project_id: str) -> list[ProjectRunLink]:
        path = self._run_links_path(project_id)
        if not path.exists():
            return []
        links: list[ProjectRunLink] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    links.append(ProjectRunLink.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue
        return links

    # ------------------------------------------------------------------
    # Session context assembly (for ask / resume)
    # ------------------------------------------------------------------

    def build_context(self, project_id: str) -> SessionContext | None:
        """Assemble a SessionContext for answering questions or resuming."""
        session = self.load_session(project_id)
        if session is None:
            return None

        milestones = self.load_milestones(project_id)
        current = None
        completed: list[ProjectMilestone] = []
        for m in milestones:
            if m.milestone_id == session.current_milestone:
                current = m
            if m.status == "completed":
                completed.append(m)

        recent = self.load_decisions(project_id, limit=20)
        important = [d for d in recent if d.made_by == "planning_council"]

        links = self.load_run_links(project_id)
        evidence_links: dict[str, str] = {}
        audit_links: dict[str, str] = {}
        for link in links:
            if link.evidence_path:
                evidence_links[link.milestone_id] = link.evidence_path
            if link.audit_path:
                audit_links[link.milestone_id] = link.audit_path

        return SessionContext(
            goal=session.goal,
            current_milestone=current,
            completed_milestones=completed,
            recent_decisions=recent,
            important_design_choices=important,
            open_risks=session.open_risks,
            evidence_links=evidence_links,
            audit_links=audit_links,
        )

    # ------------------------------------------------------------------
    # Internal write helpers
    # ------------------------------------------------------------------

    def _write_session(self, session: ProjectSession) -> None:
        path = self._session_path(session.project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_milestones(
        self, project_id: str, milestones: list[ProjectMilestone]
    ) -> None:
        path = self._milestones_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [m.to_dict() for m in milestones], ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Context snapshot (for fast resume)
    # ------------------------------------------------------------------

    def save_context_snapshot(self, project_id: str, ctx: SessionContext) -> None:
        path = self._context_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "goal": ctx.goal,
            "current_milestone": (
                ctx.current_milestone.to_dict() if ctx.current_milestone else None
            ),
            "completed_milestones": [m.to_dict() for m in ctx.completed_milestones],
            "open_risks": ctx.open_risks,
            "evidence_links": ctx.evidence_links,
            "audit_links": ctx.audit_links,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_context_snapshot(self, project_id: str) -> dict[str, Any] | None:
        path = self._context_path(project_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
