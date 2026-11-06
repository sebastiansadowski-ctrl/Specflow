"""Sloty wywiadu: lista kontrolna PO NASZEJ STRONIE, nie formularz dla użytkownika.

Użytkownik mówi swobodnie, model w każdej turze wyciąga wszystko, co pasuje do dowolnego
slotu, a KOD liczy, czego jeszcze brakuje (ADR-0007). "Nie wiem" → wartość domyślna
zaproponowana przez model i zapisana jako założenie (widoczne na bramce akceptacji).
"""

from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal["constitution", "specify", "clarify"]


class Slot(BaseModel):
    name: str
    label: str
    """Nazwa dla użytkownika (pasek postępu, podsumowanie)."""
    hint: str
    """Opis dla modelu: czego szukać w wypowiedziach."""
    required: bool = True


CONSTITUTION_SLOTS = [
    Slot(
        name="personal_data",
        label="Dane osobowe",
        hint="Czy aplikacja przechowuje dane osobowe (e-maile, hasła, adresy)? Jakie?",
    ),
    Slot(
        name="devices",
        label="Urządzenia",
        hint="Na czym głównie będzie używana: komputer, telefon, oba?",
    ),
]

SPEC_SLOTS = [
    Slot(name="name", label="Nazwa", hint="Krótka nazwa aplikacji lub funkcji."),
    Slot(name="goal", label="Cel", hint="Jaki problem rozwiązuje, po co powstaje."),
    Slot(name="users", label="Użytkownicy", hint="Kto będzie z niej korzystał (role)."),
    Slot(
        name="stories",
        label="Główne czynności",
        hint="Co użytkownik robi w aplikacji: kto, co, po co. Dla każdej czynności: "
        "jak poznać, że działa (kryteria akceptacji).",
    ),
    Slot(
        name="out_of_scope",
        label="Czego nie robi",
        hint="Co świadomie pomijamy w tej wersji.",
        required=False,
    ),
    Slot(name="data", label="Dane", hint="Jakie informacje aplikacja zapamiętuje.", required=False),
]


class Story(BaseModel):
    title: str
    actor: str = ""
    action: str = ""
    benefit: str = ""
    acceptance: list[str] = Field(default_factory=list)
    """"Jak poznać, że działa" - z tego powstaną scenariusze Given/When/Then i testy."""


class InterviewState(BaseModel):
    stage: Stage = "constitution"
    answers: dict[str, str] = Field(default_factory=dict)
    stories: list[Story] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    """Etap clarify: pytania ze znaczników [NEEDS CLARIFICATION] w spec.md."""
    clarifications: dict[str, str] = Field(default_factory=dict)
    """Etap clarify: pytanie -> odpowiedź użytkownika."""
    user_wants_to_finish: bool = False


def slots_for(stage: Stage) -> list[Slot]:
    if stage == "constitution":
        return CONSTITUTION_SLOTS
    if stage == "specify":
        return SPEC_SLOTS
    return []


def missing_slots(state: InterviewState) -> list[str]:
    """Czego brakuje - liczone przez kod, nie przez model."""
    if state.stage == "clarify":
        return [q for q in state.open_questions if not state.clarifications.get(q, "").strip()]
    missing = []
    for slot in slots_for(state.stage):
        if not slot.required:
            continue
        if slot.name == "stories":
            if not state.stories or any(not s.acceptance for s in state.stories):
                missing.append(slot.name)
        elif not state.answers.get(slot.name, "").strip():
            missing.append(slot.name)
    return missing


def progress(state: InterviewState) -> tuple[int, int]:
    """(zebrane, wymagane) do paska postępu."""
    if state.stage == "clarify":
        total = len(state.open_questions)
    else:
        total = sum(1 for s in slots_for(state.stage) if s.required)
    return total - len(missing_slots(state)), total


def is_complete(state: InterviewState) -> bool:
    """Gotowe do podsumowania: wszystko zebrane albo użytkownik chce kończyć,
    a mamy przynajmniej jedną czynność z kryterium (bez niej nie ma czego budować)."""
    if not missing_slots(state):
        return True
    if state.user_wants_to_finish and state.stage == "specify":
        return any(s.acceptance for s in state.stories)
    return state.user_wants_to_finish and state.stage != "clarify"
