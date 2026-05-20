"""Deterministic fake Claude Code worker — writes real files, no LLM, no network.

This is the ONLY fake component in the mainline path.  It substitutes for an
external Claude Code process by writing result.md, status.json, and observed/
evidence files to the packet directory.  ControlPlane, evidence classification,
and audit reporting all use their real implementations.

Behaviour profiles:
  success          — full evidence: test_output + diff + result + status
  missing_evidence — result + status but NO observed/ files
  test_failure     — result + status + test_output (showing failures)
  protected_file   — result + status + diff (touches a protected file)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from ..worker_protocol import WorkerTaskPacket

# ---------------------------------------------------------------------------
# Behaviour profiles
# ---------------------------------------------------------------------------

BEHAVIOUR_SUCCESS = "success"
BEHAVIOUR_MISSING_EVIDENCE = "missing_evidence"
BEHAVIOUR_TEST_FAILURE = "test_failure"
BEHAVIOUR_PROTECTED_FILE = "protected_file"

_KNOWN_BEHAVIOURS = frozenset([
    BEHAVIOUR_SUCCESS,
    BEHAVIOUR_MISSING_EVIDENCE,
    BEHAVIOUR_TEST_FAILURE,
    BEHAVIOUR_PROTECTED_FILE,
])


def _pick_behaviour(packet: WorkerTaskPacket, explicit: str | None) -> str:
    """Resolve the fake worker behaviour for this packet."""
    if explicit in _KNOWN_BEHAVIOURS:
        return explicit
    # Default: detect from packet title / objective keywords
    combined = f"{packet.title} {packet.objective}".lower()
    if "missing evidence" in combined or "no evidence" in combined or "skip evidence" in combined:
        return BEHAVIOUR_MISSING_EVIDENCE
    if "protected file" in combined or "secrets" in combined or "credential" in combined:
        return BEHAVIOUR_PROTECTED_FILE
    if "fail test" in combined or "broken test" in combined or "test failure" in combined:
        return BEHAVIOUR_TEST_FAILURE
    return BEHAVIOUR_SUCCESS


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _write_result_md(packet_dir: Path, behaviour: str, task_title: str) -> Path:
    """Write result.md — the worker's natural-language summary."""
    summaries = {
        BEHAVIOUR_SUCCESS: (
            f"## Result: {task_title}\n\n"
            f"### What changed\n"
            f"- Refactored error handling in src/errors.py\n"
            f"- Updated middleware in src/middleware.py\n"
            f"- Added comprehensive tests in tests/test_errors.py\n\n"
            f"### Tests run\n"
            f"- pytest: 14 passed, 0 failed\n"
            f"- lint: no issues found\n\n"
            f"### Risks remaining\n"
            f"- Edge case handling for network timeouts needs further testing\n\n"
            f"### Follow-up\n"
            f"- Consider adding integration tests for the full middleware chain\n"
        ),
        BEHAVIOUR_MISSING_EVIDENCE: (
            f"## Result: {task_title}\n\n"
            f"I think I fixed it but didn't run the tests.\n"
            f"The changes look correct to me.\n"
        ),
        BEHAVIOUR_TEST_FAILURE: (
            f"## Result: {task_title}\n\n"
            f"### What changed\n"
            f"- Updated src/errors.py with new error types\n\n"
            f"### Tests run\n"
            f"- pytest: 2 failed, 10 passed\n"
            f"- test_edge_case: AssertionError\n"
            f"- test_timeout_handling: TimeoutError\n\n"
            f"### Risks\n"
            f"- Two tests still failing, need investigation\n"
        ),
        BEHAVIOUR_PROTECTED_FILE: (
            f"## Result: {task_title}\n\n"
            f"### What changed\n"
            f"- Updated src/main.py\n"
            f"- Updated config/secrets.yaml with new API keys\n\n"
            f"### Tests run\n"
            f"- pytest: 5 passed\n"
        ),
    }
    content = summaries.get(behaviour, summaries[BEHAVIOUR_SUCCESS])
    path = packet_dir / "result.md"
    path.write_text(content, encoding="utf-8")
    return path


