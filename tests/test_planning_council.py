"""Tests for Phase 13 Planning Council — deterministic, no real LLM calls."""

from __future__ import annotations

import pytest

from orchestrator.planning import (
    LocalExecutionPlannerAdvisor,
    LocalPlannerAdvisor,
    LocalRiskReviewerAdvisor,
    PlanCandidate,
    PlanContract,
    PlannedWorkerTask,
    PlanningAdvisor,
    PlanningCouncil,
    build_default_council,
    plan_contract_to_dict,
    planned_task_to_packet_kwargs,
    render_plan_contract,
)
from orchestrator.control_plane import ControlPlane
from orchestrator.policy import Policy


# =============================================================================
# PlanCandidate
# =============================================================================

class TestPlanCandidate:
    def test_default_candidate(self):
        c = PlanCandidate()
        assert c.role == ""
        assert c.steps == []
        assert c.risks == []

    def test_full_candidate(self):
        c = PlanCandidate(
            role="planner",
            summary="Test plan",
            steps=["Step 1", "Step 2"],
            risks=["Risk A"],
            non_goals=["Don't do X"],
            required_evidence=["test_output.txt"],
            human_review_gates=["Review before deploy"],
            assumptions=["Tests exist"],
        )
        assert c.role == "planner"
        assert len(c.steps) == 2
        assert len(c.risks) == 1
        assert c.non_goals == ["Don't do X"]
        assert c.required_evidence == ["test_output.txt"]
        assert c.human_review_gates == ["Review before deploy"]


# =============================================================================
# PlannedWorkerTask
# =============================================================================

class TestPlannedWorkerTask:
    def test_default_task(self):
        t = PlannedWorkerTask()
        assert t.title == ""
        assert t.risk_level == "low"

    def test_has_boundaries_false_by_default(self):
        t = PlannedWorkerTask()
        assert t.has_boundaries is False

    def test_has_boundaries_true_with_allowed_files(self):
        t = PlannedWorkerTask(allowed_files=["src/a.py"])
        assert t.has_boundaries is True

    def test_has_boundaries_true_with_denied_files(self):
        t = PlannedWorkerTask(denied_files=["src/secrets.py"])
        assert t.has_boundaries is True

    def test_has_boundaries_true_with_required_checks(self):
        t = PlannedWorkerTask(required_checks=["pytest"])
        assert t.has_boundaries is True

    def test_task_preserves_boundaries(self):
        t = PlannedWorkerTask(
            title="Fix login bug",
            objective="Fix the login bug in auth.py",
            allowed_files=["src/auth.py", "tests/test_auth.py"],
            denied_files=["src/secrets.py"],
            required_checks=["python -m pytest"],
            expected_evidence=["test_output.txt", "diff.patch"],
            risk_level="high",
        )
        assert "src/auth.py" in t.allowed_files
        assert "src/secrets.py" in t.denied_files
        assert "python -m pytest" in t.required_checks
        assert "test_output.txt" in t.expected_evidence
        assert t.risk_level == "high"


# =============================================================================
# PlanContract
# =============================================================================

class TestPlanContract:
    def test_default_contract(self):
        pc = PlanContract()
        assert pc.approval_status == "draft"
        assert pc.steps == []

    def test_approve(self):
        pc = PlanContract()
        pc.approve()
        assert pc.approval_status == "approved"

    def test_reject(self):
        pc = PlanContract()
        pc.reject()
        assert pc.approval_status == "rejected"

    def test_edit(self):
        pc = PlanContract(steps=["old step"])
        pc.edit(steps=["new step 1", "new step 2"], non_goals=["Don't do Y"])
        assert pc.steps == ["new step 1", "new step 2"]
        assert pc.non_goals == ["Don't do Y"]
        assert pc.approval_status == "edited"

    def test_edit_preserves_unchanged_fields(self):
        pc = PlanContract(objective="Fix bug", risks=["Risk A"])
        pc.edit(steps=["new step"])
        assert pc.objective == "Fix bug"
        assert pc.risks == ["Risk A"]

    # --- blocking concerns --------------------------------------------------

    def test_has_blocking_concerns_false_by_default(self):
        pc = PlanContract()
        assert pc.has_blocking_concerns is False

    def test_has_blocking_concerns_true(self):
        pc = PlanContract(blocking_concerns=["BLOCKING: Missing evidence"])
        assert pc.has_blocking_concerns is True

    def test_approve_raises_when_blocking_concerns_exist(self):
        pc = PlanContract(
            plan_id="p1",
            steps=["Step 1"],
            blocking_concerns=["BLOCKING: Missing human review gate"],
        )
        with pytest.raises(ValueError, match="Cannot approve plan"):
            pc.approve()
        assert pc.approval_status == "draft"  # unchanged

    def test_approve_succeeds_when_no_blocking_concerns(self):
        pc = PlanContract(plan_id="p1", steps=["Step 1"])
        pc.approve()
        assert pc.approval_status == "approved"

    def test_blocking_concerns_block_execution_flag(self):
        """A plan with blocking concerns is NOT executable."""
        pc = PlanContract(
            plan_id="p1",
            steps=["Step 1"],
            blocking_concerns=["BLOCKING: Scope too broad"],
        )
        assert pc.approval_status == "draft"
        assert pc.has_blocking_concerns is True
        # approve() should raise
        with pytest.raises(ValueError):
            pc.approve()
        # After rejection, it's still not executable
        pc.reject()
        assert pc.approval_status == "rejected"



