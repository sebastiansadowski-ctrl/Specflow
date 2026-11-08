"""Worker, skrzynka poleceń i odzyskiwanie po awarii (ADR-0008) na demo Mocka."""

import asyncio
import threading
import time
from pathlib import Path

from runtime_helpers import (
    TO_SPEC_GATE,
    approve,
    drain,
    enqueue,
    make_runtime,
    new_project,
    read,
    say,
    to_building,
)
from specflow.domain import Actor, TaskStatus
from specflow.domain.project_phase import ProjectPhase as P
from specflow.harness import SessionSpec, TextPrompt
from specflow.harness.base import AgentProfile, Session
from specflow.harness.mock import MockHarness, hangs
from specflow.runtime import CommittingHarness, EventBus, Supervisor
from specflow.storage import ProjectStore
from specflow.web.sse import event_stream
from specflow.workspace import run_command

S = TaskStatus


def test_demo_runs_from_first_question_to_done(tmp_path: Path) -> None:
    rt, harness = make_runtime(tmp_path)
    pid = new_project(rt)
    drain(rt, pid)
    first = read(rt, pid).messages(pid)
    assert first[-1].role == "assistant" and "dane osobowe" in first[-1].text

    say(rt, pid, *TO_SPEC_GATE)
    assert read(rt, pid).get_project(pid).gate == "spec"
    approve(rt, pid)
    assert read(rt, pid).get_project(pid).phase == P.CLARIFY.value
    say(rt, pid, "Tytuł jest wymagany")
    assert read(rt, pid).get_project(pid).gate == "plan"
    approve(rt, pid)

    store = read(rt, pid)
    project = store.get_project(pid)
    assert project.phase == P.DONE.value and project.run_state == "idle"
    assert {t.status for t in store.board_tasks(pid)} == {S.DONE.value}
    log = run_command(["git", "log", "--format=%s"], rt.workspace(project).path)
    for key in ("T001", "T002", "T003", "T004", "T005"):
        assert f"{key}:" in log
    assert "Aplikacja jest gotowa" in store.messages(pid)[-1].text
    usage = [e.payload["role"] for e in store.events(pid) if e.type == "llm_usage"]
    assert "interviewer" in usage and "planner" in usage  # koszt wywiadu i planisty w eksporcie
    # Narracja dla UI powstaje z dziennika - bez dodatkowych wywołań modelu.
    assert not any("narrac" in str(p).lower() for _, p in harness.prompts)


def test_sse_replays_from_last_event_id_with_narration(tmp_path: Path) -> None:
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    drain(rt, pid)

    async def collect(after: int) -> list[str]:
        return [c async for c in event_stream(rt, pid, after=after, follow=False)]

    everything = asyncio.run(collect(0))
    assert everything[0].startswith("retry:")
    ids = [int(c.split("\n")[0].removeprefix("id: ")) for c in everything[1:]]
    assert ids == sorted(ids) and len(ids) >= 3
    assert any('"type": "chat_message"' in c for c in everything)

    tail = asyncio.run(collect(ids[1]))
    assert [int(c.split("\n")[0][4:]) for c in tail[1:]] == ids[2:]


def test_follow_stream_wakes_on_new_event(tmp_path: Path) -> None:
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    with rt.sessions() as session:
        last = ProjectStore(session).events(pid)[-1].id

    async def scenario() -> str:
        stream = event_stream(rt, pid, after=last, keepalive_s=5).__aiter__()
        assert (await anext(stream)).startswith("retry:")
        waiting = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0.05)
        assert not waiting.done()
        enqueue(rt, pid, "message", text="hej")  # commit → szyna → strumień czyta z bazy
        chunk = await asyncio.wait_for(waiting, timeout=2)
        await stream.aclose()  # type: ignore[attr-defined]
        return chunk

    assert '"type": "command_queued"' in asyncio.run(scenario())


