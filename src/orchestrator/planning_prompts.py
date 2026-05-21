"""Phase 19v2 — Structured-output planning prompts and Pydantic schemas.

Each LLM advisor has a SINGLE responsibility:
- Planner    → decompose tasks, output steps/assumptions/required_context
- Reviewer   → find blocking_concerns / non_blocking_concerns / human_review_gates
- ExecPlanner → generate worker_tasks with concrete file boundaries and checks
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


# =============================================================================
# Pydantic output schemas — single-responsibility contracts
# =============================================================================

class PlannerOutput(BaseModel):
    """Planner: only decompose tasks into bounded execution steps."""
    summary: str
    steps: list[str] = Field(min_length=2, max_length=10)
    risks: list[str] = Field(min_length=1)
    non_goals: list[str] = Field(min_length=2)
    required_evidence: list[str] = Field(min_length=1)
    human_review_gates: list[str]
    assumptions: list[str] = Field(min_length=1)


class ReviewerOutput(BaseModel):
    """Risk Reviewer: only find blocking concerns and review gates."""
    summary: str
    blocking_concerns: list[str]
    non_blocking_concerns: list[str]
    risks: list[str] = Field(min_length=1)
    human_review_gates: list[str]
    required_evidence: list[str]


class WorkerTaskItem(BaseModel):
    """Single worker task — concrete file boundaries, checks, evidence."""
    title: str
    objective: str
    allowed_files: list[str] = Field(min_length=1)
    denied_files: list[str] = []
    required_checks: list[str]
    expected_evidence: list[str] = Field(min_length=1)
    risk_level: Literal["low", "medium", "high"]
    dependencies: list[str] = []
    can_run_parallel: bool = False
    requires_human_review: bool = False

    @field_validator("allowed_files")
    @classmethod
    def files_must_be_specific(cls, v: list[str]) -> list[str]:
        vague = {".", "./", "*", "src/", "src", "all", "everything"}
        for f in v:
            if f.strip().rstrip("/") in vague:
                raise ValueError(f"allowed_files too broad: {f!r}")
        return v


class ExecutionPlannerOutput(BaseModel):
    """Execution Planner: only generate worker_tasks. worker_tasks is MANDATORY."""
    summary: str
    steps: list[str]
    risks: list[str]
    non_goals: list[str]
    required_evidence: list[str]
    human_review_gates: list[str]
    worker_tasks: list[WorkerTaskItem] = Field(min_length=1)


# =============================================================================
# System Prompts — short, single-responsibility (15-20 lines each)
# =============================================================================

PLANNER_SYSTEM_PROMPT: str = """\
You are a Planner. Decompose the user's task into bounded, executable steps.

Output ONLY a JSON object with these fields:
{
  "summary": "<one-sentence summary>",
  "steps": ["<concrete step>", ...],
  "risks": ["<specific risk>", ...],
  "non_goals": ["<explicit boundary>", ...],
  "required_evidence": ["<evidence file>", ...],
  "human_review_gates": ["<when human must approve>", ...],
  "assumptions": ["<what you assume true>", ...]
}

Rules:
- 3-8 concrete steps. "Read X", "Modify Y to Z", "Run pytest on W".
- Code tasks REQUIRE: read file, run tests, collect diff + test_output.
- Analysis tasks: no diff.patch needed, but test_output.txt still required.
- Protected paths (.env, secrets/, credentials.*) → add human_review_gates.
- non_goals >= 2 explicit scope boundaries.
- assumptions: what must already be true for this plan to work.
"""

REVIEWER_SYSTEM_PROMPT: str = """\
You are a Risk Reviewer. Find problems BEFORE execution starts.

Output ONLY a JSON object with these fields:
{
  "summary": "<one-sentence review. Start with BLOCKING: if fatal issues exist>",
  "blocking_concerns": ["<fatal issue — execution must NOT start>", ...],
  "non_blocking_concerns": ["<advisory issue>", ...],
  "risks": ["<specific risk>", ...],
  "human_review_gates": ["<additional gate>", ...],
  "required_evidence": ["<additional evidence needed>", ...]
}

