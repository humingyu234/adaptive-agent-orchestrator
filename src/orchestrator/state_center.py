from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateMetadata:
    """运行元数据"""

    def __init__(
        self,
        *,
        task_id: str,
        original_query: str,
        created_at: str,
        status: str = "running",
        failure_reason: str = "",
        completion_reason: str = "",
    ):
        self.task_id = task_id
        self.original_query = original_query
        self.created_at = created_at
        self.status = status
        self.failure_reason = failure_reason
        self.completion_reason = completion_reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "original_query": self.original_query,
            "created_at": self.created_at,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "completion_reason": self.completion_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateMetadata":
        return cls(
            task_id=data["task_id"],
            original_query=data["original_query"],
            created_at=data["created_at"],
            status=data.get("status", "running"),
            failure_reason=data.get("failure_reason", ""),
            completion_reason=data.get("completion_reason", ""),
        )


class ConvergenceState:
    """收敛状态"""

    def __init__(self, *, global_step: int = 0, max_steps: int = 10):
        self.global_step = global_step
        self.retry_counters: dict[str, int] = {}
        self.max_steps = max_steps

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_step": self.global_step,
            "retry_counters": self.retry_counters,
            "max_steps": self.max_steps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConvergenceState":
        state = cls(
            global_step=data.get("global_step", 0),
            max_steps=data.get("max_steps", 10),
        )
        state.retry_counters = data.get("retry_counters", {})
        return state


class DataPool:
    """数据池，存储 agent 输入输出"""

    def __init__(self, query: str):
        self.query = query
        self.raw_documents: list[dict[str, Any]] = []
        self.structured_facts: list[dict[str, Any]] = []
        self.intermediate: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "raw_documents": self.raw_documents,
            "structured_facts": self.structured_facts,
            "intermediate": self.intermediate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataPool":
        pool = cls(query=data.get("query", ""))
        pool.raw_documents = data.get("raw_documents", [])
        pool.structured_facts = data.get("structured_facts", [])
        pool.intermediate = data.get("intermediate", {})
        return pool


