"""Repozytorium projektu: import zwalidowanego planu i przejścia statusów z dziennikiem.

Każda zmiana statusu przechodzi przez maszynę stanów (kto może co zrobić) i zapisuje
zdarzenie. Po ukończeniu zadania system sam promuje zadania z Backlog do Ready.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from specflow.domain import Actor, TaskGraph, TaskStatus, transition
from specflow.storage.models import EventRow, ProjectRow, TaskRow


class ProjectStoreError(Exception):
    pass


class ProjectStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- projekty i import planu -------------------------------------------------

    def create_project(self, name: str) -> ProjectRow:
        project = ProjectRow(name=name)
        self.session.add(project)
        self.session.flush()
        self._event(project.id, "project_created", Actor.SYSTEM, payload={"name": name})
        return project

    def import_plan(self, project_id: int, graph: TaskGraph) -> list[TaskRow]:
        """Zapisuje zadania z zwalidowanego grafu jako Backlog, potem wylicza Ready."""
        if self._tasks(project_id):
            raise ProjectStoreError("Projekt ma już zaimportowany plan (przeplanowanie: F01).")

        order = graph.execution_order()
        rows: list[TaskRow] = []
        for position, key in enumerate(order):
            spec = graph.tasks[key]
            row = TaskRow(
                project_id=project_id,
                key=key,
                title=spec.title,
                story=spec.story,
                parallel=spec.parallel,
                is_test=spec.is_test,
                files=list(spec.files),
                depends_on=sorted(graph.deps[key]),
                order_index=position,
                status=TaskStatus.BACKLOG.value,
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        self._event(project_id, "plan_imported", Actor.SYSTEM, payload={"tasks": len(rows)})
        self.refresh_ready(project_id)
        return rows

    # --- odczyt ------------------------------------------------------------------

    def get_task(self, project_id: int, key: str) -> TaskRow:
        row = self.session.scalar(
            select(TaskRow).where(TaskRow.project_id == project_id, TaskRow.key == key)
        )
        if row is None:
            raise ProjectStoreError(f"Brak zadania {key} w projekcie {project_id}.")
        return row

    def next_ready(self, project_id: int) -> TaskRow | None:
        return self.session.scalar(
            select(TaskRow)
            .where(TaskRow.project_id == project_id, TaskRow.status == TaskStatus.READY.value)
            .order_by(TaskRow.order_index)
            .limit(1)
        )

    def board(self, project_id: int) -> dict[TaskStatus, list[TaskRow]]:
        columns: dict[TaskStatus, list[TaskRow]] = {status: [] for status in TaskStatus}
        for row in self._tasks(project_id):
            columns[TaskStatus(row.status)].append(row)
        return columns

    def events(self, project_id: int) -> list[EventRow]:
        return list(
            self.session.scalars(
                select(EventRow).where(EventRow.project_id == project_id).order_by(EventRow.id)
            )
        )

    # --- zmiany statusu ----------------------------------------------------------

    def set_status(
        self,
        project_id: int,
        key: str,
        target: TaskStatus,
        actor: Actor,
        *,
        reason: str | None = None,
    ) -> TaskRow:
        row = self.get_task(project_id, key)
        current = TaskStatus(row.status)
        transition(current, target, actor)  # rzuca InvalidTransitionError

        row.status = target.value
        if current is TaskStatus.REWORK and target is TaskStatus.IN_PROGRESS:
            row.attempts += 1
        payload = {"reason": reason} if reason else {}
        self._event(
            project_id,
            "status_changed",
            actor,
            task_key=key,
            from_status=current,
            to_status=target,
            payload=payload,
        )
        if target is TaskStatus.DONE:
            self.refresh_ready(project_id)
        return row

    def refresh_ready(self, project_id: int) -> list[TaskRow]:
        """Backlog -> Ready dla zadań, których wszystkie zależności są Done."""
        tasks = self._tasks(project_id)
        done = {t.key for t in tasks if t.status == TaskStatus.DONE.value}
        promoted: list[TaskRow] = []
        for row in tasks:
            if row.status == TaskStatus.BACKLOG.value and set(row.depends_on) <= done:
                promoted.append(
                    self.set_status(project_id, row.key, TaskStatus.READY, Actor.SYSTEM)
                )
        return promoted

    # --- pomocnicze --------------------------------------------------------------

    def _tasks(self, project_id: int) -> list[TaskRow]:
        return list(
            self.session.scalars(
                select(TaskRow)
                .where(TaskRow.project_id == project_id)
                .order_by(TaskRow.order_index)
            )
        )

    def _event(
        self,
        project_id: int,
        type_: str,
        actor: Actor,
        *,
        task_key: str | None = None,
        from_status: TaskStatus | None = None,
        to_status: TaskStatus | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            EventRow(
                project_id=project_id,
                task_key=task_key,
                type=type_,
                actor=actor.value,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value if to_status else None,
                payload=payload or {},
            )
        )
        self.session.flush()
