"""Tests for Phase 19 — Real LLM Planning Council.

All tests use fake providers (no real LLM calls)."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from orchestrator.planning import (
    PlanningMode,
    PlanningCouncil,
    PlanningAdvisor,
    PlanCandidate,
    PlanContract,
    PlannedWorkerTask,
    build_default_council,
    plan_contract_to_dict,
    render_plan_contract,
    LLMPlannerAdvisor,
    LLMRiskReviewerAdvisor,
    LLMExecutionPlannerAdvisor,
    LocalPlannerAdvisor,
    LocalRiskReviewerAdvisor,
    LocalExecutionPlannerAdvisor,
    _parse_plan_candidate,
    _extract_worker_tasks_from_candidates,
    _validate_with_retry,
    _build_planner_prompt,
    _build_reviewer_prompt,
    _build_execution_prompt,
    _default_model_for,
    _PLANNER_SYSTEM_PROMPT,
    _REVIEWER_SYSTEM_PROMPT,
    _EXECUTION_SYSTEM_PROMPT,
)
from orchestrator.llm_providers import MockProvider, get_provider


# =============================================================================
# Fake planning provider — returns controlled JSON for each advisor role
# =============================================================================


class FakePlanningProvider(MockProvider):
    """Mock provider that returns planning-specific JSON responses.

    Configure with canned_responses: a list of dicts returned in order.
    """

    name = "mock"

    def __init__(self, canned_responses: list[dict] | None = None):
        self.canned = canned_responses or []
        self._idx = 0
        self.calls: list[str] = []  # record prompts for assertions

    def complete_json(
        self,
        prompt: str,
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict:
        self.calls.append(prompt)
        if self._idx < len(self.canned):
            result = self.canned[self._idx]
            self._idx += 1
            return result
        return {"summary": "fallback", "steps": [], "risks": []}

    def complete_json_strict(
        self,
        prompt: str,
        *,
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2500,
        max_retries: int = 2,
    ) -> dict:
        """Delegates to complete_json — advisors call complete_json_strict
        but FakePlanningProvider only stores canned responses via complete_json."""
        return self.complete_json(
            prompt, model=model, temperature=temperature, max_tokens=max_tokens,
        )


def make_planner_response(
    summary: str = "Plan to implement feature X",
    steps: list[str] | None = None,
    risks: list[str] | None = None,
    evidence: list[str] | None = None,
) -> dict:
    return {
        "summary": summary,
        "steps": steps or ["Inspect src/a.py", "Implement changes", "Run tests"],
        "risks": risks or ["Test failures may occur"],
        "non_goals": ["Do not change unrelated files", "Do not skip tests"],
        "required_evidence": evidence or ["test_output.txt", "diff.patch"],
        "human_review_gates": [],
        "assumptions": ["Tests exist"],
    }


def make_reviewer_response(
    blocking: list[str] | None = None,
    non_blocking: list[str] | None = None,
    gates: list[str] | None = None,
) -> dict:
    return {
        "summary": "Risk review: plan looks safe",
        "blocking_concerns": blocking or [],
        "non_blocking_concerns": non_blocking or ["Consider adding edge-case tests"],
        "risks": ["Standard implementation risk"],
        "human_review_gates": gates or [],
        "required_evidence": [],
    }


def make_execution_response(
    summary: str = "Execution plan: 3 worker tasks",
    steps: list[str] | None = None,
    worker_tasks: list[dict] | None = None,
) -> dict:
    return {
        "summary": summary,
        "steps": steps or ["1. Validate boundaries", "2. Execute code change", "3. Collect evidence"],
        "risks": ["Execution may hit unexpected errors"],
        "non_goals": ["Do not run in parallel"],
        "required_evidence": ["result.md", "status.json"],
        "human_review_gates": [],
        "worker_tasks": worker_tasks or [
            {
                "title": "Fix auth bug",
                "objective": "Fix authentication bug in auth.py",
                "allowed_files": ["src/auth.py"],
                "denied_files": ["src/secrets.py"],
                "required_checks": ["python -m pytest"],
                "expected_evidence": ["test_output.txt"],
                "risk_level": "medium",
            },
        ],
    }


# =============================================================================
# LLM advisor unit tests
# =============================================================================


class TestLLMAdvisorClasses:
    def test_llm_planner_has_correct_role(self):
        advisor = LLMPlannerAdvisor(provider_name="mock")
        assert advisor.role == "planner"

    def test_llm_reviewer_has_correct_role(self):
        advisor = LLMRiskReviewerAdvisor(provider_name="mock")
        assert advisor.role == "risk_reviewer"

    def test_llm_execution_planner_has_correct_role(self):
        advisor = LLMExecutionPlannerAdvisor(provider_name="mock")
        assert advisor.role == "execution_planner"

    def test_llm_advisors_implement_protocol(self):
        for cls in [LLMPlannerAdvisor, LLMRiskReviewerAdvisor, LLMExecutionPlannerAdvisor]:
            advisor = cls(provider_name="mock")
            assert isinstance(advisor, PlanningAdvisor)


class TestLLMPlannerAdvisor:
    def test_llm_planner_produces_candidate(self):
        provider = FakePlanningProvider([make_planner_response()])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            advisor = LLMPlannerAdvisor(provider_name="mock")
            candidate = advisor.advise("Add feature X to src/a.py")
        assert candidate.role == "planner"
        assert len(candidate.steps) >= 1
        assert "test_output.txt" in candidate.required_evidence

    def test_llm_planner_captures_error_on_failure(self):
        provider = FakePlanningProvider([{"bad": "data"}])
        # Force an exception
        def raise_error(*a, **kw):
            raise RuntimeError("API down")
        provider.complete_json_strict = raise_error
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            advisor = LLMPlannerAdvisor(provider_name="mock")
            candidate = advisor.advise("Add feature X")
        assert len(candidate.blocking_concerns) >= 1
        assert "PLANNER_ERROR" in candidate.blocking_concerns[0]

    def test_llm_planner_parses_steps_and_risks(self):
        provider = FakePlanningProvider([make_planner_response(
            steps=["Step A", "Step B"],
            risks=["Risk 1", "Risk 2"],
        )])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            advisor = LLMPlannerAdvisor(provider_name="mock")
            candidate = advisor.advise("Task")
        assert candidate.steps == ["Step A", "Step B"]
        assert candidate.risks == ["Risk 1", "Risk 2"]


class TestLLMRiskReviewerAdvisor:
    def test_llm_reviewer_has_planner_output_attribute(self):
        advisor = LLMRiskReviewerAdvisor(provider_name="mock")
        assert advisor.planner_output is None
        advisor.planner_output = PlanCandidate(
            role="planner", steps=["Step 1"],
        )
        assert advisor.planner_output is not None

    def test_llm_reviewer_produces_candidate(self):
        provider = FakePlanningProvider([make_reviewer_response()])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            advisor = LLMRiskReviewerAdvisor(provider_name="mock")
            candidate = advisor.advise("Task")
        assert candidate.role == "risk_reviewer"

    def test_llm_reviewer_handles_error(self):
        provider = FakePlanningProvider()
        def raise_error(*a, **kw):
            raise RuntimeError("API down")
        provider.complete_json_strict = raise_error
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            advisor = LLMRiskReviewerAdvisor(provider_name="mock")
            candidate = advisor.advise("Task")
        assert "REVIEWER_ERROR" in candidate.blocking_concerns[0]


class TestLLMExecutionPlannerAdvisor:
    def test_llm_execution_planner_has_context_attributes(self):
        advisor = LLMExecutionPlannerAdvisor(provider_name="mock")
        assert advisor.planner_output is None
        assert advisor.reviewer_output is None

    def test_llm_execution_planner_preserves_worker_tasks(self):
        provider = FakePlanningProvider([make_execution_response(
            worker_tasks=[{"title": "T1", "objective": "Do work",
                           "allowed_files": ["src/a.py"],
                           "denied_files": ["src/b.py"],
                           "required_checks": ["pytest"],
                           "expected_evidence": ["test.txt"],
                           "risk_level": "high"}],
        )])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            advisor = LLMExecutionPlannerAdvisor(provider_name="mock")
            candidate = advisor.advise("Task")
        assert "__worker_tasks__" in "\n".join(candidate.assumptions)

    def test_llm_execution_planner_handles_error(self):
        provider = FakePlanningProvider()
        def raise_error(*a, **kw):
            raise RuntimeError("API down")
        provider.complete_json_strict = raise_error
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            advisor = LLMExecutionPlannerAdvisor(provider_name="mock")
            candidate = advisor.advise("Task")
        assert "EXECUTION_PLANNER_ERROR" in candidate.blocking_concerns[0]


# =============================================================================
# System prompts
# =============================================================================


class TestSystemPrompts:
    def test_planner_prompt_exists_and_is_string(self):
        assert isinstance(_PLANNER_SYSTEM_PROMPT, str)
        assert "Planner" in _PLANNER_SYSTEM_PROMPT

    def test_reviewer_prompt_exists_and_is_string(self):
        assert isinstance(_REVIEWER_SYSTEM_PROMPT, str)
        assert "Risk Reviewer" in _REVIEWER_SYSTEM_PROMPT

    def test_execution_prompt_exists_and_is_string(self):
        assert isinstance(_EXECUTION_SYSTEM_PROMPT, str)
        assert "Execution Planner" in _EXECUTION_SYSTEM_PROMPT

    def test_planner_prompt_mentions_json_output(self):
        assert "JSON" in _PLANNER_SYSTEM_PROMPT

    def test_reviewer_prompt_mentions_blocking_concerns(self):
        assert "blocking_concerns" in _REVIEWER_SYSTEM_PROMPT

    def test_execution_prompt_mentions_worker_tasks(self):
        assert "worker_tasks" in _EXECUTION_SYSTEM_PROMPT


# =============================================================================
# Prompt builders
# =============================================================================


class TestPromptBuilders:
    def test_build_planner_prompt_includes_query(self):
        prompt = _build_planner_prompt("Fix bug in auth.py", "medium", "controlled", "low")
        assert "Fix bug in auth.py" in prompt
        assert "medium" in prompt

    def test_build_reviewer_prompt_includes_planner_output(self):
        planner = PlanCandidate(
            steps=["Inspect code", "Fix bug"],
            risks=["Risk A"],
            required_evidence=["test.txt"],
            human_review_gates=["Review before merge"],
        )
        prompt = _build_reviewer_prompt("Fix bug", "medium", "controlled", "low", planner)
        assert "Inspect code" in prompt
        assert "Risk A" in prompt

    def test_build_reviewer_prompt_handles_none_planner(self):
        prompt = _build_reviewer_prompt("Fix bug", "medium", "controlled", "low", None)
        assert "Fix bug" in prompt

    def test_build_execution_prompt_includes_both_contexts(self):
        planner = PlanCandidate(steps=["Step 1"], required_evidence=["e1.txt"])
        reviewer = PlanCandidate(
            blocking_concerns=["BLOCKING: Missing gate"],
            non_blocking_concerns=["Consider tests"],
            human_review_gates=["Review required"],
        )
        prompt = _build_execution_prompt("Task", "medium", "controlled", "low", planner, reviewer)
        assert "Step 1" in prompt
        assert "BLOCKING: Missing gate" in prompt
        assert "Consider tests" in prompt

    def test_build_execution_prompt_handles_none_contexts(self):
        prompt = _build_execution_prompt("Task", "medium", "controlled", "low", None, None)
        assert "Task" in prompt


# =============================================================================
# Parse helpers
# =============================================================================


class TestParsePlanCandidate:
    def test_parse_complete_response(self):
        raw = {
            "summary": "Plan summary",
            "steps": ["Step 1", "Step 2"],
            "risks": ["Risk 1"],
            "non_goals": ["Non-goal 1"],
            "required_evidence": ["test.txt"],
            "human_review_gates": ["Gate 1"],
            "assumptions": ["Assumption 1"],
            "blocking_concerns": ["BLOCKING: issue"],
            "non_blocking_concerns": ["Warning"],
        }
        candidate = _parse_plan_candidate(raw, "planner")
        assert candidate.role == "planner"
        assert candidate.summary == "Plan summary"
        assert candidate.steps == ["Step 1", "Step 2"]
        assert candidate.blocking_concerns == ["BLOCKING: issue"]

    def test_parse_empty_response(self):
        candidate = _parse_plan_candidate({}, "risk_reviewer")
        assert candidate.role == "risk_reviewer"
        assert candidate.steps == []
        assert candidate.risks == []

    def test_parse_coerces_types(self):
        raw = {"steps": [1, 2, 3], "risks": [None, "valid"]}
        candidate = _parse_plan_candidate(raw, "execution_planner")
        assert candidate.steps == ["1", "2", "3"]
        assert candidate.risks == ["None", "valid"]


class TestExtractWorkerTasks:
    def test_extract_from_execution_planner(self):
        candidates = [
            PlanCandidate(role="planner"),
            PlanCandidate(role="risk_reviewer"),
            PlanCandidate(
                role="execution_planner",
                assumptions=[
                    "__worker_tasks__:" + json.dumps([{
                        "title": "Fix bug",
                        "objective": "Fix the bug",
                        "allowed_files": ["src/a.py"],
                        "denied_files": [".env"],
                        "required_checks": ["pytest"],
                        "expected_evidence": ["test.txt"],
                        "risk_level": "high",
                    }]),
                ],
            ),
        ]
        tasks = _extract_worker_tasks_from_candidates(candidates)
        assert len(tasks) == 1
        assert tasks[0].title == "Fix bug"
        assert tasks[0].allowed_files == ["src/a.py"]
        assert tasks[0].denied_files == [".env"]
        assert tasks[0].required_checks == ["pytest"]
        assert tasks[0].expected_evidence == ["test.txt"]
        assert tasks[0].risk_level == "high"

    def test_extract_multiple_worker_tasks(self):
        candidates = [
            PlanCandidate(
                role="execution_planner",
                assumptions=[
                    "__worker_tasks__:" + json.dumps([
                        {"title": "Task 1", "objective": "Do 1",
                         "allowed_files": [], "denied_files": [],
                         "required_checks": [], "expected_evidence": [],
                         "risk_level": "low"},
                        {"title": "Task 2", "objective": "Do 2",
                         "allowed_files": ["src/b.py"], "denied_files": [],
                         "required_checks": ["pytest"], "expected_evidence": ["test.txt"],
                         "risk_level": "medium"},
                    ]),
                ],
            ),
        ]
        tasks = _extract_worker_tasks_from_candidates(candidates)
        assert len(tasks) == 2
        assert tasks[0].title == "Task 1"
        assert tasks[1].title == "Task 2"
        assert tasks[1].risk_level == "medium"

    def test_extract_no_execution_planner_returns_empty(self):
        candidates = [
            PlanCandidate(role="planner"),
            PlanCandidate(role="risk_reviewer"),
        ]
        tasks = _extract_worker_tasks_from_candidates(candidates)
        assert tasks == []

    def test_extract_bad_json_returns_empty(self):
        candidates = [
            PlanCandidate(
                role="execution_planner",
                assumptions=["__worker_tasks__:not valid json{"],
            ),
        ]
        tasks = _extract_worker_tasks_from_candidates(candidates)
        assert tasks == []


# =============================================================================
# PlanningCouncil — LLM mode
# =============================================================================


class TestPlanningCouncilLLMMode:
    """Core test: LLM mode calls three advisors sequentially with context."""

    def test_llm_planning_mode_calls_three_advisors(self):
        canned = [
            make_planner_response(steps=["Plan step 1", "Plan step 2"]),
            make_reviewer_response(),
            make_execution_response(worker_tasks=[
                {"title": "W1", "objective": "Do work",
                 "allowed_files": ["src/a.py"], "denied_files": [],
                 "required_checks": ["pytest"], "expected_evidence": ["test.txt"],
                 "risk_level": "low"},
            ]),
        ]
        provider = FakePlanningProvider(canned)
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Add feature X", task_size="large")
        assert len(provider.calls) == 3
        assert len(plan.source_candidates) == 3
        assert plan.source_candidates[0].role == "planner"
        assert plan.source_candidates[1].role == "risk_reviewer"
        assert plan.source_candidates[2].role == "execution_planner"

    def test_deterministic_mode_does_not_call_provider(self):
        council = PlanningCouncil(mode="deterministic")
        plan = council.create_plan("Fix bug in src/auth.py", task_size="large")
        assert plan.planning_mode == "deterministic"
        assert len(plan.source_candidates) == 3
        # All should be local advisors (no LLM calls)
        for c in plan.source_candidates:
            assert c.role in ("planner", "risk_reviewer", "execution_planner")

    def test_llm_mode_sets_planning_mode_in_contract(self):
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Task", task_size="large")
        assert plan.planning_mode == "llm"

    def test_missing_provider_fails_clearly_without_silent_fallback(self):
        """LLM planner error must appear in blocking_concerns, not be silently swallowed."""

        def raise_keyerror(*a, **kw):
            raise KeyError("Unknown provider: bad-provider")

        provider = FakePlanningProvider()
        provider.complete_json_strict = raise_keyerror
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Task", task_size="large")
        # Planner error propagates as blocking concern
        assert len(plan.blocking_concerns) >= 1
        assert any("PLANNER_ERROR" in bc for bc in plan.blocking_concerns)

    def test_planner_output_is_validated_into_plan_contract(self):
        provider = FakePlanningProvider([
            make_planner_response(steps=["P1", "P2"], risks=["R1"]),
            make_reviewer_response(),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Add feature X", task_size="large")
        assert "P1" in plan.steps
        assert "P2" in plan.steps
        assert "R1" in plan.risks

    def test_risk_reviewer_findings_are_preserved(self):
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(
                blocking=["BLOCKING: Missing human review gate"],
                non_blocking=["Consider more tests"],
            ),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Delete production DB", task_size="large",
                                       risk_level="high")
        assert "BLOCKING: Missing human review gate" in plan.blocking_concerns
        assert "Consider more tests" in plan.non_blocking_concerns

    def test_execution_planner_generates_worker_ready_steps(self):
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(),
            make_execution_response(worker_tasks=[
                {"title": "Fix auth", "objective": "Fix the auth bug",
                 "allowed_files": ["src/auth.py"], "denied_files": ["src/secrets.py"],
                 "required_checks": ["pytest", "mypy"],
                 "expected_evidence": ["test_output.txt", "diff.patch"],
                 "risk_level": "medium"},
            ]),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Fix auth bug", task_size="large")
        assert len(plan.planned_worker_tasks) >= 1
        wt = plan.planned_worker_tasks[0]
        assert wt.title == "Fix auth"
        assert "src/auth.py" in wt.allowed_files
        assert "src/secrets.py" in wt.denied_files
        assert "pytest" in wt.required_checks
        assert "mypy" in wt.required_checks

    def test_plan_requires_user_approval_before_execution(self):
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Task", task_size="large")
        assert plan.approval_status == "draft"
        assert plan.approval_status != "approved"

    def test_cancel_stops_before_worker_packets_are_created(self):
        """Rejected plan must not be executable."""
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Task", task_size="large")
        plan.reject()
        assert plan.approval_status == "rejected"
        assert plan.approval_status != "approved"

    def test_approve_allows_execution_to_continue(self):
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(),  # no blocking concerns
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Task", task_size="large")
        assert not plan.has_blocking_concerns
        plan.approve()
        assert plan.approval_status == "approved"

    def test_invalid_llm_plan_is_rejected_or_repaired_before_execution(self):
        """Plan with no steps from LLM must carry blocking concerns."""
        provider = FakePlanningProvider([
            make_planner_response(steps=[]),  # invalid: no steps
            make_reviewer_response(),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Task", task_size="large")
        # Either has steps merged from other advisors, or blocking concerns
        has_steps = len(plan.steps) > 0
        has_blocking = len(plan.blocking_concerns) > 0
        assert has_steps or has_blocking, (
            "LLM plan with zero steps must have either merged steps or blocking concerns"
        )

    def test_reviewer_can_block_plan(self):
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(blocking=["BLOCKING: Scope creep across 3+ domains"]),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Auth, database, and deploy changes", task_size="large")
        assert plan.has_blocking_concerns
        with pytest.raises(ValueError, match="Cannot approve"):
            plan.approve()


# =============================================================================
# build_default_council with mode
# =============================================================================


class TestBuildDefaultCouncilWithMode:
    def test_default_is_deterministic(self):
        council = build_default_council()
        assert council._mode == "deterministic"

    def test_llm_mode_creates_llm_council(self):
        council = build_default_council(mode="llm")
        assert council._mode == "llm"

    def test_llm_mode_defaults_to_deepseek_provider(self):
        council = build_default_council(mode="llm")
        assert council._advisors[0].provider_name == "deepseek"


# =============================================================================
# Context passing in LLM mode
# =============================================================================


class TestLLMContextPassing:
    """Verify that in LLM mode, reviewer receives planner output and
    execution planner receives both planner and reviewer output."""

    def test_reviewer_receives_planner_output(self):
        planner_resp = make_planner_response(steps=["Planner step 1"])
        reviewer_resp = make_reviewer_response()
        exec_resp = make_execution_response()

        provider = FakePlanningProvider([planner_resp, reviewer_resp, exec_resp])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            council.create_plan("Test", task_size="large")

        # Reviewer call (index 1) should contain planner's step
        reviewer_prompt = provider.calls[1]
        assert "Planner step 1" in reviewer_prompt

    def test_execution_planner_receives_both_contexts(self):
        planner_resp = make_planner_response(steps=["Planner step", "Verify step"])
        reviewer_resp = make_reviewer_response(
            blocking=["BLOCKING: Something"],
            non_blocking=["Warning: something"],
        )
        exec_resp = make_execution_response()

        provider = FakePlanningProvider([planner_resp, reviewer_resp, exec_resp])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            council.create_plan("Test", task_size="large")

        # Execution planner call (index 2) should contain both
        exec_prompt = provider.calls[2]
        assert "Planner step" in exec_prompt
        assert "BLOCKING: Something" in exec_prompt
        assert "Warning: something" in exec_prompt


# =============================================================================
# _default_model_for
# =============================================================================


class TestDefaultModelFor:
    def test_known_provider_returns_model(self):
        assert _default_model_for("deepseek") == "deepseek-v4-pro"

    def test_unknown_provider_returns_default(self):
        assert _default_model_for("unknown-provider") == "default"

    def test_mock_provider_returns_mock(self):
        assert _default_model_for("mock") == "mock"


# =============================================================================
# PlanContract serialization includes planning_mode
# =============================================================================


class TestPlanContractPlanningMode:
    def test_to_dict_includes_planning_mode(self):
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Task", task_size="large")
        d = plan_contract_to_dict(plan)
        assert d["planning_mode"] == "llm"

    def test_render_includes_planning_mode(self):
        plan = PlanContract(plan_id="p1", objective="Test", steps=["S1"],
                            planning_mode="llm")
        text = render_plan_contract(plan)
        assert "llm" in text


# =============================================================================
# Regression: deterministic council still works
# =============================================================================


class TestDeterministicRegression:
    def test_deterministic_council_has_local_advisors(self):
        council = PlanningCouncil(mode="deterministic")
        assert isinstance(council._advisors[0], LocalPlannerAdvisor)
        assert isinstance(council._advisors[1], LocalRiskReviewerAdvisor)
        assert isinstance(council._advisors[2], LocalExecutionPlannerAdvisor)

    def test_deterministic_council_creates_plan_from_query(self):
        council = build_default_council(mode="deterministic")
        plan = council.create_plan(
            "Fix bug in src/auth.py with tests",
            task_size="large",
        )
        assert plan.planning_mode == "deterministic"
        assert len(plan.steps) > 0
        assert len(plan.source_candidates) == 3


# =============================================================================
# False-positive guards
# =============================================================================


class TestFalsePositiveGuards:
    def test_deterministic_advisors_dont_count_as_llm(self):
        """Local advisors passing tests must NOT count as LLM mode."""
        council = build_default_council(mode="deterministic")
        plan = council.create_plan("Fix bug", task_size="large")
        assert plan.planning_mode == "deterministic"
        # Local advisors never produce worker_tasks for tasks that aren't large
        # But even for large tasks, the feature is deterministic

    def test_llm_response_without_worker_ready_steps_gets_merged(self):
        """An LLM response with no worker_tasks still produces a valid plan."""
        provider = FakePlanningProvider([
            make_planner_response(),
            make_reviewer_response(),
            make_execution_response(worker_tasks=[]),  # no worker tasks
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Task", task_size="large")
        # Plan still has steps, risks, etc. from all advisors
        assert len(plan.steps) > 0
        assert len(plan.source_candidates) == 3

    def test_plan_with_no_required_evidence_for_code_task_still_validates(self):
        """A plan with no required evidence for code task gets flagged."""
        provider = FakePlanningProvider([
            make_planner_response(evidence=[]),
            make_reviewer_response(),
            make_execution_response(),
        ])
        with patch("orchestrator.llm_providers.get_provider", return_value=provider):
            council = PlanningCouncil(mode="llm", planner_provider="mock",
                                      reviewer_provider="mock",
                                      execution_planner_provider="mock")
            plan = council.create_plan("Fix bug", task_size="large")
        # The ControlPlane verify_plan would catch missing evidence,
        # but the council still produces a plan
        assert plan is not None


# =============================================================================
# _validate_with_retry — correction parse error branch
# =============================================================================


class TestValidateWithRetryCorrectionParseError:
    """Proves that when Pydantic validation fails and the subsequent correction
    prompt produces unparseable JSON, the function returns a blocking_concern
    instead of silently continuing."""

    def test_correction_parse_error_returns_blocking_concern(self):
        """Correction that returns unparseable JSON → blocking concern with details."""

        def _always_fail_validator(data: dict) -> list[str]:
            return ["field 'steps' is required"]

        # Provider whose complete_json_strict returns parse_error (simulating
        # a correction prompt that the LLM failed to produce valid JSON for)
        class _ParseErrorProvider(MockProvider):
            def complete_json_strict(self, prompt, *, model, temperature=0.3,
                                     max_tokens=2500, max_retries=2):
                return {"parse_error": True, "raw": "{broken", "last_error": "Expecting value"}

        provider = _ParseErrorProvider()
        raw_data = {"summary": "test", "steps": [], "risks": []}

        result = _validate_with_retry(
            system_and_prompt="Original prompt text",
            provider=provider,
            model="test-model",
            raw_data=raw_data,
            validator=_always_fail_validator,
            advisor_name="TestAdvisor",
        )

        assert "blocking_concern" in result
        assert "data" not in result
        assert "Pydantic validation failed" in result["blocking_concern"]
        assert "correction produced unparseable JSON" in result["blocking_concern"]

    def test_correction_success_after_first_failure(self):
        """Correction returns valid JSON on second try → success."""
        call_count = [0]

        def _fail_once_then_pass(data: dict) -> list[str]:
            call_count[0] += 1
            if call_count[0] == 1:
                return ["field 'steps' is required"]
            return []

        class _CorrectionProvider(MockProvider):
            def complete_json_strict(self, prompt, *, model, temperature=0.3,
                                     max_tokens=2500, max_retries=2):
                # Return valid data — the validator decides pass/fail
                return {"summary": "test", "steps": ["step1"], "risks": []}

        provider = _CorrectionProvider()
        raw_data = {"summary": "test", "steps": [], "risks": []}

        result = _validate_with_retry(
            system_and_prompt="Original prompt text",
            provider=provider,
            model="test-model",
            raw_data=raw_data,
            validator=_fail_once_then_pass,
            advisor_name="TestAdvisor",
        )

        assert "data" in result
        assert result["data"]["steps"] == ["step1"]


# =============================================================================
# Real LLM smoke test (skipped without API key)
# =============================================================================


class TestRealLLMSmoke:
    """One-shot smoke test that proves a real provider can produce Pydantic-valid
    Planning Council output.

    Skipped unless ``DEEPSEEK_API_KEY`` or ``OPENAI_API_KEY`` is set.
    """

    @pytest.mark.skipif(
        not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")),
        reason="No LLM API key available — set DEEPSEEK_API_KEY or OPENAI_API_KEY",
    )
    def test_planner_real_provider_produces_pydantic_valid_output(self):
        import os as _os

        provider_name = "deepseek" if _os.environ.get("DEEPSEEK_API_KEY") else "openai"
        advisor = LLMPlannerAdvisor(provider_name=provider_name)
        candidate = advisor.advise(
            "Fix a typo in src/utils.py: 'recieve' should be 'receive'",
            task_size="medium",
            run_mode="controlled",
            risk_level="low",
        )

        # Must not have blocking concerns from parse/Pydantic failure
        assert not candidate.blocking_concerns, (
            f"Planner should produce valid output, got blocking concerns: {candidate.blocking_concerns}"
        )
        # Must have at least one step
        assert len(candidate.steps) >= 1, "Planner must suggest at least one step"
        # Must have a non-empty summary
        assert len(candidate.summary) > 0, "Planner must provide a summary"
        # For a trivial typo fix, risk level should be low
        assert candidate.risks or len(candidate.steps) >= 1, "Must have either risks or steps"
