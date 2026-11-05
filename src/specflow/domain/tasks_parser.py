"""Tolerancyjny parser `tasks.md` w formacie Spec Kit.

Format zadania: `- [ ] T012 [P] [US1] Opis ze ścieżką pliku (depends on T010, T011)`.
Parser nie ufa treści: wyłapuje placeholdery i niepoprawne identyfikatory, a stan
checkboxa traktuje wyłącznie jako sygnał ostrzegawczy (status żyje w bazie Specflow).
"""

import re

from specflow.domain.issues import IssueCode, Severity, ValidationReport
from specflow.domain.plan import PhaseKind, PhaseSpec, TaskPlan, TaskSpec

_PHASE_RE = re.compile(r"^##\s+Phase\s+(\S+?)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_H2_RE = re.compile(r"^##\s+")
_H3_RE = re.compile(r"^###\s+")
_TASK_RE = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s+(\S+)\s*(.*)$")
_TASK_ID_RE = re.compile(r"^T\d{3,}$")
_MARKER_RE = re.compile(r"^\[(P|US\d+)\]\s*", re.IGNORECASE)
_STORY_RE = re.compile(r"User\s+Story\s+(\d+)", re.IGNORECASE)
_PRIORITY_RE = re.compile(r"Priority:\s*P(\d+)", re.IGNORECASE)
_DEPENDS_RE = re.compile(r"depends\s+on\s+((?:T\d{3,}[\s,]*(?:and\s+)?)+)", re.IGNORECASE)
_TASK_REF_RE = re.compile(r"T\d{3,}")
# Ścieżka z katalogiem (src/a/b.py) albo sam plik ze znanym rozszerzeniem (pyproject.toml).
_KNOWN_EXT = r"py|pyi|toml|md|json|ya?ml|cfg|ini|txt|sql|html|css|js|ts|tsx|jsx|sh|env|lock"
_PATH_RE = re.compile(
    rf"(?<![\w/:.])((?:[\w.-]+/)+[\w.\[\]-]*\.[A-Za-z0-9]+|[\w-][\w.-]*\.(?:{_KNOWN_EXT}))(?![\w/])"
)
_PLACEHOLDER_RE = re.compile(r"\[[A-Za-z][^\]]*\]")
_TEST_WORD_RE = re.compile(r"\btests?\b", re.IGNORECASE)


def _phase_kind(title: str) -> PhaseKind:
    lowered = title.lower()
    if _STORY_RE.search(title):
        return PhaseKind.STORY
    if "setup" in lowered:
        return PhaseKind.SETUP
    if "foundational" in lowered:
        return PhaseKind.FOUNDATIONAL
    if "polish" in lowered or "cross-cutting" in lowered:
        return PhaseKind.POLISH
    return PhaseKind.OTHER


def _is_test_task(description: str, files: list[str]) -> bool:
    if any(re.search(r"(^|/)tests?(/|$)|(^|/)test_[^/]*$", f) for f in files):
        return True
    return bool(_TEST_WORD_RE.search(description))


def parse_tasks_md(text: str) -> tuple[TaskPlan, ValidationReport]:
    plan = TaskPlan()
    report = ValidationReport()
    current_phase: int | None = None
    section_index = 0
    in_comment = False
    in_fence = False

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()

        # Pomijamy bloki kodu i komentarze HTML (instrukcje szablonu, przykłady).
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            in_comment = "-->" not in stripped
            continue

        phase_match = _PHASE_RE.match(stripped)
        if phase_match:
            number, title = phase_match.groups()
            if not number.isdigit():
                report.add(
                    IssueCode.PLACEHOLDER,
                    Severity.ERROR,
                    f"Nagłówek fazy ma placeholder zamiast numeru: 'Phase {number}'.",
                    line=line_no,
                )
            story_match = _STORY_RE.search(title)
            priority_match = _PRIORITY_RE.search(title)
            kind = _phase_kind(title)
            if kind is PhaseKind.STORY and _PLACEHOLDER_RE.search(title):
                report.add(
                    IssueCode.PLACEHOLDER,
                    Severity.ERROR,
                    f"Tytuł fazy zawiera placeholder: '{title}'.",
                    line=line_no,
                )
            plan.phases.append(
                PhaseSpec(
                    index=len(plan.phases),
                    title=title,
                    kind=kind,
                    story=f"US{story_match.group(1)}" if story_match else None,
                    priority=int(priority_match.group(1)) if priority_match else None,
                    line=line_no,
                )
            )
            current_phase = len(plan.phases) - 1
            section_index = 0
            continue

        if _H2_RE.match(stripped):
            # Inna sekcja (np. "Dependencies & Execution Order") - wychodzimy z fazy.
            current_phase = None
            continue

        if _H3_RE.match(stripped):
            if current_phase is not None:
                section_index += 1
            continue

        task_match = _TASK_RE.match(line)
        if not task_match:
            continue

        check, task_id, rest = task_match.groups()

        if current_phase is None:
            report.add(
                IssueCode.TASK_OUTSIDE_PHASE,
                Severity.WARNING,
                "Zadanie poza sekcją '## Phase N: ...' zostało pominięte.",
                task_id=task_id,
                line=line_no,
            )
            continue

        if not _TASK_ID_RE.match(task_id):
            is_placeholder = "X" in task_id.upper()[1:]
            code = IssueCode.PLACEHOLDER if is_placeholder else IssueCode.INVALID_TASK_ID
            report.add(
                code,
                Severity.ERROR,
                f"Niepoprawny identyfikator zadania '{task_id}' (oczekiwany format T001).",
                task_id=task_id,
                line=line_no,
            )
            continue

        parallel = False
        story: str | None = None
        while marker := _MARKER_RE.match(rest):
            value = marker.group(1).upper()
            if value == "P":
                parallel = True
            else:
                story = value
            rest = rest[marker.end() :]

        description = rest.strip()
        explicit_deps: list[str] = []
        for dep_match in _DEPENDS_RE.finditer(description):
            explicit_deps.extend(_TASK_REF_RE.findall(dep_match.group(1)))

        files = list(dict.fromkeys(_PATH_RE.findall(description)))
        description_without_files = description
        for path in files:
            description_without_files = description_without_files.replace(path, "")

        placeholder = _PLACEHOLDER_RE.search(description)
        if placeholder:
            report.add(
                IssueCode.PLACEHOLDER,
                Severity.ERROR,
                f"Opis zawiera placeholder z szablonu: '{placeholder.group(0)}'.",
                task_id=task_id,
                line=line_no,
            )

        if check.lower() == "x":
            report.add(
                IssueCode.PRECHECKED_TASK,
                Severity.WARNING,
                "Zadanie jest odhaczone w pliku. Status pochodzi z bazy Specflow, "
                "więc znacznik zostaje zignorowany.",
                task_id=task_id,
                line=line_no,
            )

        if not files:
            report.add(
                IssueCode.MISSING_FILE_PATH,
                Severity.WARNING,
                "Opis nie wskazuje ścieżki pliku; trudniej wykryć konflikty i ocenić zakres.",
                task_id=task_id,
                line=line_no,
            )

        plan.tasks.append(
            TaskSpec(
                id=task_id,
                title=description,
                phase_index=current_phase,
                section_index=section_index,
                story=story,
                parallel=parallel,
                files=files,
                explicit_deps=list(dict.fromkeys(explicit_deps)),
                prechecked=check.lower() == "x",
                is_test=_is_test_task(description_without_files, files),
                line=line_no,
            )
        )

    return plan, report
