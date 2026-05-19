"""Worker adapters — thin rendering and loading conveniences per worker kind.

Each module owns the task-instruction rendering and result-loading helpers
for one external worker (Claude Code, etc.).  Policy, recovery, and evaluation
logic stay in the orchestrator layer.
"""

from .claude_code import ClaudeCodeTaskRenderer, render_claude_code_task

__all__ = ["ClaudeCodeTaskRenderer", "render_claude_code_task"]