# =============================================================================
# Plan contract serialization
# =============================================================================

class TestPlanContractSerialization:
    def test_to_dict_basic(self):
        pc = PlanContract(
            plan_id="plan-abc123",
            objective="Test task",
            steps=["Step 1", "Step 2"],
            approval_status="draft",
        )
        d = plan_contract_to_dict(pc)
        assert d["plan_id"] == "plan-abc123"
        assert d["objective"] == "Test task"
        assert d["steps"] == ["Step 1", "Step 2"]
        assert d["approval_status"] == "draft"

    def test_to_dict_includes_worker_tasks(self):
        wt = PlannedWorkerTask(
            title="Fix bug",
            objective="Fix the bug",
            allowed_files=["src/a.py"],
            risk_level="medium",
        )
        pc = PlanContract(
            plan_id="p1",
            planned_worker_tasks=[wt],
        )
        d = plan_contract_to_dict(pc)
        assert len(d["planned_worker_tasks"]) == 1
        assert d["planned_worker_tasks"][0]["title"] == "Fix bug"
        assert d["planned_worker_tasks"][0]["risk_level"] == "medium"

    def test_to_dict_includes_disagreements(self):
        pc = PlanContract(
            plan_id="p1",
            disagreements=["Risk reviewer flagged X, planner missed it"],
        )
        d = plan_contract_to_dict(pc)
        assert len(d["disagreements"]) == 1

    def test_render_produces_readable_text(self):
        pc = PlanContract(
            plan_id="plan-test",
            objective="Fix a bug in auth.py",
            steps=["Inspect auth.py", "Fix the bug", "Run tests"],
            risks=["Security risk"],
            non_goals=["Don't change secrets.py"],
            required_evidence=["test_output.txt"],
            success_criteria=["All tests pass"],
            stop_conditions=["Stop if tests fail"],
            approval_status="draft",
        )
        text = render_plan_contract(pc)
        assert "plan-test" in text
        assert "Fix a bug in auth.py" in text
        assert "Inspect auth.py" in text
        assert "Security risk" in text
        assert "Don't change secrets.py" in text
        assert "test_output.txt" in text
        assert "draft" in text

    def test_render_shows_blocking_concerns(self):
        pc = PlanContract(
            plan_id="plan-bc",
            objective="Risky task",
            blocking_concerns=["BLOCKING: Missing human review gate"],
        )
        text = render_plan_contract(pc)
        assert "BLOCKING CONCERNS" in text
        assert "BLOCKING: Missing human review gate" in text
        assert "Executable:    NO" in text

    def test_render_shows_non_blocking_concerns(self):
        pc = PlanContract(
            plan_id="plan-nbc",
            objective="Task with warnings",
            non_blocking_concerns=["Consider splitting into sub-tasks"],
        )
        text = render_plan_contract(pc)
        assert "Non-Blocking Concerns" in text
        assert "Consider splitting into sub-tasks" in text

    def test_to_dict_includes_blocking_concerns(self):
        pc = PlanContract(
            plan_id="p1",
            blocking_concerns=["BLOCKING: No files specified"],
            non_blocking_concerns=["Consider adding tests"],
        )
        d = plan_contract_to_dict(pc)
        assert d["has_blocking_concerns"] is True
        assert "BLOCKING: No files specified" in d["blocking_concerns"]
        assert "Consider adding tests" in d["non_blocking_concerns"]

    def test_to_dict_has_boundaries_in_worker_tasks(self):
        wt = PlannedWorkerTask(
            title="Bounded",
            objective="Do work",
            allowed_files=["src/a.py"],
        )
        pc = PlanContract(plan_id="p1", planned_worker_tasks=[wt])
        d = plan_contract_to_dict(pc)
        assert d["planned_worker_tasks"][0]["has_boundaries"] is True


# =============================================================================
# PlannedWorkerTask -> WorkerTaskPacket mapping
# =============================================================================

