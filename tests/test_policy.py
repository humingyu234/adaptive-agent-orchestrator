import tempfile
import unittest
from pathlib import Path

from orchestrator.policy import Policy, load_policy


class PolicyDefaultsTest(unittest.TestCase):
    """Safe defaults — empty policy blocks nothing."""

    def test_default_policy_allows_any_file(self):
        policy = Policy.defaults()
        self.assertTrue(policy.is_file_allowed("anything.py"))
        self.assertTrue(policy.is_file_allowed(".env"))
        self.assertTrue(policy.is_file_allowed("secrets/token.txt"))

    def test_default_policy_protects_nothing(self):
        policy = Policy.defaults()
        self.assertFalse(policy.is_file_protected(".env"))
        self.assertFalse(policy.is_file_protected("src/main.py"))

    def test_default_policy_no_human_review_triggers(self):
        policy = Policy.defaults()
        self.assertFalse(policy.requires_human_review_for_tool("shell"))
        self.assertFalse(policy.requires_human_review_for_file(".env"))
        self.assertFalse(policy.requires_human_review_for_test_failure())

    def test_default_policy_no_required_checks(self):
        policy = Policy.defaults()
        self.assertEqual(policy.get_required_checks(), [])

    def test_default_policy_mode_is_controlled(self):
        policy = Policy.defaults()
        self.assertEqual(policy.mode, "controlled")

    def test_default_policy_all_tools_low_risk(self):
        policy = Policy.defaults()
        self.assertEqual(policy.get_tool_risk_level("shell"), "low")
        self.assertEqual(policy.get_tool_risk_level("unknown_tool"), "low")


class PolicyFileRulesTest(unittest.TestCase):
    """File allow / protect rules."""

    def setUp(self):
        self.policy = Policy.from_dict({
            "mode": "controlled",
            "files": {
                "allowed": ["src/**", "tests/**"],
                "protected": [".env", "secrets/**", "outputs/**"],
            },
        })

    def test_allowed_file_passes(self):
        self.assertTrue(self.policy.is_file_allowed("src/orchestrator/scheduler.py"))
        self.assertTrue(self.policy.is_file_allowed("tests/test_policy.py"))

    def test_file_outside_allowed_list_is_blocked(self):
        self.assertFalse(self.policy.is_file_allowed("README.md"))
        self.assertFalse(self.policy.is_file_allowed("scripts/deploy.sh"))

    def test_protected_file_is_detected(self):
        self.assertTrue(self.policy.is_file_protected(".env"))
        self.assertTrue(self.policy.is_file_protected("secrets/api_key.txt"))
        self.assertTrue(self.policy.is_file_protected("outputs/reports/task.json"))

    def test_normal_file_is_not_protected(self):
        self.assertFalse(self.policy.is_file_protected("src/main.py"))
        self.assertFalse(self.policy.is_file_protected("tests/test_x.py"))

    def test_empty_allowed_list_allows_everything(self):
        policy = Policy.from_dict({"files": {"allowed": []}})
        self.assertTrue(policy.is_file_allowed("anything.py"))

    def test_empty_protected_list_protects_nothing(self):
        policy = Policy.from_dict({"files": {"protected": []}})
        self.assertFalse(policy.is_file_protected(".env"))


class PolicyToolRiskTest(unittest.TestCase):
    """Tool risk levels."""

    def setUp(self):
        self.policy = Policy.from_dict({
            "tools": {
                "shell": {"risk_level": "high"},
                "search": {"risk_level": "low"},
                "file_write": {"risk_level": "medium"},
            },
        })

    def test_high_risk_tool_detected(self):
        self.assertEqual(self.policy.get_tool_risk_level("shell"), "high")

    def test_low_risk_tool_detected(self):
        self.assertEqual(self.policy.get_tool_risk_level("search"), "low")

    def test_unknown_tool_defaults_to_low(self):
        self.assertEqual(self.policy.get_tool_risk_level("nonexistent"), "low")

    def test_tool_risk_from_string_value(self):
        policy = Policy.from_dict({"tools": {"shell": "high"}})
        self.assertEqual(policy.get_tool_risk_level("shell"), "high")


