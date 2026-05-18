from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from .failure_taxonomy import FailureCategory, FailureReason


class GuardrailViolation(ValueError):
    """护栏违规异常

    当护栏检查失败时抛出，携带失败类型信息。
    """

    def __init__(
        self,
        *,
        guardrail_name: str,
        stage: str,
        message: str,
        failure_category: FailureCategory = FailureCategory.GUARDRAIL_BLOCKED,
    ):
        super().__init__(message)
        self.guardrail_name = guardrail_name
        self.stage = stage
        self.message = message
        self.failure_category = failure_category


@dataclass(frozen=True)
class GuardrailSpec:
    name: str
    stage: Literal["input", "output"]
    description: str
    handler: Callable[..., None]


class GuardrailManager:
    def __init__(self) -> None:
        self._guardrails: dict[str, GuardrailSpec] = {}

    def register(
        self,
        *,
        name: str,
        stage: Literal["input", "output"],
        description: str,
        handler: Callable[..., None],
    ) -> None:
        if name in self._guardrails:
            raise ValueError(f"Guardrail '{name}' is already registered")
        self._guardrails[name] = GuardrailSpec(
            name=name,
            stage=stage,
            description=description,
            handler=handler,
        )

    def get(self, name: str) -> GuardrailSpec:
        if name not in self._guardrails:
            raise KeyError(f"Guardrail '{name}' is not registered")
        return self._guardrails[name]

    def run_many(
        self,
        *,
        names: list[str],
        stage: Literal["input", "output"],
        agent_name: str,
        payload: dict[str, Any],
    ) -> None:
        for name in names:
            spec = self.get(name)
            if spec.stage != stage:
                continue
            spec.handler(agent_name=agent_name, payload=payload)

    def list_names(self) -> list[str]:
        return sorted(self._guardrails)


def build_default_guardrail_manager() -> GuardrailManager:
    manager = GuardrailManager()
    manager.register(
        name="require_non_empty_query",
        stage="input",
        description="Reject agent execution when the query is empty or whitespace only.",
        handler=_require_non_empty_query,
    )
    manager.register(
        name="block_sensitive_output_terms",
        stage="output",
        description="Reject outputs that contain obvious secret-bearing tokens.",
        handler=_block_sensitive_output_terms,
    )
    return manager


def _require_non_empty_query(*, agent_name: str, payload: dict[str, Any]) -> None:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise GuardrailViolation(
            guardrail_name="require_non_empty_query",
            stage="input",
            message=f"{agent_name} 需要非空 query 才能继续执行",
        )


def _block_sensitive_output_terms(*, agent_name: str, payload: dict[str, Any]) -> None:
    lowered = _flatten_strings(payload).lower()
    blocked_terms = ("api_key", "password", "secret_key", "access_token")
    for term in blocked_terms:
        if term in lowered:
            raise GuardrailViolation(
                guardrail_name="block_sensitive_output_terms",
                stage="output",
                message=f"{agent_name} 的输出触发敏感信息护栏：{term}",
            )


