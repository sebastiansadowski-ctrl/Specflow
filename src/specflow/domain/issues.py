"""Ustrukturyzowane błędy i ostrzeżenia z walidacji wyjścia modelu.

Każdy problem ma stały kod, powagę, komunikat i lokalizację. Raport można zamienić na
listę uwag dla modelu (pętla naprawcza, M4) - jak komunikaty kompilatora, a nie ogólne
"spróbuj jeszcze raz".
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class IssueCode(StrEnum):
    # błędy: blokują import planu
    NO_TASKS = "NO_TASKS"
    INVALID_TASK_ID = "INVALID_TASK_ID"
    PLACEHOLDER = "PLACEHOLDER"
    DUPLICATE_TASK_ID = "DUPLICATE_TASK_ID"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"
    SELF_DEPENDENCY = "SELF_DEPENDENCY"
    CYCLE = "CYCLE"
    TESTS_AFTER_IMPLEMENTATION = "TESTS_AFTER_IMPLEMENTATION"
    # ostrzeżenia: zapisywane, praca idzie dalej
    TASK_OUTSIDE_PHASE = "TASK_OUTSIDE_PHASE"
    PRECHECKED_TASK = "PRECHECKED_TASK"
    MISSING_FILE_PATH = "MISSING_FILE_PATH"
    FILE_CONFLICT = "FILE_CONFLICT"
    EMPTY_PHASE = "EMPTY_PHASE"


class Issue(BaseModel):
    code: IssueCode
    severity: Severity
    message: str
    task_id: str | None = None
    line: int | None = None

    def to_prompt_line(self) -> str:
        where = ", ".join(
            part for part in (self.task_id, f"linia {self.line}" if self.line else None) if part
        )
        location = f" ({where})" if where else ""
        return f"[{self.severity.value.upper()}] {self.code.value}{location}: {self.message}"


class ValidationReport(BaseModel):
    issues: list[Issue] = Field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(
        self,
        code: IssueCode,
        severity: Severity,
        message: str,
        *,
        task_id: str | None = None,
        line: int | None = None,
    ) -> None:
        self.issues.append(
            Issue(code=code, severity=severity, message=message, task_id=task_id, line=line)
        )

    def extend(self, other: "ValidationReport") -> None:
        self.issues.extend(other.issues)

    def as_repair_prompt(self) -> str:
        """Lista błędów do przekazania planiście w pętli naprawczej."""
        if self.ok:
            return ""
        lines = [
            f"Plik tasks.md ma {len(self.errors)} błąd(ów), które trzeba poprawić:",
            *(f"{n}. {issue.to_prompt_line()}" for n, issue in enumerate(self.errors, 1)),
            "Popraw tylko wskazane problemy i zachowaj format Spec Kit "
            "(`- [ ] T001 [P] [US1] opis ze ścieżką pliku`).",
        ]
        return "\n".join(lines)
