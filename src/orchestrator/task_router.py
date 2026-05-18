"""Task Router — deterministic front-door traffic light for AAO.

Decides how much AAO should be involved in a task BEFORE execution starts.
No LLM calls, no filesystem access, no network.  Pure and testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

TaskSize = Literal["small", "medium", "large"]
RunMode = Literal["off", "log", "controlled", "orchestrated"]
RiskLevel = Literal["low", "medium", "high"]
TaskType = Literal[
    "question", "explanation", "review", "bugfix", "feature",
    "refactor", "research", "ops", "phase_work", "project", "unknown",
]
Confidence = Literal["low", "medium", "high"]
RuntimeSupport = Literal["native", "route_only", "fallback_controlled", "future_orchestrated"]


@dataclass
class TaskRouteDecision:
    """The router's decision about a task before execution."""

    task_size: TaskSize = "small"
    run_mode: RunMode = "log"
    risk_level: RiskLevel = "low"
    task_type: TaskType = "unknown"
    confidence: Confidence = "medium"
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, object] = field(default_factory=dict)
    user_override: bool = False
    workflow_hint: str | None = None
    runtime_support: RuntimeSupport = "native"


# =============================================================================
# Default routing policy: size -> mode
# =============================================================================

_SIZE_TO_MODE: dict[TaskSize, RunMode] = {
    "small": "log",
    "medium": "controlled",
    "large": "orchestrated",
}


# =============================================================================
# Signal dictionaries
# =============================================================================

# Words that strongly indicate a small / lightweight ask
_SMALL_INDICATORS: frozenset[str] = frozenset({
    "explain", "what is", "what are", "what does", "how does",
    "translate", "summarize", "define", "describe", "tell me",
    "show me", "list", "which", "where is", "why is",
    "介绍一下", "解释", "什么是", "怎么用", "说明",
})

# Words that indicate medium-sized work
_MEDIUM_INDICATORS: frozenset[str] = frozenset({
    "review", "bugfix", "bug fix", "fix", "add test", "add tests",
    "update test", "write test", "one feature", "single feature",
    "refactor", "improve", "optimize", "add", "implement",
    "修改", "修复", "添加", "优化", "重构", "审查",
})

# Words that indicate large / project-level work
_LARGE_INDICATORS: frozenset[str] = frozenset({
    "phase", "multi-step", "multi step", "end-to-end", "end to end",
    "architecture", "migration", "full project", "many files",
    "multiple modules", "parallel", "long-running", "long running",
    "resume", "checkpoint", "audit", "full workflow",
    "implement phase", "整个项目", "多阶段", "架构", "迁移",
})

# High-risk words that force escalation to at least controlled
_HIGH_RISK_WORDS: frozenset[str] = frozenset({
    "delete", "remove", "rm -rf", "rm -r", "reset", "force push",
    "migrate", "deploy", "release", "production", "database",
    "credentials", "secret", ".env", "payment", "auth",
    "security", "permission", "protected",
    "删除", "强制推送", "部署", "生产", "数据库", "凭证",
    "密钥", "密码", "支付", "认证", "权限",
})

# Destructive words that force escalation even in short queries
_DESTRUCTIVE_WORDS: frozenset[str] = frozenset({
    "rm -rf", "rm -r", "force push", "delete", "reset --hard",
    "drop table", "truncate",
    "强制删除", "清空数据库",
})

# Review/bugfix task types
_REVIEW_WORDS: frozenset[str] = frozenset({
    "review", "pr", "pull request", "code review", "reviewer",
    "审查", "审核", "复核", "检查代码",
})

_BUGFIX_WORDS: frozenset[str] = frozenset({
    "bug", "bugfix", "bug fix", "fix", "broken", "crash",
    "错误", "缺陷", "崩溃", "修",
})

_FEATURE_WORDS: frozenset[str] = frozenset({
    "feature", "add", "implement", "build", "create",
    "新功能", "实现", "构建", "创建",
})

_REFACTOR_WORDS: frozenset[str] = frozenset({
    "refactor", "clean up", "cleanup", "restructure",
    "重构", "清理",
})

_RESEARCH_WORDS: frozenset[str] = frozenset({
    "research", "investigate", "analyze", "study", "explore",
    "研究", "调查", "分析",
})

_OPS_WORDS: frozenset[str] = frozenset({
    "deploy", "release", "migrate", "database", "production",
    "ci/cd", "pipeline", "infrastructure",
    "部署", "发布", "运维",
})

_QUESTION_WORDS: frozenset[str] = frozenset({
    "what", "why", "how", "when", "where", "which", "who",
    "explain", "describe", "tell me",
    "什么是", "为什么", "怎么", "如何", "解释",
})

