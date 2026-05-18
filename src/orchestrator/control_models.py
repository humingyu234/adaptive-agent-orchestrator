"""Shared control-layer contracts — runner-independent, serializable.

These models define the common language that every runner, worker, and the
ControlPlane speak.  They must stay small, typed, and free of runtime imports.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# =============================================================================
# Task sizing and run mode
# =============================================================================

TaskSize = Literal["small", "medium", "large"]
RunMode = Literal["off", "log", "controlled", "orchestrated"]


# =============================================================================
# Failure origin — where a failure was first observed or reported
# =============================================================================

FailureOrigin = Literal[
    "control_plane",
    "worker",
    "provider",
    "tool",
    "policy",
    "scheduler",
    "unknown",
]


# =============================================================================
# Recovery hint — bounded next action the ControlPlane recommends
# =============================================================================

RecoveryHint = Literal[
    "continue",
    "retry",
    "retry_with_backoff",
    "request_evidence",
    "compress_context",
    "fallback_model_or_provider",
    "replan",
    "needs_human_review",
    "fail",
]


# =============================================================================
# Control action — the decision a ControlPlane can make about a step
# =============================================================================

ControlAction = Literal[
    "continue",
    "retry",
    "replan",
    "rollback",
    "needs_human_review",
    "fail",
]


# =============================================================================
# ControlDecision — outcome of a single control check
# =============================================================================

class ControlDecision(BaseModel):
    """The result of evaluating or guarding one step in a workflow."""

    action: ControlAction = "continue"
    passed: bool = True
    reason: str = ""
    severity: Literal["low", "medium", "high", "critical"] | None = None
    failure_category: str | None = None
    failure_origin: FailureOrigin | None = None
    recovery_hint: RecoveryHint | None = None
    evidence_required: bool = False
    next_step_hint: str | None = None
    guardrail_name: str | None = None
    stage: Literal["input", "output"] | None = None


# =============================================================================
# Worker contracts
# =============================================================================

class WorkerTask(BaseModel):
    """A unit of work dispatched to a worker (agent, tool, or external runner)."""

    task_id: str
    objective: str
    allowed_files: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    mode: RunMode = "controlled"


class WorkerResult(BaseModel):
    """What a worker returns after executing a WorkerTask."""

    task_id: str
    worker_name: str
    status: Literal["completed", "failed", "timed_out", "needs_human_review"]
    output: dict[str, Any] = Field(default_factory=dict)
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    tests_run: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# =============================================================================
# Evidence pack — what was observed during a step
# =============================================================================

class EvidencePack(BaseModel):
    """Structured evidence collected during one workflow step.

    Only include evidence the runtime actually captured.  Do not invent fields.
    Fields that the current runtime does not capture remain empty by default.
    """

    task_id: str
    step_name: str
    status: str = ""
    duration_ms: int = 0
    timestamp: str = ""
    evaluation: dict[str, Any] | None = None
    failure_reason: str = ""
    output_summary: str = ""
    report_path: str = ""
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    test_results: dict[str, Any] = Field(default_factory=dict)
    diff_summary: str = ""
    notes: str = ""
