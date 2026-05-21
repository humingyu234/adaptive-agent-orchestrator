"""Phase 19 Prompt Quality Gate — evaluation runner against golden planning cases.

Usage:
    python -m orchestrator eval-prompts planning \
        --mode llm \
        --cases tests/golden/planning_cases.yaml \
        --repeat 1
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .planning import (
    PlanningCouncil,
    PlanContract,
    plan_contract_to_dict,
    build_default_council,
)
from .planning_prompts import (
    validate_planner_output,
    validate_reviewer_output,
    validate_execution_planner_output,
    validate_planner_pydantic,
    validate_reviewer_pydantic,
    validate_execution_planner_pydantic,
)
from .task_router import route_task, route_decision_to_dict


@dataclass
class CaseResult:
    """Result of evaluating one golden case."""
    case_id: str = ""
    case_title: str = ""
    passed: bool = False
    planning_mode: str = "deterministic"
    plan_dict: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    advisor_outputs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvalSummary:
    """Aggregate results from an eval-prompts run."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    mode: str = "deterministic"
    results: list[CaseResult] = field(default_factory=list)
    prompt_version: str = ""
    # Phase 19v2: 5 statistical dimensions
    parse_rate: float = 0.0
    schema_rate: float = 0.0
    worker_tasks_rate: float = 0.0
    blocking_accuracy: float = 0.0
    evidence_rate: float = 0.0


