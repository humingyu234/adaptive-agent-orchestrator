"""Isolated Reviewer — read-only inspector of worker output.

Phase 23: The reviewer examines *observed evidence* (diff, test output,
changed files, evidence artifacts) and produces ReviewFinding instances.
It does NOT trust worker self-summaries, does NOT modify code, and runs
in a context isolated from the worker's working directory.

ReviewFinding → FixTask conversion happens in MainlineExecutor, not here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .auto_repair import ReviewFinding
from .control_models import WorkerEvidenceStatus


# =============================================================================
# EvidenceBundle — what the reviewer is allowed to inspect
# =============================================================================


@dataclass
class EvidenceBundle:
    """Read-only evidence collected from a worker step.

    Every field here is an *observed fact*, never a worker self-assessment.
    The reviewer MUST NOT trust anything outside this bundle.
    """

    task_id: str
    step_id: str

    # Observed artifacts
    changed_files: list[str] = field(default_factory=list)
    diff_content: str = ""
    test_output: str = ""
    result_md: str = ""

    # Boundary context
    allowed_files: list[str] = field(default_factory=list)
    denied_files: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)

    # Worker metadata (set by runtime, not by worker)
    worker_status: str = ""

    @classmethod
    def from_packet(
        cls,
        task_id: str,
        step_id: str,
        *,
        changed_files: list[str] | None = None,
        diff_content: str = "",
        test_output: str = "",
        result_md: str = "",
        allowed_files: list[str] | None = None,
        denied_files: list[str] | None = None,
        required_checks: list[str] | None = None,
        worker_status: str = "",
    ) -> EvidenceBundle:
        return cls(
            task_id=task_id,
            step_id=step_id,
            changed_files=list(changed_files or []),
            diff_content=diff_content,
            test_output=test_output,
            result_md=result_md,
            allowed_files=list(allowed_files or []),
            denied_files=list(denied_files or []),
            required_checks=list(required_checks or []),
            worker_status=worker_status,
        )

    @property
    def has_any_evidence(self) -> bool:
        """True if at least one observable artifact is present."""
        return bool(
            self.changed_files
            or self.diff_content.strip()
            or self.test_output.strip()
            or self.result_md.strip()
        )


# =============================================================================
# Reviewer — abstract base
# =============================================================================


class Reviewer(ABC):
    """Read-only inspector.  Examines observed evidence and produces
    ReviewFinding instances.  Never writes code, never trusts worker
    self-summaries.

    Subclasses override :meth:`review` to implement specific inspection
    logic (rule-based, LLM-based, etc.).
    """

    @abstractmethod
    def review(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        """Inspect *evidence* and return findings.

        A finding is only valid if it references a concrete location in
        the evidence (file:line, evidence path, test output excerpt).
        Findings based on the worker's self-assessment are forbidden.
        """
        ...

    @property
    def name(self) -> str:
        return type(self).__name__


# =============================================================================
# RuleBasedReviewer — deterministic, no LLM
# =============================================================================


class RuleBasedReviewer(Reviewer):
    """Deterministic rule-based reviewer for tests and fast checks.

    Rules (applied in order):
    1. test_output contains FAILED → blocking (test_failure)
    2. No evidence at all → blocking (missing_evidence)
    3. result.md claims success but test_output shows failures
       → blocking (evidence_contradiction)
    4. diff touches files outside allowed_files → blocking (protected_action)
    5. changed_files don't match diff's actual changed files
       → non_blocking (incomplete_reporting)
    """

    def review(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []

        # Rule 1: test output shows failures
        findings.extend(self._check_test_failures(evidence))

        # Rule 2: no evidence at all
        findings.extend(self._check_empty_evidence(evidence))

        # Rule 3: worker claims success but evidence contradicts
        findings.extend(self._check_contradiction(evidence))

        # Rule 4: diff touches files outside allowed boundaries
        findings.extend(self._check_file_boundaries(evidence))

        # Rule 5: changed_files mismatch
        findings.extend(self._check_changed_files_accuracy(evidence))

        return findings

    # ------------------------------------------------------------------
    # individual rules
    # ------------------------------------------------------------------

    def _check_test_failures(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        test_output = evidence.test_output
        if not test_output:
            return findings

        import re
        if re.search(r"\bFAILED\b|\bFAIL\b", test_output):
            findings.append(ReviewFinding(
                finding_id=_new_finding_id(),
                step_id=evidence.step_id,
                severity="blocking",
                category="test_failure",
                description="Test output contains FAILED or FAIL",
                location="observed/test_output.txt",
                source="reviewer",
            ))
        return findings

    def _check_empty_evidence(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        if evidence.has_any_evidence:
            return []
        return [ReviewFinding(
            finding_id=_new_finding_id(),
            step_id=evidence.step_id,
            severity="blocking",
            category="missing_evidence",
            description="No observed evidence — worker produced nothing verifiable",
            location="",
            source="reviewer",
        )]

    def _check_contradiction(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        """Detect when worker claims success but evidence shows failure."""
        findings: list[ReviewFinding] = []
        result_md = evidence.result_md
        test_output = evidence.test_output

        if not result_md or not test_output:
            return findings

        # Worker claims success
        claims_success = any(
            phrase in result_md.lower()
            for phrase in ("success", "completed", "passed", "tests_pass=true")
        )

        # Evidence shows failures
        import re
        evidence_shows_failure = bool(
            re.search(r"\bFAILED\b", test_output)
        )

        if claims_success and evidence_shows_failure:
            findings.append(ReviewFinding(
                finding_id=_new_finding_id(),
                step_id=evidence.step_id,
                severity="blocking",
                category="evidence_contradiction",
                description=(
                    "Worker claims success but test output contains FAILED — "
                    "evidence contradicts worker self-assessment"
                ),
                location="observed/test_output.txt",
                source="reviewer",
            ))
        return findings

    def _check_file_boundaries(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        """Detect diff changes outside allowed_files.

        Two enforcement modes:

        1. **Read-only** (allowed_files is empty): ANY file change is a
           violation — the milestone must not modify any files.
        2. **Bounded** (allowed_files has entries): only changes inside
           the listed files are permitted.
        """
        findings: list[ReviewFinding] = []
        diff = evidence.diff_content
        if not diff:
            return findings

        import re
        diff_files: set[str] = set()
        for marker in ("--- a/", "+++ b/"):
            for m in re.finditer(rf"{re.escape(marker)}(\S+)", diff):
                diff_files.add(m.group(1))

        if not diff_files:
            return findings

        allowed = set(evidence.allowed_files)

        if not allowed:
            # Read-only milestone — every changed file is a violation
            for path in sorted(diff_files):
                findings.append(ReviewFinding(
                    finding_id=_new_finding_id(),
                    step_id=evidence.step_id,
                    severity="blocking",
                    category="protected_action",
                    description=(
                        f"Read-only milestone: diff touches {path} "
                        f"but allowed_files is empty (no files may be modified)"
                    ),
                    location=path,
                    source="reviewer",
                ))
            return findings

        # Bounded milestone — files must be within the allowlist
        out_of_bounds = diff_files - allowed
        for path in sorted(out_of_bounds):
            findings.append(ReviewFinding(
                finding_id=_new_finding_id(),
                step_id=evidence.step_id,
                severity="blocking",
                category="protected_action",
                description=f"Diff touches file outside allowed_files: {path}",
                location=path,
                source="reviewer",
            ))
        return findings

    def _check_changed_files_accuracy(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        """Detect when self-reported changed_files don't match diff reality."""
        findings: list[ReviewFinding] = []
        diff = evidence.diff_content
        reported = set(evidence.changed_files)
        if not diff or not reported:
            return findings

        import re
        diff_files: set[str] = set()
        for marker in ("--- a/", "+++ b/"):
            for m in re.finditer(rf"{re.escape(marker)}(\S+)", diff):
                diff_files.add(m.group(1))

        if diff_files != reported:
            only_in_diff = diff_files - reported
            only_reported = reported - diff_files
            detail_parts: list[str] = []
            if only_in_diff:
                detail_parts.append(f"in diff but not reported: {', '.join(sorted(only_in_diff))}")
            if only_reported:
                detail_parts.append(f"reported but not in diff: {', '.join(sorted(only_reported))}")
            findings.append(ReviewFinding(
                finding_id=_new_finding_id(),
                step_id=evidence.step_id,
                severity="non_blocking",
                category="incomplete_reporting",
                description="Changed files mismatch: " + "; ".join(detail_parts),
                location="result.md",
                source="reviewer",
            ))
        return findings


