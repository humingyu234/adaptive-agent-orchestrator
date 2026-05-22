"""Phase 23 — Isolated Reviewer tests.

Proves: Reviewer is read-only, trusts only observed evidence, detects
contradictions, produces ReviewFindings that MainlineExecutor converts
to FixTasks (not the reviewer itself).
"""

from __future__ import annotations

import pytest

from orchestrator.auto_repair import AutoRepairLoop, FixTask, ReviewFinding
from orchestrator.reviewer import (
    EvidenceBundle,
    FakeReviewer,
    LLMReviewer,
    Reviewer,
    RuleBasedReviewer,
)


# =============================================================================
# Helpers
# =============================================================================


def _bundle(**overrides) -> EvidenceBundle:
    """Build a minimal EvidenceBundle with sensible defaults."""
    defaults = dict(
        task_id="task-1",
        step_id="step-1",
        changed_files=["src/utils.py"],
        diff_content="--- a/src/utils.py\n+++ b/src/utils.py\n@@ -1 +1 @@\n-old\n+new",
        test_output="2 passed, 0 failed",
        result_md="Task completed successfully. Tests pass.",
        allowed_files=["src/utils.py"],
        denied_files=["src/secrets.py"],
        required_checks=["pytest"],
        worker_status="completed",
    )
    defaults.update(overrides)
    return EvidenceBundle.from_packet(**defaults)


def _blocking_finding(**overrides) -> ReviewFinding:
    defaults = dict(
        finding_id="F-001",
        step_id="step-1",
        severity="blocking",
        category="test_failure",
        description="Test output shows FAILED",
        location="observed/test_output.txt",
        source="reviewer",
    )
    defaults.update(overrides)
    return ReviewFinding(**defaults)


# =============================================================================
# Tests
# =============================================================================


class TestReviewerIsReadOnly:
    """Prove the reviewer cannot write or modify code."""

    def test_reviewer_has_no_write_or_edit_methods(self):
        """Reviewer subclasses must not expose write/edit/execute/fix methods."""
        forbidden = {"write", "edit", "execute", "fix", "modify", "patch",
                     "run", "dispatch", "apply", "commit", "push"}

        for cls in (Reviewer, RuleBasedReviewer, FakeReviewer, LLMReviewer):
            public_methods = {
                name for name in dir(cls)
                if not name.startswith("_") and callable(getattr(cls, name, None))
            }
            overlap = public_methods & forbidden
            assert not overlap, (
                f"{cls.__name__} must not expose write/edit methods, "
                f"found: {overlap}"
            )

    def test_reviewer_only_has_review_and_name(self):
        """The Reviewer ABC exposes only review() and name."""
        abstract_methods = Reviewer.__abstractmethods__
        assert "review" in abstract_methods, (
            "review() must be the abstract method"
        )
        # Only review should be abstract
        non_review = abstract_methods - {"review"}
        assert not non_review, (
            f"Unexpected abstract methods: {non_review}"
        )

    def test_evidence_bundle_is_frozen_snapshot(self):
        """EvidenceBundle is passed by value — mutating origin doesn't
        affect the bundle the reviewer sees."""
        changed = ["src/a.py"]
        diff = "old diff"
        test_out = "1 passed"
        result = "success"

        bundle = EvidenceBundle.from_packet(
            task_id="t1", step_id="s1",
            changed_files=list(changed),
            diff_content=diff,
            test_output=test_out,
            result_md=result,
        )

        # Mutate originals
        changed.append("src/secret.py")
        diff = "evil diff"
        test_out = ""

        assert bundle.changed_files == ["src/a.py"], (
            "changed_files must be a snapshot, not a live reference"
        )
        assert bundle.diff_content == "old diff"
        assert bundle.test_output == "1 passed"