_PHASE_WORK_WORDS: frozenset[str] = frozenset({
    "phase", "implement phase",
    "阶段", "实施阶段",
})

# =============================================================================
# File mention regex — matches backticked paths and common path patterns
# =============================================================================

_FILE_MENTION_RE = re.compile(
    r"`([^`]+\.[a-zA-Z0-9]+)`"          # backticked file paths
    r"|(?<!\w)([a-zA-Z0-9_\-/]+\.[a-zA-Z]{1,10})(?!\w)"  # bare file paths
    r"|(?<!\w)([a-zA-Z0-9_]+\.py)(?!\w)"  # .py files
)

_DIR_MENTION_RE = re.compile(
    r"(?<!\w)(src|tests|docs|scripts|outputs|inputs|configs?)(/\S*)?"
)


def _count_file_mentions(query: str) -> int:
    """Count distinct file-like mentions in a query."""
    matches = _FILE_MENTION_RE.findall(query)
    seen: set[str] = set()
    for groups in matches:
        for g in groups:
            if g and len(g) > 2:
                seen.add(g)
    return len(seen)


# =============================================================================
# Router
# =============================================================================

def route_task(
    query: str,
    *,
    explicit_mode: RunMode | None = None,
    explicit_workflow: str | None = None,
) -> TaskRouteDecision:
    """Route a task deterministically — no LLM, no filesystem, no network.

    Returns a TaskRouteDecision with size, mode, risk, type, reasons, and
    runtime support.
    """
    lowered = query.lower().strip()
    reasons: list[str] = []
    signals: dict[str, object] = {}

    # ---- classify task size --------------------------------------------------
    file_count = _count_file_mentions(lowered)
    signals["file_mentions"] = file_count

    has_small = any(w in lowered for w in _SMALL_INDICATORS)
    has_medium = any(w in lowered for w in _MEDIUM_INDICATORS)
    has_large = any(w in lowered for w in _LARGE_INDICATORS)
    has_high_risk = any(w in lowered for w in _HIGH_RISK_WORDS)
    has_destructive = any(w in lowered for w in _DESTRUCTIVE_WORDS)

    # Determine size
    if has_large:
        task_size: TaskSize = "large"
        reasons.append("large-scale or project-level intent detected")
    elif has_medium and not has_large:
        task_size = "medium"
        reasons.append("implementation/review/fix intent detected")
    elif file_count >= 4:
        task_size = "large"
        reasons.append(f"{file_count} files mentioned")
    elif file_count >= 1 and not has_small:
        task_size = "medium"
        reasons.append(f"{file_count} file(s) mentioned with no small signal")
    elif has_small and not has_medium and not has_large:
        task_size = "small"
        reasons.append("explanatory or single-question intent")
    else:
        # Ambiguous: default to medium with low confidence
        task_size = "medium"
        reasons.append("ambiguous query, no strong size signal")

    # ---- classify risk level -------------------------------------------------
    if has_destructive:
        risk_level: RiskLevel = "high"
        reasons.append("destructive operation detected")
    elif has_high_risk:
        risk_level = "high"
        reasons.append("high-risk keyword detected")
    elif task_size == "large":
        risk_level = "medium"
    elif task_size == "medium":
        risk_level = "medium"
    else:
        risk_level = "low"

    signals["has_destructive"] = has_destructive
    signals["has_high_risk"] = has_high_risk

    # ---- classify task type --------------------------------------------------
    task_type = _classify_task_type(lowered)
    signals["task_type"] = task_type

    # ---- confidence ----------------------------------------------------------
    signal_count = sum([has_small, has_medium, has_large, file_count > 0])
    if signal_count >= 2:
        confidence: Confidence = "high"
    elif signal_count == 1:
        confidence = "medium"
    else:
        confidence = "low"

    # ---- default run mode (size -> mode) ------------------------------------
    run_mode: RunMode = _SIZE_TO_MODE[task_size]

    # ---- high-risk escalation ------------------------------------------------
    if risk_level == "high" and run_mode not in ("controlled", "orchestrated"):
        run_mode = "controlled"
        reasons.append("escalated to controlled due to high risk")

    # ---- user override -------------------------------------------------------
    user_override = False
    if explicit_mode is not None:
        user_override = True
        run_mode = explicit_mode

    # ---- runtime support -----------------------------------------------------
    if run_mode == "orchestrated":
        runtime_support: RuntimeSupport = "future_orchestrated"
        reasons.append("orchestrated runner is not implemented yet")
    elif run_mode == "off":
        runtime_support = "route_only"
    elif run_mode == "log":
        runtime_support = "native"
    else:
        runtime_support = "native"

    # ---- workflow hint -------------------------------------------------------
    workflow_hint = explicit_workflow

    return TaskRouteDecision(
        task_size=task_size,
        run_mode=run_mode,
        risk_level=risk_level,
        task_type=task_type,
        confidence=confidence,
        reasons=reasons,
        signals=signals,
        user_override=user_override,
        workflow_hint=workflow_hint,
        runtime_support=runtime_support,
    )


