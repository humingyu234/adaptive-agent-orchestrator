"""Tests for failure_taxonomy — classification, recovery, severity, backoff."""

import unittest

from orchestrator.failure_taxonomy import (
    RECOVERY_HINT_GUIDANCE,
    RECOVERY_HINT_MAP,
    DEFAULT_SEVERITY_MAP,
    FailureCategory,
    FailureReason,
    FailureRecord,
    FailureSeverity,
    _NON_RETRYABLE_REASONS,
    classify_provider_error,
    classify_failure,
    create_failure_record,
    infer_failure_category,
    jittered_backoff,
)


# =============================================================================
# classify_provider_error
# =============================================================================

class ClassifyProviderErrorTest(unittest.TestCase):

    def test_rate_limit_detected_via_pattern(self):
        self.assertEqual(
            classify_provider_error("Rate limit exceeded. Try again in 30s"),
            FailureReason.RATE_LIMIT,
        )

    def test_rate_limit_detected_via_throttled(self):
        self.assertEqual(
            classify_provider_error("Request was throttled due to concurrency"),
            FailureReason.RATE_LIMIT,
        )

    def test_billing_detected_before_rate_limit(self):
        self.assertEqual(
            classify_provider_error("Insufficient credits. You have exceeded your current quota."),
            FailureReason.BILLING,
        )

    def test_auth_401(self):
        self.assertEqual(
            classify_provider_error("Unauthorized", status_code=401),
            FailureReason.AUTH,
        )

    def test_auth_403(self):
        self.assertEqual(
            classify_provider_error("Forbidden", status_code=403),
            FailureReason.AUTH,
        )

    def test_auth_invalid_api_key(self):
        self.assertEqual(
            classify_provider_error("Invalid API key provided"),
            FailureReason.AUTH,
        )

    def test_context_overflow(self):
        self.assertEqual(
            classify_provider_error("Context length exceeds maximum allowed tokens"),
            FailureReason.CONTEXT_OVERFLOW,
        )

    def test_server_error_500(self):
        self.assertEqual(
            classify_provider_error("Internal error", status_code=500),
            FailureReason.SERVER_ERROR,
        )

    def test_overloaded_503(self):
        self.assertEqual(
            classify_provider_error("Service unavailable", status_code=503),
            FailureReason.OVERLOADED,
        )

    def test_timeout(self):
        self.assertEqual(
            classify_provider_error("The request timed out after 60s"),
            FailureReason.TIMEOUT,
        )

    def test_model_not_found(self):
        self.assertEqual(
            classify_provider_error("Model 'gpt-999' does not exist"),
            FailureReason.MODEL_NOT_FOUND,
        )

    def test_format_error_400(self):
        self.assertEqual(
            classify_provider_error("Bad request", status_code=400),
            FailureReason.FORMAT_ERROR,
        )

    def test_unknown_fallback(self):
        self.assertEqual(
            classify_provider_error("Something unexpected happened"),
            FailureReason.UNKNOWN,
        )

    def test_billing_checked_before_rate_limit(self):
        reason = classify_provider_error(
            "Insufficient credits, top up your credits to continue. Rate limit also applies."
        )
        self.assertEqual(reason, FailureReason.BILLING)


# =============================================================================
# FailureRecord
# =============================================================================

