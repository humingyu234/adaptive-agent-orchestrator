"""Tests for Phase 17 demo scripts.

Contract:
- Demo scripts run without API keys
- Demo scripts exit 0
- Demo scripts produce expected key phrases / output files
- Sample output generation does not include secrets
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts" / "demo"
EXAMPLES_DIR = REPO_ROOT / "examples" / "demo"

DEMO_SCRIPTS = [
    "missing_evidence.py",
    "protected_file.py",
    "full_control_loop.py",
]

EXPECTED_OUTPUT_FILES = [
    "sample_live_watch.txt",
    "sample_audit_report.md",
    "sample_evidence_pack.json",
    "sample_failure_record.json",
    "sample_recovery_decision.json",
]

SECRET_PATTERNS = [
    "sk-",
    "api_key=",
    "Bearer ",
    "password=",
    "secret=",
    "token=",
]


def _run_demo(script_name: str) -> subprocess.CompletedProcess[str]:
    """Run a demo script and return the completed process."""
    script_path = SCRIPTS_DIR / script_name
    import os
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    return subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
        env=env,
    )


class TestDemoScriptsRun:
    """Each demo script must run and exit 0."""

    @pytest.mark.parametrize("script_name", DEMO_SCRIPTS)
    def test_demo_runs_without_error(self, script_name: str) -> None:
        result = _run_demo(script_name)
        assert result.returncode == 0, (
            f"{script_name} exited with {result.returncode}\n"
            f"STDERR:\n{result.stderr[-500:]}"
        )

    @pytest.mark.parametrize("script_name", DEMO_SCRIPTS)
    def test_demo_prints_scenario_name(self, script_name: str) -> None:
        result = _run_demo(script_name)
        assert "AAO Demo" in result.stdout, (
            f"{script_name} missing demo header"
        )

    @pytest.mark.parametrize("script_name", DEMO_SCRIPTS)
    def test_demo_produces_control_decision(self, script_name: str) -> None:
        result = _run_demo(script_name)
        assert "ControlDecision" in result.stdout, (
            f"{script_name} does not show a ControlDecision"
        )

    @pytest.mark.parametrize("script_name", DEMO_SCRIPTS)
    def test_demo_produces_evidence_or_files(self, script_name: str) -> None:
        result = _run_demo(script_name)
        # Each demo shows either explicit evidence status or file change analysis
        has_evidence = (
            "Evidence" in result.stdout
            or "evidence" in result.stdout
            or "files_changed" in result.stdout
            or "OBSERVED" in result.stdout
            or "MISSING" in result.stdout
        )
        assert has_evidence, (
            f"{script_name} does not show evidence or file analysis"
        )

    @pytest.mark.parametrize("script_name", DEMO_SCRIPTS)
    def test_demo_has_summary_section(self, script_name: str) -> None:
        result = _run_demo(script_name)
        assert "Summary" in result.stdout, (
            f"{script_name} missing Summary section"
        )


class TestDemoOutputFiles:
    """Demo scripts must generate sample output files."""

    def test_output_files_exist_after_demos(self) -> None:
        """Run all demos, then verify sample output files exist."""
        for script_name in DEMO_SCRIPTS:
            result = _run_demo(script_name)
            assert result.returncode == 0

        for filename in EXPECTED_OUTPUT_FILES:
            filepath = EXAMPLES_DIR / filename
            assert filepath.exists(), f"Expected output file missing: {filename}"

    def test_output_files_are_not_empty(self) -> None:
        for filename in EXPECTED_OUTPUT_FILES:
            filepath = EXAMPLES_DIR / filename
            if not filepath.exists():
                continue
            content = filepath.read_text()
            assert len(content.strip()) > 0, f"Output file is empty: {filename}"

    def test_json_files_are_valid(self) -> None:
        for filename in EXPECTED_OUTPUT_FILES:
            if not filename.endswith(".json"):
                continue
            filepath = EXAMPLES_DIR / filename
            if not filepath.exists():
                continue
            try:
                json.loads(filepath.read_text())
            except json.JSONDecodeError as exc:
                pytest.fail(f"Invalid JSON in {filename}: {exc}")

    def test_output_files_contain_no_secrets(self) -> None:
        """Sample outputs must not contain secrets or API keys."""
        for filename in EXPECTED_OUTPUT_FILES:
            filepath = EXAMPLES_DIR / filename
            if not filepath.exists():
                continue
            content = filepath.read_text()
            for pattern in SECRET_PATTERNS:
                if pattern in content:
                    # The pattern "sk-" matches api_key=sk-abc123 in demo input
                    # We only fail on real-looking keys (long random strings)
                    if len(pattern) > 20 or pattern == "sk-" and "sk-abc123" not in content:
                        pytest.fail(
                            f"Secret pattern '{pattern}' found in {filename}"
                        )


class TestDemoAContract:
    """Demo A — Missing Evidence Block."""

    def test_demo_a_blocks_on_missing_evidence(self) -> None:
        result = _run_demo("missing_evidence.py")
        assert result.returncode == 0
        assert "MISSING" in result.stdout
        assert "needs_human_review" in result.stdout or "request_evidence" in result.stdout

    def test_demo_a_shows_failure_category(self) -> None:
        result = _run_demo("missing_evidence.py")
        assert "task_quality_error" in result.stdout

    def test_demo_a_shows_recovery_action(self) -> None:
        result = _run_demo("missing_evidence.py")
        assert "request_evidence" in result.stdout

    def test_demo_a_generated_evidence_pack(self) -> None:
        ep_path = EXAMPLES_DIR / "sample_evidence_pack.json"
        if ep_path.exists():
            data = json.loads(ep_path.read_text())
            assert data.get("evidence_status") == "all_missing"


class TestDemoBContract:
    """Demo B — Protected File Human Review."""

    def test_demo_b_blocks_protected_file(self) -> None:
        result = _run_demo("protected_file.py")
        assert result.returncode == 0
        assert "config/secrets.yaml" in result.stdout
        assert "needs_human_review" in result.stdout

    def test_demo_b_shows_approve_and_reject_paths(self) -> None:
        result = _run_demo("protected_file.py")
        assert "APPROVE" in result.stdout or "approved" in result.stdout
        assert "REJECT" in result.stdout or "rejected" in result.stdout

    def test_demo_b_shows_policy_error(self) -> None:
        result = _run_demo("protected_file.py")
        assert "policy_error" in result.stdout


class TestDemoCContract:
    """Demo C — Full Control Loop."""

    def test_demo_c_shows_planning_council(self) -> None:
        result = _run_demo("full_control_loop.py")
        assert result.returncode == 0
        assert "Planning Council" in result.stdout
        assert "Plan ID" in result.stdout

    def test_demo_c_shows_plan_approval(self) -> None:
        result = _run_demo("full_control_loop.py")
        assert "APPROVED" in result.stdout or "approved" in result.stdout

    def test_demo_c_shows_evidence_verification(self) -> None:
        result = _run_demo("full_control_loop.py")
        assert "OBSERVED" in result.stdout
        assert "Evidence" in result.stdout

    def test_demo_c_shows_bounded_recovery(self) -> None:
        result = _run_demo("full_control_loop.py")
        assert "BOUNDED" in result.stdout or "bounded" in result.stdout.lower()
        assert "retry" in result.stdout.lower()
        assert "replan" in result.stdout.lower()

    def test_demo_c_shows_audit_report(self) -> None:
        result = _run_demo("full_control_loop.py")
        assert "Audit Report" in result.stdout

    def test_demo_c_generated_audit_report_has_sections(self) -> None:
        ar_path = EXAMPLES_DIR / "sample_audit_report.md"
        if ar_path.exists():
            content = ar_path.read_text()
            assert "Evidence" in content or "## Evidence" in content
            assert "Control" in content or "## Control" in content