def _classify_task_type(lowered: str) -> TaskType:
    """Classify the task type from query keywords."""
    if any(w in lowered for w in _PHASE_WORK_WORDS):
        return "phase_work"
    if any(w in lowered for w in _REVIEW_WORDS):
        return "review"
    if any(w in lowered for w in _BUGFIX_WORDS):
        return "bugfix"
    if any(w in lowered for w in _OPS_WORDS):
        return "ops"
    if any(w in lowered for w in _FEATURE_WORDS):
        return "feature"
    if any(w in lowered for w in _REFACTOR_WORDS):
        return "refactor"
    if any(w in lowered for w in _RESEARCH_WORDS):
        return "research"
    if any(w in lowered for w in _QUESTION_WORDS):
        return "question"
    if any(w in lowered for w in ("explain", "describe", "what is", "解释", "说明")):
        return "explanation"
    return "unknown"


# =============================================================================
# Rendering
# =============================================================================

def render_route_decision(decision: TaskRouteDecision) -> str:
    """Render a route decision as terminal-safe, human-readable text."""
    sep = "=" * 64

    override = " (user override)" if decision.user_override else ""

    lines = [
        sep,
        "Route Decision",
        sep,
        f"  Task Size:      {decision.task_size}",
        f"  Run Mode:       {decision.run_mode}{override}",
        f"  Risk Level:     {decision.risk_level}",
        f"  Task Type:      {decision.task_type}",
        f"  Confidence:     {decision.confidence}",
        f"  Runtime:        {decision.runtime_support}",
    ]

    if decision.workflow_hint:
        lines.append(f"  Workflow Hint:  {decision.workflow_hint}")

    lines.append("")
    lines.append("Reasons:")
    for r in decision.reasons:
        lines.append(f"  - {r}")

    lines.append(sep)
    return "\n".join(lines)


def route_decision_to_dict(decision: TaskRouteDecision) -> dict[str, object]:
    """Serialize a TaskRouteDecision for persistence."""
    return {
        "task_size": decision.task_size,
        "run_mode": decision.run_mode,
        "risk_level": decision.risk_level,
        "task_type": decision.task_type,
        "confidence": decision.confidence,
        "reasons": decision.reasons,
        "signals": {k: str(v) for k, v in decision.signals.items()},
        "user_override": decision.user_override,
        "workflow_hint": decision.workflow_hint,
        "runtime_support": decision.runtime_support,
    }


# =============================================================================
# Run-mode semantics — single source of truth for what each mode means
# =============================================================================


def should_execute_workflow(decision: TaskRouteDecision) -> bool:
    """Return True if this route should actually run a workflow.

    off  → never execute
    log  → do not execute (only record/display the route)
    controlled → execute with AAO controls
    orchestrated → execute only if an orchestrated runner exists (currently: no)
    """
    if decision.run_mode == "off":
        return False
    if decision.run_mode == "log":
        return False
    if decision.run_mode == "orchestrated" and decision.runtime_support == "future_orchestrated":
        return False
    return True


def should_apply_control(decision: TaskRouteDecision) -> bool:
    """Return True if AAO control decisions (guardrails, evaluator, policy, recovery)
    should be applied during execution.

    off / log → no control
    controlled / orchestrated → apply control
    """
    return decision.run_mode in ("controlled", "orchestrated")


def should_only_log(decision: TaskRouteDecision) -> bool:
    """Return True if AAO should only record the route decision without blocking
    or executing a workflow.
    """
    return decision.run_mode in ("off", "log")


def requires_future_runner(decision: TaskRouteDecision) -> bool:
    """Return True if the run mode requires a runner that does not exist yet."""
    return (
        decision.run_mode == "orchestrated"
        and decision.runtime_support == "future_orchestrated"
    )


def effective_run_mode(decision: TaskRouteDecision) -> RunMode:
    """Return the effective run mode after resolving future/fallback states.

    An orchestrated route with future_orchestrated runtime support
    effectively falls back to controlled if the user forces execution.
    """
    if requires_future_runner(decision):
        return "controlled"
    return decision.run_mode


# =============================================================================
# Routing convenience — single call for ask/run command paths
# =============================================================================


def route_and_check(query: str, *, explicit_mode: RunMode | None = None) -> TaskRouteDecision:
    """Route a task and return the decision.  Pure convenience wrapper."""
    return route_task(query, explicit_mode=explicit_mode)