class FailureRecordTest(unittest.TestCase):

    def test_creates_with_explicit_category(self):
        rec = create_failure_record(
            category=FailureCategory.PROVIDER_ERROR,
            reason="rate_limit",
            agent_name="planner",
        )
        self.assertEqual(rec.origin, "unknown")
        self.assertEqual(rec.category, FailureCategory.PROVIDER_ERROR)
        self.assertEqual(rec.reason, "rate_limit")
        self.assertEqual(rec.agent_name, "planner")
        self.assertIsNotNone(rec.recovery_hint)

    def test_to_dict_includes_all_fields(self):
        rec = create_failure_record(
            category=FailureCategory.GUARDRAIL_BLOCKED,
            reason="input_guardrail_blocked",
            agent_name="reviewer",
            severity=FailureSeverity.HIGH,
            context={"key": "value"},
        )
        d = rec.to_dict()
        self.assertEqual(d["origin"], "unknown")
        self.assertEqual(d["category"], "guardrail_blocked")
        self.assertEqual(d["reason"], "input_guardrail_blocked")
        self.assertEqual(d["agent_name"], "reviewer")
        self.assertEqual(d["severity"], "high")
        self.assertEqual(d["context"], {"key": "value"})

    def test_is_retryable_true_for_transient_provider_error(self):
        rec = FailureRecord(
            category=FailureCategory.PROVIDER_ERROR,
            reason="rate_limit",
        )
        self.assertTrue(rec.is_retryable)

    def test_is_retryable_true_for_timeout(self):
        rec = FailureRecord(
            category=FailureCategory.PROVIDER_ERROR,
            reason="timeout",
        )
        self.assertTrue(rec.is_retryable)

    def test_is_retryable_false_for_auth_permanent(self):
        rec = FailureRecord(
            category=FailureCategory.PROVIDER_ERROR,
            reason="auth_permanent",
        )
        self.assertFalse(rec.is_retryable)

    def test_is_retryable_false_for_guardrail_blocked(self):
        rec = FailureRecord(
            category=FailureCategory.GUARDRAIL_BLOCKED,
            reason="input_guardrail_blocked",
        )
        self.assertFalse(rec.is_retryable)

    def test_is_retryable_false_for_sensitive_content(self):
        rec = FailureRecord(
            category=FailureCategory.GUARDRAIL_BLOCKED,
            reason="sensitive_content",
        )
        self.assertFalse(rec.is_retryable)

    def test_is_retryable_false_for_tool_loop(self):
        rec = FailureRecord(
            category=FailureCategory.TOOL_ERROR,
            reason="exact_repeated_tool_failure",
        )
        self.assertFalse(rec.is_retryable)

    def test_is_retryable_true_for_single_tool_failure(self):
        rec = FailureRecord(
            category=FailureCategory.TOOL_ERROR,
            reason="tool_failed",
        )
        self.assertTrue(rec.is_retryable)


# =============================================================================
# Recovery hints
# =============================================================================

class RecoveryHintTest(unittest.TestCase):

    def test_rate_limit_maps_to_retry_with_backoff(self):
        self.assertEqual(
            RECOVERY_HINT_MAP[FailureReason.RATE_LIMIT],
            "retry_with_backoff",
        )

    def test_auth_permanent_maps_to_fail(self):
        self.assertEqual(
            RECOVERY_HINT_MAP[FailureReason.AUTH_PERMANENT],
            "fail",
        )

    def test_sensitive_content_maps_to_fail(self):
        self.assertEqual(
            RECOVERY_HINT_MAP[FailureReason.SENSITIVE_CONTENT],
            "fail",
        )

    def test_tool_loop_maps_to_replan_not_retry(self):
        for reason in (
            FailureReason.EXACT_REPEATED_TOOL_FAILURE,
            FailureReason.SAME_TOOL_REPEATED_FAILURE,
            FailureReason.IDEMPOTENT_NO_PROGRESS,
        ):
            with self.subTest(reason=reason):
                self.assertEqual(RECOVERY_HINT_MAP[reason], "replan")

    def test_guidance_has_entry_for_every_hint_value(self):
        hint_values = set(RECOVERY_HINT_MAP.values())
        for hint in hint_values:
            with self.subTest(hint=hint):
                self.assertIn(hint, RECOVERY_HINT_GUIDANCE)

    def test_non_retryable_set_is_consistent_with_hints(self):
        for reason in _NON_RETRYABLE_REASONS:
            with self.subTest(reason=reason):
                hint = RECOVERY_HINT_MAP[reason]
                self.assertIn(
                    hint, ("fail", "replan", "needs_human_review"),
                    f"{reason} is non-retryable but hint is {hint!r}",
                )


# =============================================================================
# Severity
# =============================================================================

