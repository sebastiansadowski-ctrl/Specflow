"""Adapter OpenCode: implementacja portu `Harness` dla `opencode serve` v2.2.5."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath

from specflow.harness.base import (
    CommandPrompt,
    HarnessError,
    Prompt,
    Session,
    SessionSpec,
    TextPrompt,
)
from specflow.harness.events import AgentEvent, FileChanged, RunFinished, build_run_finished
from specflow.harness.opencode.client import OpenCodeClient
from specflow.harness.opencode.mapping import SUBSCRIBED_TYPES, OpenCodeEventMapper
from specflow.harness.permissions import rules_for


class OpenCodeHarness:
    """`host_root` (katalog projektów po stronie Specflow) jest zamontowany w kontenerze
    jako `container_root`; adapter tłumaczy ścieżki w obie strony."""

    name = "opencode"

    def __init__(
        self,
        client: OpenCodeClient,
        *,
        host_root: Path,
        container_root: str = "/workspace",
    ) -> None:
        self.client = client
        self.host_root = host_root.resolve()
        self.container_root = PurePosixPath(container_root)

    def container_path(self, workdir: Path) -> str:
        try:
            relative = workdir.resolve().relative_to(self.host_root)
        except ValueError as exc:
            raise HarnessError(f"{workdir} leży poza {self.host_root}") from exc
        return str(self.container_root / PurePosixPath(*relative.parts))

    async def start_session(self, spec: SessionSpec) -> Session:
        permissions = [rule.model_dump() for rule in rules_for(spec.profile)]
        session_id = await self.client.create_session(
            title=spec.title,
            directory=self.container_path(spec.workdir),
            permissions=permissions,
        )
        return Session(id=session_id, spec=spec)

    async def run(
        self,
        session: Session,
        prompt: Prompt,
        *,
        timeout_s: float,
        expect_report: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        mapper = OpenCodeEventMapper(session.id)
        prefix = self.container_path(session.spec.workdir).rstrip("/") + "/"
        timed_out = False

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s

        async with self.client.events(SUBSCRIBED_TYPES) as stream:
            if isinstance(prompt, TextPrompt):
                await self.client.prompt(session.id, prompt.text)
            elif isinstance(prompt, CommandPrompt):
                await self.client.command(session.id, prompt.name, prompt.arguments)
            # Limit czasu liczony na każde oczekiwanie na zdarzenie, nie przez `yield`
            # (anulowanie nie może przechodzić przez punkt zawieszenia generatora).
            while mapper.terminal is None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    envelope = await asyncio.wait_for(anext(stream), remaining)
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    timed_out = True
                    break
                for event in mapper.map(envelope):
                    if isinstance(event, FileChanged) and event.path.startswith(prefix):
                        event = FileChanged(path=event.path[len(prefix) :])
                    yield event

        if timed_out:
            await self.abort(session)
            yield RunFinished(status="timeout", error=f"Przekroczono limit {timeout_s}s.")
            return
        if mapper.terminal is None:
            yield RunFinished(
                status="failed", error="Strumień zdarzeń zakończył się przedwcześnie."
            )
            return
        yield build_run_finished(
            mapper.terminal,
            mapper.last_text,
            expect_report=expect_report,
            error=mapper.terminal_error,
        )

    async def abort(self, session: Session) -> None:
        with contextlib.suppress(HarnessError):  # sesja mogła się już zakończyć
            await self.client.interrupt(session.id)

    async def close(self, session: Session) -> None:
        await self.client.delete_session(session.id)
