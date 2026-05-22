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
    ProjectMilestone,
    ProjectRunLink,
    ProjectSession,
    ProjectSessionStore,
    SessionContext,
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
        session = _create_active_session(tmp_store)
        # Pause first
        session.status = "paused"
        tmp_store.save_session(session)

        from orchestrator.__main__ import _handle_project_continue

        class FakeArgs:
            project_id = session.project_id

        _handle_project_continue(FakeArgs(), tmp_store)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "active"

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
        assert "error" in data or "No active" in data.get("answer", "")

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