class SeverityTest(unittest.TestCase):

    def test_default_severity_map_covers_all_categories(self):
        for cat in FailureCategory:
            with self.subTest(category=cat):
                self.assertIn(cat, DEFAULT_SEVERITY_MAP)

    def test_guardrail_blocked_is_high(self):
        self.assertEqual(
            DEFAULT_SEVERITY_MAP[FailureCategory.GUARDRAIL_BLOCKED],
            FailureSeverity.HIGH,
        )

    def test_policy_error_is_high(self):
        self.assertEqual(
            DEFAULT_SEVERITY_MAP[FailureCategory.POLICY_ERROR],
            FailureSeverity.HIGH,
        )

    def test_provider_error_is_medium(self):
        self.assertEqual(
            DEFAULT_SEVERITY_MAP[FailureCategory.PROVIDER_ERROR],
            FailureSeverity.MEDIUM,
        )

    def test_failure_record_resolves_severity_from_reason(self):
        rec = FailureRecord(
            category=FailureCategory.PROVIDER_ERROR,
            reason="auth_permanent",
        )
        self.assertEqual(rec.severity, FailureSeverity.CRITICAL)

    def test_failure_record_falls_back_to_category_severity(self):
        rec = FailureRecord(
            category=FailureCategory.PROVIDER_ERROR,
            reason="some_unknown_reason_string",
        )
        self.assertEqual(rec.severity, FailureSeverity.MEDIUM)


# =============================================================================
# jittered_backoff
# =============================================================================

class JitteredBackoffTest(unittest.TestCase):

    def test_returns_positive_delay(self):
        delay = jittered_backoff(1)
        self.assertGreater(delay, 0)

    def test_increases_with_attempt(self):
        d1 = jittered_backoff(1, jitter_ratio=0)
        d2 = jittered_backoff(3, jitter_ratio=0)
        self.assertGreater(d2, d1)

    def test_respects_max_delay(self):
        delay = jittered_backoff(100, max_delay=10.0, jitter_ratio=0)
        self.assertLessEqual(delay, 10.0)

    def test_jitter_adds_variation(self):
        delays = {jittered_backoff(2, jitter_ratio=0.5) for _ in range(20)}
        self.assertGreater(len(delays), 1, "Jitter should produce variation")

    def test_accepts_base_delay(self):
        delay = jittered_backoff(1, base_delay=1.0, jitter_ratio=0)
        self.assertAlmostEqual(delay, 1.0, delta=0.01)


# =============================================================================
# infer_failure_category (fallback)
# =============================================================================

class InferFailureCategoryTest(unittest.TestCase):

    def test_guardrail_blocked_status(self):
        cat = infer_failure_category(status="guardrail_blocked", reason="blocked")
        self.assertEqual(cat, FailureCategory.GUARDRAIL_BLOCKED)

    def test_guardrail_violation_event(self):
        cat = infer_failure_category(
            status="failed", reason="something", event_type="guardrail_violation"
        )
        self.assertEqual(cat, FailureCategory.GUARDRAIL_BLOCKED)

    def test_timed_out_status(self):
        cat = infer_failure_category(status="timed_out", reason="timeout")
        self.assertEqual(cat, FailureCategory.PROVIDER_ERROR)

    def test_trust_level_in_reason(self):
        cat = infer_failure_category(
            status="failed", reason="trust_level too low for this action"
        )
        self.assertEqual(cat, FailureCategory.POLICY_ERROR)

    def test_permission_in_reason(self):
        cat = infer_failure_category(
            status="failed", reason="permission denied for write"
        )
        self.assertEqual(cat, FailureCategory.POLICY_ERROR)

    def test_tool_in_reason(self):
        cat = infer_failure_category(status="failed", reason="tool execution error")
        self.assertEqual(cat, FailureCategory.TOOL_ERROR)

    def test_eval_action_retry(self):
        cat = infer_failure_category(
            status="failed", reason="low quality", eval_action="retry"
        )
        self.assertEqual(cat, FailureCategory.TASK_QUALITY_ERROR)

    def test_eval_action_fail(self):
        cat = infer_failure_category(
            status="failed", reason="fatal error", eval_action="fail"
        )
        self.assertEqual(cat, FailureCategory.TASK_QUALITY_ERROR)

    def test_unknown_fallback(self):
        cat = infer_failure_category(status="failed", reason="unexpected crash")
        self.assertEqual(cat, FailureCategory.UNKNOWN)


