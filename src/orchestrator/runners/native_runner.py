"""NativeRunner — wraps the existing sequential Scheduler in the RunnerProtocol.

This is NOT a new runner.  It is an adapter that gives the existing
scheduler the same interface as LangGraphRunner so orchestrated-mode
code can call either one without branching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import RunnerResult


@dataclass
class NativeRunner:
    """RunnerProtocol adapter over the existing sequential Scheduler.

    Does NOT change scheduler behaviour.  Merely wraps run() -> RunnerResult.
    """

    _workflow: dict[str, Any] = field(default_factory=dict)
    _project_root: str = "."

    @property
    def runner_name(self) -> str:
        return "native"

    def configure(self, *, workflow: dict[str, Any], project_root: str = ".") -> None:
        """Set workflow and project root before run()."""
        self._workflow = workflow
        self._project_root = project_root

    def run(
        self,
        *,
        plan: Any = None,
        control_plane: Any = None,
        memory_manager: Any = None,
        project_root: Any = None,
        policy: Any = None,
        recovery_playbook: Any = None,
        state_center: Any = None,
        **kwargs: Any,
    ) -> RunnerResult:
        """Execute via the existing Scheduler and convert its result.

        The plan, control_plane, memory_manager, etc. are accepted for
        protocol compatibility but the NativeRunner uses the Scheduler's
        own construction (which already wires all of these internally).

        *plan* is ignored — the native scheduler uses its own workflow dict.
        """
        from ..scheduler import Scheduler

        root = str(project_root or self._project_root)
        workflow = kwargs.get("workflow") or self._workflow
        query = str(kwargs.get("query", ""))

        scheduler = Scheduler(
            workflow=workflow,
            project_root=root,
            use_orchestrator=True,
            policy=policy,
            recovery_playbook=recovery_playbook,
        )

        state, run_result = scheduler.run(query)

        # Collect evidence paths from state trace
        evidence_paths: list[str] = []
        for event in state.execution_trace:
            ep = event.get("evidence_path") or event.get("report_path")
            if ep and ep not in evidence_paths:
                evidence_paths.append(str(ep))

        control_events = [
            e for e in state.execution_trace
            if e.get("event") in (
                "evaluation", "policy_decision", "recovery_decision",
                "guardrail_violation", "human_review_decision",
            )
        ]

        # Map RunResult -> RunnerResult
        return RunnerResult(
            run_id=run_result.task_id,
            status=run_result.status,
            steps_completed=state.convergence.global_step,
            last_node=run_result.final_node,
            evidence_paths=evidence_paths,
            control_events=control_events,
            failure_record=(
                {"category": run_result.failure_reason, "reason": run_result.reason}
                if run_result.status in ("failed", "timed_out")
                else None
            ),
            recovery_actions=[
                e.get("action", "") for e in control_events
                if e.get("event") == "recovery_decision"
            ],
            report_path=run_result.convergence_report_path,
            human_review_state=(
                "awaiting" if run_result.status == "needs_human_review" else None
            ),
            reason=run_result.reason,
        )
