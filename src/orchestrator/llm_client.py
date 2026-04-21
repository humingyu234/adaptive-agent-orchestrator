from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .llm_providers import LLMProvider, MockProvider, get_provider


@dataclass(frozen=True)
class ModelProfile:
    name: str
    model_name: str
    temperature: float
    max_tokens: int


class LLMClient:
    """Unified wrapper over mock and real LLM providers."""

    def __init__(
        self,
        provider: LLMProvider | str | None = None,
        default_model: str | None = None,
    ) -> None:
        self._provider = self._resolve_provider(provider)
        self._default_model = self._resolve_default_model(default_model)
        self._profiles = self._build_profiles()

    def _resolve_provider(self, provider: LLMProvider | str | None) -> LLMProvider:
        if provider is None:
            return MockProvider()
        if isinstance(provider, str):
            return get_provider(provider)
        return provider

    def _resolve_default_model(self, default_model: str | None) -> str:
        if default_model:
            return default_model

        provider_name = getattr(self._provider, "name", "mock")
        defaults = {
            "glm": "GLM-5.1",
            "kimi": "moonshot-v1-8k",
            "deepseek": "deepseek-chat",
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-haiku-20240307",
            "ollama": "llama3",
            "codex": "o3",
            "cli": "cli-default",
            "mock": "mock",
        }
        return defaults.get(provider_name, "gpt-4o-mini")

    def _build_profiles(self) -> dict[str, ModelProfile]:
        if self._provider.name == "mock":
            return {
                "worker": ModelProfile("worker", "mock-worker", 0.2, 3000),
                "worker_fast": ModelProfile("worker_fast", "mock-worker-fast", 0.1, 2000),
                "orchestrator": ModelProfile("orchestrator", "mock-orchestrator", 0.1, 3500),
            }

        return {
            "worker": ModelProfile("worker", self._default_model, 0.2, 3000),
            "worker_fast": ModelProfile("worker_fast", self._default_model, 0.1, 2000),
            "orchestrator": ModelProfile("orchestrator", self._default_model, 0.1, 3500),
        }

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def get_profile(self, name: str) -> ModelProfile:
        if name not in self._profiles:
            raise KeyError(f"Model profile '{name}' is not registered")
        return self._profiles[name]

    def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        actual_model = model or self._default_model
        return self._provider.complete(
            prompt,
            model=actual_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def complete_json(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        actual_model = model or self._default_model
        return self._provider.complete_json(
            prompt,
            model=actual_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def complete_structured(
        self,
        *,
        task: str,
        profile: str,
        payload: dict[str, Any],
        model: str | None = None,
    ) -> dict[str, Any]:
        model_profile = self.get_profile(profile)

        if self._provider.name == "mock":
            return self._mock_complete(task=task, payload=payload, profile=model_profile)

        prompt = self._build_prompt(task=task, payload=payload)
        actual_model = model or model_profile.model_name or self._default_model

        result = self._provider.complete_json(
            prompt,
            model=actual_model,
            temperature=model_profile.temperature,
            max_tokens=model_profile.max_tokens,
        )
        result["model_profile"] = profile
        result["provider"] = self._provider.name
        return result

    def _build_prompt(self, *, task: str, payload: dict[str, Any]) -> str:
        if task == "plan":
            return self._build_plan_prompt(payload)
        if task == "summarize":
            return self._build_summarize_prompt(payload)
        if task == "supervise":
            return self._build_supervise_prompt(payload)
        raise KeyError(f"Unsupported task: {task}")

    def _build_plan_prompt(self, payload: dict[str, Any]) -> str:
        query = payload.get("query", "")
        plan_type = payload.get("plan_type", "research")
        retrieved_memories = payload.get("retrieved_memories", [])

        memory_hints = ""
        if retrieved_memories:
            memory_hints = f"\n\nRelevant past memories:\n{self._format_memories(retrieved_memories)}"

        return f"""You are a task planning expert. Generate a structured plan for the user query.
Task type: {plan_type}
User query: {query}
{memory_hints}

Return JSON only:
{{
    "sub_questions": ["sub-question 1", "sub-question 2", "sub-question 3"],
    "plan_type": "{plan_type}",
    "confidence": 0.85
}}
"""

    def _build_summarize_prompt(self, payload: dict[str, Any]) -> str:
        query = payload.get("query", "")
        plan_type = payload.get("plan_type", "general")
        sub_questions = payload.get("sub_questions", [])
        raw_documents = payload.get("raw_documents", [])

        docs_text = self._format_documents(raw_documents[:5])
        questions_text = "\n".join(f"- {q}" for q in sub_questions)

        return f"""You are an information summarization expert. Answer the user query based on the retrieved documents.
User query: {query}
Task type: {plan_type}

Sub-questions:
{questions_text}

Retrieved documents:
{docs_text}

Return JSON only:
{{
    "conclusion": "overall conclusion",
    "sections": [
        {{"sub_question": "question", "answer": "answer"}}
    ],
    "plan_type": "{plan_type}"
}}
"""

    def _build_supervise_prompt(self, payload: dict[str, Any]) -> str:
        query = payload.get("query", "")
        status = payload.get("status", "running")
        process_review = payload.get("process_review", {})
        concerns = payload.get("concerns", [])
        review_reason = payload.get("review_reason", "")
        suggested_target = payload.get("suggested_target", "none")
        suggested_action = payload.get("suggested_action", "accept")

        concerns_text = "\n".join(f"- {c}" for c in concerns) if concerns else "None"

        return f"""You are a task supervisor. Review the current execution state and decide the next action.
User query: {query}
Current status: {status}
Process review: {process_review}
Concerns:
{concerns_text}
Review reason: {review_reason}
Suggested target: {suggested_target}
Suggested action: {suggested_action}

Return JSON only:
{{
    "next_action": "accept or revise",
    "concerns": [],
    "summary": "review summary",
    "review_reason": "why",
    "suggested_target": "target agent or none",
    "suggested_action": "accept/revise/re_plan/gather_more_evidence"
}}
"""

    def _format_memories(self, memories: list[dict]) -> str:
        lines = []
        for i, memory in enumerate(memories[:3], 1):
            query = memory.get("query", "")
            summary = memory.get("summary", {})
            conclusion = summary.get("conclusion", "")[:100] if isinstance(summary, dict) else ""
            lines.append(f"{i}. {query}: {conclusion}")
        return "\n".join(lines)

    def _format_documents(self, documents: list[dict]) -> str:
        lines = []
        for i, doc in enumerate(documents, 1):
            title = doc.get("title", "Untitled")
            snippet = doc.get("snippet", "")[:200]
            lines.append(f"{i}. {title}\n   {snippet}")
        return "\n".join(lines)

    def _mock_complete(
        self,
        *,
        task: str,
        payload: dict[str, Any],
        profile: ModelProfile,
    ) -> dict[str, Any]:
        if task == "plan":
            return self._mock_plan(payload=payload, profile=profile)
        if task == "summarize":
            return self._mock_summary(payload=payload, profile=profile)
        if task == "supervise":
            return self._mock_supervisor_report(payload=payload, profile=profile)
        raise KeyError(f"Unsupported task: {task}")

    def _mock_plan(self, *, payload: dict[str, Any], profile: ModelProfile) -> dict[str, Any]:
        query = str(payload.get("query", "")).strip()
        plan_type = str(payload.get("plan_type", "research"))
        retrieved_memories = payload.get("retrieved_memories", [])
        seed = query or "task"
        return {
            "sub_questions": [
                f"What is the goal and scope of {seed}?",
                f"What key information does {seed} need?",
                f"How should {seed} be delivered?",
            ],
            "plan_type": plan_type,
            "confidence": 0.68,
            "model_profile": profile.name,
            "memory_hints_used": len(retrieved_memories) if isinstance(retrieved_memories, list) else 0,
        }

    def _mock_summary(self, *, payload: dict[str, Any], profile: ModelProfile) -> dict[str, Any]:
        query = str(payload.get("query", "")).strip()
        plan_type = str(payload.get("plan_type", "general"))
        sub_questions = payload.get("sub_questions", [])
        raw_documents = payload.get("raw_documents", [])

        sections = []
        for sub_question in sub_questions:
            sections.append({
                "sub_question": sub_question,
                "answer": f"Based on {len(raw_documents)} context items, formed summary for: {sub_question}",
            })

        conclusion = f"Summary for {query} ({plan_type}), based on {len(raw_documents)} items." if raw_documents else ""
        return {
            "conclusion": conclusion,
            "sections": sections,
            "plan_type": plan_type,
            "model_profile": profile.name,
        }

    def _mock_supervisor_report(self, *, payload: dict[str, Any], profile: ModelProfile) -> dict[str, Any]:
        query = str(payload.get("query", "")).strip()
        status = str(payload.get("status", "running"))
        process_review = payload.get("process_review", {})
        concerns = payload.get("concerns", [])
        review_reason = str(payload.get("review_reason", "Process complete, results acceptable"))
        suggested_target = str(payload.get("suggested_target", "none"))
        suggested_action = str(payload.get("suggested_action", "accept"))

        review_summary = f"Supervisor reviewed task: {query}" if query else "Supervisor reviewed current task"
        next_action = "accept" if suggested_action == "accept" else "revise"
        return {
            "query": query,
            "next_action": next_action,
            "status": "reviewed",
            "concerns": concerns,
            "summary": review_summary,
            "review_reason": review_reason,
            "suggested_target": suggested_target,
            "suggested_action": suggested_action,
            "process_review": {
                **process_review,
                "status_seen": status,
                "model_profile": profile.name,
            },
        }
