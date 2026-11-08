"""Harness z podglądem zdarzeń: przekazuje wszystko dalej, a kopię daje obserwatorowi.

Używa go ProjectFlow, żeby zapisać w dzienniku zużycie tokenów wywiadu i planisty
(M6b: bez tego nie da się policzyć, ile przebieg zabiera z limitu planu modelu).
Wzorzec dekoratora, jak CommittingHarness: wywiad i planista nic o tym nie wiedzą.
"""

from collections.abc import AsyncIterator, Callable
from pathlib import Path

from specflow.harness.base import CommandResult, Harness, Prompt, Session, SessionSpec
from specflow.harness.events import AgentEvent


class ObservedHarness:
    def __init__(self, inner: Harness, observer: Callable[[AgentEvent], None]) -> None:
        self.inner = inner
        self.observer = observer
        self.name = inner.name

    async def start_session(self, spec: SessionSpec) -> Session:
        return await self.inner.start_session(spec)

    async def run(
        self,
        session: Session,
        prompt: Prompt,
        *,
        timeout_s: float,
        expect_report: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        async for event in self.inner.run(
            session, prompt, timeout_s=timeout_s, expect_report=expect_report
        ):
            self.observer(event)
            yield event

    async def run_command(self, workdir: Path, command: str, *, timeout_s: float) -> CommandResult:
        return await self.inner.run_command(workdir, command, timeout_s=timeout_s)

    async def abort(self, session: Session) -> None:
        await self.inner.abort(session)

    async def close(self, session: Session) -> None:
        await self.inner.close(session)
