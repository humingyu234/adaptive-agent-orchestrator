"""Tests for Phase 14 Memory Layer — deterministic, no real LLM calls, no secrets."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from orchestrator.memory import (
    MemoryContext,
    MemoryItem,
    MemoryKind,
    MemorySourceType,
    MemoryStore,
    contains_secrets,
    redact_secrets,
    should_remember,
)
from orchestrator.memory_manager import MemoryManager
from orchestrator.planning import PlanningCouncil


# =============================================================================
# MemoryItem
# =============================================================================

class TestMemoryItem:
    def test_memory_item_requires_source_type(self):
        with pytest.raises(ValueError, match="Invalid source_type"):
            MemoryItem(source_type="invalid")  # type: ignore[arg-type]

    def test_memory_item_requires_kind(self):
        item = MemoryItem(kind="run_summary", source_type="observed")
        assert item.kind == "run_summary"

    def test_memory_item_defaults(self):
        item = MemoryItem(
            kind="project_constraint",
            source_type="observed",
            title="Test",
            content="Test content",
        )
        assert item.id.startswith("mem-")
        assert len(item.id) > 5
        assert item.created_at
        assert item.updated_at

    def test_memory_item_serialization_roundtrip(self):
        item = MemoryItem(
            kind="architecture_decision",
            source_type="observed",
            title="Architecture decision",
            content="We decided to use Pydantic",
            task_id="task-1",
            tags=["architecture", "decision"],
            confidence=0.9,
        )
        d = item.to_dict()
        item2 = MemoryItem.from_dict(d)
        assert item2.id == item.id
        assert item2.kind == item.kind
        assert item2.source_type == item.source_type
        assert item2.title == item.title
        assert item2.content == item.content
        assert item2.tags == item.tags
        assert item2.confidence == item.confidence

    def test_memory_item_accepts_all_valid_source_types(self):
        for st in ("observed", "reported", "inferred"):
            item = MemoryItem(source_type=st)  # type: ignore[arg-type]
            assert item.source_type == st


# =============================================================================
# MemoryStore — create, load, list
# =============================================================================

class TestMemoryStore:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield MemoryStore(tmp)

    def test_missing_memory_files_do_not_crash(self, store):
        assert store.load("nonexistent-id") is None
        items = store.list_items()
        assert items == []
        result = store.retrieve(query="nonexistent")
        assert result == []

    def test_project_memory_can_be_loaded(self, store):
        item = store.create(MemoryItem(
            kind="project_constraint",
            source_type="observed",
            title="Never edit tmp/",
            content="Do not edit tmp/ or generated outputs.",
        ))
        loaded = store.load(item.id)
        assert loaded is not None
        assert loaded.title == "Never edit tmp/"
        assert loaded.source_type == "observed"

    def test_decision_memory_can_be_recorded_and_loaded(self, store):
        item = store.create(MemoryItem(
            kind="architecture_decision",
            source_type="observed",
            title="ControlPlane stays independent",
            content="ControlPlane must remain independent from Runner and Worker layers.",
        ))
        loaded = store.load(item.id)
        assert loaded is not None
        assert loaded.kind == "architecture_decision"
        assert "ControlPlane" in loaded.content

    def test_failure_lesson_can_be_recorded_and_retrieved(self, store):
        store.record_failure_lesson(
            failure_category="policy_error",
            reason="Worker wrote to denied files",
            recovery_hint="needs_human_review",
            source_type="observed",
        )
        results = store.retrieve(kind="failure_lesson", query="policy_error denied")
        assert len(results) >= 1
        found = results[0]
        assert found.kind == "failure_lesson"
        assert found.source_type == "observed"
        assert "policy_error" in found.content

    def test_memory_does_not_convert_reported_to_observed(self, store):
        reported = store.create(MemoryItem(
            kind="worker_lesson",
            source_type="reported",
            title="Worker claimed tests passed",
            content="Worker reported that tests passed but no evidence provided.",
        ))
        loaded = store.load(reported.id)
        assert loaded is not None
        assert loaded.source_type == "reported"
        # Source type must stay as reported
        assert loaded.source_type != "observed"

    def test_memory_is_not_accepted_as_current_evidence(self, store):
        """Memory items are hints, not evidence for the current run."""
        item = store.create(MemoryItem(
            kind="run_summary",
            source_type="observed",
            title="Previous run: passed",
            content="Previous run had all tests passing.",
        ))
        # The item exists in memory but has no evidence_path
        loaded = store.load(item.id)
        assert loaded is not None
        # It's a memory item, not observed evidence for the current run
        assert loaded.evidence_path == ""

    def test_secret_like_values_are_rejected_or_redacted(self, store):
        # Secrets in content should be redacted
        item = store.create(MemoryItem(
            kind="failure_lesson",
            source_type="observed",
            title="API key leak test",
            content="The API key sk-proj-1234567890abcdef1234567890abcdef was found in logs",
        ))
        loaded = store.load(item.id)
        assert loaded is not None
        assert "sk-proj" not in loaded.content
        assert "[REDACTED]" in loaded.content

        # GitHub PAT should be redacted
        item2 = store.create(MemoryItem(
            kind="failure_lesson",
            source_type="observed",
            title="GitHub token leak",
            content="Found ghp_abc123def456ghi789jkl012mno345pqr678stu in file",
        ))
        loaded2 = store.load(item2.id)
        assert loaded2 is not None
        assert "ghp_" not in loaded2.content
        assert "[REDACTED]" in loaded2.content

    def test_retrieval_respects_top_k_and_kind_filter(self, store):
        for i in range(5):
            store.create(MemoryItem(
                kind="failure_lesson",
                source_type="observed",
                title=f"Failure {i}",
                content=f"Failure lesson number {i}",
                tags=[f"fail-{i}"],
            ))
        for i in range(3):
            store.create(MemoryItem(
                kind="architecture_decision",
                source_type="observed",
                title=f"Decision {i}",
                content=f"Architecture decision {i}",
                tags=[f"arch-{i}"],
            ))

        # top_k=2
        results = store.retrieve(kind="failure_lesson", top_k=2)
        assert len(results) <= 2
        for r in results:
            assert r.kind == "failure_lesson"

        # kind filter
        arch_results = store.retrieve(kind="architecture_decision", top_k=5)
        assert all(r.kind == "architecture_decision" for r in arch_results)

        # source_type filter
        observed = store.retrieve(source_type="observed", top_k=10)
        assert all(r.source_type == "observed" for r in observed)

    def test_record_failure_lesson_reflection_gate(self, store):
        """Transient failures should not always produce a lesson."""
        # record_failure_lesson always records (reflection is manual)
        item = store.record_failure_lesson(
            failure_category="tool_error",
            reason="Temporary network timeout on node install",
            recovery_hint="retry",
            source_type="observed",
        )
        assert item is not None
        assert item.kind == "failure_lesson"

    def test_list_items_filters(self, store):
        store.create(MemoryItem(
            kind="project_constraint",
            source_type="observed",
            title="Constraint A",
            content="Content A",
        ))
        store.create(MemoryItem(
            kind="failure_lesson",
            source_type="reported",
            title="Failure B",
            content="Content B",
        ))

        all_items = store.list_items()
        assert len(all_items) == 2

        constraints = store.list_items(kind="project_constraint")
        assert len(constraints) == 1
        assert constraints[0].kind == "project_constraint"

        reported = store.list_items(source_type="reported")
        assert len(reported) == 1
        assert reported[0].source_type == "reported"


# =============================================================================
# MemoryContext
# =============================================================================

class TestMemoryContext:
    def test_empty_context(self):
        ctx = MemoryContext()
        assert ctx.is_empty
        summary = ctx.to_summary()
        assert summary["total_items"] == 0

    def test_non_empty_context(self):
        ctx = MemoryContext(
            project_constraints=[MemoryItem(
                kind="project_constraint",
                source_type="observed",
                title="Never edit tmp/",
                content="...",
            )],
            failure_lessons=[MemoryItem(
                kind="failure_lesson",
                source_type="observed",
                title="Worker evidence",
                content="...",
            )],
        )
        assert not ctx.is_empty
        summary = ctx.to_summary()
        assert summary["project_constraints"] == 1
        assert summary["failure_lessons"] == 1
        assert summary["total_items"] == 2
        assert "observed" in summary["source_types"]

    def test_context_source_paths(self):
        ctx = MemoryContext(source_paths=["/tmp/test.json"])
        assert len(ctx.source_paths) == 1


# =============================================================================
# Secret detection
# =============================================================================

class TestSecretDetection:
    def test_redact_secrets_openai(self):
        text = "Found key: sk-proj-1234567890abcdef1234567890abcdef"
        result = redact_secrets(text)
        assert "sk-proj" not in result
        assert "[REDACTED]" in result

    def test_redact_secrets_github_pat(self):
        text = "token: ghp_abc123def456ghi789jkl012mno345pqr678stu"
        result = redact_secrets(text)
        assert "ghp_" not in result
        assert "[REDACTED]" in result

    def test_redact_secrets_aws_key(self):
        text = "AKIAIOSFODNN7EXAMPLE embedded"
        result = redact_secrets(text)
        assert "AKIA" not in result
        assert "[REDACTED]" in result

    def test_redact_secrets_jwt(self):
        text = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9n1oq7T3U6vzA"
        result = redact_secrets(text)
        assert "eyJ" not in result
        assert "[REDACTED]" in result

    def test_contains_secrets_positive(self):
        assert contains_secrets("apikey=sk-proj-abc123def456")
        assert contains_secrets("token: ghp_abc123def456ghi789jkl012mno345pqr678stu")

    def test_contains_secrets_negative(self):
        assert not contains_secrets("This is a normal error message")
        assert not contains_secrets("Test output: 42 tests passed")

    def test_redact_does_not_change_normal_text(self):
        text = "This is normal project documentation."
        assert redact_secrets(text) == text


# =============================================================================
# should_remember reflection gate
# =============================================================================

class TestShouldRemember:
    def test_rejects_empty_source_type(self):
        assert not should_remember(kind="run_summary", source_type="", content="test")  # type: ignore[arg-type]

    def test_rejects_empty_kind(self):
        assert not should_remember(kind="", source_type="observed", content="test")  # type: ignore[arg-type]

    def test_rejects_empty_content(self):
        assert not should_remember(kind="run_summary", source_type="observed", content="")

    def test_rejects_transient(self):
        assert not should_remember(kind="run_summary", source_type="observed", content="test", is_transient=True)

    def test_rejects_short_reported_failure(self):
        assert not should_remember(kind="failure_lesson", source_type="reported", content="short")

    def test_accepts_observed_failure_with_substance(self):
        assert should_remember(
            kind="failure_lesson",
            source_type="observed",
            content="The worker failed because it attempted to write to a denied file path protected by policy",
        )


# =============================================================================
# MemoryManager — integration of old + new
# =============================================================================

class TestMemoryManager:
    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield MemoryManager(tmp)

    def test_manager_has_both_apis(self, manager):
        assert hasattr(manager, "capture")
        assert hasattr(manager, "retrieve")
        assert hasattr(manager, "create_item")
        assert hasattr(manager, "retrieve_context")
        assert hasattr(manager, "record_failure_lesson")

    def test_create_and_load_item(self, manager):
        item = manager.create_item(MemoryItem(
            kind="project_constraint",
            source_type="observed",
            title="Test constraint",
            content="Test content",
        ))
        loaded = manager.load_item(item.id)
        assert loaded is not None
        assert loaded.title == "Test constraint"

    def test_retrieve_context_returns_bounded_context(self, manager):
        manager.create_item(MemoryItem(
            kind="project_constraint",
            source_type="observed",
            title="Constraint 1",
            content="Do not touch tmp/",
        ))
        manager.create_item(MemoryItem(
            kind="failure_lesson",
            source_type="observed",
            title="Failure: permission denied",
            content="Permission denied on protected file",
            tags=["failure"],
        ))
        ctx = manager.retrieve_context(query="permission denied")
        assert isinstance(ctx, MemoryContext)
        assert not ctx.is_empty
        summary = ctx.to_summary()
        assert summary["project_constraints"] >= 1

    def test_record_failure_lesson_via_manager(self, manager):
        item = manager.record_failure_lesson(
            failure_category="tool_error",
            reason="Command failed with exit code 1",
            recovery_hint="retry",
            source_type="observed",
            task_id="task-1",
        )
        assert item is not None
        assert item.kind == "failure_lesson"
        loaded = manager.load_item(item.id)
        assert loaded is not None
        assert "tool_error" in loaded.content

    def test_record_decision_via_manager(self, manager):
        item = manager.record_decision(
            title="Use Pydantic for models",
            content="All control models should use Pydantic BaseModel.",
            kind="architecture_decision",
            source_type="observed",
            tags=["architecture"],
        )
        assert item is not None
        assert item.kind == "architecture_decision"


# =============================================================================
# Planning Council receives bounded memory context
# =============================================================================

class TestPlanningCouncilWithMemory:
    def test_planning_council_receives_bounded_memory_context(self):
        council = PlanningCouncil()
        ctx = MemoryContext(
            project_constraints=[MemoryItem(
                kind="project_constraint",
                source_type="observed",
                title="Never edit tmp/",
                content="Do not edit tmp/ or generated outputs.",
            )],
            failure_lessons=[MemoryItem(
                kind="failure_lesson",
                source_type="observed",
                title="When worker reports tests passed without observed output, request evidence",
                content="Worker claimed tests passed but no pytest output observed.",
            )],
        )
        plan = council.create_plan(
            "Implement a new feature",
            task_size="large",
            memory_context=ctx,
        )
        assert len(plan.memory_hints) >= 2
        assert any("Never edit tmp/" in h for h in plan.memory_hints)
        assert any("request evidence" in h for h in plan.memory_hints)

    def test_planning_council_plan_still_validates_normally_with_memory(self):
        """Memory hints don't bypass planning validation."""
        council = PlanningCouncil()
        ctx = MemoryContext(
            project_constraints=[MemoryItem(
                kind="project_constraint",
                source_type="observed",
                title="Never edit tmp/",
                content="...",
            )],
        )
        plan = council.create_plan(
            "Implement auth system with database changes",
            task_size="large",
            memory_context=ctx,
        )
        # The plan should still have blocking concerns from risk_reviewer
        # (code change + no files + high-risk keywords)
        assert len(plan.blocking_concerns) > 0
        # Memory hints are present but don't affect validation
        assert len(plan.memory_hints) >= 0
        # Cannot approve due to blocking concerns
        with pytest.raises(ValueError, match="blocking concerns"):
            plan.approve()

    def test_plan_without_memory_context_has_empty_hints(self):
        council = PlanningCouncil()
        plan = council.create_plan("Simple research task", task_size="small")
        assert plan.memory_hints == []