class TestPlannedTaskToPacketMapping:
    def test_mapping_preserves_objective(self):
        pwt = PlannedWorkerTask(
            title="T1",
            objective="Do work",
            allowed_files=["src/a.py"],
            denied_files=["src/b.py"],
            required_checks=["pytest"],
            expected_evidence=["test_output.txt"],
            risk_level="high",
        )
        kwargs = planned_task_to_packet_kwargs(pwt, run_id="r1", task_id="t1")
        assert kwargs["run_id"] == "r1"
        assert kwargs["task_id"] == "t1"
        assert kwargs["objective"] == "Do work"
        assert kwargs["allowed_files"] == ["src/a.py"]
        assert kwargs["denied_files"] == ["src/b.py"]
        assert kwargs["required_checks"] == ["pytest"]
        assert kwargs["expected_evidence"] == ["test_output.txt"]
        assert kwargs["risk_level"] == "high"

    def test_mapping_without_ids(self):
        pwt = PlannedWorkerTask(title="T1", objective="X")
        kwargs = planned_task_to_packet_kwargs(pwt)
        assert kwargs["run_id"] == ""
        assert kwargs["task_id"] == ""
        assert kwargs["objective"] == "X"


# =============================================================================
# Local advisors
# =============================================================================

class TestLocalPlannerAdvisor:
    def test_implements_protocol(self):
        advisor = LocalPlannerAdvisor()
        assert isinstance(advisor, PlanningAdvisor)
        assert advisor.role == "planner"

    def test_produces_steps_for_code_task(self):
        advisor = LocalPlannerAdvisor()
        candidate = advisor.advise(
            "Fix the login bug in `src/auth.py`",
            task_size="medium",
            run_mode="controlled",
            risk_level="medium",
        )
        assert len(candidate.steps) >= 1
        assert any("auth.py" in s for s in candidate.steps)
        assert candidate.role == "planner"

    def test_produces_evidence_for_code_task(self):
        advisor = LocalPlannerAdvisor()
        candidate = advisor.advise(
            "Implement feature X in src/module.py",
            task_size="medium",
        )
        assert any("test_output.txt" in e or "diff.patch" in e for e in candidate.required_evidence)

    def test_produces_human_review_gates_for_high_risk(self):
        advisor = LocalPlannerAdvisor()
        candidate = advisor.advise(
            "Delete the user database and redeploy production",
            task_size="large",
            risk_level="high",
        )
        assert len(candidate.human_review_gates) >= 1

    def test_produces_non_goals(self):
        advisor = LocalPlannerAdvisor()
        candidate = advisor.advise("Add a feature")
        assert len(candidate.non_goals) >= 1
        assert any("Do not change" in ng or "Do not skip" in ng for ng in candidate.non_goals)

    def test_large_task_produces_more_steps(self):
        advisor = LocalPlannerAdvisor()
        small = advisor.advise("What is Python?", task_size="small")
        large = advisor.advise("Implement Phase 13 end-to-end architecture", task_size="large")
        assert len(large.steps) >= len(small.steps)


class TestLocalRiskReviewerAdvisor:
    def test_implements_protocol(self):
        advisor = LocalRiskReviewerAdvisor()
        assert isinstance(advisor, PlanningAdvisor)
        assert advisor.role == "risk_reviewer"

    def test_high_risk_task_requires_human_review_gate(self):
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise(
            "Delete all production databases",
            task_size="large",
            risk_level="high",
        )
        has_human_gate = any(
            "human review" in g.lower() or "MUST" in g
            for g in candidate.human_review_gates
        )
        assert has_human_gate or len(candidate.human_review_gates) >= 1

    def test_code_task_requires_evidence(self):
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise("Implement feature X", task_size="medium")
        assert len(candidate.required_evidence) >= 1

    def test_identifies_scope_risk_without_files(self):
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise("Fix the bug", task_size="medium")
        # Should identify scope risk since no files mentioned
        combined = " ".join(candidate.risks + candidate.non_goals)
        assert len(candidate.risks) >= 1

    def test_produces_risks_for_large_task(self):
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise("Implement entire Phase 13", task_size="large")
        assert len(candidate.risks) >= 1

    # --- blocking concerns from risk_reviewer ------------------------------

    def test_high_risk_without_human_review_produces_blocking_concern(self):
        """Risk reviewer MUST produce blocking concern for high-risk tasks."""
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise(
            "Delete all production databases and redeploy",
            task_size="large",
            risk_level="high",
        )
        assert len(candidate.blocking_concerns) >= 1
        blocking_text = " ".join(candidate.blocking_concerns).lower()
        assert "human_review_gate" in blocking_text or "human review" in blocking_text

    def test_code_change_without_files_produces_blocking_concern(self):
        """Risk reviewer blocks medium/large code tasks with no files."""
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise("Fix the login bug", task_size="medium")
        blocking_text = " ".join(candidate.blocking_concerns).lower()
        assert "scope too broad" in blocking_text or "no files" in blocking_text

    def test_scope_creep_produces_blocking_concern(self):
        """Risk reviewer blocks queries touching >=3 distinct domains."""
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise(
            "Implement auth, migrate database, and deploy to production",
            task_size="large",
        )
        # This should hit auth + database + deploy = 3 domains
        assert len(candidate.blocking_concerns) >= 1
        blocking_text = " ".join(candidate.blocking_concerns).lower()
        assert "scope creep" in blocking_text

    def test_safe_query_produces_only_non_blocking(self):
        """Non-code, non-high-risk queries should only have non-blocking concerns."""
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise(
            "Research the best Python testing frameworks",
            task_size="medium",
        )
        # No blocking concerns expected for research-only tasks
        assert len(candidate.blocking_concerns) == 0

    def test_risk_reviewer_outputs_separate_blocking_and_non_blocking(self):
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise(
            "Delete user database credentials",
            task_size="large",
            risk_level="high",
        )
        assert isinstance(candidate.blocking_concerns, list)
        assert isinstance(candidate.non_blocking_concerns, list)
        # Blocking concerns should start with BLOCKING:
        for bc in candidate.blocking_concerns:
            assert bc.startswith("BLOCKING:"), f"Expected BLOCKING prefix: {bc}"

    def test_large_code_task_without_files_is_blocked(self):
        advisor = LocalRiskReviewerAdvisor()
        candidate = advisor.advise(
            "Implement the new microservice architecture",
            task_size="large",
        )
        blocking_text = " ".join(candidate.blocking_concerns).lower()
        assert "no concrete boundaries" in blocking_text or "files mentioned" in blocking_text


