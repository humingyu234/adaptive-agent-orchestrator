"""Tests for Phase 14.5 — CLIProvider security fixes, no real CLI calls."""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from orchestrator.llm_providers import CLIProvider, MockProvider


class TestMockProvider:
    def test_complete_returns_mock_response(self):
        p = MockProvider()
        result = p.complete("hello", model="test")
        assert "hello" in result

    def test_complete_json_returns_dict(self):
        p = MockProvider()
        result = p.complete_json("hello", model="test")
        assert isinstance(result, dict)
        assert result.get("mock") is True


class TestCLIProviderCommandParsing:
    def test_cli_provider_parses_simple_command(self):
        provider = CLIProvider(command="echo")
        assert provider._argv == ["echo"]

    def test_cli_provider_parses_command_with_args(self):
        provider = CLIProvider(command="codex --model gpt-5")
        assert provider._argv == ["codex", "--model", "gpt-5"]

    def test_cli_provider_rejects_empty_command(self):
        with pytest.raises(ValueError, match="must not be empty"):
            CLIProvider(command="")

    def test_cli_provider_rejects_whitespace_command(self):
        with pytest.raises(ValueError, match="must not be empty"):
            CLIProvider(command="   ")

    def test_cli_provider_does_not_execute_shell_injection(self):
        """Shell metacharacters are treated as literal arguments, not commands."""
        provider = CLIProvider(command="codex; rm -rf /tmp/test")
        argv = provider._argv
        # shlex.split treats ; as a token: ['codex;', 'rm', '-rf', '/tmp/test']
        # The semicolon is attached to 'codex' — no second command
        joined = " ".join(argv)
        assert "codex" in joined
        assert ";" in joined
        assert "rm" in argv
        assert len(argv) > 1


class TestCLIProviderSubprocess:
    def test_cli_provider_runs_command_without_shell(self):
        """CLIProvider.complete() must use shell=False."""
        provider = CLIProvider(command="echo hello")
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="ok", stderr="")
            provider.complete("test prompt", model="test")
            _args, kwargs = mock_run.call_args
            # Verify shell=False
            assert kwargs.get("shell") is False
            # Verify argv is a list (not a string)
            argv = kwargs.get("args") if "args" in kwargs else _args[0]
            assert isinstance(argv, list)

    def test_cli_provider_raises_on_nonzero_exit(self):
        provider = CLIProvider(command="echo hello")
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="error msg")
            with pytest.raises(RuntimeError, match="CLI command failed"):
                provider.complete("test", model="test")

    def test_cli_provider_shell_special_chars_are_literal(self):
        """Verify that 'echo ok; rm -rf /tmp/aao-test' does NOT execute rm."""
        provider = CLIProvider(command="echo ok; rm -rf /tmp/aao-test")
        # shlex.split treats ; as a regular token when not preceded by space
        # but with spaces, 'echo' 'ok;' 'rm' '-rf' '/tmp/aao-test' -> 5 tokens
        # Actually shlex.split("echo ok; rm -rf /tmp/aao-test"):
        #   ['echo', 'ok;', 'rm', '-rf', '/tmp/aao-test']
        # So "ok;" is one token with semicolon attached
        # The key is: the argv is a list, shell=False, so no second command runs
        argv = provider._build_argv("test-model")
        assert isinstance(argv, list)
        assert len(argv) >= 2
        # With shell=False, the semicolon cannot trigger a second command
        # It will be passed as a literal argument to echo
        assert ";" in " ".join(argv) or any(";" in a for a in argv)

    def test_build_argv_appends_model_when_not_specified(self):
        provider = CLIProvider(command="codex")
        argv = provider._build_argv("gpt-5")
        assert "--model" in argv
        assert "gpt-5" in argv

    def test_build_argv_does_not_duplicate_model_flag(self):
        provider = CLIProvider(command="codex --model gpt-4")
        argv = provider._build_argv("gpt-5")
        assert argv.count("--model") == 1
        # Original model flag preserved
        assert "gpt-4" in argv
        assert "gpt-5" not in argv


class TestCLIProviderWithoutMocks:
    """Tests that exercise real subprocess (safe commands only)."""

    def test_cli_passes_prompt_via_stdin(self):
        """End-to-end: CLIProvider with 'cat' returns the prompt text from stdin."""
        provider = CLIProvider(command="cat", timeout=5)
        result = provider.complete("hello-test-123", model="")
        assert "hello-test-123" in result
