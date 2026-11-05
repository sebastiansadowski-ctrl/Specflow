"""Adapter Mock: udawany agent odtwarzający zaprogramowane scenariusze.

Pozwala deterministycznie, za darmo i w CI przetestować ścieżki orkiestratora
i weryfikacji, także te złośliwe (fantomowe ukończenie, edycja testów).
Mock NIE egzekwuje profili uprawnień - symuluje agenta, który je obchodzi (np. przez bash),
żeby sprawdzić, czy kolejne warstwy obrony (weryfikacja diffu) zadziałają.
"""

import asyncio
import itertools
import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from specflow.harness.base import CommandPrompt, Prompt, Session, SessionSpec, TextPrompt
from specflow.harness.events import (
    AgentEvent,
    AgentMessage,
    FileChanged,
    RunFinished,
    ToolCall,
    ToolResult,
    Usage,
    build_run_finished,
)


class Scenario(BaseModel):
    name: str
    files: dict[str, str] = Field(default_factory=dict)
    """Pliki zapisywane w katalogu projektu: ścieżka względna -> treść."""
    report: dict[str, Any] | None = None
    """Raport końcowy (zostanie zapisany jako blok JSON w ostatniej wiadomości)."""
    final_text: str | None = None
    """Ostatnia wiadomość wprost (nadpisuje raport) - do testów złych formatów."""
    hang: bool = False
    """Agent nie kończy pracy (test limitu czasu)."""
    crash: str | None = None
    """Agent kończy się błędem harnessu."""


def success(
    files: dict[str, str], summary: str = "Zrobione.", notes: str | None = None
) -> Scenario:
    return Scenario(
        name="success",
        files=files,
        report={"status": "done", "summary": summary, "notes": notes},
    )


def broken_code(files: dict[str, str]) -> Scenario:
    """Agent twierdzi, że skończył, ale kod nie przejdzie testów."""
    return Scenario(
        name="broken_code", files=files, report={"status": "done", "summary": "Gotowe."}
    )


def asks_question(question: str) -> Scenario:
    return Scenario(
        name="asks_question",
        report={"status": "blocked", "summary": "Brakuje informacji.", "question": question},
    )


def phantom_done() -> Scenario:
    """Raportuje sukces, niczego nie zmieniając."""
    return Scenario(name="phantom_done", report={"status": "done", "summary": "Wszystko działa."})


def edits_tests(path: str, content: str) -> Scenario:
    """Zmienia plik testu (obchodząc reguły), żeby test przeszedł."""
    return Scenario(
        name="edits_tests", files={path: content}, report={"status": "done", "summary": "Gotowe."}
    )


def no_report() -> Scenario:
    return Scenario(name="no_report", final_text="Skończyłem, wszystko powinno działać.")


def hangs() -> Scenario:
    return Scenario(name="hangs", hang=True)


def crashes(error: str = "provider error") -> Scenario:
    return Scenario(name="crashes", crash=error)


class MockHarness:
    """Wybiera scenariusz po fragmencie promptu (np. identyfikatorze zadania "T010")."""

    name = "mock"

    def __init__(
        self,
        default: Scenario | None = None,
        by_match: dict[str, Scenario] | None = None,
    ) -> None:
        self.default = default or phantom_done()
        self.by_match = by_match or {}
        self.prompts: list[tuple[str, Prompt]] = []
        """Historia promptów (session_id, prompt) - do sprawdzania, co dostał agent."""
        self._ids = itertools.count(1)
        self._sessions: dict[str, Session] = {}

    async def start_session(self, spec: SessionSpec) -> Session:
        session = Session(id=f"mock-{next(self._ids)}", spec=spec)
        self._sessions[session.id] = session
        return session

    def _pick(self, prompt: Prompt) -> Scenario:
        text = (
            prompt.text if isinstance(prompt, TextPrompt) else f"/{prompt.name} {prompt.arguments}"
        )
        for fragment, scenario in self.by_match.items():
            if fragment in text:
                return scenario
        return self.default

    async def run(
        self,
        session: Session,
        prompt: Prompt,
        *,
        timeout_s: float,
        expect_report: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        self.prompts.append((session.id, prompt))
        scenario = self._pick(prompt)
        label = prompt.name if isinstance(prompt, CommandPrompt) else "zadanie"
        yield AgentMessage(text=f"[mock:{scenario.name}] Pracuję nad: {label}")

        if scenario.hang:
            try:
                await asyncio.wait_for(asyncio.Event().wait(), timeout=timeout_s)
            except TimeoutError:
                yield RunFinished(status="timeout", error=f"Przekroczono limit {timeout_s}s.")
                return

        if scenario.crash:
            yield RunFinished(status="failed", error=scenario.crash)
            return

        for n, (relative, content) in enumerate(scenario.files.items(), start=1):
            call_id = f"call-{n}"
            yield ToolCall(call_id=call_id, tool="edit", summary=f"edytuję {relative}")
            target = session.spec.workdir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            yield ToolResult(call_id=call_id, tool="edit", ok=True)
            yield FileChanged(path=relative)

        yield Usage(input_tokens=1000, output_tokens=200, cost_usd=0.0)

        final_text = scenario.final_text
        if final_text is None and scenario.report is not None:
            final_text = f"Podsumowanie:\n```json\n{json.dumps(scenario.report)}\n```"
        final_text = final_text or ""
        yield AgentMessage(text=final_text)
        yield build_run_finished("completed", final_text, expect_report=expect_report)

    async def abort(self, session: Session) -> None:
        return None

    async def close(self, session: Session) -> None:
        self._sessions.pop(session.id, None)
