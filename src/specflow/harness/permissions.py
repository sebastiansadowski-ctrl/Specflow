"""Profile uprawnień agentów w neutralnym formacie (ADR-0005).

Bez `ask`: w trybie bez człowieka nikt nie odpowie, więc reguły są wyłącznie
`allow`/`deny`. Twardą granicą jest kontener; te reguły to porządek, nie kontrola dostępu.
Kolejność ma znaczenie: wygrywa OSTATNIA pasująca reguła.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class AgentProfile(StrEnum):
    IMPLEMENTER = "implementer"
    """Agent wykonawczy: pisze kod, nie rusza testów."""
    TEST_WRITER = "test_writer"
    """Pisze wyłącznie testy (zadania testowe przed implementacją)."""
    PLANNER = "planner"
    """Uruchamia komendy Spec Kit; zapisuje tylko artefakty w specs/ i .specify/."""
    INTERVIEWER = "interviewer"
    """Czysta rozmowa: bez żadnych narzędzi."""


class PermissionRule(BaseModel):
    action: str
    """Narzędzie lub strażnik: edit, bash, read, webfetch, doom_loop, external_directory, *."""
    resource: str
    """Wzorzec ścieżki albo komendy, np. "tests/**", "git push*"."""
    effect: Literal["allow", "deny"]


TEST_PATHS = ["tests/**", "**/tests/**", "**/test_*.py", "**/*_test.py", "**/*.test.*"]

_SAFETY: list[tuple[str, str]] = [
    ("bash", "git push*"),
    ("bash", "git remote*"),
    ("bash", "sudo *"),
    ("bash", "rm -rf /*"),
    ("doom_loop", "*"),
    ("external_directory", "*"),
    ("read", "*.env"),
    ("read", "*.env.*"),
]


def _rules(*items: tuple[str, str, Literal["allow", "deny"]]) -> list[PermissionRule]:
    return [PermissionRule(action=a, resource=r, effect=e) for a, r, e in items]


def rules_for(profile: AgentProfile) -> list[PermissionRule]:
    if profile is AgentProfile.INTERVIEWER:
        return _rules(("*", "*", "deny"))

    base = _rules(("*", "*", "allow"))
    if profile is AgentProfile.IMPLEMENTER:
        base += _rules(*((("edit", path, "deny")) for path in TEST_PATHS))
    elif profile is AgentProfile.TEST_WRITER:
        base += _rules(("edit", "*", "deny"), *(("edit", path, "allow") for path in TEST_PATHS))
    elif profile is AgentProfile.PLANNER:
        base += _rules(
            ("edit", "*", "deny"), ("edit", "specs/**", "allow"), ("edit", ".specify/**", "allow")
        )
    # Zakazy bezpieczeństwa na końcu: wygrywa ostatnia pasująca reguła.
    return base + _rules(*((action, resource, "deny") for action, resource in _SAFETY))
