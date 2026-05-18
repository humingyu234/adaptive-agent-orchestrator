"""Failure taxonomy with four-layer structure.

Layers:
  origin   — where the failure was first observed or reported
  category — broad failure family
  reason   — concrete machine-readable cause
  recovery — bounded next action

ControlPlane does not directly call LLM providers.  Provider/API failures are
reported by a worker or provider layer and classified here.  ControlPlane-
originated failures come from control decisions (evaluator, guardrails, policy).

Attribution:
  Provider error pattern lists are adapted from Hermes Agent (MIT):
    NousResearch/hermes-agent/agent/error_classifier.py
"""

from __future__ import annotations

import random
import threading
import time
from enum import Enum
from typing import Any

from .control_models import FailureOrigin, RecoveryHint


# =============================================================================
# Failure category — broad failure family
# =============================================================================

class FailureCategory(str, Enum):
    """Broad failure family."""

    PROVIDER_ERROR = "provider_error"
    TASK_QUALITY_ERROR = "task_quality_error"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    TOOL_ERROR = "tool_error"
    POLICY_ERROR = "policy_error"
    UNKNOWN = "unknown"


# =============================================================================
# Failure reason — concrete machine-readable cause
# =============================================================================

class FailureReason(str, Enum):
    """Concrete machine-readable cause within a failure category."""

    # Provider reasons
    AUTH = "auth"
    AUTH_PERMANENT = "auth_permanent"
    BILLING = "billing"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    OVERLOADED = "overloaded"
    SERVER_ERROR = "server_error"
    CONTEXT_OVERFLOW = "context_overflow"
    MODEL_NOT_FOUND = "model_not_found"
    FORMAT_ERROR = "format_error"

    # Task quality reasons
    EVALUATION_FAILED = "evaluation_failed"
    LOW_QUALITY_OUTPUT = "low_quality_output"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    MISSING_EVIDENCE = "missing_evidence"

    # Guardrail reasons
    INPUT_GUARDRAIL_BLOCKED = "input_guardrail_blocked"
    OUTPUT_GUARDRAIL_BLOCKED = "output_guardrail_blocked"
    SENSITIVE_CONTENT = "sensitive_content"
    PROTECTED_ACTION = "protected_action"

    # Tool reasons
    TOOL_FAILED = "tool_failed"
    EXACT_REPEATED_TOOL_FAILURE = "exact_repeated_tool_failure"
    SAME_TOOL_REPEATED_FAILURE = "same_tool_repeated_failure"
    IDEMPOTENT_NO_PROGRESS = "idempotent_no_progress"

    # Policy reasons
    PROTECTED_FILE_CHANGE = "protected_file_change"
    HIGH_RISK_TOOL = "high_risk_tool"
    REVIEWER_WRITE_ATTEMPT = "reviewer_write_attempt"
    MISSING_REQUIRED_CHECK = "missing_required_check"

    # Fallback
    UNKNOWN = "unknown"


# =============================================================================
# Recovery hint guidance (human-readable)
# =============================================================================

RECOVERY_HINT_GUIDANCE: dict[RecoveryHint, str] = {
    "continue": "Step passed; proceed normally.",
    "retry": "Retry the step with a bounded limit.",
    "retry_with_backoff": "Wait with jittered backoff, then retry.",
    "request_evidence": "Ask the worker to provide missing evidence.",
    "compress_context": "Context too large; compress and retry with a smaller payload.",
    "fallback_model_or_provider": "Switch to a fallback model or provider route if available.",
    "replan": "Replan the step with a different strategy.",
    "needs_human_review": "Pause and request human review.",
    "fail": "Stop the task; recovery is not possible.",
}


# =============================================================================
# Failure severity
# =============================================================================

class FailureSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# =============================================================================
# Default severity map (reason -> severity)
# =============================================================================