def _flatten_strings(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_strings(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_strings(item) for item in value)
    return ""


# =============================================================================
# ToolCallGuardrailController — tool-loop detection
# Algorithm adapted from Hermes Agent (MIT): agent/tool_guardrails.py
# =============================================================================


class ToolLoopType(str, Enum):
    EXACT_REPEATED_FAILURE = "exact_repeated_failure"
    SAME_TOOL_REPEATED_FAILURE = "same_tool_repeated_failure"
    IDEMPOTENT_NO_PROGRESS = "idempotent_no_progress"


class ToolLoopAction(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"
    HALT = "halt"


@dataclass
class ToolLoopDetection:
    action: ToolLoopAction = ToolLoopAction.ALLOW
    loop_type: ToolLoopType | None = None
    tool_name: str | None = None
    detail: str = ""
    failure_reason: FailureReason | None = None


@dataclass
class _ToolCallRecord:
    tool_name: str
    args_hash: str
    result_hash: str
    success: bool
    timestamp: float = field(default_factory=time.monotonic)


def _make_hash(obj: Any) -> str:
    """Deterministic hash for tool args / results (dedup only, not crypto)."""
    raw = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


class ToolCallGuardrailController:
    """Detect tool-call loops: exact-repeat failure, same-tool failure, no-progress.

    Pure and testable — no I/O, no LLM calls.  Call ``record_call`` after every
    tool invocation, then ``check`` to see whether a loop has been detected.

    Two-tier thresholds: *warn* fires first (action=warn), *block* fires later
    (action=block/halt).  This lets the caller surface a warning to the agent
    before hard-stopping.
    """

    def __init__(
        self,
        max_exact_repeats: int = 2,
        max_same_tool_failures: int = 3,
        max_idempotent_calls: int = 3,
        *,
        warn_exact_repeats: int | None = None,
        warn_same_tool_failures: int | None = None,
        warn_idempotent_calls: int | None = None,
    ) -> None:
        self._history: list[_ToolCallRecord] = []
        self._max_exact = max_exact_repeats
        self._max_same_tool = max_same_tool_failures
        self._max_idempotent = max_idempotent_calls
        self._warn_exact = warn_exact_repeats if warn_exact_repeats is not None else max(1, max_exact_repeats - 1)
        self._warn_same_tool = warn_same_tool_failures if warn_same_tool_failures is not None else max(1, max_same_tool_failures - 1)
        self._warn_idempotent = warn_idempotent_calls if warn_idempotent_calls is not None else max(1, max_idempotent_calls - 1)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def record_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        *,
        success: bool,
    ) -> None:
        """Record a tool invocation result."""
        self._history.append(
            _ToolCallRecord(
                tool_name=tool_name,
                args_hash=_make_hash(args),
                result_hash=_make_hash(result),
                success=success,
            )
        )

    def check(self) -> ToolLoopDetection:
        """Check recent history for a tool-call loop.

        Checks are ordered by severity — exact-repeat is the tightest signal,
        so it is checked first.  Warn thresholds fire before block thresholds,
        giving callers a chance to surface warnings before hard-stopping.
        """
        if not self._history:
            return ToolLoopDetection(action=ToolLoopAction.ALLOW)

        # 1) Exact repeated failure
        detection = self._check_exact_repeated_failure()
        if detection.action in (ToolLoopAction.BLOCK, ToolLoopAction.HALT):
            return detection
        if detection.action == ToolLoopAction.WARN:
            return detection

        # 2) Same-tool repeated failure
        detection = self._check_same_tool_repeated_failure()
        if detection.action in (ToolLoopAction.BLOCK, ToolLoopAction.HALT):
            return detection
        if detection.action == ToolLoopAction.WARN:
            return detection

        # 3) Idempotent no-progress
        detection = self._check_idempotent_no_progress()
        if detection.action != ToolLoopAction.ALLOW:
            return detection

        return ToolLoopDetection(action=ToolLoopAction.ALLOW)

    def reset(self) -> None:
        """Clear all history."""
        self._history.clear()

    @property
    def history_len(self) -> int:
        return len(self._history)

    # ------------------------------------------------------------------
    # internal detectors
    # ------------------------------------------------------------------

    def _check_exact_repeated_failure(self) -> ToolLoopDetection:
        block_needed = self._max_exact + 1
        warn_needed = self._warn_exact + 1

        if len(self._history) < warn_needed:
            return ToolLoopDetection(action=ToolLoopAction.ALLOW)

        # Check for BLOCK first (stricter)
        if len(self._history) >= block_needed:
            recent = self._history[-block_needed:]
            first = recent[0]
            if not first.success and all(
                not r.success and r.tool_name == first.tool_name and r.args_hash == first.args_hash
                for r in recent[1:]
            ):
                return ToolLoopDetection(
                    action=ToolLoopAction.BLOCK,
                    loop_type=ToolLoopType.EXACT_REPEATED_FAILURE,
                    tool_name=first.tool_name,
                    detail=(
                        f"Tool '{first.tool_name}' called {len(recent)} times with "
                        f"identical args and failed every time."
                    ),
                    failure_reason=FailureReason.EXACT_REPEATED_TOOL_FAILURE,
                )

        # Check for WARN
        recent = self._history[-warn_needed:]
        first = recent[0]
        if not first.success and all(
            not r.success and r.tool_name == first.tool_name and r.args_hash == first.args_hash
            for r in recent[1:]
        ):
            return ToolLoopDetection(
                action=ToolLoopAction.WARN,
                loop_type=ToolLoopType.EXACT_REPEATED_FAILURE,
                tool_name=first.tool_name,
                detail=(
                    f"Tool '{first.tool_name}' called {len(recent)} times with "
                    f"identical args and failed each time."
                ),
                failure_reason=FailureReason.EXACT_REPEATED_TOOL_FAILURE,
            )

        return ToolLoopDetection(action=ToolLoopAction.ALLOW)

    def _check_same_tool_repeated_failure(self) -> ToolLoopDetection:
        block_needed = self._max_same_tool + 1
        warn_needed = self._warn_same_tool + 1

        if len(self._history) < warn_needed:
            return ToolLoopDetection(action=ToolLoopAction.ALLOW)

        baseline_tool = self._history[-1].tool_name

        if len(self._history) >= block_needed:
            recent = self._history[-block_needed:]
            if all(not r.success and r.tool_name == baseline_tool for r in recent):
                return ToolLoopDetection(
                    action=ToolLoopAction.BLOCK,
                    loop_type=ToolLoopType.SAME_TOOL_REPEATED_FAILURE,
                    tool_name=baseline_tool,
                    detail=(
                        f"Tool '{baseline_tool}' failed {len(recent)} consecutive "
                        f"times with different arguments."
                    ),
                    failure_reason=FailureReason.SAME_TOOL_REPEATED_FAILURE,
                )

        recent = self._history[-warn_needed:]
        if all(not r.success and r.tool_name == baseline_tool for r in recent):
            return ToolLoopDetection(
                action=ToolLoopAction.WARN,
                loop_type=ToolLoopType.SAME_TOOL_REPEATED_FAILURE,
                tool_name=baseline_tool,
                detail=(
                    f"Tool '{baseline_tool}' failed {len(recent)} consecutive "
                    f"times with different arguments."
                ),
                failure_reason=FailureReason.SAME_TOOL_REPEATED_FAILURE,
            )

        return ToolLoopDetection(action=ToolLoopAction.ALLOW)

    def _check_idempotent_no_progress(self) -> ToolLoopDetection:
        block_needed = self._max_idempotent + 1
        warn_needed = self._warn_idempotent + 1

        if len(self._history) < warn_needed:
            return ToolLoopDetection(action=ToolLoopAction.ALLOW)

        baseline_tool = self._history[-1].tool_name

        if len(self._history) >= block_needed:
            recent = self._history[-block_needed:]
            first = recent[0]
            if first.success and all(
                r.success and r.tool_name == baseline_tool and r.result_hash == first.result_hash
                for r in recent[1:]
            ):
                return ToolLoopDetection(
                    action=ToolLoopAction.HALT,
                    loop_type=ToolLoopType.IDEMPOTENT_NO_PROGRESS,
                    tool_name=baseline_tool,
                    detail=(
                        f"Tool '{baseline_tool}' returned the same result {len(recent)} "
                        f"consecutive times — no progress is being made."
                    ),
                    failure_reason=FailureReason.IDEMPOTENT_NO_PROGRESS,
                )

        recent = self._history[-warn_needed:]
        first = recent[0]
        if first.success and all(
            r.success and r.tool_name == baseline_tool and r.result_hash == first.result_hash
            for r in recent[1:]
        ):
            return ToolLoopDetection(
                action=ToolLoopAction.WARN,
                loop_type=ToolLoopType.IDEMPOTENT_NO_PROGRESS,
                tool_name=baseline_tool,
                detail=(
                    f"Tool '{baseline_tool}' returned the same result {len(recent)} "
                    f"consecutive times — may indicate stalled progress."
                ),
                failure_reason=FailureReason.IDEMPOTENT_NO_PROGRESS,
            )

        return ToolLoopDetection(action=ToolLoopAction.ALLOW)