class TestLocalExecutionPlannerAdvisor:
    def test_implements_protocol(self):
        advisor = LocalExecutionPlannerAdvisor()
        assert isinstance(advisor, PlanningAdvisor)
        assert advisor.role == "execution_planner"

    def test_produces_numbered_steps(self):
        advisor = LocalExecutionPlannerAdvisor()
        candidate = advisor.advise("Add feature X to src/module.py", task_size="medium")
        assert len(candidate.steps) >= 3

    def test_code_task_has_test_step(self):
        advisor = LocalExecutionPlannerAdvisor()
        candidate = advisor.advise("Implement feature in src/a.py")
        has_test = any("test" in s.lower() or "check" in s.lower() for s in candidate.steps)
        assert has_test

    def test_high_risk_has_human_review_gate(self):
        advisor = LocalExecutionPlannerAdvisor()
        candidate = advisor.advise(
            "Delete all user records from database",
            risk_level="high",
        )
        assert len(candidate.human_review_gates) >= 1

    def test_non_code_task_has_different_steps(self):
        advisor = LocalExecutionPlannerAdvisor()
        code_plan = advisor.advise("Implement feature X in src/a.py")
        research_plan = advisor.advise("Research the best approach for X")
        assert code_plan.steps != research_plan.steps

    # --- blocking concerns from execution_planner --------------------------

    def test_large_code_task_without_files_produces_blocking_concern(self):
        advisor = LocalExecutionPlannerAdvisor()
        candidate = advisor.advise(
            "Implement the new architecture",
            task_size="large",
        )
        blocking_text = " ".join(candidate.blocking_concerns).lower()
        assert "no file boundaries" in blocking_text or "no allowed_files" in blocking_text

    def test_small_task_does_not_produce_blocking_from_execution_planner(self):
        advisor = LocalExecutionPlannerAdvisor()
        candidate = advisor.advise(
            "What is Python?",
            task_size="small",
        )
        assert len(candidate.blocking_concerns) == 0


# =============================================================================
# PlanningCouncil
# =============================================================================

