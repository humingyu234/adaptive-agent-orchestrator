from .models import AgentConfig
from .agents.base import BaseAgent


REGISTRY: dict[str, type[BaseAgent]] = {}


def register(name: str):
    def decorator(cls: type[BaseAgent]) -> type[BaseAgent]:
        if not hasattr(cls, "config") or not isinstance(cls.config, AgentConfig):
            raise ValueError(f"Agent '{name}' is missing a valid config")
        if cls.config.name != name:
            raise ValueError(f"config.name '{cls.config.name}' does not match registry name '{name}'")
        REGISTRY[name] = cls
        return cls
    return decorator


def get_agent(name: str) -> type[BaseAgent]:
    if name not in REGISTRY:
        raise KeyError(f"Agent '{name}' is not registered")
    return REGISTRY[name]
