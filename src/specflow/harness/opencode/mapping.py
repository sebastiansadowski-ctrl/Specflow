"""Tłumaczenie zdarzeń OpenCode v2.2.5 (`GET /api/event`) na nasz słownik.

Źródło typów: `packages/protocol/openapi.json` i `packages/schema/src/session-event.ts`
w tagu v2.2.5. Koperta zdarzenia: {"id", "type", "created", "data": {"sessionID", ...}}.

Mapper jest stanowy w obrębie jednej sesji: `session.tool.called` nie niesie nazwy narzędzia,
więc zapamiętujemy ją z `session.tool.input.started`.
"""

from typing import Any

from specflow.harness.events import (
    AgentEvent,
    AgentMessage,
    FileChanged,
    RunStatus,
    ToolCall,
    ToolResult,
    Usage,
)

PINNED_VERSION = "2.2.5"

SUBSCRIBED_TYPES = [
    "session.tool.input.started",
    "session.tool.called",
    "session.tool.success",
    "session.tool.failed",
    "session.text.ended",
    "session.step.ended",
    "session.step.failed",
    "session.execution.succeeded",
    "session.execution.failed",
    "session.execution.interrupted",
    "session.idle",
]

_PATH_KEYS = ("filePath", "path", "file")
_EDIT_TOOLS = {"edit", "write", "patch", "multiedit", "apply_patch"}
_MAX_SUMMARY = 160


def _short(value: object) -> str:
    text = str(value)
    return text if len(text) <= _MAX_SUMMARY else text[: _MAX_SUMMARY - 1] + "…"


def _describe(tool: str, args: dict[str, Any]) -> str:
    target = _target(args)
    if target is None:
        return tool
    return f"{tool}: {target}" if "command" in args else f"{tool} {target}"


def _target(args: dict[str, Any]) -> str | None:
    for key in _PATH_KEYS:
        if key in args:
            return _short(args[key])
    for key in ("command", "pattern"):
        if key in args:
            return _short(args[key])
    return None


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _error_text(error: object) -> str:
    if isinstance(error, dict):
        for key in ("message", "text", "_tag", "type"):
            if key in error:
                return _short(error[key])
    return _short(error)


class OpenCodeEventMapper:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.tool_names: dict[str, str] = {}
        self.tool_inputs: dict[str, dict[str, Any]] = {}
        self.changed_paths: set[str] = set()
        self.last_text = ""
        self.terminal: RunStatus | None = None
        self.terminal_error: str | None = None

    def map(self, envelope: dict[str, Any]) -> list[AgentEvent]:
        """Zwraca zero lub więcej naszych zdarzeń. Obce sesje i nieznane typy są pomijane."""
        data = envelope.get("data")
        if not isinstance(data, dict) or data.get("sessionID") != self.session_id:
            return []
        kind = envelope.get("type")
        call_id = str(data.get("id", ""))

        match kind:
            case "session.tool.input.started":
                self.tool_names[call_id] = str(data.get("name", "tool"))
                return []
            case "session.tool.called":
                args = _as_dict(data.get("input"))
                tool = self.tool_names.get(call_id, "tool")
                self.tool_inputs[call_id] = args
                return [
                    ToolCall(
                        call_id=call_id,
                        tool=tool,
                        summary=_describe(tool, args),
                        target=_target(args),
                    )
                ]
            case "session.tool.success":
                tool = self.tool_names.get(call_id, "tool")
                events: list[AgentEvent] = [ToolResult(call_id=call_id, tool=tool, ok=True)]
                if tool in _EDIT_TOOLS:
                    args = self.tool_inputs.get(call_id, {})
                    path = next((str(args[k]) for k in _PATH_KEYS if k in args), None)
                    if path:
                        events += self._file_changed([path])
                return events
            case "session.tool.failed":
                tool = self.tool_names.get(call_id, "tool")
                return [
                    ToolResult(
                        call_id=call_id,
                        tool=tool,
                        ok=False,
                        summary=_error_text(data.get("error")),
                    )
                ]
            case "session.text.ended":
                self.last_text = str(data.get("text", ""))
                return [AgentMessage(text=self.last_text)]
            case "session.step.ended" | "session.step.failed":
                tokens = _as_dict(data.get("tokens"))
                events = [
                    Usage(
                        input_tokens=int(tokens.get("input", 0)),
                        output_tokens=int(tokens.get("output", 0)),
                        cost_usd=float(data.get("cost") or 0.0),
                    )
                ]
                files = data.get("files")
                if isinstance(files, list):
                    events += self._file_changed([str(f) for f in files])
                return events
            case "session.execution.succeeded" | "session.idle":
                self.terminal = self.terminal or "completed"
                return []
            case "session.execution.failed":
                self.terminal = "failed"
                self.terminal_error = _error_text(data.get("error"))
                return []
            case "session.execution.interrupted":
                self.terminal = "aborted"
                self.terminal_error = f"przerwano: {data.get('reason', 'unknown')}"
                return []
            case _:
                return []

    def _file_changed(self, paths: list[str]) -> list[AgentEvent]:
        fresh = [p for p in paths if p not in self.changed_paths]
        self.changed_paths.update(fresh)
        return [FileChanged(path=p) for p in fresh]