def test_commands_from_ui_are_not_blocked_while_agent_works(tmp_path: Path) -> None:
    """Regresja zakleszczenia SQLite: worker nie trzyma transakcji zapisu w trakcie pracy
    agenta, więc polecenie z interfejsu zapisuje się od razu. Pauza działa po bieżącym
    zadaniu, a wznowienie dokańcza budowę."""
    rt, harness = make_runtime(tmp_path)
    pid = new_project(rt)
    to_building(rt, pid)
    harness.step_delay_s = 0.3
    supervisor = Supervisor(rt, grace_s=5)

    async def scenario() -> float:
        supervisor.ensure_worker(pid)
        await _wait_for(rt, pid, lambda s: s.get_task(pid, "T001").status == S.IN_PROGRESS)
        started = time.monotonic()
        enqueue(rt, pid, "pause")
        elapsed = time.monotonic() - started
        await _wait_for(rt, pid, lambda s: s.get_task(pid, "T001").status == S.DONE)
        await _wait_for(rt, pid, lambda s: s.get_project(pid).run_state == "paused")
        await asyncio.sleep(0.5)
        assert read(rt, pid).get_task(pid, "T002").status == S.READY  # nie wystartowało
        harness.step_delay_s = 0
        enqueue(rt, pid, "resume")
        await _wait_for(rt, pid, lambda s: s.get_project(pid).phase == P.DONE, timeout=60)
        await supervisor.stop()
        return elapsed

    assert asyncio.run(scenario()) < 1.0


def test_interrupted_task_returns_to_ready_without_using_an_attempt(tmp_path: Path) -> None:
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    to_building(rt, pid)
    with rt.sessions() as session:
        store = rt.store(session, pid)
        workspace = rt.workspace(store.get_project(pid))
        base = workspace.head()
        store.set_status(pid, "T001", S.IN_PROGRESS, Actor.ORCHESTRATOR)
        store.get_task(pid, "T001").session_id = "mock-dead"
        store.start_run(
            pid,
            "T001",
            session_id="mock-dead",
            profile="implementer",
            prompt_version="v",
            base_sha=base,
        )
        store.commit()
    (workspace.path / "half_done.py").write_text("print('w połowie')\n")

    keys = asyncio.run(Supervisor(rt).recover(pid))

    store = read(rt, pid)
    task = store.get_task(pid, "T001")
    assert keys == ["T001"] and task.status == S.READY and task.attempts == 0
    assert task.session_id is None
    assert [r.outcome for r in store.runs(pid, "T001")] == ["interrupted"]
    assert not (workspace.path / "half_done.py").exists() and workspace.head() == base
    branches = run_command(["git", "branch", "--list", "attempt/*"], workspace.path)
    assert "attempt/T001-" in branches and "interrupted" in branches
    assert store.events(pid)[-1].type == "recovery"
    drain(rt, pid)
    assert read(rt, pid).get_project(pid).phase == P.DONE.value


def test_interrupted_interview_turn_is_resumed_once(tmp_path: Path) -> None:
    rt, harness = make_runtime(tmp_path)
    pid = new_project(rt)
    drain(rt, pid)
    command_id = enqueue(rt, pid, "message", text="Nie")
    with rt.sessions() as session:  # awaria: wiadomość zapisana, odpowiedzi modelu brak
        store = rt.store(session, pid)
        command = store.pending_commands(pid)[0]
        store.begin_command(command)
        store.add_message(pid, "user", "Nie", command_id=command_id)
        store.commit()

    drain(rt, pid)

    messages = read(rt, pid).messages(pid)
    assert [m.role for m in messages] == ["assistant", "user", "assistant"]
    assert "urządzeniach" in messages[-1].text
    interview = [p for _, p in harness.prompts if isinstance(p, TextPrompt)]
    assert "Nie" in interview[-1].text  # wznowiona tura dostała wiadomość użytkownika


