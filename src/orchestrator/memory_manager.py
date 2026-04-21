import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .state_center import StateCenter


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryManager:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)

    def capture(
        self,
        *,
        state: StateCenter,
        final_node: str | None,
    ) -> tuple[dict, Path]:
        intermediate = state.data_pool.intermediate
        plan = intermediate.get("plan", {})
        summary = intermediate.get("summary", {})
        supervisor_report = intermediate.get("supervisor_report", {})
        human_review_gate = intermediate.get("human_review_gate", {})

        short_term = {
            "query": state.data_pool.query,
            "status": state.metadata.status,
            "final_node": final_node,
            "plan_sub_questions": plan.get("sub_questions", []) if isinstance(plan, dict) else [],
            "summary_conclusion": summary.get("conclusion", "") if isinstance(summary, dict) else "",
        }
        long_term = {
            "task_id": state.metadata.task_id,
            "created_at": state.metadata.created_at,
            "captured_at": utc_now_iso(),
            "checkpoints_created": len(state.checkpoints),
            "steps_executed": state.convergence.global_step,
        }
        entity = {
            "document_titles": [
                document.get("title", "")
                for document in state.data_pool.raw_documents
                if isinstance(document, dict) and document.get("title")
            ][:10],
        }
        procedural = {
            "retry_counters": state.convergence.retry_counters,
            "supervisor_action": supervisor_report.get("suggested_action")
            if isinstance(supervisor_report, dict)
            else None,
            "supervisor_target": supervisor_report.get("suggested_target")
            if isinstance(supervisor_report, dict)
            else None,
            "human_review_status": human_review_gate.get("status")
            if isinstance(human_review_gate, dict)
            else None,
        }
        failure_events = [
            {
                "agent_name": event.get("agent_name"),
                "reason": event.get("reason"),
                "action": event.get("action"),
            }
            for event in state.execution_trace
            if isinstance(event, dict)
            and event.get("event") == "evaluation"
            and (event.get("passed") is False or event.get("action") in {"retry", "fail"})
        ]
        failure_memory = {
            "status": state.metadata.status,
            "failure_reason": state.metadata.failure_reason,
            "recent_failures": failure_events[-5:],
        }

        bundle = {
            "task_id": state.metadata.task_id,
            "memory_version": "v1",
            "short_term": short_term,
            "long_term": long_term,
            "entity": entity,
            "procedural": procedural,
            "failure_memory": failure_memory,
        }
        output_path = self._memory_path(state)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        self._append_index_entry(bundle=bundle, memory_path=output_path, plan=plan, summary=summary)
        return bundle, output_path

    def retrieve(self, *, query: str, top_k: int = 3) -> list[dict]:
        index = self._load_index()
        if not index:
            return []

        query_tokens = self._tokenize(query)
        ranked_entries = []
        for entry in index:
            entry_tokens = set(entry.get("tokens", []))
            overlap = len(query_tokens & entry_tokens)
            if overlap == 0:
                continue
            ranked_entries.append((overlap, entry))

        ranked_entries.sort(key=lambda item: (-item[0], item[1].get("captured_at", "")), reverse=False)
        retrieved = []
        for _, entry in ranked_entries[:top_k]:
            memory_path = Path(entry["memory_path"])
            if not memory_path.exists():
                continue
            bundle = json.loads(memory_path.read_text(encoding="utf-8"))
            retrieved.append(
                {
                    "task_id": entry["task_id"],
                    "query": entry["query"],
                    "plan_type": entry.get("plan_type"),
                    "summary_conclusion": entry.get("summary_conclusion", ""),
                    "memory_path": str(memory_path),
                    "captured_at": entry.get("captured_at"),
                    "memory_version": bundle.get("memory_version"),
                }
            )
        return retrieved

    def _append_index_entry(self, *, bundle: dict, memory_path: Path, plan: dict, summary: dict) -> None:
        index = self._load_index()
        summary_conclusion = summary.get("conclusion", "") if isinstance(summary, dict) else ""
        query = bundle["short_term"]["query"]
        entry = {
            "task_id": bundle["task_id"],
            "query": query,
            "plan_type": plan.get("plan_type") if isinstance(plan, dict) else None,
            "summary_conclusion": summary_conclusion,
            "memory_path": str(memory_path),
            "captured_at": bundle["long_term"]["captured_at"],
            "tokens": sorted(self._tokenize(query) | self._tokenize(summary_conclusion)),
        }
        index = [existing for existing in index if existing.get("task_id") != entry["task_id"]]
        index.append(entry)
        self._index_path().parent.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_index(self) -> list[dict]:
        index_path = self._index_path()
        if not index_path.exists():
            return []
        return json.loads(index_path.read_text(encoding="utf-8"))

    def _index_path(self) -> Path:
        return self.project_root / "outputs" / "memory" / "index.json"

    def _memory_path(self, state: StateCenter) -> Path:
        return self.project_root / "outputs" / "memory" / f"{state.metadata.task_id}.json"

    def _tokenize(self, text: str) -> set[str]:
        return {token for token in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(token) >= 3}