_DEFAULT_REASON_SEVERITY: dict[FailureReason, FailureSeverity] = {
    # Provider — transient
    FailureReason.RATE_LIMIT: FailureSeverity.LOW,
    FailureReason.TIMEOUT: FailureSeverity.LOW,
    FailureReason.OVERLOADED: FailureSeverity.LOW,
    FailureReason.SERVER_ERROR: FailureSeverity.LOW,
    # Provider — hard
    FailureReason.AUTH: FailureSeverity.HIGH,
    FailureReason.AUTH_PERMANENT: FailureSeverity.CRITICAL,
    FailureReason.BILLING: FailureSeverity.HIGH,
    FailureReason.CONTEXT_OVERFLOW: FailureSeverity.LOW,
    FailureReason.MODEL_NOT_FOUND: FailureSeverity.HIGH,
    FailureReason.FORMAT_ERROR: FailureSeverity.HIGH,
    # Quality
    FailureReason.EVALUATION_FAILED: FailureSeverity.MEDIUM,
    FailureReason.LOW_QUALITY_OUTPUT: FailureSeverity.MEDIUM,
    FailureReason.MISSING_REQUIRED_FIELD: FailureSeverity.MEDIUM,
    FailureReason.MISSING_EVIDENCE: FailureSeverity.MEDIUM,
    # Guardrail
    FailureReason.INPUT_GUARDRAIL_BLOCKED: FailureSeverity.HIGH,
    FailureReason.OUTPUT_GUARDRAIL_BLOCKED: FailureSeverity.HIGH,
    FailureReason.SENSITIVE_CONTENT: FailureSeverity.HIGH,
    FailureReason.PROTECTED_ACTION: FailureSeverity.HIGH,
    # Tool
    FailureReason.TOOL_FAILED: FailureSeverity.MEDIUM,
    FailureReason.EXACT_REPEATED_TOOL_FAILURE: FailureSeverity.MEDIUM,
    FailureReason.SAME_TOOL_REPEATED_FAILURE: FailureSeverity.MEDIUM,
    FailureReason.IDEMPOTENT_NO_PROGRESS: FailureSeverity.MEDIUM,
    # Policy
    FailureReason.PROTECTED_FILE_CHANGE: FailureSeverity.HIGH,
    FailureReason.HIGH_RISK_TOOL: FailureSeverity.HIGH,
    FailureReason.REVIEWER_WRITE_ATTEMPT: FailureSeverity.CRITICAL,
    FailureReason.MISSING_REQUIRED_CHECK: FailureSeverity.MEDIUM,
    # Fallback
    FailureReason.UNKNOWN: FailureSeverity.MEDIUM,
}


# =============================================================================
# Recovery action mapping (reason -> hint)
# =============================================================================
# A recovery hint is NOT the same thing as implemented runtime capability.
# fallback_model_or_provider means "safe to solve by provider fallback IF such
# a route exists."  If AAO does not yet have provider fallback wired, return
# the hint clearly but do not pretend the runtime actually switched providers.

RECOVERY_HINT_MAP: dict[FailureReason, RecoveryHint] = {
    # Transient provider -> retry with backoff
    FailureReason.RATE_LIMIT: "retry_with_backoff",
    FailureReason.TIMEOUT: "retry_with_backoff",
    FailureReason.OVERLOADED: "retry_with_backoff",
    FailureReason.SERVER_ERROR: "retry_with_backoff",
    # Context -> compress
    FailureReason.CONTEXT_OVERFLOW: "compress_context",
    # Model / routing
    FailureReason.MODEL_NOT_FOUND: "fallback_model_or_provider",
    FailureReason.AUTH: "fallback_model_or_provider",
    # Hard failures -> do NOT retry
    FailureReason.AUTH_PERMANENT: "fail",
    FailureReason.BILLING: "fail",
    FailureReason.FORMAT_ERROR: "fail",
    # Quality
    FailureReason.EVALUATION_FAILED: "retry",
    FailureReason.LOW_QUALITY_OUTPUT: "retry",
    FailureReason.MISSING_REQUIRED_FIELD: "retry",
    FailureReason.MISSING_EVIDENCE: "request_evidence",
    # Guardrail -> do NOT retry
    FailureReason.INPUT_GUARDRAIL_BLOCKED: "fail",
    FailureReason.OUTPUT_GUARDRAIL_BLOCKED: "fail",
    FailureReason.SENSITIVE_CONTENT: "fail",
    FailureReason.PROTECTED_ACTION: "needs_human_review",
    # Tool loop -> replan, not retry
    FailureReason.TOOL_FAILED: "retry",
    FailureReason.EXACT_REPEATED_TOOL_FAILURE: "replan",
    FailureReason.SAME_TOOL_REPEATED_FAILURE: "replan",
    FailureReason.IDEMPOTENT_NO_PROGRESS: "replan",
    # Policy
    FailureReason.PROTECTED_FILE_CHANGE: "needs_human_review",
    FailureReason.HIGH_RISK_TOOL: "needs_human_review",
    FailureReason.REVIEWER_WRITE_ATTEMPT: "fail",
    FailureReason.MISSING_REQUIRED_CHECK: "request_evidence",
    # Fallback
    FailureReason.UNKNOWN: "fail",
}

