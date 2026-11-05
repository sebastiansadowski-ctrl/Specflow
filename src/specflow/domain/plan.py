"""Model planu sparsowanego z `tasks.md` (jeszcze bez zależności niejawnych)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class PhaseKind(StrEnum):
    SETUP = "setup"
    FOUNDATIONAL = "foundational"
    STORY = "story"
    POLISH = "polish"
    OTHER = "other"


class PhaseSpec(BaseModel):
    index: int
    """Kolejność fazy w pliku (0, 1, 2, ...), niezależnie od numeru w nagłówku."""
    title: str
    kind: PhaseKind
    story: str | None = None
    """Np. "US1" dla fazy historyjki użytkownika."""
    priority: int | None = None
    """Np. 1 dla "(Priority: P1)"."""
    line: int


class TaskSpec(BaseModel):
    id: str
    title: str
    phase_index: int | None
    section_index: int = 0
    """Numer podsekcji (`###`) w fazie; podsekcja działa jak bariera."""
    story: str | None = None
    parallel: bool = False
    files: list[str] = Field(default_factory=list)
    explicit_deps: list[str] = Field(default_factory=list)
    prechecked: bool = False
    """Checkbox `[X]` w pliku. Nie jest źródłem statusu - tylko sygnałem do ostrzeżenia."""
    is_test: bool = False
    line: int


class TaskPlan(BaseModel):
    phases: list[PhaseSpec] = Field(default_factory=list)
    tasks: list[TaskSpec] = Field(default_factory=list)

    def phase(self, index: int) -> PhaseSpec:
        return self.phases[index]
