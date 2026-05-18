"""Recovery playbook — bounded, deterministic recovery decisions.

Turns FailureRecord + attempt_count + run_mode + runtime capabilities
into a RecoveryDecision that the scheduler can execute without owning
the recovery matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .control_models import RecoveryHint
from .failure_taxonomy import (
    RECOVERY_HINT_MAP,
    FailureCategory,
    FailureReason,
    FailureRecord,
    jittered_backoff,
)


# =============================================================================
# Recovery action — what the runtime should do
# =============================================================================

RecoveryAction = str  # one of the RecoveryHint literal values or "continue"


# =============================================================================
# RecoveryDecision
# =============================================================================

@dataclass
class RecoveryDecision:
    """Bounded, visible, deterministic recovery decision.

    Answers: what failed, what to do now, how many times tried, is it terminal,
    does the runtime support this action, what should happen next.
    """

    failure_category: str
    failure_reason: str
    failure_origin: str = "unknown"
    recovery_hint: str = "fail"
    action: RecoveryAction = "fail"
    reason: str = ""
    attempt_count: int = 0
    max_attempts: int = 1
    next_step_hint: str | None = None
    delay_seconds: float = 0.0
    terminal: bool = True
    requires_human_review: bool = False
    runtime_supported: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_category": self.failure_category,
            "failure_reason": self.failure_reason,
            "failure_origin": self.failure_origin,
            "recovery_hint": self.recovery_hint,
            "action": self.action,
            "reason": self.reason,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "next_step_hint": self.next_step_hint,
            "delay_seconds": self.delay_seconds,
            "terminal": self.terminal,
            "requires_human_review": self.requires_human_review,
            "runtime_supported": self.runtime_supported,
        }


# =============================================================================
# Recovery attempt key — stable retry accounting
# =============================================================================

@dataclass(frozen=True)
class RecoveryAttemptKey:
    """Stable key for counting retry attempts on the same failure.

    Same agent + same category/reason increments the counter.
    Different agent or different reason creates a separate chain.
    """

    task_id: str
    agent_name: str
    failure_category: str
    failure_reason: str
    step_name: str = ""


# =============================================================================
# Capability set
# =============================================================================

_RUNTIME_CAPABILITY_ACTIONS: frozenset[str] = frozenset({
    "retry",
    "retry_with_backoff",
    "request_evidence",
    "replan",
    "compress_context",
    "fallback_model_or_provider",
    "human_review",
    "fail",
})


# =============================================================================
# Recovery matrix — max attempts per hint under controlled mode
# =============================================================================

_MAX_ATTEMPTS: dict[str, int] = {
    "retry": 2,
    "retry_with_backoff": 2,
    "request_evidence": 1,
    "replan": 1,
    "compress_context": 1,
    "fallback_model_or_provider": 1,
}

_EXHAUSTED_ACTION: dict[str, str] = {
    "retry": "needs_human_review",
    "retry_with_backoff": "needs_human_review",
    "request_evidence": "needs_human_review",
    "replan": "needs_human_review",
    "compress_context": "needs_human_review",
    "fallback_model_or_provider": "needs_human_review",
}

# Hints that must never produce a retry (hard stops / protected actions)
_HARD_STOP_HINTS: frozenset[str] = frozenset({
    "fail",
    "needs_human_review",
    "request_evidence",
})

# Reasons that have dedicated non-retry handlers:
#   missing_evidence / missing_required_check → request_evidence handler
#   tool-loop reasons → replan handler
# These must NOT appear in _NON_RETRYABLE_REASONS — their handlers already
# prevent blind retries, and the early check would short-circuit them to fail.
_NON_RETRYABLE_REASONS: frozenset[str] = frozenset({
    "auth_permanent",
    "billing",
    "format_error",
    "input_guardrail_blocked",
    "output_guardrail_blocked",
    "sensitive_content",
    "reviewer_write_attempt",
    "unknown",
})


# =============================================================================
# RecoveryPlaybook
# =============================================================================

class RecoveryPlaybook:
    """Deterministic recovery matrix.

    Maps FailureRecord + attempt_count + run_mode + capabilities
    → RecoveryDecision.  Never calls an LLM.
    """

    def __init__(
        self,
        *,
        runtime_capabilities: set[str] | None = None,
    ) -> None:
        self._capabilities = runtime_capabilities or {
            "retry",
            "retry_with_backoff",
            "request_evidence",
            "replan",
            "human_review",
            "fail",
        }

    def decide(
        self,
        failure_record: FailureRecord,
        *,
        attempt_count: int = 0,
        run_mode: str = "controlled",
        task_id: str = "",
        step_name: str = "",
    ) -> RecoveryDecision:
        """Produce a bounded recovery decision from a FailureRecord."""
        hint: RecoveryHint = failure_record.recovery_hint or "fail"

        # --- off mode: bypass ---
        if run_mode == "off":
            return RecoveryDecision(
                failure_category=failure_record.category.value,
                failure_reason=failure_record.reason,
                failure_origin=failure_record.origin,
                recovery_hint=hint,
                action="continue",
                reason="Recovery bypassed (run_mode=off)",
                attempt_count=attempt_count,
                max_attempts=1,
                terminal=False,
                requires_human_review=False,
                runtime_supported=True,
            )

        # --- log mode: record but don't enforce (must come before hint handlers) ---
        if run_mode == "log":
            return self._log_decision(failure_record, hint, attempt_count)

        # --- determine max attempts ---
        max_attempts = _MAX_ATTEMPTS.get(hint, 1)
        exhausted = attempt_count >= max_attempts

        # --- hard stops — never retry ---
        reason_str = failure_record.reason
        if reason_str in _NON_RETRYABLE_REASONS:
            return self._hard_stop(
                failure_record, hint, reason_str, attempt_count, max_attempts, task_id, step_name
            )

        if hint in ("fail", "needs_human_review"):
            return self._hard_stop(
                failure_record, hint, reason_str, attempt_count, max_attempts, task_id, step_name
            )

        # --- request_evidence — no retry, no exhaustion retry ---
        if hint == "request_evidence":
            return self._request_evidence_decision(failure_record, attempt_count, task_id, step_name)

        # --- retry / retry_with_backoff ---
        if hint in ("retry", "retry_with_backoff"):
            return self._retry_decision(
                failure_record, hint, attempt_count, exhausted, task_id, step_name
            )

        # --- replan ---
        if hint == "replan":
            return self._replan_decision(
                failure_record, attempt_count, exhausted, task_id, step_name
            )

        # --- compress_context ---
        if hint == "compress_context":
            return self._compress_decision(
                failure_record, attempt_count, exhausted, task_id, step_name
            )

        # --- fallback_model_or_provider ---
        if hint == "fallback_model_or_provider":
            return self._fallback_decision(
                failure_record, attempt_count, task_id, step_name
            )

        # --- fallback: fail ---
        return RecoveryDecision(
            failure_category=failure_record.category.value,
            failure_reason=failure_record.reason,
            failure_origin=failure_record.origin,
            recovery_hint=hint,
            action="fail",
            reason=f"No recovery route for hint '{hint}'",
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            terminal=True,
            requires_human_review=False,
            runtime_supported=True,
        )

    # ------------------------------------------------------------------
    # internal decision helpers
    # ------------------------------------------------------------------

    def _log_decision(
        self,
        failure_record: FailureRecord,
        hint: str,
        attempt_count: int,
    ) -> RecoveryDecision:
        """Log mode: record the decision but always return continue."""
        max_att = _MAX_ATTEMPTS.get(hint, 1)
        return RecoveryDecision(
            failure_category=failure_record.category.value,
            failure_reason=failure_record.reason,
            failure_origin=failure_record.origin,
            recovery_hint=hint,
            action="continue",
            reason=f"Log mode: would act on '{hint}' but not enforced",
            attempt_count=attempt_count,
            max_attempts=max_att,
            terminal=False,
            requires_human_review=False,
            runtime_supported=True,
        )

    def _hard_stop(
        self,
        failure_record: FailureRecord,
        hint: str,
        reason_str: str,
        attempt_count: int,
        max_attempts: int,
        task_id: str,
        step_name: str,
    ) -> RecoveryDecision:
        """Fail or needs_human_review — no retry."""
        requires_hr = hint == "needs_human_review"
        action = "needs_human_review" if requires_hr else "fail"
        return RecoveryDecision(
            failure_category=failure_record.category.value,
            failure_reason=failure_record.reason,
            failure_origin=failure_record.origin,
            recovery_hint=hint,
            action=action,
            reason=f"Hard stop: {reason_str} — {action}",
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            terminal=True,
            requires_human_review=requires_hr or action == "needs_human_review",
            runtime_supported=True,
        )

    def _request_evidence_decision(
        self,
        failure_record: FailureRecord,
        attempt_count: int,
        task_id: str,
        step_name: str,
    ) -> RecoveryDecision:
        """Request evidence — no blind retry, no exhaustion retry."""
        return RecoveryDecision(
            failure_category=failure_record.category.value,
            failure_reason=failure_record.reason,
            failure_origin=failure_record.origin,
            recovery_hint="request_evidence",
            action="request_evidence",
            reason=f"Missing evidence: {failure_record.reason}",
            attempt_count=attempt_count,
            max_attempts=1,
            terminal=True,
            requires_human_review=False,
            runtime_supported=self._supports("request_evidence"),
            next_step_hint="Provide the requested evidence before retrying",
        )

    def _retry_decision(
        self,
        failure_record: FailureRecord,
        hint: str,
        attempt_count: int,
        exhausted: bool,
        task_id: str,
        step_name: str,
    ) -> RecoveryDecision:
        """Retry or retry_with_backoff — bounded by max attempts."""
        max_att = _MAX_ATTEMPTS.get(hint, 2)
        if exhausted:
            fallback = _EXHAUSTED_ACTION.get(hint, "needs_human_review")
            return RecoveryDecision(
                failure_category=failure_record.category.value,
                failure_reason=failure_record.reason,
                failure_origin=failure_record.origin,
                recovery_hint=hint,
                action=fallback,
                reason=f"{hint} exhausted after {attempt_count} attempt(s)",
                attempt_count=attempt_count,
                max_attempts=max_att,
                terminal=True,
                requires_human_review=fallback == "needs_human_review",
                runtime_supported=True,
            )

        delay = jittered_backoff(attempt_count) if hint == "retry_with_backoff" else 0.0
        runtime_ok = self._supports(hint)
        if not runtime_ok:
            return RecoveryDecision(
                failure_category=failure_record.category.value,
                failure_reason=failure_record.reason,
                failure_origin=failure_record.origin,
                recovery_hint=hint,
                action="needs_human_review",
                reason=f"Retry not supported by runtime, hint was '{hint}'",
                attempt_count=attempt_count,
                max_attempts=max_att,
                delay_seconds=0,
                terminal=True,
                requires_human_review=True,
                runtime_supported=False,
            )

        return RecoveryDecision(
            failure_category=failure_record.category.value,
            failure_reason=failure_record.reason,
            failure_origin=failure_record.origin,
            recovery_hint=hint,
            action=hint,
            reason=f"Attempt {attempt_count + 1}/{max_att}",
            attempt_count=attempt_count,
            max_attempts=max_att,
            delay_seconds=delay,
            terminal=False,
            requires_human_review=False,
            runtime_supported=True,
            next_step_hint="Retry with backoff" if hint == "retry_with_backoff" else "Retry immediately",
        )

    def _replan_decision(
        self,
        failure_record: FailureRecord,
        attempt_count: int,
        exhausted: bool,
        task_id: str,
        step_name: str,
    ) -> RecoveryDecision:
        """Replan — once, then human review if exhausted."""
        if exhausted:
            return RecoveryDecision(
                failure_category=failure_record.category.value,
                failure_reason=failure_record.reason,
                failure_origin=failure_record.origin,
                recovery_hint="replan",
                action="needs_human_review",
                reason="Replan exhausted",
                attempt_count=attempt_count,
                max_attempts=1,
                terminal=True,
                requires_human_review=True,
                runtime_supported=True,
            )

        if not self._supports("replan"):
            return RecoveryDecision(
                failure_category=failure_record.category.value,
                failure_reason=failure_record.reason,
                failure_origin=failure_record.origin,
                recovery_hint="replan",
                action="needs_human_review",
                reason="Replan not supported by runtime",
                attempt_count=attempt_count,
                max_attempts=1,
                terminal=True,
                requires_human_review=True,
                runtime_supported=False,
            )

        return RecoveryDecision(
            failure_category=failure_record.category.value,
            failure_reason=failure_record.reason,
            failure_origin=failure_record.origin,
            recovery_hint="replan",
            action="replan",
            reason="Replan with different strategy",
            attempt_count=attempt_count,
            max_attempts=1,
            terminal=False,
            requires_human_review=False,
            runtime_supported=True,
            next_step_hint="Create a revised plan",
        )

    def _compress_decision(
        self,
        failure_record: FailureRecord,
        attempt_count: int,
        exhausted: bool,
        task_id: str,
        step_name: str,
    ) -> RecoveryDecision:
        """Compress context — once, then human review if exhausted or unsupported."""
        if exhausted:
            return RecoveryDecision(
                failure_category=failure_record.category.value,
                failure_reason=failure_record.reason,
                failure_origin=failure_record.origin,
                recovery_hint="compress_context",
                action="needs_human_review",
                reason="Context compression exhausted",
                attempt_count=attempt_count,
                max_attempts=1,
                terminal=True,
                requires_human_review=True,
                runtime_supported=True,
            )

        if not self._supports("compress_context"):
            return RecoveryDecision(
                failure_category=failure_record.category.value,
                failure_reason=failure_record.reason,
                failure_origin=failure_record.origin,
                recovery_hint="compress_context",
                action="request_evidence",
                reason="Context compression not supported by runtime",
                attempt_count=attempt_count,
                max_attempts=1,
                terminal=True,
                requires_human_review=False,
                runtime_supported=False,
                next_step_hint="Compress context manually or reduce payload size",
            )

        return RecoveryDecision(
            failure_category=failure_record.category.value,
            failure_reason=failure_record.reason,
            failure_origin=failure_record.origin,
            recovery_hint="compress_context",
            action="compress_context",
            reason=f"Context compression attempt {attempt_count + 1}/1",
            attempt_count=attempt_count,
            max_attempts=1,
            terminal=False,
            requires_human_review=False,
            runtime_supported=True,
            next_step_hint="Compress and retry with smaller payload",
        )

    def _fallback_decision(
        self,
        failure_record: FailureRecord,
        attempt_count: int,
        task_id: str,
        step_name: str,
    ) -> RecoveryDecision:
        """Fallback model/provider — if supported, use it; otherwise human review."""
        if self._supports("fallback_model_or_provider"):
            return RecoveryDecision(
                failure_category=failure_record.category.value,
                failure_reason=failure_record.reason,
                failure_origin=failure_record.origin,
                recovery_hint="fallback_model_or_provider",
                action="fallback_model_or_provider",
                reason="Switching to fallback model or provider",
                attempt_count=attempt_count,
                max_attempts=1,
                terminal=False,
                requires_human_review=False,
                runtime_supported=True,
                next_step_hint="Use fallback model or provider route",
            )

        return RecoveryDecision(
            failure_category=failure_record.category.value,
            failure_reason=failure_record.reason,
            failure_origin=failure_record.origin,
            recovery_hint="fallback_model_or_provider",
            action="needs_human_review",
            reason="Provider fallback not supported by runtime",
            attempt_count=attempt_count,
            max_attempts=1,
            terminal=True,
            requires_human_review=True,
            runtime_supported=False,
            next_step_hint="Manually switch provider or model",
        )

    def _supports(self, capability: str) -> bool:
        """Check if the runtime supports a given recovery capability."""
        return capability in self._capabilities


# =============================================================================
# Attempt tracker
# =============================================================================

class AttemptTracker:
    """Track attempt counts per stable RecoveryAttemptKey."""

    def __init__(self) -> None:
        self._counts: dict[RecoveryAttemptKey, int] = {}

    def record(self, key: RecoveryAttemptKey) -> int:
        """Record an attempt and return the new count (1-based)."""
        current = self._counts.get(key, 0) + 1
        self._counts[key] = current
        return current

    def get(self, key: RecoveryAttemptKey) -> int:
        """Return the current attempt count (0 if never attempted)."""
        return self._counts.get(key, 0)

    def reset(self, key: RecoveryAttemptKey) -> None:
        """Reset attempt count for a key."""
        self._counts.pop(key, None)


# =============================================================================
# Factory
# =============================================================================

def build_default_playbook(
    runtime_capabilities: set[str] | None = None,
) -> RecoveryPlaybook:
    """Create a RecoveryPlaybook with sensible default capabilities."""
    return RecoveryPlaybook(runtime_capabilities=runtime_capabilities)