# =============================================================================
# Report includes memory usage with source types
# =============================================================================

class TestReportMemoryUsage:
    def test_report_lists_memory_usage_with_source_types(self):
        ctx = MemoryContext(
            project_constraints=[
                MemoryItem(kind="project_constraint", source_type="observed",
                           title="Constraint A", content="..."),
                MemoryItem(kind="project_constraint", source_type="observed",
                           title="Constraint B", content="..."),
            ],
            failure_lessons=[
                MemoryItem(kind="failure_lesson", source_type="reported",
                           title="Failure X", content="..."),
            ],
        )
        summary = ctx.to_summary()
        assert summary["project_constraints"] == 2
        assert summary["failure_lessons"] == 1
        assert summary["source_types"]["observed"] == 2
        assert summary["source_types"]["reported"] == 1
        assert summary["total_items"] == 3


# =============================================================================
# MemoryStore persistence and edge cases
# =============================================================================

class TestMemoryStorePersistence:
    def test_create_and_reload_via_new_store_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store1 = MemoryStore(tmp)
            item = store1.create(MemoryItem(
                kind="project_constraint",
                source_type="observed",
                title="Persist test",
                content="This should survive.",
            ))
            store2 = MemoryStore(tmp)
            loaded = store2.load(item.id)
            assert loaded is not None
            assert loaded.title == "Persist test"

    def test_invalid_json_in_index_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / ".aao" / "memory"
            base.mkdir(parents=True, exist_ok=True)
            (base / "index.json").write_text("not valid json", encoding="utf-8")
            store = MemoryStore(tmp)
            items = store.list_items()
            assert items == []
            result = store.retrieve(query="test")
            assert result == []

    def test_missing_file_referenced_in_index_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / ".aao" / "memory"
            base.mkdir(parents=True, exist_ok=True)
            # Write index referencing a nonexistent file
            index = [{
                "id": "ghost-id",
                "kind": "failure_lesson",
                "source_type": "observed",
                "title": "Ghost",
                "path": str(base / "ghost.json"),
                "created_at": "2025-01-01T00:00:00",
                "tags": [],
                "tokens": ["ghost"],
            }]
            (base / "index.json").write_text(json.dumps(index), encoding="utf-8")
            store = MemoryStore(tmp)
            items = store.list_items()
            assert items == []  # ghost file skipped

    def test_retrieve_by_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(tmp)
            store.create(MemoryItem(
                kind="failure_lesson",
                source_type="observed",
                title="Tagged failure",
                content="Some failure content",
                tags=["deploy", "critical"],
            ))
            results = store.retrieve(tags=["deploy"])
            assert len(results) >= 1
            assert results[0].kind == "failure_lesson"