# Reasons that must never be blindly retried
_NON_RETRYABLE_REASONS: frozenset[FailureReason] = frozenset({
    FailureReason.AUTH_PERMANENT,
    FailureReason.BILLING,
    FailureReason.FORMAT_ERROR,
    FailureReason.INPUT_GUARDRAIL_BLOCKED,
    FailureReason.OUTPUT_GUARDRAIL_BLOCKED,
    FailureReason.SENSITIVE_CONTENT,
    FailureReason.EXACT_REPEATED_TOOL_FAILURE,
    FailureReason.SAME_TOOL_REPEATED_FAILURE,
    FailureReason.IDEMPOTENT_NO_PROGRESS,
    FailureReason.REVIEWER_WRITE_ATTEMPT,
    FailureReason.UNKNOWN,
})


# =============================================================================
# Backward-compatible severity map (category -> severity)
# =============================================================================

DEFAULT_SEVERITY_MAP: dict[FailureCategory, FailureSeverity] = {
    FailureCategory.PROVIDER_ERROR: FailureSeverity.MEDIUM,
    FailureCategory.TASK_QUALITY_ERROR: FailureSeverity.MEDIUM,
    FailureCategory.GUARDRAIL_BLOCKED: FailureSeverity.HIGH,
    FailureCategory.TOOL_ERROR: FailureSeverity.MEDIUM,
    FailureCategory.POLICY_ERROR: FailureSeverity.HIGH,
    FailureCategory.UNKNOWN: FailureSeverity.MEDIUM,
}


# =============================================================================
# Provider error pattern lists
# Adapted from Hermes Agent (MIT): agent/error_classifier.py
# =============================================================================

_BILLING_PATTERNS: list[str] = [
    "insufficient credits",
    "insufficient_quota",
    "insufficient balance",
    "credit balance",
    "credits have been exhausted",
    "top up your credits",
    "payment required",
    "billing hard limit",
    "exceeded your current quota",
    "account is deactivated",
    "plan does not include",
]

_RATE_LIMIT_PATTERNS: list[str] = [
    "rate limit",
    "rate_limit",
    "too many requests",
    "throttled",
    "requests per minute",
    "tokens per minute",
    "requests per day",
    "try again in",
    "please retry after",
    "resource_exhausted",
    "rate increased too quickly",
    "throttlingexception",
    "too many concurrent requests",
    "servicequotaexceededexception",
]


# =============================================================================
# FailureRecord
# =============================================================================

class FailureRecord:
    """Structured failure record with origin, category, reason, and recovery."""

    def __init__(
        self,
        category: FailureCategory,
        *,
        origin: FailureOrigin = "unknown",
        reason: str = "",
        recovery_hint: RecoveryHint | None = None,
        agent_name: str | None = None,
        severity: FailureSeverity | None = None,
        context: dict[str, Any] | None = None,
    ):
        self.origin: FailureOrigin = origin
        self.category = category
        self.reason = reason
        self.recovery_hint = recovery_hint or _resolve_recovery_hint(category, reason)
        self.agent_name = agent_name
        self.severity = severity or _resolve_severity(category, reason)
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "category": self.category.value,
            "reason": self.reason,
            "recovery_hint": self.recovery_hint,
            "agent_name": self.agent_name,
            "severity": self.severity.value,
            "context": self.context,
        }

    @property
    def is_retryable(self) -> bool:
        """Whether this failure is safe to retry (even with backoff).

        Judge by recovery_hint so the system is self-consistent: whatever the
        hint map prescribes, is_retryable follows.
        """
        return self.recovery_hint in {"retry", "retry_with_backoff"}


# =============================================================================
# Classification helpers
# =============================================================================

def classify_provider_error(
    error_message: str, status_code: int | None = None
) -> FailureReason:
    """Classify a provider/API error message into a concrete FailureReason."""
    lowered = error_message.lower()

    # Billing — check before rate_limit (some billing messages contain "quota")
    for pattern in _BILLING_PATTERNS:
        if pattern in lowered:
            return FailureReason.BILLING

    # Rate limit
    for pattern in _RATE_LIMIT_PATTERNS:
        if pattern in lowered:
            return FailureReason.RATE_LIMIT

    # Auth
    if status_code in {401, 403}:
        return FailureReason.AUTH
    if "unauthorized" in lowered or "forbidden" in lowered or "invalid api key" in lowered:
        return FailureReason.AUTH

    # Context overflow
    if "context" in lowered and (
        "too large" in lowered
        or "overflow" in lowered
        or "exceed" in lowered
        or "maximum" in lowered
    ):
        return FailureReason.CONTEXT_OVERFLOW

    # Server errors
    if status_code in {500, 502}:
        return FailureReason.SERVER_ERROR
    if status_code in {503, 529}:
        return FailureReason.OVERLOADED

    # Timeout
    if "timeout" in lowered or "timed out" in lowered:
        return FailureReason.TIMEOUT

    # Model not found
    if "model" in lowered and (
        "not found" in lowered
        or "does not exist" in lowered
        or "not available" in lowered
        or "not supported" in lowered
    ):
        return FailureReason.MODEL_NOT_FOUND

    # Format error
    if status_code == 400:
        return FailureReason.FORMAT_ERROR

    return FailureReason.UNKNOWN