class PolicyHumanReviewTest(unittest.TestCase):
    """Human review triggers."""

    def setUp(self):
        self.policy = Policy.from_dict({
            "human_review": {
                "required_for": [
                    "high_risk_tool",
                    "protected_file_change",
                    "failed_tests",
                ],
            },
            "tools": {
                "shell": {"risk_level": "high"},
                "search": {"risk_level": "low"},
            },
            "files": {
                "protected": [".env", "secrets/**"],
            },
        })

    def test_high_risk_tool_requires_human_review(self):
        self.assertTrue(self.policy.requires_human_review_for_tool("shell"))

    def test_low_risk_tool_does_not_require_human_review(self):
        self.assertFalse(self.policy.requires_human_review_for_tool("search"))

    def test_protected_file_change_requires_human_review(self):
        self.assertTrue(self.policy.requires_human_review_for_file(".env"))
        self.assertTrue(self.policy.requires_human_review_for_file("secrets/token.txt"))

    def test_normal_file_does_not_require_human_review(self):
        self.assertFalse(self.policy.requires_human_review_for_file("src/main.py"))

    def test_failed_tests_trigger_human_review(self):
        self.assertTrue(self.policy.requires_human_review_for_test_failure())

    def test_high_risk_tool_not_triggered_when_not_in_list(self):
        policy = Policy.from_dict({
            "human_review": {"required_for": ["failed_tests"]},
            "tools": {"shell": {"risk_level": "high"}},
        })
        self.assertFalse(policy.requires_human_review_for_tool("shell"))

    def test_protected_file_not_triggered_when_not_in_list(self):
        policy = Policy.from_dict({
            "human_review": {"required_for": ["failed_tests"]},
            "files": {"protected": [".env"]},
        })
        self.assertFalse(policy.requires_human_review_for_file(".env"))


class PolicyRequiredChecksTest(unittest.TestCase):
    """Required checks extraction."""

    def test_required_checks_loaded(self):
        policy = Policy.from_dict({"checks": {"required": ["pytest", "lint"]}})
        self.assertEqual(policy.get_required_checks(), ["pytest", "lint"])

    def test_missing_checks_section_returns_empty(self):
        policy = Policy.from_dict({})
        self.assertEqual(policy.get_required_checks(), [])


