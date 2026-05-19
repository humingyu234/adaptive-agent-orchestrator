"""Runner abstraction — protocol, result, and implementations.

Runners execute workflow structure.  They are NOT workers — workers perform
work inside a node.  Runners decide node order, checkpoint/resume, and
interrupt handling.

RunnerProtocol
    The contract every runner must satisfy.
RunnerResult
    Standardised result that every runner returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..control_models import ControlDecision


# =============================================================================
# RunnerResult
# =============================================================================


@dataclass
class RunnerResult:
    """Standardised result from any runner implementation.

    This is runner-level, not task-level.  The caller maps it to RunResult
    or other downstream models as needed.
    """

    run_id: str
    status: str  # completed, failed, timed_out, needs_human_review
    steps_completed: int = 0
    last_node: str | None = None
    evidence_paths: list[str] = field(default_factory=list)
    control_events: list[dict[str, Any]] = field(default_factory=list)
    failure_record: dict[str, Any] | None = None
    recovery_actions: list[str] = field(default_factory=list)
    checkpoint_id: str | None = None
    report_path: str | None = None
    human_review_state: str | None = None  # None, awaiting, approved, rejected
    reason: str = ""


# =============================================================================
# RunnerProtocol
# =============================================================================


@runtime_checkable
class RunnerProtocol(Protocol):
    """Contract that every runner must satisfy.

    A runner takes an approved PlanContract and executes its steps, calling
    ControlPlane after each meaningful node.  It returns a RunnerResult.
    """

    def run(self, *, plan: Any, control_plane: Any, memory_manager: Any,
            project_root: Any, policy: Any, recovery_playbook: Any,
            state_center: Any | None, **kwargs: Any) -> RunnerResult:
        """Execute the approved plan and return a standardised result."""
        ...

    @property
    def runner_name(self) -> str:
        """Human-readable runner identifier (e.g. 'native', 'langgraph')."""
        ...


# =============================================================================
# Imports (lazy — avoid circular imports)
# =============================================================================


def get_native_runner():
    """Return NativeRunner class, imported on demand."""
    from .native_runner import NativeRunner
    return NativeRunner


def get_langgraph_runner():
    """Return LangGraphRunner class if available, None otherwise."""
    try:
        from .langgraph_runner import LangGraphRunner
        return LangGraphRunner
    except ImportError:
        return None
