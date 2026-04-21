from __future__ import annotations

from ..guardrails import GuardrailManager, build_default_guardrail_manager
from ..llm_client import LLMClient
from ..llm_providers import LLMProvider, get_provider
from ..models import AgentConfig, EvalResult
from ..tool_registry import ToolRegistry, build_default_tool_registry, build_real_tool_registry


class BaseAgent:
    """所有 Agent 的基类

    每个 agent 实例拥有独立的 tool_registry、guardrail_manager、llm_client，
    避免多实例共享状态导致的并发问题。
    """

    config: AgentConfig

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        guardrail_manager: GuardrailManager | None = None,
        llm_client: LLMClient | None = None,
        llm_provider: LLMProvider | str | None = None,
        use_real_tools: bool = False,
    ) -> None:
        self._tool_registry = tool_registry or (
            build_real_tool_registry() if use_real_tools else build_default_tool_registry()
        )
        self._guardrail_manager = guardrail_manager or build_default_guardrail_manager()
        self._llm_client = self._resolve_llm_client(llm_client, llm_provider)

    def _resolve_llm_client(
        self,
        llm_client: LLMClient | None,
        llm_provider: LLMProvider | str | None,
    ) -> LLMClient:
        """解析 LLM Client

        优先级：
        1. 显式传入的 llm_client
        2. 显式传入的 llm_provider
        3. AgentConfig 中配置的 llm_provider
        4. 默认 Mock LLMClient
        """
        if llm_client is not None:
            return llm_client

        # 优先使用显式传入的 provider
        provider = llm_provider
        if provider is None and hasattr(self, "config"):
            # 其次使用 AgentConfig 中配置的 provider
            provider = self.config.llm_provider

        if provider is not None:
            return LLMClient(provider=provider)

        return LLMClient()

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    @tool_registry.setter
    def tool_registry(self, value: ToolRegistry) -> None:
        self._tool_registry = value

    @property
    def guardrail_manager(self) -> GuardrailManager:
        return self._guardrail_manager

    @guardrail_manager.setter
    def guardrail_manager(self, value: GuardrailManager) -> None:
        self._guardrail_manager = value

    @property
    def llm_client(self) -> LLMClient:
        return self._llm_client

    @llm_client.setter
    def llm_client(self, value: LLMClient) -> None:
        self._llm_client = value

    def run(self, context_view: dict) -> dict:
        raise NotImplementedError

    def self_evaluate(self, output: dict) -> EvalResult | None:
        return None

    def run_tool(self, tool_name: str, **kwargs):
        if tool_name not in self.config.tools:
            raise ValueError(f"Agent '{self.config.name}' cannot use undeclared tool '{tool_name}'")
        tool = self._tool_registry.get(tool_name)
        self._assert_tool_permission(tool_name=tool_name, tool_risk_level=tool.risk_level)
        return self._tool_registry.run(tool_name, **kwargs)

    def apply_input_guardrails(self, context_view: dict) -> None:
        self._guardrail_manager.run_many(
            names=self.config.guardrails,
            stage="input",
            agent_name=self.config.name,
            payload=context_view,
        )

    def apply_output_guardrails(self, output: dict) -> None:
        self._guardrail_manager.run_many(
            names=self.config.guardrails,
            stage="output",
            agent_name=self.config.name,
            payload=output,
        )

    def complete_structured(self, task: str, **payload):
        return self._llm_client.complete_structured(
            task=task,
            profile=self.config.model_profile,
            payload=payload,
            model=self.config.llm_model,
        )

    def _assert_tool_permission(self, *, tool_name: str, tool_risk_level: str) -> None:
        ranking = {"low": 1, "medium": 2, "high": 3}
        agent_rank = ranking.get(self.config.trust_level, 0)
        tool_rank = ranking.get(tool_risk_level, 0)
        if agent_rank < tool_rank:
            raise ValueError(
                f"Agent '{self.config.name}' with trust_level '{self.config.trust_level}' "
                f"cannot use tool '{tool_name}' with risk_level '{tool_risk_level}'"
            )