Block if: no file boundaries, missing evidence for code tasks, high-risk without
human gate, protected files in scope, empty required_checks on code task.
Be specific: "Code change with no test_step; required_evidence is empty" not "Missing tests".
If plan is safe: blocking_concerns MUST be [].
"""

EXECUTION_PLANNER_SYSTEM_PROMPT: str = """\
You are an Execution Planner. Turn a reviewed plan into worker_tasks.

Output ONLY a JSON object with these fields:
{
  "summary": "<one-sentence execution summary>",
  "steps": ["<execution step>", ...],
  "risks": ["<execution risk>", ...],
  "non_goals": ["<execution boundary>", ...],
  "required_evidence": ["<evidence file>", ...],
  "human_review_gates": ["<review gate>", ...],
  "worker_tasks": [
    {
      "title": "<short title>",
      "objective": "<what the worker accomplishes>",
      "allowed_files": ["<specific file path>", ...],
      "denied_files": ["<must-not-touch file>", ...],
      "required_checks": ["<exact command e.g. pytest>", ...],
      "expected_evidence": ["<observable output file>", ...],
      "risk_level": "low|medium|high",
      "dependencies": ["<step_id>", ...],
      "can_run_parallel": true|false,
      "requires_human_review": true|false
    }
  ]
}

worker_tasks is MANDATORY and non-empty. Each task:
- allowed_files: specific paths, never ["."] or ["src/"].
- Code tasks: required_checks non-empty, expected_evidence includes test_output.txt + diff.patch.
- Analysis tasks: diff.patch NOT required, required_checks may be empty.
- Protected files → denied_files or requires_human_review: true.
- can_run_parallel: true only when no file overlap with other tasks.
- Address Reviewer blocking_concerns: missing test → add pytest, no boundaries → add files.
"""

# =============================================================================
# Pydantic validation with error formatting (for retry correction prompts)
# =============================================================================


def validate_planner_pydantic(data: dict[str, Any]) -> list[str]:
    """Validate Planner output with Pydantic. Returns list of error strings."""
    try:
        PlannerOutput.model_validate(data)
        return []
    except ValidationError as e:
        return [_format_validation_error(err) for err in e.errors()]


def validate_reviewer_pydantic(data: dict[str, Any]) -> list[str]:
    """Validate Reviewer output with Pydantic. Returns list of error strings."""
    try:
        ReviewerOutput.model_validate(data)
        return []
    except ValidationError as e:
        return [_format_validation_error(err) for err in e.errors()]


def validate_execution_planner_pydantic(data: dict[str, Any]) -> list[str]:
    """Validate Execution Planner output with Pydantic. Returns list of error strings."""
    try:
        ExecutionPlannerOutput.model_validate(data)
        return []
    except ValidationError as e:
        return [_format_validation_error(err) for err in e.errors()]


def _format_validation_error(err: dict[str, Any]) -> str:
    """Convert a Pydantic error dict into a human-readable correction hint."""
    loc = " -> ".join(str(p) for p in err.get("loc", []))
    msg = err.get("msg", "unknown error")
    etype = err.get("type", "")
    if etype == "missing":
        return f"MISSING FIELD: '{loc}' is required but was not present in your output."
    if etype in ("string_type", "list_type", "dict_type", "bool_type", "literal_error"):
        return f"WRONG TYPE: '{loc}' — {msg}."
    if etype == "value_error":
        return f"INVALID VALUE: '{loc}' — {msg}."
    return f"VALIDATION ERROR at '{loc}': {msg}"


# =============================================================================
# Prompt Builders
# =============================================================================


def _to_dict(obj: Any) -> dict[str, Any] | None:
    """Normalise PlanCandidate-like or dict to dict.  Returns None for None input."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    # PlanCandidate-like: has attributes
    return {
        "summary": getattr(obj, "summary", ""),
        "steps": getattr(obj, "steps", []),
        "risks": getattr(obj, "risks", []),
        "non_goals": getattr(obj, "non_goals", []),
        "required_evidence": getattr(obj, "required_evidence", []),
        "human_review_gates": getattr(obj, "human_review_gates", []),
        "blocking_concerns": getattr(obj, "blocking_concerns", []),
        "non_blocking_concerns": getattr(obj, "non_blocking_concerns", []),
    }


