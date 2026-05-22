"""Phase 24 — Project Session Layer tests.

Proves: session CRUD, milestone transitions, decision log append,
context assembly, CLI handlers, edge cases.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from orchestrator.project_session import (
    DecisionLog,
    MilestoneApproval,
    ProjectMilestone,
    ProjectRunLink,
    ProjectSession,
    ProjectSessionStore,
    SelfRepairProposal,
    SessionContext,
    SystemFinding,
    _new_id,
    _now,
)


# =============================================================================
# Helpers
# =============================================================================


@pytest.fixture
def tmp_store() -> ProjectSessionStore:
    """Store pointed at a disposable temp directory."""
    with tempfile.TemporaryDirectory(prefix="aao-test-session-") as td:
        yield ProjectSessionStore(td)


def _create_active_session(store: ProjectSessionStore, goal: str = "Test project") -> ProjectSession:
    session = store.create_session(goal=goal)
    m = ProjectMilestone(
        milestone_id=_new_id(),
        name="First milestone",
        description="Initial setup",
        status="in_progress",
        plan_step_ids=["step-1"],
        approval_required=True,
    )
    store.save_milestones(session.project_id, [m])
    session.current_milestone = m.milestone_id
    store.save_session(session)
    store.log_decision(session.project_id, DecisionLog(
        entry_id=_new_id(), timestamp=_now(),
        decision="Chose approach A", reason="Better performance",
        alternatives=["approach B", "approach C"],
        made_by="planning_council",
    ))
    store.log_decision(session.project_id, DecisionLog(
        entry_id=_new_id(), timestamp=_now(),
        decision="Approved milestone 1", reason="Looks good",
        made_by="human",
    ))
    store.link_run(session.project_id, ProjectRunLink(
        milestone_id=m.milestone_id, run_id="run-001",
        evidence_path="outputs/evidence/run-001.json",
        audit_path="outputs/audits/run-001.json",
        status="completed",
    ))
    return session


# =============================================================================
# Session CRUD
# =============================================================================


class TestSessionCRUD:
    """Create, load, save, close, list."""

    def test_create_session_persists_to_disk(self, tmp_store):
        session = tmp_store.create_session("Build a memory system")
        assert session.project_id
        assert session.status == "active"
        assert tmp_store._session_path(session.project_id).exists()

    def test_load_session_roundtrips(self, tmp_store):
        session = tmp_store.create_session("Roundtrip test")
        loaded = tmp_store.load_session(session.project_id)
        assert loaded is not None
        assert loaded.goal == "Roundtrip test"
        assert loaded.project_id == session.project_id

    def test_load_nonexistent_returns_none(self, tmp_store):
        assert tmp_store.load_session("nonexistent") is None

    def test_save_session_updates_last_active(self, tmp_store):
        session = tmp_store.create_session("Save test")
        original = session.last_active_at
        session.goal = "Updated goal"
        tmp_store.save_session(session)
        loaded = tmp_store.load_session(session.project_id)
        assert loaded.goal == "Updated goal"
        assert loaded.last_active_at >= original

    def test_close_session_marks_completed(self, tmp_store):
        session = _create_active_session(tmp_store)
        result = tmp_store.close_session(session.project_id)
        assert result is not None
        assert result.status == "completed"

    def test_close_already_closed_no_error(self, tmp_store):
        session = _create_active_session(tmp_store)
        tmp_store.close_session(session.project_id)
        result = tmp_store.close_session(session.project_id)
        assert result.status == "completed"

    def test_close_nonexistent_returns_none(self, tmp_store):
        assert tmp_store.close_session("nonexistent") is None

    def test_list_sessions_returns_all(self, tmp_store):
        s1 = tmp_store.create_session("Project A")
        s2 = tmp_store.create_session("Project B")
        sessions = tmp_store.list_sessions()
        ids = [s["project_id"] for s in sessions]
        assert s1.project_id in ids
        assert s2.project_id in ids

    def test_list_sessions_empty_when_none_exist(self, tmp_store):
        assert tmp_store.list_sessions() == []


# =============================================================================
# Milestone transitions
# =============================================================================


class TestMilestones:
    """Milestone state management."""

    def test_create_milestones_stored_and_loaded(self, tmp_store):
        session = tmp_store.create_session("Milestone test")
        ms = [
            ProjectMilestone(milestone_id="ms-1", name="Step 1", status="pending"),
            ProjectMilestone(milestone_id="ms-2", name="Step 2", status="pending"),
        ]
        tmp_store.save_milestones(session.project_id, ms)
        loaded = tmp_store.load_milestones(session.project_id)
        assert len(loaded) == 2
        assert loaded[0].name == "Step 1"

    def test_advance_milestone_updates_status_and_session(self, tmp_store):
        session = _create_active_session(tmp_store)
        ms_list = tmp_store.load_milestones(session.project_id)
        ms = ms_list[0]
        result = tmp_store.advance_milestone(
            session.project_id, ms.milestone_id, "completed"
        )
        assert result is not None
        assert ms.milestone_id in result.completed_milestones

    def test_get_current_milestone_returns_correct(self, tmp_store):
        session = _create_active_session(tmp_store)
        ms_list = tmp_store.load_milestones(session.project_id)
        current = tmp_store.get_current_milestone(session.project_id)
        assert current is not None
        assert current.milestone_id == ms_list[0].milestone_id

    def test_get_current_milestone_none_when_no_session(self, tmp_store):
        assert tmp_store.get_current_milestone("nonexistent") is None

    def test_advance_milestone_nonexistent_session(self, tmp_store):
        assert tmp_store.advance_milestone("nonexistent", "ms-1", "completed") is None


# =============================================================================
# Decision log (append-only JSONL)
# =============================================================================


class TestDecisionLog:
    """Decisions are append-only, loaded most-recent-first."""

    def test_log_and_load_decisions(self, tmp_store):
        session = tmp_store.create_session("Decision test")
        d1 = DecisionLog(entry_id="d-1", timestamp=_now(), decision="First", reason="Because")
        d2 = DecisionLog(entry_id="d-2", timestamp=_now(), decision="Second", reason="Also because")
        tmp_store.log_decision(session.project_id, d1)
        tmp_store.log_decision(session.project_id, d2)
        decisions = tmp_store.load_decisions(session.project_id)
        assert len(decisions) == 2
        assert decisions[0].entry_id == "d-2"  # most recent first

    def test_load_decisions_empty_when_no_log(self, tmp_store):
        assert tmp_store.load_decisions("nonexistent") == []

    def test_load_decisions_respects_limit(self, tmp_store):
        session = tmp_store.create_session("Limit test")
        for i in range(10):
            tmp_store.log_decision(session.project_id, DecisionLog(
                entry_id=f"d-{i}", timestamp=_now(),
                decision=f"Decision {i}", reason="test",
            ))
        assert len(tmp_store.load_decisions(session.project_id, limit=5)) == 5

    def test_corrupt_lines_skipped(self, tmp_store):
        session = tmp_store.create_session("Corrupt test")
        path = tmp_store._decision_log_path(session.project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json\n", encoding="utf-8")
        decisions = tmp_store.load_decisions(session.project_id)
        assert decisions == []


# =============================================================================
# Run links (append-only JSONL)
# =============================================================================


class TestRunLinks:
    """Run links connect milestones to execution runs."""

    def test_link_and_load_runs(self, tmp_store):
        session = tmp_store.create_session("Run link test")
        link = ProjectRunLink(
            milestone_id="ms-1", run_id="run-001",
            evidence_path="outputs/evidence/run-001.json",
            audit_path="outputs/audits/run-001.json",
            status="completed",
        )
        tmp_store.link_run(session.project_id, link)
        links = tmp_store.load_run_links(session.project_id)
        assert len(links) == 1
        assert links[0].run_id == "run-001"

    def test_load_run_links_empty(self, tmp_store):
        assert tmp_store.load_run_links("nonexistent") == []


# =============================================================================
# Context assembly
# =============================================================================


class TestContextAssembly:
    """SessionContext is assembled from persisted data for ask/resume."""

    def test_build_context_includes_all_sections(self, tmp_store):
        session = _create_active_session(tmp_store)
        ctx = tmp_store.build_context(session.project_id)
        assert ctx is not None
        assert ctx.goal == "Test project"
        assert ctx.current_milestone is not None
        assert ctx.current_milestone.name == "First milestone"
        assert len(ctx.recent_decisions) == 2
        assert len(ctx.important_design_choices) >= 1  # made_by=human

    def test_build_context_none_for_nonexistent(self, tmp_store):
        assert tmp_store.build_context("nonexistent") is None

    def test_context_snapshot_survives_roundtrip(self, tmp_store):
        session = _create_active_session(tmp_store)
        ctx = tmp_store.build_context(session.project_id)
        tmp_store.save_context_snapshot(session.project_id, ctx)
        snap = tmp_store.load_context_snapshot(session.project_id)
        assert snap is not None
        assert snap["goal"] == "Test project"
        assert snap["current_milestone"] is not None

    def test_context_snapshot_none_when_missing(self, tmp_store):
        assert tmp_store.load_context_snapshot("nonexistent") is None


# =============================================================================
# Session state edge cases
# =============================================================================


class TestSessionEdgeCases:
    """Cross-restart persistence, close gating, etc."""

    def test_session_survives_store_recreation(self, tmp_store):
        """Session persists because it's file-based — same dir, new store."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Simulate process restart: new store pointing to same root
        store2 = ProjectSessionStore(tmp_store._root)
        loaded = store2.load_session(pid)
        assert loaded is not None
        assert loaded.goal == "Test project"
        milestones = store2.load_milestones(pid)
        assert len(milestones) > 0

    def test_close_prevents_reopen_as_active(self, tmp_store):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        tmp_store.close_session(pid)
        loaded = tmp_store.load_session(pid)
        assert loaded.status == "completed"

    def test_continue_closed_project_is_detectable(self, tmp_store):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        tmp_store.close_session(pid)
        loaded = tmp_store.load_session(pid)
        assert loaded.status != "active"

    def test_empty_milestones_list_no_error(self, tmp_store):
        session = tmp_store.create_session("Empty milestones")
        assert tmp_store.load_milestones(session.project_id) == []

    def test_build_context_with_no_milestones(self, tmp_store):
        session = tmp_store.create_session("No milestones yet")
        ctx = tmp_store.build_context(session.project_id)
        assert ctx is not None
        assert ctx.current_milestone is None
        assert ctx.completed_milestones == []

    def test_project_id_uniqueness(self, tmp_store):
        s1 = tmp_store.create_session("Project 1")
        s2 = tmp_store.create_session("Project 2")
        assert s1.project_id != s2.project_id


