from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .failure_taxonomy import FailureCategory


class GuardrailViolation(ValueError):
    """护栏违规异常

    当护栏检查失败时抛出，携带失败类型信息。
    """

    def __init__(
        self,
        *,
        guardrail_name: str,
        stage: str,
        message: str,
        failure_category: FailureCategory = FailureCategory.GUARDRAIL_BLOCKED,
    ):
        super().__init__(message)
        self.guardrail_name = guardrail_name
        self.stage = stage
        self.message = message
        self.failure_category = failure_category


@dataclass(frozen=True)
class GuardrailSpec:
    name: str
    stage: Literal["input", "output"]
    description: str
    handler: Callable[..., None]


class GuardrailManager:
    def __init__(self) -> None:
        self._guardrails: dict[str, GuardrailSpec] = {}

    def register(
        self,
        *,
        name: str,
        stage: Literal["input", "output"],
        description: str,
        handler: Callable[..., None],
    ) -> None:
        if name in self._guardrails:
            raise ValueError(f"Guardrail '{name}' is already registered")
        self._guardrails[name] = GuardrailSpec(
            name=name,
            stage=stage,
            description=description,
            handler=handler,
        )

    def get(self, name: str) -> GuardrailSpec:
        if name not in self._guardrails:
            raise KeyError(f"Guardrail '{name}' is not registered")
        return self._guardrails[name]

    def run_many(
        self,
        *,
        names: list[str],
        stage: Literal["input", "output"],
        agent_name: str,
        payload: dict[str, Any],
    ) -> None:
        for name in names:
            spec = self.get(name)
            if spec.stage != stage:
                continue
            spec.handler(agent_name=agent_name, payload=payload)

    def list_names(self) -> list[str]:
        return sorted(self._guardrails)


def build_default_guardrail_manager() -> GuardrailManager:
    manager = GuardrailManager()
    manager.register(
        name="require_non_empty_query",
        stage="input",
        description="Reject agent execution when the query is empty or whitespace only.",
        handler=_require_non_empty_query,
    )
    manager.register(
        name="block_sensitive_output_terms",
        stage="output",
        description="Reject outputs that contain obvious secret-bearing tokens.",
        handler=_block_sensitive_output_terms,
    )
    return manager


def _require_non_empty_query(*, agent_name: str, payload: dict[str, Any]) -> None:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise GuardrailViolation(
            guardrail_name="require_non_empty_query",
            stage="input",
            message=f"{agent_name} 需要非空 query 才能继续执行",
        )


def _block_sensitive_output_terms(*, agent_name: str, payload: dict[str, Any]) -> None:
    lowered = _flatten_strings(payload).lower()
    blocked_terms = ("api_key", "password", "secret_key", "access_token")
    for term in blocked_terms:
        if term in lowered:
            raise GuardrailViolation(
                guardrail_name="block_sensitive_output_terms",
                stage="output",
                message=f"{agent_name} 的输出触发敏感信息护栏：{term}",
            )


def _flatten_strings(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_strings(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_strings(item) for item in value)
    return ""
