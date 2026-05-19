#!/usr/bin/env python3
"""Demo C — Complex Task Control Loop.

Story:
    Complex task enters planning, gets reviewed, executes through a worker,
    hits at least one control decision, and ends with an audit report.

Value:
    Shows the full AAO workflow, not a single isolated checker.

What it shows:
    - Planning Council creates a plan with risk review
    - Plan is approved
    - Worker executes
    - Evidence is verified
    - Control decisions along the way
    - Final audit report

Run:
    python scripts/demo/full_control_loop.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from orchestrator.control_models import (
    ControlDecision,
    WorkerEvidenceItem,
    WorkerEvidenceStatus,
)
from orchestrator.control_plane import ControlPlane
from orchestrator.failure_taxonomy import (
    FailureCategory,
    FailureSeverity,
    create_failure_record,
)
from orchestrator.planning import (
    PlanContract,
    build_default_council,
)
from orchestrator.policy import Policy

from _demo_utils import (
    banner,
    print_decision,
    print_header,
    print_section,
    write_sample_json,
    write_sample_markdown,
    write_sample_text,
)


def main() -> None:
    banner("AAO Demo C — Complex Task Control Loop")

    # ------------------------------------------------------------------
    # 1. Policy — controlled mode with evidence requirements
    # ------------------------------------------------------------------
    print_header("1. Policy Configuration")
    policy = Policy.from_dict({
        "mode": "controlled",
        "files": {
            "allowed": ["src/**", "tests/**"],
            "protected": [".env", "config/secrets.yaml"],
        },
        "checks": {
            "required": ["pytest", "lint"],
        },
        "human_review": {
            "required_for": ["protected_file_change", "failed_tests"],
        },
    })
    print_section("Run mode", policy.mode)
    print_section("Required checks", policy.get_required_checks())

    # ------------------------------------------------------------------
    # 2. Planning Council — create a plan for a complex task
    # ------------------------------------------------------------------
    print_header("2. Planning Council — Plan Creation")

    task_query = (
        "Refactor error handling in src/errors.py, src/middleware.py, "
        "and tests/test_errors.py to use structured error types"
    )
    print_section("Task query", task_query)

    council = build_default_council()
    plan = council.create_plan(
        query=task_query,
        task_size="large",
        run_mode="controlled",
    )

    print_section("Plan ID", plan.plan_id)
    print_section("Task size", plan.task_size)
    print_section("Steps", plan.steps)
    print_section("Success criteria", plan.success_criteria)
    print_section("Stop conditions", plan.stop_conditions)
    print_section("Required evidence", plan.required_evidence)
    print_section("Non-goals", plan.non_goals)
    print_section("Planned worker tasks", str(plan.planned_worker_tasks))

    if plan.blocking_concerns:
        print("\n  ⚠ Blocking concerns (from risk reviewer):")
        for concern in plan.blocking_concerns:
            print(f"    - {concern}")

    # ------------------------------------------------------------------
    # 3. Plan approval
    # ------------------------------------------------------------------
    print_header("3. Plan Approval")

    approve_error = None
    try:
        plan.approve()
        print("  Plan APPROVED — execution can proceed.")
    except ValueError as exc:
        approve_error = str(exc)
        print(f"  Plan approval BLOCKED: {approve_error}")

    print_section("Approval status", plan.approval_status)
    if approve_error:
        print_section("Approve error", approve_error)

    # ------------------------------------------------------------------
    # 4. ControlPlane verifies the plan
    # ------------------------------------------------------------------
    print_header("4. ControlPlane — Plan Verification")

    cp = ControlPlane(policy=policy)
    plan_decision = cp.verify_plan(plan)
    print_decision(plan_decision.model_dump())

    plan_verification = {
        "plan_id": plan.plan_id,
        "task_size": plan.task_size,
        "steps_count": len(plan.steps),
        "has_success_criteria": len(plan.success_criteria) > 0,
        "has_required_evidence": len(plan.required_evidence) > 0,
        "blocking_concerns": plan.blocking_concerns,
        "approved": plan.approval_status == "approved",
        "verification_passed": plan_decision.passed,
    }
    print_section("Plan verification", plan_verification)

    # ------------------------------------------------------------------
    # 5. Worker execution (fake, deterministic)
    # ------------------------------------------------------------------
    print_header("5. Worker Execution")

    worker_output = {
        "status": "completed",
        "test_output": "14 passed, 0 failed",
        "files_changed": [
            "src/errors.py",
            "src/middleware.py",
            "tests/test_errors.py",
        ],
        "tools_called": ["read_file", "edit_file", "run_tests", "run_lint"],
        "errors": [],
        "summary": "Refactored error handling to use structured error types. All tests pass.",
    }
    print_section("status", worker_output["status"])
    print_section("test_output", worker_output["test_output"])
    print_section("files_changed", worker_output["files_changed"])
    print_section("tools_called", worker_output["tools_called"])

    # ------------------------------------------------------------------
    # 6. Evidence verification
    # ------------------------------------------------------------------
    print_header("6. Evidence Verification")

    evidence_items = [
        WorkerEvidenceItem(key="test_output", status="observed", path="test_results.json",
                          description="14 passed, 0 failed"),
        WorkerEvidenceItem(key="diff_patch", status="observed", path="diff.patch",
                          description="Unified diff of 3 files"),
        WorkerEvidenceItem(key="lint_output", status="observed", path="lint.log",
                          description="Linter output — no issues found"),
    ]
    evidence_status = WorkerEvidenceStatus(
        task_id=plan.plan_id,
        worker_kind="claude_code",
        worker_status="completed",
        items=evidence_items,
        reported_summary=worker_output["summary"],
        changed_files=worker_output["files_changed"],
    )

    for item in evidence_items:
        icon = "OBSERVED" if item.status == "observed" else "MISSING"
        print(f"  [{icon}] {item.key:20s}  → {item.description}")

    evidence_decision = cp.verify_worker_evidence(evidence_status)
    print_decision(evidence_decision.model_dump())

    # ------------------------------------------------------------------
    # 7. Guardrail output check
    # ------------------------------------------------------------------
    print_header("7. Output Guardrail Check")

    guard_decision = cp.guard_output(
        agent_name="demo_worker",
        payload=worker_output,
    )
    print_decision(guard_decision.model_dump())

    # ------------------------------------------------------------------
    # 8. Recovery — what if tests had failed?
    # ------------------------------------------------------------------
    print_header("8. Recovery — Simulated Test Failure")

    # Simulate: what if tests DID fail?
    test_failure_record = create_failure_record(
        category=FailureCategory.TASK_QUALITY_ERROR,
        origin="worker",
        reason="evaluation_failed",
        agent_name="demo_worker",
        severity=FailureSeverity.MEDIUM,
        recovery_hint="retry",
    )

    retry1 = cp.decide_recovery(
        test_failure_record,
        attempt_count=0,
        run_mode="controlled",
        task_id=plan.plan_id,
        step_name="run_tests",
    )
    print("  --- Attempt 0 (test failure → retry) ---")
    print_section("action", retry1.action)
    print_section("reason", retry1.reason)

    retry2 = cp.decide_recovery(
        test_failure_record,
        attempt_count=1,
        run_mode="controlled",
        task_id=plan.plan_id,
        step_name="run_tests",
    )
    print("\n  --- Attempt 1 (retry exhausted → replan) ---")
    print_section("action", retry2.action)
    print_section("reason", retry2.reason)

    print("\n  >>> Recovery is BOUNDED: retry once, then replan.")
    print("  >>> No infinite retry loop — the system escalates appropriately.")

    # ------------------------------------------------------------------
    # 9. Generate audit report and sample outputs
    # ------------------------------------------------------------------
    print_header("9. Audit Report & Sample Outputs")

    audit_md = f"""\
