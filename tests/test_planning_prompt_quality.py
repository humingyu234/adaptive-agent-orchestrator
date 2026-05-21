"""Phase 19 Prompt Quality Gate — local validators against golden planning cases.

These tests prove that AAO's prompt validation rejects malformed, vague,
or non-executable plans.  All tests use fake providers / deterministic
fixtures — no LLM keys or network required.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from orchestrator.planning_prompts import (
    PLANNER_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    EXECUTION_PLANNER_SYSTEM_PROMPT,
    build_planner_prompt,
    build_reviewer_prompt,
    build_execution_planner_prompt,
    validate_planner_output,
    validate_reviewer_output,
    validate_execution_planner_output,
    validate_planner_pydantic,
    validate_reviewer_pydantic,
    validate_execution_planner_pydantic,
    PROMPT_VERSION,
)

# =============================================================================
# Load golden cases
# =============================================================================

_CASES_PATH = Path(__file__).resolve().parent / "golden" / "planning_cases.yaml"


def _load_cases() -> list[dict[str, Any]]:
    with open(_CASES_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("cases", [])


GOLDEN_CASES = _load_cases()


# =============================================================================
# Prompt structure checks (no LLM needed)
# =============================================================================


class TestPromptStructure:
    """Centralized prompts must have required sections and quality rules."""

    def test_planner_prompt_is_non_empty(self):
        assert len(PLANNER_SYSTEM_PROMPT) > 150
        assert "JSON object" in PLANNER_SYSTEM_PROMPT
        assert "steps" in PLANNER_SYSTEM_PROMPT

    def test_reviewer_prompt_is_non_empty(self):
        assert len(REVIEWER_SYSTEM_PROMPT) > 150
        assert "JSON object" in REVIEWER_SYSTEM_PROMPT
        assert "blocking_concerns" in REVIEWER_SYSTEM_PROMPT

    def test_execution_planner_prompt_is_non_empty(self):
        assert len(EXECUTION_PLANNER_SYSTEM_PROMPT) > 200
        assert "JSON object" in EXECUTION_PLANNER_SYSTEM_PROMPT
        assert "worker_tasks" in EXECUTION_PLANNER_SYSTEM_PROMPT

    def test_prompt_version_is_tracked(self):
        assert PROMPT_VERSION == "3.0.0"

    def test_all_prompts_ban_markdown_fences(self):
        """Prompts must instruct models to output ONLY JSON, no markdown."""
        for name, prompt in [("planner", PLANNER_SYSTEM_PROMPT),
                             ("reviewer", REVIEWER_SYSTEM_PROMPT),
                             ("execution", EXECUTION_PLANNER_SYSTEM_PROMPT)]:
            # v3 prompts say "Output ONLY a JSON object" instead of "no markdown"
            assert "ONLY" in prompt or "ONLY a JSON" in prompt, \
                f"{name} prompt should instruct JSON-only output"

    def test_all_prompts_require_json_output(self):
        for name, prompt in [("planner", PLANNER_SYSTEM_PROMPT),
                             ("reviewer", REVIEWER_SYSTEM_PROMPT),
                             ("execution", EXECUTION_PLANNER_SYSTEM_PROMPT)]:
            assert "JSON" in prompt, f"{name} prompt should require JSON output"

    def test_golden_cases_loaded(self):
        assert len(GOLDEN_CASES) >= 10, f"Expected >= 10 cases, got {len(GOLDEN_CASES)}"


# =============================================================================
# Prompt Quality Validator Tests — rejection cases
# =============================================================================


class TestQualityRejectsMissingWorkerTasks:
    """validate_execution_planner_output must reject plans with no worker_tasks."""

    def test_empty_worker_tasks_rejected(self):
        data = {
            "summary": "Plan with no workers",
            "steps": ["Do something"],
            "risks": ["Nothing specific"],
            "non_goals": ["Don't break things"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [],
        }
        errors = validate_execution_planner_output(data)
        assert len(errors) > 0
        assert any("empty" in e.lower() for e in errors)

    def test_missing_worker_tasks_key_rejected(self):
        data = {
            "summary": "No worker_tasks key",
            "steps": ["Do something"],
            "risks": ["Risk"],
            "non_goals": ["Boundary 1", "Boundary 2"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
        }
        errors = validate_execution_planner_output(data)
        assert len(errors) > 0
        assert any("worker_tasks" in e.lower() for e in errors)

    def test_worker_task_with_empty_allowed_files_rejected(self):
        data = {
            "summary": "Task with empty boundaries",
            "steps": ["Fix bug"],
            "risks": ["Breaking change"],
            "non_goals": ["Don't touch config"],
            "required_evidence": ["test_output.txt", "diff.patch"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Fix it",
                "objective": "modify code to fix bug",
                "allowed_files": [],
                "required_checks": ["pytest"],
                "expected_evidence": ["diff.patch", "test_output.txt"],
                "risk_level": "medium",
            }],
        }
        errors = validate_execution_planner_output(data)
        assert len(errors) > 0
        assert any("allowed_files" in e.lower() and "empty" in e.lower() for e in errors)

    def test_worker_task_with_broad_allowed_files_rejected(self):
        data = {
            "summary": "Task with broad scope",
            "steps": ["Fix everything"],
            "risks": ["Breaking"],
            "non_goals": ["None"],
            "required_evidence": ["test_output.txt", "diff.patch"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Fix all",
                "objective": "modify code",
                "allowed_files": ["."],
                "required_checks": ["pytest"],
                "expected_evidence": ["diff.patch"],
                "risk_level": "medium",
            }],
        }
        errors = validate_execution_planner_output(data)
        assert len(errors) > 0
        assert any("broad" in e.lower() for e in errors)


class TestQualityRejectsGenericBlockingConcerns:
    """validate_reviewer_output must reject generic, non-actionable concerns."""

    def test_generic_blocking_concern_rejected(self):
        data = {
            "summary": "Looks fine",
            "blocking_concerns": ["missing tests"],
            "non_blocking_concerns": [],
            "risks": [],
            "human_review_gates": [],
            "required_evidence": [],
        }
        errors = validate_reviewer_output(data)
        assert len(errors) > 0
        assert any("generic" in e.lower() for e in errors)

    def test_specific_blocking_concern_accepted(self):
        data = {
            "summary": "Plan needs work",
            "blocking_concerns": [
                "Code change requested but test_output.txt not in required_evidence",
                "allowed_files is empty for worker task 'Fix it' — no file boundaries set",
            ],
            "non_blocking_concerns": ["Could add lint step"],
            "risks": ["Breaking change in control_plane.py"],
            "human_review_gates": [],
            "required_evidence": ["test_output.txt"],
        }
        errors = validate_reviewer_output(data)
        assert len(errors) == 0, f"Specific concerns should pass: {errors}"

    def test_generic_risk_rejected(self):
        data = {
            "summary": "OK",
            "blocking_concerns": [],
            "non_blocking_concerns": [],
            "risks": ["might fail"],
            "human_review_gates": [],
            "required_evidence": [],
        }
        errors = validate_reviewer_output(data)
        assert len(errors) > 0
        assert any("generic" in e.lower() for e in errors)


class TestQualityRejectsMissingRequiredChecks:
    """Code-changing tasks must have required_checks."""

    def test_code_task_without_required_checks_rejected(self):
        data = {
            "summary": "Code fix without checks",
            "steps": ["Fix bug", "Commit"],
            "risks": ["Regression"],
            "non_goals": ["Don't refactor"],
            "required_evidence": ["diff.patch", "test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Fix bug",
                "objective": "modify the code to fix the bug",
                "allowed_files": ["src/orchestrator/policy.py"],
                "required_checks": [],
                "expected_evidence": ["diff.patch"],
                "risk_level": "medium",
            }],
        }
        errors = validate_execution_planner_output(data)
        assert len(errors) > 0
        assert any("required_checks" in e.lower() for e in errors)

    def test_code_task_with_required_checks_accepted(self):
        data = {
            "summary": "Proper code fix",
            "steps": ["Fix bug", "Run tests"],
            "risks": ["Regression"],
            "non_goals": ["Don't refactor", "Don't touch config"],
            "required_evidence": ["diff.patch", "test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Fix bug in policy.py",
                "objective": "modify src/orchestrator/policy.py to fix the bug",
                "allowed_files": ["src/orchestrator/policy.py"],
                "required_checks": ["python -m pytest tests/test_policy.py -v"],
                "expected_evidence": ["diff.patch", "test_output.txt"],
                "risk_level": "medium",
            }],
        }
        errors = validate_execution_planner_output(data)
        # Check for missing diff.patch — the top-level required_evidence should have it
        has_diff_err = any("diff.patch" in e.lower() for e in errors)
        # The worker task is fine; top-level evidence might be flagged
        task_level_errors = [e for e in errors if "worker_task" in e.lower()]
        assert len(task_level_errors) == 0, f"Worker task should be valid: {task_level_errors}"


class TestQualityRejectsMissingExpectedEvidence:
    """Every plan must have expected_evidence."""

    def test_empty_expected_evidence_rejected(self):
        data = {
            "summary": "No evidence",
            "steps": ["Step 1"],
            "risks": ["Risk"],
            "non_goals": ["Boundary 1", "Boundary 2"],
            "required_evidence": [],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Task",
                "objective": "Do something",
                "allowed_files": ["src/a.py"],
                "required_checks": ["pytest"],
                "expected_evidence": [],
                "risk_level": "low",
            }],
        }
        errors = validate_execution_planner_output(data)
        assert len(errors) > 0
        assert any("expected_evidence" in e.lower() and "empty" in e.lower() for e in errors)

    def test_planner_empty_evidence_rejected(self):
        data = {
            "summary": "Plan",
            "steps": ["Step 1", "Step 2"],
            "risks": ["Risk"],
            "non_goals": ["B1", "B2"],
            "required_evidence": [],
            "human_review_gates": [],
            "assumptions": ["Assume X"],
        }
        errors = validate_planner_output(data)
        assert len(errors) > 0
        assert any("required_evidence" in e.lower() and "empty" in e.lower() for e in errors)


class TestQualityRejectsProtectedFileWithoutReview:
    """Allowed files containing protected patterns must set requires_human_review."""

    def test_protected_file_without_review_rejected(self):
        data = {
            "summary": "Touching secrets",
            "steps": ["Update secrets"],
            "risks": ["Exposure"],
            "non_goals": ["Don't break prod"],
            "required_evidence": ["diff.patch", "test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Update secrets",
                "objective": "modify config/secrets.yaml",
                "allowed_files": ["config/secrets.yaml"],
                "required_checks": [],
                "expected_evidence": ["diff.patch"],
                "risk_level": "high",
                "requires_human_review": False,
            }],
        }
        errors = validate_execution_planner_output(data)
        assert len(errors) > 0
        assert any("protected" in e.lower() for e in errors)

    def test_protected_file_with_review_accepted(self):
        data = {
            "summary": "Careful secrets update",
            "steps": ["Backup secrets", "Update secrets", "Verify"],
            "risks": ["Exposure"],
            "non_goals": ["Don't change other config"],
            "required_evidence": ["diff.patch", "test_output.txt"],
            "human_review_gates": ["Human must review secrets change"],
            "worker_tasks": [{
                "title": "Update secrets carefully",
                "objective": "modify config/secrets.yaml with review",
                "allowed_files": ["config/secrets.yaml"],
                "required_checks": ["python -m pytest"],
                "expected_evidence": ["diff.patch", "test_output.txt"],
                "risk_level": "high",
                "requires_human_review": True,
            }],
        }
        errors = validate_execution_planner_output(data)
        protected_errors = [e for e in errors if "protected" in e.lower()]
        assert len(protected_errors) == 0, f"Should accept with review: {protected_errors}"


# =============================================================================
# Planner validator tests
# =============================================================================


class TestPlannerValidator:
    def test_valid_planner_output_passes(self):
        data = {
            "summary": "Add type hints to policy.py",
            "steps": [
                "Read src/orchestrator/policy.py",
                "Add type hints to all function signatures",
                "Run python -m pytest tests/test_policy.py",
                "Collect diff.patch and test_output.txt",
            ],
            "risks": ["May break implicit None returns"],
            "non_goals": [
                "Do not change function logic",
                "Do not modify other files",
            ],
            "required_evidence": ["diff.patch", "test_output.txt"],
            "human_review_gates": [],
            "assumptions": ["Python 3.12 available", "pytest is installed"],
        }
        errors = validate_planner_output(data)
        assert errors == [], f"Valid plan should pass: {errors}"

    def test_too_few_steps_rejected(self):
        data = {
            "summary": "Fix",
            "steps": ["Fix the code"],
            "risks": ["May break"],
            "non_goals": ["Don't change config", "Don't refactor"],
            "required_evidence": ["diff.patch"],
            "human_review_gates": [],
            "assumptions": ["Code is there"],
        }
        errors = validate_planner_output(data)
        assert len(errors) > 0
        assert any("steps" in e.lower() for e in errors)

    def test_vague_step_rejected(self):
        data = {
            "summary": "Fix bug",
            "steps": ["do the work", "Verify"],
            "risks": ["Risk"],
            "non_goals": ["Don't refactor", "Don't change config"],
            "required_evidence": ["diff.patch"],
            "human_review_gates": [],
            "assumptions": ["X"],
        }
        errors = validate_planner_output(data)
        assert len(errors) > 0
        assert any("vague" in e.lower() for e in errors)

    def test_empty_risks_rejected(self):
        data = {
            "summary": "Plan with no risks",
            "steps": ["Step 1", "Step 2", "Step 3"],
            "risks": [],
            "non_goals": ["B1", "B2"],
            "required_evidence": ["diff.patch"],
            "human_review_gates": [],
            "assumptions": ["A1"],
        }
        errors = validate_planner_output(data)
        assert len(errors) > 0
        assert any("risks" in e.lower() for e in errors)

    def test_too_few_non_goals_rejected(self):
        data = {
            "summary": "Plan",
            "steps": ["Step 1", "Step 2", "Step 3"],
            "risks": ["Risk"],
            "non_goals": ["Only one boundary"],
            "required_evidence": ["diff.patch"],
            "human_review_gates": [],
            "assumptions": ["A1"],
        }
        errors = validate_planner_output(data)
        assert len(errors) > 0
        assert any("non_goals" in e.lower() for e in errors)

    def test_empty_assumptions_rejected(self):
        data = {
            "summary": "Plan",
            "steps": ["Step 1", "Step 2", "Step 3"],
            "risks": ["Risk"],
            "non_goals": ["B1", "B2"],
            "required_evidence": ["diff.patch"],
            "human_review_gates": [],
            "assumptions": [],
        }
        errors = validate_planner_output(data)
        assert len(errors) > 0
        assert any("assumptions" in e.lower() and "empty" in e.lower() for e in errors)


# =============================================================================
# Execution planner validator — valid plans
# =============================================================================


class TestExecutionPlannerValidatorValid:
    def test_code_changing_plan_with_all_required_fields_passes(self):
        data = {
            "summary": "Add docstrings to policy.py",
            "steps": [
                "Read src/orchestrator/policy.py",
                "Add Google-style docstrings",
                "Run python -m pytest tests/test_policy.py -v",
                "Collect diff.patch and test_output.txt",
            ],
            "risks": ["Docstring may be inaccurate"],
            "non_goals": [
                "Do not change logic",
                "Do not add new functions",
            ],
            "required_evidence": ["diff.patch", "test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Add docstrings",
                "objective": "add Google-style docstrings to all methods in policy.py",
                "allowed_files": ["src/orchestrator/policy.py"],
                "denied_files": ["config/secrets.yaml", ".env"],
                "required_checks": ["python -m pytest tests/test_policy.py -v"],
                "expected_evidence": ["diff.patch", "test_output.txt"],
                "risk_level": "low",
                "dependencies": [],
                "can_run_parallel": False,
                "requires_human_review": False,
            }],
        }
        errors = validate_execution_planner_output(data)
        assert errors == [], f"Valid plan should pass: {errors}"

    def test_analysis_only_plan_without_diff_passes(self):
        """Analysis-only tasks don't need diff.patch."""
        data = {
            "summary": "Count test files",
            "steps": [
                "List all test files",
                "Count and categorize",
            ],
            "risks": ["May miss hidden files"],
            "non_goals": [
                "Do not modify any files",
                "Do not run tests",
            ],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Count test files",
                "objective": "list and count Python test files in tests/",
                "allowed_files": [],
                "denied_files": [],
                "required_checks": [],
                "expected_evidence": ["test_output.txt"],
                "risk_level": "low",
                "dependencies": [],
                "can_run_parallel": False,
                "requires_human_review": False,
            }],
        }
        errors = validate_execution_planner_output(data)
        # No diff.patch requirement for analysis tasks
        diff_errors = [e for e in errors if "diff.patch" in e.lower()]
        assert len(diff_errors) == 0, \
            f"Analysis-only tasks should not require diff.patch: {diff_errors}"

    def test_invalid_risk_level_rejected(self):
        data = {
            "summary": "Invalid risk",
            "steps": ["Step"],
            "risks": ["Risk"],
            "non_goals": ["B1", "B2"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Task",
                "objective": "do",
                "allowed_files": ["src/a.py"],
                "required_checks": [],
                "expected_evidence": ["test_output.txt"],
                "risk_level": "critical",
            }],
        }
        errors = validate_execution_planner_output(data)
        assert any("risk_level" in e.lower() for e in errors)