def build_planner_prompt(
    query: str,
    task_size: str = "medium",
    run_mode: str = "controlled",
    risk_level: str = "medium",
    task_type: str = "unknown",
) -> str:
    """Build the full prompt for the Planner advisor."""
    return (
        f"TASK: {query}\n"
        f"TASK SIZE: {task_size}\n"
        f"RUN MODE: {run_mode}\n"
        f"RISK LEVEL: {risk_level}\n"
        f"TASK TYPE: {task_type}\n"
        f"\nProduce the JSON plan now."
    )


def build_reviewer_prompt(
    query: str,
    task_size: str = "medium",
    run_mode: str = "controlled",
    risk_level: str = "medium",
    planner_output: dict[str, Any] | None = None,
    task_type: str = "unknown",
) -> str:
    """Build the full prompt for the Risk Reviewer advisor, including planner output."""
    base = build_planner_prompt(query, task_size, run_mode, risk_level, task_type)
    planner_dict = _to_dict(planner_output)
    if planner_dict:
        base += (
            f"\nPLANNER'S PROPOSED PLAN:\n"
            f"  Summary: {planner_dict.get('summary', 'N/A')}\n"
            f"  Steps: {json.dumps(planner_dict.get('steps', []))}\n"
            f"  Risks: {json.dumps(planner_dict.get('risks', []))}\n"
            f"  Required Evidence: {json.dumps(planner_dict.get('required_evidence', []))}\n"
            f"  Human Review Gates: {json.dumps(planner_dict.get('human_review_gates', []))}\n"
            f"  Non-Goals: {json.dumps(planner_dict.get('non_goals', []))}\n"
        )
    base += "\nReview the plan and produce your JSON critique now."
    return base


def build_execution_planner_prompt(
    query: str,
    task_size: str = "medium",
    run_mode: str = "controlled",
    risk_level: str = "medium",
    planner_output: dict[str, Any] | None = None,
    reviewer_output: dict[str, Any] | None = None,
    task_type: str = "unknown",
) -> str:
    """Build the full prompt for the Execution Planner, including both prior outputs."""
    base = build_planner_prompt(query, task_size, run_mode, risk_level, task_type)
    planner_dict = _to_dict(planner_output)
    reviewer_dict = _to_dict(reviewer_output)

    if planner_dict:
        base += (
            f"\nPLANNER'S PLAN:\n"
            f"  Steps: {json.dumps(planner_dict.get('steps', []))}\n"
            f"  Evidence: {json.dumps(planner_dict.get('required_evidence', []))}\n"
            f"  Review Gates: {json.dumps(planner_dict.get('human_review_gates', []))}\n"
        )
    if reviewer_dict:
        blocking = reviewer_dict.get("blocking_concerns", [])
        non_blocking = reviewer_dict.get("non_blocking_concerns", [])
        if blocking:
            base += f"\nREVIEWER BLOCKING CONCERNS (MUST BE ADDRESSED): {json.dumps(blocking)}\n"
        if non_blocking:
            base += f"\nReviewer non-blocking: {json.dumps(non_blocking)}\n"
        if reviewer_dict.get("human_review_gates"):
            base += f"\nReviewer requires gates: {json.dumps(reviewer_dict['human_review_gates'])}\n"
        if reviewer_dict.get("required_evidence"):
            base += f"\nReviewer requires additional evidence: {json.dumps(reviewer_dict['required_evidence'])}\n"
    base += "\nProduce the execution plan with worker_tasks now."
    return base


# =============================================================================
# Prompt Quality Validators
# =============================================================================