def _check(expected: dict[str, Any], plan_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Run all applicable checks for one golden case against a plan contract dict.

    Returns a list of check result dicts with {check, passed, detail}.
    """
    results: list[dict[str, Any]] = []

    steps = plan_dict.get("steps", [])
    risks = plan_dict.get("risks", [])
    required_evidence = plan_dict.get("required_evidence", [])
    blocking_concerns = plan_dict.get("blocking_concerns", [])
    human_review_gates = plan_dict.get("human_review_gates", [])
    worker_tasks = plan_dict.get("planned_worker_tasks", [])
    source_candidates = plan_dict.get("source_candidates", [])
    advisor_outputs = plan_dict.get("advisor_outputs", [])

    # ---- risk_level -----------------------------------------------------------
    if "risk_level" in expected:
        actual_risk = plan_dict.get("risk_level", "") or ""
        valid_levels = expected["risk_level"]
        ok = actual_risk in valid_levels
        results.append({
            "check": "risk_level",
            "passed": ok,
            "detail": f"expected one of {valid_levels}, got '{actual_risk}'",
        })

    # ---- min_steps ------------------------------------------------------------
    if "min_steps" in expected:
        ok = len(steps) >= expected["min_steps"]
        results.append({
            "check": "min_steps",
            "passed": ok,
            "detail": f"expected >= {expected['min_steps']}, got {len(steps)}",
        })

    # ---- required_evidence_contains -------------------------------------------
    if "required_evidence_contains" in expected:
        re_strs = [str(e).lower() for e in required_evidence]
        for item in expected["required_evidence_contains"]:
            ok = any(item.lower() in s for s in re_strs)
            results.append({
                "check": f"required_evidence_contains:{item}",
                "passed": ok,
                "detail": f"looking for '{item}' in {required_evidence}",
            })

    # ---- expected_evidence_not_empty ------------------------------------------
    if expected.get("expected_evidence_not_empty"):
        ok = len(required_evidence) > 0
        results.append({
            "check": "expected_evidence_not_empty",
            "passed": ok,
            "detail": f"required_evidence has {len(required_evidence)} items",
        })

    # ---- required_checks_not_empty (code-changing tasks) ---------------------
    if expected.get("required_checks_not_empty"):
        if worker_tasks:
            checks_ok = all(
                len(wt.get("required_checks", [])) > 0
                for wt in worker_tasks
            )
        else:
            checks_ok = False
        results.append({
            "check": "required_checks_not_empty",
            "passed": checks_ok,
            "detail": f"worker_tasks count: {len(worker_tasks)}",
        })

    # ---- required_checks_may_be_empty -----------------------------------------
    if expected.get("required_checks_may_be_empty"):
        results.append({
            "check": "required_checks_may_be_empty",
            "passed": True,
            "detail": "analysis-only tasks are allowed to have empty checks",
        })

    # ---- worker_task_count_min / max ------------------------------------------
    if "worker_task_count_min" in expected:
        ok = len(worker_tasks) >= expected["worker_task_count_min"]
        results.append({
            "check": "worker_task_count_min",
            "passed": ok,
            "detail": f"expected >= {expected['worker_task_count_min']}, got {len(worker_tasks)}",
        })
    if "worker_task_count_max" in expected:
        ok = len(worker_tasks) <= expected["worker_task_count_max"]
        results.append({
            "check": "worker_task_count_max",
            "passed": ok,
            "detail": f"expected <= {expected['worker_task_count_max']}, got {len(worker_tasks)}",
        })

    # ---- blocking_concerns_empty / not_empty ----------------------------------
    if expected.get("blocking_concerns_empty"):
        ok = len(blocking_concerns) == 0
        results.append({
            "check": "blocking_concerns_empty",
            "passed": ok,
            "detail": f"blocking_concerns has {len(blocking_concerns)} items: {blocking_concerns[:3]}",
        })
    if expected.get("blocking_concerns_not_empty"):
        ok = len(blocking_concerns) > 0
        results.append({
            "check": "blocking_concerns_not_empty",
            "passed": ok,
            "detail": f"blocking_concerns has {len(blocking_concerns)} items",
        })

    # ---- human_review_gate_empty / not_empty / may_exist ----------------------
    if expected.get("human_review_gate_empty"):
        ok = len(human_review_gates) == 0
        results.append({
            "check": "human_review_gate_empty",
            "passed": ok,
            "detail": f"human_review_gates has {len(human_review_gates)} items",
        })
    if expected.get("human_review_gate_not_empty"):
        ok = len(human_review_gates) > 0
        results.append({
            "check": "human_review_gate_not_empty",
            "passed": ok,
            "detail": f"human_review_gates has {len(human_review_gates)} items",
        })
    if expected.get("human_review_gate_may_exist"):
        results.append({
            "check": "human_review_gate_may_exist",
            "passed": True,
            "detail": "human_review_gate is optional for this case",
        })

    # ---- can_run_parallel -----------------------------------------------------
    if "can_run_parallel" in expected:
        ok = any(wt.get("can_run_parallel") for wt in worker_tasks)
        results.append({
            "check": "can_run_parallel",
            "passed": ok if expected["can_run_parallel"] else not ok,
            "detail": f"expected={expected['can_run_parallel']}, got={ok}",
        })

    # ---- all_files_overlap ----------------------------------------------------
    if expected.get("all_files_overlap"):
        files_per_task = [
            set(wt.get("allowed_files", [])) for wt in worker_tasks
        ]
        overlap = False
        for i in range(len(files_per_task)):
            for j in range(i + 1, len(files_per_task)):
                if files_per_task[i] & files_per_task[j]:
                    overlap = True
                    break
        results.append({
            "check": "all_files_overlap",
            "passed": overlap,
            "detail": "expected all tasks to share files",
        })

    # ---- diff_patch_not_required ----------------------------------------------
    if expected.get("diff_patch_not_required"):
        has_diff = any("diff.patch" in str(e).lower() for e in required_evidence)
        results.append({
            "check": "diff_patch_not_required",
            "passed": not has_diff,
            "detail": f"diff.patch in required_evidence: {has_diff}",
        })

    # ---- Advisor output validators (run against advisor_outputs) --------------
    for ao in advisor_outputs:
        role = ao.get("role", "")
        if role == "execution_planner":
            # The LLM produces worker_tasks at top level, but they are extracted
            # into planned_worker_tasks.  Reconstruct a synthetic dict so the
            # validator sees the full shape the LLM was meant to produce.
            synth = dict(ao)
            synth["worker_tasks"] = [
                {
                    "title": wt.get("title", ""),
                    "objective": wt.get("objective", ""),
                    "allowed_files": wt.get("allowed_files", []),
                    "denied_files": wt.get("denied_files", []),
                    "required_checks": wt.get("required_checks", []),
                    "expected_evidence": wt.get("expected_evidence", []),
                    "risk_level": wt.get("risk_level", "low"),
                    "dependencies": wt.get("dependencies", []),
                    "can_run_parallel": wt.get("can_run_parallel", False),
                    "requires_human_review": wt.get("requires_human_review", False),
                }
                for wt in worker_tasks
            ]
            val_errors = validate_execution_planner_output(synth)
            pyd_errors = validate_execution_planner_pydantic(synth)
        elif role == "planner":
            val_errors = validate_planner_output(ao)
            pyd_errors = validate_planner_pydantic(ao)
        elif role == "risk_reviewer":
            val_errors = validate_reviewer_output(ao)
            pyd_errors = validate_reviewer_pydantic(ao)
        else:
            continue
        for ve in val_errors:
            results.append({
                "check": f"advisor_validator:{role}",
                "passed": False,
                "detail": ve,
            })
        for pe in pyd_errors:
            results.append({
                "check": f"pydantic_validator:{role}",
                "passed": False,
                "detail": pe,
            })

    return results


def _compute_stats(results: list[CaseResult]) -> dict[str, float]:
    """Compute 5 quality statistics from case results.

    Returns dict with: parse_rate, schema_rate, worker_tasks_rate,
    blocking_accuracy, evidence_rate.
    """
    total = len(results)
    if total == 0:
        return {
            "parse_rate": 0.0, "schema_rate": 0.0,
            "worker_tasks_rate": 0.0, "blocking_accuracy": 0.0,
            "evidence_rate": 0.0,
        }

    parse_ok = 0      # no "parse_error" in any advisor output
    schema_ok = 0     # no "advisor_validator" check failures
    wt_ok = 0         # worker_tasks non-empty
    blocking_ok = 0   # blocking_concerns checks passed
    evidence_ok = 0   # required_evidence checks passed

    for r in results:
        # parse_rate: no advisor output has parse_error
        has_parse_error = False
        for ao in r.advisor_outputs:
            if ao.get("parse_error") or any(
                "parse_error" in str(a).lower() for a in ao.get("assumptions", [])
            ):
                has_parse_error = True
                break
        if not has_parse_error:
            parse_ok += 1

        # schema_rate: no check failed due to advisor_validator
        has_schema_failure = any(
            c.get("check", "").startswith("advisor_validator:")
            and not c.get("passed", False)
            for c in r.checks
        )
        if not has_schema_failure:
            schema_ok += 1

        # worker_tasks_rate: plan has non-empty worker_tasks
        if r.plan_dict.get("planned_worker_tasks"):
            wt_ok += 1

        # blocking_accuracy: blocking_* check(s) exist and all pass
        blocking_checks = [
            c for c in r.checks
            if "blocking_concerns" in c.get("check", "")
        ]
        if blocking_checks and all(c["passed"] for c in blocking_checks):
            blocking_ok += 1
        elif not blocking_checks:
            # No blocking check defined for this case — neutral, count as pass
            blocking_ok += 1

        # evidence_rate: required_evidence checks pass
        evidence_checks = [
            c for c in r.checks
            if "evidence" in c.get("check", "")
        ]
        if evidence_checks and all(c["passed"] for c in evidence_checks):
            evidence_ok += 1
        elif not evidence_checks:
            evidence_ok += 1

    return {
        "parse_rate": parse_ok / total * 100,
        "schema_rate": schema_ok / total * 100,
        "worker_tasks_rate": wt_ok / total * 100,
        "blocking_accuracy": blocking_ok / total * 100,
        "evidence_rate": evidence_ok / total * 100,
    }


def run_eval_cases(
    cases_path: str,
    *,
    mode: str = "deterministic",
    repeat: int = 1,
    verbose: bool = False,
) -> EvalSummary:
    """Run all golden cases through the Planning Council and validate results.

    Args:
        cases_path: Path to the YAML golden cases file.
        mode: Planning mode — "deterministic" or "llm".
        repeat: Number of times to repeat each case (for statistical confidence).
        verbose: Print per-case details to stderr.

    Returns:
        EvalSummary with aggregated results.
    """
    with open(cases_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    cases: list[dict[str, Any]] = data.get("cases", [])
    prompt_version: str = data.get("prompt_version", "unknown")

    from .planning_prompts import PROMPT_VERSION

    summary = EvalSummary(mode=mode, prompt_version=PROMPT_VERSION)
    council = build_default_council(mode=mode)

    for case in cases:
        case_id = case["id"]
        title = case.get("title", case_id)
        query = case["query"]
        task_size = case.get("task_size", "medium")
        run_mode = case.get("run_mode", "controlled")
        risk_level = case.get("risk_level", "low")
        task_type = case.get("task_type", "unknown")
        expected = case.get("expected", {})

        # Re-run if repeat > 1 (take last result)
        plan: PlanContract | None = None
        for _ in range(repeat):
            plan = council.create_plan(
                query,
                task_size=task_size,
                run_mode=run_mode,
                risk_level=risk_level,
                task_type=task_type,
            )

        if plan is None:
            result = CaseResult(
                case_id=case_id,
                case_title=title,
                passed=False,
                planning_mode=mode,
                errors=["create_plan returned None"],
            )
            summary.results.append(result)
            summary.total += 1
            summary.failed += 1
            continue

        plan_dict = plan_contract_to_dict(plan)

        # ---- Detect LLM provider failures ------------------------------------
        llm_errors: list[str] = []
        for ao in plan_dict.get("advisor_outputs", []):
            role = ao.get("role", "unknown")
            for bc in ao.get("blocking_concerns", []):
                if "LLM call failed" in bc or "ERROR:" in bc:
                    llm_errors.append(f"{role}: {bc[:150]}")
            summary_text = ao.get("summary", "")
            if "LLM" in summary_text and ("failed" in summary_text or "error" in summary_text.lower()):
                llm_errors.append(f"{role}: {summary_text[:150]}")

        # Route decision for context
        decision = route_task(query)
        plan_dict["risk_level"] = decision.risk_level
        plan_dict["route_decision"] = route_decision_to_dict(decision)

        if llm_errors:
            checks = [{
                "check": "llm_provider_health",
                "passed": False,
                "detail": "; ".join(llm_errors[:3]),
            }]
            all_passed = False
            errors = llm_errors
        else:
            checks = _check(expected, plan_dict)
            all_passed = all(c["passed"] for c in checks)
            errors = [c["detail"] for c in checks if not c["passed"]]

        result = CaseResult(
            case_id=case_id,
            case_title=title,
            passed=all_passed,
            planning_mode=mode,
            plan_dict=plan_dict,
            checks=checks,
            errors=errors,
            advisor_outputs=plan_dict.get("advisor_outputs", []),
        )
        summary.results.append(result)
        summary.total += 1
        if all_passed:
            summary.passed += 1
        else:
            summary.failed += 1

        if verbose and not all_passed:
            sys.stderr.write(f"\nFAIL {case_id}: {title}\n")
            for e in errors:
                sys.stderr.write(f"  - {e}\n")

    # ---- Phase 19v2: compute 5 statistical dimensions ----------------------
    stats = _compute_stats(summary.results)
    summary.parse_rate = stats["parse_rate"]
    summary.schema_rate = stats["schema_rate"]
    summary.worker_tasks_rate = stats["worker_tasks_rate"]
    summary.blocking_accuracy = stats["blocking_accuracy"]
    summary.evidence_rate = stats["evidence_rate"]

    return summary


def render_eval_summary(summary: EvalSummary) -> str:
    """Render an EvalSummary as a human-readable text report."""
    lines: list[str] = []
    lines.append("=" * 68)
    lines.append("Phase 19v2 — Prompt Quality Gate Evaluation")
    lines.append("=" * 68)
    lines.append(f"  Mode:           {summary.mode}")
    lines.append(f"  Prompt Version: {summary.prompt_version}")
    lines.append(f"  Cases:          {summary.total}")
    lines.append(f"  Passed:         {summary.passed}")
    lines.append(f"  Failed:         {summary.failed}")
    if summary.total > 0:
        pct = summary.passed / summary.total * 100
        lines.append(f"  Pass Rate:      {pct:.0f}%")
    lines.append("")
    lines.append("  Quality Statistics (Phase 19v2):")
    lines.append(f"    Parse Rate:        {summary.parse_rate:.0f}%    (JSON parse success)")
    lines.append(f"    Schema Rate:       {summary.schema_rate:.0f}%    (Pydantic validation pass)")
    lines.append(f"    Worker Tasks Rate: {summary.worker_tasks_rate:.0f}%    (worker_tasks non-empty)")
    lines.append(f"    Blocking Accuracy: {summary.blocking_accuracy:.0f}%    (blocking correct)")
    lines.append(f"    Evidence Rate:     {summary.evidence_rate:.0f}%    (required_evidence complete)")
    lines.append("")

    llm_errors = 0
    for r in summary.results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"  [{status}] {r.case_id}: {r.case_title}")
        if not r.passed:
            for detail in r.errors[:3]:
                lines.append(f"          > {detail}")
                if "LLM call failed" in detail or "Insufficient" in detail or "upstream" in detail:
                    llm_errors += 1
    lines.append("")
    if llm_errors > 0:
        lines.append(f"  !! {llm_errors} case(s) have LLM provider errors — real-LLM-smoke-blocked")
        lines.append(f"  !! Check API keys, account balance, and provider health.")
        lines.append("")
    return "\n".join(lines)


def eval_summary_to_dict(summary: EvalSummary) -> dict[str, Any]:
    """Serialize EvalSummary to a JSON-serializable dict."""
    return {
        "mode": summary.mode,
        "prompt_version": summary.prompt_version,
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "pass_rate": (summary.passed / summary.total * 100) if summary.total > 0 else 0,
        "quality_stats": {
            "parse_rate": summary.parse_rate,
            "schema_rate": summary.schema_rate,
            "worker_tasks_rate": summary.worker_tasks_rate,
            "blocking_accuracy": summary.blocking_accuracy,
            "evidence_rate": summary.evidence_rate,
        },
        "results": [
            {
                "case_id": r.case_id,
                "case_title": r.case_title,
                "passed": r.passed,
                "errors": r.errors,
                "checks": r.checks,
                "plan_summary": r.plan_dict.get("objective", ""),
                "worker_task_count": len(r.plan_dict.get("planned_worker_tasks", [])),
                "blocking_concerns": r.plan_dict.get("blocking_concerns", []),
            }
            for r in summary.results
        ],
    }
