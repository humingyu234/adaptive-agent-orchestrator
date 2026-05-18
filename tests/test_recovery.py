"""Phase 11 — Recovery Playbook boundary tests.

Contract: FailureRecord + attempts + run_mode + runtime capability
produce a bounded, visible, deterministic RecoveryDecision.
"""

from __future__ import annotations

import pytest

from src.orchestrator.control_models import ControlDecision
from src.orchestrator.failure_taxonomy import (
    FailureCategory,
    FailureRecord,
    FailureReason,
    FailureSeverity,
)
from src.orchestrator.recovery import (
    AttemptTracker,
    RecoveryAttemptKey,
    RecoveryDecision,
    RecoveryPlaybook,
    build_default_playbook,
)


def _make_record(
    category: FailureCategory = FailureCategory.PROVIDER_ERROR,
    reason: str = "rate_limit",
    origin: str = "provider",
) -> FailureRecord:
    return FailureRecord(
        category=category,
        reason=reason,
        origin=origin,  # type: ignore[arg-type]
    )


# ===========================================================================
# RecoveryPlaybook unit tests
# ===========================================================================


class TestRateLimitRetriesWithBackoff:
    def test_rate_limit_retries_then_human_review(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="rate_limit")

        # Attempt 0: first try
        d = pb.decide(record, attempt_count=0)
        assert d.action == "retry_with_backoff"
        assert d.delay_seconds > 0
        assert d.terminal is False
        assert d.runtime_supported is True

        # Attempt 1: second try
        d = pb.decide(record, attempt_count=1)
        assert d.action == "retry_with_backoff"
        assert d.terminal is False

        # Attempt 2: exhausted
        d = pb.decide(record, attempt_count=2)
        assert d.action == "needs_human_review"
        assert d.terminal is True
        assert d.requires_human_review is True

    def test_timeout_retries_with_backoff(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="timeout")
        d = pb.decide(record, attempt_count=0)
        assert d.action == "retry_with_backoff"
        assert d.delay_seconds > 0

    def test_overloaded_retries_with_backoff(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="overloaded")
        d = pb.decide(record, attempt_count=0)
        assert d.action == "retry_with_backoff"


class TestBillingFailsFast:
    def test_billing_fails_fast_without_retry(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="billing")
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"
        assert d.terminal is True
        assert d.requires_human_review is False

    def test_auth_permanent_fails_fast(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="auth_permanent")
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"
        assert d.terminal is True

    def test_format_error_fails_fast(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="format_error")
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"


