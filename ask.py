#!/usr/bin/env python3
"""
Terminal shortcut to call various LLMs without Claude Code.
Usage:
    python ask.py "帮我写一个 Python 快速排序" --model codex
    python ask.py "hello" --model kimi
    python ask.py "解释量子力学" --model deepseek
    python ask.py "写首诗" --model glm
"""

import argparse
import os
import subprocess
import sys


def call_codex(prompt: str) -> str:
    """Call the official Codex CLI (subscription-based, no API key needed)."""
    commands = [
        ["codex", "--quiet", "--no-approval", prompt],
        ["codex", "-q", "--no-approval", prompt],
        ["codex", "--quiet", prompt],
        ["codex", "-q", prompt],
        ["codex", prompt],
    ]
    last_err = ""
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                encoding="utf-8",
                errors="ignore",
            )
            if result.returncode == 0:
                return result.stdout.strip()
            last_err = result.stderr or result.stdout
        except Exception as exc:
            last_err = str(exc)
    raise RuntimeError(f"Codex CLI failed. Last error: {last_err}")


def call_openai_compatible(prompt: str, model: str, api_key: str, base_url: str) -> str:
    try:
        import openai
    except ImportError:
        raise ImportError("Please install openai: pip install openai")

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return resp.choices[0].message.content or ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask an LLM from the terminal")
    parser.add_argument("prompt", help="The prompt to send")
    parser.add_argument(
        "--model",
        choices=["codex", "kimi", "deepseek", "glm"],
        default="codex",
        help="Which model to use (default: codex)",
    )
    args = parser.parse_args()

    if args.model == "codex":
        print(call_codex(args.prompt))
        return

    if args.model == "kimi":
        api_key = os.environ.get("KIMI_API_KEY", "")
        if not api_key:
            print("Error: Set KIMI_API_KEY environment variable.", file=sys.stderr)
            sys.exit(1)
        print(call_openai_compatible(args.prompt, "moonshot-v1-8k", api_key, "https://api.moonshot.cn/v1"))
        return

    if args.model == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            print("Error: Set DEEPSEEK_API_KEY environment variable.", file=sys.stderr)
            sys.exit(1)
        print(call_openai_compatible(args.prompt, "deepseek-chat", api_key, "https://api.deepseek.com/v1"))
        return

    if args.model == "glm":
        api_key = os.environ.get("GLM_API_KEY", "")
        if not api_key:
            print("Error: Set GLM_API_KEY environment variable.", file=sys.stderr)
            sys.exit(1)
        print(call_openai_compatible(args.prompt, "GLM-5.1", api_key, "https://open.bigmodel.cn/api/paas/v4/"))
        return


if __name__ == "__main__":
    main()
