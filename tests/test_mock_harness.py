import asyncio
from pathlib import Path

from specflow.harness import (
    AgentEvent,
    AgentProfile,
    CommandPrompt,
    FileChanged,
    RunFinished,
    SessionSpec,
    TextPrompt,
    ToolCall,
    mock,
)


def run_scenario(
    harness: mock.MockHarness, workdir: Path, prompt_text: str, timeout_s: float = 5
) -> list[AgentEvent]:
    async def go() -> list[AgentEvent]:
        spec = SessionSpec(title="t", workdir=workdir, profile=AgentProfile.IMPLEMENTER)
        session = await harness.start_session(spec)
        events = [
            e async for e in harness.run(session, TextPrompt(text=prompt_text), timeout_s=timeout_s)
        ]
        await harness.close(session)
        return events

    return asyncio.run(go())


def finished(events: list[AgentEvent]) -> RunFinished:
    last = events[-1]
    assert isinstance(last, RunFinished)
    return last


def test_success_writes_files_and_reports_done(tmp_path: Path) -> None:
    harness = mock.MockHarness(
        by_match={"T010": mock.success({"src/auth.py": "def login(): ...\n"}, notes="login()")}
    )
    events = run_scenario(harness, tmp_path, "Zadanie T010: serwis logowania")
    assert (tmp_path / "src/auth.py").read_text() == "def login(): ...\n"
    assert any(isinstance(e, ToolCall) for e in events)
    assert [e.path for e in events if isinstance(e, FileChanged)] == ["src/auth.py"]
    result = finished(events)
    assert result.status == "completed"
    assert result.report is not None and result.report.notes == "login()"


def test_question_is_reported_as_blocked(tmp_path: Path) -> None:
    harness = mock.MockHarness(default=mock.asks_question("Jaki algorytm haseł?"))
    report = finished(run_scenario(harness, tmp_path, "T001")).report
    assert report is not None and report.status == "blocked"
    assert report.question == "Jaki algorytm haseł?"


def test_phantom_done_changes_nothing(tmp_path: Path) -> None:
    harness = mock.MockHarness(default=mock.phantom_done())
    events = run_scenario(harness, tmp_path, "T001")
    assert not any(isinstance(e, FileChanged) for e in events)
    report = finished(events).report
    assert report is not None and report.status == "done"  # weryfikacja musi to wyłapać (M3)


def test_missing_report_is_surfaced(tmp_path: Path) -> None:
    result = finished(run_scenario(mock.MockHarness(default=mock.no_report()), tmp_path, "T001"))
    assert result.report is None and result.report_error is not None


def test_hang_ends_with_timeout(tmp_path: Path) -> None:
    harness = mock.MockHarness(default=mock.hangs())
    result = finished(run_scenario(harness, tmp_path, "T001", timeout_s=0.05))
    assert result.status == "timeout"


def test_crash_ends_with_failure(tmp_path: Path) -> None:
    result = finished(run_scenario(mock.MockHarness(default=mock.crashes("boom")), tmp_path, "T1"))
    assert result.status == "failed" and result.error == "boom"


def test_prompts_are_recorded_for_inspection(tmp_path: Path) -> None:
    harness = mock.MockHarness()

    async def go() -> None:
        spec = SessionSpec(title="t", workdir=tmp_path, profile=AgentProfile.PLANNER)
        session = await harness.start_session(spec)
        prompt = CommandPrompt(name="speckit.tasks")
        _ = [e async for e in harness.run(session, prompt, timeout_s=1, expect_report=False)]

    asyncio.run(go())
    [(_, prompt)] = harness.prompts
    assert isinstance(prompt, CommandPrompt) and prompt.name == "speckit.tasks"
