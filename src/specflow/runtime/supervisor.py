"""Nadzorca workerów: start z odzyskiwaniem stanu i łagodne zamykanie (ADR-0008).

Start:  dla każdego projektu uzgodnienie stanu (recovery), potem worker w tle.
Stop:   workery kończą bieżący krok (maks. `grace_s`), potem są przerywane, a przerwana
        praca przechodzi tę samą ścieżkę co po awarii (recovery). Jedna ścieżka kodu dla
        restartu planowanego i awarii = mniej przypadków do przetestowania.
"""

import asyncio
import contextlib
import logging

from specflow.runtime.recovery import recover_project
from specflow.runtime.worker import ProjectWorker, Runtime

log = logging.getLogger(__name__)


class Supervisor:
    def __init__(self, runtime: Runtime, *, grace_s: float = 20.0) -> None:
        self.rt = runtime
        self.grace_s = grace_s
        self.workers: dict[int, ProjectWorker] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}

    async def start(self) -> None:
        for project_id in self._project_ids():
            await self.recover(project_id)
            self.ensure_worker(project_id)

    def ensure_worker(self, project_id: int) -> ProjectWorker:
        task = self._tasks.get(project_id)
        if task is not None and not task.done():
            return self.workers[project_id]
        worker = ProjectWorker(project_id, self.rt)
        self.workers[project_id] = worker
        self._tasks[project_id] = asyncio.create_task(
            worker.run(), name=f"specflow-project-{project_id}"
        )
        return worker

    async def stop(self) -> None:
        for worker in self.workers.values():
            worker.stop()
        tasks = list(self._tasks.items())
        if not tasks:
            return
        _done, pending = await asyncio.wait([t for _, t in tasks], timeout=self.grace_s)
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for project_id, task in tasks:
            if task in pending:
                await self.recover(project_id)
        self._tasks.clear()
        self.workers.clear()

    async def recover(self, project_id: int) -> list[str]:
        with self.rt.sessions() as session:
            store = self.rt.store(session, project_id)
            project = store.get_project(project_id)
            keys = await recover_project(
                store, self.rt.harness, self.rt.workspace(project), project_id
            )
        if keys:
            log.info("Projekt %s: przerwane zadania wróciły do Ready: %s", project_id, keys)
        return keys

    def _project_ids(self) -> list[int]:
        with self.rt.sessions() as session:
            return [p.id for p in self.rt.store(session, 0).projects()]
