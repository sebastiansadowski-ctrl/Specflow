"""Szablony promptów dla agenta wykonawczego - "prompt to kod".

Zasady (ADR-0005, ADR-0006):
- mały, celowany kontekst: odnośniki do dokumentów zamiast ich treści, kryteria akceptacji
  tylko z własnej historyjki, notatki tylko od zadań, od których zadanie zależy;
- każda zmiana treści szablonu = nowa `PROMPT_VERSION` (zapisywana w każdym Run, do evals);
- rodzaj wiadomości (zadanie, Rework, odpowiedź) to pojęcie naszej domeny - harness widzi
  po prostu kolejną wiadomość w sesji.
"""

import re

from pydantic import BaseModel, Field

PROMPT_VERSION = "task-prompt/v1"

REPORT_INSTRUCTIONS = """Na samym końcu odpowiedzi zwróć raport w bloku JSON:
```json
{"status": "done", "summary": "co zrobiłeś (1-2 zdania)",
 "notes": "co powinny wiedzieć kolejne zadania (opcjonalnie)"}
```
Jeśli brakuje Ci informacji, której nie da się ustalić z kodu i dokumentów, NIE zgaduj:
zwróć {"status": "blocked", "summary": "...", "question": "konkretne pytanie do użytkownika"}."""

_STORY_HEADER_RE = re.compile(r"^(#{2,4})\s+User Story\s+(\d+)\b", re.IGNORECASE)
_ANY_HEADER_RE = re.compile(r"^(#{1,6})\s+")
_MAX_ACCEPTANCE = 1500
_MAX_NOTE = 300
_MAX_NOTES = 8


class DependencyNote(BaseModel):
    key: str
    notes: str


class TaskContext(BaseModel):
    key: str
    title: str
    story: str | None = None
    is_test: bool = False
    files: list[str] = Field(default_factory=list)
    feature_dir: str | None = None
    """Np. "specs/001-todo-login"."""
    acceptance: str | None = None
    dependency_notes: list[DependencyNote] = Field(default_factory=list)
    user_hint: str | None = None
    """Wskazówka użytkownika po wyczerpaniu prób."""
    previous_failure: str | None = None
    """Ostatnia informacja zwrotna z weryfikacji (historia porażek dla nowej sesji)."""


def extract_story_section(spec_text: str, story: str) -> str | None:
    """Wycina z `spec.md` sekcję historyjki (np. "US1" -> "### User Story 1 ...")."""
    number = story.upper().removeprefix("US")
    lines = spec_text.splitlines()
    start = level = None
    for n, line in enumerate(lines):
        match = _STORY_HEADER_RE.match(line)
        if match and match.group(2) == number:
            start, level = n, len(match.group(1))
            break
    if start is None or level is None:
        return None
    end = len(lines)
    for n in range(start + 1, len(lines)):
        header = _ANY_HEADER_RE.match(lines[n])
        if header and len(header.group(1)) <= level:
            end = n
            break
    section = "\n".join(lines[start:end]).strip()
    return section[:_MAX_ACCEPTANCE]


def build_task_prompt(ctx: TaskContext) -> str:
    role = (
        "Piszesz WYŁĄCZNIE testy dla poniższego zadania. Testy mają sprawdzać kryteria "
        "akceptacji i na razie NIE przechodzić (implementacji jeszcze nie ma), ale muszą "
        "się uruchamiać bez błędów importu i składni."
        if ctx.is_test
        else "Implementujesz poniższe zadanie. Nie zmieniaj testów ani ich konfiguracji "
        "(tests/, conftest.py, ustawienia pytest) - testy są kontraktem."
    )
    parts = [
        f"Zadanie {ctx.key}{f' [{ctx.story}]' if ctx.story else ''}: {ctx.title}",
        role,
    ]
    if ctx.files:
        parts.append("Pliki zadania: " + ", ".join(ctx.files))
    docs = [".specify/memory/constitution.md"]
    if ctx.feature_dir:
        docs = [f"{ctx.feature_dir}/spec.md", f"{ctx.feature_dir}/plan.md", *docs]
        parts.append(
            "Dokumenty (przeczytaj, jeśli potrzebujesz): "
            + ", ".join(docs)
            + f", oraz {ctx.feature_dir}/data-model.md i {ctx.feature_dir}/contracts/"
            + ", jeśli istnieją."
        )
    if ctx.acceptance:
        parts.append(f"Kryteria akceptacji historyjki:\n{ctx.acceptance}")
    notes = [n for n in ctx.dependency_notes if n.notes.strip()][-_MAX_NOTES:]
    if notes:
        parts.append(
            "Od zadań, od których zależysz:\n"
            + "\n".join(f"- {n.key}: {n.notes.strip()[:_MAX_NOTE]}" for n in notes)
        )
    if ctx.user_hint:
        parts.append(f"Wskazówka od użytkownika (ważna): {ctx.user_hint}")
    if ctx.previous_failure:
        parts.append(
            "Poprzednie podejścia do tego zadania nie przeszły weryfikacji. "
            f"Ostatni wynik:\n{ctx.previous_failure}\nNie powtarzaj tych błędów."
        )
    parts.append(
        "Zasady: zmieniaj tylko to, co potrzebne do tego zadania; możesz uruchamiać testy, "
        "żeby sprawdzić swoją pracę; o zakończeniu zadania decyduje automatyczna weryfikacja."
    )
    parts.append(REPORT_INSTRUCTIONS)
    return "\n\n".join(parts)


def build_rework_prompt(key: str, feedback: str, *, attempt: int, max_attempts: int) -> str:
    return "\n\n".join(
        [
            f"Zadanie {key}: automatyczna weryfikacja nie przeszła "
            f"(podejście {attempt} z {max_attempts}).",
            feedback,
            "Popraw tylko wskazane problemy. Nie zmieniaj testów, żeby przeszły.",
            REPORT_INSTRUCTIONS,
        ]
    )


def build_answer_prompt(key: str, question: str | None, answer: str) -> str:
    asked = f'Pytałeś: "{question}"\n' if question else ""
    return "\n\n".join(
        [
            f"Zadanie {key}: użytkownik odpowiedział na Twoje pytanie.\n{asked}Odpowiedź: {answer}",
            "Kontynuuj zadanie z uwzględnieniem tej odpowiedzi.",
            REPORT_INSTRUCTIONS,
        ]
    )