# =============================================================================
# FakeReviewer — pre-configured findings for tests
# =============================================================================


class FakeReviewer(Reviewer):
    """Returns pre-configured findings for deterministic testing.

    Useful when you want to control exactly what the reviewer "finds"
    without relying on real evidence analysis.
    """

    def __init__(self, findings: list[ReviewFinding] | None = None) -> None:
        self._findings: list[ReviewFinding] = list(findings or [])

    def review(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        return list(self._findings)

    def set_findings(self, findings: list[ReviewFinding]) -> None:
        self._findings = list(findings)


# =============================================================================
# CodexReviewer — LLM reviewer backed by Codex CLI read-only sandbox
# =============================================================================


class CodexReviewer(Reviewer):
    """LLM reviewer backed by Codex CLI in read-only sandbox.

    Launches an isolated ``codex exec`` subprocess with write tools disabled.
    Receives only the EvidenceBundle contents via a constructed prompt.
    Output is constrained by a JSON Schema so the response can be parsed
    into structured ReviewFinding objects.

    Cold Validation pattern: Claude Code builds, Codex CLI audits.
    Zero shared context — each review gets a fresh session.
    """

    _DEFAULT_TIMEOUT = 600  # 10 minutes

    def __init__(
        self,
        schema_path: str = "",
        timeout: int | None = None,
    ) -> None:
        self._schema_path = schema_path or str(
            Path(__file__).parent / "review_schema.json"
        )
        self._timeout = timeout or self._DEFAULT_TIMEOUT

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def review(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        """Run Codex CLI in read-only sandbox and parse findings.

        Graceful degradation: returns empty list when Codex is unavailable,
        times out, produces unparseable output, or returns a non-zero exit
        code.  The caller treats an empty result as "no additional findings"
        rather than a failure.
        """
        if not self.is_available():
            return []

        prompt = self._build_prompt(evidence)
        import tempfile

        with tempfile.TemporaryDirectory(prefix="aao-review-") as iso_dir:
            try:
                proc = subprocess.run(
                    [
                        "codex", "exec",
                        "--sandbox", "read-only",
                        "--output-schema", self._schema_path,
                        "--session-id", f"review-{uuid.uuid4().hex[:8]}",
                        "-C", iso_dir,
                        prompt,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return []

        return self._parse_output(proc.stdout)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(evidence: EvidenceBundle) -> str:
        """Construct the review prompt from observed evidence only.

        The prompt deliberately frames the reviewer as an outsider:
        it did not write the code, has no context, and must not trust
        the worker's self-assessment.
        """
        changed_files = "\n".join(
            f"- {f}" for f in evidence.changed_files
        ) if evidence.changed_files else "(none)"

        diff = evidence.diff_content or "(no diff)"

        test_output = evidence.test_output or "(no test output)"

        result_md = evidence.result_md or "(no result.md)"

        allowed = "\n".join(
            f"- {f}" for f in evidence.allowed_files
        ) if evidence.allowed_files else "(none)"

        checks = "\n".join(
            f"- {c}" for c in evidence.required_checks
        ) if evidence.required_checks else "(none)"

        return (
            "You are an isolated code reviewer. You did NOT write this code.\n"
            "You have NO context beyond what is provided below.\n"
            "Never trust the worker's self-assessment. Cite concrete evidence.\n"
            "\n"
            f"== TASK ==\n{evidence.step_id}\n"
            "\n"
            f"== CHANGED FILES ==\n{changed_files}\n"
            "\n"
            f"== DIFF ==\n{diff}\n"
            "\n"
            f"== TEST OUTPUT ==\n{test_output}\n"
            "\n"
            f"== RESULT.MD (worker self-report — DO NOT TRUST) ==\n{result_md}\n"
            "\n"
            f"== ALLOWED FILES ==\n{allowed}\n"
            "\n"
            f"== REQUIRED CHECKS ==\n{checks}\n"
            "\n"
            "For each issue found, provide file:line or evidence path as "
            "location.  Output as structured JSON per the output schema."
        )

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    _FINDING_SEVERITY_MAP = {
        "blocking": "blocking",
        "non_blocking": "non_blocking",
        "info": "info",
    }

    def _parse_output(self, raw: str) -> list[ReviewFinding]:
        """Parse Codex JSON output into ReviewFinding list.

        Returns empty list on any parse failure — the caller treats this as
        "no additional findings" so a malformed LLM response never blocks
        the pipeline.
        """
        json_str = self._extract_json(raw)
        if not json_str:
            return []
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        findings: list[ReviewFinding] = []
        for item in data.get("findings", []):
            severity = self._FINDING_SEVERITY_MAP.get(
                item.get("severity", ""), "non_blocking"
            )
            findings.append(ReviewFinding(
                finding_id=f"F-{uuid.uuid4().hex[:8]}",
                step_id="",  # filled in by caller
                severity=severity,
                category=item.get("category", "llm_review"),
                description=item.get("description", ""),
                location=item.get("location", ""),
                suggested_fix=item.get("suggested_fix"),
                source="reviewer",
            ))
        return findings

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Extract the JSON block from Codex output.

        The Codex response may contain log lines before/after the JSON.
        We look for the first '{' / last '}' pair.
        """
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return ""
        return raw[start:end + 1]

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """True if the ``codex`` CLI is on PATH."""
        return shutil.which("codex") is not None


# =============================================================================
# LLMReviewer — interface placeholder (kept for backward compat)
# =============================================================================


class LLMReviewer(Reviewer):
    """LLM-based reviewer — interface placeholder.

    Prefer :class:`CodexReviewer` for real LLM review.
    This class remains as a no-dependency stub for environments where
    Codex CLI is not available.
    """

    def review(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        raise NotImplementedError(
            "LLMReviewer is a placeholder — use CodexReviewer instead"
        )


# =============================================================================
# helpers
# =============================================================================


def _new_finding_id() -> str:
    return f"F-{uuid.uuid4().hex[:8]}"