def validate_planner_output(data: dict[str, Any]) -> list[str]:
    """Validate Planner JSON output. Returns list of error messages (empty = valid)."""
    errors: list[str] = []

    # Required fields
    for field in ("summary", "steps", "risks", "non_goals", "required_evidence",
                  "human_review_gates", "assumptions"):
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if "steps" in data:
        steps = data["steps"]
        if not isinstance(steps, list) or len(steps) < 2:
            errors.append(f"steps must be a list with at least 2 items, got {len(steps) if isinstance(steps, list) else type(steps).__name__}")
        elif len(steps) > 10:
            errors.append(f"steps has {len(steps)} items — exceeds max 10; task should be split")
        else:
            # Check for vague steps
            vague_words = ("do the work", "fix it", "improve things", "do stuff",
                          "make it better", "clean up")
            for i, step in enumerate(steps):
                if isinstance(step, str) and step.lower().strip() in vague_words:
                    errors.append(f"Step {i+1} is too vague: '{step}'")

    if "risks" in data and isinstance(data["risks"], list) and len(data["risks"]) == 0:
        errors.append("risks is empty — every plan has at least one risk")

    if "non_goals" in data:
        ng = data["non_goals"]
        if isinstance(ng, list) and len(ng) < 2:
            errors.append(f"non_goals must have at least 2 boundaries, got {len(ng)}")

    if "required_evidence" in data:
        ev = data["required_evidence"]
        if isinstance(ev, list) and len(ev) == 0:
            errors.append("required_evidence is empty")

    if "assumptions" in data:
        asm = data["assumptions"]
        if isinstance(asm, list) and len(asm) == 0:
            errors.append("assumptions is empty — state what the plan assumes")

    return errors


def validate_reviewer_output(data: dict[str, Any]) -> list[str]:
    """Validate Risk Reviewer JSON output. Returns list of error messages."""
    errors: list[str] = []

    for field in ("summary", "blocking_concerns", "non_blocking_concerns",
                  "risks", "human_review_gates", "required_evidence"):
        if field not in data:
            errors.append(f"Missing required field: {field}")

    # Check for generic blocking concerns
    if "blocking_concerns" in data:
        bc = data["blocking_concerns"]
        if isinstance(bc, list):
            generic_phrases = ("missing tests", "no evidence", "not safe", "bad plan",
                             "needs review", "incomplete", "fix it", "missing things",
                             "not enough", "could be better", "add more")
            for concern in bc:
                if isinstance(concern, str) and concern.lower().strip() in generic_phrases:
                    errors.append(f"Blocking concern is too generic: '{concern}'")

    if "risks" in data:
        risks = data["risks"]
        if isinstance(risks, list):
            generic_risks = ("might fail", "could break", "unknown risk", "maybe problems")
            for risk in risks:
                if isinstance(risk, str) and risk.lower().strip() in generic_risks:
                    errors.append(f"Risk is too generic: '{risk}'")

    return errors


