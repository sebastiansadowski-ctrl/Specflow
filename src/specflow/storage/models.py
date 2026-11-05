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

    project: Mapped[ProjectRow] = relationship(back_populates="tasks")


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
