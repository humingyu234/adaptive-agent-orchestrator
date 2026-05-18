"""Tests for tool-loop guardrail detection."""

import unittest

from orchestrator.guardrails import (
    ToolCallGuardrailController,
    ToolLoopAction,
    ToolLoopDetection,
    ToolLoopType,
    _ToolCallRecord,
    _make_hash,
)
from orchestrator.failure_taxonomy import FailureReason


class ToolCallGuardrailControllerTest(unittest.TestCase):
    """ToolCallGuardrailController detects 3 tool-loop types."""

    def setUp(self):
        self.gc = ToolCallGuardrailController(
            max_exact_repeats=2,
            max_same_tool_failures=3,
            max_idempotent_calls=3,
        )

    # ------------------------------------------------------------------
    # exact repeated failure — block
    # ------------------------------------------------------------------

    def test_exact_repeated_failure_blocked(self):
        for _ in range(3):  # max_exact=2 → needs 3 failures for block
            self.gc.record_call(
                "search", {"query": "hello"}, {"error": "timeout"},
                success=False,
            )
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.BLOCK)
        self.assertEqual(detection.loop_type, ToolLoopType.EXACT_REPEATED_FAILURE)
        self.assertEqual(detection.tool_name, "search")
        self.assertEqual(
            detection.failure_reason, FailureReason.EXACT_REPEATED_TOOL_FAILURE
        )

    def test_exact_repeated_failure_not_detected_when_args_differ(self):
        self.gc.record_call("search", {"query": "a"}, {"error": "fail"}, success=False)
        self.gc.record_call("search", {"query": "b"}, {"error": "fail"}, success=False)
        self.gc.record_call("search", {"query": "c"}, {"error": "fail"}, success=False)
        detection = self.gc.check()
        self.assertNotEqual(
            detection.loop_type, ToolLoopType.EXACT_REPEATED_FAILURE
        )

    def test_exact_repeated_failure_reset_by_success(self):
        self.gc.record_call("search", {"q": "x"}, {"error": "fail"}, success=False)
        self.gc.record_call("search", {"q": "x"}, {"error": "fail"}, success=False)
        self.gc.record_call("search", {"q": "x"}, {"ok": "data"}, success=True)
        self.gc.record_call("search", {"q": "x"}, {"error": "fail"}, success=False)
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW,
                         "A success between failures should reset the exact-repeat window")

    # ------------------------------------------------------------------
    # same-tool repeated failure — block
    # ------------------------------------------------------------------

    def test_same_tool_repeated_failure_blocked(self):
        for i in range(4):  # max_same_tool=3 → needs 4 for block
            self.gc.record_call(
                "search", {"query": str(i)}, {"error": "fail"},
                success=False,
            )
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.BLOCK)
        self.assertEqual(detection.loop_type, ToolLoopType.SAME_TOOL_REPEATED_FAILURE)
        self.assertEqual(detection.tool_name, "search")
        self.assertEqual(
            detection.failure_reason, FailureReason.SAME_TOOL_REPEATED_FAILURE
        )

    def test_same_tool_repeated_failure_different_tools_ok(self):
        self.gc.record_call("tool_a", {"x": 1}, {"error": "fail"}, success=False)
        self.gc.record_call("tool_b", {"x": 2}, {"error": "fail"}, success=False)
        self.gc.record_call("tool_a", {"x": 3}, {"error": "fail"}, success=False)
        self.gc.record_call("tool_b", {"x": 4}, {"error": "fail"}, success=False)
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW)

    def test_same_tool_repeated_failure_reset_by_success(self):
        for i in range(3):
            self.gc.record_call("search", {"q": str(i)}, {"error": "x"}, success=False)
        self.gc.record_call("search", {"q": "ok"}, {"data": 1}, success=True)
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW)

    # ------------------------------------------------------------------
    # idempotent no-progress — halt
    # ------------------------------------------------------------------

    def test_idempotent_no_progress_halted(self):
        for _ in range(4):  # max_idempotent=3 → needs 4 for halt
            self.gc.record_call(
                "list_files", {"path": "."}, ["a.txt"],
                success=True,
            )
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.HALT)
        self.assertEqual(detection.loop_type, ToolLoopType.IDEMPOTENT_NO_PROGRESS)
        self.assertEqual(
            detection.failure_reason, FailureReason.IDEMPOTENT_NO_PROGRESS
        )

    def test_idempotent_no_progress_not_detected_when_result_differs(self):
        self.gc.record_call("list_files", {"path": "."}, ["a.txt"], success=True)
        self.gc.record_call("list_files", {"path": "."}, ["a.txt"], success=True)
        self.gc.record_call("list_files", {"path": "."}, ["a.txt"], success=True)
        self.gc.record_call("list_files", {"path": "."}, ["b.txt"], success=True)
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW)

    def test_idempotent_no_progress_not_detected_on_failures(self):
        for _ in range(4):
            self.gc.record_call(
                "list_files", {"path": "."}, {"error": "fail"},
                success=False,
            )
        detection = self.gc.check()
        self.assertNotEqual(
            detection.loop_type, ToolLoopType.IDEMPOTENT_NO_PROGRESS
        )

    def test_idempotent_no_progress_requires_same_tool_name(self):
        """P2.5: tool-name consistency must be verified in idempotent check."""
        self.gc.record_call("tool_a", {"x": 1}, ["same"], success=True)
        self.gc.record_call("tool_b", {"x": 2}, ["same"], success=True)
        self.gc.record_call("tool_a", {"x": 3}, ["same"], success=True)
        self.gc.record_call("tool_b", {"x": 4}, ["same"], success=True)
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW,
                         "Different tools with same result should not trigger idempotent detection")

    # ------------------------------------------------------------------
    # empty history
    # ------------------------------------------------------------------

    def test_empty_history_no_detection(self):
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW)
        self.assertIsNone(detection.loop_type)

    def test_single_call_no_detection(self):
        self.gc.record_call("search", {"q": "x"}, ["result"], success=True)
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW)

    # ------------------------------------------------------------------
    # reset
    # ------------------------------------------------------------------

    def test_reset_clears_history(self):
        for _ in range(3):
            self.gc.record_call("search", {"q": "x"}, {"error": "fail"}, success=False)
        self.assertEqual(self.gc.history_len, 3)
        self.gc.reset()
        self.assertEqual(self.gc.history_len, 0)
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW)

    # ------------------------------------------------------------------
    # custom thresholds
    # ------------------------------------------------------------------

    def test_custom_thresholds(self):
        gc = ToolCallGuardrailController(
            max_exact_repeats=1,
        )
        gc.record_call("tool", {"x": 1}, {"error": "fail"}, success=False)
        gc.record_call("tool", {"x": 1}, {"error": "fail"}, success=False)
        detection = gc.check()
        self.assertEqual(detection.action, ToolLoopAction.BLOCK)
        self.assertEqual(detection.loop_type, ToolLoopType.EXACT_REPEATED_FAILURE)

    # ------------------------------------------------------------------
    # ordering: exact-repeat checked before same-tool
    # ------------------------------------------------------------------

    def test_exact_repeat_takes_priority_over_same_tool(self):
        for _ in range(4):
            self.gc.record_call(
                "search", {"query": "exact"}, {"error": "fail"},
                success=False,
            )
        detection = self.gc.check()
        self.assertEqual(
            detection.loop_type, ToolLoopType.EXACT_REPEATED_FAILURE,
            "Exact-repeat should be detected before same-tool",
        )

    # ------------------------------------------------------------------
    # P2.3: warn vs block threshold separation
    # ------------------------------------------------------------------

    def test_warn_before_block_for_exact_repeated_failure(self):
        """Warn threshold fires before block threshold."""
        gc = ToolCallGuardrailController(
            max_exact_repeats=3,
            warn_exact_repeats=1,
        )
        # 2 consecutive exact failures → warn (warn_exact=1 → needs 2)
        gc.record_call("tool", {"x": 1}, {"error": "fail"}, success=False)
        gc.record_call("tool", {"x": 1}, {"error": "fail"}, success=False)
        detection = gc.check()
        self.assertEqual(detection.action, ToolLoopAction.WARN)
        self.assertEqual(detection.loop_type, ToolLoopType.EXACT_REPEATED_FAILURE)

        # 2 more → block (max_exact=3 → needs 4)
        gc.record_call("tool", {"x": 1}, {"error": "fail"}, success=False)
        gc.record_call("tool", {"x": 1}, {"error": "fail"}, success=False)
        detection = gc.check()
        self.assertEqual(detection.action, ToolLoopAction.BLOCK)

    def test_warn_before_block_for_same_tool_failure(self):
        """Warn threshold fires before block threshold for same-tool failures."""
        gc = ToolCallGuardrailController(
            max_same_tool_failures=4,
            warn_same_tool_failures=2,
        )
        # 3 consecutive same-tool failures → warn
        for i in range(3):
            gc.record_call("search", {"q": str(i)}, {"error": "fail"}, success=False)
        detection = gc.check()
        self.assertEqual(detection.action, ToolLoopAction.WARN)

        # 2 more → block (max_same_tool=4 → needs 5)
        for i in range(3, 5):
            gc.record_call("search", {"q": str(i)}, {"error": "fail"}, success=False)
        detection = gc.check()
        self.assertEqual(detection.action, ToolLoopAction.BLOCK)

    def test_warn_before_halt_for_idempotent_no_progress(self):
        """Warn threshold fires before halt for idempotent no-progress."""
        gc = ToolCallGuardrailController(
            max_idempotent_calls=4,
            warn_idempotent_calls=2,
        )
        # 3 consecutive same results → warn
        for _ in range(3):
            gc.record_call("list", {"path": "."}, ["a.txt"], success=True)
        detection = gc.check()
        self.assertEqual(detection.action, ToolLoopAction.WARN)
        self.assertEqual(detection.loop_type, ToolLoopType.IDEMPOTENT_NO_PROGRESS)

        # 2 more → halt (max_idempotent=4 → needs 5)
        for _ in range(2):
            gc.record_call("list", {"path": "."}, ["a.txt"], success=True)
        detection = gc.check()
        self.assertEqual(detection.action, ToolLoopAction.HALT)

    def test_warn_defaults_to_one_less_than_block(self):
        """When warn thresholds are not set, they default to max(1, block-1)."""
        gc = ToolCallGuardrailController(max_exact_repeats=2)
        self.assertEqual(gc._warn_exact, 1)

    # ------------------------------------------------------------------
    # P1: metadata does not expose raw sensitive arguments
    # ------------------------------------------------------------------

    def test_tool_loop_metadata_does_not_expose_raw_sensitive_arguments(self):
        """_ToolCallRecord must store only hashes, never raw args or results."""
        sensitive_args = {"api_key": "sk-abc123", "password": "s3cret"}
        sensitive_result = {"token": "bearer-xyz789"}

        gc = ToolCallGuardrailController(max_exact_repeats=2)
        gc.record_call("auth", sensitive_args, sensitive_result, success=True)

        record = gc._history[0]

        # _ToolCallRecord must only have args_hash and result_hash
        self.assertTrue(hasattr(record, "args_hash"))
        self.assertTrue(hasattr(record, "result_hash"))
        self.assertFalse(hasattr(record, "args"),
                         "_ToolCallRecord must not expose raw args")
        self.assertFalse(hasattr(record, "result"),
                         "_ToolCallRecord must not expose raw result")

        # The hashes must not be reversible to the original values
        raw_args_json_contains_key = "sk-abc123" in record.args_hash
        raw_result_json_contains_token = "bearer-xyz789" in record.result_hash
        self.assertFalse(raw_args_json_contains_key,
                         "args_hash must not contain raw sensitive values")
        self.assertFalse(raw_result_json_contains_token,
                         "result_hash must not contain raw sensitive values")

        # Hash must be deterministic
        self.assertEqual(
            _make_hash(sensitive_args),
            _make_hash(sensitive_args),
            "Hash must be deterministic for the same input",
        )

    # ------------------------------------------------------------------
    # P2.4: action field values
    # ------------------------------------------------------------------

    def test_allow_action_when_nothing_detected(self):
        detection = self.gc.check()
        self.assertEqual(detection.action, ToolLoopAction.ALLOW)

    def test_block_action_for_exact_repeat(self):
        for _ in range(3):
            self.gc.record_call("tool", {"x": 1}, {"error": "fail"}, success=False)
        self.assertEqual(self.gc.check().action, ToolLoopAction.BLOCK)

    def test_halt_action_for_idempotent_no_progress(self):
        for _ in range(4):
            self.gc.record_call("list", {"path": "."}, ["same"], success=True)
        self.assertEqual(self.gc.check().action, ToolLoopAction.HALT)

    def test_action_enum_has_expected_values(self):
        expected = {"allow", "warn", "block", "halt"}
        self.assertEqual(set(ToolLoopAction), expected)
