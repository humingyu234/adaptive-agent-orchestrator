#!/usr/bin/env python3
"""Demo A — Missing Evidence Block.

Story:
    Worker says the task is complete, but there is no observed test output.
    AAO refuses to mark the run as successful.

Value:
    Prevents "AI says done" from becoming false completion.

What it shows:
    - fake worker output (status=completed, no test_output, no files_changed)
    - evidence status (all items missing)
    - ControlPlane decision (blocked → needs_human_review)
    - failure category (TASK_QUALITY_ERROR / missing_evidence)
    - recovery action (request_evidence)
    - generated sample outputs (evidence pack, failure record)

Run:
    python scripts/demo/missing_evidence.py
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
    FailureRecord,
    FailureSeverity,
    create_failure_record,
)
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
    banner("AAO Demo A — Missing Evidence Block")

    # ------------------------------------------------------------------
    # 1. Build the policy (controlled mode, evidence required)
    # ------------------------------------------------------------------
    print_header("1. Policy Configuration")
    policy = Policy.from_dict({
        "mode": "controlled",
        "checks": {
            "required": ["pytest"],
        },
    })
    print_section("Run mode", policy.mode)
    print_section("Required checks", policy.get_required_checks())

    # ------------------------------------------------------------------
    # 2. Fake worker output — claims completion but provides nothing observable
    # ------------------------------------------------------------------
    print_header("2. Worker Output (fake, deterministic)")

    worker_output = {
        "status": "completed",
        "test_output": "",
        "files_changed": [],
        "tools_called": [],
        "errors": [],
        "summary": "I think I fixed it but didn't run tests",
    }
    print_section("status", worker_output["status"])
    print_section("test_output", worker_output["test_output"] or "(empty)")
    print_section("files_changed", worker_output["files_changed"] or "(none)")
    print_section("summary", worker_output["summary"])

    # ------------------------------------------------------------------
    # 3. Build evidence status — all items MISSING
    # ------------------------------------------------------------------
    print_header("3. Evidence Status")

    evidence_items = [
        WorkerEvidenceItem(
            key="test_output",
            status="missing",
            path="test_results.json",
            description="Captured pytest output",
        ),
        WorkerEvidenceItem(
            key="files_changed",
            status="missing",
            path="diff.patch",
            description="Unified diff of all changed files",
        ),
        WorkerEvidenceItem(
            key="commands_run",
            status="missing",
            path="commands.log",
            description="Shell commands executed during the task",
        ),
    ]

    evidence_status = WorkerEvidenceStatus(
        task_id="demo-missing-evidence-001",
        worker_kind="claude_code",
        worker_status="completed",
        items=evidence_items,
        reported_summary=worker_output["summary"],
        changed_files=[],
    )

    for item in evidence_items:
        icon = "OBSERVED" if item.status == "observed" else "MISSING"
        print(f"  [{icon}] {item.key:20s}  ({item.description})")
    print(f"\n  All observed: {not evidence_status.has_missing_required}")

    # ------------------------------------------------------------------
    # 4. ControlPlane verifies evidence — EXPECTED TO BLOCK
    # ------------------------------------------------------------------
    print_header("4. ControlPlane Decision")

    cp = ControlPlane(policy=policy)
    decision = cp.verify_worker_evidence(evidence_status)
    print_decision(decision.model_dump())

    if not decision.passed:
        print("\n  >>> AAO BLOCKED: Evidence is missing — cannot mark task as successful.")
        print("  >>> Without observed test output, \"I fixed it\" is just a claim.")

    # ------------------------------------------------------------------
    # 5. Failure classification
    # ------------------------------------------------------------------
    print_header("5. Failure Classification")

    failure_record = create_failure_record(
        category=FailureCategory.TASK_QUALITY_ERROR,
        origin="control_plane",
        reason="missing_evidence",
        agent_name="demo_worker",
        severity=FailureSeverity.HIGH,
        recovery_hint="request_evidence",
    )
    print_section("category", failure_record.category.value)
    print_section("reason", failure_record.reason)
    print_section("severity", failure_record.severity.value)
    print_section("recovery_hint", failure_record.recovery_hint)

    # ------------------------------------------------------------------
    # 6. Recovery decision
    # ------------------------------------------------------------------
    print_header("6. Recovery Decision")

    recovery = cp.decide_recovery(
        failure_record,
        attempt_count=0,
        run_mode="controlled",
        task_id="demo-missing-evidence-001",
        step_name="code_change",
    )
    print_section("action", recovery.action)
    print_section("reason", recovery.reason)
    print_section("attempt_count", str(recovery.attempt_count))
    print_section("max_attempts", str(recovery.max_attempts))

    print("\n  >>> Recovery is bounded: after max_attempts, action changes to replan or fail.")
    print("  >>> No infinite retry loop.")

    # ------------------------------------------------------------------
    # 7. Generate sample outputs
    # ------------------------------------------------------------------
    print_header("7. Sample Outputs Generated")

    evidence_pack = {
        "task_id": "demo-missing-evidence-001",
        "step_name": "code_change",
        "worker_status": "completed",
        "evidence_status": "all_missing",
        "test_results": None,
        "files_changed": [],
        "commands_run": [],
        "control_decision": decision.model_dump(),
    }
    ep_path = write_sample_json("sample_evidence_pack.json", evidence_pack)
    print(f"  Evidence Pack  → {ep_path}")

    fr_path = write_sample_json("sample_failure_record.json", failure_record.to_dict())
    print(f"  Failure Record → {fr_path}")

    rd_data = {
        "action": recovery.action,
        "reason": recovery.reason,
        "attempt_count": recovery.attempt_count,
        "max_attempts": recovery.max_attempts,
        "recovery_hint": recovery.recovery_hint,
    }
    rc_path = write_sample_json("sample_recovery_decision.json", rd_data)
    print(f"  Recovery Decision → {rc_path}")

    # Live watch sample
    lw_text = """\
AAO Live Watch — demo-missing-evidence-001
──────────────────────────────────────────
  Status:       BLOCKED (needs_human_review)
  Current step: code_change
  Progress:     1/1 (worker completed but no evidence)
  Last decision: needs_human_review — missing required observed evidence
  Evidence:      test_output [MISSING], files_changed [MISSING]
  Human review:  required — worker claims success but cannot prove it"""
    lw_path = write_sample_text("sample_live_watch.txt", lw_text)
    print(f"  Live Watch     → {lw_path}")

    print_header("Summary")
    print("""
  What happened:
    1. Worker reported "completed" with a natural-language summary.
    2. AAO checked for observed evidence — test output, file changes, commands.
    3. All evidence items were MISSING.
    4. ControlPlane blocked success → needs_human_review.
    5. Failure classified as TASK_QUALITY_ERROR / missing_evidence.
    6. Recovery suggested: request_evidence (bounded, no infinite retry).

  Why this matters:
    Without evidence verification, an AI worker can say "done" and the
    orchestrator will mark the task as successful.  AAO prevents this
    by requiring observed evidence — not reported claims.
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