def _write_status_json(packet_dir: Path, behaviour: str, task_id: str) -> Path:
    """Write status.json — machine-readable worker result."""
    status_data: dict[str, Any] = {
        "task_id": task_id,
        "status": "completed",
        "worker_kind": "fake",
    }

    if behaviour == BEHAVIOUR_SUCCESS:
        status_data["changed_files"] = [
            "src/errors.py", "src/middleware.py", "tests/test_errors.py",
        ]
        status_data["summary"] = "14 passed, 0 failed. Refactored error handling."
    elif behaviour == BEHAVIOUR_MISSING_EVIDENCE:
        status_data["changed_files"] = []
        status_data["summary"] = "I think I fixed it but didn't run tests"
    elif behaviour == BEHAVIOUR_TEST_FAILURE:
        status_data["changed_files"] = ["src/errors.py"]
        status_data["summary"] = "2 failed, 10 passed. Edge case and timeout tests failing."
    elif behaviour == BEHAVIOUR_PROTECTED_FILE:
        status_data["changed_files"] = ["src/main.py", "config/secrets.yaml"]
        status_data["summary"] = "Updated main entry point and secrets"

    path = packet_dir / "status.json"
    path.write_text(json.dumps(status_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _write_observed_evidence(packet_dir: Path, behaviour: str) -> list[Path]:
    """Write observed/ evidence files. Returns list of written paths."""
    observed_dir = packet_dir / "observed"
    observed_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if behaviour == BEHAVIOUR_MISSING_EVIDENCE:
        # Intentionally write nothing — this is the "missing evidence" scenario
        return written

    # test_output.txt
    test_outputs = {
        BEHAVIOUR_SUCCESS: (
            "============================= test session starts =============================\n"
            "collected 14 items\n\n"
            "tests/test_errors.py::test_structured_error_types PASSED              [  7%]\n"
            "tests/test_errors.py::test_error_serialization PASSED                 [ 14%]\n"
            "tests/test_errors.py::test_error_deserialization PASSED               [ 21%]\n"
            "tests/test_errors.py::test_error_inheritance PASSED                   [ 28%]\n"
            "tests/test_errors.py::test_custom_error_message PASSED                [ 35%]\n"
            "tests/test_errors.py::test_error_context_data PASSED                  [ 42%]\n"
            "tests/test_errors.py::test_middleware_error_propagation PASSED        [ 50%]\n"
            "tests/test_errors.py::test_middleware_error_logging PASSED            [ 57%]\n"
            "tests/test_errors.py::test_middleware_error_response PASSED           [ 64%]\n"
            "tests/test_errors.py::test_error_handler_registry PASSED              [ 71%]\n"
            "tests/test_errors.py::test_default_error_handler PASSED               [ 78%]\n"
            "tests/test_errors.py::test_custom_error_handler PASSED                [ 85%]\n"
            "tests/test_errors.py::test_error_handler_priority PASSED              [ 92%]\n"
            "tests/test_errors.py::test_error_handler_fallback PASSED              [100%]\n\n"
            "============================= 14 passed in 0.87s ==============================\n"
        ),
        BEHAVIOUR_TEST_FAILURE: (
            "============================= test session starts =============================\n"
            "collected 12 items\n\n"
            "tests/test_errors.py::test_structured_error_types PASSED              [  8%]\n"
            "tests/test_errors.py::test_error_serialization PASSED                 [ 16%]\n"
            "tests/test_errors.py::test_error_deserialization PASSED               [ 25%]\n"
            "tests/test_errors.py::test_error_inheritance PASSED                   [ 33%]\n"
            "tests/test_errors.py::test_custom_error_message PASSED                [ 41%]\n"
            "tests/test_errors.py::test_edge_case FAILED                           [ 50%]\n"
            "tests/test_errors.py::test_timeout_handling FAILED                    [ 58%]\n"
            "tests/test_errors.py::test_middleware_error_propagation PASSED        [ 66%]\n"
            "tests/test_errors.py::test_middleware_error_logging PASSED            [ 75%]\n"
            "tests/test_errors.py::test_middleware_error_response PASSED           [ 83%]\n"
            "tests/test_errors.py::test_error_handler_registry PASSED              [ 91%]\n"
            "tests/test_errors.py::test_default_error_handler PASSED               [100%]\n\n"
            "======================== 2 failed, 10 passed in 0.93s =========================\n"
        ),
        BEHAVIOUR_PROTECTED_FILE: (
            "============================= test session starts =============================\n"
            "collected 5 items\n\n"
            "tests/test_main.py::test_entry_point PASSED                           [ 20%]\n"
            "tests/test_main.py::test_config_loading PASSED                        [ 40%]\n"
            "tests/test_main.py::test_secrets_loading PASSED                       [ 60%]\n"
            "tests/test_main.py::test_error_handling PASSED                        [ 80%]\n"
            "tests/test_main.py::test_logging_setup PASSED                         [100%]\n\n"
            "============================= 5 passed in 0.34s ===============================\n"
        ),
    }
    if behaviour in test_outputs:
        p = observed_dir / "test_output.txt"
        p.write_text(test_outputs[behaviour], encoding="utf-8")
        written.append(p)

    # diff.patch
    diffs = {
        BEHAVIOUR_SUCCESS: (
            "diff --git a/src/errors.py b/src/errors.py\n"
            "--- a/src/errors.py\n"
            "+++ b/src/errors.py\n"
            "@@ -1,15 +1,25 @@\n"
            " from dataclasses import dataclass\n"
            " \n"
            " \n"
            "-class AppError(Exception):\n"
            "-    pass\n"
            "+class StructuredError(Exception):\n"
            "+    def __init__(self, code: str, message: str, context: dict | None = None):\n"
            "+        self.code = code\n"
            "+        self.message = message\n"
            "+        self.context = context or {}\n"
            "+        super().__init__(message)\n"
            " \n"
            " \n"
            "-class ConfigError(AppError):\n"
            "-    pass\n"
            "+class ConfigError(StructuredError):\n"
            "+    pass\n"
            " \n"
            " \n"
            "-class ValidationError(AppError):\n"
            "-    pass\n"
            "+class ValidationError(StructuredError):\n"
            "+    def __init__(self, message: str, field: str, **kwargs):\n"
            "+        super().__init__(\n"
            "+            code='VALIDATION_ERROR',\n"
            "+            message=message,\n"
            "+            context={'field': field, **kwargs},\n"
            "+        )\n"
            "diff --git a/src/middleware.py b/src/middleware.py\n"
            "@@ -10,6 +10,8 @@\n"
            " def handle_error(error: Exception) -> Response:\n"
            "-    if isinstance(error, AppError):\n"
            "-        return Response(status=500, body=str(error))\n"
            "+    if isinstance(error, StructuredError):\n"
            "+        return Response(\n"
            "+            status=500,\n"
            "+            body={'code': error.code, 'message': error.message},\n"
            "+        )\n"
            "     return Response(status=500, body='Internal error')\n"
            "diff --git a/tests/test_errors.py b/tests/test_errors.py\n"
            "new file mode 100644\n"
            "@@ -0,0 +1,42 @@\n"
            "+import pytest\n"
            "+from errors import StructuredError, ConfigError, ValidationError\n"
            "+\n"
            "+def test_structured_error_types():\n"
            "+    err = StructuredError(code='TEST', message='test')\n"
            "+    assert err.code == 'TEST'\n"
            "+    assert err.message == 'test'\n"
            "+\n"
            "+def test_error_serialization():\n"
            "+    err = StructuredError(code='E001', message='msg', context={'key': 'val'})\n"
            "+    data = {'code': err.code, 'message': err.message, 'context': err.context}\n"
            "+    assert data['code'] == 'E001'\n"
            "+    assert data['context']['key'] == 'val'\n"
            "+\n"
            "+def test_validation_error():\n"
            "+    err = ValidationError(message='Invalid input', field='email')\n"
            "+    assert err.code == 'VALIDATION_ERROR'\n"
            "+    assert err.context['field'] == 'email'\n"
        ),
        BEHAVIOUR_TEST_FAILURE: (
            "diff --git a/src/errors.py b/src/errors.py\n"
            "@@ -1,8 +1,12 @@\n"
            " class StructuredError(Exception):\n"
            "-    pass\n"
            "+    def __init__(self, code: str, message: str, context: dict | None = None):\n"
            "+        self.code = code\n"
            "+        self.message = message\n"
            "+        self.context = context or {}\n"
            "+        super().__init__(message)\n"
        ),
        BEHAVIOUR_PROTECTED_FILE: (
            "diff --git a/src/main.py b/src/main.py\n"
            "@@ -1,5 +1,8 @@\n"
            "+from pathlib import Path\n"
            " def main():\n"
            "-    pass\n"
            "+    config = load_config(Path('config/secrets.yaml'))\n"
            "+    app = create_app(config)\n"
            "+    app.run()\n"
            "diff --git a/config/secrets.yaml b/config/secrets.yaml\n"
            "new file mode 100644\n"
            "@@ -0,0 +1,3 @@\n"
            "+api_key: sk-abc123\n"
            "+database_url: postgresql://localhost/mydb\n"
            "+secret_token: xyz-789\n"
        ),
    }
    if behaviour in diffs:
        p = observed_dir / "diff.patch"
        p.write_text(diffs[behaviour], encoding="utf-8")
        written.append(p)

    return written


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_fake_worker(
    packet: WorkerTaskPacket,
    *,
    behaviour: str | None = None,
    packet_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute a fake worker, writing result/status/evidence files to disk.

    Args:
        packet: The WorkerTaskPacket describing what to do.
        behaviour: One of BEHAVIOUR_* or None to auto-detect from packet.
        packet_dir: Override the packet directory (defaults to packet.packet_root).

    Returns:
        A dict with keys: run_id, task_id, packet_dir, behaviour, result_md_path,
        status_json_path, observed_paths, changed_files, summary.
    """
    resolved_behaviour = _pick_behaviour(packet, behaviour)
    pdir = packet_dir or packet.packet_root
    pdir.mkdir(parents=True, exist_ok=True)

    result_md = _write_result_md(pdir, resolved_behaviour, packet.title or packet.objective)
    status_json = _write_status_json(pdir, resolved_behaviour, packet.task_id)
    observed = _write_observed_evidence(pdir, resolved_behaviour)

    # Load back status for return value
    status_data = json.loads(status_json.read_text(encoding="utf-8"))

    return {
        "run_id": packet.run_id,
        "task_id": packet.task_id,
        "packet_dir": str(pdir),
        "behaviour": resolved_behaviour,
        "result_md_path": str(result_md),
        "status_json_path": str(status_json),
        "observed_paths": [str(p) for p in observed],
        "changed_files": status_data.get("changed_files", []),
        "summary": status_data.get("summary", ""),
        "worker_status": status_data.get("status", "completed"),
    }
