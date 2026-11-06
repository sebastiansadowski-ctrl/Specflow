"""Tabele SQLAlchemy 2.0. Baza jest źródłem prawdy dla zadań i statusów (nie `tasks.md`)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON}  # noqa: RUF012


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    paused_reason: Mapped[str | None] = mapped_column(default=None)
    """Gdy ustawione, orkiestrator nie startuje nowych zadań (np. "agent niedostępny")."""
    passing_tests: Mapped[list[str]] = mapped_column(default=list)
    """Testy przechodzące po ostatnim udanym zadaniu - punkt odniesienia dla regresji."""
    known_tests: Mapped[list[str]] = mapped_column(default=list)
    """Wszystkie testy zebrane po ostatnim udanym zadaniu - kontrola "liczba testów nie spadła"."""

    # --- wywiad i planowanie (M4) ---
    phase: Mapped[str] = mapped_column(String(20), default="constitution")
    interview_state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Stan slotów wywiadu (InterviewState) - źródło prawdy, niezależne od historii sesji."""
    interviewer_session_id: Mapped[str | None] = mapped_column(default=None)
    planner_session_id: Mapped[str | None] = mapped_column(default=None)
    gate: Mapped[str | None] = mapped_column(String(20), default=None)
    """Otwarta bramka akceptacji: "spec" albo "plan"."""
    gate_summary: Mapped[str | None] = mapped_column(default=None)
    planning_message: Mapped[str | None] = mapped_column(default=None)
    """Planowanie utknęło (Awaiting input na poziomie projektu): co poszło nie tak."""
    feature_dir: Mapped[str | None] = mapped_column(default=None)

    tasks: Mapped[list["TaskRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="TaskRow.order_index"
    )


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    key: Mapped[str] = mapped_column(String(20))
    """Identyfikator ze Spec Kit, np. "T012"."""
    title: Mapped[str]
    story: Mapped[str | None] = mapped_column(String(20))
    parallel: Mapped[bool] = mapped_column(default=False)
    is_test: Mapped[bool] = mapped_column(default=False)
    files: Mapped[list[str]] = mapped_column(default=list)
    depends_on: Mapped[list[str]] = mapped_column(default=list)
    """Klucze zadań, które muszą być Done wcześniej (z DAG-u, po walidacji)."""
    order_index: Mapped[int]
    """Pozycja w harmonogramie (TaskGraph.execution_order)."""
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(default=0)
    """Liczba podejść agenta w bieżącym budżecie (zeruje się po wskazówce użytkownika)."""

    session_id: Mapped[str | None] = mapped_column(default=None)
    """Sesja harnessu do wznowienia (Rework, odpowiedź na pytanie)."""
    notes: Mapped[str | None] = mapped_column(default=None)
    """Notatka przekazania z raportu agenta - trafia do promptów zadań zależnych."""
    commit_sha: Mapped[str | None] = mapped_column(String(64), default=None)

    awaiting_reason: Mapped[str | None] = mapped_column(String(30), default=None)
    """"question" (pytanie agenta), "attempts_exhausted" (wyczerpane próby)."""
    awaiting_message: Mapped[str | None] = mapped_column(default=None)
    pending_input: Mapped[str | None] = mapped_column(default=None)
    """Odpowiedź lub wskazówka użytkownika czekająca na następne uruchomienie."""
    last_feedback: Mapped[str | None] = mapped_column(default=None)
    """Ostatnia informacja zwrotna z weryfikacji (historia porażek dla nowej sesji)."""

    project: Mapped[ProjectRow] = relationship(back_populates="tasks")


class RunRow(Base):
    """Jedno podejście agenta do zadania: obserwowalność, koszty, podstawa przyszłych evals."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    task_key: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int]
    session_id: Mapped[str]
    profile: Mapped[str] = mapped_column(String(20))
    prompt_version: Mapped[str] = mapped_column(String(40))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    run_status: Mapped[str | None] = mapped_column(String(20), default=None)
    """completed / failed / aborted / timeout (z RunFinished)."""
    report_status: Mapped[str | None] = mapped_column(String(20), default=None)
    """done / blocked / None (brak raportu)."""
    outcome: Mapped[str | None] = mapped_column(String(20), default=None)
    """done / rework / awaiting_input / harness_error."""
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    verification: Mapped[dict[str, Any]] = mapped_column(default=dict)
    attempt_branch: Mapped[str | None] = mapped_column(default=None)
    started_at: Mapped[datetime] = mapped_column(default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class DecisionRow(Base):
    """Decyzja projektu: odpowiedź lub wskazówka użytkownika (w F01 trafia do promptów)."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    task_key: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    """"answer" (na pytanie agenta) albo "hint" (po wyczerpaniu prób)."""
    question: Mapped[str | None] = mapped_column(default=None)
    text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_now)


class EventRow(Base):
    """Dziennik zdarzeń: historia zmian i źródło strumienia na żywo dla kanbanu."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    task_key: Mapped[str | None] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(20))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ChatMessageRow(Base):
    """Wiadomość w czacie projektu (wywiad, komunikaty systemu) - do wyświetlenia w UI."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    role: Mapped[str] = mapped_column(String(20))
    """"user", "assistant" albo "system"."""
    phase: Mapped[str] = mapped_column(String(20))
    text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_now)
