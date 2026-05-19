#!/usr/bin/env python3
"""Demo B — Protected File Human Review.

Story:
    Worker attempts a risky/protected file change.
    AAO pauses and asks for human review before continuing.

Value:
    Keeps dangerous work from silently passing through automation.

What it shows:
    - policy rule (config/secrets.yaml is protected)
    - attempted file change
    - ControlPlane check → needs_human_review
    - human review approve path (→ continue)
    - human review reject path (→ fail)
    - generated sample outputs

Run:
    python scripts/demo/protected_file.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from orchestrator.control_plane import ControlPlane
from orchestrator.failure_taxonomy import (
    FailureCategory,
    FailureSeverity,
    create_failure_record,
)
from orchestrator.planning import PlanContract
from orchestrator.policy import Policy

from _demo_utils import (
    banner,
    print_decision,
    print_header,
    print_section,
    write_sample_json,
    write_sample_text,
)


def main() -> None:
    banner("AAO Demo B — Protected File Human Review")

    # ------------------------------------------------------------------
    # 1. Policy with protected files
    # ------------------------------------------------------------------
    print_header("1. Policy Configuration")

    policy = Policy.from_dict({
        "mode": "controlled",
        "files": {
            "allowed": ["src/**", "tests/**", "docs/**"],
            "protected": [".env", "config/secrets.yaml", "config/credentials.*"],
        },
        "human_review": {
            "required_for": [
                "protected_file_change",
                "high_risk_tool",
            ],
        },
    })
    print_section("Run mode", policy.mode)
    print_section("Protected files", [
        ".env",
        "config/secrets.yaml",
        "config/credentials.*",
    ])
    print_section("Human review triggers", [
        "protected_file_change",
        "high_risk_tool",
    ])

    # Show that the file is indeed protected
    is_protected = policy.is_file_protected("config/secrets.yaml")
    needs_review = policy.requires_human_review_for_file("config/secrets.yaml")
    print(f"\n  config/secrets.yaml → is_protected={is_protected}, needs_human_review={needs_review}")

    # ------------------------------------------------------------------
    # 2. Fake worker output — modified a protected file
    # ------------------------------------------------------------------
    print_header("2. Worker Output (fake, deterministic)")

    worker_output = {
        "status": "completed",
        "test_output": "5 passed",
        "files_changed": ["src/main.py", "config/secrets.yaml"],
        "tools_called": ["read_file", "edit_file", "run_tests"],
        "summary": "Updated main entry point and secrets configuration",
    }
    print_section("status", worker_output["status"])
    print_section("test_output", worker_output["test_output"])
    print_section("files_changed", worker_output["files_changed"])
    print_section("summary", worker_output["summary"])

    # ------------------------------------------------------------------
    # 3. ControlPlane checks the file changes
    # ------------------------------------------------------------------
    print_header("3. ControlPlane — Policy Check")

    cp = ControlPlane(policy=policy)
    decision = cp.check_policy_for_file_changes(
        files_changed=worker_output["files_changed"],
    )
    print_decision(decision.model_dump())

    if not decision.passed:
        print("\n  >>> AAO BLOCKED: Protected file change detected.")
        print("  >>> config/secrets.yaml is on the protected list.")
        print("  >>> System requires HUMAN REVIEW before proceeding.")

    # ------------------------------------------------------------------
    # 4. Failure classification for the policy violation
    # ------------------------------------------------------------------
    print_header("4. Failure Classification")

    failure_record = create_failure_record(
        category=FailureCategory.POLICY_ERROR,
        origin="policy",
        reason="protected_file_change",
        agent_name="demo_worker",
        severity=FailureSeverity.HIGH,
        recovery_hint="needs_human_review",
    )
    print_section("category", failure_record.category.value)
    print_section("reason", failure_record.reason)
    print_section("severity", failure_record.severity.value)
    print_section("recovery_hint", failure_record.recovery_hint)

    # ------------------------------------------------------------------
    # 5. Human Review Gate — ASK (simulated)
    # ------------------------------------------------------------------
    print_header("5. Human Review Gate")

    review_question = (
        f"Worker modified {'config/secrets.yaml'} (protected). "
        f"Change summary: {worker_output['summary']}\n\n"
        f"Approve or reject this change?"
    )
    print_section("Question", review_question.strip())

    # Simulate both paths with PlanContract (deterministic demo, no user input)
    print("\n  --- Simulated APPROVE path ---")
    approve_plan = PlanContract(
        plan_id="demo-protected-file-001",
        task_size="medium",
        objective="Update configuration loading in src/main.py and config/secrets.yaml",
        steps=[
            "Read current config structure",
            "Update main.py to load new config",
            "Update secrets.yaml with new keys",
        ],
        required_evidence=["test_output", "diff_patch"],
    )
    try:
        approve_plan.approve()
        print("  Plan approved → execution can continue")
        print(f"  Approval status: {approve_plan.approval_status}")
    except ValueError as exc:
        print(f"  Plan approve blocked: {exc}")

    print("\n  --- Simulated REJECT path ---")
    reject_plan = PlanContract(
        plan_id="demo-protected-file-002",
        task_size="medium",
        objective="Update configuration loading in src/main.py and config/secrets.yaml",
        steps=[
            "Read current config structure",
            "Update main.py",
            "Update secrets.yaml",
        ],
        required_evidence=["test_output", "diff_patch"],
    )
    try:
        reject_plan.reject()
        print("  Plan rejected → execution stopped")
        print("  Reason: Secrets change not justified — use environment variables instead")
        print(f"  Approval status: {reject_plan.approval_status}")
    except ValueError as exc:
        print(f"  Plan reject blocked: {exc}")

    # ------------------------------------------------------------------
    # 6. Recovery — what happens (human must decide)
    # ------------------------------------------------------------------
    print_header("6. Recovery Decision")

    recovery = cp.decide_recovery(
        failure_record,
        attempt_count=0,
        run_mode="controlled",
        task_id="demo-protected-file-001",
        step_name="edit_file",
    )
    print_section("action", recovery.action)
    print_section("reason", recovery.reason)
    print_section("recovery_hint", recovery.recovery_hint)

    print("\n  >>> Protected file changes cannot be auto-retried.")
    print("  >>> Only a human can approve or reject this change.")
    print("  >>> This is NOT a blind retry loop — it's a deliberate gate.")

    # ------------------------------------------------------------------
    # 7. Generate sample outputs
    # ------------------------------------------------------------------
    print_header("7. Sample Outputs Generated")

    # Policy violation record
    fr_path = write_sample_json("sample_failure_record.json", failure_record.to_dict())
    print(f"  Failure Record → {fr_path}")

    # Audit report sample
    audit_md = """\