# =============================================================================
# Prompt builder tests (integration with fake providers)
# =============================================================================


class TestPromptBuilderIntegration:
    """Smoke-test that prompt builders produce expected strings."""

    def test_build_planner_prompt_includes_query(self):
        prompt = build_planner_prompt("Fix bug in auth.py", "small", "controlled", "low", "implementation")
        assert "Fix bug in auth.py" in prompt
        assert "TASK:" in prompt
        assert "TASK SIZE:" in prompt

    def test_build_reviewer_prompt_includes_planner_context(self):
        prompt = build_reviewer_prompt(
            "Fix bug", "medium", "controlled", "low",
            planner_output={"summary": "Fix it", "steps": ["Step 1"]},
        )
        assert "Fix bug" in prompt
        assert "PLANNER'S PROPOSED PLAN" in prompt
        assert "Step 1" in prompt

    def test_build_execution_prompt_includes_reviewer_blocking(self):
        prompt = build_execution_planner_prompt(
            "Fix bug", "medium", "controlled", "low",
            reviewer_output={"blocking_concerns": ["No test step"], "non_blocking_concerns": []},
        )
        assert "BLOCKING CONCERNS" in prompt
        assert "No test step" in prompt


# =============================================================================
# Golden case shape validation
# =============================================================================


class TestGoldenCasesHaveExpectedShape:
    """Each golden case YAML entry must be well-formed."""

    def test_all_cases_have_required_meta(self):
        for case in GOLDEN_CASES:
            assert "id" in case, f"Case missing id: {case}"
            assert "title" in case, f"Case {case.get('id')} missing title"
            assert "query" in case, f"Case {case['id']} missing query"
            assert "expected" in case, f"Case {case['id']} missing expected"

    def test_all_case_ids_are_unique(self):
        ids = [c["id"] for c in GOLDEN_CASES]
        assert len(ids) == len(set(ids)), f"Duplicate case ids: {ids}"

    def test_all_expected_sections_have_valid_keys(self):
        valid_keys = {
            "risk_level", "min_steps", "required_evidence_contains",
            "expected_evidence_not_empty", "required_checks_not_empty",
            "required_checks_may_be_empty", "worker_task_count_min",
            "worker_task_count_max", "blocking_concerns_empty",
            "blocking_concerns_not_empty", "human_review_gate_empty",
            "human_review_gate_not_empty", "human_review_gate_may_exist",
            "can_run_parallel", "all_files_overlap", "diff_patch_not_required",
        }
        for case in GOLDEN_CASES:
            for key in case["expected"]:
                assert key in valid_keys, \
                    f"Case {case['id']}: unknown expected key '{key}'"

    def test_protected_file_case_requires_review(self):
        case = next(c for c in GOLDEN_CASES if c["id"] == "case-005-protected-file")
        assert case["expected"].get("human_review_gate_not_empty")
        assert case["expected"].get("blocking_concerns_not_empty")

    def test_reject_case_has_blocking_concerns(self):
        case = next(c for c in GOLDEN_CASES if c["id"] == "case-010-should-reject")
        assert case["expected"].get("blocking_concerns_not_empty")
        assert case["expected"].get("human_review_gate_not_empty")


