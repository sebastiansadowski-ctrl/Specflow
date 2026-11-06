"""Wspólne dla testów runtime i API: projekt demo, polecenia, przebieg do budowy."""

import asyncio
from pathlib import Path

from specflow.bootstrap import build_runtime
from specflow.harness import demo
from specflow.harness.demo import DemoHarness
from specflow.runtime import ProjectWorker, Runtime
from specflow.settings import Settings
from specflow.storage import ProjectStore
from specflow.workspace import Workspace

# Kolejne wiadomości użytkownika w demo (treść nie ma znaczenia - odpowiedzi są nagrane).
TO_SPEC_GATE = ["Nie", "Komputer i telefon", "Lista zadań dla rodziny"]


def make_runtime(tmp_path: Path, delay: float = 0.0) -> tuple[Runtime, DemoHarness]:
    harness = DemoHarness(step_delay_s=delay)
    rt = build_runtime(Settings(data_dir=tmp_path, mock_step_delay_s=delay), harness=harness)
    return rt, harness


def new_project(rt: Runtime, name: str = "Lista zadań") -> int:
    with rt.sessions() as session:
        store = rt.store(session, 0)
        project = store.create_project(name)
        store.commit()
        demo.prepare_workspace(Workspace.create(rt.projects_dir, project.id, project.name))
        store.enqueue(project.id, "start")
        store.commit()
        return project.id


def enqueue(rt: Runtime, pid: int, kind: str, **fields: str) -> int:
    with rt.sessions() as session:
        store = rt.store(session, pid)
        command = store.enqueue(pid, kind, **fields)
        store.commit()
        return command.id


def drain(rt: Runtime, pid: int, max_steps: int = 100) -> int:
    return asyncio.run(ProjectWorker(pid, rt).drain(max_steps))


def say(rt: Runtime, pid: int, *texts: str) -> None:
    for text in texts:
        enqueue(rt, pid, "message", text=text)
        drain(rt, pid)


def approve(rt: Runtime, pid: int, max_steps: int = 100) -> None:
    enqueue(rt, pid, "approve")
    drain(rt, pid, max_steps)


def to_building(rt: Runtime, pid: int) -> None:
    """Wywiad, obie bramki i planowanie - bez uruchamiania zadań."""
    drain(rt, pid)
    say(rt, pid, *TO_SPEC_GATE)
    approve(rt, pid)
    say(rt, pid, "Tytuł jest wymagany")
    approve(rt, pid, max_steps=1)  # tylko polecenie akceptacji, bez zadań


def read(rt: Runtime, pid: int) -> ProjectStore:
    """Store na świeżej sesji (do asercji). Sesja zostaje otwarta do końca testu."""
    return rt.store(rt.sessions(), pid)