# Audit Report — demo-protected-file-001

## Evidence
- **test_output**: 5 passed (observed)
- **files_changed**: src/main.py, config/secrets.yaml (observed)
- **commands_run**: read_file, edit_file, run_tests (observed)

## Failure
- **category**: POLICY_ERROR
- **reason**: protected_file_change
- **severity**: high
- **file**: config/secrets.yaml

## Recovery
- **action**: needs_human_review
- **reason**: Protected file changes require explicit human approval

## Status
**BLOCKED** — Waiting for human review decision.
"""
    ar_path = write_sample_text("sample_audit_report.md", audit_md)
    print(f"  Audit Report   → {ar_path}")

    lw_text = """\
AAO Live Watch — demo-protected-file-001
────────────────────────────────────────
  Status:       BLOCKED (needs_human_review)
  Current step: edit_file
  Progress:     2/3 (paused for human review)
  Last decision: needs_human_review — protected file config/secrets.yaml
  Evidence:      test_output [OBSERVED], files_changed [OBSERVED]
  Policy:        config/secrets.yaml is PROTECTED
  Human review:  REQUIRED — approve or reject the secrets change"""
    lw_path = write_sample_text("sample_live_watch.txt", lw_text)
    print(f"  Live Watch     → {lw_path}")

    print_header("Summary")
    print("""
  What happened:
    1. Worker modified config/secrets.yaml (protected file).
    2. Policy engine detected the protected file change.
    3. ControlPlane blocked execution → needs_human_review.
    4. Human review gate shows the question and waits.
    5. Approve → continue execution.  Reject → fail with reason.
    6. No automatic retry loop — policy violations need human judgment.

  Why this matters:
    Without policy enforcement, a worker can silently modify secrets,
    credentials, or environment files.  AAO pauses and asks for human
    review before such changes take effect.
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