class TestPlanningCouncil:
    def test_creates_plan_with_required_fields(self):
        council = build_default_council()
        plan = council.create_plan(
            "Implement Phase 13 planning council in src/orchestrator/",
            task_size="large",
            run_mode="orchestrated",
            risk_level="medium",
        )
        assert plan.objective != ""
        assert len(plan.steps) > 0
        assert len(plan.risks) > 0
        assert len(plan.non_goals) > 0
        assert len(plan.required_evidence) > 0
        assert len(plan.success_criteria) > 0
        assert len(plan.stop_conditions) > 0
        assert plan.approval_status == "draft"

    def test_creates_plan_with_steps_risks_evidence_success_and_non_goals(self):
        council = build_default_council()
        plan = council.create_plan(
            "Add login feature to src/auth.py with full test coverage",
            task_size="large",
            run_mode="orchestrated",
            risk_level="high",
        )
        assert len(plan.steps) >= 1
        assert len(plan.risks) >= 1
        assert len(plan.non_goals) >= 1
        assert len(plan.required_evidence) >= 1
        assert len(plan.success_criteria) >= 1
        assert len(plan.stop_conditions) >= 1

    def test_plan_has_unique_plan_id(self):
        council = build_default_council()
        p1 = council.create_plan("Task A", task_size="large")
        p2 = council.create_plan("Task B", task_size="large")
        assert p1.plan_id != p2.plan_id
        assert p1.plan_id.startswith("plan-")

    def test_large_task_creates_planned_worker_tasks(self):
        council = build_default_council()
        plan = council.create_plan(
            "Implement Phase 13 in src/orchestrator/",
            task_size="large",
            run_mode="orchestrated",
        )
        assert len(plan.planned_worker_tasks) >= 1

    def test_small_task_does_not_create_planned_worker_tasks(self):
        council = build_default_council()
        plan = council.create_plan(
            "What is Python?",
            task_size="small",
        )
        # Small tasks don't need worker tasks
        assert plan.planned_worker_tasks == []

    def test_council_keeps_advisor_disagreements_for_audit(self):
        council = build_default_council()
        # Use a query that will produce disagreements between planner and risk reviewer
        plan = council.create_plan(
            "Deploy to production and delete old database",
            task_size="large",
            risk_level="high",
        )
        assert len(plan.source_candidates) == 3  # all 3 advisors contributed
        # Disagreements may or may not exist depending on the exact query,
        # but source_candidates must always be preserved
        assert len(plan.source_candidates) > 0

    def test_council_has_bounded_candidates(self):
        council = build_default_council()
        assert council.max_candidates == 3
        plan = council.create_plan("Some task", task_size="large")
        assert len(plan.source_candidates) <= 3

    def test_council_rejects_too_many_candidates(self):
        with pytest.raises(ValueError):
            PlanningCouncil(max_candidates=5)

    def test_council_rejects_too_many_revision_rounds(self):
        with pytest.raises(ValueError):
            PlanningCouncil(max_revision_rounds=2)

    def test_revise_plan_updates_fields(self):
        council = build_default_council()
        plan = council.create_plan("Task", task_size="large")
        plan = council.revise_plan(
            plan,
            edits={"steps": ["Updated step 1"], "non_goals": ["Updated non-goal"]},
        )
        assert plan.steps == ["Updated step 1"]
        assert "Updated non-goal" in plan.non_goals
        assert plan.approval_status == "edited"

    # --- blocking concerns from council -----------------------------------

    def test_council_merges_blocking_concerns_from_all_advisors(self):
        """create_plan should collect blocking_concerns from all candidates."""
        council = build_default_council()
        plan = council.create_plan(
            "Delete production database and migrate all credentials",
            task_size="large",
            risk_level="high",
        )
        # Risk reviewer + possibly execution planner should have blocking concerns
        assert isinstance(plan.blocking_concerns, list)
        assert isinstance(plan.non_blocking_concerns, list)
        # High-risk should definitely produce blocking concerns from risk reviewer
        assert len(plan.blocking_concerns) >= 1

    def test_high_risk_large_task_produces_unapproved_plan(self):
        """High-risk large tasks must produce draft (not approved) plans."""
        council = build_default_council()
        plan = council.create_plan(
            "Delete all user data and drop production database",
            task_size="large",
            risk_level="high",
        )
        assert plan.approval_status == "draft"
        assert plan.has_blocking_concerns  # high-risk large tasks ALWAYS have blocking concerns

    def test_council_plan_disagreements_mention_blocking(self):
        """When risk reviewer has blocking concerns, disagreements should mention it."""
        council = build_default_council()
        plan = council.create_plan(
            "Delete production database credentials and migrate all secrets",
            task_size="large",
            risk_level="high",
        )
        # At least one disagreement should mention blocking
        blocking_mentioned = any(
            "blocking" in d.lower() for d in plan.disagreements
        )
        assert blocking_mentioned or len(plan.blocking_concerns) > 0

    def test_plan_cannot_be_approved_with_blocking_concerns_from_council(self):
        """End-to-end: council creates plan with blocking concerns → cannot approve."""
        council = build_default_council()
        plan = council.create_plan(
            "Delete everything in production",
            task_size="large",
            risk_level="high",
        )
        assert plan.has_blocking_concerns
        with pytest.raises(ValueError, match="Cannot approve"):
            plan.approve()


# =============================================================================
# Task size gating
# =============================================================================

class TestTaskSizeGating:
    def test_small_task_does_not_produce_large_plan(self):
        """Small tasks should not create complex plans by default."""
        council = build_default_council()
        plan = council.create_plan(
            "What does git status do?",
            task_size="small",
            run_mode="log",
        )
        # Small tasks still get a plan contract (the council creates one),
        # but it should be minimal
        assert plan.task_size == "small"
        assert plan.planned_worker_tasks == []

    def test_complex_task_generates_plan_contract(self):
        council = build_default_council()
        plan = council.create_plan(
            "Implement Phase 13 end-to-end architecture with multi-step migration",
            task_size="large",
            run_mode="orchestrated",
        )
        assert plan.task_size == "large"
        assert len(plan.steps) > 0
        assert plan.approval_status == "draft"


