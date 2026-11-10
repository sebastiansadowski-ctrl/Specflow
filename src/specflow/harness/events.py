"""Nasz słownik zdarzeń agenta - niezależny od jakiegokolwiek harnessu (ADR-0002).

Adaptery tłumaczą zdarzenia swojego narzędzia na te typy (anti-corruption layer).
Reszta systemu (orkiestrator, kanban, weryfikacja) zna tylko ten słownik.
"""

import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


class AgentReport(BaseModel):
    """Raport końcowy agenta: granica model-kod (ADR-0005). Kod go waliduje, nie ufa mu."""

    status: Literal["done", "blocked"]
    summary: str = Field(min_length=1)
    question: str | None = None
    """Wymagane, gdy status = blocked: pytanie do użytkownika."""
    notes: str | None = None
    """Notatka przekazania dla zadań zależnych (np. "verify_password() jest w security.py")."""

    @model_validator(mode="after")
    def _blocked_needs_question(self) -> "AgentReport":
        if self.status == "blocked" and not (self.question and self.question.strip()):
            raise ValueError("status 'blocked' wymaga pola 'question'")
        return self


class AgentMessage(BaseModel):
    kind: Literal["message"] = "message"
    text: str


class ToolCall(BaseModel):
    kind: Literal["tool_call"] = "tool_call"
    call_id: str
    tool: str
    summary: str
    target: str | None = None
    """Czego dotyczy wywołanie: ścieżka pliku, komenda albo wzorzec (do narracji dla UI)."""


class ToolResult(BaseModel):
    kind: Literal["tool_result"] = "tool_result"
    call_id: str
    tool: str
    ok: bool
    summary: str = ""


class FileChanged(BaseModel):
    kind: Literal["file_changed"] = "file_changed"
    path: str


class Usage(BaseModel):
    kind: Literal["usage"] = "usage"
    input_tokens: int = 0
    """Tokeny wejścia bez odczytów z pamięci podręcznej (OpenCode liczy je osobno)."""
    output_tokens: int = 0
    cache_read_tokens: int = 0
    """Wejście odczytane z pamięci podręcznej modelu (np. powtarzany prompt systemowy)."""
    reasoning_tokens: int = 0
    cost_usd: float = 0.0


RunStatus = Literal["completed", "failed", "aborted", "timeout"]


class RunFinished(BaseModel):
    """Koniec pracy agenta. `completed` znaczy tylko "przestał pracować", NIE "zrobione"."""

    kind: Literal["run_finished"] = "run_finished"
    status: RunStatus
    report: AgentReport | None = None
    report_error: str | None = None
    """Dlaczego nie udało się odczytać raportu (brak bloku JSON, zły format)."""
    error: str | None = None


AgentEvent = Annotated[
    AgentMessage | ToolCall | ToolResult | FileChanged | Usage | RunFinished,
    Field(discriminator="kind"),
]


def build_run_finished(
    status: RunStatus,
    final_text: str,
    *,
    expect_report: bool,
    error: str | None = None,
) -> RunFinished:
    """Wspólne dla wszystkich adapterów: raport parsujemy tylko po normalnym zakończeniu."""
    if not expect_report or status != "completed":
        return RunFinished(status=status, error=error)
    report, report_error = parse_agent_report(final_text)
    return RunFinished(status=status, report=report, report_error=report_error, error=error)


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_agent_report(text: str) -> tuple[AgentReport | None, str | None]:
    """Szuka OSTATNIEGO bloku JSON z polem "status" w odpowiedzi agenta.

    Zwraca (raport, None) albo (None, opis błędu). Brak raportu to błąd, nie sukces.
    """
    candidates = _FENCED_JSON_RE.findall(text)
    if not candidates:
        start = text.rfind("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            candidates = [text[start : end + 1]]
    for raw in reversed(candidates):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "status" not in data:
            continue
        try:
            return AgentReport.model_validate(data), None
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'raport'}: {err['msg']}"
                for err in exc.errors()
            )
            return None, f"Raport ma zły format: {problems}"
    return None, "Brak raportu końcowego w bloku JSON z polem 'status'."
