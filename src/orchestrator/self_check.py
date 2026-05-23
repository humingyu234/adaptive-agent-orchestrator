"""Phase 27 — AAO Self-Issue Handling.

Detects problems in AAO's own control chain (SystemFindings) as distinct
from ordinary task issues (test failures, lint errors).  SystemFindings
are NEVER auto-fixed — they require human review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_session import (
    ProjectSessionStore,
    SelfRepairProposal,
    SystemFinding,
    _new_id,
    _now,
)

# Paths that SelfRepairProposals must NEVER touch.
# A proposal targeting any of these is blocked at generation time.
AAO_PROTECTED_PREFIXES = (
    "src/orchestrator/",
    "CLAUDE.md",
    ".claude/phase-specs/",
    ".claude/project-skills/",
    ".env",
    "tests/",  # AAO tests are part of the control system
)


def _is_protected_path(file_path: str) -> bool:
    """Return True if *file_path* falls inside the AAO protected set."""
    normalized = file_path.replace("\\", "/")
    for prefix in AAO_PROTECTED_PREFIXES:
        if normalized.startswith(prefix) or normalized.endswith(prefix.rstrip("/")):
            return True
    return False


def generate_repair_proposal(finding: SystemFinding) -> SelfRepairProposal | None:
    """Generate a repair proposal for a SystemFinding.

    Returns None if the proposal would touch AAO-protected files —
    those must be fixed by a human developer, never by AAO itself.
    """
    # Build a tentative proposal based on the finding category
    summary, affected_files, risks, test_plan = _build_proposal_parts(finding)

    # Hard block: if any affected file is AAO-protected, refuse to generate
    for f in affected_files:
        if _is_protected_path(f):
            return None

    return SelfRepairProposal(
        proposal_id=_new_id(),
        triggered_by=[finding.finding_id],
        summary=summary,
        affected_files=affected_files,
        risks=risks,
        test_plan=test_plan,
        requires_human_approval=True,
    )


def _build_proposal_parts(
    finding: SystemFinding,
) -> tuple[str, list[str], list[str], str]:
    """Return (summary, affected_files, risks, test_plan) for a finding."""
    if finding.category == "evidence_false_positive":
        return (
            "Correct the evidence classifier to stop marking missing evidence as observed.",
            ["src/orchestrator/evidence.py"],
            ["Changing evidence classification may hide real evidence gaps"],
            "Run golden scenario suite and verify evidence status alignment.",
        )
    elif finding.category == "isolation_violation":
        return (
            "Add a sandbox guard to the reviewer to prevent writes to worker directories.",
            ["src/orchestrator/reviewer.py"],
            ["Too-strict isolation may break legitimate reviewer access patterns"],
            "Run reviewer tests with a temp worker directory and assert no writes.",
        )
    elif finding.category == "worker_bridge_bypass":
        return (
            "Add a pre-execution check that the worker process actually started.",
            ["src/orchestrator/workers/claude_code.py"],
            ["May cause false positives when worker exits quickly for valid reasons"],
            "Test with both real and mock Claude Code worker invocations.",
        )
    elif finding.category == "resume_broken":
        return (
            "Add integrity checks before loading evidence files referenced by run_links.",
            ["src/orchestrator/project_session.py"],
            ["May prevent legitimate resumes when evidence files are intentionally moved"],
            "Test resume after deleting/renaming evidence files.",
        )
    elif finding.category == "control_chain_gap":
        return (
            "Wire the ControlDecision into the MainlineExecutor decision loop.",
            ["src/orchestrator/mainline_executor.py"],
            ["Adding decision consumption may change execution flow timing"],
            "Run the mainline integration tests and check decision order.",
        )
    elif finding.category == "plan_reality_drift":
        return (
            "Add a plan-step-to-milestone alignment check after each milestone completes.",
            ["src/orchestrator/mainline_executor.py"],
            ["False drift signals may trigger unnecessary replan"],
            "Run project continue flow and compare milestone descriptions to evidence.",
        )
    elif finding.category == "decision_inconsistency":
        return (
            "Add a decision consistency checker that compares decisions by failure category.",
            ["src/orchestrator/control_plane.py"],
            ["May flag legitimate context-dependent decisions as inconsistent"],
            "Collect decision pairs with same failure category and verify consistency logic.",
        )
    elif finding.category == "file_boundary_violation":
        return (
            "Fix the file boundary enforcement pipeline to detect and block "
            "unauthorized file modifications during read-only milestones.",
            ["src/orchestrator/reviewer.py",
             "src/orchestrator/mainline_executor.py"],
            ["Tightening boundary checks may block legitimate edge cases"],
            "Run boundary enforcement tests and golden scenario suite.",
        )
    else:
        return (
            f"Investigate and resolve system finding: {finding.description}",
            [],
            ["Unknown scope — manual investigation required"],
            "Manual review by developer.",
        )


# ---------------------------------------------------------------------------
# Self-check functions — each returns a list of SystemFinding
# ---------------------------------------------------------------------------


def _check_evidence_quality(store: ProjectSessionStore, pid: str) -> list[SystemFinding]:
    """Check for evidence_false_positive: evidence marked [observed] but file missing."""
    findings: list[SystemFinding] = []
    links = store.load_run_links(pid)
    for link in links:
        if not link.evidence_path:
            continue
        ev_path = store._root / link.evidence_path
        if not ev_path.exists():
            continue
        try:
            import json
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            items = ev.get("evidence_status", {}).get("items", [])
            for item in items:
                if item.get("status") == "observed":
                    item_path = item.get("path", "")
                    if item_path:
                        full = store._root / item_path if not item_path.startswith("/") else Path(item_path)
                        if not full.exists():
                            findings.append(SystemFinding(
                                finding_id=_new_id(),
                                category="evidence_false_positive",
                                severity="high",
                                description=f"Evidence item '{item.get('key')}' marked observed but file missing: {item_path}",
                                evidence_refs=[str(ev_path)],
                                affected_components=["evidence classifier"],
                                detected_at=_now(),
                            ))
        except Exception:
            continue
    return findings


def _check_isolation(store: ProjectSessionStore, pid: str) -> list[SystemFinding]:
    """Check for isolation_violation: reviewer may have written to worker dirs."""
    findings: list[SystemFinding] = []
    links = store.load_run_links(pid)
    for link in links:
        if not link.evidence_path:
            continue
        ev_path = store._root / link.evidence_path
        if not ev_path.exists():
            continue
        try:
            import json
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            rf = ev.get("review_findings", [])
            for f in rf:
                if isinstance(f, dict):
                    desc = f.get("description", "")
                    if "write" in desc.lower() and "worker" in desc.lower():
                        findings.append(SystemFinding(
                            finding_id=_new_id(),
                            category="isolation_violation",
                            severity="critical",
                            description=f"Reviewer may have written to worker directory: {desc}",
                            evidence_refs=[str(ev_path)],
                            affected_components=["reviewer"],
                            detected_at=_now(),
                        ))
        except Exception:
            continue
    return findings


def _check_resume_integrity(store: ProjectSessionStore, pid: str) -> list[SystemFinding]:
    """Check for resume_broken: run_links reference non-existent files."""
    findings: list[SystemFinding] = []
    links = store.load_run_links(pid)
    for link in links:
        if link.evidence_path:
            ev_path = store._root / link.evidence_path
            if not ev_path.exists():
                findings.append(SystemFinding(
                    finding_id=_new_id(),
                    category="resume_broken",
                    severity="high",
                    description=f"Run link {link.run_id} references missing evidence: {link.evidence_path}",
                    evidence_refs=[str(store._run_links_path(pid))],
                    affected_components=["project_session", "run_links"],
                    detected_at=_now(),
                ))
        if link.audit_path:
            audit_path = store._root / link.audit_path
            if not audit_path.exists():
                findings.append(SystemFinding(
                    finding_id=_new_id(),
                    category="resume_broken",
                    severity="medium",
                    description=f"Run link {link.run_id} references missing audit: {link.audit_path}",
                    evidence_refs=[str(store._run_links_path(pid))],
                    affected_components=["project_session", "run_links"],
                    detected_at=_now(),
                ))
    return findings


def _check_worker_bypass(store: ProjectSessionStore, pid: str) -> list[SystemFinding]:
    """Check for worker_bridge_bypass: completed runs with no evidence of work."""
    findings: list[SystemFinding] = []
    links = store.load_run_links(pid)
    for link in links:
        if link.status != "completed":
            continue
        if not link.evidence_path:
            continue
        ev_path = store._root / link.evidence_path
        if not ev_path.exists():
            continue
        try:
            import json
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            changed = ev.get("changed_files", [])
            test_out = ev.get("test_output", "")
            if not changed and not test_out:
                findings.append(SystemFinding(
                    finding_id=_new_id(),
                    category="worker_bridge_bypass",
                    severity="high",
                    description=f"Run {link.run_id} completed but evidence has no changed_files and no test_output",
                    evidence_refs=[str(ev_path)],
                    affected_components=["worker bridge", "mainline_executor"],
                    detected_at=_now(),
                ))
        except Exception:
            continue
    return findings


def _check_plan_drift(store: ProjectSessionStore, pid: str) -> list[SystemFinding]:
    """Check for plan_reality_drift: milestone descriptions vs evidence content."""
    findings: list[SystemFinding] = []
    milestones = store.load_milestones(pid)
    links = store.load_run_links(pid)
    for ms in milestones:
        if ms.status not in ("completed", "paused_for_approval"):
            continue
        ms_links = [l for l in links if l.milestone_id == ms.milestone_id]
        if not ms_links:
            # Milestone completed/executed but no run link recorded
            findings.append(SystemFinding(
                finding_id=_new_id(),
                category="plan_reality_drift",
                severity="medium",
                description=f"Milestone '{ms.name}' is {ms.status} but has no linked runs",
                evidence_refs=[str(store._milestones_path(pid))],
                affected_components=["mainline_executor", "project_session"],
                detected_at=_now(),
            ))
    return findings


# Milestone description prefixes that indicate a read-only operation.
# Any milestone whose description starts with one of these must not
# produce file changes.
_READ_ONLY_PREFIXES = (
    "read", "examine", "audit", "inspect", "trace",
    "search", "check", "analyze", "review",
)


def _is_read_only_milestone(description: str) -> bool:
    """Return True if the milestone description signals a read-only operation."""
    lowered = description.strip().lower()
    return lowered.startswith(_READ_ONLY_PREFIXES)


def _check_file_boundary_violation(
    store: ProjectSessionStore, pid: str,
) -> list[SystemFinding]:
    """Check for file_boundary_violation: read-only milestones that produced
    file changes, or bounded milestones whose changes exceed their scope."""
    findings: list[SystemFinding] = []
    milestones = {m.milestone_id: m for m in store.load_milestones(pid)}
    links = store.load_run_links(pid)

    for link in links:
        ms = milestones.get(link.milestone_id)
        if not ms:
            continue
        if ms.status not in ("completed", "paused_for_approval"):
            continue
        if not link.evidence_path:
            continue

        ev_path = store._root / link.evidence_path
        if not ev_path.exists():
            continue

        try:
            import json
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            changed = ev.get("changed_files", [])
        except Exception:
            continue

        if not changed:
            continue

        if _is_read_only_milestone(ms.description):
            findings.append(SystemFinding(
                finding_id=_new_id(),
                category="file_boundary_violation",
                severity="critical",
                description=(
                    f"Read-only milestone '{ms.name}' ({ms.milestone_id}) "
                    f"produced file changes: {changed}"
                ),
                evidence_refs=[str(ev_path)],
                affected_components=["mainline_executor", "reviewer", "worker"],
                detected_at=_now(),
            ))

    return findings


def _check_decision_consistency(store: ProjectSessionStore, pid: str) -> list[SystemFinding]:
    """Check for decision_inconsistency: same failure handled differently."""
    findings: list[SystemFinding] = []
    decisions = store.load_decisions(pid)
    # Group decisions by failure-related keywords in reason
    from collections import defaultdict
    by_category: dict[str, list[Any]] = defaultdict(list)
    for d in decisions:
        lowered = d.reason.lower()
        for cat in ("test failure", "lint error", "timeout", "evidence missing", "reviewer"):
            if cat in lowered:
                by_category[cat].append(d)
                break
    for cat, decs in by_category.items():
        if len(decs) < 2:
            continue
        actions = {d.decision for d in decs}
        if len(actions) > 1:
            findings.append(SystemFinding(
                finding_id=_new_id(),
                category="decision_inconsistency",
                severity="medium",
                description=f"Failure category '{cat}' handled differently across {len(decs)} decisions: {', '.join(sorted(actions))}",
                evidence_refs=[str(store._decision_log_path(pid))],
                affected_components=["control_plane"],
                detected_at=_now(),
            ))
    return findings


# Registry of all self-check functions
_CHECKS: dict[str, Any] = {
    "evidence_false_positive": _check_evidence_quality,
    "isolation_violation": _check_isolation,
    "resume_broken": _check_resume_integrity,
    "worker_bridge_bypass": _check_worker_bypass,
    "plan_reality_drift": _check_plan_drift,
    "decision_inconsistency": _check_decision_consistency,
    "file_boundary_violation": _check_file_boundary_violation,
}


def run_self_check(
    store: ProjectSessionStore,
    project_id: str,
    category: str | None = None,
) -> list[SystemFinding]:
    """Run all self-checks (or a single category) against a project session.

    Returns a list of SystemFindings.  An empty list means no system issues
    were detected.
    """
    findings: list[SystemFinding] = []
    if category is not None:
        check_fn = _CHECKS.get(category)
        if check_fn is not None:
            findings.extend(check_fn(store, project_id))
    else:
        for check_fn in _CHECKS.values():
            findings.extend(check_fn(store, project_id))
    return findings
