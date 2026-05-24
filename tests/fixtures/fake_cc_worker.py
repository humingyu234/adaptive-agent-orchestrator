#!/usr/bin/env python3
"""Fake Claude Code worker for testing Phase 18 subprocess bridge.

Simulates a real Claude Code worker by reading a task prompt from stdin,
writing expected output files (result.md, status.json, observed/), and
exiting with a configurable code.

Usage:
  echo "prompt" | python fake_cc_worker.py --behavior success --packet-dir /tmp/pkt
  echo "prompt" | python fake_cc_worker.py --behavior missing_evidence --exit-code 0

Behaviors:
  success          — writes full evidence: test_output.txt + diff.patch + result + status
  missing_evidence — writes result.md and status.json but no observed/ files
  test_failure     — writes test_output.txt with FAILED lines
  nonzero_exit     — writes partial output, exits 1
  timeout          — sleeps indefinitely (caller must kill)
  protected_file   — writes changed_files including config/secrets.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--behavior", default="success",
                        choices=["success", "missing_evidence", "test_failure",
                                  "nonzero_exit", "timeout", "protected_file"])
    parser.add_argument("--packet-dir", default="")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0)
    args = parser.parse_args()

    # Read prompt from stdin
    prompt = sys.stdin.read()
    _ = prompt  # consumed but not parsed

    if args.sleep:
        time.sleep(args.sleep)

    if args.behavior == "timeout":
        # Sleep forever — caller must kill us
        while True:
            time.sleep(1)

    if args.behavior == "nonzero_exit":
        _write_minimal(args.packet_dir or ".", "failed", "Worker failed intentionally",
                       changed_files=[])
        sys.exit(1)

    pdir = Path(args.packet_dir) if args.packet_dir else Path("test_packet")
    pdir.mkdir(parents=True, exist_ok=True)
    obs = pdir / "observed"
    obs.mkdir(parents=True, exist_ok=True)

    if args.behavior == "missing_evidence":
        _write_minimal(str(pdir), "completed", "I think I fixed it but didn't run tests",
                       changed_files=[])
        sys.exit(args.exit_code)

    if args.behavior == "test_failure":
        (obs / "test_output.txt").write_text(
            "============================= test session starts ================\n"
            "collected 12 items\n\n"
            "tests/test_a.py::test_ok PASSED\n"
            "tests/test_a.py::test_edge_case FAILED\n"
            "tests/test_a.py::test_timeout FAILED\n"
            "======================== 2 failed, 10 passed =====================\n",
            encoding="utf-8",
        )
        (obs / "diff.patch").write_text(
            "diff --git a/src/errors.py b/src/errors.py\n"
            "+    def __init__(self, code: str, message: str): ...\n",
            encoding="utf-8",
        )
        _write_minimal(str(pdir), "completed", "2 failed, 10 passed. Needs fixing.",
                       changed_files=["src/errors.py"])
        (pdir / "result.md").write_text(
            "## Result\n\n### Tests run\n- pytest: 2 failed, 10 passed\n",
            encoding="utf-8",
        )
        sys.exit(args.exit_code)

    if args.behavior == "protected_file":
        (obs / "test_output.txt").write_text("5 passed\n", encoding="utf-8")
        (obs / "diff.patch").write_text(
            "diff --git a/config/secrets.yaml b/config/secrets.yaml\n"
            "+api_key: sk-fake123\n",
            encoding="utf-8",
        )
        _write_minimal(str(pdir), "completed", "Updated secrets config",
                       changed_files=["src/main.py", "config/secrets.yaml"])
        (pdir / "result.md").write_text(
            "## Result\n\n### What changed\n- Updated config/secrets.yaml\n",
            encoding="utf-8",
        )
        sys.exit(args.exit_code)

    # success (default)
    (obs / "test_output.txt").write_text(
        "============================= test session starts ================\n"
        "collected 14 items\n\n"
        "................\n"
        "============================= 14 passed ==========================\n",
        encoding="utf-8",
    )
    (obs / "diff.patch").write_text(
        "diff --git a/src/utils.py b/src/utils.py\n"
        "+def helper():\n"
        "+    return True\n",
        encoding="utf-8",
    )
    _write_minimal(str(pdir), "completed", "14 passed, 0 failed. Added helper function.",
                   changed_files=["src/utils.py"])
    (pdir / "result.md").write_text(
        "## Result\n\n### What changed\n- Added helper function to src/utils.py\n"
        "### Tests run\n- pytest: 14 passed, 0 failed\n",
        encoding="utf-8",
    )
    sys.exit(args.exit_code)


def _write_minimal(packet_dir: str, status: str, summary: str, *, changed_files: list[str]) -> None:
    pdir = Path(packet_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    status_data = {
        "task_id": pdir.name,
        "status": status,
        "changed_files": changed_files,
        "summary": summary,
    }
    (pdir / "status.json").write_text(
        json.dumps(status_data, indent=2, ensure_ascii=False), encoding="utf-8",
    )


if __name__ == "__main__":
    main()