class TestReviewerOnlyTrustsObservedEvidence:
    """Prove findings are based on observed evidence, not worker self-claims."""

    def test_finding_references_observed_path_not_result_md(self):
        """When test_output contains FAILED, the finding location must be
        observed/test_output.txt, not result.md."""
        bundle = _bundle(
            test_output="1 passed, 1 FAILED",
            result_md="All tests passed successfully!",
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        blocking = [f for f in findings if f.is_blocking]
        assert len(blocking) >= 1, "FAILED in test_output must produce blocking finding"

        for f in blocking:
            assert f.location == "observed/test_output.txt", (
                f"Blocking finding must reference observed/test_output.txt, "
                f"got {f.location!r}"
            )
            assert f.source == "reviewer"

    def test_finding_never_trusts_worker_status_alone(self):
        """Even when worker_status='completed', missing evidence is still blocking."""
        bundle = _bundle(
            test_output="",
            result_md="",
            diff_content="",
            changed_files=[],
            worker_status="completed",
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        missing = [f for f in findings if f.category == "missing_evidence"]
        assert len(missing) == 1, (
            "Empty evidence must produce missing_evidence regardless of worker_status"
        )
        assert missing[0].is_blocking

    def test_evidence_contradiction_detected(self):
        """Worker claims success in result_md but test_output shows FAILED."""
        bundle = _bundle(
            result_md="Task completed successfully. tests_pass=true.",
            test_output="2 passed, 3 FAILED",
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        contradictions = [f for f in findings if f.category == "evidence_contradiction"]
        assert len(contradictions) == 1, (
            "result_md claiming success while test_output shows FAILED "
            "must produce evidence_contradiction"
        )
        assert contradictions[0].is_blocking
        assert "contradicts" in contradictions[0].description.lower()

    def test_protected_action_detected_when_diff_touches_denied(self):
        """Diff changing a file outside allowed_files produces protected_action."""
        bundle = _bundle(
            changed_files=["src/utils.py", "src/secrets.py"],
            diff_content=(
                "--- a/src/utils.py\n+++ b/src/utils.py\n@@ -1 +1 @@\n-old\n+new\n"
                "--- a/src/secrets.py\n+++ b/src/secrets.py\n@@ -1 +1 @@\n-old\n+new"
            ),
            allowed_files=["src/utils.py"],
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        protected = [f for f in findings if f.category == "protected_action"]
        assert len(protected) >= 1, (
            "Diff touching files outside allowed_files must produce protected_action"
        )
        assert any("src/secrets.py" in f.description for f in protected)


class TestFindingFixTaskConversion:
    """Prove ReviewFinding → FixTask conversion (done by MainlineExecutor)."""

    def test_fix_task_from_finding_preserves_linkage(self):
        """FixTask.from_finding() correctly links back to the ReviewFinding."""
        finding = _blocking_finding(
            finding_id="F-abc123",
            step_id="step-5",
            suggested_fix="Fix the assertion on line 42",
            location="src/errors.py:42",
        )
        fix = FixTask.from_finding(
            finding,
            target_file="src/errors.py",
            verification="pytest src/errors.py",
        )

        assert fix.triggered_by_finding_id == "F-abc123"
        assert fix.step_id == "step-5"
        assert fix.target_file == "src/errors.py"
        assert fix.verification == "pytest src/errors.py"
        assert fix.fix_description == "Fix the assertion on line 42"
        assert fix.status == "pending"
        assert fix.fix_id.startswith("FT-")

    def test_fix_task_fallback_when_no_explicit_target(self):
        """FixTask uses finding.location as target_file when none provided."""
        finding = _blocking_finding(
            location="src/middleware.py:30",
            suggested_fix=None,
        )
        fix = FixTask.from_finding(finding)
        assert fix.target_file == "src/middleware.py:30"
        assert fix.verification == "pytest"
        # description becomes fix_description when suggested_fix is None
        assert fix.fix_description == finding.description

    def test_non_blocking_finding_does_not_produce_fix_task(self):
        """Non-blocking findings are skipped by AutoRepairLoop."""
        finding = _blocking_finding(severity="non_blocking")
        loop = AutoRepairLoop(max_attempts=2)

        called = False

        def dispatch(ft: FixTask) -> dict:
            nonlocal called
            called = True
            return {"status": "completed"}

        def verify(r: dict) -> bool:
            return True

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
        )
        assert not called, "Non-blocking finding must not trigger dispatch"
        assert result.status == "still_failing"
        assert result.total_rounds == 0


class TestReviewerDoesNotExecuteFixes:
    """Prove the reviewer only inspects and reports — never executes."""

    def test_rule_based_reviewer_has_no_execution_methods(self):
        """RuleBasedReviewer must not have dispatch/run/execute/apply methods."""
        rbr = RuleBasedReviewer()
        forbidden = {"dispatch", "run", "execute", "apply", "fix", "repair"}
        for name in forbidden:
            assert not hasattr(rbr, name), (
                f"RuleBasedReviewer must not expose {name}()"
            )

    def test_reviewer_review_returns_findings_not_actions(self):
        """review() returns list[ReviewFinding], never executes anything."""
        bundle = _bundle(test_output="1 FAILED")
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        assert isinstance(findings, list)
        for f in findings:
            assert isinstance(f, ReviewFinding), (
                f"review() must return ReviewFinding instances, got {type(f)}"
            )

    def test_fake_reviewer_does_not_mutate_evidence(self):
        """FakeReviewer returns configured findings without touching evidence."""
        pre_configured = [_blocking_finding()]
        reviewer = FakeReviewer(findings=pre_configured)

        bundle = _bundle()
        original_test_output = bundle.test_output
        original_diff = bundle.diff_content

        reviewer.review(bundle)

        assert bundle.test_output == original_test_output
        assert bundle.diff_content == original_diff


class TestReviewerContextIsolation:
    """Prove reviewer context is isolated from worker context."""

    def test_evidence_bundle_creates_independent_copy(self):
        """from_packet() creates a new list, not a reference to the input."""
        files = ["src/a.py"]
        bundle = EvidenceBundle.from_packet(
            task_id="t1", step_id="s1",
            changed_files=files,
        )
        files.append("src/secret.py")
        assert "src/secret.py" not in bundle.changed_files, (
            "EvidenceBundle must copy the input list"
        )

    def test_reviewer_cannot_access_worker_packet(self):
        """Reviewer only sees EvidenceBundle — no access to WorkerTaskPacket
        or the filesystem."""
        reviewer = RuleBasedReviewer()
        # The reviewer's interface takes EvidenceBundle, not WorkerTaskPacket
        import inspect
        sig = inspect.signature(reviewer.review)
        params = list(sig.parameters.keys())
        assert "evidence" in params, (
            "review() must accept 'evidence' parameter (EvidenceBundle), "
            f"got params: {params}"
        )
        # Only one parameter: evidence
        assert len(params) == 1, (
            f"review() must take exactly 1 parameter (evidence), got {len(params)}"
        )

    def test_llm_reviewer_placeholder_isolated(self):
        """LLMReviewer placeholder raises NotImplementedError — it cannot
        accidentally execute anything."""
        reviewer = LLMReviewer()
        with pytest.raises(NotImplementedError):
            reviewer.review(_bundle())


class TestNonBlockingFindings:
    """Prove non-blocking findings are recorded but don't block."""

    def test_non_blocking_finding_severity(self):
        """Non-blocking findings have is_blocking=False."""
        finding = ReviewFinding(
            finding_id="F-nb", step_id="s1",
            severity="non_blocking", category="style",
            description="Missing type annotation",
            location="src/utils.py:10",
            source="reviewer",
        )
        assert finding.is_blocking is False
        assert finding.is_system_issue is False

    def test_incomplete_reporting_is_non_blocking(self):
        """Changed files mismatch is non_blocking, not blocking."""
        bundle = _bundle(
            changed_files=["src/a.py"],
            diff_content=(
                "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-old\n+new\n"
                "--- a/src/b.py\n+++ b/src/b.py\n@@ -1 +1 @@\n-old\n+new"
            ),
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        reporting = [f for f in findings if f.category == "incomplete_reporting"]
        assert len(reporting) == 1
        assert reporting[0].severity == "non_blocking"
        assert not reporting[0].is_blocking


class TestRuleBasedReviewerDetection:
    """Prove RuleBasedReviewer correctly detects each issue type."""

    def test_detects_test_failure(self):
        bundle = _bundle(test_output="3 passed, 2 FAILED")
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        test_fails = [f for f in findings if f.category == "test_failure"]
        assert len(test_fails) == 1
        assert test_fails[0].is_blocking

    def test_detects_missing_evidence(self):
        bundle = _bundle(
            test_output="", result_md="", diff_content="", changed_files=[],
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        missing = [f for f in findings if f.category == "missing_evidence"]
        assert len(missing) == 1
        assert missing[0].is_blocking

    def test_no_false_positives_on_clean_evidence(self):
        """Clean evidence with no issues produces no blocking findings."""
        bundle = _bundle(
            test_output="5 passed, 0 failed",
            result_md="Task completed. All tests pass.",
            diff_content="--- a/src/utils.py\n+++ b/src/utils.py\n@@ -1 +1 @@\n-old\n+new",
            changed_files=["src/utils.py"],
            allowed_files=["src/utils.py"],
            worker_status="completed",
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        blocking = [f for f in findings if f.is_blocking]
        assert len(blocking) == 0, (
            f"Clean evidence must not produce blocking findings, got: "
            f"{[(f.category, f.description) for f in blocking]}"
        )

    def test_detects_protected_action_multiple_files(self):
        """Multiple out-of-bounds files each get their own finding."""
        bundle = _bundle(
            allowed_files=["src/a.py"],
            diff_content=(
                "--- a/src/b.py\n+++ b/src/b.py\n@@ -1 +1 @@\n-old\n+new\n"
                "--- a/src/c.py\n+++ b/src/c.py\n@@ -1 +1 @@\n-old\n+new"
            ),
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        protected = [f for f in findings if f.category == "protected_action"]
        assert len(protected) == 2, (
            f"Expected 2 protected_action findings, got {len(protected)}"
        )
        paths = {f.location for f in protected}
        assert paths == {"src/b.py", "src/c.py"}


class TestFakeReviewer:
    """Prove FakeReviewer returns exactly the configured findings."""

    def test_returns_configured_findings(self):
        configured = [
            _blocking_finding(finding_id="F-a", category="test_failure"),
            _blocking_finding(finding_id="F-b", severity="non_blocking",
                              category="style"),
        ]
        reviewer = FakeReviewer(findings=configured)
        result = reviewer.review(_bundle())

        assert len(result) == 2
        assert result[0].finding_id == "F-a"
        assert result[1].finding_id == "F-b"

    def test_set_findings_updates_configuration(self):
        reviewer = FakeReviewer(findings=[_blocking_finding(finding_id="F-old")])
        reviewer.set_findings([_blocking_finding(finding_id="F-new")])
        result = reviewer.review(_bundle())
        assert len(result) == 1
        assert result[0].finding_id == "F-new"

    def test_default_returns_empty(self):
        reviewer = FakeReviewer()
        result = reviewer.review(_bundle())
        assert result == []


class TestReviewerRejectsWorkerSelfSummary:
    """Prove reviewer does not trust worker self-summary as evidence."""

    def test_self_reported_success_without_evidence_is_blocked(self):
        """Worker claims 'All tasks completed successfully' but provides
        no test_output, no diff — reviewer must not produce a false all-clear.

        result_md alone (worker self-report) is observable as a file, so it
        does NOT trigger missing_evidence.  But the reviewer also must not
        claim the step is clean — with no test_output or diff there is
        nothing to verify, so the reviewer returns zero findings (cannot
        verify the claim, but cannot disprove it either).  The evidence
        classifier + ControlPlane handle the missing expected-evidence check.
        """
        bundle = _bundle(
            result_md="All tasks completed successfully. Everything is fine.",
            test_output="",
            diff_content="",
            changed_files=[],
            worker_status="completed",
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        # No blocking findings — there is nothing to contradict.
        # The reviewer does not trust the self-report, but it cannot
        # fabricate a contradiction without observed evidence to compare.
        blocking = [f for f in findings if f.is_blocking]
        assert len(blocking) == 0, (
            "result_md-only bundle: reviewer cannot verify or disprove; "
            "evidence classifier gates missing expected-evidence separately"
        )

    def test_self_reported_tests_pass_contradicted_by_output(self):
        """Worker says 'tests_pass=true' but test output shows FAILED."""
        bundle = _bundle(
            result_md="All good. tests_pass=true. Completed.",
            test_output="1 passed, 1 FAILED",
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        contradictions = [f for f in findings if f.category == "evidence_contradiction"]
        assert len(contradictions) == 1, (
            "Claiming tests_pass=true when output has FAILED must be caught"
        )

    def test_worker_status_field_not_used_as_evidence(self):
        """worker_status='completed' alone never satisfies evidence requirements."""
        bundle = _bundle(
            worker_status="completed",
            test_output="",
            result_md="",
            diff_content="",
            changed_files=[],
        )
        reviewer = RuleBasedReviewer()
        findings = reviewer.review(bundle)

        missing = [f for f in findings if f.category == "missing_evidence"]
        assert len(missing) == 1, (
            "worker_status alone must not satisfy evidence requirements"
        )


# =============================================================================
# Integration: Reviewer → FixTask in MainlineExecutor context
# =============================================================================


class TestReviewerMainlineIntegration:
    """Prove the reviewer findings feed correctly into the repair path."""

    def test_blocking_reviewer_finding_triggers_repair_loop(self):
        """A blocking finding from the reviewer triggers AutoRepairLoop."""
        finding = _blocking_finding(
            category="test_failure",
            location="src/utils.py:42",
            suggested_fix="Fix the assertion on line 42",
        )
        loop = AutoRepairLoop(max_attempts=1)

        dispatched = False

        def dispatch(ft: FixTask) -> dict:
            nonlocal dispatched
            dispatched = True
            assert ft.target_file == "src/utils.py:42"
            return {"status": "completed", "test_output": "2 passed, 0 failed"}

        def verify(r: dict) -> bool:
            return "0 failed" in str(r.get("test_output", ""))

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
            target_file=finding.location,
        )
        assert dispatched, "Blocking reviewer finding must dispatch FixTask"
        assert result.status == "fixed"

    def test_reviewer_finding_rounds_appear_in_repair_result(self):
        """Repair rounds from reviewer findings are properly recorded."""
        finding = _blocking_finding(
            finding_id="F-rev-1",
            description="Protected file access detected",
            category="protected_action",
            location="src/secrets.py",
        )
        loop = AutoRepairLoop(max_attempts=1)
        dispatch_calls = []

        def dispatch(ft: FixTask) -> dict:
            dispatch_calls.append(ft)
            return {"status": "completed", "test_output": "0 failed"}

        def verify(r: dict) -> bool:
            return True

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
            target_file="src/secrets.py",
        )
        assert result.total_rounds == 1
        assert len(result.rounds) == 1
        r0 = result.rounds[0]
        assert r0.finding_id == "F-rev-1"
        assert r0.status == "fixed"

    def test_mainline_executor_has_reviewer_method(self):
        """MainlineExecutor exposes _run_reviewer for evidence inspection."""
        from orchestrator.mainline_executor import MainlineExecutor

        executor = MainlineExecutor()
        assert hasattr(executor, "_run_reviewer"), (
            "MainlineExecutor must have _run_reviewer method"
        )
        assert callable(executor._run_reviewer)

    def test_auto_repair_success_returns_fix_packet_for_reviewer(self):
        """P1 fix: _try_auto_repair returns the last fix packet so the
        caller can point follow-up inspection (Phase 23 reviewer) at the
        fixed evidence instead of the stale original packet."""
        from orchestrator.mainline_executor import MainlineExecutor
        from orchestrator.worker_protocol import PacketFiles, WorkerTaskPacket

        executor = MainlineExecutor()

        # Simulate a finding whose repair will write clean test output.
        finding = _blocking_finding(
            category="test_failure",
            location="src/utils.py",
            suggested_fix="Fix the flaky assertion",
        )

        repair_result, fix_packet = executor._try_auto_repair(
            finding=finding,
            worker_mode="fake",
        )

        assert repair_result.is_fixed, (
            "Fake worker with default test-output rule should pass repair"
        )
        assert fix_packet is not None, (
            "_try_auto_repair must return the last fix packet so the caller "
            "can redirect the reviewer to it"
        )
        assert isinstance(fix_packet, WorkerTaskPacket)
        # The fix packet must have its own packet_root distinct from the
        # original task — it was created by _fix_task_to_packet.
        assert fix_packet.packet_root.exists()
        # The fix worker should have written test output to the fix packet dir.
        test_output_path = fix_packet.packet_root / PacketFiles.TEST_OUTPUT
        assert test_output_path.exists(), (
            "Fix worker must write test_output.txt to the fix packet directory"
        )


# =============================================================================
# Phase 30 — CodexReviewer tests
# =============================================================================


class _FakeCompletedProc:
    """Minimal subprocess.CompletedProcess stub."""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class TestCodexReviewer:
    """Prove CodexReviewer correctly builds prompts, parses output, and
    handles all failure modes gracefully."""

    def test_is_a_reviewer_subclass(self):
        from orchestrator.reviewer import CodexReviewer, Reviewer
        cr = CodexReviewer()
        assert isinstance(cr, Reviewer), (
            "CodexReviewer must be a Reviewer subclass"
        )

    def test_is_available_detects_codex(self):
        from orchestrator.reviewer import CodexReviewer
        # In CI/WSL without codex, is_available should return False
        # without raising.  We just verify the method exists and returns a bool.
        result = CodexReviewer.is_available()
        assert isinstance(result, bool), (
            "is_available() must return bool"
        )

    def test_review_returns_empty_when_codex_not_available(self):
        from orchestrator.reviewer import CodexReviewer
        bundle = _bundle()
        cr = CodexReviewer(timeout=5)
        # If codex is not on PATH, review returns [] immediately
        if not CodexReviewer.is_available():
            findings = cr.review(bundle)
            assert findings == [], (
                "review must return empty list when codex is not available"
            )

    def test_builds_correct_prompt(self):
        """Prompt includes all evidence sections and frames reviewer as outsider."""
        from orchestrator.reviewer import CodexReviewer

        bundle = _bundle(
            step_id="step-fix-1",
            changed_files=["src/utils.py"],
            diff_content="--- a/src/utils.py\n+++ b/src/utils.py\n-old\n+new",
            test_output="2 passed, 0 failed",
            result_md="Fixed the bug.",
            allowed_files=["src/utils.py"],
            required_checks=["pytest"],
        )
        prompt = CodexReviewer._build_prompt(bundle)

        assert "step-fix-1" in prompt
        assert "src/utils.py" in prompt
        assert "2 passed, 0 failed" in prompt
        assert "DO NOT TRUST" in prompt, (
            "Prompt must warn reviewer not to trust worker self-report"
        )
        assert "Fixed the bug." in prompt
        assert "pytest" in prompt
        assert "isolated code reviewer" in prompt.lower(), (
            "Prompt must frame reviewer as outsider"
        )

    def test_parse_output_extracts_findings(self):
        """Valid JSON with findings is correctly parsed."""
        from orchestrator.reviewer import CodexReviewer

        cr = CodexReviewer(timeout=5)
        raw = """some log noise
{
  "findings": [
    {
      "severity": "blocking",
      "category": "logic_error",
      "description": "Changed + to - instead of fixing the test",
      "location": "src/utils.py:1",
      "suggested_fix": "Change return a-b to return a+b"
    }
  ],
  "overall_pass": false
}
more noise"""

        findings = cr._parse_output(raw)
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "blocking"
        assert f.category == "logic_error"
        assert "Changed" in f.description
        assert f.location == "src/utils.py:1"
        assert f.suggested_fix is not None
        assert f.source == "reviewer"

    def test_parse_output_empty_on_malformed_json(self):
        from orchestrator.reviewer import CodexReviewer
        cr = CodexReviewer(timeout=5)

        assert cr._parse_output("not json at all") == []
        assert cr._parse_output("") == []
        assert cr._parse_output("{ invalid }") == []

    def test_parse_output_empty_on_missing_json_block(self):
        from orchestrator.reviewer import CodexReviewer
        cr = CodexReviewer(timeout=5)

        assert cr._parse_output("just text, no braces") == []

    def test_parse_output_handles_missing_fields(self):
        """Missing optional fields (suggested_fix) default to None."""
        from orchestrator.reviewer import CodexReviewer
        cr = CodexReviewer(timeout=5)

        raw = """{
  "findings": [
    {
      "severity": "non_blocking",
      "category": "style",
      "description": "Missing type hint",
      "location": "src/utils.py:5"
    }
  ],
  "overall_pass": true
}"""
        findings = cr._parse_output(raw)
        assert len(findings) == 1
        assert findings[0].suggested_fix is None

    def test_parse_output_handles_empty_findings(self):
        """A clean review with no findings returns empty list."""
        from orchestrator.reviewer import CodexReviewer
        cr = CodexReviewer(timeout=5)

        raw = '{"findings": [], "overall_pass": true}'
        findings = cr._parse_output(raw)
        assert findings == []

    def test_extract_json_finds_first_last_braces(self):
        from orchestrator.reviewer import CodexReviewer

        assert CodexReviewer._extract_json('{"a":1}') == '{"a":1}'
        assert CodexReviewer._extract_json('log\n{"a":1}\nmore') == '{"a":1}'
        assert CodexReviewer._extract_json('no braces') == ''
        assert CodexReviewer._extract_json('') == ''

    def test_review_with_mocked_codex_call(self, monkeypatch):
        """Full review() with a mocked successful codex subprocess."""
        from orchestrator.reviewer import CodexReviewer, EvidenceBundle

        # Force is_available to return True
        monkeypatch.setattr(CodexReviewer, "is_available", lambda *a: True)

        fake_output = """pre-logs
{
  "findings": [
    {
      "severity": "blocking",
      "category": "test_failure",
      "description": "Test output has 2 FAILED",
      "location": "observed/test_output.txt",
      "suggested_fix": "Fix the assertion on line 42"
    }
  ],
  "overall_pass": false
}
"""

        def fake_run(*args, **kwargs):
            proc = _FakeCompletedProc()
            proc.stdout = fake_output
            proc.returncode = 0
            return proc

        monkeypatch.setattr("orchestrator.reviewer.subprocess.run", fake_run)

        bundle = _bundle(test_output="1 passed, 2 FAILED")
        cr = CodexReviewer(timeout=5)
        findings = cr.review(bundle)

        assert len(findings) == 1
        assert findings[0].category == "test_failure"
        assert findings[0].is_blocking

    def test_review_handles_timeout(self, monkeypatch):
        from orchestrator.reviewer import CodexReviewer
        monkeypatch.setattr(CodexReviewer, "is_available", lambda *a: True)

        import subprocess as _subprocess
        monkeypatch.setattr(
            "orchestrator.reviewer.subprocess.run",
            lambda *a, **kw: (_ for _ in ()).throw(
                _subprocess.TimeoutExpired("codex", 1)
            ),
        )

        cr = CodexReviewer(timeout=5)
        findings = cr.review(_bundle())
        assert findings == [], (
            "Timeout must return empty findings, not crash"
        )

    def test_review_handles_codex_not_found(self, monkeypatch):
        from orchestrator.reviewer import CodexReviewer
        monkeypatch.setattr(CodexReviewer, "is_available", lambda *a: True)

        import subprocess as _subprocess
        monkeypatch.setattr(
            "orchestrator.reviewer.subprocess.run",
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("codex")),
        )

        cr = CodexReviewer(timeout=5)
        findings = cr.review(_bundle())
        assert findings == [], (
            "FileNotFoundError must return empty findings, not crash"
        )

    # ------------------------------------------------------------------
    # _should_invoke_codex_reviewer trigger logic (spec test plan)
    # ------------------------------------------------------------------

    @staticmethod
    def _patch_codex_available(monkeypatch, available: bool):
        """Patch shutil.which so codex appears present or absent.

        The method does ``import shutil`` inside the function body, so we
        must patch the real ``shutil`` module in sys.modules.
        """
        import shutil as _shutil
        monkeypatch.setattr(_shutil, "which", lambda _x: "/usr/bin/codex" if available else None)

    def test_should_invoke_for_large_task(self, monkeypatch):
        """Large tasks always trigger Layer 2 regardless of other signals."""
        from orchestrator.mainline_executor import MainlineExecutor
        self._patch_codex_available(monkeypatch, True)
        assert MainlineExecutor._should_invoke_codex_reviewer(task_size="large") is True

    def test_should_invoke_for_high_risk(self, monkeypatch):
        """High-risk tasks always trigger Layer 2 regardless of other signals."""
        from orchestrator.mainline_executor import MainlineExecutor
        self._patch_codex_available(monkeypatch, True)
        assert MainlineExecutor._should_invoke_codex_reviewer(risk_level="high") is True

    def test_should_invoke_after_failed_repair_then_pass(self, monkeypatch):
        """Failed repair followed by 'passed' — suspicious pattern triggers Layer 2."""
        from orchestrator.mainline_executor import MainlineExecutor
        self._patch_codex_available(monkeypatch, True)
        repair_history = [
            {"round": 0, "retest_result": "failed"},
            {"round": 1, "retest_result": "passed"},
        ]
        assert MainlineExecutor._should_invoke_codex_reviewer(
            task_size="medium",
            risk_level="low",
            repair_history=repair_history,
        ) is True

    def test_should_skip_when_codex_not_available(self, monkeypatch):
        """When codex is not on PATH, never invoke regardless of signals."""
        from orchestrator.mainline_executor import MainlineExecutor
        self._patch_codex_available(monkeypatch, False)
        assert MainlineExecutor._should_invoke_codex_reviewer(
            task_size="large",
        ) is False
        assert MainlineExecutor._should_invoke_codex_reviewer(
            risk_level="high",
        ) is False

    def test_should_skip_for_small_low_risk_clean_signal(self, monkeypatch):
        """Small, low-risk task with no Layer 1 findings and clean repair
        history should NOT trigger Layer 2."""
        from orchestrator.mainline_executor import MainlineExecutor
        self._patch_codex_available(monkeypatch, True)
        assert MainlineExecutor._should_invoke_codex_reviewer(
            task_size="small",
            risk_level="low",
            rule_findings=None,
            repair_history=None,
        ) is False

    def test_should_invoke_when_layer1_finds_something(self, monkeypatch):
        """Any Layer 1 finding (even non_blocking) triggers Layer 2 for a
        semantic second opinion."""
        from orchestrator.mainline_executor import MainlineExecutor
        self._patch_codex_available(monkeypatch, True)
        finding = ReviewFinding(
            finding_id="F-abc",
            step_id="step-1",
            severity="non_blocking",
            category="incomplete_reporting",
            description="Changed files mismatch",
            location="result.md",
            source="reviewer",
        )
        assert MainlineExecutor._should_invoke_codex_reviewer(
            task_size="small",
            risk_level="low",
            rule_findings=[finding],
        ) is True