class TestMissingEvidence:
    def test_missing_evidence_requests_evidence_without_blind_retry(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.TASK_QUALITY_ERROR,
            reason="missing_evidence",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "request_evidence"
        assert d.terminal is True
        assert d.next_step_hint is not None

    def test_missing_evidence_does_not_retry_even_with_attempts_remaining(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.TASK_QUALITY_ERROR,
            reason="missing_evidence",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action != "retry"
        assert "request_evidence" in d.action

    def test_missing_required_check_does_not_blind_retry(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.POLICY_ERROR,
            reason="missing_required_check",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "request_evidence"
        assert d.terminal is True


class TestGuardrailBlockedFailsFast:
    def test_input_guardrail_blocked_fails_fast(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.GUARDRAIL_BLOCKED,
            reason="input_guardrail_blocked",
            origin="control_plane",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"
        assert d.terminal is True

    def test_output_guardrail_blocked_fails_fast(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.GUARDRAIL_BLOCKED,
            reason="output_guardrail_blocked",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"
        assert d.terminal is True

    def test_sensitive_content_fails_fast(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.GUARDRAIL_BLOCKED,
            reason="sensitive_content",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"


class TestToolLoop:
    def test_exact_repeated_tool_failure_replans(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.TOOL_ERROR,
            reason="exact_repeated_tool_failure",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "replan"
        assert d.terminal is False

    def test_tool_loop_replan_exhausted_goes_to_human_review(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.TOOL_ERROR,
            reason="same_tool_repeated_failure",
        )
        d = pb.decide(record, attempt_count=1)
        assert d.action == "needs_human_review"
        assert d.terminal is True

    def test_idempotent_no_progress_replans(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.TOOL_ERROR,
            reason="idempotent_no_progress",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "replan"


class TestEvaluationFailed:
    def test_evaluation_failed_retries_once(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.TASK_QUALITY_ERROR,
            reason="evaluation_failed",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "retry"
        assert d.terminal is False

    def test_evaluation_failed_retry_exhausted_needs_human_review(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.TASK_QUALITY_ERROR,
            reason="evaluation_failed",
        )
        d = pb.decide(record, attempt_count=2)
        assert d.action == "needs_human_review"
        assert d.terminal is True


class TestUnknownFailure:
    def test_unknown_failure_does_not_retry_blindly(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.UNKNOWN,
            reason="unknown",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"
        assert d.terminal is True
        assert d.action != "retry"

    def test_unknown_reason_string_also_fails(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.UNKNOWN,
            reason="something_weird_happened",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"


class TestUnsupportedRuntime:
    def test_fallback_provider_unsupported_is_marked(self):
        pb = RecoveryPlaybook(
            runtime_capabilities={"retry", "fail", "human_review"},
        )
        record = _make_record(reason="model_not_found")
        d = pb.decide(record, attempt_count=0)
        assert d.runtime_supported is False
        assert d.action == "needs_human_review"

    def test_retry_unsupported_falls_back_to_human_review(self):
        pb = RecoveryPlaybook(
            runtime_capabilities={"fail", "human_review"},
        )
        record = _make_record(reason="rate_limit")
        d = pb.decide(record, attempt_count=0)
        assert d.runtime_supported is False
        assert d.action == "needs_human_review"

    def test_replan_unsupported_falls_back_to_human_review(self):
        pb = RecoveryPlaybook(
            runtime_capabilities={"retry", "fail"},
        )
        record = _make_record(
            category=FailureCategory.TOOL_ERROR,
            reason="exact_repeated_tool_failure",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.runtime_supported is False
        assert d.action == "needs_human_review"


class TestLogMode:
    def test_log_mode_records_recovery_without_enforcing(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="rate_limit")
        d = pb.decide(record, attempt_count=0, run_mode="log")
        assert d.action == "continue"
        assert d.terminal is False

    def test_log_mode_does_not_block_hard_stop(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="billing")
        d = pb.decide(record, attempt_count=0, run_mode="log")
        assert d.action == "continue"
        assert d.terminal is False


class TestControlledMode:
    def test_controlled_mode_enforces_recovery(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="rate_limit")
        d = pb.decide(record, attempt_count=0, run_mode="controlled")
        assert d.action == "retry_with_backoff"
        assert d.delay_seconds > 0

    def test_controlled_mode_fails_on_hard_stop(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="billing")
        d = pb.decide(record, attempt_count=0, run_mode="controlled")
        assert d.action == "fail"


class TestOffMode:
    def test_off_mode_bypasses_recovery(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="billing")
        d = pb.decide(record, attempt_count=0, run_mode="off")
        assert d.action == "continue"
        assert d.terminal is False


class TestPolicyHardStops:
    def test_reviewer_write_attempt_fails_fast(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.POLICY_ERROR,
            reason="reviewer_write_attempt",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fail"
        assert d.terminal is True

    def test_protected_file_change_needs_human_review(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.POLICY_ERROR,
            reason="protected_file_change",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "needs_human_review"
        assert d.terminal is True

    def test_high_risk_tool_needs_human_review(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.POLICY_ERROR,
            reason="high_risk_tool",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "needs_human_review"
        assert d.terminal is True


class TestContextOverflow:
    def test_context_overflow_compress_unsupported_requests_evidence(self):
        pb = RecoveryPlaybook(
            runtime_capabilities={"retry", "fail", "human_review"},
        )
        record = _make_record(
            category=FailureCategory.PROVIDER_ERROR,
            reason="context_overflow",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.runtime_supported is False
        assert d.action == "request_evidence"


class TestToolFailed:
    def test_tool_failed_retries_once_then_human_review(self):
        pb = RecoveryPlaybook()
        record = _make_record(
            category=FailureCategory.TOOL_ERROR,
            reason="tool_failed",
        )
        d = pb.decide(record, attempt_count=0)
        assert d.action == "retry"
        d = pb.decide(record, attempt_count=2)
        assert d.action == "needs_human_review"


class TestProviderRoute:
    def test_model_not_found_falls_back_if_supported(self):
        pb = RecoveryPlaybook(
            runtime_capabilities={"fallback_model_or_provider", "retry", "fail", "human_review"},
        )
        record = _make_record(reason="model_not_found")
        d = pb.decide(record, attempt_count=0)
        assert d.action == "fallback_model_or_provider"
        assert d.runtime_supported is True


# ===========================================================================
# AttemptTracker tests
# ===========================================================================


class TestAttemptTracker:
    def test_attempt_key_separates_different_agents(self):
        tracker = AttemptTracker()
        key_a = RecoveryAttemptKey(
            task_id="t1", agent_name="planner",
            failure_category="provider_error", failure_reason="rate_limit",
        )
        key_b = RecoveryAttemptKey(
            task_id="t1", agent_name="search",
            failure_category="provider_error", failure_reason="rate_limit",
        )
        assert tracker.record(key_a) == 1
        assert tracker.record(key_a) == 2
        assert tracker.record(key_b) == 1

    def test_attempt_key_separates_different_reasons(self):
        tracker = AttemptTracker()
        key_a = RecoveryAttemptKey(
            task_id="t1", agent_name="planner",
            failure_category="provider_error", failure_reason="rate_limit",
        )
        key_b = RecoveryAttemptKey(
            task_id="t1", agent_name="planner",
            failure_category="provider_error", failure_reason="timeout",
        )
        assert tracker.record(key_a) == 1
        assert tracker.record(key_b) == 1

    def test_reset_clears_attempt_count(self):
        tracker = AttemptTracker()
        key = RecoveryAttemptKey(
            task_id="t1", agent_name="planner",
            failure_category="provider_error", failure_reason="rate_limit",
        )
        tracker.record(key)
        tracker.record(key)
        assert tracker.get(key) == 2
        tracker.reset(key)
        assert tracker.get(key) == 0

    def test_different_failure_reasons_do_not_exhaust_each_other(self):
        """Different failure reasons should NOT exhaust each other's retry budgets."""
        pb = RecoveryPlaybook()
        tracker = AttemptTracker()

        rate_limit_key = RecoveryAttemptKey(
            task_id="t1", agent_name="agent1",
            failure_category="provider_error", failure_reason="rate_limit",
        )
        timeout_key = RecoveryAttemptKey(
            task_id="t1", agent_name="agent1",
            failure_category="provider_error", failure_reason="timeout",
        )

        # Rate limit: 1st attempt
        record_rl = _make_record(reason="rate_limit")
        c1 = tracker.record(rate_limit_key)
        d1 = pb.decide(record_rl, attempt_count=c1 - 1)
        assert d1.action == "retry_with_backoff"

        # Timeout: should start fresh, not use rate_limit's budget
        record_to = _make_record(reason="timeout")
        c2 = tracker.record(timeout_key)
        d2 = pb.decide(record_to, attempt_count=c2 - 1)
        assert d2.action == "retry_with_backoff"
        assert d2.terminal is False


# ===========================================================================
# RecoveryDecision serialisation
# ===========================================================================


class TestRecoveryDecisionDict:
    def test_to_dict_includes_all_keys(self):
        pb = RecoveryPlaybook()
        record = _make_record(reason="rate_limit")
        d = pb.decide(record, attempt_count=0)
        result = d.to_dict()
        for key in (
            "failure_category", "failure_reason", "failure_origin",
            "recovery_hint", "action", "reason", "attempt_count",
            "max_attempts", "next_step_hint", "delay_seconds",
            "terminal", "requires_human_review", "runtime_supported",
        ):
            assert key in result, f"Missing key {key}"


# ===========================================================================
# Factory
# ===========================================================================


class TestBuildDefaultPlaybook:
    def test_default_playbook_has_basic_capabilities(self):
        pb = build_default_playbook()
        record = _make_record(reason="rate_limit")
        d = pb.decide(record, attempt_count=0)
        assert d.action == "retry_with_backoff"
