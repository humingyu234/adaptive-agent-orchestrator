"""收敛报告生成器

负责从 StateCenter 和运行数据生成结构化的 ConvergenceReport。
"""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .failure_taxonomy import FailureRecord
from .registry import get_agent
from .state_center import StateCenter


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConvergenceReportWriter:
    """收敛报告生成器"""

    def __init__(self, project_root: Path, workflow: dict):
        self.project_root = project_root
        self.workflow = workflow

    def write(
        self,
        *,
        state: StateCenter,
        final_node: str | None,
        memory_path: Path,
        failure_record: FailureRecord | None = None,
    ) -> Path:
        """生成并写入收敛报告"""
        report_dir = self.project_root / "outputs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{state.metadata.task_id}.json"

        log_records = self._load_log_records(state)
        report = self._build_report(
            state=state,
            final_node=final_node,
            memory_path=memory_path,
            failure_record=failure_record,
            log_records=log_records,
        )

        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path

    def _build_report(
        self,
        *,
        state: StateCenter,
        final_node: str | None,
        memory_path: Path,
        failure_record: FailureRecord | None,
        log_records: list[dict],
    ) -> dict[str, Any]:
        """构建报告结构"""
        event_counter = self._count_events(state.execution_trace)
        evaluation_events = self._filter_events(state.execution_trace, "evaluation")
        failed_evaluations = self._filter_failed_evaluations(evaluation_events)
        supervisor_guidance_events = self._filter_events(state.execution_trace, "supervisor_guidance")
        checkpoint_replans = self._filter_events(state.execution_trace, "checkpoint_replan")
        rollback_events = self._filter_events(state.execution_trace, "rollback")
        guardrail_violations = self._filter_events(state.execution_trace, "guardrail_violation")
        checkpoint_events = self._filter_events(state.execution_trace, "checkpoint")
        write_events = self._filter_events(state.execution_trace, "write")

        duration_by_agent, evaluation_action_counts, slowest_step, total_duration_ms, agents_seen_in_logs = (
            self._analyze_log_records(log_records)
        )

        unique_agents_seen = list(dict.fromkeys(agents_seen_in_logs))
        declared_tools_by_agent = self._get_declared_tools_by_agent(unique_agents_seen)
        trust_levels_by_agent = self._get_trust_levels_by_agent(unique_agents_seen)
        tool_risk_levels = self._get_tool_risk_levels(declared_tools_by_agent)
        tool_names_seen_in_outputs = self._get_tool_names_seen(state)

        human_review_gate = state.data_pool.intermediate.get("human_review_gate", {})
        supervisor_report = state.data_pool.intermediate.get("supervisor_report", {})
        memory_bundle = state.data_pool.intermediate.get("memory_bundle", {})
        retrieved_memories = state.data_pool.intermediate.get("retrieved_memories", [])
        plan = state.data_pool.intermediate.get("plan", {})
        summary = state.data_pool.intermediate.get("summary", {})

        return {
            "task_id": state.metadata.task_id,
            "workflow_name": self.workflow.get("name"),
            "query": state.data_pool.query,
            "status": state.metadata.status,
            "failure_reason": state.metadata.failure_reason,
            "completion_reason": state.metadata.completion_reason,
            "final_node": final_node,
            "state_version": state.version,
            "timeline": self._build_timeline(state, total_duration_ms, slowest_step),
            "flow_summary": self._build_flow_summary(
                agents_seen_in_logs,
                unique_agents_seen,
                plan,
                summary,
                declared_tools_by_agent,
                trust_levels_by_agent,
                tool_risk_levels,
                tool_names_seen_in_outputs,
            ),
            "control_summary": self._build_control_summary(
                state,
                supervisor_guidance_events,
                checkpoint_replans,
                rollback_events,
                guardrail_violations,
                human_review_gate,
                supervisor_report,
            ),
            "quality_summary": self._build_quality_summary(
                evaluation_events,
                failed_evaluations,
                evaluation_action_counts,
                guardrail_violations,
            ),
            "artifact_summary": self._build_artifact_summary(state, memory_path, report_path=None),
            "execution_audit": self._build_execution_audit(
                log_records,
                checkpoint_events,
                write_events,
                event_counter,
                duration_by_agent,
                supervisor_guidance_events,
                checkpoint_replans,
                guardrail_violations,
            ),
            "memory_summary": self._build_memory_summary(memory_bundle, retrieved_memories),
            "failure_summary": self._build_failure_summary(failure_record),
        }

    def _load_log_records(self, state: StateCenter) -> list[dict]:
        log_path = self.project_root / "outputs" / "logs" / f"{state.metadata.task_id}.jsonl"
        if not log_path.exists():
            return []
        records = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
        return records

    def _count_events(self, execution_trace: list) -> Counter:
        return Counter(
            event.get("event")
            for event in execution_trace
            if isinstance(event, dict) and isinstance(event.get("event"), str)
        )

    def _filter_events(self, execution_trace: list, event_type: str) -> list[dict]:
        return [event for event in execution_trace if event.get("event") == event_type]

    def _filter_failed_evaluations(self, evaluation_events: list[dict]) -> list[dict]:
        return [
            event
            for event in evaluation_events
            if event.get("passed") is False or event.get("action") in {"retry", "fail"}
        ]

    def _analyze_log_records(self, log_records: list[dict]) -> tuple[dict, Counter, dict | None, int, list]:
        duration_by_agent: dict[str, int] = {}
        evaluation_action_counts: Counter[str] = Counter()
        slowest_step: dict | None = None
        total_duration_ms = 0
        agents_seen_in_logs: list[str] = []

        for record in log_records:
            duration_ms = int(record.get("duration_ms", 0) or 0)
            total_duration_ms += duration_ms
            agent_name = str(record.get("agent", "unknown"))
            duration_by_agent[agent_name] = duration_by_agent.get(agent_name, 0) + duration_ms
            agents_seen_in_logs.append(agent_name)
            evaluation = record.get("evaluation")
            if isinstance(evaluation, dict):
                action = str(evaluation.get("action", "continue"))
                evaluation_action_counts[action] += 1
            current_step = {
                "step": record.get("step"),
                "agent": agent_name,
                "duration_ms": duration_ms,
            }
            if slowest_step is None or duration_ms > slowest_step["duration_ms"]:
                slowest_step = current_step

        return duration_by_agent, evaluation_action_counts, slowest_step, total_duration_ms, agents_seen_in_logs

    def _get_declared_tools_by_agent(self, agent_names: list[str]) -> dict[str, list[str]]:
        return {
            agent_name: get_agent(agent_name)().config.tools
            for agent_name in agent_names
        }

    def _get_trust_levels_by_agent(self, agent_names: list[str]) -> dict[str, str]:
        return {
            agent_name: get_agent(agent_name)().config.trust_level
            for agent_name in agent_names
        }

    def _get_tool_risk_levels(self, declared_tools_by_agent: dict[str, list[str]]) -> dict[str, str]:
        return {
            name: get_agent(agent_name)().tool_registry.get(name).risk_level
            for agent_name, names in declared_tools_by_agent.items()
            for name in names
        }

    def _get_tool_names_seen(self, state: StateCenter) -> list[str]:
        return sorted(
            {
                str(document.get("tool_name"))
                for document in state.data_pool.raw_documents
                if isinstance(document, dict) and document.get("tool_name")
            }
        )

    def _build_timeline(self, state: StateCenter, total_duration_ms: int, slowest_step: dict | None) -> dict:
        return {
            "created_at": state.metadata.created_at,
            "report_generated_at": utc_now_iso(),
            "steps_executed": state.convergence.global_step,
            "max_steps": state.convergence.max_steps,
            "total_duration_ms": total_duration_ms,
            "slowest_step": slowest_step,
        }

    def _build_flow_summary(
        self,
        agents_seen: list[str],
        unique_agents: list[str],
        plan: dict,
        summary: dict,
        declared_tools: dict[str, list[str]],
        trust_levels: dict[str, str],
        tool_risk_levels: dict[str, str],
        tool_names_seen: list[str],
    ) -> dict:
        return {
            "agents_seen": agents_seen,
            "unique_agents_seen": unique_agents,
            "plan_type": plan.get("plan_type") if isinstance(plan, dict) else None,
            "memory_hints_used": plan.get("memory_hints_used") if isinstance(plan, dict) else None,
            "summary_conclusion_preview": (
                str(summary.get("conclusion", ""))[:200] if isinstance(summary, dict) else ""
            ),
            "declared_tools_by_agent": declared_tools,
            "trust_levels_by_agent": trust_levels,
            "tool_risk_levels": tool_risk_levels,
            "tool_names_seen_in_outputs": tool_names_seen,
        }

    def _build_control_summary(
        self,
        state: StateCenter,
        supervisor_guidance_events: list,
        checkpoint_replans: list,
        rollback_events: list,
        guardrail_violations: list,
        human_review_gate: dict,
        supervisor_report: dict,
    ) -> dict:
        return {
            "retry_counters": state.convergence.retry_counters,
            "supervisor_guidance_rounds": len(supervisor_guidance_events),
            "checkpoint_replans": len(checkpoint_replans),
            "rollback_events": len(rollback_events),
            "guardrail_violations": len(guardrail_violations),
            "human_review_required": bool(
                isinstance(human_review_gate, dict) and human_review_gate.get("approval_required")
            ),
            "human_review_status": human_review_gate.get("status")
            if isinstance(human_review_gate, dict)
            else None,
            "latest_supervisor_action": supervisor_report.get("suggested_action")
            if isinstance(supervisor_report, dict)
            else None,
            "latest_supervisor_target": supervisor_report.get("suggested_target")
            if isinstance(supervisor_report, dict)
            else None,
        }

    def _build_quality_summary(
        self,
        evaluation_events: list,
        failed_evaluations: list,
        evaluation_action_counts: Counter,
        guardrail_violations: list,
    ) -> dict:
        return {
            "evaluation_events": len(evaluation_events),
            "failed_evaluations": len(failed_evaluations),
            "evaluation_action_counts": dict(evaluation_action_counts),
            "failed_evaluation_reasons": [
                {
                    "agent_name": event.get("agent_name"),
                    "action": event.get("action"),
                    "reason": event.get("reason"),
                }
                for event in failed_evaluations[-5:]
            ],
            "guardrail_reasons": [
                {
                    "agent_name": event.get("agent_name"),
                    "guardrail_name": event.get("guardrail_name"),
                    "stage": event.get("stage"),
                    "reason": event.get("reason"),
                }
                for event in guardrail_violations[-5:]
            ],
        }

    def _build_artifact_summary(
        self,
        state: StateCenter,
        memory_path: Path,
        report_path: str | None = None,
    ) -> dict:
        return {
            "log_path": str(self.project_root / "outputs" / "logs" / f"{state.metadata.task_id}.jsonl"),
            "state_path": str(self.project_root / "outputs" / "states" / f"{state.metadata.task_id}.json"),
            "checkpoint_dir": str(self.project_root / "outputs" / "checkpoints" / state.metadata.task_id),
            "report_path": str(self.project_root / "outputs" / "reports" / f"{state.metadata.task_id}.json"),
            "memory_path": str(memory_path),
            "latest_checkpoint_id": state.checkpoints[-1]["checkpoint_id"] if state.checkpoints else None,
        }

    def _build_execution_audit(
        self,
        log_records: list,
        checkpoint_events: list,
        write_events: list,
        event_counter: Counter,
        duration_by_agent: dict,
        supervisor_guidance_events: list,
        checkpoint_replans: list,
        guardrail_violations: list,
    ) -> dict:
        return {
            "log_records": len(log_records),
            "checkpoint_events": len(checkpoint_events),
            "write_events": len(write_events),
            "event_counts": dict(event_counter),
            "duration_by_agent_ms": duration_by_agent,
            "supervisor_guidance_history": [
                {
                    "suggested_target": event.get("suggested_target"),
                    "suggested_action": event.get("suggested_action"),
                    "revision_round": event.get("revision_round"),
                }
                for event in supervisor_guidance_events
            ],
            "checkpoint_replan_history": [
                {
                    "checkpoint_id": event.get("checkpoint_id"),
                    "restored_from": event.get("restored_from"),
                    "target": event.get("target"),
                    "action": event.get("action"),
                }
                for event in checkpoint_replans
            ],
            "guardrail_history": [
                {
                    "agent_name": event.get("agent_name"),
                    "guardrail_name": event.get("guardrail_name"),
                    "stage": event.get("stage"),
                }
                for event in guardrail_violations
            ],
        }

    def _build_memory_summary(self, memory_bundle: dict, retrieved_memories: list) -> dict:
        return {
            "memory_version": memory_bundle.get("memory_version") if isinstance(memory_bundle, dict) else None,
            "short_term_status": memory_bundle.get("short_term", {}).get("status")
            if isinstance(memory_bundle, dict)
            else None,
            "failure_memory_status": memory_bundle.get("failure_memory", {}).get("status")
            if isinstance(memory_bundle, dict)
            else None,
            "retrieved_memory_count": len(retrieved_memories) if isinstance(retrieved_memories, list) else 0,
        }

    def _build_failure_summary(self, failure_record: FailureRecord | None) -> dict:
        if failure_record:
            return {
                "has_failure": True,
                "category": failure_record.category.value,
                "severity": failure_record.severity.value,
                "agent_name": failure_record.agent_name,
                "reason": failure_record.reason,
            }
        return {
            "has_failure": False,
            "category": None,
            "severity": None,
            "agent_name": None,
            "reason": None,
        }
