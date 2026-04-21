"""Core typed models used across the orchestrator runtime."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel


# =============================================================================
# Agent I/O models
# =============================================================================


class SubQuestion(TypedDict):
    """A single planner sub-question."""

    question: str


class PlanOutput(BaseModel):
    """Structured planner output."""

    sub_questions: list[str]
    plan_type: str = "research"
    confidence: float = 0.0
    model_profile: str | None = None
    memory_hints_used: int = 0


class Document(TypedDict):
    """Search document record."""

    title: str
    url: str
    snippet: str
    source_type: str
    tool_name: str


class SummarySection(BaseModel):
    """One section in a structured summary."""

    sub_question: str
    answer: str


class SummaryOutput(BaseModel):
    """Structured summarizer output."""

    conclusion: str
    sections: list[SummarySection] = []
    plan_type: str = "general"
    model_profile: str | None = None


class SupervisorReport(BaseModel):
    """Structured supervisor output."""

    query: str = ""
    next_action: Literal["accept", "revise"] = "accept"
    status: str = "reviewed"
    concerns: list[str] = []
    summary: str = ""
    review_reason: str = ""
    suggested_target: str = "none"
    suggested_action: str = "accept"
    process_review: dict[str, Any] = {}


class HumanReviewGate(BaseModel):
    """Structured human review packet."""

    decision: Literal["await_human", "approved", "rejected"]
    approval_required: bool = True
    status: str = "awaiting_human_review"
    query: str = ""
    review_reason: str = ""
    recommended_target: str = "none"
    recommended_action: str = "accept"
    summary_preview: str = ""
    trace_events_seen: int = 0
    runtime_status_seen: str = ""
    failure_reason_seen: str = ""


# =============================================================================
# Context view model
# =============================================================================


class ContextView(TypedDict, total=False):
    """Context payload exposed to an agent at runtime."""

    query: str
    plan: dict[str, Any]
    raw_documents: list[dict[str, Any]]
    summary: dict[str, Any]
    supervisor_report: dict[str, Any]
    human_review_gate: dict[str, Any]
    execution_trace: list[dict[str, Any]]
    retry_counters: dict[str, int]
    global_step: int
    status: str
    failure_reason: str
    retrieved_memories: list[dict[str, Any]]
    memory_bundle: dict[str, Any]


# =============================================================================
# Runtime config and result models
# =============================================================================


class WriteSpec(BaseModel):
    field: str
    schema_name: str | None = None


class EvalCriteriaItem(BaseModel):
    """One declarative evaluation rule."""

    path: str
    expected_type: Literal["dict", "list", "str", "non_empty_str"] = "dict"
    min_items: int | None = None
    max_items: int | None = None
    allowed_values: set[str] | None = None
    action: Literal["continue", "retry", "re_plan", "fail"] = "fail"
    reason: str = ""


class AgentConfig(BaseModel):
    name: str
    reads: list[str]
    writes: list[WriteSpec]
    tools: list[str] = []
    guardrails: list[str] = []
    eval_criteria: list[EvalCriteriaItem] = []
    model_profile: str = "worker"
    llm_provider: str | None = None
    llm_model: str | None = None
    trust_level: Literal["low", "medium", "high"] = "medium"
    terminal_behavior: Literal["continue", "pause_for_human", "fail"] = "continue"
    max_tokens: int = 4000
    max_retries: int = 3


class EvalCriterion(BaseModel):
    dimension: str
    layer: Literal["L1", "L2", "L3"]
    check: str
    action_on_fail: Literal["retry", "re_plan", "fail", "warn"]


class EvalResult(BaseModel):
    passed: bool
    action: Literal["continue", "retry", "re_plan", "fail"] = "continue"
    reason: str = ""
    level_triggered: Literal["L1", "L2", "L3"] = "L1"


class Checkpoint(BaseModel):
    checkpoint_id: str
    step_id: int
    snapshot: dict[str, Any]
    created_by: str
    reason: str
    timestamp: str


class RunResult(BaseModel):
    task_id: str
    status: Literal["completed", "failed", "timed_out", "needs_human_review"]
    final_node: str | None = None
    reason: str = ""
    failure_reason: str = ""
    completion_reason: str = ""
    state_version: int
    checkpoint_dir: str | None = None
    convergence_report_path: str | None = None
    memory_path: str | None = None