# =============================================================================
# classify_failure (legacy)
# =============================================================================

class ClassifyFailureTest(unittest.TestCase):

    def test_returns_failure_record_with_category(self):
        rec = classify_failure(
            status="timed_out", reason="timeout", agent_name="test_agent"
        )
        self.assertIsInstance(rec, FailureRecord)
        self.assertEqual(rec.category, FailureCategory.PROVIDER_ERROR)
        self.assertEqual(rec.agent_name, "test_agent")

    def test_guardrail_status_maps_to_guardrail_blocked(self):
        rec = classify_failure(
            status="guardrail_blocked",
            reason="blocked by guard",
            event_type="guardrail_violation",
        )
        self.assertEqual(rec.category, FailureCategory.GUARDRAIL_BLOCKED)

    def test_includes_agent_name(self):
        rec = classify_failure(status="failed", reason="something", agent_name="worker")
        self.assertEqual(rec.agent_name, "worker")


# =============================================================================
# FailureCategory enum
# =============================================================================

class FailureCategoryTest(unittest.TestCase):

    def test_has_expected_categories(self):
        expected = {"provider_error", "task_quality_error", "guardrail_blocked",
                     "tool_error", "policy_error", "unknown"}
        self.assertEqual(set(FailureCategory), expected)


# =============================================================================
# FailureReason enum
# =============================================================================

class FailureReasonTest(unittest.TestCase):

    def test_provider_reasons_exist(self):
        provider_reasons = {
            FailureReason.AUTH, FailureReason.AUTH_PERMANENT,
            FailureReason.BILLING, FailureReason.RATE_LIMIT,
            FailureReason.TIMEOUT, FailureReason.OVERLOADED,
            FailureReason.SERVER_ERROR, FailureReason.CONTEXT_OVERFLOW,
            FailureReason.MODEL_NOT_FOUND, FailureReason.FORMAT_ERROR,
        }
        for r in provider_reasons:
            self.assertIsInstance(r, FailureReason)

    def test_tool_loop_reasons_exist(self):
        self.assertIsInstance(FailureReason.EXACT_REPEATED_TOOL_FAILURE, FailureReason)
        self.assertIsInstance(FailureReason.SAME_TOOL_REPEATED_FAILURE, FailureReason)
        self.assertIsInstance(FailureReason.IDEMPOTENT_NO_PROGRESS, FailureReason)

    def test_policy_reasons_exist(self):
        self.assertIsInstance(FailureReason.PROTECTED_FILE_CHANGE, FailureReason)
        self.assertIsInstance(FailureReason.HIGH_RISK_TOOL, FailureReason)
        self.assertIsInstance(FailureReason.REVIEWER_WRITE_ATTEMPT, FailureReason)


# =============================================================================
# Named recovery-mapping contract tests (spec-required)
# =============================================================================

class RecoveryMappingContractTest(unittest.TestCase):
    """Each test is a named product contract.  If one fails, the spec is broken."""

    def test_timeout_maps_to_retry_with_backoff(self):
        self.assertEqual(
            RECOVERY_HINT_MAP[FailureReason.TIMEOUT],
            "retry_with_backoff",
        )

    def test_context_overflow_maps_to_compress_context(self):
        self.assertEqual(
            RECOVERY_HINT_MAP[FailureReason.CONTEXT_OVERFLOW],
            "compress_context",
        )

    def test_billing_does_not_blind_retry(self):
        self.assertEqual(
            RECOVERY_HINT_MAP[FailureReason.BILLING],
            "fail",
        )
        self.assertIn(FailureReason.BILLING, _NON_RETRYABLE_REASONS)

    def test_missing_evidence_requests_evidence(self):
        self.assertEqual(
            RECOVERY_HINT_MAP[FailureReason.MISSING_EVIDENCE],
            "request_evidence",
        )

    def test_unknown_failure_uses_safe_fallback(self):
        self.assertEqual(
            RECOVERY_HINT_MAP[FailureReason.UNKNOWN],
            "fail",
        )
        self.assertIn(FailureReason.UNKNOWN, RECOVERY_HINT_MAP)