# Audit Report — {plan.plan_id}

## Task
{task_query}

## Plan
- **Steps**: {len(plan.steps)}
- **Success criteria**: {', '.join(plan.success_criteria)}
- **Required evidence**: {', '.join(plan.required_evidence)}
- **Approval status**: {plan.approval_status}

## Evidence
- test_output: 14 passed, 0 failed [OBSERVED]
- diff_patch: 3 files changed [OBSERVED]
- lint_output: no issues found [OBSERVED]

## Control Decisions
1. Plan verification: {plan_decision.action} (passed={plan_decision.passed})
2. Evidence verification: {evidence_decision.action} (passed={evidence_decision.passed})
3. Output guardrail: {guard_decision.action} (passed={guard_decision.passed})

## Recovery
- Test failure → retry (bounded, max 1)
- Retry exhausted → replan

## Status
**PASSED** — Task completed with observed evidence.
"""
    ar_path = write_sample_markdown("sample_audit_report.md", audit_md)
    print(f"  Audit Report    → {ar_path}")

    ep_data = {
        "task_id": plan.plan_id,
        "step_name": "code_refactor",
        "worker_status": "completed",
        "test_output": "14 passed, 0 failed",
        "files_changed": worker_output["files_changed"],
        "tools_called": worker_output["tools_called"],
        "evidence_items": [item.model_dump() for item in evidence_items],
        "plan_verification": plan_verification,
        "control_decisions": [
            plan_decision.model_dump(),
            evidence_decision.model_dump(),
            guard_decision.model_dump(),
        ],
    }
    ep_path = write_sample_json("sample_evidence_pack.json", ep_data)
    print(f"  Evidence Pack   → {ep_path}")

    lw_text = f"""\
AAO Live Watch — {plan.plan_id}
───────────────────────────────────────────
  Status:       PASSED
  Task:         {task_query}
  Plan:         {plan.plan_id} (large, {len(plan.steps)} steps)
  Progress:     3/3 steps complete
  Current step: audit_report
  Last decision: continue — all checks passed
  Evidence:      test_output [OBSERVED], diff_patch [OBSERVED], lint_output [OBSERVED]
  Guardrails:    output clean
  Human review:  not required"""
    lw_path = write_sample_text("sample_live_watch.txt", lw_text)
    print(f"  Live Watch      → {lw_path}")

    print_header("Summary")
    print("""
  What happened:
    1. Planning Council created a structured plan for a complex task.
    2. Risk reviewer flagged concerns; plan was reviewed and approved.
    3. Worker executed: 3 files changed, 14 tests passed.
    4. Evidence verified: test output, diff, and lint all observed.
    5. Output guardrails checked: no secrets or harmful content.
    6. Recovery simulated: test failure → retry → exhausted → replan.
    7. Audit report generated with evidence, decisions, and status.

  Full AAO workflow demonstrated:
    Planning → Risk Review → Approval → Execution → Evidence →
    Guardrails → Recovery → Audit Report

  Why this matters:
    This shows AAO is not a single checker.  It's a complete control
    loop that guides complex tasks from planning to audit, with
    evidence, guardrails, recovery, and human review at every stage.
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
