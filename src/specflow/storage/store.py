"""Repozytorium projektu: import zwalidowanego planu i przejścia statusów z dziennikiem.

Każda zmiana statusu przechodzi przez maszynę stanów (kto może co zrobić) i zapisuje
zdarzenie. Po ukończeniu zadania system sam promuje zadania z Backlog do Ready.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from specflow.domain import Actor, TaskGraph, TaskStatus, transition
from specflow.domain.project_phase import ProjectPhase, advance_phase
from specflow.storage.models import (
    ChatMessageRow,
    CommandRow,
    DecisionRow,
    EventRow,
    ProjectRow,
    RunRow,
    TaskRow,
)

RUN_STATES = frozenset({"idle", "running", "paused"})
COMMAND_KINDS = frozenset({"start", "message", "approve", "answer", "pause", "resume"})
CHAT_COMMANDS = frozenset({"start", "message", "approve"})
"""Polecenia czatu: wykonują turę modelu, więc naraz może czekać tylko jedno."""


class ProjectStoreError(Exception):
    pass


class ProjectStore:
    def __init__(self, session: Session, on_commit: Callable[[], None] | None = None) -> None:
        self.session = session
        self.on_commit = on_commit
        """Wywoływane po każdym commicie - np. powiadomienie szyny zdarzeń (SSE)."""

    def commit(self) -> None:
        """Zatwierdza transakcję. Wywołujący (orkiestrator, warstwa web) decyduje kiedy."""
        self.session.commit()
        if self.on_commit is not None:
            self.on_commit()

    def projects(self) -> list[ProjectRow]:
        return list(self.session.scalars(select(ProjectRow).order_by(ProjectRow.id)))

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
        direct = graph.direct_deps()
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
                depends_on=sorted(direct[key]),
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

    def board_tasks(self, project_id: int) -> list[TaskRow]:
        """Wszystkie zadania projektu w kolejności harmonogramu."""
        return self._tasks(project_id)

    def events(
        self, project_id: int, *, after: int = 0, limit: int | None = None
    ) -> list[EventRow]:
        """Zdarzenia projektu po `after` (id) - nadrabianie strumienia SSE po Last-Event-ID."""
        query = (
            select(EventRow)
            .where(EventRow.project_id == project_id, EventRow.id > after)
            .order_by(EventRow.id)
        )
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def log(
        self,
        project_id: int,
        type_: str,
        actor: Actor | str,
        *,
        task_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Dopisuje zdarzenie do dziennika (np. krok planisty, zdarzenie agenta)."""
        self._event(project_id, type_, actor, task_key=task_key, payload=payload)

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
        if target is TaskStatus.IN_PROGRESS:
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

    # --- Awaiting input: pytania agenta, wyczerpane próby, odpowiedzi ------------

    def request_input(
        self,
        project_id: int,
        key: str,
        actor: Actor,
        *,
        reason: str,
        message: str,
    ) -> TaskRow:
        """Przenosi zadanie do Awaiting input z powodem i treścią widoczną dla użytkownika."""
        row = self.set_status(project_id, key, TaskStatus.AWAITING_INPUT, actor, reason=message)
        row.awaiting_reason = reason
        row.awaiting_message = message
        self.session.flush()
        return row

    def answer(self, project_id: int, key: str, text: str) -> TaskRow:
        """Odpowiedź (na pytanie agenta) albo wskazówka (po wyczerpaniu prób) od użytkownika.

        - pytanie: ta sama sesja dostanie odpowiedź, licznik prób bez zmian;
        - wyczerpane próby: nowa sesja, licznik prób od zera.
        Każda odpowiedź zapisuje się jako decyzja projektu.
        """
        if not text.strip():
            raise ProjectStoreError("Odpowiedź nie może być pusta.")
        row = self.get_task(project_id, key)
        if TaskStatus(row.status) is not TaskStatus.AWAITING_INPUT:
            raise ProjectStoreError(f"Zadanie {key} nie czeka na odpowiedź.")
        exhausted = row.awaiting_reason == "attempts_exhausted"
        self.session.add(
            DecisionRow(
                project_id=project_id,
                task_key=key,
                kind="hint" if exhausted else "answer",
                question=row.awaiting_message,
                text=text.strip(),
            )
        )
        row.pending_input = text.strip()
        if exhausted:
            row.attempts = 0
            row.session_id = None
        row.awaiting_reason = None
        row.awaiting_message = None
        return self.set_status(project_id, key, TaskStatus.READY, Actor.USER, reason="odpowiedź")

    def decisions(self, project_id: int) -> list[DecisionRow]:
        return list(
            self.session.scalars(
                select(DecisionRow)
                .where(DecisionRow.project_id == project_id)
                .order_by(DecisionRow.id)
            )
        )

    # --- próby (Run) -------------------------------------------------------------

    def start_run(
        self,
        project_id: int,
        key: str,
        *,
        session_id: str,
        profile: str,
        prompt_version: str,
        base_sha: str | None,
    ) -> RunRow:
        task = self.get_task(project_id, key)
        run = RunRow(
            project_id=project_id,
            task_key=key,
            attempt=task.attempts,
            session_id=session_id,
            profile=profile,
            prompt_version=prompt_version,
            base_sha=base_sha,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_run(self, run: RunRow, *, outcome: str, **fields: Any) -> RunRow:
        for name, value in fields.items():
            setattr(run, name, value)
        run.outcome = outcome
        run.finished_at = datetime.now(UTC)
        self.session.flush()
        return run

    def runs(self, project_id: int, key: str | None = None) -> list[RunRow]:
        query = select(RunRow).where(RunRow.project_id == project_id)
        if key:
            query = query.where(RunRow.task_key == key)
        return list(self.session.scalars(query.order_by(RunRow.id)))

    # --- projekt -----------------------------------------------------------------

    def get_project(self, project_id: int) -> ProjectRow:
        project = self.session.get(ProjectRow, project_id)
        if project is None:
            raise ProjectStoreError(f"Brak projektu {project_id}.")
        return project

    def pause(self, project_id: int, reason: str) -> None:
        self.get_project(project_id).paused_reason = reason
        self._event(project_id, "project_paused", Actor.SYSTEM, payload={"reason": reason})

    def resume(self, project_id: int) -> None:
        self.get_project(project_id).paused_reason = None
        self._event(project_id, "project_resumed", Actor.USER)

    def add_message(
        self, project_id: int, role: str, text: str, *, command_id: int | None = None
    ) -> ChatMessageRow:
        """Dodaje wiadomość czatu. Z `command_id` jest idempotentne: ponowne wykonanie
        polecenia po awarii zwraca istniejącą wiadomość zamiast dodawać drugą."""
        if command_id is not None:
            existing = self.session.scalars(
                select(ChatMessageRow).where(
                    ChatMessageRow.project_id == project_id,
                    ChatMessageRow.command_id == command_id,
                    ChatMessageRow.role == role,
                )
            ).first()
            if existing is not None:
                return existing
        message = ChatMessageRow(
            project_id=project_id,
            role=role,
            phase=self.get_project(project_id).phase,
            text=text,
            command_id=command_id,
        )
        self.session.add(message)
        self.session.flush()
        self._event(
            project_id,
            "chat_message",
            Actor.SYSTEM,
            payload={"message_id": message.id, "role": role, "text": text},
        )
        return message

    def messages(self, project_id: int) -> list[ChatMessageRow]:
        return list(
            self.session.scalars(
                select(ChatMessageRow)
                .where(ChatMessageRow.project_id == project_id)
                .order_by(ChatMessageRow.id)
            )
        )

    def set_run_state(self, project_id: int, state: str) -> ProjectRow:
        """Stan docelowy orkiestratora: idle / running / paused (przycisk użytkownika)."""
        if state not in RUN_STATES:
            raise ProjectStoreError(f"Nieznany stan pracy: {state}.")
        project = self.get_project(project_id)
        if project.run_state != state:
            project.run_state = state
            self._event(project_id, "run_state_changed", Actor.SYSTEM, payload={"state": state})
        return project

    # --- skrzynka poleceń (inbox) ------------------------------------------------

    def enqueue(
        self,
        project_id: int,
        kind: str,
        *,
        task_key: str | None = None,
        text: str | None = None,
    ) -> CommandRow:
        if kind not in COMMAND_KINDS:
            raise ProjectStoreError(f"Nieznane polecenie: {kind}.")
        self.get_project(project_id)
        command = CommandRow(project_id=project_id, kind=kind, task_key=task_key, text=text)
        self.session.add(command)
        self.session.flush()
        self._event(
            project_id,
            "command_queued",
            Actor.USER,
            task_key=task_key,
            payload={"command_id": command.id, "kind": kind},
        )
        return command

    def pending_commands(
        self, project_id: int, kinds: frozenset[str] | None = None
    ) -> list[CommandRow]:
        query = select(CommandRow).where(
            CommandRow.project_id == project_id, CommandRow.status == "pending"
        )
        if kinds is not None:
            query = query.where(CommandRow.kind.in_(kinds))
        return list(self.session.scalars(query.order_by(CommandRow.id)))

    def begin_command(self, command: CommandRow) -> bool:
        """Oznacza początek wykonania. Zwraca True, gdy polecenie było już zaczęte
        (poprzednie wykonanie przerwała awaria) - wtedy worker wznawia zamiast powtarzać."""
        interrupted = command.attempts > 0
        command.attempts += 1
        self.session.flush()
        return interrupted

    def finish_command(self, command: CommandRow, *, error: str | None = None) -> CommandRow:
        command.status = "failed" if error else "done"
        command.error = error
        command.processed_at = datetime.now(UTC)
        self._event(
            command.project_id,
            "command_failed" if error else "command_done",
            Actor.SYSTEM,
            task_key=command.task_key,
            payload={"command_id": command.id, "kind": command.kind, "error": error},
        )
        return command

    def set_phase(self, project_id: int, target: str) -> ProjectRow:
        """Zmiana etapu projektu przez maszynę stanów etapów (z zapisem zdarzenia)."""
        project = self.get_project(project_id)
        current = ProjectPhase(project.phase)
        advance_phase(current, ProjectPhase(target))
        project.phase = target
        self._event(
            project_id,
            "phase_changed",
            Actor.SYSTEM,
            payload={"from": current.value, "to": target},
        )
        return project

    def save_test_baseline(self, project_id: int, *, passing: set[str], known: set[str]) -> None:
        project = self.get_project(project_id)
        project.passing_tests = sorted(passing)
        project.known_tests = sorted(known)
        self.session.flush()

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
        actor: Actor | str,
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
                actor=actor.value if isinstance(actor, Actor) else actor,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value if to_status else None,
                payload=payload or {},
            )
        )
        self.session.flush()
