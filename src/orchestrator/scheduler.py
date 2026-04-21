import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .evaluator import Evaluator
from .failure_taxonomy import FailureCategory, FailureRecord, create_failure_record, infer_failure_category
from .guardrails import GuardrailViolation
from .live_interrupt import InterruptSignal, LiveInterruptController
from .llm_client import LLMClient
from .llm_providers import get_provider
from .memory_manager import MemoryManager
from .models import EvalResult, RunResult
from .registry import get_agent
from .project_context import ProjectContext
from .report_writer import ConvergenceReportWriter
from .state_center import StateCenter
from .supervisor_orchestrator import OrchestrationDecision, SupervisorOrchestrator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Scheduler:
    def __init__(
        self,
        workflow: dict,
        project_root: str | Path | None = None,
        use_orchestrator: bool = True,
        llm_overrides: dict[str, dict[str, str | None]] | None = None,
    ):
        self.workflow = workflow
        self.evaluator = Evaluator()
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.memory_manager = MemoryManager(self.project_root)
        self.project_context = ProjectContext(self.project_root)
        self.report_writer = ConvergenceReportWriter(self.project_root, workflow)
        self.interrupt_controller = LiveInterruptController(
            self.project_root / "outputs" / "interrupts" / "signal.json"
        )
        self.llm_overrides = llm_overrides or {}
        self.orchestrator: SupervisorOrchestrator | None = None
        if use_orchestrator:
            self.orchestrator = SupervisorOrchestrator(
                max_iterations=workflow.get("max_steps", 10),
                stall_threshold=3,
            )

    def run(self, query: str) -> tuple[StateCenter, RunResult]:
        state = StateCenter(query=query, max_steps=self.workflow.get("max_steps", 10))
        retrieved_memories = self.memory_manager.retrieve(query=query, top_k=3)
        state.write("retrieved_memories", retrieved_memories, "memory_manager")

        agents = self.workflow.get("agents", [])
        workflow_agents = [node["name"] for node in agents]
        if self.orchestrator:
            self.orchestrator.initialize(query, workflow_agents)

        self._create_runtime_checkpoint(
            state=state,
            created_by="scheduler",
            reason="initial_state",
            node_name="bootstrap",
            node_index=-1,
        )
        return self._execute_agents(
            state=state,
            agents=agents,
            workflow_agents=workflow_agents,
            start_index=0,
        )

    def resume_human_review(
        self,
        *,
        state: StateCenter,
        decision: str,
        reason: str = "",
    ) -> tuple[StateCenter, RunResult]:
        agents = self.workflow.get("agents", [])
        workflow_agents = [node["name"] for node in agents]
        if self.orchestrator:
            self.orchestrator.initialize(state.data_pool.query, workflow_agents)

        human_index = next((index for index, node in enumerate(agents) if node["name"] == "human_review"), None)
        if human_index is None:
            return self._finalize_run(
                state=state,
                status="failed",
                final_node=None,
                reason="当前 workflow 不包含 human_review 节点",
            )

        gate = state.data_pool.intermediate.get("human_review_gate")
        if not isinstance(gate, dict):
            return self._finalize_run(
                state=state,
                status="failed",
                final_node="human_review",
                reason="未找到 human_review_gate，无法继续处理人工审核结果",
            )

        normalized_decision = decision.strip().lower()
        state.execution_trace.append(
            {
                "event": "human_review_decision",
                "decision": normalized_decision,
                "reason": reason,
                "timestamp": utc_now_iso(),
            }
        )

        if normalized_decision == "approve":
            gate["decision"] = "approved"
            gate["status"] = "approved"
            if reason:
                gate["review_reason"] = reason
            state.set_status("running", "")
            next_index = human_index + 1
            if next_index < len(agents):
                return self._execute_agents(
                    state=state,
                    agents=agents,
                    workflow_agents=workflow_agents,
                    start_index=next_index,
                )
            return self._finalize_run(
                state=state,
                status="completed",
                final_node="human_review",
                reason=reason or "人工审核已通过",
            )

        if normalized_decision == "reject":
            gate["decision"] = "rejected"
            gate["status"] = "rejected"
            if reason:
                gate["review_reason"] = reason

            recommended_target = str(gate.get("recommended_target", "none") or "none")
            recommended_action = str(gate.get("recommended_action", "accept") or "accept")
            if recommended_target not in {"", "none", "human_review"}:
                target_index = next(
                    (index for index, node in enumerate(agents) if node["name"] == recommended_target),
                    None,
                )
                if target_index is not None:
                    state.set_status("running", "")
                    state.data_pool.intermediate.pop("human_review_gate", None)
                    self._prepare_revision_target(
                        state=state,
                        target=recommended_target,
                        target_index=target_index,
                        action=recommended_action,
                    )
                    if state.metadata.status == "failed":
                        return self._finalize_run(
                            state=state,
                            status="failed",
                            final_node="human_review",
                            reason=state.metadata.failure_reason,
                        )
                    return self._execute_agents(
                        state=state,
                        agents=agents,
                        workflow_agents=workflow_agents,
                        start_index=target_index,
                    )

            return self._finalize_run(
                state=state,
                status="failed",
                final_node="human_review",
                reason=reason or "人工审核拒绝",
            )

        return self._finalize_run(
            state=state,
            status="failed",
            final_node="human_review",
            reason=f"不支持的人工审核决策：{decision}",
        )

    def _execute_agents(
        self,
        *,
        state: StateCenter,
        agents: list[dict],
        workflow_agents: list[str],
        start_index: int,
    ) -> tuple[StateCenter, RunResult]:
        current_index = start_index
        while current_index < len(agents):
            if state.convergence.global_step >= state.convergence.max_steps:
                return self._finalize_run(
                    state=state,
                    status="timed_out",
                    final_node=agents[current_index]["name"] if current_index < len(agents) else None,
                    reason="达到最大步数限制",
                )

            node = agents[current_index]
            agent_name = node["name"]
            interrupt_result = self._handle_live_interrupt(
                state=state,
                agents=agents,
                current_index=current_index,
            )
            if interrupt_result is not None:
                if isinstance(interrupt_result, tuple):
                    return interrupt_result
                current_index = interrupt_result
                continue

            agent_cls = get_agent(agent_name)
            agent = self._build_agent(agent_cls=agent_cls, agent_name=agent_name)

            view = state.prepare_view(agent.config.reads)
            view.update(self.project_context.get_context_for_agent(agent.config.reads))
            start = perf_counter()
            output: dict = {}
            error_message = ""
            status = "success"

            try:
                agent.apply_input_guardrails(view)
                output = agent.run(view)
                agent.apply_output_guardrails(output)
                for write_spec in agent.config.writes:
                    if write_spec.field in output:
                        state.write(write_spec.field, output[write_spec.field], agent.config.name)
            except GuardrailViolation as exc:
                status = "guardrail_blocked"
                error_message = exc.message
                state.execution_trace.append(
                    {
                        "event": "guardrail_violation",
                        "agent_name": agent_name,
                        "guardrail_name": exc.guardrail_name,
                        "stage": exc.stage,
                        "reason": exc.message,
                        "failure_category": exc.failure_category.value,
                        "timestamp": utc_now_iso(),
                    }
                )
            except Exception as exc:  # pragma: no cover - runtime defensive path
                status = "error"
                error_message = str(exc)

            duration_ms = int((perf_counter() - start) * 1000)

            if status in {"error", "guardrail_blocked"}:
                if self.orchestrator:
                    self.orchestrator.mark_agent_failed(
                        agent_name,
                        error_message,
                        blocked=status == "guardrail_blocked",
                    )
                state.convergence.global_step += 1
                state.set_status("failed", error_message)
                self._append_execution_log(
                    state=state,
                    agent=agent_name,
                    step=state.convergence.global_step,
                    input_view=view,
                    output={"error": error_message},
                    duration_ms=duration_ms,
                    status=status,
                )

                if self.orchestrator and status == "error":
                    failure_decision = self.orchestrator.handle_failure(
                        agent_name=agent_name,
                        error=error_message,
                        workflow_agents=workflow_agents,
                    )
                    if failure_decision.action == "re_plan":
                        planner_index = next(
                            (i for i, workflow_node in enumerate(agents) if workflow_node["name"] == "planner"),
                            None,
                        )
                        if planner_index is not None:
                            self._prepare_replan(state)
                            state.execution_trace.append(
                                {
                                    "event": "orchestrator_replan",
                                    "reason": failure_decision.reason,
                                    "timestamp": utc_now_iso(),
                                }
                            )
                            current_index = planner_index
                            continue
                    if failure_decision.action == "continue" and failure_decision.next_agent:
                        target_index = next(
                            (
                                i
                                for i, workflow_node in enumerate(agents)
                                if workflow_node["name"] == failure_decision.next_agent
                            ),
                            None,
                        )
                        if target_index is not None:
                            current_index = target_index
                            continue

                return self._finalize_run(
                    state=state,
                    status="failed",
                    final_node=agent_name,
                    reason=error_message,
                )

            if self.orchestrator:
                self.orchestrator.mark_agent_completed(agent_name, output)

            eval_result = self.evaluator.evaluate(
                agent.config.eval_criteria,
                output,
                context=view,
                agent_name=agent_name,
            )
            state.execution_trace.append(
                {
                    "event": "evaluation",
                    "agent_name": agent_name,
                    "passed": eval_result.passed,
                    "action": eval_result.action,
                    "reason": eval_result.reason,
                    "timestamp": utc_now_iso(),
                }
            )

            state.convergence.global_step += 1
            self._append_execution_log(
                state=state,
                agent=agent_name,
                step=state.convergence.global_step,
                input_view=view,
                output=output,
                duration_ms=duration_ms,
                status="success",
                eval_result=eval_result,
            )
            self._create_runtime_checkpoint(
                state=state,
                created_by=agent_name,
                reason="post_step_success",
                node_name=agent_name,
                node_index=current_index,
            )

            if eval_result.action == "continue":
                if agent.config.terminal_behavior == "pause_for_human":
                    human_review_gate = self._read_terminal_payload(state=state, agent=agent) or {}
                    decision = human_review_gate.get("decision")
                    if decision == "await_human":
                        return self._finalize_run(
                            state=state,
                            status="needs_human_review",
                            final_node=agent_name,
                            reason="等待人工确认后再继续",
                        )

                if self.orchestrator:
                    orch_decision = self._get_orchestrator_decision(
                        state=state,
                        workflow_agents=workflow_agents,
                        current_agent=agent_name,
                    )
                    if orch_decision.action == "complete":
                        if self._can_complete_after_agent(
                            state=state,
                            agents=agents,
                            current_index=current_index,
                        ):
                            return self._finalize_run(
                                state=state,
                                status="completed",
                                final_node=agent_name,
                                reason=orch_decision.reason,
                            )
                        state.execution_trace.append(
                            {
                                "event": "orchestrator_complete_deferred",
                                "agent_name": agent_name,
                                "reason": orch_decision.reason,
                                "timestamp": utc_now_iso(),
                            }
                        )
                    if orch_decision.action == "re_plan":
                        planner_index = next(
                            (i for i, workflow_node in enumerate(agents) if workflow_node["name"] == "planner"),
                            None,
                        )
                        if planner_index is not None:
                            self._prepare_replan(state)
                            state.execution_trace.append(
                                {
                                    "event": "orchestrator_replan",
                                    "reason": orch_decision.reason,
                                    "timestamp": utc_now_iso(),
                                }
                            )
                            current_index = planner_index
                            continue
                    if orch_decision.action == "fail":
                        state.set_status("failed", orch_decision.reason)
                        return self._finalize_run(
                            state=state,
                            status="failed",
                            final_node=agent_name,
                            reason=orch_decision.reason,
                        )
                    if orch_decision.next_agent:
                        target_index = next(
                            (
                                i
                                for i, workflow_node in enumerate(agents)
                                if workflow_node["name"] == orch_decision.next_agent
                            ),
                            None,
                        )
                        if target_index is not None:
                            current_index = target_index
                            continue

                next_index = self._resolve_supervisor_guidance(state=state, agents=agents)
                if state.metadata.status == "failed":
                    return self._finalize_run(
                        state=state,
                        status="failed",
                        final_node=agent_name,
                        reason=state.metadata.failure_reason,
                    )
                if next_index is not None:
                    current_index = next_index
                    continue
                current_index += 1
                continue

            if eval_result.action == "retry":
                retry_count = state.convergence.retry_counters.get(agent_name, 0) + 1
                state.convergence.retry_counters[agent_name] = retry_count
                if retry_count >= agent.config.max_retries:
                    reason = f"{agent_name} 超过最大重试次数：{agent.config.max_retries}"
                    state.set_status("failed", reason)
                    if self.orchestrator:
                        self.orchestrator.mark_agent_failed(agent_name, reason)
                    return self._finalize_run(
                        state=state,
                        status="failed",
                        final_node=agent_name,
                        reason=reason,
                    )
                continue

            reason = eval_result.reason or f"{agent_name} 未通过评估"
            state.set_status("failed", reason)
            if self.orchestrator:
                self.orchestrator.mark_agent_failed(agent_name, reason)
            return self._finalize_run(
                state=state,
                status="failed",
                final_node=agent_name,
                reason=reason,
            )

        return self._finalize_run(
            state=state,
            status="completed",
            final_node=agents[-1]["name"] if agents else None,
            reason="工作流末尾节点已完成",
        )

    def _resolve_supervisor_guidance(self, *, state: StateCenter, agents: list[dict]) -> int | None:
        report = state.data_pool.intermediate.get("supervisor_report")
        if not isinstance(report, dict):
            return None
        if report.get("next_action") != "revise":
            return None

        target = report.get("suggested_target")
        action = report.get("suggested_action")
        if not isinstance(target, str) or target in ("", "none", "supervisor"):
            return None

        target_index = next((index for index, node in enumerate(agents) if node["name"] == target), None)
        if target_index is None:
            return None

        revision_key = f"supervisor:{target}:{action}"
        revision_count = state.convergence.retry_counters.get(revision_key, 0) + 1
        state.convergence.retry_counters[revision_key] = revision_count

        max_revision_rounds = int(self.workflow.get("max_supervisor_revisions", 1) or 1)
        if revision_count > max_revision_rounds:
            reason = f"supervisor 对 {target} 的建议 {action} 超过上限：{max_revision_rounds}"
            state.set_status("failed", reason)
            return None

        self._prepare_revision_target(
            state=state,
            target=target,
            target_index=target_index,
            action=action,
        )
        if state.metadata.status == "failed":
            return None

        state.execution_trace.append(
            {
                "event": "supervisor_guidance",
                "suggested_target": target,
                "suggested_action": action,
                "revision_round": revision_count,
                "timestamp": utc_now_iso(),
            }
        )
        return target_index

    def _prepare_revision_target(
        self,
        *,
        state: StateCenter,
        target: str,
        target_index: int,
        action: str,
    ) -> None:
        intermediate = state.data_pool.intermediate

        if self.orchestrator:
            self.orchestrator.reset_from_agent(target)

        if target == "planner" and action == "re_plan":
            checkpoint = state.find_latest_checkpoint_before(target_index)
            if checkpoint is None or not state.rollback_to(checkpoint["checkpoint_id"]):
                state.set_status("failed", "未找到可用于 re_plan 的检查点")
                return
            state.execution_trace.append(
                {
                    "event": "checkpoint_replan",
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "restored_from": checkpoint.get("node_name"),
                    "target": target,
                    "action": action,
                    "timestamp": utc_now_iso(),
                }
            )
            state.data_pool.intermediate.pop("supervisor_report", None)
            return

        if target == "search":
            intermediate.pop("summary", None)
            intermediate.pop("supervisor_report", None)
            state.data_pool.raw_documents = []
            return

        if target == "summarizer":
            intermediate.pop("summary", None)
            intermediate.pop("supervisor_report", None)

    def _append_execution_log(
        self,
        *,
        state: StateCenter,
        agent: str,
        step: int,
        input_view: dict,
        output: dict,
        duration_ms: int,
        status: str,
        eval_result: EvalResult | None = None,
    ) -> None:
        logs_dir = self.project_root / "outputs" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_path(state)
        record = {
            "task_id": state.metadata.task_id,
            "agent": agent,
            "step": step,
            "timestamp": utc_now_iso(),
            "duration_ms": duration_ms,
            "token_usage": {"input": 0, "output": 0},
            "input_hash": self._hash_payload(input_view),
            "output_hash": self._hash_payload(output),
            "status": status,
        }
        if eval_result is not None:
            record["evaluation"] = eval_result.model_dump()
        with log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_terminal_payload(self, *, state: StateCenter, agent) -> dict | None:
        if not agent.config.writes:
            return None

        primary_field = agent.config.writes[0].field
        if primary_field in state.data_pool.intermediate:
            return state.data_pool.intermediate.get(primary_field)
        if hasattr(state.data_pool, primary_field):
            return getattr(state.data_pool, primary_field)
        return None

    def _get_orchestrator_decision(
        self,
        *,
        state: StateCenter,
        workflow_agents: list[str],
        current_agent: str,
    ) -> OrchestrationDecision:
        if self.orchestrator is None:
            return OrchestrationDecision(action="continue", reason="编排器未启用")

        return self.orchestrator.decide_next_step(
            state=self._build_orchestrator_state_view(state),
            execution_trace=state.execution_trace,
            workflow_agents=workflow_agents,
            current_agent=current_agent,
        )

    def _build_orchestrator_state_view(self, state: StateCenter) -> dict:
        view = {
            "query": state.data_pool.query,
            "raw_documents": state.data_pool.raw_documents,
        }
        view.update(state.data_pool.intermediate)
        return view
    def _build_agent(self, *, agent_cls, agent_name: str):
        override = self.llm_overrides.get(agent_name) or self.llm_overrides.get("*")
        if not override:
            return agent_cls()

        provider_name = override.get("provider")
        model_name = override.get("model")
        if provider_name:
            provider = get_provider(provider_name)
            # 如果 model_name 为 None，让 LLMClient 自动推断默认模型
            llm_client = LLMClient(provider=provider, default_model=model_name or None)
            return agent_cls(llm_client=llm_client)
        if model_name:
            llm_client = LLMClient(default_model=model_name)
            return agent_cls(llm_client=llm_client)
        return agent_cls()

    def _handle_live_interrupt(
        self,
        *,
        state: StateCenter,
        agents: list[dict],
        current_index: int,
    ) -> tuple[StateCenter, RunResult] | int | None:
        signal = self.interrupt_controller.check()
        if signal == InterruptSignal.NONE:
            return None

        current_agent = agents[current_index]["name"] if current_index < len(agents) else "scheduler"
        interrupt_state = self._build_orchestrator_state_view(state)
        response = self.interrupt_controller.handle(
            interrupt_state,
            current_agent,
            state.convergence.global_step,
        )
        if not response.accepted:
            return None

        self._apply_interrupt_state(state=state, interrupt_state=interrupt_state)
        state.execution_trace.append(
            {
                "event": "live_interrupt",
                "signal": response.signal.value,
                "agent_name": current_agent,
                "message": response.message,
                "applied_changes": response.applied_changes,
                "timestamp": utc_now_iso(),
            }
        )

        if response.signal == InterruptSignal.ABORT:
            return self._finalize_run(
                state=state,
                status="failed",
                final_node=current_agent,
                reason="运行被人工中止",
            )
        if response.signal == InterruptSignal.PAUSE:
            return self._finalize_run(
                state=state,
                status="needs_human_review",
                final_node=current_agent,
                reason="运行被人工暂停，等待后续处理",
            )
        if response.signal == InterruptSignal.SKIP:
            return current_index + 1
        if interrupt_state.get("_force_complete"):
            return self._finalize_run(
                state=state,
                status="completed",
                final_node=current_agent,
                reason="运行被人工强制标记为完成",
            )
        target = interrupt_state.get("_change_target")
        if isinstance(target, str) and target:
            target_index = next(
                (idx for idx, node in enumerate(agents) if node["name"] == target),
                None,
            )
            if target_index is not None:
                return target_index
        return None

    def _apply_interrupt_state(self, *, state: StateCenter, interrupt_state: dict) -> None:
        if "query" in interrupt_state and interrupt_state["query"] != state.data_pool.query:
            state.data_pool.query = interrupt_state["query"]

        for key, value in interrupt_state.items():
            if key in {"query", "raw_documents", "_force_complete", "_change_target"}:
                continue
            if key not in state.data_pool.intermediate and key not in {"plan", "summary", "supervisor_report", "human_review_gate"}:
                continue
            state.data_pool.intermediate[key] = value

    def _prepare_replan(self, state: StateCenter) -> None:
        intermediate = state.data_pool.intermediate
        intermediate.pop("plan", None)
        intermediate.pop("summary", None)
        intermediate.pop("supervisor_report", None)
        state.data_pool.raw_documents = []
        if self.orchestrator:
            self.orchestrator.reset_from_agent("planner")

    def _can_complete_after_agent(
        self,
        *,
        state: StateCenter,
        agents: list[dict],
        current_index: int,
    ) -> bool:
        if current_index != len(agents) - 1:
            return False

        required_fields_by_agent = {
            "planner": "plan",
            "search": "raw_documents",
            "summarizer": "summary",
            "supervisor": "supervisor_report",
            "human_review": "human_review_gate",
        }
        for node in agents[: current_index + 1]:
            required_field = required_fields_by_agent.get(node["name"])
            if required_field and not self._state_has_meaningful_value(state=state, field=required_field):
                return False
        return True

    def _state_has_meaningful_value(self, *, state: StateCenter, field: str) -> bool:
        if field == "raw_documents":
            value = state.data_pool.raw_documents
        else:
            value = state.data_pool.intermediate.get(field)

        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, dict)):
            return bool(value)
        return value is not None

    def _hash_payload(self, payload: dict) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _create_runtime_checkpoint(
        self,
        *,
        state: StateCenter,
        created_by: str,
        reason: str,
        node_name: str,
        node_index: int,
    ) -> None:
        state.create_checkpoint(
            created_by=created_by,
            reason=reason,
            node_name=node_name,
            node_index=node_index,
            project_root=self.project_root,
        )

    def _finalize_run(
        self,
        *,
        state: StateCenter,
        status: str,
        final_node: str | None,
        reason: str = "",
    ) -> tuple[StateCenter, RunResult]:
        state.set_status(status, reason)

        failure_record: FailureRecord | None = None
        if status in ("failed", "timed_out", "guardrail_blocked"):
            failure_record = self._classify_failure(state=state, status=status, reason=reason, final_node=final_node)
            state.execution_trace.append(
                {
                    "event": "failure_classified",
                    "category": failure_record.category.value,
                    "severity": failure_record.severity.value,
                    "agent_name": failure_record.agent_name,
                    "reason": failure_record.reason,
                    "timestamp": utc_now_iso(),
                }
            )

        memory_bundle, memory_path = self.memory_manager.capture(state=state, final_node=final_node)
        state.write("memory_bundle", memory_bundle, "memory_manager")
        report_path = self.report_writer.write(
            state=state,
            final_node=final_node,
            memory_path=memory_path,
            failure_record=failure_record,
        )
        state.save_to(self._state_path(state))
        return state, RunResult(
            task_id=state.metadata.task_id,
            status=status,
            final_node=final_node,
            reason=reason,
            failure_reason=state.metadata.failure_reason,
            completion_reason=state.metadata.completion_reason,
            state_version=state.version,
            checkpoint_dir=str(self._checkpoint_dir(state)),
            convergence_report_path=str(report_path),
            memory_path=str(memory_path),
        )

    def _classify_failure(
        self,
        *,
        state: StateCenter,
        status: str,
        reason: str,
        final_node: str | None,
    ) -> FailureRecord:
        last_guardrail = None
        last_failed_eval = None

        for event in reversed(state.execution_trace):
            if event.get("event") == "guardrail_violation" and last_guardrail is None:
                last_guardrail = event
            if event.get("event") == "evaluation" and event.get("passed") is False and last_failed_eval is None:
                last_failed_eval = event

        if last_guardrail and "failure_category" in last_guardrail:
            category = FailureCategory(last_guardrail["failure_category"])
            return create_failure_record(
                category=category,
                agent_name=final_node,
                reason=reason,
            )

        eval_action = last_failed_eval.get("action") if last_failed_eval else None
        event_type = last_guardrail.get("event") if last_guardrail else None

        category = infer_failure_category(
            status=status,
            reason=reason,
            event_type=event_type,
            eval_action=eval_action,
        )
        return create_failure_record(
            category=category,
            agent_name=final_node,
            reason=reason,
        )

    def _state_path(self, state: StateCenter) -> Path:
        return self.project_root / "outputs" / "states" / f"{state.metadata.task_id}.json"

    def _log_path(self, state: StateCenter) -> Path:
        return self.project_root / "outputs" / "logs" / f"{state.metadata.task_id}.jsonl"

    def _checkpoint_dir(self, state: StateCenter) -> Path:
        return self.project_root / "outputs" / "checkpoints" / state.metadata.task_id