def _resolve_recovery_hint(
    category: FailureCategory, reason: str
) -> RecoveryHint:
    """Resolve a recovery hint from category and reason string."""
    try:
        reason_enum = FailureReason(reason)
    except (ValueError, TypeError):
        reason_enum = FailureReason.UNKNOWN
    return RECOVERY_HINT_MAP.get(reason_enum, "fail")


def _resolve_severity(
    category: FailureCategory, reason: str
) -> FailureSeverity:
    """Resolve severity from category and reason string."""
    try:
        reason_enum = FailureReason(reason)
    except (ValueError, TypeError):
        return DEFAULT_SEVERITY_MAP.get(category, FailureSeverity.MEDIUM)
    return _DEFAULT_REASON_SEVERITY.get(
        reason_enum, DEFAULT_SEVERITY_MAP.get(category, FailureSeverity.MEDIUM)
    )


# =============================================================================
# Jittered backoff
# Adapted from Hermes Agent (MIT): agent/retry_utils.py jittered_backoff
# =============================================================================

_jitter_counter: int = 0
_jitter_lock = threading.Lock()


def jittered_backoff(
    attempt: int,
    *,
    base_delay: float = 5.0,
    max_delay: float = 120.0,
    jitter_ratio: float = 0.5,
) -> float:
    """Compute a jittered exponential backoff delay.

    Only use for transient failures (rate_limit, timeout, overloaded,
    server_error).  Never use for guardrail_blocked, billing, auth_permanent,
    format_error, or protected_file_change.
    """
    global _jitter_counter
    with _jitter_lock:
        _jitter_counter += 1
        tick = _jitter_counter

    exponent = max(0, attempt - 1)
    if exponent >= 63 or base_delay <= 0:
        delay = max_delay
    else:
        delay = min(base_delay * (2 ** exponent), max_delay)

    seed = (time.time_ns() ^ (tick * 0x9E3779B9)) & 0xFFFFFFFF
    rng = random.Random(seed)
    jitter = rng.uniform(0, jitter_ratio * delay)

    return delay + jitter


# =============================================================================
# Backward-compatible creation helpers
# =============================================================================

def create_failure_record(
    *,
    category: FailureCategory,
    origin: FailureOrigin = "unknown",
    reason: str = "",
    recovery_hint: RecoveryHint | None = None,
    agent_name: str | None = None,
    severity: FailureSeverity | None = None,
    context: dict[str, Any] | None = None,
) -> FailureRecord:
    """Create a FailureRecord with an explicit, caller-known category.

    This is the recommended creation path.  It does NOT call infer.
    """
    return FailureRecord(
        category=category,
        origin=origin,
        reason=reason,
        recovery_hint=recovery_hint,
        agent_name=agent_name,
        severity=severity,
        context=context,
    )


def infer_failure_category(
    *,
    status: str,
    reason: str,
    event_type: str | None = None,
    eval_action: str | None = None,
) -> FailureCategory:
    """Fallback: infer broad failure category from runtime signals.

    Prefer create_failure_record() when the failure source already knows
    the category.  Use this only for unknown fallback paths.
    """
    if status == "guardrail_blocked" or event_type == "guardrail_violation":
        return FailureCategory.GUARDRAIL_BLOCKED
    if status == "timed_out":
        return FailureCategory.PROVIDER_ERROR
    if "trust_level" in reason.lower() or "risk_level" in reason.lower():
        return FailureCategory.POLICY_ERROR
    if "permission" in reason.lower():
        return FailureCategory.POLICY_ERROR
    if "tool" in reason.lower():
        return FailureCategory.TOOL_ERROR
    if eval_action in ("retry", "fail"):
        return FailureCategory.TASK_QUALITY_ERROR
    return FailureCategory.UNKNOWN


def classify_failure(
    *,
    status: str,
    reason: str,
    agent_name: str | None = None,
    event_type: str | None = None,
    eval_action: str | None = None,
) -> FailureRecord:
    """Legacy classify_failure — uses infer for backward compatibility.

    Deprecated: prefer create_failure_record() with an explicit category.
    This function is retained for backward compatibility and unknown
    fallback paths ONLY.
    """
    category = infer_failure_category(
        status=status, reason=reason, event_type=event_type, eval_action=eval_action
    )
    return FailureRecord(
        category=category,
        origin="unknown",
        reason=reason,
        agent_name=agent_name,
    )
