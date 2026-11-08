"""Deterministyczne kontrole artefaktów Spec Kit (granica model-kod dla planowania).

Komendy /speckit.* pisze model; zanim pójdziemy dalej, kod sprawdza wynik.
Kontrole celowo są proste i czytelne - wykrywają typowe porażki: nieuzupełnione szablony,
brakujące historyjki lub scenariusze, pominięty stos, pozostawione znaczniki.
"""

import re

from pydantic import BaseModel, Field

_TEMPLATE_TOKEN_RE = re.compile(r"\[[A-Z][A-Z0-9_]{2,}\]")
"""Placeholdery szablonu konstytucji, np. [PROJECT_NAME], [PRINCIPLE_1_NAME]."""
_SPEC_PLACEHOLDER_RE = re.compile(
    r"\[(FEATURE NAME|Brief Title|initial state|action|expected outcome|DATE|###-feature-name)\]"
)
_STORY_RE = re.compile(
    r"^#{2,4}\s+User Story\s+(\d+)\s*[-:\u2013]?\s*(.*?)\s*(\(Priority.*)?$", re.M
)
_H2_RE = re.compile(r"^##\s+(?!#)", re.M)
_MARKER_RE = re.compile(r"\[NEEDS CLARIFICATION:\s*([^\]]+)\]")
_SEVERITY_ROW_RE = re.compile(r"^\|[^|\n]*\|[^|\n]*\|\s*CRITICAL\s*\|(.*)$", re.M)


class ArtifactCheck(BaseModel):
    ok: bool
    problems: list[str] = Field(default_factory=list)


_TODO_RE = re.compile(r"TODO\([A-Z_]+\)")


def check_constitution(text: str) -> ArtifactCheck:
    problems = []
    tokens = sorted(set(_TEMPLATE_TOKEN_RE.findall(text)))
    if tokens:
        problems.append(f"nieuzupełnione pola szablonu: {', '.join(tokens[:5])}")
    if "test" not in text.lower():
        problems.append("brak zasady o testach (Test-First)")
    todos = sorted(set(_TODO_RE.findall(text)))
    if todos:
        problems.append(f"zostawione znaczniki TODO: {', '.join(todos[:5])}")
    return ArtifactCheck(ok=not problems, problems=problems)


def story_titles(spec_text: str) -> list[str]:
    return [m.group(2).strip() or f"User Story {m.group(1)}" for m in _STORY_RE.finditer(spec_text)]


def clarification_markers(text: str) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in _MARKER_RE.findall(text)))


def _story_sections(spec_text: str) -> list[str]:
    """Treść każdej historyjki: do kolejnej historyjki albo nagłówka `## …` (np. Requirements)."""
    starts = [m.start() for m in _STORY_RE.finditer(spec_text)]
    sections = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(spec_text)
        next_h2 = _H2_RE.search(spec_text, start + 1, end)
        sections.append(spec_text[start : next_h2.start() if next_h2 else end])
    return sections


def check_spec(text: str, expected_stories: int) -> ArtifactCheck:
    problems = []
    titles = story_titles(text)
    if len(titles) < expected_stories:
        problems.append(
            f"specyfikacja ma {len(titles)} historyjek, a wywiad zebrał {expected_stories}"
        )
    for n, section in enumerate(_story_sections(text), start=1):
        if "**Given**" not in section:
            problems.append(f"historyjka {n} nie ma scenariuszy akceptacji (**Given** …)")
    placeholders = sorted(set(_SPEC_PLACEHOLDER_RE.findall(text)))
    if placeholders:
        problems.append(f"nieuzupełnione pola szablonu: {', '.join(placeholders)}")
    return ArtifactCheck(ok=not problems, problems=problems)


def check_plan(text: str) -> ArtifactCheck:
    problems = []
    lowered = text.lower()
    for required in ("python", "fastapi", "sqlite", "pytest"):
        if required not in lowered:
            problems.append(f"plan nie używa ustalonego stosu: brak '{required}'")
    if clarification_markers(text) or "NEEDS CLARIFICATION" in text:
        problems.append("plan zawiera nierozstrzygnięte 'NEEDS CLARIFICATION'")
    return ArtifactCheck(ok=not problems, problems=problems)


def critical_findings(analyze_output: str) -> list[str]:
    """Wiersze tabeli raportu /speckit.analyze z powagą CRITICAL."""
    return [row.strip(" |") for row in _SEVERITY_ROW_RE.findall(analyze_output)]
