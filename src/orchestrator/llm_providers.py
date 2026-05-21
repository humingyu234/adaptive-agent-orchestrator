from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import PureWindowsPath
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

    @abstractmethod
    def complete_json_strict(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2500,
        max_retries: int = 2,
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

    def complete_json_strict(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2500,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        return {"mock": True, "prompt_preview": prompt[:100], "mode": "strict"}


class CLIProvider(LLMProvider):
    """Run an external CLI command as an LLM provider.

    The command string is parsed with shlex.split() so that ``"codex --model gpt-5"``
    becomes ``["codex", "--model", "gpt-5"]``.  Shell metacharacters (``;``, ``|``,
    ``&&`` etc.) are treated as literal arguments — they do NOT execute shell
    commands.

    ``shell=False`` is always used to prevent command injection via the
    ``LLM_CLI_COMMAND`` environment variable.
    """

    name = "cli"

    def __init__(self, command: str | None = None, timeout: int = 120):
        if command is not None:
            raw = command.strip()
        else:
            raw = os.environ.get("LLM_CLI_COMMAND", "codex").strip()
        if not raw:
            raise ValueError("CLIProvider command must not be empty")
        self.command_str = raw
        self._argv = self._parse_command(raw)
        self.timeout = timeout

    @staticmethod
    def _parse_command(raw: str) -> list[str]:
        """Parse a command string into argv list.  Shell metacharacters are literal."""
        try:
            argv = shlex.split(raw)
        except ValueError as exc:
            raise ValueError(
                f"CLIProvider: cannot parse command {raw!r}: {exc}"
            ) from exc
        if not argv:
            raise ValueError("CLIProvider: command resolved to empty argv")
        if not argv[0].strip():
            raise ValueError(f"CLIProvider: command has empty executable: {raw!r}")
        return argv

    def _build_argv(self, model: str | None = None) -> list[str]:
        """Return the argv list for a subprocess call.

        If the user already specified ``--model`` in the command string we keep it.
        Otherwise ``--model <model>`` is appended when *model* is non-empty.
        """
        argv = list(self._argv)
        has_model_flag = any(
            arg in ("-m", "--model")
            for arg in argv
        )
        if not has_model_flag and model:
            argv.extend(["--model", model])
        return argv

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        argv = self._build_argv(model)
        try:
            result = subprocess.run(
                argv,
                shell=False,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"CLI command failed (exit {result.returncode}): {result.stderr.strip()}"
                )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"CLI command timed out after {self.timeout}s")
        except FileNotFoundError:
            raise RuntimeError(
                f"CLI command not found: {argv[0]!r}. "
                f"Install it or set LLM_CLI_COMMAND."
            )

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

    def complete_json_strict(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2500,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Call the CLI LLM and return parsed JSON dict, with automatic retry.

        On parse failure the original response text is appended to a correction
        prompt and the model is asked to fix it.  After *max_retries* attempts
        the method returns ``{"parse_error": True, "raw": "...", "attempts": N,
        "last_error": "..."}`` instead of raising — callers MUST check for
        ``parse_error`` in the returned dict.
        """
        last_raw: str = ""
        last_error: str = ""
        current_prompt = prompt

        for attempt in range(max_retries + 1):
            try:
                raw = self.complete(
                    current_prompt + "\n\nReturn JSON only.",
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except RuntimeError:
                raise  # network / auth errors propagate immediately

            last_raw = raw
            text = raw.strip()

            # Strip markdown code fences
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # Try to extract JSON substring if the model embedded it in text
            parsed = _extract_json_substring(text)
            if parsed is not None:
                return parsed

            # Parse failed — build correction prompt
            last_error = _describe_json_parse_error(text)
            if attempt < max_retries:
                current_prompt = _build_correction_prompt(
                    original_prompt=prompt,
                    raw_response=text,
                    error=last_error,
                )
                temperature = max(0.1, temperature - 0.1)

        return {
            "parse_error": True,
            "raw": last_raw,
            "attempts": max_retries + 1,
            "last_error": last_error,
        }


class CodexProvider(CLIProvider):
    name = "codex"

    def __init__(self, model: str = "o3", timeout: int = 180):
        self.model = model
        self.timeout = timeout

    def _resolve_codex_command(self) -> list[str]:
        candidates = ("codex.exe", "codex.cmd", "codex")
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                return self._normalize_codex_command(path)
        return ["codex"]

    def _normalize_codex_command(self, path: str) -> list[str]:
        # On WSL, PATH may resolve to Windows launchers like /mnt/c/.../codex.cmd.
        # Invoke them through cmd.exe so they remain executable from Linux.
        if os.name != "nt" and path.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", self._to_windows_path(path)]
        return [path]

    def _to_windows_path(self, path: str) -> str:
        if path.startswith("/mnt/") and len(path) > 6:
            drive = path[5]
            remainder = path[6:].replace("/", "\\")
            return str(PureWindowsPath(f"{drive}:{remainder}"))
        return path

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
                input=prompt.encode("utf-8"),
                capture_output=True,
                timeout=self.timeout,
            )
            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if result.returncode != 0:
                details = stderr or stdout
                raise RuntimeError(f"Codex CLI failed: {details}")

            file_output = ""
            if output_path and os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    file_output = f.read().strip()

            if file_output:
                return file_output

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
        self._json_mode_supported: bool | None = None  # lazy detection

    def _get_client(self):
        import httpx

        return httpx.Client(
            base_url=self.api_base,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=180.0,
        )

    def _supports_json_mode(self) -> bool:
        """Detect whether this provider supports response_format json_object."""
        if self._json_mode_supported is not None:
            return self._json_mode_supported
        # GLM proxy (svips.org) and Kimi do not reliably support json_object mode.
        # DeepSeek and OpenAI do.  Default to False for safety.
        unsupported = {"glm", "kimi"}
        self._json_mode_supported = self.name not in unsupported
        return self._json_mode_supported

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: str | None = None,
    ) -> str:
        import httpx

        client = self._get_client()
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format and self._supports_json_mode():
            body["response_format"] = {"type": response_format}

        try:
            response = client.post("chat/completions", json=body)
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

    # ------------------------------------------------------------------
    # Phase 19v2: structured JSON with retry
    # ------------------------------------------------------------------

    def complete_json_strict(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2500,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Call the LLM and return parsed JSON dict, with automatic retry.

        On parse failure the original response text is appended to a correction
        prompt and the model is asked to fix it.  After *max_retries* attempts
        the method returns ``{"parse_error": True, "raw": "...", "attempts": N,
        "last_error": "..."}`` instead of raising — callers MUST check for
        ``parse_error`` in the returned dict.

        JSON mode (``response_format={"type": "json_object"}``) is enabled for
        providers that support it, with automatic fallback for those that don't.
        """
        last_raw: str = ""
        last_error: str = ""
        current_prompt = prompt

        for attempt in range(max_retries + 1):
            use_json_mode = self._supports_json_mode()
            try:
                raw = self.complete(
                    current_prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format="json_object" if use_json_mode else None,
                )
            except RuntimeError:
                raise  # network / auth errors propagate immediately

            last_raw = raw
            text = raw.strip()

            # Strip markdown code fences
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # Try to extract JSON substring if the model embedded it in text
            parsed = _extract_json_substring(text)

            if parsed is not None:
                return parsed

            # Parse failed — build correction prompt
            last_error = _describe_json_parse_error(text)
            if attempt < max_retries:
                correction = _build_correction_prompt(
                    original_prompt=prompt,
                    raw_response=text,
                    error=last_error,
                )
                current_prompt = correction
                temperature = max(0.1, temperature - 0.1)

        return {
            "parse_error": True,
            "raw": last_raw,
            "attempts": max_retries + 1,
            "last_error": last_error,
        }


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
            timeout=180.0,
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
                    "temperature": temperature,
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

    def complete_json_strict(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2500,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Call the Anthropic LLM and return parsed JSON dict, with automatic retry.

        Anthropic does not support response_format json_object.
        On parse failure the original response text is appended to a correction
        prompt and the model is asked to fix it.  After *max_retries* attempts
        the method returns ``{"parse_error": True, "raw": "...", "attempts": N,
        "last_error": "..."}`` instead of raising — callers MUST check for
        ``parse_error`` in the returned dict.
        """
        last_raw: str = ""
        last_error: str = ""
        current_prompt = prompt

        for attempt in range(max_retries + 1):
            try:
                raw = self.complete(
                    current_prompt + "\n\nReturn JSON only.",
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except RuntimeError:
                raise  # network / auth errors propagate immediately

            last_raw = raw
            text = raw.strip()

            # Strip markdown code fences
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # Try to extract JSON substring if the model embedded it in text
            parsed = _extract_json_substring(text)
            if parsed is not None:
                return parsed

            # Parse failed — build correction prompt
            last_error = _describe_json_parse_error(text)
            if attempt < max_retries:
                current_prompt = _build_correction_prompt(
                    original_prompt=prompt,
                    raw_response=text,
                    error=last_error,
                )
                temperature = max(0.1, temperature - 0.1)

        return {
            "parse_error": True,
            "raw": last_raw,
            "attempts": max_retries + 1,
            "last_error": last_error,
        }


# ------------------------------------------------------------------
# JSON parse helpers for complete_json_strict
# ------------------------------------------------------------------


def _extract_json_substring(text: str) -> dict[str, Any] | None:
    """Try to find and parse a JSON object within arbitrary text.

    Returns a dict on success or None if no JSON object can be found.
    """
    if not text:
        return None

    # Fast path: the whole string is valid JSON
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find JSON object boundaries with braces
    # Strategy: find the first '{' and find its matching '}'
    start = text.find("{")
    if start == -1:
        return None

    # Walk forward counting brace depth
    depth = 0
    for end in range(start, len(text)):
        ch = text[end]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:end + 1]
                try:
                    result = json.loads(candidate)
                    if isinstance(result, dict):
                        return result
                except (json.JSONDecodeError, ValueError):
                    pass
                break

    return None


def _describe_json_parse_error(text: str) -> str:
    """Produce a human-readable description of why the text fails JSON parse."""
    if not text:
        return "Output was empty (expected a JSON object)."

    # Trim to avoid reporting errors on trailing noise if we can find a brace
    trimmed = text.strip()

    try:
        json.loads(trimmed)
        return "Text parsed as valid JSON but was not a dict."
    except json.JSONDecodeError as exc:
        # Give context: show the error position
        line = exc.lineno
        col = exc.colno
        msg = exc.msg
        # Show a snippet around the error
        snippet = ""
        lines = text.split("\n")
        if 1 <= line <= len(lines):
            snippet = lines[line - 1].strip()
            if len(snippet) > 120:
                snippet = snippet[:120] + "..."
        return (
            f"JSON parse error at line {line}, col {col}: {msg}. "
            f"Snippet: {snippet}"
        )


def _build_correction_prompt(
    original_prompt: str,
    raw_response: str,
    error: str,
) -> str:
    """Build a correction prompt with the original request, raw output, and errors."""
    return (
        f"{original_prompt}\n\n"
        f"---\n\n"
        f"Your last response could not be parsed as valid JSON.\n\n"
        f"Error: {error}\n\n"
        f"Your last response was:\n```\n{raw_response[:2000]}\n```\n\n"
        f"Please fix the issue and return ONLY a valid JSON object. "
        f"Do NOT wrap it in markdown fences, do not add any other text."
    )


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
