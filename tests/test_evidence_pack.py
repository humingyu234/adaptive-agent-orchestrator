"""Tests for Phase 4 — EvidencePack builder and integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from orchestrator.control_models import EvidencePack
from orchestrator.evidence import (
    build_evidence_pack,
    build_evidence_pack_from_log_record,
    evidence_packs_from_logs,
)


# ===========================================================================
# 1. build_evidence_pack — successful step
# ===========================================================================

class TestBuildEvidencePack:
    def test_successful_step_produces_evidence(self):
        pack = build_evidence_pack(
            task_id="task-1",
            step_name="planner",
            status="success",
            duration_ms=1234,
            timestamp="2025-01-01T00:00:00Z",
            evaluation={"passed": True, "action": "continue"},
            output_summary="Plan created",
        )
        assert pack.task_id == "task-1"
        assert pack.step_name == "planner"
        assert pack.status == "success"
        assert pack.duration_ms == 1234
        assert pack.evaluation == {"passed": True, "action": "continue"}
        assert pack.output_summary == "Plan created"
        assert pack.failure_reason == ""

    def test_failed_step_records_failure_reason(self):
        pack = build_evidence_pack(
            task_id="task-2",
            step_name="search",
            status="error",
            duration_ms=500,
            failure_reason="connection refused",
        )
        assert pack.status == "error"
        assert pack.failure_reason == "connection refused"
        assert pack.evaluation is None

    def test_missing_optional_fields_do_not_crash(self):
        pack = build_evidence_pack(
            task_id="task-3",
            step_name="summarizer",
            status="success",
        )
        assert pack.status == "success"
        assert pack.duration_ms == 0
        assert pack.evaluation is None
        assert pack.failure_reason == ""
        assert pack.files_changed == []
        assert pack.commands_run == []
        assert pack.test_results == {}

    def test_serializable_with_model_dump(self):
        pack = build_evidence_pack(
            task_id="task-4",
            step_name="planner",
            status="success",
            evaluation={"passed": True, "action": "continue"},
        )
        dumped = pack.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["task_id"] == "task-4"
        json_text = json.dumps(dumped)
        assert isinstance(json_text, str)

    def test_does_not_invent_files_or_commands(self):
        pack = build_evidence_pack(
            task_id="task-5",
            step_name="worker",
            status="success",
        )
        assert pack.files_changed == []
        assert pack.commands_run == []
        assert pack.test_results == {}
        assert pack.diff_summary == ""


# ===========================================================================
# 2. build_evidence_pack_from_log_record
# ===========================================================================

class TestBuildEvidenceFromLogRecord:
    def test_maps_log_record_fields(self):
        record = {
            "task_id": "abc123",
            "agent": "planner",
            "status": "success",
            "duration_ms": 987,
            "timestamp": "2025-01-01T00:00:00Z",
            "evaluation": {"passed": True, "action": "continue"},
            "output_hash": "abc123def456",
        }
        pack = build_evidence_pack_from_log_record(
            log_record=record,
            report_path="/tmp/report.json",
        )
        assert pack.task_id == "abc123"
        assert pack.step_name == "planner"
        assert pack.status == "success"
        assert pack.duration_ms == 987
        assert pack.evaluation == {"passed": True, "action": "continue"}
        assert pack.report_path == "/tmp/report.json"
        assert pack.files_changed == []
        assert pack.commands_run == []

    def test_error_log_record_captures_failure(self):
        record = {
            "task_id": "fail-1",
            "agent": "worker",
            "status": "error",
            "duration_ms": 100,
            "timestamp": "",
            "error": "something broke",
        }
        pack = build_evidence_pack_from_log_record(log_record=record)
        assert pack.status == "error"
        assert "something broke" in pack.failure_reason


# ===========================================================================
# 3. evidence_packs_from_logs
# ===========================================================================

class TestEvidencePacksFromLogs:
    def test_converts_multiple_records(self):
        records = [
            {"task_id": "t1", "agent": "a1", "status": "success", "duration_ms": 100, "timestamp": ""},
            {"task_id": "t1", "agent": "a2", "status": "success", "duration_ms": 200, "timestamp": ""},
        ]
        packs = evidence_packs_from_logs(log_records=records, report_path="/r.json")
        assert len(packs) == 2
        assert packs[0].step_name == "a1"
        assert packs[1].step_name == "a2"

    def test_empty_logs_returns_empty_list(self):
        packs = evidence_packs_from_logs(log_records=[])
        assert packs == []


# ===========================================================================
# 4. Integration — evidence written during scheduler run
# ===========================================================================

class TestEvidenceIntegration:
    def test_evidence_file_exists_after_completed_run(self):
        import orchestrator.agents as _agents  # noqa: F401
        from orchestrator.scheduler import Scheduler
        from orchestrator.workflow import load_workflow

        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="evidence integration test")

            assert result.status == "completed"
            assert result.evidence_path is not None
            evidence_file = Path(result.evidence_path)
            assert evidence_file.exists()

            packs = json.loads(evidence_file.read_text())
            assert len(packs) >= 1
            for pack in packs:
                assert "task_id" in pack
                assert "step_name" in pack
                assert "status" in pack

    def test_evidence_in_report_after_completed_run(self):
        import orchestrator.agents as _agents  # noqa: F401
        from orchestrator.scheduler import Scheduler
        from orchestrator.workflow import load_workflow

        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="evidence report test")

            assert result.status == "completed"
            report = json.loads(Path(result.convergence_report_path).read_text())
            assert "evidence_summary" in report
            assert report["evidence_summary"]["steps_with_evidence"] >= 1

# ===========================================================================
# 5. EvidencePack output_summary (Phase 7A Fix 5)
# ===========================================================================

class TestEvidenceOutputSummary:
    def test_derives_bounded_output_summary_from_recorded_output(self):
        record = {
            "task_id": "t1",
            "agent": "summarizer",
            "status": "success",
            "duration_ms": 200,
            "timestamp": "2026-01-01T00:00:00Z",
            "output_summary": "summary: here is a conclusion; plan_type: research",
        }
        pack = build_evidence_pack_from_log_record(log_record=record)
        assert pack.output_summary == "summary: here is a conclusion; plan_type: research"

    def test_output_summary_is_bounded_to_500_chars(self):
        long_value = "field: " + ("x" * 600)
        record = {
            "task_id": "t2",
            "agent": "worker",
            "status": "success",
            "output_summary": long_value,
        }
        pack = build_evidence_pack_from_log_record(log_record=record)
        assert len(pack.output_summary) <= 500

    def test_empty_output_summary_when_not_recorded(self):
        record = {
            "task_id": "t3",
            "agent": "worker",
            "status": "error",
        }
        pack = build_evidence_pack_from_log_record(log_record=record)
        assert pack.output_summary == ""

    def test_does_not_invent_files_commands_tests_or_diff(self):
        record = {
            "task_id": "t4",
            "agent": "planner",
            "status": "success",
            "output_summary": "plan: research questions",
        }
        pack = build_evidence_pack_from_log_record(
            log_record=record,
            report_path="/tmp/r.json",
        )
        assert pack.files_changed == []
        assert pack.commands_run == []
        assert pack.test_results == {}
        assert pack.diff_summary == ""


class TestEvidenceSummaryInReport:
    def test_evidence_summary_is_readable_and_bounded(self):
        import orchestrator.agents as _agents  # noqa: F401
        from orchestrator.scheduler import Scheduler
        from orchestrator.workflow import load_workflow

        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="evidence summary test")

            assert result.status == "completed"
            report = json.loads(Path(result.convergence_report_path).read_text())
            assert "evidence_summary" in report
            es = report["evidence_summary"]
            assert es["steps_with_evidence"] >= 1
            assert isinstance(es, dict)
            steps = es.get("steps") or es.get("step_summaries") or []
            assert len(steps) >= 1, "evidence_summary must contain step entries"
            for step in steps:
                assert "step_name" in step
                assert "status" in step
                assert "output_summary" in step, (
                    f"Step {step.get('step_name')} missing output_summary"
                )
                assert isinstance(step["output_summary"], str)