class StateCenter:
    """状态中心，管理整个运行周期的状态"""

    def __init__(
        self,
        query: str,
        max_steps: int = 10,
        *,
        task_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self.metadata = StateMetadata(
            task_id=task_id or str(uuid4()),
            original_query=query,
            created_at=created_at or utc_now_iso(),
        )
        self.execution_trace: list[dict[str, Any]] = []
        self.data_pool = DataPool(query=query)
        self.convergence = ConvergenceState(max_steps=max_steps)
        self.checkpoints: list[dict[str, Any]] = []
        self.version = 0

    def prepare_view(self, reads: list[str]) -> dict[str, Any]:
        """根据 agent 的 reads 配置准备上下文视图"""
        view: dict[str, Any] = {}
        for key in reads:
            if key == "query":
                view[key] = self.data_pool.query
                continue
            if key == "execution_trace":
                view[key] = self._trim_execution_trace(self.execution_trace)
                continue
            if key == "retry_counters":
                view[key] = deepcopy(self.convergence.retry_counters)
                continue
            if key == "global_step":
                view[key] = self.convergence.global_step
                continue
            if key == "status":
                view[key] = self.metadata.status
                continue
            if key == "failure_reason":
                view[key] = self.metadata.failure_reason
                continue
            if key == "completion_reason":
                view[key] = self.metadata.completion_reason
                continue
            if key in self.data_pool.intermediate:
                view[key] = self._trim_value(self.data_pool.intermediate[key])
                continue
            if hasattr(self.data_pool, key):
                view[key] = self._trim_value(getattr(self.data_pool, key))
        return view

    def write(self, field: str, value: Any, agent_name: str) -> None:
        """写入数据到 data_pool"""
        if field in ("raw_documents", "structured_facts"):
            setattr(self.data_pool, field, value)
        else:
            self.data_pool.intermediate[field] = value
        self.version += 1
        self.execution_trace.append(
            {
                "event": "write",
                "agent_name": agent_name,
                "field": field,
                "timestamp": utc_now_iso(),
                "version": self.version,
            }
        )

    def create_checkpoint(
        self,
        created_by: str,
        reason: str,
        *,
        node_name: str | None = None,
        node_index: int | None = None,
        project_root: str | Path | None = None,
    ) -> str:
        """创建检查点"""
        checkpoint_id = str(uuid4())
        snapshot = {
            "raw_documents": deepcopy(self.data_pool.raw_documents),
            "structured_facts": deepcopy(self.data_pool.structured_facts),
            "intermediate": deepcopy(self.data_pool.intermediate),
            "convergence": self.convergence.to_dict(),
            "version": self.version,
        }
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "step_id": self.convergence.global_step,
            "snapshot": snapshot,
            "created_by": created_by,
            "reason": reason,
            "node_name": node_name,
            "node_index": node_index,
            "timestamp": utc_now_iso(),
        }
        self.checkpoints.append(checkpoint)
        self.execution_trace.append(
            {
                "event": "checkpoint",
                "checkpoint_id": checkpoint_id,
                "created_by": created_by,
                "reason": reason,
                "node_name": node_name,
                "node_index": node_index,
                "timestamp": checkpoint["timestamp"],
                "version": self.version,
            }
        )
        if project_root is not None:
            self._persist_checkpoint(checkpoint=checkpoint, project_root=project_root)
        return checkpoint_id

    def rollback_to(self, checkpoint_id: str) -> bool:
        """回滚到指定检查点"""
        for checkpoint in reversed(self.checkpoints):
            if checkpoint["checkpoint_id"] != checkpoint_id:
                continue
            snapshot = checkpoint["snapshot"]
            current_retry_counters = deepcopy(self.convergence.retry_counters)
            self.data_pool.raw_documents = deepcopy(snapshot["raw_documents"])
            self.data_pool.structured_facts = deepcopy(snapshot["structured_facts"])
            self.data_pool.intermediate = deepcopy(snapshot["intermediate"])
            previous_convergence = ConvergenceState.from_dict(snapshot["convergence"])
            previous_convergence.global_step = self.convergence.global_step
            previous_convergence.retry_counters = current_retry_counters
            self.convergence = previous_convergence
            self.version = snapshot["version"]
            self.execution_trace.append(
                {
                    "event": "rollback",
                    "checkpoint_id": checkpoint_id,
                    "timestamp": utc_now_iso(),
                    "version": self.version,
                }
            )
            return True
        return False

    def find_latest_checkpoint_before(self, node_index: int) -> dict[str, Any] | None:
        """找到指定节点之前的最近检查点"""
        for checkpoint in reversed(self.checkpoints):
            checkpoint_index = checkpoint.get("node_index")
            if checkpoint_index is None or checkpoint_index >= node_index:
                continue
            return checkpoint
        return None

    def save_to(self, path: str | Path) -> Path:
        """持久化状态到文件"""
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": self.metadata.to_dict(),
            "execution_trace": deepcopy(self.execution_trace),
            "data_pool": self.data_pool.to_dict(),
            "convergence": self.convergence.to_dict(),
            "checkpoints": deepcopy(self.checkpoints),
            "version": self.version,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    @classmethod
    def load_from(cls, path: str | Path) -> "StateCenter":
        """从文件加载状态"""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        state = cls(
            query=payload["data_pool"]["query"],
            max_steps=payload["convergence"]["max_steps"],
            task_id=payload["metadata"]["task_id"],
            created_at=payload["metadata"]["created_at"],
        )
        state.metadata = StateMetadata.from_dict(payload["metadata"])
        state.execution_trace = payload["execution_trace"]
        state.data_pool = DataPool.from_dict(payload["data_pool"])
        state.convergence = ConvergenceState.from_dict(payload["convergence"])
        state.checkpoints = payload["checkpoints"]
        state.version = payload["version"]
        return state

    def set_status(self, status: str, reason: str = "") -> None:
        """????????????????????"""
        self.metadata.status = status
        if status in {"failed", "timed_out", "guardrail_blocked"}:
            self.metadata.failure_reason = reason
            self.metadata.completion_reason = ""
        elif status in {"completed", "needs_human_review"}:
            self.metadata.failure_reason = ""
            self.metadata.completion_reason = reason
        else:
            self.metadata.failure_reason = ""
            self.metadata.completion_reason = ""

    def _trim_value(self, value: Any) -> Any:
        """截断大值用于视图"""
        if isinstance(value, list) and len(value) > 10:
            return value[:5]
        return value

    def _trim_execution_trace(self, trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """截断执行轨迹用于视图"""
        if len(trace) <= 8:
            return deepcopy(trace)
        return deepcopy(trace[-8:])

    def _persist_checkpoint(self, *, checkpoint: dict[str, Any], project_root: str | Path) -> None:
        """持久化检查点到文件"""
        checkpoint_dir = Path(project_root) / "outputs" / "checkpoints" / self.metadata.task_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / f"{checkpoint['step_id']:03d}_{checkpoint['checkpoint_id']}.json"
        checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
