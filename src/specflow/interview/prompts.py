"""Prompt tury wywiadu (wersjonowany, jak prompty zadań)."""

import json

from specflow.interview.slots import InterviewState, missing_slots, slots_for
from specflow.interview.turn import state_for_prompt

INTERVIEW_PROMPT_VERSION = "interview/v2"
MARKER = "[wywiad]"
"""Znacznik w każdej turze - ułatwia rozpoznanie tur wywiadu w logach i w testach."""

_RULES = """Jesteś życzliwym konsultantem, który pomaga osobie nietechnicznej opisać aplikację.
Zasady:
- mów prostym językiem, bez żargonu technicznego; zwracaj się do użytkownika po polsku;
- użytkownik może mówić swobodnie i w dowolnej kolejności - wyciągaj z jego wypowiedzi
  WSZYSTKO, co pasuje do dowolnego punktu listy, nie tylko do tego, o który pytałeś;
- zadawaj JEDNO pytanie naraz, o najważniejszą brakującą rzecz; możesz podać przykład odpowiedzi;
- NIE pytaj o technologie, języki programowania ani bazy danych - o tym decyduje Specflow;
- gdy użytkownik nie wie lub mówi "wszystko jedno", zaproponuj rozsądną wartość, wpisz ją
  i dodaj krótkie założenie do "assumptions";
- dla każdej czynności użytkownika ustal, jak poznać, że działa (konkretny, sprawdzalny wynik);
- jeśli po Twojej odpowiedzi nie będzie już brakować żadnej WYMAGANEJ informacji, NIE zadawaj
  pytania: podsumuj krótko i napisz, że zaraz pokażesz podsumowanie do akceptacji (tam
  użytkownik może poprosić o zmiany); założenia wpisz do "assumptions";
- nie witaj się ponownie, gdy rozmowa już trwa;
- jeśli użytkownik chce zakończyć, ustaw "user_wants_to_finish": true."""

_STAGE_GOALS = {
    "constitution": "Etap: ZASADY projektu. Potrzebujemy tylko dwóch informacji z listy. "
    "Pozostałe zasady (testy przed kodem, prostota) Specflow ustala sam.",
    "specify": "Etap: SPECYFIKACJA - co ma powstać i po co.",
    "clarify": "Etap: DOPRECYZOWANIE. Zadaj kolejno pytania z 'open_questions' prostym "
    "językiem; odpowiedzi wpisuj do 'clarifications' (klucz = DOKŁADNA treść pytania).",
}

_FORMAT = """Odpowiedz WYŁĄCZNIE blokiem JSON:
```json
{"message": "tekst do użytkownika (krótkie potwierdzenie + jedno pytanie)",
 "updates": {"<nazwa punktu>": "wartość"},
 "stories": [{"title": "...", "actor": "...", "action": "...", "benefit": "...",
              "acceptance": ["jak poznać, że działa"]}],
 "assumptions": ["..."],
 "clarifications": {"<dokładna treść pytania>": "odpowiedź"},
 "personal_data": {"stored": true, "kinds": ["imiona"]},
 "user_wants_to_finish": false}
```
"personal_data" podawaj tylko na etapie ZASADY, gdy już wiesz, czy aplikacja przechowuje
dane osobowe (stored: true/false) i jakie (kinds); w przeciwnym razie pomiń pole.
"stories" podawaj jako PEŁNĄ aktualną listę czynności albo pomiń pole,
jeśli nic się nie zmieniło."""


def build_interview_prompt(state: InterviewState, user_message: str | None) -> str:
    checklist = "\n".join(
        f"- {slot.name} ({'wymagane' if slot.required else 'opcjonalne'}): {slot.hint}"
        for slot in slots_for(state.stage)
    )
    parts = [MARKER, _RULES, _STAGE_GOALS[state.stage]]
    if checklist:
        parts.append(f"Lista punktów do zebrania:\n{checklist}")
    parts.append("Co już wiemy (JSON):\n" + json.dumps(state_for_prompt(state), ensure_ascii=False))
    parts.append("Brakuje jeszcze: " + (", ".join(missing_slots(state)) or "nic"))
    if user_message is None and state.stage == "constitution":
        parts.append("To początek rozmowy: przywitaj się krótko i zadaj pierwsze pytanie.")
    elif user_message is None:
        parts.append(
            "To początek nowego etapu tej samej rozmowy: bez powitania, jednym zdaniem "
            "przejdź do tematu i zadaj pierwsze pytanie."
        )
    else:
        parts.append(f"Wiadomość użytkownika:\n{user_message}")
    parts.append(_FORMAT)
    return "\n\n".join(parts)


def build_repair_prompt(error: str) -> str:
    return (
        f"{MARKER} Twoja poprzednia odpowiedź nie dała się odczytać ({error}). "
        f"Zwróć ją ponownie w wymaganym formacie.\n\n{_FORMAT}"
    )
