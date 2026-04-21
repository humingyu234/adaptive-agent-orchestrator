from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        ...

    @abstractmethod
    def complete_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    mode: str
    configured: bool
    available: bool
    default_model: str
    api_base: str | None = None
    note: str = ""


class MockProvider(LLMProvider):
    name = "mock"

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        return f"Mock response for: {prompt[:100]}"

    def complete_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        return {"mock": True, "prompt_preview": prompt[:100]}


class CLIProvider(LLMProvider):
    name = "cli"

    def __init__(self, command: str | None = None, timeout: int = 120):
        self.command = command or os.environ.get("LLM_CLI_COMMAND", "codex")
        self.timeout = timeout

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        try:
            result = subprocess.run(
                self.command,
                shell=True,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                raise RuntimeError(f"CLI command failed: {result.stderr}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"CLI command timed out after {self.timeout}s")

    def complete_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        json_prompt = f"{prompt}\n\nReturn JSON only."
        raw = self.complete(
            json_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": raw, "parse_error": True}


class CodexProvider(CLIProvider):
    name = "codex"

    def __init__(self, model: str = "o3", timeout: int = 180):
        self.model = model
        self.timeout = timeout

    def _resolve_codex_command(self) -> list[str]:
        for candidate in ("codex.exe", "codex.cmd", "codex"):
            path = shutil.which(candidate)
            if path:
                return [path]
        return ["codex"]

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        actual_model = model or self.model
        output_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".txt",
                delete=False,
            ) as tmp:
                output_path = tmp.name

            result = subprocess.run(
                [
                    *self._resolve_codex_command(),
                    "exec",
                    "--model",
                    actual_model,
                    "--full-auto",
                    "--skip-git-repo-check",
                    "--color",
                    "never",
                    "-o",
                    output_path,
                    "-",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"Codex CLI failed: {details}")

            file_output = ""
            if output_path and os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    file_output = f.read().strip()

            if file_output:
                return file_output

            stdout = result.stdout.strip()
            if stdout:
                return stdout

            raise RuntimeError("Codex CLI returned no final output.")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Codex CLI timed out after {self.timeout}s")
        finally:
            if output_path and os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass


class OllamaProvider(CLIProvider):
    name = "ollama"

    def __init__(self, model: str = "llama3", timeout: int = 120):
        super().__init__(command=f"ollama run {model}", timeout=timeout)


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        name: str,
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        self.name = name
        self.api_key = api_key
        self.api_base = (api_base or "").rstrip("/") + "/"

    def _get_client(self):
        import httpx

        return httpx.Client(
            base_url=self.api_base,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        import httpx

        client = self._get_client()
        try:
            response = client.post(
                "chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            detail = exc.response.text.strip()
            if status_code == 502:
                raise RuntimeError(
                    f"{self.name} gateway returned HTTP 502 for model '{model}' at '{self.api_base}'. "
                    "This usually means the upstream model service or proxy gateway is unavailable."
                ) from exc
            raise RuntimeError(
                f"{self.name} request failed with HTTP {status_code} for model '{model}' at '{self.api_base}'. "
                f"Response: {detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"{self.name} request could not reach '{self.api_base}' for model '{model}': {exc}"
            ) from exc
        finally:
            client.close()

    def complete_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        raw = self.complete(
            prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": raw, "parse_error": True}


class GLMProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        key = api_key or os.environ.get("GLM_API_KEY")
        base = api_base or os.environ.get("GLM_API_BASE", "https://open.bigmodel.cn/api/paas/v4")
        if not key:
            raise ValueError("GLM API key not found. Set GLM_API_KEY environment variable.")
        super().__init__(name="glm", api_key=key, api_base=base)


class KimiProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        key = api_key or os.environ.get("KIMI_API_KEY")
        base = api_base or os.environ.get("KIMI_API_BASE", "https://api.moonshot.cn/v1")
        if not key:
            raise ValueError("Kimi API key not found. Set KIMI_API_KEY environment variable.")
        super().__init__(name="kimi", api_key=key, api_base=base)


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        base = api_base or os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        if not key:
            raise ValueError("DeepSeek API key not found. Set DEEPSEEK_API_KEY environment variable.")
        super().__init__(name="deepseek", api_key=key, api_base=base)


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        base = api_base or os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
        if not key:
            raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY environment variable.")
        super().__init__(name="openai", api_key=key, api_base=base)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key not found. Set ANTHROPIC_API_KEY environment variable.")

    def _get_client(self):
        import httpx

        return httpx.Client(
            base_url="https://api.anthropic.com/",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        client = self._get_client()
        try:
            response = client.post(
                "v1/messages",
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
        finally:
            client.close()

    def complete_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        raw = self.complete(
            prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": raw, "parse_error": True}


PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "mock": MockProvider,
    "cli": CLIProvider,
    "codex": CodexProvider,
    "ollama": OllamaProvider,
    "glm": GLMProvider,
    "kimi": KimiProvider,
    "deepseek": DeepSeekProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(name: str, **kwargs) -> LLMProvider:
    if name not in PROVIDER_REGISTRY:
        raise KeyError(f"Unknown provider: {name}. Available: {list(PROVIDER_REGISTRY.keys())}")
    return PROVIDER_REGISTRY[name](**kwargs)


def list_providers() -> list[str]:
    return list(PROVIDER_REGISTRY.keys())


def describe_providers() -> list[ProviderStatus]:
    provider_defaults = {
        "mock": {"mode": "builtin", "default_model": "mock", "configured": True, "available": True, "note": "Local mock provider."},
        "cli": {
            "mode": "cli",
            "default_model": "cli-default",
            "configured": bool(os.environ.get("LLM_CLI_COMMAND")),
            "available": bool(os.environ.get("LLM_CLI_COMMAND")),
            "note": "Uses LLM_CLI_COMMAND when configured.",
        },
        "codex": {
            "mode": "cli",
            "default_model": "gpt-5.4",
            "configured": bool(_find_command("codex.exe", "codex.cmd", "codex")),
            "available": bool(_find_command("codex.exe", "codex.cmd", "codex")),
            "note": "Uses local Codex CLI.",
        },
        "ollama": {
            "mode": "cli",
            "default_model": "llama3",
            "configured": bool(_find_command("ollama.exe", "ollama.cmd", "ollama")),
            "available": bool(_find_command("ollama.exe", "ollama.cmd", "ollama")),
            "note": "Uses local Ollama CLI.",
        },
        "glm": {
            "mode": "http",
            "default_model": "GLM-5.1",
            "configured": bool(os.environ.get("GLM_API_KEY")),
            "available": bool(os.environ.get("GLM_API_KEY")),
            "api_base": os.environ.get("GLM_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
            "note": "OpenAI-compatible HTTP API.",
        },
        "kimi": {
            "mode": "http",
            "default_model": "moonshot-v1-8k",
            "configured": bool(os.environ.get("KIMI_API_KEY")),
            "available": bool(os.environ.get("KIMI_API_KEY")),
            "api_base": os.environ.get("KIMI_API_BASE", "https://api.moonshot.cn/v1"),
            "note": "OpenAI-compatible HTTP API.",
        },
        "deepseek": {
            "mode": "http",
            "default_model": "deepseek-chat",
            "configured": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "available": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "api_base": os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
            "note": "OpenAI-compatible HTTP API.",
        },
        "openai": {
            "mode": "http",
            "default_model": "gpt-4o-mini",
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
            "available": bool(os.environ.get("OPENAI_API_KEY")),
            "api_base": os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
            "note": "OpenAI-compatible HTTP API.",
        },
        "anthropic": {
            "mode": "http",
            "default_model": "claude-3-haiku-20240307",
            "configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "available": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "api_base": "https://api.anthropic.com/",
            "note": "Anthropic messages API.",
        },
    }

    statuses: list[ProviderStatus] = []
    for name in list_providers():
        meta = provider_defaults[name]
        statuses.append(
            ProviderStatus(
                name=name,
                mode=meta["mode"],
                configured=meta["configured"],
                available=meta["available"],
                default_model=meta["default_model"],
                api_base=meta.get("api_base"),
                note=meta.get("note", ""),
            )
        )
    return statuses


def _find_command(*candidates: str) -> str | None:
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None