# =============================================================================
# Plan verification (ControlPlane)
# =============================================================================

class TestControlPlaneVerifyPlan:
    def test_valid_plan_passes_verification(self):
        cp = ControlPlane()
        council = build_default_council()
        plan = council.create_plan(
            "Add feature X to src/module.py with tests",
            task_size="large",
            run_mode="orchestrated",
        )
        decision = cp.verify_plan(plan)
        assert decision.passed
        assert decision.action == "continue"

    def test_plan_missing_steps_requests_revision(self):
        cp = ControlPlane()
        plan = PlanContract(
            objective="Do something",
            steps=[],  # no steps
            success_criteria=["Complete"],
            required_evidence=["result.md"],
        )
        decision = cp.verify_plan(plan)
        assert not decision.passed
        assert decision.action == "replan"

    def test_plan_missing_success_criteria_requests_revision(self):
        cp = ControlPlane()
        plan = PlanContract(
            objective="Do something",
            steps=["Step 1"],
            success_criteria=[],  # no success criteria
            required_evidence=["result.md"],
        )
        decision = cp.verify_plan(plan)
        assert not decision.passed
        assert decision.action == "replan"

    def test_plan_missing_required_evidence_for_code_work_requests_revision(self):
        cp = ControlPlane()
        council = build_default_council()
        plan = council.create_plan(
            "Implement new authentication system",
            task_size="large",
        )
        # Clear evidence AND blocking concerns to isolate the evidence check
        plan.required_evidence = []
        plan.blocking_concerns = []
        decision = cp.verify_plan(plan)
        assert not decision.passed
        assert decision.action == "replan"

    def test_high_risk_plan_without_gate_requires_human_review(self):
        cp = ControlPlane()
        council = build_default_council()
        plan = council.create_plan(
            "Delete all user data and drop production database",
            task_size="large",
            risk_level="high",
        )
        # Clear human review gates to trigger the check
        plan.human_review_gates = []
        decision = cp.verify_plan(plan)
        assert not decision.passed
        assert decision.action == "needs_human_review"

    def test_not_a_plan_contract_fails(self):
        cp = ControlPlane()
        decision = cp.verify_plan("not a plan")
        assert not decision.passed
        assert decision.action == "fail"

    def test_off_mode_bypasses_verification(self):
        cp = ControlPlane(policy=Policy(mode="off"))
        plan = PlanContract(objective="X")  # missing everything
        decision = cp.verify_plan(plan)
        assert decision.passed

    def test_log_mode_passes_but_records(self):
        cp = ControlPlane(policy=Policy(mode="log"))
        plan = PlanContract(objective="X", steps=[])  # missing steps
        decision = cp.verify_plan(plan)
        assert decision.passed  # log mode does not block
        assert decision.action == "continue"

    def test_planned_worker_task_without_boundaries_requests_revision(self):
        cp = ControlPlane()
        wt = PlannedWorkerTask(title="Unbounded task", objective="Do stuff")
        plan = PlanContract(
            objective="Test",
            steps=["Step 1"],
            success_criteria=["Done"],
            required_evidence=["result.md"],
            planned_worker_tasks=[wt],
        )
        decision = cp.verify_plan(plan)
        # No allowed_files, no denied_files -> no boundaries
        assert not decision.passed
        assert decision.action == "replan"

    def test_planned_worker_task_with_boundaries_passes(self):
        cp = ControlPlane()
        wt = PlannedWorkerTask(
            title="Bounded task",
            objective="Do stuff",
            allowed_files=["src/a.py"],
            denied_files=["src/secrets.py"],
        )
        plan = PlanContract(
            objective="Test",
            steps=["Step 1"],
            success_criteria=["Done"],
            required_evidence=["result.md"],
            planned_worker_tasks=[wt],
        )
        decision = cp.verify_plan(plan)
        assert decision.passed

    # --- verify_plan rejects plans with blocking concerns ------------------

    def test_verify_plan_rejects_blocking_concerns(self):
        """verify_plan MUST return needs_human_review for plans with blocking concerns."""
        cp = ControlPlane()
        plan = PlanContract(
            objective="Fix auth bug",
            steps=["Inspect auth.py", "Fix the bug", "Run tests"],
            success_criteria=["All tests pass"],
            required_evidence=["test_output.txt", "diff.patch"],
            blocking_concerns=["BLOCKING: Missing human review gate for high-risk operation"],
        )
        decision = cp.verify_plan(plan)
        assert not decision.passed
        assert decision.action == "needs_human_review"
        assert decision.severity == "high"
        assert "blocking concern" in decision.reason.lower()

    def test_verify_plan_blocking_concerns_checked_before_other_checks(self):
        """Blocking concerns are the FIRST check; returns immediately."""
        cp = ControlPlane()
        plan = PlanContract(
            objective="Task",
            steps=[],  # Also missing steps, but blocking should fire first
            success_criteria=[],
            blocking_concerns=["BLOCKING: Scope creep"],
        )
        decision = cp.verify_plan(plan)
        assert not decision.passed
        # Should be needs_human_review from blocking check, not replan from missing steps
        assert decision.action == "needs_human_review"

    def test_verify_plan_log_mode_passes_blocking_concerns(self):
        cp = ControlPlane(policy=Policy(mode="log"))
        plan = PlanContract(
            objective="Task",
            steps=["Step 1"],
            success_criteria=["Done"],
            blocking_concerns=["BLOCKING: Missing gate"],
        )
        decision = cp.verify_plan(plan)
        assert decision.passed  # log mode does not block

    def test_verify_plan_off_mode_bypasses_blocking_concerns(self):
        cp = ControlPlane(policy=Policy(mode="off"))
        plan = PlanContract(
            objective="Task",
            blocking_concerns=["BLOCKING: Something"],
        )
        decision = cp.verify_plan(plan)
        assert decision.passed


