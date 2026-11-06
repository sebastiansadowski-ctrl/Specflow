"""Silnik wywiadu: jedna tura = prompt → model (sesja bez narzędzi) → JSON → scalenie stanu.

Model prowadzi rozmowę, kod pilnuje stanu i kompletności. Przy złym formacie odpowiedzi
jedna próba naprawy w tej samej sesji; potem uprzejma prośba do użytkownika o powtórzenie,
a stan zostaje bez zmian.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from specflow.harness import (
    AgentMessage,
    AgentProfile,
    Harness,
    HarnessError,
    RunFinished,
    Session,
    SessionSpec,
    TextPrompt,
)
from specflow.interview.prompts import build_interview_prompt, build_repair_prompt
from specflow.interview.slots import InterviewState, is_complete, progress
from specflow.interview.turn import apply_turn, parse_turn

FALLBACK_MESSAGE = "Przepraszam, nie zrozumiałem do końca. Czy możesz to powiedzieć inaczej?"


class TurnResult(BaseModel):
    state: InterviewState
    message: str
    ok: bool
    """False, gdy model dwa razy nie oddał poprawnego JSON-a (stan bez zmian)."""
    complete: bool
    progress: tuple[int, int]
    ignored: list[str] = Field(default_factory=list)
    error: str | None = None


class Interviewer:
    def __init__(self, harness: Harness, *, timeout_s: float = 300) -> None:
        self.harness = harness
        self.timeout_s = timeout_s

    async def open_session(self, workdir: Path, title: str = "Specflow: wywiad") -> Session:
        return await self.harness.start_session(
            SessionSpec(title=title, workdir=workdir, profile=AgentProfile.INTERVIEWER)
        )

    async def turn(
        self, session: Session, state: InterviewState, user_message: str | None
    ) -> TurnResult:
        text = await self._ask(session, build_interview_prompt(state, user_message))
        turn, error = parse_turn(text)
        if turn is None:
            text = await self._ask(session, build_repair_prompt(error or "?"))
            turn, error = parse_turn(text)
        if turn is None:
            return TurnResult(
                state=state,
                message=FALLBACK_MESSAGE,
                ok=False,
                complete=False,
                progress=progress(state),
                error=error,
            )
        new_state, ignored = apply_turn(state, turn)
        return TurnResult(
            state=new_state,
            message=turn.message,
            ok=True,
            complete=is_complete(new_state),
            progress=progress(new_state),
            ignored=ignored,
        )

    async def _ask(self, session: Session, prompt: str) -> str:
        last_text = ""
        finished: RunFinished | None = None
        async for event in self.harness.run(
            session, TextPrompt(text=prompt), timeout_s=self.timeout_s, expect_report=False
        ):
            if isinstance(event, AgentMessage) and event.text.strip():
                last_text = event.text
            elif isinstance(event, RunFinished):
                finished = event
        if finished is None or finished.status != "completed":
            reason = finished.error if finished else "brak zakończenia"
            raise HarnessError(f"Wywiad: model nie odpowiedział ({reason}).")
        return last_text
