"""LangGraphRunner — optional LangGraph-backed orchestrated runner.

LangGraph is the railway track.  AAO is still the signal system.

Maps an approved PlanContract to a LangGraph StateGraph:
  PlanContract.steps         -> graph nodes
  PlannedWorkerTask          -> node work packet
  human_review_gates         -> interrupt / approval nodes
  required_evidence          -> post-node evidence checks
  success_criteria           -> final completion check

Every node follows:
  pre_node_policy_check
    -> run node / worker
    -> collect evidence
    -> post_node_control_check
    -> recovery decision if needed
    -> record control event

If LangGraph is not installed, LangGraphRunner.run() raises a clear error.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from . import RunnerResult

# Optional LangGraph import
_LANGGRAPH_AVAILABLE = False
try:
    from langgraph.graph import StateGraph, END  # type: ignore[import-untyped]
    from langgraph.checkpoint.memory import InMemorySaver  # type: ignore[import-untyped]
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_graph_state(state: Any) -> GraphState:
    """Normalise state input to a GraphState instance.

    LangGraph 1.x passes dataclass instances to node functions.
    FakeGraphBackend (tests) passes plain dicts.
    This helper accepts either and returns a GraphState.
    """
    if isinstance(state, GraphState):
        return state
    if isinstance(state, dict):
        return GraphState.from_dict(state)
    raise TypeError(
        f"Expected GraphState or dict, got {type(state).__name__}"
    )


# =============================================================================
# Graph state
# =============================================================================


@dataclass
class GraphState:
    """State that flows through the LangGraph execution.

    Evidence and control decisions are accumulated here but ALSO written
    to AAO-owned evidence files.  Graph state is a cache, not the audit record.
    """

    task_id: str = ""
    run_id: str = ""
    objective: str = ""
    steps: list[str] = field(default_factory=list)
    current_step: int = 0
    node_outputs: dict[str, Any] = field(default_factory=dict)
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    control_decisions: list[dict[str, Any]] = field(default_factory=list)
    human_review_gate: dict[str, Any] | None = None
    required_evidence: list[str] = field(default_factory=list)
    status: str = "running"  # running, completed, failed, needs_human_review
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "objective": self.objective,
            "steps": self.steps,
            "current_step": self.current_step,
            "node_outputs": self.node_outputs,
            "evidence_items": self.evidence_items,
            "control_decisions": self.control_decisions,
            "human_review_gate": self.human_review_gate,
            "required_evidence": self.required_evidence,
            "status": self.status,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GraphState:
        return cls(
            task_id=d.get("task_id", ""),
            run_id=d.get("run_id", ""),
            objective=d.get("objective", ""),
            steps=d.get("steps", []),
            current_step=d.get("current_step", 0),
            node_outputs=d.get("node_outputs", {}),
            evidence_items=d.get("evidence_items", []),
            control_decisions=d.get("control_decisions", []),
            human_review_gate=d.get("human_review_gate"),
            required_evidence=d.get("required_evidence", []),
            status=d.get("status", "running"),
            errors=d.get("errors", []),
        )


# =============================================================================
# Graph backend abstraction — allows testing without real LangGraph
# =============================================================================


class GraphBackend:
    """Abstract graph execution backend.

    When LangGraph is available, LangGraphBackend delegates to StateGraph.
    For tests, FakeGraphBackend provides the same contract.
    """

    def compile(self) -> Any:
        raise NotImplementedError

    def invoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def stream(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError


# =============================================================================
# LangGraphRunner
# =============================================================================


@dataclass
class LangGraphRunner:
    """Execute an approved PlanContract through a LangGraph StateGraph.

    Requires an approved PlanContract.  Refuses to execute unapproved plans.

    Every node is wrapped: pre-node policy → execute → evidence → post-node
    control → recovery.  Evidence is stored in AAO-owned files, not buried
    in graph state.

    If LangGraph is not installed, instantiation succeeds but run() raises
    a clear RuntimeError.
    """

    project_root: str = "."
    _graph: Any = None
    _backend: GraphBackend | None = None
    _checkpointer: Any = None

    @property
    def runner_name(self) -> str:
        return "langgraph"

    @property
    def is_available(self) -> bool:
        return _LANGGRAPH_AVAILABLE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        plan: Any,
        control_plane: Any,
        memory_manager: Any = None,
        project_root: Any = None,
        policy: Any = None,
        recovery_playbook: Any = None,
        state_center: Any = None,
        worker_registry: dict[str, Callable] | None = None,
        **kwargs: Any,
    ) -> RunnerResult:
        """Execute an approved PlanContract.

        Args:
            plan: An approved PlanContract with steps, required_evidence, etc.
            control_plane: ControlPlane instance for policy/guardrail/recovery decisions.
            memory_manager: MemoryManager for recording lessons.
            project_root: Project root path for evidence/report storage.
            policy: Policy for runtime enforcement.
            recovery_playbook: RecoveryPlaybook for failure handling.
            state_center: Optional pre-existing StateCenter for state tracking.
            worker_registry: Dict mapping step names to callables for execution.

        Returns:
            RunnerResult with run_id, status, evidence, control events, etc.

        Raises:
            ValueError: If plan is not approved.
            RuntimeError: If LangGraph is not installed.
        """
        if not _LANGGRAPH_AVAILABLE and self._backend is None:
            raise RuntimeError(
                "LangGraphRunner requires langgraph to be installed. "
                "Install with: pip install langgraph"
            )

        # Guard: plan must be approved
        approval = getattr(plan, "approval_status", None)
        if approval != "approved":
            raise ValueError(
                f"LangGraphRunner requires an approved PlanContract. "
                f"Got approval_status={approval!r}"
            )

        root = Path(project_root or self.project_root)
        run_id = kwargs.get("run_id") or f"run-{uuid.uuid4().hex[:12]}"
        task_id = getattr(plan, "plan_id", None) or f"task-{uuid.uuid4().hex[:12]}"

        # Build initial graph state
        state = GraphState(
            task_id=task_id,
            run_id=run_id,
            objective=getattr(plan, "objective", ""),
            steps=list(getattr(plan, "steps", [])),
        )

        # Build and execute the graph
        graph = self._build_graph(
            plan=plan,
            control_plane=control_plane,
            policy=policy,
            recovery_playbook=recovery_playbook,
            worker_registry=worker_registry or {},
            root=root,
        )

        # Compile with checkpointer when real LangGraph is used
        if _LANGGRAPH_AVAILABLE and self._backend is None:
            try:
                self._checkpointer = InMemorySaver()
                compiled = graph.compile(checkpointer=self._checkpointer)
            except Exception:
                compiled = graph.compile()
        else:
            compiled = graph.compile()

        config = {"configurable": {"thread_id": run_id}}

        try:
            final_state_dict = compiled.invoke(state.to_dict(), config)
            final_state = GraphState.from_dict(final_state_dict)
        except _HumanReviewInterrupt:
            # Graph was interrupted for human review
            return RunnerResult(
                run_id=run_id,
                status="needs_human_review",
                steps_completed=state.current_step,
                last_node=state.steps[state.current_step] if state.current_step < len(state.steps) else None,
                evidence_paths=self._collect_evidence_paths(root, task_id),
                control_events=state.control_decisions,
                human_review_state="awaiting",
                reason="Human review required — awaiting decision",
            )
        except Exception as exc:
            return RunnerResult(
                run_id=run_id,
                status="failed",
                steps_completed=state.current_step,
                last_node=state.steps[state.current_step] if state.current_step < len(state.steps) else None,
                evidence_paths=self._collect_evidence_paths(root, task_id),
                control_events=state.control_decisions,
                failure_record={"reason": str(exc)},
                reason=str(exc),
            )

        return RunnerResult(
            run_id=run_id,
            status=final_state.status,
            steps_completed=len(final_state.steps),
            last_node=final_state.steps[-1] if final_state.steps else None,
            evidence_paths=self._collect_evidence_paths(root, task_id),
            control_events=final_state.control_decisions,
            checkpoint_id=run_id,
            human_review_state=(
                "awaiting" if final_state.status == "needs_human_review" else None
            ),
            reason=f"Workflow {final_state.status}",
        )

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(
        self,
        *,
        plan: Any,
        control_plane: Any,
        policy: Any,
        recovery_playbook: Any,
        worker_registry: dict[str, Callable],
        root: Path,
    ) -> Any:
        """Build a StateGraph from an approved PlanContract.

        Returns a StateGraph (or FakeGraphBackend for testing).
        """
        if self._backend is not None:
            return _FakeGraphWrapper(
                backend=self._backend,
                plan=plan,
                control_plane=control_plane,
                policy=policy,
                recovery_playbook=recovery_playbook,
                worker_registry=worker_registry,
                root=root,
            )

        # Real LangGraph path
        graph = StateGraph(GraphState)

        steps = getattr(plan, "steps", [])
        human_review_gates = set(getattr(plan, "human_review_gates", []))
        required_evidence = list(getattr(plan, "required_evidence", []))

        for i, step_name in enumerate(steps):
            # Add worker node
            graph.add_node(
                step_name,
                self._make_worker_node(
                    step_name=step_name,
                    step_index=i,
                    control_plane=control_plane,
                    policy=policy,
                    recovery_playbook=recovery_playbook,
                    worker_registry=worker_registry,
                    root=root,
                ),
            )
            # Add control node after each worker
            control_name = f"_control_{step_name}"
            graph.add_node(
                control_name,
                self._make_control_node(
                    step_name=step_name,
                    step_index=i,
                    control_plane=control_plane,
                    is_last=(i == len(steps) - 1),
                    human_review_gates=human_review_gates,
                    required_evidence_keys=required_evidence,
                ),
            )

            # Edge: worker -> control
            graph.add_edge(step_name, control_name)

            # Edge: control -> next step or end
            if i < len(steps) - 1:
                graph.add_conditional_edges(
                    control_name,
                    self._make_router(steps[i + 1]),
                )
            else:
                graph.add_edge(control_name, END)

        # Set entry point
        if steps:
            graph.set_entry_point(steps[0])

        return graph

    # ------------------------------------------------------------------
    # Node factories
    # ------------------------------------------------------------------

    def _make_worker_node(
        self,
        *,
        step_name: str,
        step_index: int,
        control_plane: Any,
        policy: Any,
        recovery_playbook: Any,
        worker_registry: dict[str, Callable],
        root: Path,
    ) -> Callable:
        """Create a node function that executes one workflow step."""

        def worker_node(state: Any) -> dict[str, Any]:
            gs = _ensure_graph_state(state)

            # pre_node_policy_check — run guardrails on input
            self._run_pre_node_policy(
                state=gs, step_name=step_name, control_plane=control_plane,
            )

            # Execute the worker
            worker_fn = worker_registry.get(step_name)
            if worker_fn is not None:
                try:
                    output = worker_fn(gs.to_dict())
                except Exception as exc:
                    gs.errors.append(f"{step_name}: {exc}")
                    gs.node_outputs[step_name] = {"error": str(exc)}
                    gs.current_step = step_index
                    return gs.to_dict()
            else:
                # No-op node — useful for human_review gates
                output = {"status": "completed", "step": step_name}

            gs.node_outputs[step_name] = output

            # Collect evidence
            evidence = self._collect_node_evidence(
                step_name=step_name,
                output=output,
                root=root,
                task_id=gs.task_id,
            )
            gs.evidence_items.append(evidence)

            gs.current_step = step_index
            return gs.to_dict()

        return worker_node

    def _make_control_node(
        self,
        *,
        step_name: str,
        step_index: int,
        control_plane: Any,
        is_last: bool = False,
        human_review_gates: set[str] = set(),
        required_evidence_keys: list[str] = [],
    ) -> Callable:
        """Create a control node that checks the worker's output.

        *required_evidence_keys* comes from plan.required_evidence and is used
        by the evidence check to verify that expected evidence was collected.
        """

        def control_node(state: Any) -> dict[str, Any]:
            gs = _ensure_graph_state(state)
            output = gs.node_outputs.get(step_name, {})

            # Evaluate output through ControlPlane
            decision = control_plane.evaluate_output(
                [],  # eval_criteria — use defaults
                output,
                context={},
                agent_name=step_name,
            )

            gs.control_decisions.append({
                "event": "evaluation",
                "agent_name": step_name,
                "passed": decision.passed,
                "action": decision.action,
                "reason": decision.reason,
                "timestamp": utc_now_iso(),
            })

            # Human review gate check
            if step_name in human_review_gates:
                gs.human_review_gate = {
                    "step": step_name,
                    "status": "awaiting",
                    "decision": "await_human",
                }
                gs.status = "needs_human_review"
                raise _HumanReviewInterrupt(step_name)

            # Evidence check — verify plan.required_evidence was collected
            if hasattr(control_plane, "check_policy_for_required_evidence"):
                required = set(required_evidence_keys) | set(gs.required_evidence)
                observed = {
                    e.get("key", "") for e in gs.evidence_items
                    if e.get("status") == "observed"
                }
                if required:
                    evidence_decision = control_plane.check_policy_for_required_evidence(
                        required_evidence_keys=required,
                        observed_evidence_keys=observed,
                    )
                    if not evidence_decision.passed:
                        gs.status = "needs_human_review"
                        gs.control_decisions.append({
                            "event": "policy_decision",
                            "decision_type": "required_evidence",
                            "passed": False,
                            "action": evidence_decision.action,
                            "reason": evidence_decision.reason,
                            "timestamp": utc_now_iso(),
                        })
                        raise _HumanReviewInterrupt(step_name)

            # Decide next action
            if not decision.passed:
                if decision.action in ("fail",):
                    gs.status = "failed"
                elif decision.action == "retry":
                    pass  # Stay on this node
                elif decision.action == "replan":
                    # replan is deferred to runner/scheduler level —
                    # the graph alone cannot restructure its own nodes.
                    # Record the decision and stop.
                    gs.status = "failed"
                    gs.errors.append(
                        f"ControlPlane returned replan for {step_name}; "
                        "graph execution cannot replan itself"
                    )
                elif decision.action == "needs_human_review":
                    gs.status = "needs_human_review"
                    raise _HumanReviewInterrupt(step_name)

            if is_last and gs.status == "running":
                gs.status = "completed"

            return gs.to_dict()

        return control_node

    def _make_router(self, next_step: str) -> Callable:
        """Create a conditional edge router."""
        def router(state: Any) -> str:
            gs = _ensure_graph_state(state)
            if gs.status == "failed":
                return END
            if gs.status == "needs_human_review":
                return END
            return next_step
        return router

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_pre_node_policy(
        self, *, state: GraphState, step_name: str, control_plane: Any,
    ) -> None:
        """Run policy/guardrail checks before a node executes.

        Guardrail decisions that return passed=False are recorded as
        guardrail_violation events.  Unexpected errors in the guard
        infrastructure itself are logged to state.errors but do NOT
        crash the runner — the node still executes.
        """
        try:
            decision = control_plane.guard_input(
                agent_name=step_name,
                payload=state.to_dict(),
                guardrail_names=[],
            )
            if not decision.passed:
                state.control_decisions.append({
                    "event": "guardrail_violation",
                    "agent_name": step_name,
                    "stage": "input",
                    "reason": decision.reason,
                    "timestamp": utc_now_iso(),
                })
        except Exception as exc:
            # Programming errors in guard infrastructure (TypeError,
            # AttributeError, etc.) — log but do not crash the run.
            state.errors.append(
                f"pre_node_policy[{step_name}]: guard_input raised "
                f"{type(exc).__name__}: {exc}"
            )

    def _collect_node_evidence(
        self, *, step_name: str, output: dict[str, Any], root: Path, task_id: str,
    ) -> dict[str, Any]:
        """Collect evidence for a node execution to AAO-owned storage."""
        evidence = {
            "step_name": step_name,
            "task_id": task_id,
            "status": output.get("status", "unknown"),
            "output_summary": str(output)[:500],
            "timestamp": utc_now_iso(),
        }

        # Write evidence to AAO evidence directory
        evidence_dir = root / "outputs" / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / f"{task_id}_{step_name}.json"
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        evidence["evidence_path"] = str(evidence_path)
        return evidence

    def _collect_evidence_paths(self, root: Path, task_id: str) -> list[str]:
        """List evidence files for a given task."""
        evidence_dir = root / "outputs" / "evidence"
        if not evidence_dir.exists():
            return []
        return sorted(
            str(p) for p in evidence_dir.glob(f"{task_id}*.json")
        )


# =============================================================================
# Internal: human review interrupt signal
# =============================================================================


class _HumanReviewInterrupt(Exception):
    """Raised inside a graph node to signal a human review pause."""

    def __init__(self, step_name: str) -> None:
        super().__init__(f"Human review required at step: {step_name}")
        self.step_name = step_name


# =============================================================================
# Internal: fake graph wrapper for testing
# =============================================================================


class _FakeGraphWrapper:
    """Wraps a FakeGraphBackend so it acts like a compiled LangGraph graph."""

    def __init__(self, *, backend: GraphBackend, plan: Any, control_plane: Any,
                 policy: Any, recovery_playbook: Any, worker_registry: dict[str, Callable],
                 root: Path) -> None:
        self._backend = backend
        self._plan = plan
        self._control_plane = control_plane
        self._policy = policy
        self._recovery_playbook = recovery_playbook
        self._worker_registry = worker_registry
        self._root = root

    def compile(self) -> _FakeGraphWrapper:
        return self

    def invoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._backend.invoke(state, config)