# =============================================================================
# User approve/edit/reject paths
# =============================================================================

class TestUserApprovalPaths:
    def test_user_rejects_plan_and_execution_does_not_start(self):
        plan = PlanContract(plan_id="p1", steps=["Step 1"])
        plan.reject()
        assert plan.approval_status == "rejected"

    def test_user_approves_plan(self):
        plan = PlanContract(plan_id="p1", steps=["Step 1"])
        plan.approve()
        assert plan.approval_status == "approved"

    def test_user_edits_plan_and_contract_is_updated(self):
        plan = PlanContract(
            plan_id="p1",
            steps=["Old step"],
            non_goals=["Old non-goal"],
        )
        plan.edit(steps=["New step 1", "New step 2"])
        assert plan.steps == ["New step 1", "New step 2"]
        assert plan.approval_status == "edited"

    def test_edit_only_changes_provided_fields(self):
        plan = PlanContract(
            plan_id="p1",
            steps=["Step 1"],
            non_goals=["Non-goal 1"],
            risks=["Risk 1"],
            success_criteria=["Criterion 1"],
        )
        plan.edit(steps=["Updated step"])
        assert plan.steps == ["Updated step"]
        assert plan.non_goals == ["Non-goal 1"]  # unchanged
        assert plan.risks == ["Risk 1"]  # unchanged
        assert plan.success_criteria == ["Criterion 1"]  # unchanged

    def test_rejected_plan_cannot_be_used_for_execution(self):
        plan = PlanContract(plan_id="p1", steps=["Step 1"])
        plan.reject()
        assert plan.approval_status != "approved"
        assert plan.approval_status != "draft"


# =============================================================================
# Compatibility: planned worker tasks preserve boundaries for Phase 12
# =============================================================================

class TestPlannedWorkerTaskBoundariesPreserved:
    def test_boundaries_are_available_for_worker_packet(self):
        pwt = PlannedWorkerTask(
            title="Worker task",
            objective="Do bounded work",
            allowed_files=["src/module.py", "tests/test_module.py"],
            denied_files=["src/secrets.py", ".env"],
            required_checks=["python -m pytest", "python -m mypy"],
            expected_evidence=["test_output.txt", "diff.patch"],
            risk_level="medium",
        )
        packet_kwargs = planned_task_to_packet_kwargs(pwt)
        assert "src/module.py" in packet_kwargs["allowed_files"]
        assert "src/secrets.py" in packet_kwargs["denied_files"]
        assert "python -m pytest" in packet_kwargs["required_checks"]
        assert "test_output.txt" in packet_kwargs["expected_evidence"]
        assert packet_kwargs["risk_level"] == "medium"


# =============================================================================
# Regression: existing task router behavior still works
# =============================================================================

class TestTaskRouterStillWorks:
    def test_route_small_task_not_large(self):
        from orchestrator.task_router import route_task
        decision = route_task("What is Python?")
        assert decision.task_size in ("small", "medium")
        # Small/medium tasks should not trigger orchestrated mode
        assert decision.run_mode != "orchestrated" or decision.task_size == "large"

    def test_route_large_task_is_large(self):
        from orchestrator.task_router import route_task
        decision = route_task(
            "Implement Phase 13 end-to-end architecture migration"
        )
        assert decision.task_size == "large"
        assert decision.run_mode in ("controlled", "orchestrated")


# =============================================================================
# Regression: existing worker bridge evidence tests still pass
# =============================================================================

