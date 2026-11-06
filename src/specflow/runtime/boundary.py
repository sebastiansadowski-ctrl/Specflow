"""Granica transakcji przy wywołaniach agenta.

Problem: SQLite ma jedną blokadę zapisu na całą bazę. Gdyby worker zostawił otwartą
transakcję zapisu (np. po `start_run`) i czekał (`await`) 30 minut na agenta, każdy inny
zapis - np. polecenie "pauza" z interfejsu - czekałby na blokadę, a w tym samym wątku
pętli asyncio skończyłoby się to zakleszczeniem i błędem "database is locked".

Rozwiązanie: harness opakowany tak, że PRZED każdym wywołaniem agenta (i przed każdym
oczekiwaniem na kolejne zdarzenie) zatwierdzamy transakcję. Wszystkie długie `await`
w workerze to wywołania harnessu, więc jedna klasa pilnuje zasady w całym kodzie,
a orkiestrator, wywiad i planista nie muszą o niej wiedzieć.
"""

from collections.abc import AsyncIterator, Callable
from pathlib import Path

from specflow.harness import AgentEvent, CommandResult, Harness, Prompt, Session, SessionSpec


class CommittingHarness:
    def __init__(self, inner: Harness, before_call: Callable[[], None]) -> None:
        self.inner = inner
        self.before_call = before_call
        self.name = inner.name

    async def start_session(self, spec: SessionSpec) -> Session:
        self.before_call()
        return await self.inner.start_session(spec)

    async def run(
        self,
        session: Session,
        prompt: Prompt,
        *,
        timeout_s: float,
        expect_report: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        stream = self.inner.run(
            session, prompt, timeout_s=timeout_s, expect_report=expect_report
        ).__aiter__()
        while True:
            self.before_call()
            try:
                event = await anext(stream)
            except StopAsyncIteration:
                return
            yield event

    async def run_command(self, workdir: Path, command: str, *, timeout_s: float) -> CommandResult:
        self.before_call()
        return await self.inner.run_command(workdir, command, timeout_s=timeout_s)

    async def abort(self, session: Session) -> None:
        self.before_call()
        await self.inner.abort(session)

    async def close(self, session: Session) -> None:
        self.before_call()
        await self.inner.close(session)
