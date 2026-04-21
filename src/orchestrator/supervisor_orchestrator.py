"""Supervisor Orchestrator

一个更高层的总控编排器。

当前版本的定位不是取代 workflow，而是在 workflow 之上提供：
- 任务账本
- 基础 stalled / no progress 检测
- 对 supervisor revise 建议的统一路由
- 对 runtime 完成时机的更谨慎判断
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskItem:
    id: str
    description: str
    assigned_agent: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    dependencies: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


@dataclass
class TaskLedger:
    query: str
    tasks: list[TaskItem] = field(default_factory=list)
    current_task_id: str | None = None
    iteration_count: int = 0
    max_iterations: int = 10

    def add_task(self, task: TaskItem) -> None:
        self.tasks.append(task)

    def get_task(self, task_id: str) -> TaskItem | None:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def update_task(self, task_id: str, **kwargs: Any) -> None:
        task = self.get_task(task_id)
        if task is None:
            return
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc).isoformat()

    def ensure_workflow_tasks(self, workflow_agents: list[str]) -> None:
        if self.tasks:
            return
        for priority, agent_name in enumerate(workflow_agents):
            self.add_task(
                TaskItem(
                    id=agent_name,
                    description=f"workflow step: {agent_name}",
                    assigned_agent=agent_name,
                    priority=priority,
                )
            )

    def reset_from_agent(self, agent_name: str) -> None:
        seen_target = False
        for task in self.tasks:
            if task.id == agent_name:
                seen_target = True
            if seen_target:
                task.status = TaskStatus.PENDING
                task.result = None
                task.error = None
                task.updated_at = datetime.now(timezone.utc).isoformat()

    def get_pending_tasks(self) -> list[TaskItem]:
        return [task for task in self.tasks if task.status == TaskStatus.PENDING]

    def get_blocked_tasks(self) -> list[TaskItem]:
        return [task for task in self.tasks if task.status == TaskStatus.BLOCKED]

    def get_completed_tasks(self) -> list[TaskItem]:
        return [task for task in self.tasks if task.status == TaskStatus.COMPLETED]

    def progress_summary(self) -> dict[str, Any]:
        total = len(self.tasks)
        completed = len(self.get_completed_tasks())
        pending = len(self.get_pending_tasks())
        blocked = len(self.get_blocked_tasks())
        return {
            "total": total,
            "completed": completed,
            "pending": pending,
            "blocked": blocked,
            "progress_rate": completed / total if total > 0 else 0.0,
            "iteration_count": self.iteration_count,
            "is_stalled": pending > 0 and pending == blocked,
        }


@dataclass
class OrchestrationDecision:
    action: str  # continue / re_plan / complete / fail
    next_agent: str | None = None
    reason: str = ""
    task_updates: list[dict[str, Any]] = field(default_factory=list)
    context_updates: dict[str, Any] = field(default_factory=dict)


class SupervisorOrchestrator:
    def __init__(self, max_iterations: int = 10, stall_threshold: int = 3) -> None:
        self.max_iterations = max_iterations
        self.stall_threshold = stall_threshold
        self._ledger: TaskLedger | None = None
        self._stall_count = 0
        self._last_progress_rate = 0.0

    def initialize(self, query: str, workflow_agents: list[str]) -> TaskLedger:
        self._ledger = TaskLedger(query=query, max_iterations=self.max_iterations)
        self._ledger.ensure_workflow_tasks(workflow_agents)
        self._stall_count = 0
        self._last_progress_rate = 0.0
        return self._ledger

    @property
    def ledger(self) -> TaskLedger | None:
        return self._ledger

    def mark_agent_completed(self, agent_name: str, result: dict[str, Any] | None = None) -> None:
        if self._ledger is None:
            return
        self._ledger.update_task(
            agent_name,
            status=TaskStatus.COMPLETED,
            result=result,
            error=None,
        )

    def mark_agent_failed(self, agent_name: str, error: str, *, blocked: bool = False) -> None:
        if self._ledger is None:
            return
        self._ledger.update_task(
            agent_name,
            status=TaskStatus.BLOCKED if blocked else TaskStatus.FAILED,
            error=error,
        )

    def reset_from_agent(self, agent_name: str) -> None:
        if self._ledger is None:
            return
        self._ledger.reset_from_agent(agent_name)
        self._stall_count = 0
        self._last_progress_rate = 0.0

    def decide_next_step(
        self,
        *,
        state: dict[str, Any],
        execution_trace: list[dict[str, Any]],
        workflow_agents: list[str],
        current_agent: str,
    ) -> OrchestrationDecision:
        del execution_trace
        if self._ledger is None:
            return OrchestrationDecision(action="fail", reason="任务账本未初始化")

        self._ledger.ensure_workflow_tasks(workflow_agents)
        self._ledger.iteration_count += 1
        if self._ledger.iteration_count > self._ledger.max_iterations:
            return OrchestrationDecision(
                action="fail",
                reason=f"超过最大迭代次数：{self._ledger.max_iterations}",
            )

        progress = self._ledger.progress_summary()
        if self._detect_stall(progress):
            return OrchestrationDecision(
                action="re_plan",
                reason="任务长时间无进展，需要重新规划",
                context_updates={"stall_detected": True, "stall_count": self._stall_count},
            )

        if current_agent == "supervisor":
            supervisor_report = state.get("supervisor_report", {})
            next_action = supervisor_report.get("next_action", "accept")
            suggested_target = supervisor_report.get("suggested_target", "none")
            if next_action == "revise" and suggested_target not in ("", "none", None):
                self.reset_from_agent(str(suggested_target))
                return OrchestrationDecision(
                    action="continue",
                    next_agent=str(suggested_target),
                    reason=f"supervisor 建议回到 {suggested_target}",
                )

        next_agent = self._next_workflow_agent(current_agent, workflow_agents)
        if next_agent is None:
            return OrchestrationDecision(
                action="complete",
                reason="工作流末尾节点已完成",
            )

        if current_agent == "search":
            raw_documents = state.get("raw_documents", [])
            if not raw_documents:
                return OrchestrationDecision(
                    action="continue",
                    next_agent="search",
                    reason="搜索结果为空，继续补充搜索",
                )

        return OrchestrationDecision(
            action="continue",
            next_agent=next_agent,
            reason=f"{current_agent} 完成，继续到 {next_agent}",
        )

    def handle_failure(
        self,
        *,
        agent_name: str,
        error: str,
        workflow_agents: list[str],
    ) -> OrchestrationDecision:
        if self._ledger is None:
            return OrchestrationDecision(action="fail", reason=f"{agent_name} 失败: {error}")

        self._ledger.iteration_count += 1
        self.mark_agent_failed(agent_name, error)

        if agent_name == "planner":
            self.reset_from_agent("planner")
            return OrchestrationDecision(action="re_plan", reason=f"planner 失败: {error}")

        next_agent = self._next_workflow_agent(agent_name, workflow_agents)
        if next_agent is not None and agent_name == "search":
            return OrchestrationDecision(
                action="continue",
                next_agent=next_agent,
                reason=f"search 失败，尝试继续到 {next_agent}",
            )

        return OrchestrationDecision(action="fail", reason=f"{agent_name} 失败: {error}")

    def get_status_report(self) -> dict[str, Any]:
        if self._ledger is None:
            return {"status": "not_initialized"}

        progress = self._ledger.progress_summary()
        return {
            "query": self._ledger.query,
            "iteration": self._ledger.iteration_count,
            "max_iterations": self._ledger.max_iterations,
            "progress": progress,
            "tasks": [
                {
                    "id": task.id,
                    "description": task.description[:50],
                    "status": task.status.value,
                    "assigned_agent": task.assigned_agent,
                }
                for task in self._ledger.tasks
            ],
        }

    def _detect_stall(self, progress: dict[str, Any]) -> bool:
        if progress["total"] == 0:
            return False
        if progress["progress_rate"] == self._last_progress_rate:
            self._stall_count += 1
        else:
            self._stall_count = 0
        self._last_progress_rate = progress["progress_rate"]
        return self._stall_count >= self.stall_threshold

    def _next_workflow_agent(self, current_agent: str, workflow_agents: list[str]) -> str | None:
        if current_agent not in workflow_agents:
            return None
        current_index = workflow_agents.index(current_agent)
        if current_index >= len(workflow_agents) - 1:
            return None
        return workflow_agents[current_index + 1]
