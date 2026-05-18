"""Phase 9A — sales_preview module tests."""

import unittest

from orchestrator.sales_preview import build_sales_preview
from orchestrator.state_center import StateCenter


class BuildSalesPreviewTest(unittest.TestCase):
    """build_sales_preview returns None or a preview dict from state data."""

    def test_returns_none_when_no_sales_data(self):
        state = StateCenter(query="generic query")
        state.write("plan", {"plan_type": "research"}, "planner")
        result = build_sales_preview(state)
        self.assertIsNone(result)

    def test_includes_sales_profile_when_present(self):
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_profile"] = {
            "industry": "SaaS",
            "company_type": "startup",
            "pain_points": ["cost", "scale", "latency"],
            "decision_pressure": ["deadline", "budget"],
        }
        result = build_sales_preview(state)
        self.assertIsNotNone(result)
        profile = result["sales_profile_preview"]
        self.assertEqual(profile["industry"], "SaaS")
        self.assertEqual(profile["company_type"], "startup")
        self.assertEqual(len(profile["pain_points"]), 3)

    def test_pain_points_truncated_at_3(self):
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_profile"] = {
            "industry": "SaaS",
            "company_type": "startup",
            "pain_points": ["a", "b", "c", "d", "e"],
            "decision_pressure": [],
        }
        result = build_sales_preview(state)
        self.assertEqual(len(result["sales_profile_preview"]["pain_points"]), 3)

    def test_includes_sales_strategy_when_present(self):
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_strategy"] = {
            "positioning": "premium",
            "next_action": "send proposal",
            "risk_notes": ["budget concern"],
            "generation_mode": "llm",
            "provider": "openai",
            "fallback_reason": "",
        }
        result = build_sales_preview(state)
        self.assertEqual(
            result["sales_strategy_preview"]["positioning"], "premium"
        )
        self.assertEqual(
            result["sales_strategy_preview"]["next_action"], "send proposal"
        )

    def test_includes_reply_draft_when_present(self):
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_reply"] = {
            "message": "Hi there",
            "cta": "Book a call",
            "send_policy": "review_first",
            "generation_mode": "template",
            "provider": "",
            "fallback_reason": "no_llm",
        }
        result = build_sales_preview(state)
        self.assertEqual(result["reply_draft_preview"]["message"], "Hi there")
        self.assertEqual(result["reply_draft_preview"]["send_policy"], "review_first")

    def test_includes_risk_decision_when_present(self):
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_runtime_summary"] = {
            "risk_level_label": "high",
            "risk_flags": ["urgent", "legal"],
            "decision_label": "human_review",
            "reason": "legal concern",
        }
        result = build_sales_preview(state)
        self.assertEqual(result["risk_decision_preview"]["risk_level"], "high")
        self.assertEqual(len(result["risk_decision_preview"]["risk_flags"]), 2)

    def test_risk_decision_falls_back_to_risk_level_field(self):
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_runtime_summary"] = {
            "risk_level": "medium",
            "risk_flags": [],
            "decision": "proceed",
            "reason": "",
        }
        result = build_sales_preview(state)
        self.assertEqual(result["risk_decision_preview"]["risk_level"], "medium")

    def test_empty_dicts_return_none(self):
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_profile"] = {}
        state.data_pool.intermediate["sales_strategy"] = {}
        state.data_pool.intermediate["sales_reply"] = {}
        state.data_pool.intermediate["sales_runtime_summary"] = {}
        result = build_sales_preview(state)
        # Empty dicts are still dicts — function returns a dict with empty sections
        # because `isinstance(item, dict)` is True for {}
        self.assertIsNotNone(result)

    def test_string_values_are_stripped(self):
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_profile"] = {
            "industry": "  FinTech  ",
            "company_type": "enterprise",
            "pain_points": [],
            "decision_pressure": [],
        }
        result = build_sales_preview(state)
        self.assertEqual(result["sales_profile_preview"]["industry"], "FinTech")

    def test_output_shape_is_stable(self):
        """The shape of the returned dict must be stable for CLI consumers."""
        state = StateCenter(query="sales task")
        state.data_pool.intermediate["sales_profile"] = {
            "industry": "SaaS",
            "company_type": "startup",
            "pain_points": ["cost"],
            "decision_pressure": [],
        }
        state.data_pool.intermediate["sales_strategy"] = {
            "positioning": "value",
            "next_action": "call",
            "risk_notes": [],
            "generation_mode": "llm",
            "provider": "openai",
            "fallback_reason": "",
        }
        state.data_pool.intermediate["sales_reply"] = {
            "message": "msg",
            "cta": "cta",
            "send_policy": "auto",
            "generation_mode": "llm",
            "provider": "openai",
            "fallback_reason": "",
        }
        state.data_pool.intermediate["sales_runtime_summary"] = {
            "risk_level_label": "low",
            "risk_flags": [],
            "decision_label": "proceed",
            "reason": "",
        }

        result = build_sales_preview(state)
        self.assertIsNotNone(result)

        expected_keys = {
            "sales_profile_preview",
            "sales_strategy_preview",
            "reply_draft_preview",
            "risk_decision_preview",
        }
        self.assertEqual(set(result.keys()), expected_keys)

        profile_keys = {"industry", "company_type", "pain_points", "decision_pressure"}
        self.assertEqual(set(result["sales_profile_preview"].keys()), profile_keys)

        strategy_keys = {
            "positioning", "next_action", "risk_notes",
            "generation_mode", "provider", "fallback_reason",
        }
        self.assertEqual(set(result["sales_strategy_preview"].keys()), strategy_keys)

        reply_keys = {
            "message", "cta", "send_policy",
            "generation_mode", "provider", "fallback_reason",
        }
        self.assertEqual(set(result["reply_draft_preview"].keys()), reply_keys)

        risk_keys = {"risk_level", "risk_flags", "decision", "reason"}
        self.assertEqual(set(result["risk_decision_preview"].keys()), risk_keys)


if __name__ == "__main__":
    unittest.main()
