"""Auto-repair loop — bounded fix-dispatch-verify cycle.

Phase 22: When a worker step fails or a reviewer flags a blocking
finding, AAO generates a scoped FixTask, dispatches it to a worker,
re-verifies, and repeats up to max_attempts.  If all attempts are
exhausted the step enters human review.

Not blind retry, not freeform debugging — a bounded repair loop with
a single file target and a single verification check per FixTask.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

# =============================================================================
# Models
# =============================================================================

FindingSeverity = Literal["blocking", "non_blocking", "info"]
FindingSource = Literal["reviewer", "control_plane", "evaluator"]
FixTaskStatus = Literal["pending", "in_progress", "fixed", "still_failing"]
RepairStatus = Literal["fixed", "still_failing", "blocked_needs_review"]


@dataclass
class ReviewFinding:
    """A single issue discovered by a reviewer, ControlPlane, or evaluator.

    Only *blocking* findings trigger a FixTask.  *non_blocking* and *info*
    findings are recorded but do not start the repair loop.
    """

    finding_id: str
    step_id: str
    severity: FindingSeverity
    category: str
    description: str
    location: str = ""
    suggested_fix: str | None = None
    source: FindingSource = "control_plane"

    @classmethod
    def from_control_decision(
        cls,
        step_id: str,
        reason: str,
        *,
        category: str = "evaluation_failed",
        location: str = "",
        suggested_fix: str | None = None,
        source: FindingSource = "control_plane",
    ) -> ReviewFinding:
        return cls(
            finding_id=f"F-{uuid.uuid4().hex[:8]}",
            step_id=step_id,
            severity="blocking",
            category=category,
            description=reason,
            location=location,
            suggested_fix=suggested_fix,
            source=source,
        )

    @property
    def is_blocking(self) -> bool:
        return self.severity == "blocking"

    @property
    def is_system_issue(self) -> bool:
        return self.category.startswith("system_")


@dataclass
class FixTask:
    """A bounded repair task scoped to exactly one file and one verification.

    Generated from a blocking ReviewFinding.  The worker receives this
    as its objective and must stay within the single target file.
    """

    fix_id: str
    triggered_by_finding_id: str
    step_id: str
    target_file: str
    fix_description: str
    verification: str
    max_attempts: int = 2
    current_attempt: int = 0
    status: FixTaskStatus = "pending"

    @classmethod
    def from_finding(
        cls,
        finding: ReviewFinding,
        *,
        target_file: str = "",
        verification: str = "",
    ) -> FixTask:
        return cls(
            fix_id=f"FT-{uuid.uuid4().hex[:8]}",
            triggered_by_finding_id=finding.finding_id,
            step_id=finding.step_id,
            target_file=target_file or finding.location or "unknown",
            fix_description=finding.suggested_fix or finding.description,
            verification=verification or "pytest",
        )


@dataclass
class RepairRound:
    """Audit record for one round of the repair loop."""

    repair_round: int
    finding_id: str
    finding: str
    fix_task_id: str
    fix_description: str
    worker_result: dict[str, Any]
    retest_result: str
    rereview_result: str
    status: str  # "fixed" | "still_failing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "repair_round": self.repair_round,
            "finding_id": self.finding_id,
            "finding": self.finding,
            "fix_task_id": self.fix_task_id,
            "fix_description": self.fix_description,
            "worker_result": self.worker_result,
            "retest_result": self.retest_result,
            "rereview_result": self.rereview_result,
            "status": self.status,
        }


@dataclass
class RepairResult:
    """Outcome of the full repair loop for one step."""

    status: RepairStatus
    step_id: str
    total_rounds: int
    rounds: list[RepairRound] = field(default_factory=list)
    final_finding: ReviewFinding | None = None

    @property
    def is_fixed(self) -> bool:
        return self.status == "fixed"


# =============================================================================
# AutoRepairLoop
# =============================================================================

# Callback signatures used by the repair loop.  The caller (MainlineExecutor)
# provides concrete implementations that know about worker dispatch and
# control-plane verification.
DispatchFn = Callable[[FixTask], dict[str, Any]]
"""Given a FixTask, execute it and return the worker result dict."""

VerifyFn = Callable[[dict[str, Any]], bool]
"""Given a worker result dict, return True if the fix passed verification."""


class AutoRepairLoop:
    """Bounded auto-repair: detect failure → generate FixTask → dispatch →
    verify → repeat (max 2 rounds) → escalate to human review on exhaustion.

    The loop does NOT own worker dispatch or policy checks — those are
    injected via *dispatch_fn* and *verify_fn* so this class stays
    runner-agnostic.
    """

    def __init__(self, *, max_attempts: int = 2) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._max_attempts = max_attempts
        # Per-step attempt counter.  Reset across different steps.
        self._attempts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attempt_repair(
        self,
        finding: ReviewFinding,
        *,
        dispatch_fn: DispatchFn,
        verify_fn: VerifyFn,
        target_file: str = "",
        verification: str = "",
    ) -> RepairResult:
        """Run the repair loop for *finding*.

        Returns RepairResult.fixed if any round passes verification.
        Returns RepairResult.blocked_needs_review if all attempts exhausted.
        """
        # Gate: only blocking findings trigger repair
        if not finding.is_blocking:
            return RepairResult(
                status="still_failing",
                step_id=finding.step_id,
                total_rounds=0,
                final_finding=finding,
            )

        # Gate: system issues go through Phase 27, not ordinary FixTask
        if finding.is_system_issue:
            return RepairResult(
                status="blocked_needs_review",
                step_id=finding.step_id,
                total_rounds=0,
                final_finding=finding,
            )

        step_id = finding.step_id
        rounds: list[RepairRound] = []

        for round_num in range(1, self._max_attempts + 1):
            # Build a fresh FixTask for each round (the fix angle may differ)
            fix_task = FixTask.from_finding(
                finding,
                target_file=target_file,
                verification=verification,
            )
            fix_task.current_attempt = round_num
            fix_task.status = "in_progress"

            # Dispatch the FixTask to the worker
            worker_result = dispatch_fn(fix_task)

            # Verify the fix
            passed = verify_fn(worker_result)

            self._attempts[step_id] = round_num

            audit_round = RepairRound(
                repair_round=round_num,
                finding_id=finding.finding_id,
                finding=finding.description,
                fix_task_id=fix_task.fix_id,
                fix_description=fix_task.fix_description,
                worker_result=worker_result,
                retest_result="passed" if passed else "failed",
                rereview_result="no blocking findings" if passed else "still failing",
                status="fixed" if passed else "still_failing",
            )
            rounds.append(audit_round)

            if passed:
                fix_task.status = "fixed"
                return RepairResult(
                    status="fixed",
                    step_id=step_id,
                    total_rounds=round_num,
                    rounds=rounds,
                )

            fix_task.status = "still_failing"

        # All attempts exhausted
        return RepairResult(
            status="blocked_needs_review",
            step_id=step_id,
            total_rounds=self._max_attempts,
            rounds=rounds,
            final_finding=finding,
        )

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def attempts_for(self, step_id: str) -> int:
        """Return how many repair attempts have been made for *step_id*."""
        return self._attempts.get(step_id, 0)

    def reset(self, step_id: str) -> None:
        """Reset attempt counter for *step_id*."""
        self._attempts.pop(step_id, None)

    @property
    def max_attempts(self) -> int:
        return self._max_attempts
