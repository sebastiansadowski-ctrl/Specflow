"""Regresja mapowania na NAGRANIU z prawdziwego OpenCode 2.2.5 (M6b, etap 0).

Nagranie: `record.py` w kontenerze lab, model openai/gpt-6.1-terra, polecenie „utwórz
hello.py”. Jeśli przyszła wersja OpenCode zmieni zdarzenia, nagrywamy je ponownie
i ten test pokaże, co trzeba poprawić w adapterze.
"""

import json
from pathlib import Path

from specflow.harness import (
    AgentMessage,
    FileChanged,
    ToolCall,
    ToolResult,
    Usage,
    build_run_finished,
)
from specflow.harness.opencode.mapping import OpenCodeEventMapper
from specflow.storage.models import EventRow
from specflow.web.narration import narrate

FIXTURE = Path(__file__).parent / "fixtures" / "opencode" / "smoke.jsonl"
SESSION = "ses_e42bbd888ffelcm5imfiupKqK0"
CALL = "call_db45041ac4074376ba2ac2b86c7b08bd"


def replay() -> tuple[OpenCodeEventMapper, list[object]]:
    mapper = OpenCodeEventMapper(SESSION)
    events: list[object] = []
    for line in FIXTURE.read_text().splitlines():
        events += mapper.map(json.loads(line))
    return mapper, events


def test_real_opencode_events_map_to_our_vocabulary() -> None:
    mapper, events = replay()
    assert events[:3] == [
        ToolCall(call_id=CALL, tool="patch", summary="patch hello.py", target="hello.py"),
        ToolResult(
            call_id=CALL, tool="patch", ok=True, summary="Success. Updated the following files:"
        ),
        FileChanged(path="hello.py"),
    ]
    assert events[3] == Usage(input_tokens=5539, output_tokens=44, cost_usd=0.0)
    assert isinstance(events[4], AgentMessage) and '"status": "done"' in events[4].text
    assert events[5] == Usage(input_tokens=99, output_tokens=38, cost_usd=0.0)
    assert mapper.terminal == "completed"


def test_real_final_message_is_a_valid_agent_report() -> None:
    mapper, _ = replay()
    finished = build_run_finished("completed", mapper.last_text, expect_report=True)
    assert finished.report is not None and finished.report_error is None
    assert finished.report.status == "done"
    assert "hello.py" in finished.report.summary


def test_real_patch_call_is_narrated_with_the_file_name() -> None:
    _, events = replay()
    call = events[0]
    assert isinstance(call, ToolCall)
    row = EventRow(
        project_id=1,
        type="agent_tool_call",
        task_key="T001",
        actor="agent",
        payload=call.model_dump(mode="json"),
    )
    narration = narrate(row)
    assert narration is not None and narration.text == "T001: zmienia plik hello.py"