# =============================================================================
# Eval Prompts Runner tests (pipeline integration)
# =============================================================================


class TestEvalPromptsRunner:
    """Test the eval-prompts runner end-to-end (deterministic pipeline only)."""

    def test_import(self):
        from orchestrator.eval_prompts import run_eval_cases, render_eval_summary, eval_summary_to_dict
        assert run_eval_cases is not None
        assert render_eval_summary is not None
        assert eval_summary_to_dict is not None

    def test_run_deterministic_produces_summary(self):
        from orchestrator.eval_prompts import run_eval_cases

        cases_path = str(Path(__file__).resolve().parent / "golden" / "planning_cases.yaml")
        summary = run_eval_cases(cases_path, mode="deterministic", repeat=1)

        assert summary.total == 10
        assert summary.mode == "deterministic"
        assert summary.prompt_version == "3.0.0"
        assert len(summary.results) == 10
        # Each result must have the expected shape
        for r in summary.results:
            assert r.case_id
            assert isinstance(r.passed, bool)
            assert isinstance(r.checks, list)
            assert isinstance(r.plan_dict, dict)

    def test_render_and_serialize(self):
        from orchestrator.eval_prompts import run_eval_cases, render_eval_summary, eval_summary_to_dict

        cases_path = str(Path(__file__).resolve().parent / "golden" / "planning_cases.yaml")
        summary = run_eval_cases(cases_path, mode="deterministic", repeat=1)

        text = render_eval_summary(summary)
        assert "Phase 19" in text
        assert "Prompt Quality Gate" in text

        d = eval_summary_to_dict(summary)
        assert d["total"] == 10
        assert "results" in d
        assert d["mode"] == "deterministic"
        assert isinstance(d["pass_rate"], (int, float))

    def test_verbose_mode_does_not_crash(self):
        from orchestrator.eval_prompts import run_eval_cases

        cases_path = str(Path(__file__).resolve().parent / "golden" / "planning_cases.yaml")
        summary = run_eval_cases(cases_path, mode="deterministic", repeat=1, verbose=True)
        assert summary.total == 10


