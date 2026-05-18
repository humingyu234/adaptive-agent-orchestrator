"""Tests for control_models — behaviour, serialization, and edge cases."""

import json
import unittest

from orchestrator.control_models import (
    ControlDecision,
    EvidencePack,
    WorkerResult,
    WorkerTask,
)


class ControlDecisionTest(unittest.TestCase):
    """ControlDecision is the primary control-plane verdict object."""

    def test_default_is_continue(self):
        decision = ControlDecision()
        self.assertTrue(decision.passed)
        self.assertEqual(decision.action, "continue")
        self.assertEqual(decision.reason, "")

    def test_failed_decision_includes_failure_category(self):
        decision = ControlDecision(
            action="retry",
            passed=False,
            reason="raw_documents empty",
            severity="medium",
            failure_category="search_result_empty",
        )
        self.assertFalse(decision.passed)
        self.assertEqual(decision.action, "retry")
        self.assertEqual(decision.severity, "medium")
        self.assertEqual(decision.failure_category, "search_result_empty")

    def test_replan_decision_can_carry_next_step_hint(self):
        decision = ControlDecision(
            action="replan",
            passed=False,
            reason="planner unstable",
            next_step_hint="planner",
        )
        self.assertEqual(decision.action, "replan")
        self.assertEqual(decision.next_step_hint, "planner")

    def test_human_review_decision_sets_evidence_required(self):
        decision = ControlDecision(
            action="needs_human_review",
            passed=False,
            reason="high-risk tool call detected",
            evidence_required=True,
        )
        self.assertTrue(decision.evidence_required)

    def test_rollback_decision_includes_failure_category(self):
        decision = ControlDecision(
            action="rollback",
            passed=False,
            reason="supervisor triggered rollback",
            failure_category="supervisor_replan",
        )
        self.assertEqual(decision.action, "rollback")
        self.assertEqual(decision.failure_category, "supervisor_replan")

    def test_serializable_with_model_dump(self):
        decision = ControlDecision(
            action="continue",
            passed=True,
            reason="all checks passed",
        )
        dumped = decision.model_dump()
        self.assertEqual(dumped["action"], "continue")
        self.assertTrue(dumped["passed"])
        reloaded = ControlDecision(**json.loads(json.dumps(dumped)))
        self.assertEqual(reloaded.action, decision.action)
        self.assertEqual(reloaded.passed, decision.passed)


class WorkerTaskTest(unittest.TestCase):
    """WorkerTask describes work before it starts."""

    def test_records_allowed_files_and_required_checks(self):
        task = WorkerTask(
            task_id="task-1",
            objective="refactor auth module",
            allowed_files=["src/auth/**", "tests/auth/**"],
            required_checks=["pytest", "mypy"],
            risk_level="medium",
        )
        self.assertEqual(task.task_id, "task-1")
        self.assertEqual(task.allowed_files, ["src/auth/**", "tests/auth/**"])
        self.assertEqual(task.required_checks, ["pytest", "mypy"])
        self.assertEqual(task.risk_level, "medium")

    def test_defaults_are_safe(self):
        task = WorkerTask(task_id="t", objective="test")
        self.assertEqual(task.allowed_files, [])
        self.assertEqual(task.required_checks, [])
        self.assertEqual(task.risk_level, "low")
        self.assertEqual(task.mode, "controlled")

    def test_high_risk_task_sets_risk_level(self):
        task = WorkerTask(
            task_id="task-2",
            objective="deploy to production",
            risk_level="high",
        )
        self.assertEqual(task.risk_level, "high")

    def test_serializable_with_model_dump(self):
        task = WorkerTask(
            task_id="task-3",
            objective="update dependencies",
            allowed_files=["requirements.txt"],
            required_checks=["pytest"],
        )
        dumped = task.model_dump()
        self.assertEqual(dumped["task_id"], "task-3")
        self.assertEqual(dumped["objective"], "update dependencies")


class WorkerResultTest(unittest.TestCase):
    """WorkerResult records what happened after a task."""

    def test_completed_result_records_output(self):
        result = WorkerResult(
            task_id="task-1",
            worker_name="planner",
            status="completed",
            output={"plan": {"sub_questions": ["q1", "q2"]}},
            files_changed=["src/auth/login.py"],
            commands_run=["pytest"],
            tests_run=["test_login.py"],
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.worker_name, "planner")
        self.assertIn("plan", result.output)
        self.assertEqual(result.files_changed, ["src/auth/login.py"])

    def test_failed_result_records_errors(self):
        result = WorkerResult(
            task_id="task-2",
            worker_name="search",
            status="failed",
            errors=["search API timeout"],
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.errors, ["search API timeout"])

    def test_missing_optional_fields_do_not_crash(self):
        result = WorkerResult(
            task_id="t",
            worker_name="w",
            status="completed",
        )
        self.assertEqual(result.files_changed, [])
        self.assertEqual(result.commands_run, [])
        self.assertEqual(result.tests_run, [])
        self.assertEqual(result.errors, [])

    def test_serializable_with_model_dump(self):
        result = WorkerResult(
            task_id="task-4",
            worker_name="summarizer",
            status="completed",
            output={"summary": "done"},
        )
        dumped = result.model_dump()
        self.assertEqual(dumped["worker_name"], "summarizer")
        self.assertEqual(dumped["status"], "completed")


class EvidencePackTest(unittest.TestCase):
    """EvidencePack records observed facts, not invented ones."""

    def test_records_commands_and_test_results(self):
        evidence = EvidencePack(
            task_id="task-1",
            step_name="search",
            commands_run=["python -m pytest tests/"],
            test_results={"passed": 80, "failed": 0},
        )
        self.assertEqual(evidence.task_id, "task-1")
        self.assertEqual(evidence.step_name, "search")
        self.assertEqual(evidence.commands_run, ["python -m pytest tests/"])
        self.assertEqual(evidence.test_results["passed"], 80)

    def test_empty_evidence_is_valid(self):
        evidence = EvidencePack(task_id="t", step_name="s")
        self.assertEqual(evidence.files_changed, [])
        self.assertEqual(evidence.commands_run, [])
        self.assertEqual(evidence.test_results, {})
        self.assertEqual(evidence.diff_summary, "")
        self.assertEqual(evidence.notes, "")

    def test_files_changed_are_recorded(self):
        evidence = EvidencePack(
            task_id="task-2",
            step_name="refactor",
            files_changed=["src/orchestrator/scheduler.py"],
        )
        self.assertIn("src/orchestrator/scheduler.py", evidence.files_changed)

    def test_missing_fields_do_not_crash_serialization(self):
        evidence = EvidencePack(task_id="task-3", step_name="summarize")
        dumped = evidence.model_dump()
        self.assertEqual(dumped["files_changed"], [])
        self.assertIsInstance(json.dumps(dumped), str)

    def test_notes_and_diff_can_be_populated(self):
        evidence = EvidencePack(
            task_id="task-4",
            step_name="code_review",
            diff_summary="3 files changed, +12 -4",
            notes="all changes in allowed scope",
        )
        self.assertEqual(evidence.diff_summary, "3 files changed, +12 -4")
        self.assertEqual(evidence.notes, "all changes in allowed scope")


if __name__ == "__main__":
    unittest.main()