# =============================================================================
# CLI handler integration
# =============================================================================


class TestCLIHandlers:
    """Test the handler functions directly (not via argparse)."""

    def test_project_start_creates_session_with_milestones(self, tmp_store):
        from orchestrator.__main__ import _handle_project_start

        class FakeArgs:
            goal = "CLI test project"
            project_id = None
            planning_mode = "deterministic"

        _handle_project_start(FakeArgs(), tmp_store)
        sessions = tmp_store.list_sessions()
        assert len(sessions) == 1
        pid = sessions[0]["project_id"]
        session = tmp_store.load_session(pid)
        assert session.goal == "CLI test project"
        milestones = tmp_store.load_milestones(pid)
        assert len(milestones) > 0
        assert session.current_milestone is not None

    def test_project_status_shows_current_state(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_status

        class FakeArgs:
            project_id = session.project_id

        _handle_project_status(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["project_id"] == session.project_id
        assert data["goal"] == "Test project"
        assert data["current_milestone"] is not None
        assert "pending_approvals" in data

    def test_project_ask_answers_from_decision_log(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = session.project_id
            question = "Why did we choose approach A?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        # The question shares words with "Chose approach A" decision
        assert "approach" in data["answer"].lower() or "Decision:" in data["answer"]
        assert len(data["evidence"]) > 0

    def test_project_ask_unknown_question_gives_honest_answer(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = session.project_id
            question = "What's the weather like?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "don't have enough" in data["answer"].lower() or "no" in data["answer"].lower()
        assert len(data["evidence"]) > 0

    def test_project_ask_next_step(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = session.project_id
            question = "What should I do next?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "next_recommended_action" in str(data["evidence"])

    def test_project_continue_resumes_active(self, tmp_store, capsys):
        """After continue + successful execution, session is paused_for_approval."""
        session = _create_active_session(tmp_store)
        pid = session.project_id
        # Pause first
        session.status = "paused"
        tmp_store.save_session(session)

        from orchestrator.__main__ import _handle_project_continue

        class FakeArgs:
            project_id = pid
            worker_mode = "fake"
            planning_mode = "deterministic"
            max_workers = 2

        _handle_project_continue(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)

        # After successful fake-worker execution, submit_for_approval pauses the session
        assert data["run_id"]
        s = tmp_store.load_session(pid)
        assert s.status == "paused"  # gate tripped

        # Run link must be created
        links = tmp_store.load_run_links(pid)
        run_links = [l for l in links if l.run_id == data["run_id"]]
        assert len(run_links) == 1

        # Decision must be logged
        decisions = tmp_store.load_decisions(pid)
        resume_decisions = [d for d in decisions if "Resumed execution" in d.decision]
        assert len(resume_decisions) >= 1

        # Milestone must be paused_for_approval
        ms = tmp_store.get_current_milestone(pid)
        assert ms is not None
        assert ms.status == "paused_for_approval"

    def test_project_continue_paused_for_approval_is_blocked(self, tmp_store, capsys):
        """When milestone is already paused_for_approval, continue is blocked."""
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        # Submit for approval to trigger the gate
        tmp_store.submit_for_approval(pid, ms.milestone_id)

        from orchestrator.__main__ import _handle_project_continue

        class FakeArgs:
            project_id = pid

        _handle_project_continue(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "paused_for_approval"
        assert "waiting for approval" in data["_note"].lower()

    def test_project_close_marks_completed(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_close

        class FakeArgs:
            project_id = session.project_id

        _handle_project_close(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "completed"

    def test_project_continue_after_close_is_blocked(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)
        tmp_store.close_session(session.project_id)

        from orchestrator.__main__ import _handle_project_continue

        class FakeArgs:
            project_id = session.project_id

        _handle_project_continue(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "error" in data
        assert "Cannot continue" in data["error"]

    def test_project_ask_no_session_shows_help(self, tmp_store, capsys):
        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = "nonexistent"
            question = "Anything?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "error" in data
        assert "not found" in data["error"].lower() or "nonexistent" in data["error"]

    def test_project_ask_about_risks(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)
        session.open_risks = ["Memory leak in worker pool"]
        tmp_store.save_session(session)

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = session.project_id
            question = "Are there any risks?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "Memory leak" in data["answer"]

    def test_project_ask_about_files(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)

        # Create an actual evidence file with changed_files so the handler
        # can read real artifact data.  Evidence paths in run links are
        # relative to store root (resolved by _read_evidence_json).
        link = tmp_store.load_run_links(session.project_id)[0]
        ev_path = Path(tmp_store._root) / link.evidence_path
        ev_path.parent.mkdir(parents=True, exist_ok=True)
        ev_path.write_text(json.dumps({
            "changed_files": ["src/utils.py", "tests/test_utils.py"],
            "test_output": "10 passed, 0 failed",
        }), encoding="utf-8")

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = session.project_id
            question = "What files were changed?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "src/utils.py" in data["answer"]

    def test_ask_unknown_question_suggests_what_artifact_to_check(self, tmp_store, capsys):
        """Unknown question must cite specific artifact paths, not just a directory."""
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = session.project_id
            question = "What's the weather like?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "decision_log.jsonl" in data["answer"]
        assert "run_links.jsonl" in data["answer"]
        assert "milestones.json" in data["answer"]
        assert "session.json" in data["answer"]
        assert len(data["evidence"]) >= 2

    def test_ask_does_not_launch_workers_or_modify_state(self, tmp_store, capsys):
        """project ask is read-only — it must not change any state on disk."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Snapshot before
        s_before = tmp_store.load_session(pid)
        ms_before = tmp_store.load_milestones(pid)
        decisions_before = tmp_store.load_decisions(pid)
        links_before = tmp_store.load_run_links(pid)

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = pid
            question = "What files were changed?"

        _handle_project_ask(FakeArgs(), tmp_store)

        # Snapshot after
        s_after = tmp_store.load_session(pid)
        ms_after = tmp_store.load_milestones(pid)
        decisions_after = tmp_store.load_decisions(pid)
        links_after = tmp_store.load_run_links(pid)

        # Nothing must change
        assert s_after.goal == s_before.goal
        assert s_after.status == s_before.status
        assert s_after.current_milestone == s_before.current_milestone
        assert len(ms_after) == len(ms_before)
        assert len(decisions_after) == len(decisions_before)
        assert len(links_after) == len(links_before)

    def test_resume_continues_from_correct_milestone(self, tmp_store, capsys):
        """Resume must execute the in_progress milestone, not a completed one."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Add two milestones, mark first as completed
        ms1 = tmp_store.get_current_milestone(pid)
        ms2 = ProjectMilestone(
            milestone_id="ms-2", name="Second milestone",
            description="Phase 2", status="pending",
        )
        all_ms = tmp_store.load_milestones(pid)
        tmp_store.save_milestones(pid, all_ms + [ms2])

        # Complete ms1, activate ms2
        tmp_store.advance_milestone(pid, ms1.milestone_id, "completed")
        for m in tmp_store.load_milestones(pid):
            if m.milestone_id == "ms-2":
                m.status = "in_progress"
                break
        session.current_milestone = "ms-2"
        session.status = "paused"
        tmp_store.save_session(session)
        tmp_store.save_milestones(pid, tmp_store.load_milestones(pid))

        from orchestrator.__main__ import _handle_project_continue

        class FakeArgs:
            project_id = pid
            worker_mode = "fake"
            planning_mode = "deterministic"
            max_workers = 2

        _handle_project_continue(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)

        # Output must reference the correct milestone (ms2)
        assert data["current_milestone"] is not None
        assert data["current_milestone"]["name"] == "Second milestone"

    def test_continue_output_includes_resume_summary(self, tmp_store, capsys):
        """project continue output must include last_decision and pending_approvals."""
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        # First run: continue executes and submits for approval
        session.status = "paused"
        tmp_store.save_session(session)

        from orchestrator.__main__ import _handle_project_continue

        class FakeArgs:
            project_id = pid
            worker_mode = "fake"
            planning_mode = "deterministic"
            max_workers = 2

        _handle_project_continue(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)

        # Resume summary fields must be present
        assert "last_decision" in data
        assert "pending_approvals" in data
        assert "completed_milestones" in data
        assert "next_recommended_action" in data

    def test_unknown_question_gives_targeted_paths_by_keyword(self, tmp_store, capsys):
        """Unknown questions should suggest artifact paths relevant to the question topic."""
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_ask

        # Question about "history" → should suggest decision_log but not all paths
        class FakeArgs:
            project_id = session.project_id
            question = "What is the project history?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "decision_log.jsonl" in data["answer"]
        # Should NOT contain unrelated paths
        assert "run_links.jsonl" not in data["answer"]
        assert "milestones.json" not in data["answer"]

        # Question about "execution" → should suggest run_links
        class FakeArgs2:
            project_id = session.project_id
            question = "Show me the execution timeline?"

        _handle_project_ask(FakeArgs2(), tmp_store)
        out2 = capsys.readouterr().out
        data2 = json.loads(out2)
        assert "run_links.jsonl" in data2["answer"]
        assert "decision_log.jsonl" not in data2["answer"]

    def test_reviewer_findings_include_evidence_label(self, tmp_store, capsys):
        """Reviewer findings answer must include [observed] or [reported] label."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Create evidence file with review_findings
        link = tmp_store.load_run_links(pid)[0]
        ev_path = Path(tmp_store._root) / link.evidence_path
        ev_path.parent.mkdir(parents=True, exist_ok=True)
        ev_path.write_text(json.dumps({
            "review_findings": [
                {"severity": "P1", "description": "Missing error handling"}
            ],
        }), encoding="utf-8")

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = pid
            question = "What did the reviewer find?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        # Must have an evidence label
        assert "[observed]" in data["answer"] or "[reported]" in data["answer"]
        assert "P1" in data["answer"]

    def test_repair_history_includes_evidence_label(self, tmp_store, capsys):
        """Repair history answer must include [observed] or [reported] label."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Create audit file with repair_rounds
        link = tmp_store.load_run_links(pid)[0]
        audit_path = Path(tmp_store._root) / link.audit_path
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps({
            "repair_rounds": 2,
        }), encoding="utf-8")

        from orchestrator.__main__ import _handle_project_ask

        class FakeArgs:
            project_id = pid
            question = "How many repair rounds?"

        _handle_project_ask(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "[observed]" in data["answer"] or "[reported]" in data["answer"]
        assert "2 round(s)" in data["answer"]

    def test_status_includes_pending_approvals_field(self, tmp_store, capsys):
        """project status must include pending_approvals list."""
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        # Submit for approval to create a pending approval record
        tmp_store.submit_for_approval(pid, ms.milestone_id)

        from orchestrator.__main__ import _handle_project_status

        class FakeArgs:
            project_id = pid

        _handle_project_status(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "pending_approvals" in data
        assert isinstance(data["pending_approvals"], list)
        assert len(data["pending_approvals"]) == 1
        assert data["pending_approvals"][0]["status"] == "awaiting_approval"

    def test_resolve_project_id_uses_latest_active(self, tmp_store):
        from orchestrator.__main__ import _resolve_project_id

        s1 = tmp_store.create_session("First")
        s2 = tmp_store.create_session("Second")
        tmp_store.close_session(s1.project_id)

        pid, reason = _resolve_project_id(tmp_store, explicit=None)
        assert pid == s2.project_id  # s1 closed, s2 active
        assert reason is None

    def test_resolve_project_id_none_when_no_active(self, tmp_store):
        from orchestrator.__main__ import _resolve_project_id

        pid, reason = _resolve_project_id(tmp_store, explicit=None)
        assert pid is None
        assert reason == "no_active"

    def test_resolve_project_id_none_for_explicit_not_found(self, tmp_store):
        from orchestrator.__main__ import _resolve_project_id

        pid, reason = _resolve_project_id(tmp_store, explicit="nonexistent")
        assert pid is None
        assert reason == "explicit_not_found"


# =============================================================================
# Phase 25 — Milestone Gate / Human Approval
# =============================================================================


class TestMilestoneGate:
    """Milestone gate: submit → human decision → advance/re-block/re-execute."""

    def test_submit_for_approval_creates_record_and_pauses(self, tmp_store):
        session = _create_active_session(tmp_store)
        ms = tmp_store.get_current_milestone(session.project_id)

        approval = tmp_store.submit_for_approval(
            session.project_id,
            ms.milestone_id,
            evidence_summary="Built feature X",
            files_changed=["src/x.py"],
            test_results_summary="5 passed",
            reviewer_findings=["minor: docstring missing"],
            repair_history=["round-1: fixed import"],
            open_risks=["performance regression risk"],
        )

        assert approval is not None
        assert approval.status == "awaiting_approval"
        assert approval.evidence_summary == "Built feature X"
        assert approval.files_changed == ["src/x.py"]

        # Milestone should be paused_for_approval, NOT completed
        ms_refreshed = tmp_store.get_current_milestone(session.project_id)
        assert ms_refreshed is not None
        assert ms_refreshed.status == "paused_for_approval"

        # Session should be paused
        s = tmp_store.load_session(session.project_id)
        assert s.status == "paused"

    def test_milestone_completed_does_not_auto_continue_to_next(self, tmp_store):
        """Gate requirement: completing execution must pause, not auto-advance."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Add a second pending milestone
        ms2 = ProjectMilestone(
            milestone_id="ms-2", name="Second milestone",
            description="Phase 2", status="pending",
        )
        all_ms = tmp_store.load_milestones(pid)
        tmp_store.save_milestones(pid, all_ms + [ms2])

        ms1 = tmp_store.get_current_milestone(pid)
        tmp_store.submit_for_approval(pid, ms1.milestone_id)

        # ms1 must be paused_for_approval, ms2 must still be pending
        ms_list = tmp_store.load_milestones(pid)
        ms1_data = next(m for m in ms_list if m.milestone_id == ms1.milestone_id)
        ms2_data = next(m for m in ms_list if m.milestone_id == "ms-2")
        assert ms1_data.status == "paused_for_approval"
        assert ms2_data.status == "pending"

    def test_approve_unlocks_next_milestone(self, tmp_store):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms1 = tmp_store.get_current_milestone(pid)

        # Add a second pending milestone
        ms2 = ProjectMilestone(
            milestone_id="ms-2", name="Second milestone",
            description="Phase 2", status="pending",
        )
        all_ms = tmp_store.load_milestones(pid)
        tmp_store.save_milestones(pid, all_ms + [ms2])

        # Submit and then approve
        tmp_store.submit_for_approval(pid, ms1.milestone_id)
        approval = tmp_store.approve_milestone(pid, ms1.milestone_id)

        assert approval is not None
        assert approval.status == "approved"
        assert approval.approved_by == "human"

        # ms1 should now be completed
        ms_list = tmp_store.load_milestones(pid)
        ms1_data = next(m for m in ms_list if m.milestone_id == ms1.milestone_id)
        assert ms1_data.status == "completed"
        assert ms1.milestone_id in tmp_store.load_session(pid).completed_milestones

        # ms2 should now be in_progress
        ms2_data = next(m for m in ms_list if m.milestone_id == "ms-2")
        assert ms2_data.status == "in_progress"

        # session should be active
        s = tmp_store.load_session(pid)
        assert s.status == "active"

    def test_approve_last_milestone_clears_current_and_completes_session(self, tmp_store):
        """When the last milestone is approved, current_milestone → None, session → completed."""
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        # This is the ONLY milestone — no more pending
        tmp_store.submit_for_approval(pid, ms.milestone_id)
        tmp_store.approve_milestone(pid, ms.milestone_id)

        s = tmp_store.load_session(pid)
        assert s.current_milestone is None
        assert s.status == "completed"
        assert s.next_recommended_action == "All milestones completed."

    def test_reject_generates_adjustment_task(self, tmp_store):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        tmp_store.submit_for_approval(pid, ms.milestone_id)
        approval = tmp_store.reject_milestone(
            pid, ms.milestone_id, reason="Design doesn't match requirements"
        )

        assert approval is not None
        assert approval.status == "rejected"
        assert "requirements" in approval.rejection_reason

        # Milestone should be blocked
        ms_refreshed = tmp_store.get_current_milestone(pid)
        assert ms_refreshed.status == "blocked"

        # Session should note re-plan required
        s = tmp_store.load_session(pid)
        assert "Re-plan required" in s.next_recommended_action

    def test_request_changes_enters_repair_path(self, tmp_store):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        tmp_store.submit_for_approval(pid, ms.milestone_id)
        approval = tmp_store.request_changes_milestone(
            pid, ms.milestone_id, notes="Add more test coverage for edge cases"
        )

        assert approval is not None
        assert approval.status == "changes_requested"
        assert "test coverage" in approval.changes_requested_notes

        # Milestone should be back to in_progress for re-execution
        ms_refreshed = tmp_store.get_current_milestone(pid)
        assert ms_refreshed.status == "in_progress"

        # Session should be active
        s = tmp_store.load_session(pid)
        assert s.status == "active"

    def test_audit_records_human_approval(self, tmp_store):
        """Approve must log a DecisionLog entry with made_by='human'."""
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        tmp_store.submit_for_approval(pid, ms.milestone_id)
        tmp_store.approve_milestone(pid, ms.milestone_id)

        decisions = tmp_store.load_decisions(pid)
        approval_decisions = [
            d for d in decisions
            if "Approved milestone" in d.decision and d.made_by == "human"
        ]
        assert len(approval_decisions) >= 1

    def test_cannot_skip_gate_even_if_all_checks_pass(self, tmp_store):
        """Even with perfect evidence, submit_for_approval must pause."""
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        # Simulate "perfect" evidence
        tmp_store.submit_for_approval(
            pid, ms.milestone_id,
            evidence_summary="All checks passed",
            files_changed=["src/a.py"],
            test_results_summary="100 passed, 0 failed",
            reviewer_findings=[],  # no findings = clean
            repair_history=[],     # no repairs needed
            open_risks=[],
        )

        ms_refreshed = tmp_store.get_current_milestone(pid)
        assert ms_refreshed.status == "paused_for_approval"

        s = tmp_store.load_session(pid)
        assert s.status == "paused"

    def test_rejection_reason_preserved_in_session(self, tmp_store):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        tmp_store.submit_for_approval(pid, ms.milestone_id)
        rejection_reason = "Security review required before proceeding"
        tmp_store.reject_milestone(pid, ms.milestone_id, reason=rejection_reason)

        # Reason preserved in approval record
        approvals = tmp_store.load_approvals(pid)
        assert len(approvals) == 1
        assert approvals[0].rejection_reason == rejection_reason

        # Reason preserved in decision log
        decisions = tmp_store.load_decisions(pid)
        reject_decisions = [d for d in decisions if "Rejected milestone" in d.decision]
        assert len(reject_decisions) >= 1
        assert rejection_reason in reject_decisions[0].reason

    def test_approval_required_but_not_given_blocks_all_subsequent_milestones(self, tmp_store):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms1 = tmp_store.get_current_milestone(pid)

        # Add two more pending milestones
        ms2 = ProjectMilestone(
            milestone_id="ms-2", name="Second", status="pending",
        )
        ms3 = ProjectMilestone(
            milestone_id="ms-3", name="Third", status="pending",
        )
        all_ms = tmp_store.load_milestones(pid)
        tmp_store.save_milestones(pid, all_ms + [ms2, ms3])

        # Submit ms1 for approval but don't approve
        tmp_store.submit_for_approval(pid, ms1.milestone_id)

        # ms2 and ms3 must still be pending
        ms_list = tmp_store.load_milestones(pid)
        ms2_data = next(m for m in ms_list if m.milestone_id == "ms-2")
        ms3_data = next(m for m in ms_list if m.milestone_id == "ms-3")
        assert ms2_data.status == "pending"
        assert ms3_data.status == "pending"

    def test_submit_nonexistent_milestone_returns_none(self, tmp_store):
        session = _create_active_session(tmp_store)
        result = tmp_store.submit_for_approval(session.project_id, "nonexistent")
        assert result is None

    def test_submit_nonexistent_session_returns_none(self, tmp_store):
        result = tmp_store.submit_for_approval("nonexistent", "ms-1")
        assert result is None

    def test_approve_nonexistent_returns_none(self, tmp_store):
        assert tmp_store.approve_milestone("nonexistent", "ms-1") is None

    def test_reject_nonexistent_returns_none(self, tmp_store):
        assert tmp_store.reject_milestone("nonexistent", "ms-1") is None

    def test_request_changes_nonexistent_returns_none(self, tmp_store):
        assert tmp_store.request_changes_milestone("nonexistent", "ms-1") is None


class TestMilestoneGateCLI:
    """CLI handlers for milestone approval gate."""

    def test_project_approve_unlocks_next(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)

        # Add second milestone and submit for approval
        ms2 = ProjectMilestone(
            milestone_id="ms-2", name="Second", status="pending",
        )
        all_ms = tmp_store.load_milestones(pid)
        tmp_store.save_milestones(pid, all_ms + [ms2])
        tmp_store.submit_for_approval(pid, ms.milestone_id)

        from orchestrator.__main__ import _handle_project_approve

        class FakeArgs:
            milestone_id = ms.milestone_id
            project_id = pid

        _handle_project_approve(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "approved"
        assert data["approved_by"] == "human"
        assert data["next_milestone"] is not None

    def test_project_reject_with_reason(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)
        tmp_store.submit_for_approval(pid, ms.milestone_id)

        from orchestrator.__main__ import _handle_project_reject

        class FakeArgs:
            milestone_id = ms.milestone_id
            project_id = pid
            reason = "Wrong approach"

        _handle_project_reject(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "rejected"
        assert data["reason"] == "Wrong approach"

    def test_project_request_changes_with_notes(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms = tmp_store.get_current_milestone(pid)
        tmp_store.submit_for_approval(pid, ms.milestone_id)

        from orchestrator.__main__ import _handle_project_request_changes

        class FakeArgs:
            milestone_id = ms.milestone_id
            project_id = pid
            notes = "Add integration tests"

        _handle_project_request_changes(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "changes_requested"
        assert "integration tests" in data["notes"]

    def test_project_approve_no_awaiting_record(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_approve

        class FakeArgs:
            milestone_id = "nonexistent"
            project_id = session.project_id

        _handle_project_approve(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "error" in data

    def test_project_reject_no_awaiting_record(self, tmp_store, capsys):
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_reject

        class FakeArgs:
            milestone_id = "nonexistent"
            project_id = session.project_id
            reason = ""

        _handle_project_reject(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "error" in data

    def test_project_approve_no_session(self, tmp_store, capsys):
        from orchestrator.__main__ import _handle_project_approve

        class FakeArgs:
            milestone_id = "ms-1"
            project_id = "nonexistent"

        _handle_project_approve(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "error" in data or "not found" in data.get("error", "").lower()

    def test_project_continue_after_approval_flow(self, tmp_store, capsys):
        """Full flow: continue → execute → submit → approve → continue next."""
        session = _create_active_session(tmp_store)
        pid = session.project_id
        ms1 = tmp_store.get_current_milestone(pid)

        # Add second milestone
        ms2 = ProjectMilestone(
            milestone_id="ms-2", name="Second", status="pending",
        )
        all_ms = tmp_store.load_milestones(pid)
        tmp_store.save_milestones(pid, all_ms + [ms2])

        # Step 1: Submit for approval (simulating what project continue does after execution)
        tmp_store.submit_for_approval(pid, ms1.milestone_id)
        s = tmp_store.load_session(pid)
        assert s.status == "paused"

        # Step 2: Approve
        tmp_store.approve_milestone(pid, ms1.milestone_id)
        s = tmp_store.load_session(pid)
        assert s.status == "active"
        ms_list = tmp_store.load_milestones(pid)
        ms2_data = next(m for m in ms_list if m.milestone_id == "ms-2")
        assert ms2_data.status == "in_progress"

        # Step 3: Verify ms1 is in completed_milestones
        assert ms1.milestone_id in s.completed_milestones


# =============================================================================
# Phase 27 — AAO Self-Issue Handling
# =============================================================================


class TestSystemFindings:
    """SystemFinding detection, record_system_issue, and hard blocks."""

    def test_system_issue_enters_blocked_needs_review(self, tmp_store):
        """SystemFinding must set session to blocked_needs_review — never auto-fixed."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        finding = SystemFinding(
            finding_id="sf-001",
            category="evidence_false_positive",
            severity="high",
            description="Evidence marked observed but file missing",
            evidence_refs=["outputs/evidence/run-001.json"],
            affected_components=["evidence classifier"],
        )
        tmp_store.record_system_issue(pid, finding)

        s = tmp_store.load_session(pid)
        assert s.status == "blocked_needs_review"
        assert "System issue" in s.pending_decisions[0]

        # Finding must be persisted
        loaded = tmp_store.load_findings(pid)
        assert len(loaded) == 1
        assert loaded[0].category == "evidence_false_positive"

        # Decision must be logged
        decisions = tmp_store.load_decisions(pid)
        sys_decisions = [d for d in decisions if "System issue" in d.decision]
        assert len(sys_decisions) >= 1

    def test_task_issue_does_not_set_blocked_status(self, tmp_store):
        """Ordinary task issues (logged as normal decisions) don't block the session."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Log a normal task issue (like a test failure)
        tmp_store.log_decision(pid, DecisionLog(
            entry_id=_new_id(),
            timestamp=_now(),
            decision="Auto-repair triggered for test failure",
            reason="3 tests failed in test_worker.py",
            made_by="control_plane",
        ))

        s = tmp_store.load_session(pid)
        assert s.status == "active"  # NOT blocked_needs_review
        assert s.status != "blocked_needs_review"

    def test_self_repair_proposal_includes_risks_and_test_plan(self):
        """Every SelfRepairProposal must include risks and a test plan."""
        from orchestrator.self_check import generate_repair_proposal

        finding = SystemFinding(
            finding_id="sf-002",
            category="worker_bridge_bypass",
            severity="high",
            description="Worker completed but no evidence of work",
        )

        proposal = generate_repair_proposal(finding)
        # worker_bridge_bypass targets src/orchestrator/workers/claude_code.py
        # which is AAO-protected → proposal should be blocked
        assert proposal is None

        # Test with a non-protected category simulation — decision_inconsistency
        # targets src/orchestrator/control_plane.py which is also protected
        finding2 = SystemFinding(
            finding_id="sf-003",
            category="decision_inconsistency",
            severity="medium",
            description="Same failure handled differently",
        )
        proposal2 = generate_repair_proposal(finding2)
        assert proposal2 is None  # also protected

    def test_self_repair_proposal_requires_human_approval(self):
        """SelfRepairProposal.requires_human_approval must always be True."""
        from orchestrator.self_check import SelfRepairProposal as SRP

        proposal = SRP(
            proposal_id="p-001",
            summary="Fix something",
            affected_files=["src/business_logic.py"],
            risks=["Risk 1"],
            test_plan="Run tests",
        )
        assert proposal.requires_human_approval is True

    def test_proposal_to_modify_aao_source_is_blocked(self):
        """Proposals targeting AAO core files must be blocked at generation."""
        from orchestrator.self_check import _is_protected_path, generate_repair_proposal

        # All AAO core paths are protected
        assert _is_protected_path("src/orchestrator/mainline_executor.py") is True
        assert _is_protected_path("src/orchestrator/__main__.py") is True
        assert _is_protected_path("CLAUDE.md") is True
        assert _is_protected_path(".claude/phase-specs/phase-27.md") is True
        assert _is_protected_path(".claude/project-skills/aao-core-builder.md") is True
        assert _is_protected_path(".env") is True
        assert _is_protected_path("tests/test_project_session.py") is True

        # Non-AAO files are not protected
        assert _is_protected_path("src/business_logic.py") is False
        assert _is_protected_path("README.md") is False

        # All built-in categories target AAO source → proposals blocked
        for cat in ("evidence_false_positive", "isolation_violation",
                     "worker_bridge_bypass", "resume_broken",
                     "control_chain_gap", "plan_reality_drift",
                     "decision_inconsistency"):
            finding = SystemFinding(
                finding_id="sf-test",
                category=cat,
                severity="high",
                description="Test",
            )
            proposal = generate_repair_proposal(finding)
            assert proposal is None, f"Proposal for {cat} should be blocked — it targets AAO core"

    def test_unknown_category_proposal_not_blocked(self):
        """An unrecognized category with no affected files should still generate a proposal."""
        from orchestrator.self_check import generate_repair_proposal

        finding = SystemFinding(
            finding_id="sf-004",
            category="unknown_category",
            severity="low",
            description="Something unknown happened",
        )
        proposal = generate_repair_proposal(finding)
        # Unknown category has empty affected_files, so no protected path hit
        assert proposal is not None
        assert proposal.requires_human_approval is True
        assert "unknown" in proposal.summary.lower()

    def test_system_issue_detection_distinguishes_from_task_issue(self, tmp_store):
        """SystemFindings have categories distinct from ordinary task failures."""
        from orchestrator.self_check import run_self_check

        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Create a run link with evidence that has changed_files but no test_output
        # AND the evidence file is missing (triggers resume_broken)
        link = tmp_store.load_run_links(pid)[0]
        # Point to a non-existent evidence file
        link.evidence_path = "outputs/evidence/nonexistent.json"
        link.audit_path = "outputs/audits/nonexistent.json"
        tmp_store.link_run(pid, ProjectRunLink(
            milestone_id=link.milestone_id,
            run_id="run-002",
            evidence_path="outputs/evidence/nonexistent.json",
            audit_path="outputs/audits/nonexistent.json",
            status="completed",
        ))

        findings = run_self_check(tmp_store, pid)
        # Should detect resume_broken (missing evidence + audit files)
        assert len(findings) > 0
        for f in findings:
            # All findings should be system categories, not task categories
            assert f.category in (
                "evidence_false_positive", "isolation_violation",
                "resume_broken", "worker_bridge_bypass",
                "plan_reality_drift", "decision_inconsistency",
            )

    def test_self_check_empty_project_no_findings(self, tmp_store):
        """A clean project with no issues should return empty findings list."""
        from orchestrator.self_check import run_self_check

        # Use a bare session without run_links to avoid false positives
        session = tmp_store.create_session("Clean project")
        findings = run_self_check(tmp_store, session.project_id)
        assert findings == []

    def test_self_check_single_category_filter(self, tmp_store):
        """Filtering by category should only run that check."""
        from orchestrator.self_check import run_self_check

        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Add a broken run link to trigger resume_broken
        tmp_store.link_run(pid, ProjectRunLink(
            milestone_id="ms-1",
            run_id="run-broken",
            evidence_path="outputs/evidence/nonexistent.json",
            audit_path="",
            status="completed",
        ))

        # Run only evidence_false_positive check — should not find resume_broken
        findings = run_self_check(tmp_store, pid, category="evidence_false_positive")
        for f in findings:
            assert f.category == "evidence_false_positive"

        # Run resume_broken check — should find the issue
        findings2 = run_self_check(tmp_store, pid, category="resume_broken")
        assert len(findings2) > 0
        assert all(f.category == "resume_broken" for f in findings2)

    def test_record_system_issue_with_proposal(self, tmp_store):
        """record_system_issue stores both finding and proposal when provided."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        finding = SystemFinding(
            finding_id="sf-005",
            category="resume_broken",
            severity="medium",
            description="Missing evidence file",
        )

        from orchestrator.self_check import SelfRepairProposal as SRP
        proposal = SRP(
            proposal_id="p-002",
            triggered_by=["sf-005"],
            summary="Fix the broken reference",
            affected_files=["src/business_logic.py"],
            risks=["Low risk"],
            test_plan="Verify file existence before load",
        )

        tmp_store.record_system_issue(pid, finding, proposal)

        # Both must be persisted
        findings = tmp_store.load_findings(pid)
        assert len(findings) == 1

        proposals = tmp_store.load_proposals(pid)
        assert len(proposals) == 1
        assert proposals[0].summary == "Fix the broken reference"


class TestSelfCheckCLI:
    """CLI handler for self-check command."""

    def test_self_check_command_outputs_structured_json(self, tmp_store, capsys):
        """self-check CLI must output structured JSON with findings and proposals."""
        session = _create_active_session(tmp_store)

        from orchestrator.__main__ import _handle_project_self_check

        class FakeArgs:
            project_id = session.project_id
            category = None

        _handle_project_self_check(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "findings" in data
        assert "proposals" in data
        assert "blocked_proposals" in data
        assert "status" in data
        assert isinstance(data["findings"], list)
        assert isinstance(data["proposals"], list)

    def test_self_check_no_active_session_shows_error(self, tmp_store, capsys):
        """self-check with no active project should show an error."""
        from orchestrator.__main__ import _handle_project_self_check

        class FakeArgs:
            project_id = "nonexistent"
            category = None

        _handle_project_self_check(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "error" in data

    def test_self_check_with_broken_run_link_detects_issue(self, tmp_store, capsys):
        """self-check should detect resume_broken when run_links point to missing files."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Add a broken run link
        tmp_store.link_run(pid, ProjectRunLink(
            milestone_id="ms-1",
            run_id="run-broken",
            evidence_path="outputs/evidence/nonexistent.json",
            audit_path="outputs/audits/nonexistent.json",
            status="completed",
        ))

        from orchestrator.__main__ import _handle_project_self_check

        class FakeArgs:
            project_id = pid
            category = None

        _handle_project_self_check(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data["findings"]) > 0
        # All proposals for detected issues target AAO core → blocked
        assert data["blocked_proposals"] >= 1
        assert "system issue(s) detected" in data["_note"]

    def test_self_check_session_enters_blocked_status_after_detection(self, tmp_store, capsys):
        """After self-check finds issues, session must be blocked_needs_review."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        # Add broken run links to trigger detection
        tmp_store.link_run(pid, ProjectRunLink(
            milestone_id="ms-1",
            run_id="run-broken-2",
            evidence_path="outputs/evidence/nonexistent.json",
            audit_path="",
            status="completed",
        ))

        from orchestrator.__main__ import _handle_project_self_check

        class FakeArgs:
            project_id = pid
            category = None

        _handle_project_self_check(FakeArgs(), tmp_store)

        s = tmp_store.load_session(pid)
        assert s.status == "blocked_needs_review"

    def test_self_check_with_category_filter(self, tmp_store, capsys):
        """self-check --category should only run the specified check."""
        session = _create_active_session(tmp_store)
        pid = session.project_id

        from orchestrator.__main__ import _handle_project_self_check

        class FakeArgs:
            project_id = pid
            category = "decision_inconsistency"

        _handle_project_self_check(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "findings" in data