# =============================================================================
# Phase 19v2 — Structured Output Hardening Tests
# =============================================================================


class TestPydanticSchemas:
    """Pydantic output schemas must validate correctly and reject bad inputs."""

    # -- Planner ----------------------------------------------------------------

    def test_planner_valid_output_passes(self):
        """Valid PlannerOutput dict passes Pydantic validation."""
        errors = validate_planner_pydantic({
            "summary": "Fix the bug",
            "steps": ["Read file", "Make change", "Run tests"],
            "risks": ["May break existing tests"],
            "non_goals": ["Do not change API", "Do not modify config"],
            "required_evidence": ["test_output.txt", "diff.patch"],
            "human_review_gates": [],
            "assumptions": ["Tests exist", "Python 3.12 available"],
        })
        assert errors == []

    def test_planner_missing_field_fails(self):
        """Missing required field triggers validation error."""
        errors = validate_planner_pydantic({
            "summary": "Incomplete plan",
            # missing steps, risks, non_goals, required_evidence, assumptions
        })
        assert len(errors) > 0
        assert any("steps" in e.lower() or "MISSING" in e for e in errors)

    def test_planner_empty_risks_fails(self):
        """Empty risks list triggers validation error."""
        errors = validate_planner_pydantic({
            "summary": "No risks plan",
            "steps": ["Step 1", "Step 2"],
            "risks": [],
            "non_goals": ["Boundary 1", "Boundary 2"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "assumptions": ["Tests exist"],
        })
        assert len(errors) > 0

    def test_planner_too_few_steps_fails(self):
        """Less than 2 steps triggers validation error."""
        errors = validate_planner_pydantic({
            "summary": "One step plan",
            "steps": ["Only one step"],
            "risks": ["Risk"],
            "non_goals": ["Boundary 1", "Boundary 2"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "assumptions": ["Tests exist"],
        })
        assert len(errors) > 0

    # -- Reviewer ---------------------------------------------------------------

    def test_reviewer_valid_output_passes(self):
        """Valid ReviewerOutput dict passes Pydantic validation."""
        errors = validate_reviewer_pydantic({
            "summary": "Review complete",
            "blocking_concerns": [],
            "non_blocking_concerns": ["Consider adding more tests"],
            "risks": ["Change may affect downstream consumers"],
            "human_review_gates": [],
            "required_evidence": [],
        })
        assert errors == []

    def test_reviewer_missing_field_fails(self):
        """Missing required field in ReviewerOutput triggers error."""
        errors = validate_reviewer_pydantic({
            "summary": "Incomplete review",
        })
        assert len(errors) > 0

    # -- Execution Planner -----------------------------------------------------

    def test_execution_planner_valid_output_passes(self):
        """Valid ExecutionPlannerOutput passes Pydantic validation."""
        errors = validate_execution_planner_pydantic({
            "summary": "Execute the plan",
            "steps": ["Implement change", "Run tests"],
            "risks": ["Test failure"],
            "non_goals": ["Don't touch config"],
            "required_evidence": ["test_output.txt", "diff.patch"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Fix bug in policy.py",
                "objective": "Modify policy.py to fix the null check bug",
                "allowed_files": ["src/orchestrator/policy.py"],
                "denied_files": [],
                "required_checks": ["python -m pytest tests/test_policy.py -v"],
                "expected_evidence": ["test_output.txt", "diff.patch"],
                "risk_level": "medium",
                "dependencies": [],
                "can_run_parallel": False,
                "requires_human_review": False,
            }],
        })
        assert errors == []

    def test_execution_planner_empty_worker_tasks_fails(self):
        """Empty worker_tasks triggers Pydantic validation error (min_length=1)."""
        errors = validate_execution_planner_pydantic({
            "summary": "No workers",
            "steps": ["Step 1"],
            "risks": ["Risk"],
            "non_goals": ["Boundary 1"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [],
        })
        assert len(errors) > 0
        assert any("worker_tasks" in e.lower() for e in errors)

    def test_execution_planner_missing_worker_tasks_fails(self):
        """Missing worker_tasks key triggers Pydantic validation error."""
        errors = validate_execution_planner_pydantic({
            "summary": "Missing worker_tasks key",
            "steps": ["Step 1"],
            "risks": ["Risk"],
            "non_goals": ["Boundary 1"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
        })
        assert len(errors) > 0

    # -- WorkerTaskItem ---------------------------------------------------------

    def test_worker_task_invalid_risk_level_fails(self):
        """Invalid risk_level triggers Literal validation error."""
        errors = validate_execution_planner_pydantic({
            "summary": "Bad risk",
            "steps": ["Step 1"],
            "risks": ["Risk"],
            "non_goals": ["Boundary 1"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Task",
                "objective": "Do it",
                "allowed_files": ["src/a.py"],
                "required_checks": ["pytest"],
                "expected_evidence": ["test_output.txt"],
                "risk_level": "critical",  # not in low/medium/high
            }],
        })
        assert len(errors) > 0

    def test_worker_task_broad_allowed_files_fails(self):
        """Broad allowed_files like '.' triggers field_validator error."""
        errors = validate_execution_planner_pydantic({
            "summary": "Broad files",
            "steps": ["Step 1"],
            "risks": ["Risk"],
            "non_goals": ["Boundary 1"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Task",
                "objective": "Do it",
                "allowed_files": ["."],
                "required_checks": ["pytest"],
                "expected_evidence": ["test_output.txt"],
                "risk_level": "low",
            }],
        })
        assert len(errors) > 0

    def test_worker_task_empty_allowed_files_fails(self):
        """Empty allowed_files triggers Pydantic min_length error."""
        errors = validate_execution_planner_pydantic({
            "summary": "No boundaries",
            "steps": ["Step 1"],
            "risks": ["Risk"],
            "non_goals": ["Boundary 1"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [{
                "title": "Task",
                "objective": "Do it",
                "allowed_files": [],
                "required_checks": ["pytest"],
                "expected_evidence": ["test_output.txt"],
                "risk_level": "low",
            }],
        })
        assert len(errors) > 0


class TestJSONParseHelpers:
    """Markdown-wrapped JSON and malformed JSON must be handled correctly."""

    def test_markdown_json_fence_stripped(self):
        """JSON inside ```json``` fences is extracted by _extract_json_substring."""
        from orchestrator.llm_providers import _extract_json_substring
        result = _extract_json_substring('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_markdown_generic_fence_stripped(self):
        """JSON inside ``` fences (no language tag) is extracted."""
        from orchestrator.llm_providers import _extract_json_substring
        result = _extract_json_substring('```\n{"x": 1}\n```')
        assert result == {"x": 1}

    def test_json_with_trailing_text_extracted(self):
        """Dict followed by explanatory text is correctly extracted."""
        from orchestrator.llm_providers import _extract_json_substring
        result = _extract_json_substring(
            '{"summary": "done", "steps": ["A", "B"]}'
            'Let me know if you need changes.'
        )
        assert result is not None
        assert result["summary"] == "done"

    def test_no_json_returns_none(self):
        """Plain text with no JSON returns None."""
        from orchestrator.llm_providers import _extract_json_substring
        assert _extract_json_substring("Just a regular response") is None

    def test_json_parse_error_described(self):
        """_describe_json_parse_error returns helpful message for invalid JSON."""
        from orchestrator.llm_providers import _describe_json_parse_error
        err = _describe_json_parse_error('{"a": b}')
        assert "JSON parse error" in err
        assert "'b'" in err or "b" in err

    def test_correction_prompt_includes_context(self):
        """Correction prompt contains original prompt, raw response, and error."""
        from orchestrator.llm_providers import _build_correction_prompt
        cp = _build_correction_prompt("Do X", '{"bad json}', "parse error: ...")
        assert "Do X" in cp
        assert '{"bad json}' in cp
        assert "parse error" in cp
        assert "ONLY a valid JSON object" in cp


class TestRetryAndBlocking:
    """Retry exhaustion must generate blocking_concern, never fake PlanContract."""

    def test_parse_error_causes_blocking_concern_in_planner(self):
        """LLMPlannerAdvisor returns blocking_concern when JSON parse fails."""
        from orchestrator.planning import LLMPlannerAdvisor

        class FailingProvider:
            name = "failing"
            def complete(self, *args, **kwargs):
                return "not json at all {"

            def complete_json(self, *args, **kwargs):
                return {"parse_error": True, "raw": "not json {", "attempts": 3,
                        "last_error": "Expected ':' after key"}

            def complete_json_strict(self, *args, **kwargs):
                return {"parse_error": True, "raw": "not json {", "attempts": 3,
                        "last_error": "Expected ':' after key"}

        # Monkey-patch get_provider to return our failing provider
        import orchestrator.planning as plan_mod
        import orchestrator.llm_providers as prov_mod
        orig_get = prov_mod.get_provider

        try:
            prov_mod.get_provider = lambda name, **kw: FailingProvider()
            advisor = LLMPlannerAdvisor(provider_name="failing", model="test")
            candidate = advisor.advise("Fix the bug")

            assert len(candidate.blocking_concerns) > 0
            assert any("PARSE_ERROR" in bc for bc in candidate.blocking_concerns), \
                f"Expected PARSE_ERROR in blocking_concerns: {candidate.blocking_concerns}"
            # Must NOT produce a valid-looking summary pretending success
            assert "parse failed" in candidate.summary.lower() or \
                   "PARSE_ERROR" in str(candidate.blocking_concerns)
        finally:
            prov_mod.get_provider = orig_get

    def test_retry_exhaustion_generates_blocking_concern_in_execution_planner(self):
        """After max retries with validation failures, execution planner produces blocking."""
        from orchestrator.planning import LLMExecutionPlannerAdvisor

        call_count = [0]

        class FlakyProvider:
            name = "flaky"

            def complete_json_strict(self, *args, **kwargs):
                call_count[0] += 1
                # Always return valid JSON but with missing worker_tasks field
                # which will fail Pydantic validation
                return {
                    "summary": "Plan without workers",
                    "steps": ["Step 1"],
                    "risks": ["Risk"],
                    "non_goals": ["Boundary"],
                    "required_evidence": ["test_output.txt"],
                    "human_review_gates": [],
                    # worker_tasks intentionally missing
                }

        import orchestrator.llm_providers as prov_mod
        orig_get = prov_mod.get_provider

        try:
            prov_mod.get_provider = lambda name, **kw: FlakyProvider()
            advisor = LLMExecutionPlannerAdvisor(provider_name="flaky", model="test")
            candidate = advisor.advise("Fix the bug")

            # Must have generated blocking_concern (validation failed after retries)
            assert len(candidate.blocking_concerns) > 0
            assert any(
                "validation" in bc.lower() or "worker_tasks" in bc.lower()
                for bc in candidate.blocking_concerns
            ), f"Expected validation/worker_tasks complaint: {candidate.blocking_concerns}"

            # Must NOT produce fake worker_tasks
            # (assumptions won't have __worker_tasks__: marker)
            assert not any("__worker_tasks__" in a for a in candidate.assumptions)
        finally:
            prov_mod.get_provider = orig_get

    def test_execution_planner_no_worker_tasks_blocked(self):
        """Execution planner that returns empty worker_tasks is blocked,
        never allowed to pretend success."""
        from orchestrator.planning import LLMExecutionPlannerAdvisor
        from orchestrator.planning_prompts import validate_execution_planner_pydantic

        # Direct Pydantic validation: empty worker_tasks is an error
        data = {
            "summary": "No workers",
            "steps": ["Step 1"],
            "risks": ["Risk"],
            "non_goals": ["Boundary"],
            "required_evidence": ["test_output.txt"],
            "human_review_gates": [],
            "worker_tasks": [],
        }
        errors = validate_execution_planner_pydantic(data)
        assert len(errors) > 0
        assert any("worker_tasks" in e.lower() for e in errors)


class TestFormatValidationError:
    """_format_validation_error produces human-readable correction hints."""

    def test_missing_field_message(self):
        from orchestrator.planning_prompts import _format_validation_error
        msg = _format_validation_error({
            "loc": ["steps"], "msg": "Field required", "type": "missing"
        })
        assert "MISSING" in msg
        assert "steps" in msg

    def test_wrong_type_message(self):
        from orchestrator.planning_prompts import _format_validation_error
        msg = _format_validation_error({
            "loc": ["worker_tasks", 0, "allowed_files"],
            "msg": "Input should be a valid list",
            "type": "list_type",
        })
        assert "WRONG TYPE" in msg

    def test_invalid_value_message(self):
        from orchestrator.planning_prompts import _format_validation_error
        msg = _format_validation_error({
            "loc": ["worker_tasks", 0, "risk_level"],
            "msg": "Input should be 'low', 'medium' or 'high'",
            "type": "literal_error",
        })
        assert "WRONG TYPE" in msg


class TestEvalStatistics:
    """The 5 quality statistics must be computed correctly."""

    def test_stats_all_pass(self):
        """When all checks pass, all 5 stats are 100%."""
        from orchestrator.eval_prompts import CaseResult, _compute_stats

        results = [
            CaseResult(
                case_id="test-1",
                case_title="Test case",
                passed=True,
                plan_dict={"planned_worker_tasks": [{"title": "Task 1"}]},
                checks=[
                    {"check": "blocking_concerns_empty", "passed": True},
                    {"check": "required_evidence_contains:test_output.txt", "passed": True},
                ],
                advisor_outputs=[
                    {"role": "planner", "summary": "ok"},
                    {"role": "execution_planner", "summary": "ok"},
                ],
            )
        ]
        stats = _compute_stats(results)
        assert stats["parse_rate"] == 100.0
        assert stats["schema_rate"] == 100.0
        assert stats["worker_tasks_rate"] == 100.0
        assert stats["blocking_accuracy"] == 100.0
        assert stats["evidence_rate"] == 100.0

    def test_stats_with_failures(self):
        """When checks fail, corresponding stats drop below 100%."""
        from orchestrator.eval_prompts import CaseResult, _compute_stats

        results = [
            CaseResult(
                case_id="fail-1",
                case_title="Failing case",
                passed=False,
                plan_dict={},  # no worker_tasks
                checks=[
                    {"check": "advisor_validator:execution_planner", "passed": False,
                     "detail": "worker_tasks empty"},
                    {"check": "blocking_concerns_empty", "passed": False,
                     "detail": "blocking_concerns has 3 items"},
                ],
                advisor_outputs=[
                    {"role": "execution_planner", "summary": "failed",
                     "assumptions": ["parse_error"]},
                ],
            )
        ]
        stats = _compute_stats(results)
        assert stats["parse_rate"] == 0.0       # parse_error in assumptions
        assert stats["schema_rate"] == 0.0      # advisor_validator failed
        assert stats["worker_tasks_rate"] == 0.0 # no planned_worker_tasks
        assert stats["blocking_accuracy"] == 0.0 # blocking_concerns_empty failed
        # evidence_rate: no evidence checks → neutral pass
        assert stats["evidence_rate"] == 100.0

    def test_eval_summary_stores_stats(self):
        """EvalSummary correctly stores computed statistics."""
        from orchestrator.eval_prompts import EvalSummary, CaseResult, _compute_stats

        summary = EvalSummary(total=5, passed=4, failed=1)
        results = [
            CaseResult(
                case_id=f"case-{i}",
                case_title=f"Case {i}",
                passed=(i != 2),
                plan_dict={"planned_worker_tasks": [{"title": "T"}]} if i != 2 else {},
                checks=[
                    {"check": "blocking_concerns_empty", "passed": i != 2},
                ],
                advisor_outputs=[],
            )
            for i in range(5)
        ]
        stats = _compute_stats(results)
        summary.parse_rate = stats["parse_rate"]
        summary.schema_rate = stats["schema_rate"]
        summary.worker_tasks_rate = stats["worker_tasks_rate"]
        summary.blocking_accuracy = stats["blocking_accuracy"]
        summary.evidence_rate = stats["evidence_rate"]

        assert summary.parse_rate == 100.0
        assert summary.worker_tasks_rate == 80.0  # 4/5 have worker_tasks
        assert summary.blocking_accuracy == 80.0  # case-2 fails blocking

    def test_render_includes_quality_stats(self):
        """render_eval_summary includes the 5 quality statistic lines."""
        from orchestrator.eval_prompts import EvalSummary, render_eval_summary

        summary = EvalSummary(
            total=10, passed=8, failed=2, mode="llm", prompt_version="3.0.0",
            parse_rate=90.0, schema_rate=85.0, worker_tasks_rate=80.0,
            blocking_accuracy=95.0, evidence_rate=88.0,
        )
        output = render_eval_summary(summary)

        assert "Parse Rate:" in output
        assert "Schema Rate:" in output
        assert "Worker Tasks Rate:" in output
        assert "Blocking Accuracy:" in output
        assert "Evidence Rate:" in output
        assert "90%" in output
        assert "85%" in output
        assert "80%" in output
        assert "95%" in output
        assert "88%" in output