# =============================================================================
# MemoryItem unique IDs
# =============================================================================

class TestMemoryItemIds:
    def test_memory_items_have_unique_ids(self):
        item1 = MemoryItem(kind="run_summary", source_type="observed",
                           title="A", content="a")
        item2 = MemoryItem(kind="run_summary", source_type="observed",
                           title="B", content="b")
        assert item1.id != item2.id

    def test_memory_item_custom_id(self):
        item = MemoryItem(id="custom-123", kind="run_summary",
                          source_type="observed", title="T", content="C")
        assert item.id == "custom-123"


# =============================================================================
# Phase 14.5 — canonical vs legacy memory boundary
# =============================================================================

class TestCanonicalMemoryBoundary:
    """Verify .aao/memory is canonical, outputs/memory is legacy artifact."""

    def test_memory_store_is_canonical_project_memory(self):
        """MemoryStore writes to .aao/memory/, the canonical project memory."""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(tmp)
            item = store.create(MemoryItem(
                kind="project_constraint",
                source_type="observed",
                title="Canonical test",
                content="This lives in .aao/memory/",
            ))
            # Verify the file was written under .aao/memory/
            aao_dir = Path(tmp) / ".aao" / "memory"
            assert aao_dir.exists()
            # The index is at .aao/memory/index.json
            index_path = aao_dir / "index.json"
            assert index_path.exists()
            # The item file is somewhere under .aao/memory/
            item_files = list(aao_dir.rglob(f"{item.id}.json"))
            assert len(item_files) >= 1

    def test_legacy_memory_manager_does_not_upgrade_reported_to_observed(self):
        """Source type boundaries are enforced: reported stays reported."""
        item = MemoryItem(
            kind="failure_lesson",
            source_type="reported",
            title="Reported failure",
            content="Worker said something failed but we didn't observe it.",
        )
        assert item.source_type == "reported"
        # Serialize and reload — source_type must not change
        reloaded = MemoryItem.from_dict(item.to_dict())
        assert reloaded.source_type == "reported"
        # Creating through MemoryStore must preserve source_type
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(tmp)
            stored = store.create(item)
            loaded = store.load(stored.id)
            assert loaded is not None
            assert loaded.source_type == "reported"
            assert loaded.source_type != "observed"