def validate_execution_planner_output(data: dict[str, Any]) -> list[str]:
    """Validate Execution Planner JSON output. Returns list of error messages.

    This is the most critical validator — worker_tasks must be executable.
    """
    errors: list[str] = []

    for field in ("summary", "steps", "risks", "non_goals", "required_evidence",
                  "human_review_gates", "worker_tasks"):
        if field not in data:
            errors.append(f"Missing required field: {field}")

    # worker_tasks validation
    worker_tasks = data.get("worker_tasks", [])
    if not isinstance(worker_tasks, list) or len(worker_tasks) == 0:
        errors.append("worker_tasks is empty or not a list — at least 1 task required")
        return errors  # can't validate further

    for i, wt in enumerate(worker_tasks):
        if not isinstance(wt, dict):
            errors.append(f"worker_task[{i}] is not a dict")
            continue

        prefix = f"worker_task[{i}]"

        # Required fields in each worker task
        for req in ("title", "objective", "allowed_files", "required_checks",
                    "expected_evidence", "risk_level"):
            if req not in wt:
                errors.append(f"{prefix}: missing required field '{req}'")

        # allowed_files must be non-empty and specific
        af = wt.get("allowed_files", [])
        if isinstance(af, list):
            if len(af) == 0:
                errors.append(f"{prefix}: allowed_files is empty — must specify file boundaries")
            else:
                vague_af = {".", "./", "*", "src/", "src", "all", "everything"}
                if any(str(f).strip().rstrip("/") in vague_af for f in af):
                    errors.append(f"{prefix}: allowed_files too broad: {af}")

        # required_checks for code-changing tasks
        rc = wt.get("required_checks", [])
        risk = str(wt.get("risk_level", "low")).lower()

        # Check if this appears to be a code-changing task
        obj = str(wt.get("objective", "")).lower()
        is_code_task = any(kw in obj for kw in
                          ("modify", "fix", "refactor", "implement", "add", "change",
                           "write", "edit", "update", "create", "remove", "delete"))

        if is_code_task and isinstance(rc, list) and len(rc) == 0:
            errors.append(f"{prefix}: code-changing task has empty required_checks")

        # expected_evidence must be non-empty
        ee = wt.get("expected_evidence", [])
        if isinstance(ee, list) and len(ee) == 0:
            errors.append(f"{prefix}: expected_evidence is empty")

        # risk_level must be valid
        if risk not in ("low", "medium", "high"):
            errors.append(f"{prefix}: invalid risk_level '{wt.get('risk_level')}' — must be low/medium/high")

        # Protected file check
        protected_patterns = (
            ".env", "config/secrets.yaml", "secrets/", "outputs/", "credentials.",
            "secret", "token", "key",
        )
        for f in af:
            f_str = str(f)
            if any(p in f_str for p in protected_patterns):
                requires_review = bool(wt.get("requires_human_review", False))
                if not requires_review:
                    errors.append(
                        f"{prefix}: allowed_files contains protected path '{f_str}' "
                        f"but requires_human_review is not set"
                    )
                break

        # dependencies must be a list of strings
        deps = wt.get("dependencies", [])
        if isinstance(deps, list):
            for d in deps:
                if not isinstance(d, str):
                    errors.append(f"{prefix}: dependency {d!r} is not a string")

        # can_run_parallel must be boolean
        crp = wt.get("can_run_parallel")
        if crp is not None and not isinstance(crp, bool):
            errors.append(f"{prefix}: can_run_parallel must be boolean, got {type(crp).__name__}")

    # Overall evidence rules
    has_code_task = any(
        any(kw in str(wt.get("objective", "")).lower() for kw in
            ("modify", "fix", "refactor", "implement", "add", "change",
             "write", "edit", "update", "create", "remove", "delete"))
        for wt in worker_tasks if isinstance(wt, dict)
    )
    if has_code_task:
        re = data.get("required_evidence", [])
        if isinstance(re, list):
            re_strs = [str(e) for e in re]
            if "diff.patch" not in re_strs:
                errors.append("Code-changing task but diff.patch not in required_evidence")
            if "test_output.txt" not in re_strs:
                errors.append("Code-changing task but test_output.txt not in required_evidence")

    return errors


# =============================================================================
# Prompt version tracking
# =============================================================================

PROMPT_VERSION = "3.0.0"
PROMPT_DATE = "2026-05-21"

PROMPT_MANIFEST = {
    "version": PROMPT_VERSION,
    "date": PROMPT_DATE,
    "roles": ["planner", "risk_reviewer", "execution_planner"],
    "rules_version": "3",
    "changes_v3": [
        "Added Pydantic output schemas: PlannerOutput, ReviewerOutput, WorkerTaskItem, ExecutionPlannerOutput",
        "Simplified prompts from ~80 lines to ~15-20 lines each (single-responsibility)",
        "Added Pydantic-based validators for structured retry correction prompts",
        "WorkerTaskItem uses Literal['low','medium','high'] for risk_level",
        "Added @field_validator on allowed_files to reject broad patterns",
        "Added _format_validation_error() for human-readable correction hints",
    ],
}
