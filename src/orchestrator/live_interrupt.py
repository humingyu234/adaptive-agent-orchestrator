"""Live Interrupt utilities for runtime pause/resume/abort/inject flows."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Event, Lock
from typing import Any


class InterruptSignal(str, Enum):
    NONE = "none"
    PAUSE = "pause"
    RESUME = "resume"
    ABORT = "abort"
    INJECT = "inject"
    SKIP = "skip"
    RESTART = "restart"


class InjectCommand(str, Enum):
    MODIFY_QUERY = "modify_query"
    FORCE_COMPLETE = "force_complete"
    OVERRIDE_RESULT = "override_result"
    ADD_CONTEXT = "add_context"
    CHANGE_TARGET = "change_target"


@dataclass
class InterruptRequest:
    signal: InterruptSignal
    reason: str = ""
    command: InjectCommand | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    source: str = "human"

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class InterruptResponse:
    accepted: bool
    signal: InterruptSignal
    message: str = ""
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    applied_changes: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class InterruptLog:
    request: InterruptRequest
    response: InterruptResponse
    task_id: str
    agent_at_interrupt: str = ""
    step_at_interrupt: int = 0


class LiveInterruptController:
    def __init__(self, interrupt_file: Path | None = None) -> None:
        self._lock = Lock()
        self._pause_event = Event()
        self._resume_event = Event()
        self._resume_event.set()
        self._abort_flag = False
        self._current_signal: InterruptSignal = InterruptSignal.NONE
        self._inject_queue: list[InterruptRequest] = []
        self._interrupt_history: list[InterruptLog] = []
        self._interrupt_file = interrupt_file or (Path.cwd() / "outputs" / "interrupts" / "signal.json")

    def request(self, request: InterruptRequest) -> InterruptResponse:
        with self._lock:
            self._current_signal = request.signal

            if request.signal == InterruptSignal.PAUSE:
                self._pause_event.set()
                self._resume_event.clear()
                return InterruptResponse(True, request.signal, "Pause signal accepted")

            if request.signal == InterruptSignal.RESUME:
                self._pause_event.clear()
                self._resume_event.set()
                self._current_signal = InterruptSignal.NONE
                return InterruptResponse(True, request.signal, "Resume signal accepted")

            if request.signal == InterruptSignal.ABORT:
                self._abort_flag = True
                return InterruptResponse(True, request.signal, "Abort signal accepted")

            if request.signal == InterruptSignal.INJECT:
                self._inject_queue.append(request)
                return InterruptResponse(True, request.signal, "Inject signal queued")

            if request.signal == InterruptSignal.SKIP:
                return InterruptResponse(True, request.signal, "Skip current agent requested")

            return InterruptResponse(False, request.signal, f"Unsupported signal: {request.signal}")

    def check(self) -> InterruptSignal:
        if self._interrupt_file and self._interrupt_file.exists():
            try:
                data = json.loads(self._interrupt_file.read_text(encoding="utf-8"))
                signal_str = data.get("signal", "none")
                if signal_str != "none":
                    self._interrupt_file.unlink()
                    return InterruptSignal(signal_str)
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        with self._lock:
            return self._current_signal

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def is_aborted(self) -> bool:
        return self._abort_flag

    def wait_for_resume(self, timeout: float | None = None) -> bool:
        return self._resume_event.wait(timeout)

    def handle(self, state: dict[str, Any], agent_name: str, step: int) -> InterruptResponse:
        signal = self.check()
        if signal == InterruptSignal.NONE:
            return InterruptResponse(False, signal, "No interrupt signal")

        if signal == InterruptSignal.ABORT:
            return InterruptResponse(True, signal, "Abort requested", state_snapshot=state.copy())

        if signal == InterruptSignal.PAUSE:
            return InterruptResponse(True, signal, "Pause requested", state_snapshot=state.copy())

        if signal == InterruptSignal.INJECT:
            with self._lock:
                if not self._inject_queue:
                    return InterruptResponse(False, signal, "No queued inject request")
                request = self._inject_queue.pop(0)
            return self._apply_inject(request, state)

        if signal == InterruptSignal.SKIP:
            self._clear_signal()
            return InterruptResponse(
                True,
                signal,
                f"Skip current agent: {agent_name}",
                applied_changes=[f"skip:{agent_name}"],
            )

        return InterruptResponse(True, signal, f"Interrupt handled: {signal.value}")

    def _apply_inject(self, request: InterruptRequest, state: dict[str, Any]) -> InterruptResponse:
        command = request.command
        payload = request.payload
        applied_changes: list[str] = []

        if command == InjectCommand.MODIFY_QUERY:
            new_query = payload.get("query", "")
            if new_query:
                state["query"] = new_query
                applied_changes.append(f"query -> {new_query[:50]}")
        elif command == InjectCommand.ADD_CONTEXT:
            context_key = payload.get("key", "")
            if context_key:
                state[context_key] = payload.get("value")
                applied_changes.append(f"added context: {context_key}")
        elif command == InjectCommand.FORCE_COMPLETE:
            state["_force_complete"] = True
            applied_changes.append("force_complete flag set")
        elif command == InjectCommand.OVERRIDE_RESULT:
            field_name = payload.get("field", "")
            if field_name:
                state[field_name] = payload.get("value")
                applied_changes.append(f"overridden: {field_name}")
        elif command == InjectCommand.CHANGE_TARGET:
            new_target = payload.get("target", "")
            if new_target:
                state["_change_target"] = new_target
                applied_changes.append(f"target -> {new_target}")

        self._clear_signal()
        return InterruptResponse(
            True,
            InterruptSignal.INJECT,
            f"Inject command applied: {command}",
            state_snapshot=state.copy(),
            applied_changes=applied_changes,
        )

    def _clear_signal(self) -> None:
        with self._lock:
            self._current_signal = InterruptSignal.NONE

    def inject(self, command: InjectCommand, payload: dict[str, Any], reason: str = "") -> InterruptResponse:
        request = InterruptRequest(
            signal=InterruptSignal.INJECT,
            command=command,
            payload=payload,
            reason=reason,
            source="human",
        )
        return self.request(request)

    def pause(self, reason: str = "") -> InterruptResponse:
        return self.request(InterruptRequest(signal=InterruptSignal.PAUSE, reason=reason))

    def resume(self, reason: str = "") -> InterruptResponse:
        return self.request(InterruptRequest(signal=InterruptSignal.RESUME, reason=reason))

    def abort(self, reason: str = "") -> InterruptResponse:
        return self.request(InterruptRequest(signal=InterruptSignal.ABORT, reason=reason))

    def skip_current(self, reason: str = "") -> InterruptResponse:
        return self.request(InterruptRequest(signal=InterruptSignal.SKIP, reason=reason))

    def log_interrupt(self, request: InterruptRequest, response: InterruptResponse, task_id: str, agent_name: str, step: int) -> None:
        self._interrupt_history.append(InterruptLog(request, response, task_id, agent_name, step))

    def get_interrupt_history(self) -> list[InterruptLog]:
        return self._interrupt_history.copy()

    def write_signal_file(self, signal: InterruptSignal, payload: dict[str, Any] | None = None) -> None:
        self._interrupt_file.parent.mkdir(parents=True, exist_ok=True)
        self._interrupt_file.write_text(
            json.dumps(
                {
                    "signal": signal.value,
                    "payload": payload or {},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def format_interrupt_response(response: InterruptResponse) -> str:
    lines = [
        "Interrupt Response",
        "=" * 30,
        f"Accepted: {response.accepted}",
        f"Signal: {response.signal.value}",
        f"Message: {response.message}",
    ]
    if response.applied_changes:
        lines.append("")
        lines.append("Applied changes:")
        for change in response.applied_changes:
            lines.append(f"  - {change}")
    return "\n".join(lines)
