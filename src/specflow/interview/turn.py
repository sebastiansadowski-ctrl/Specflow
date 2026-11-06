"""Tura wywiadu: odpowiedź modelu w JSON (granica model-kod) i scalanie ze stanem.

Model PROPONUJE: wyciągnięte fakty, założenia, wiadomość do użytkownika.
Kod DECYDUJE: waliduje JSON, scala sloty, liczy kompletność (slots.missing_slots).
"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from specflow.interview.slots import InterviewState, Story, slots_for

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class TurnOutput(BaseModel):
    message: str = Field(min_length=1)
    """Tekst dla użytkownika: krótkie potwierdzenie i JEDNO pytanie (albo podsumowanie)."""
    updates: dict[str, str] = Field(default_factory=dict)
    stories: list[Story] | None = None
    """Pełna aktualna lista czynności (zastępuje poprzednią), albo None = bez zmian."""
    assumptions: list[str] = Field(default_factory=list)
    clarifications: dict[str, str] = Field(default_factory=dict)
    user_wants_to_finish: bool = False


def parse_turn(text: str) -> tuple[TurnOutput | None, str | None]:
    """Ostatni blok JSON z polem "message". Zwraca (wynik, None) albo (None, błąd)."""
    candidates = _FENCED_JSON_RE.findall(text)
    if not candidates:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            candidates = [text[start : end + 1]]
    for raw in reversed(candidates):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "message" not in data:
            continue
        try:
            return TurnOutput.model_validate(data), None
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'odpowiedź'}: {e['msg']}"
                for e in exc.errors()
            )
            return None, f"zły format: {problems}"
    return None, "brak bloku JSON z polem 'message'"


def apply_turn(state: InterviewState, turn: TurnOutput) -> tuple[InterviewState, list[str]]:
    """Scala odpowiedź modelu ze stanem. Zwraca nowy stan i listę zignorowanych pól."""
    new = state.model_copy(deep=True)
    known = {slot.name for slot in slots_for(state.stage)} - {"stories"}
    ignored: list[str] = []
    for name, value in turn.updates.items():
        if name not in known:
            ignored.append(name)
        elif value.strip():
            new.answers[name] = value.strip()
    if turn.stories is not None and state.stage == "specify":
        new.stories = [s for s in turn.stories if s.title.strip()]
    for assumption in turn.assumptions:
        if assumption.strip() and assumption.strip() not in new.assumptions:
            new.assumptions.append(assumption.strip())
    if state.stage == "clarify":
        for question, answer in turn.clarifications.items():
            if question in new.open_questions and answer.strip():
                new.clarifications[question] = answer.strip()
            else:
                ignored.append(f"clarifications[{question[:40]}]")
    new.user_wants_to_finish = turn.user_wants_to_finish
    return new, ignored


def state_for_prompt(state: InterviewState) -> dict[str, Any]:
    """Zwięzły stan do promptu (model widzi, co już wiemy)."""
    data: dict[str, Any] = {"answers": state.answers, "assumptions": state.assumptions}
    if state.stage == "specify":
        data["stories"] = [s.model_dump() for s in state.stories]
    if state.stage == "clarify":
        data["open_questions"] = state.open_questions
        data["clarifications"] = state.clarifications
    return data