class TestWorkerBridgeStillWorks:
    def test_worker_task_packet_create_still_works(self):
        from orchestrator.worker_protocol import WorkerTaskPacket
        packet = WorkerTaskPacket.create(objective="Test")
        assert packet.objective == "Test"
        assert packet.worker_kind == "claude_code"

    def test_planned_worker_task_to_packet_preserves_contract(self):
        """PlannedWorkerTask can feed WorkerTaskPacket.create() without loss."""
        from orchestrator.worker_protocol import WorkerTaskPacket

        pwt = PlannedWorkerTask(
            title="Fix auth bug",
            objective="Fix the authentication bug in auth.py",
            allowed_files=["src/auth.py"],
            denied_files=["src/secrets.py"],
            required_checks=["python -m pytest tests/test_auth.py"],
            expected_evidence=["test_output.txt"],
            risk_level="high",
        )
        kwargs = planned_task_to_packet_kwargs(pwt)
        packet = WorkerTaskPacket.create(**{k: v for k, v in kwargs.items() if v})  # type: ignore[arg-type]

        assert packet.objective == pwt.objective
        assert packet.allowed_files == pwt.allowed_files
        assert packet.denied_files == pwt.denied_files
        assert packet.required_checks == pwt.required_checks
        assert packet.expected_evidence == pwt.expected_evidence
        assert packet.risk_level == "high"


# =============================================================================
# Regression: control plane policy/recovery tests still pass
# =============================================================================

class TestControlPlaneStillWorks:
    def test_evaluate_output_still_works(self):
        cp = ControlPlane()
        from orchestrator.models import EvalCriteriaItem
        criteria = [
            EvalCriteriaItem(
                path="result",
                expected_type="non_empty_str",
                action="retry",
            ),
        ]
        decision = cp.evaluate_output(criteria, {"result": "OK"})
        assert decision.passed
        assert decision.action == "continue"

    def test_verify_worker_evidence_still_works(self):
        cp = ControlPlane()
        from orchestrator.control_models import WorkerEvidenceStatus, WorkerEvidenceItem
        evidence = WorkerEvidenceStatus(
            task_id="t1",
            worker_kind="claude_code",
            worker_status="completed",
            items=[
                WorkerEvidenceItem(key="test_output.txt", status="observed"),
            ],
        )
        decision = cp.verify_worker_evidence(evidence)
        assert decision.passed
        assert decision.action == "continue"

    def test_decide_recovery_still_works(self):
        cp = ControlPlane()
        from orchestrator.failure_taxonomy import FailureCategory, FailureRecord
        fr = FailureRecord(
            category=FailureCategory.TASK_QUALITY_ERROR,
            reason="missing_evidence",
            origin="worker",
        )
        recovery = cp.decide_recovery(fr, task_id="t1")
        assert recovery.recovery_hint == "request_evidence"


# =============================================================================
# Live view planning summary
# =============================================================================

class TestLiveViewPlanningSummary:
    def test_build_live_view_accepts_planning_summary(self):
        from orchestrator.live_view import build_live_view
        from orchestrator.state_center import StateCenter

        state = StateCenter(query="test")
        plan_sum = {
            "plan_id": "plan-abc",
            "approval_status": "approved",
            "number_of_steps": 5,
            "required_evidence_count": 3,
            "top_risks": ["Security risk", "Scope risk"],
        }
        view = build_live_view(state, planning_summary=plan_sum)
        assert view["planning_summary"] is not None
        assert view["planning_summary"]["plan_id"] == "plan-abc"
        assert view["planning_summary"]["approval_status"] == "approved"
        assert view["planning_summary"]["number_of_steps"] == 5

    def test_build_live_view_without_planning_summary_is_none(self):
        from orchestrator.live_view import build_live_view
        from orchestrator.state_center import StateCenter

        state = StateCenter(query="test")
        view = build_live_view(state)
        assert view["planning_summary"] is None


# =============================================================================
# CLI plan command (unit level)
# =============================================================================

class TestPlanCommand:
    def test_build_default_council_returns_planning_council(self):
        council = build_default_council()
        assert isinstance(council, PlanningCouncil)
        assert council.max_candidates == 3

    def test_plan_contract_is_serializable(self):
        council = build_default_council()
        plan = council.create_plan(
            "Add feature X to src/module.py",
            task_size="large",
        )
        d = plan_contract_to_dict(plan)
        assert isinstance(d, dict)
        assert "plan_id" in d
        assert "steps" in d
        assert "risks" in d

    def test_render_plan_contract_returns_string(self):
        plan = PlanContract(plan_id="p1", objective="Test", steps=["S1"])
        text = render_plan_contract(plan)
        assert isinstance(text, str)
        assert "p1" in text
        assert "Test" in text