class PolicyYamlTest(unittest.TestCase):
    """YAML loading."""

    def test_load_policy_from_yaml_file(self):
        import tempfile
        import os

        yaml_content = """mode: controlled

files:
  allowed:
    - src/**
  protected:
    - .env

checks:
  required:
    - pytest

human_review:
  required_for:
    - high_risk_tool

tools:
  shell:
    risk_level: high
"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            tmp_path = f.name

        try:
            policy = Policy.from_yaml(tmp_path)
            self.assertEqual(policy.mode, "controlled")
            self.assertTrue(policy.is_file_allowed("src/main.py"))
            self.assertTrue(policy.is_file_protected(".env"))
            self.assertEqual(policy.get_required_checks(), ["pytest"])
            self.assertTrue(policy.requires_human_review_for_tool("shell"))
            self.assertEqual(policy.get_tool_risk_level("shell"), "high")
        finally:
            os.unlink(tmp_path)

    def test_load_policy_returns_defaults_for_none(self):
        policy = load_policy(None)
        self.assertEqual(policy.mode, "controlled")
        self.assertTrue(policy.is_file_allowed("anything.py"))

    def test_load_policy_returns_defaults_for_missing_file(self):
        policy = load_policy("/nonexistent/policy.yaml")
        self.assertEqual(policy.mode, "controlled")

    def test_from_dict_handles_empty_dict(self):
        policy = Policy.from_dict({})
        self.assertEqual(policy.mode, "controlled")
        self.assertTrue(policy.is_file_allowed("any.py"))
        self.assertFalse(policy.is_file_protected("any.py"))
        self.assertEqual(policy.get_required_checks(), [])

    def test_from_dict_handles_none_sections(self):
        policy = Policy.from_dict({
            "mode": "controlled",
            "files": None,
            "checks": None,
            "human_review": None,
            "tools": None,
        })
        self.assertTrue(policy.is_file_allowed("any.py"))


class PolicyGlobMatchingTest(unittest.TestCase):
    """fnmatch glob patterns behave as expected."""

    def test_double_star_matches_nested_paths(self):
        policy = Policy.from_dict({"files": {"allowed": ["src/**"]}})
        self.assertTrue(policy.is_file_allowed("src/a.py"))
        self.assertTrue(policy.is_file_allowed("src/a/b.py"))
        self.assertTrue(policy.is_file_allowed("src/a/b/c/d.py"))

    def test_single_star_matches_within_directory(self):
        policy = Policy.from_dict({"files": {"allowed": ["src/*.py"]}})
        self.assertTrue(policy.is_file_allowed("src/main.py"))
        self.assertFalse(policy.is_file_allowed("src/sub/main.py"))

    def test_exact_filename_match(self):
        policy = Policy.from_dict({"files": {"protected": [".env"]}})
        self.assertTrue(policy.is_file_protected(".env"))
        self.assertFalse(policy.is_file_protected(".env.backup"))

    def test_question_mark_matches_single_char(self):
        policy = Policy.from_dict({"files": {"protected": ["secrets/?.key"]}})
        self.assertTrue(policy.is_file_protected("secrets/a.key"))
        self.assertFalse(policy.is_file_protected("secrets/ab.key"))


class PolicyModeTest(unittest.TestCase):
    """Mode field."""

    def test_mode_default_is_controlled(self):
        policy = Policy.from_dict({})
        self.assertEqual(policy.mode, "controlled")

    def test_mode_can_be_overridden(self):
        for mode in ("off", "log", "controlled", "orchestrated"):
            with self.subTest(mode=mode):
                policy = Policy.from_dict({"mode": mode})
                self.assertEqual(policy.mode, mode)


if __name__ == "__main__":
    unittest.main()

class PolicyScopeDocumentationTest(unittest.TestCase):
    """Phase 7A Fix 6 — Policy scope is documented by tests.

    These tests serve as executable documentation for Policy's default
    behaviour.  Policy is a declarative helper: it checks patterns and
    risk levels but does NOT enforce anything at runtime unless wired
    into the scheduler / ControlPlane enforcement path.
    """

    def test_policy_default_behavior_is_documented_by_tests(self):
        """Default Policy is fully permissive — blocks nothing, requires nothing.

        This is the key contract: a default-constructed Policy must never
        reject a file, never require human review, and never mandate checks.
        Any runtime enforcement must be explicitly configured.
        """
        policy = Policy.defaults()

        # File access: everything allowed, nothing protected
        self.assertTrue(policy.is_file_allowed("any/file.py"))
        self.assertTrue(policy.is_file_allowed(".env"))
        self.assertTrue(policy.is_file_allowed("secrets/keys.json"))
        self.assertFalse(policy.is_file_protected(".env"))
        self.assertFalse(policy.is_file_protected("src/main.py"))

        # Tool risk: everything is low risk by default
        self.assertEqual(policy.get_tool_risk_level("any_tool"), "low")
        self.assertEqual(policy.get_tool_risk_level("shell"), "low")

        # Human review: never required by default
        self.assertFalse(policy.requires_human_review_for_tool("shell"))
        self.assertFalse(policy.requires_human_review_for_file(".env"))
        self.assertFalse(policy.requires_human_review_for_test_failure())

        # Required checks: none by default
        self.assertEqual(policy.get_required_checks(), [])

        # Mode: controlled (uses AAO control checks)
        self.assertEqual(policy.mode, "controlled")

    def test_policy_protected_file_requires_review_when_configured(self):
        """When protected_file_change is in human_review_required_for,
        touching a protected file triggers human review."""
        policy = Policy.from_dict({
            "human_review": {"required_for": ["protected_file_change"]},
            "files": {"protected": [".env", "secrets/**"]},
        })
        self.assertTrue(policy.requires_human_review_for_file(".env"))
        self.assertTrue(policy.requires_human_review_for_file("secrets/token.txt"))
        self.assertFalse(policy.requires_human_review_for_file("src/main.py"))

    def test_policy_high_risk_tool_requires_review_when_configured(self):
        """When high_risk_tool is in human_review_required_for,
        using a high-risk tool triggers human review."""
        policy = Policy.from_dict({
            "human_review": {"required_for": ["high_risk_tool"]},
            "tools": {"shell": {"risk_level": "high"}, "search": {"risk_level": "low"}},
        })
        self.assertTrue(policy.requires_human_review_for_tool("shell"))
        self.assertFalse(policy.requires_human_review_for_tool("search"))
        self.assertFalse(policy.requires_human_review_for_tool("nonexistent"))