def test_interrupted_planning_step_is_repeated(tmp_path: Path) -> None:
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    drain(rt, pid)
    say(rt, pid, *TO_SPEC_GATE)
    command_id = enqueue(rt, pid, "approve")
    with rt.sessions() as session:  # awaria w trakcie /speckit.specify
        store = rt.store(session, pid)
        project = store.get_project(pid)
        store.begin_command(store.pending_commands(pid)[0])
        project.gate = None
        project.planning_step = "specify"
        store.add_message(pid, "user", "[zatwierdzono specyfikację]", command_id=command_id)
        store.commit()

    drain(rt, pid)

    store = read(rt, pid)
    project = store.get_project(pid)
    assert project.phase == P.CLARIFY.value and project.planning_step is None
    assert "pusty tytuł" in store.messages(pid)[-1].text
    assert [m.text for m in store.messages(pid)].count("[zatwierdzono specyfikację]") == 1


def test_command_interrupted_too_many_times_fails(tmp_path: Path) -> None:
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    with rt.sessions() as session:
        store = rt.store(session, pid)
        store.pending_commands(pid)[0].attempts = 3
        store.commit()
    drain(rt, pid)
    events = read(rt, pid).events(pid)
    assert events[-1].type == "command_failed"
    assert "zbyt wiele" in events[-1].payload["error"]


def test_invalid_command_fails_without_stopping_the_worker(tmp_path: Path) -> None:
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    enqueue(rt, pid, "answer", task_key="T001", text="odpowiedź")  # zadań jeszcze nie ma
    enqueue(rt, pid, "pause")  # pauza przed budową
    drain(rt, pid)
    store = read(rt, pid)
    failed = [e for e in store.events(pid) if e.type == "command_failed"]
    assert len(failed) == 2
    assert store.messages(pid)[0].role == "assistant"  # "start" wykonał się normalnie


def test_shutdown_interrupts_hanging_agent_and_recovers(tmp_path: Path) -> None:
    rt, harness = make_runtime(tmp_path)
    pid = new_project(rt)
    to_building(rt, pid)
    harness.by_match["Zadanie T001"] = hangs()
    supervisor = Supervisor(rt, grace_s=0.2)

    async def scenario() -> None:
        supervisor.ensure_worker(pid)
        await _wait_for(rt, pid, lambda s: s.get_task(pid, "T001").status == S.IN_PROGRESS)
        await supervisor.stop()

    asyncio.run(scenario())
    store = read(rt, pid)
    task = store.get_task(pid, "T001")
    assert task.status == S.READY and task.attempts == 0
    assert store.runs(pid, "T001")[-1].outcome == "interrupted"


def test_committing_harness_commits_before_every_agent_call() -> None:
    calls: list[str] = []
    inner = MockHarness()
    harness = CommittingHarness(inner, before_call=lambda: calls.append("commit"))
    spec = SessionSpec(title="t", workdir=Path("."), profile=AgentProfile.INTERVIEWER)

    async def scenario() -> int:
        session = await harness.start_session(spec)
        events = [e async for e in harness.run(session, TextPrompt(text="x"), timeout_s=5)]
        await harness.close(Session(id=session.id, spec=spec))
        return len(events)

    n_events = asyncio.run(scenario())
    # start_session + przed każdym zdarzeniem i przed końcem strumienia + close
    assert calls.count("commit") == 1 + n_events + 1 + 1


def test_event_bus_wakes_subscriber_from_another_thread() -> None:
    bus = EventBus()

    async def scenario() -> bool:
        with bus.subscribe(7) as signal:
            threading.Thread(target=bus.notify, args=(7,)).start()
            await asyncio.wait_for(signal.wait(), timeout=2)
            return bus.subscribers(7) == 1

    assert asyncio.run(scenario())
    assert bus.subscribers(7) == 0


async def _wait_for(rt, pid, check, timeout: float = 20.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with rt.sessions() as session:
            if check(rt.store(session, pid)):
                return
        await asyncio.sleep(0.05)
    raise AssertionError("warunek nie został spełniony w czasie")
