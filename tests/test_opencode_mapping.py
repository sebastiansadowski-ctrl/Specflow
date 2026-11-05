from typing import Any

from specflow.harness import AgentMessage, FileChanged, ToolCall, ToolResult, Usage
from specflow.harness.opencode import OpenCodeEventMapper

SID = "ses_123"


def ev(kind: str, **data: Any) -> dict[str, Any]:
    """Koperta zdarzenia w formacie OpenCode v2.2.5."""
    return {"id": "evt_1", "type": kind, "created": 0, "data": {"sessionID": SID, **data}}


def test_tool_lifecycle_maps_to_call_result_and_file_change() -> None:
    mapper = OpenCodeEventMapper(SID)
    assert mapper.map(ev("session.tool.input.started", id="c1", name="edit")) == []
    [call] = mapper.map(ev("session.tool.called", id="c1", input={"filePath": "src/a.py"}))
    assert call == ToolCall(call_id="c1", tool="edit", summary="edit src/a.py")
    result, changed = mapper.map(ev("session.tool.success", id="c1", content=[{}]))
    assert result == ToolResult(call_id="c1", tool="edit", ok=True)
    assert changed == FileChanged(path="src/a.py")


def test_bash_call_summary_and_failure() -> None:
    mapper = OpenCodeEventMapper(SID)
    mapper.map(ev("session.tool.input.started", id="c2", name="bash"))
    [call] = mapper.map(ev("session.tool.called", id="c2", input={"command": "uv run pytest"}))
    assert isinstance(call, ToolCall) and call.summary == "bash: uv run pytest"
    [failed] = mapper.map(ev("session.tool.failed", id="c2", error={"message": "exit 1"}))
    assert failed == ToolResult(call_id="c2", tool="bash", ok=False, summary="exit 1")


def test_step_end_reports_usage_and_deduplicated_files() -> None:
    mapper = OpenCodeEventMapper(SID)
    mapper.changed_paths.add("src/a.py")
    events = mapper.map(
        ev(
            "session.step.ended",
            cost=0.012,
            tokens={"input": 1200, "output": 300, "reasoning": 0, "cache": {"read": 0, "write": 0}},
            files=["src/a.py", "src/b.py"],
        )
    )
    assert events == [
        Usage(input_tokens=1200, output_tokens=300, cost_usd=0.012),
        FileChanged(path="src/b.py"),
    ]


def test_text_and_terminal_states() -> None:
    mapper = OpenCodeEventMapper(SID)
    assert mapper.map(ev("session.text.ended", text="Gotowe")) == [AgentMessage(text="Gotowe")]
    assert mapper.last_text == "Gotowe"
    mapper.map(ev("session.execution.succeeded"))
    assert mapper.terminal == "completed"

    failing = OpenCodeEventMapper(SID)
    failing.map(ev("session.execution.failed", error={"message": "rate limit"}))
    assert failing.terminal == "failed" and failing.terminal_error == "rate limit"

    interrupted = OpenCodeEventMapper(SID)
    interrupted.map(ev("session.execution.interrupted", reason="user"))
    assert interrupted.terminal == "aborted"


def test_other_sessions_and_unknown_events_are_ignored() -> None:
    mapper = OpenCodeEventMapper(SID)
    other = {"type": "session.text.ended", "data": {"sessionID": "ses_other", "text": "x"}}
    assert mapper.map(other) == []
    assert mapper.map(ev("session.reasoning.delta", delta="hmm")) == []
    assert mapper.map({"type": "server.connected"}) == []
