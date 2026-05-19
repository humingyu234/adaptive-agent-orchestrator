"""Shared utilities for demo scripts — deterministic, no LLM, no network, no filesystem."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def ensure_output_dir() -> Path:
    """Return the examples/demo directory, creating it if needed."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    demo_dir = repo_root / "examples" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    return demo_dir


def print_header(title: str) -> None:
    width = 68
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def print_section(label: str, content: str | list[str] | dict[str, Any] | None, indent: int = 2) -> None:
    prefix = " " * indent
    print(f"\n{prefix}[{label}]")
    if content is None:
        print(f"{prefix}  (none)")
    elif isinstance(content, str):
        for line in content.splitlines():
            print(f"{prefix}  {line}")
    elif isinstance(content, dict):
        print(f"{prefix}  {json.dumps(content, indent=2, default=str).replace(chr(10), chr(10) + prefix + '  ')}")
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                flat = ", ".join(f"{k}={v}" for k, v in item.items())
                print(f"{prefix}  - {flat}")
            else:
                print(f"{prefix}  - {item}")
    else:
        print(f"{prefix}  {content}")


def print_decision(decision: dict[str, Any]) -> None:
    action = decision.get("action", "?")
    passed = decision.get("passed", False)
    status = "PASS" if passed else "BLOCK"
    reason = decision.get("reason", "")
    print(f"\n  ControlDecision: action={action}  passed={passed}  [{status}]")
    if reason:
        print(f"    reason: {reason}")
    for extra in ("failure_category", "recovery_hint", "severity"):
        val = decision.get(extra)
        if val:
            print(f"    {extra}: {val}")


def write_sample_json(filename: str, data: dict[str, Any]) -> Path:
    demo_dir = ensure_output_dir()
    path = demo_dir / filename
    path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False))
    return path


def write_sample_text(filename: str, text: str) -> Path:
    demo_dir = ensure_output_dir()
    path = demo_dir / filename
    path.write_text(text)
    return path


def write_sample_markdown(filename: str, text: str) -> Path:
    demo_dir = ensure_output_dir()
    path = demo_dir / filename
    path.write_text(text)
    return path


def banner(text: str) -> None:
    print(f"\n{'*' * 60}")
    print(f"* {text}")
    print(f"{'*' * 60}")
