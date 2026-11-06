"""Port: interfejs, który implementuje każdy adapter harnessu (ADR-0002)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from specflow.harness.events import AgentEvent
from specflow.harness.permissions import AgentProfile


class HarnessError(Exception):
    """Błąd komunikacji z harnessem (nie mylić z porażką zadania)."""


class SessionSpec(BaseModel):
    title: str
    workdir: Path
    """Katalog projektu po stronie Specflow (adapter tłumaczy go na ścieżkę w kontenerze)."""
    profile: AgentProfile
    model: str | None = None
    """None = domyślny model skonfigurowany w harnessie."""


class Session(BaseModel):
    id: str
    spec: SessionSpec


class TextPrompt(BaseModel):
    text: str


class CommandPrompt(BaseModel):
    """Slash-komenda harnessu, np. name="speckit.tasks"."""

    name: str
    arguments: str = ""


Prompt = TextPrompt | CommandPrompt


class CommandResult(BaseModel):
    """Wynik komendy uruchomionej w środowisku agenta BEZ udziału modelu (weryfikacja)."""

    exit_code: int | None
    """None, gdy komenda nie zakończyła się sama (timeout, zabita)."""
    output: str
    """Połączone stdout i stderr (może być przycięte)."""
    timed_out: bool = False


class Harness(Protocol):
    name: str

    async def start_session(self, spec: SessionSpec) -> Session: ...

    def run(
        self,
        session: Session,
        prompt: Prompt,
        *,
        timeout_s: float,
        expect_report: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        """Wysyła prompt i strumieniuje zdarzenia. Ostatnie zdarzenie to zawsze RunFinished.

        `expect_report`: czy oczekujemy raportu końcowego w JSON (zadania tak,
        komendy Spec Kit nie).
        """
        ...

    async def run_command(self, workdir: Path, command: str, *, timeout_s: float) -> CommandResult:
        """Deterministyczna komenda w środowisku agenta (sandbox), np. testy projektu.
        Nigdy nie uruchamiamy kodu agenta tam, gdzie działa Specflow (ADR-0006)."""
        ...

    async def abort(self, session: Session) -> None: ...

    async def close(self, session: Session) -> None: ...
