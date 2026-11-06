"""Teksty składane przez KOD (ADR-0007): podsumowania na bramkach i briefy dla Spec Kit.

Podsumowanie, które akceptuje użytkownik, musi dokładnie odpowiadać temu, co zostanie
zbudowane - dlatego składa je kod z zebranych slotów i sparsowanych artefaktów,
a nie model (streszczenie modelu mogłoby coś przeinaczyć).
"""

from specflow.domain import TaskGraph
from specflow.interview.slots import InterviewState

STACK = {
    "Język": "Python 3.12",
    "Aplikacja": "FastAPI + proste strony HTML (Jinja2)",
    "Dane": "SQLite",
    "Testy": "pytest",
}
"""Stos F00 - ustalony przez Specflow (profile stosów: pomysł na później, ROADMAP)."""

DEFAULT_PRINCIPLES = [
    (
        "Test-First",
        "Każda funkcja ma testy napisane z kryteriów akceptacji, zanim powstanie kod. "
        "Testy są kontraktem: implementacja ich nie zmienia.",
    ),
    ("Simplicity", "Najprostsze rozwiązanie, które spełnia wymagania; bez zbędnych warstw."),
    (
        "Clear Errors",
        "Użytkownik zawsze dostaje zrozumiały komunikat, gdy coś pójdzie nie tak.",
    ),
]

_LANGUAGE_RULES = (
    "Language rules: write the content in Polish (the user's language), but keep ALL Spec Kit "
    "template headings in English exactly as in the template (e.g. '## User Scenarios & "
    "Testing', '### User Story 1 - ...', '## Phase 1: Setup') and keep the scenario keywords "
    "**Given**, **When**, **Then** in English."
)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- (brak)"


# --- podsumowania dla użytkownika -------------------------------------------------


def render_spec_summary(state: InterviewState) -> str:
    a = state.answers
    lines = [
        f"## {a.get('name', 'Twoja aplikacja')}",
        f"**Cel:** {a.get('goal', '-')}",
        f"**Kto korzysta:** {a.get('users', '-')}",
        "",
        "### Co będzie można zrobić",
    ]
    for n, story in enumerate(state.stories, start=1):
        who = f"{story.actor}: " if story.actor else ""
        lines.append(f"{n}. **{story.title}** - {who}{story.action}".rstrip(" -:"))
        lines += [f"   - sprawdzimy: {criterion}" for criterion in story.acceptance]
    if a.get("out_of_scope"):
        lines += ["", f"**Czego nie robimy teraz:** {a['out_of_scope']}"]
    if a.get("data"):
        lines.append(f"**Jakie dane zapamiętujemy:** {a['data']}")
    if a.get("personal_data") or a.get("devices"):
        lines += [
            "",
            f"**Dane osobowe:** {a.get('personal_data', '-')}",
            f"**Urządzenia:** {a.get('devices', '-')}",
        ]
    if state.assumptions:
        lines += ["", "### Założenia (do sprawdzenia)", _bullets(state.assumptions)]
    return "\n".join(lines)


def render_plan_summary(story_titles: list[str], graph: TaskGraph) -> str:
    phases = {t.phase_index for t in graph.tasks.values()}
    tests = sum(1 for t in graph.tasks.values() if t.is_test)
    lines = [
        "## Plan budowy",
        "**Technologia (ustala Specflow):** "
        + ", ".join(f"{k.lower()}: {v}" for k, v in STACK.items()),
        "",
        f"**Historyjki ({len(story_titles)}):**",
        _bullets(story_titles),
        "",
        f"**Zadania:** {len(graph.tasks)} w {len(phases)} fazach, w tym {tests} zadań z testami.",
        "Każda historyjka najpierw dostaje testy z kryteriów akceptacji, potem kod. "
        "Zadanie jest gotowe dopiero, gdy przejdzie automatyczną weryfikację.",
    ]
    return "\n".join(lines)


# --- briefy dla komend Spec Kit (argumenty /speckit.*) ---------------------------


def render_constitution_brief(state: InterviewState, project_name: str) -> str:
    a = state.answers
    principles = "\n".join(f"- {name}: {text}" for name, text in DEFAULT_PRINCIPLES)
    extra = [f"Personal data: {a.get('personal_data', 'unknown')}"]
    if "tak" in a.get("personal_data", "").lower() or "@" in a.get("personal_data", ""):
        extra.append(
            "Add a principle 'Personal Data Protection': passwords hashed, personal data "
            "never logged, access only for the owner."
        )
    extra.append(f"Target devices: {a.get('devices', 'computer')} (responsive web UI).")
    return "\n".join(
        [
            f"Create the constitution for project '{project_name}'.",
            "Core principles:",
            principles,
            *extra,
            "Governance: amendments require user approval; version 1.0.0.",
            _LANGUAGE_RULES,
        ]
    )


def render_spec_brief(state: InterviewState) -> str:
    a = state.answers
    stories = []
    for n, s in enumerate(state.stories, start=1):
        criteria = "; ".join(s.acceptance)
        stories.append(
            f"{n}. {s.title} (Priority: P{n}) - actor: {s.actor or a.get('users', 'user')}; "
            f"action: {s.action}; benefit: {s.benefit}; acceptance: {criteria}"
        )
    parts = [
        f"Feature: {a.get('name', 'application')}",
        f"Goal: {a.get('goal', '')}",
        f"Users: {a.get('users', '')}",
        "User stories (one '### User Story N' section each, in this order, with acceptance "
        "scenarios derived from the acceptance criteria):",
        *stories,
    ]
    if a.get("out_of_scope"):
        parts.append(f"Out of scope: {a['out_of_scope']}")
    if a.get("data"):
        parts.append(f"Data: {a['data']}")
    if state.assumptions:
        parts.append("Assumptions: " + "; ".join(state.assumptions))
    parts += [
        "Do not mention technologies. Use [NEEDS CLARIFICATION: ...] only for decisions "
        "that cannot be inferred (max 3).",
        _LANGUAGE_RULES,
    ]
    return "\n".join(parts)


def render_clarifications_prompt(feature_dir: str, clarifications: dict[str, str]) -> str:
    pairs = "\n".join(f'- "{q}" -> {a}' for q, a in clarifications.items())
    return (
        f"Update {feature_dir}/spec.md: replace every [NEEDS CLARIFICATION: ...] marker with "
        f"the user's answer below, adjusting the surrounding text. Do not change anything else.\n"
        f"{pairs}\n{_LANGUAGE_RULES}"
    )


def render_plan_brief() -> str:
    return (
        "Technical stack (fixed by the platform - do not choose another): Python 3.12, "
        "FastAPI web app serving simple HTML pages with Jinja2, SQLite storage, pytest for "
        "tests, uv for dependencies. The project skeleton already exists (created by the "
        "platform): pyproject.toml with pytest configured, application code in the app/ "
        "package, tests in tests/. Do not create or change the [tool.pytest.ini_options] "
        "section; add dependencies with `uv add`. " + _LANGUAGE_RULES
    )


def render_tasks_brief() -> str:
    return (
        "Tests are REQUIRED by the constitution (Test-First): in every user story phase put "
        "the test tasks in a '### Tests for User Story N' subsection BEFORE the implementation "
        "subsection. Every task must name the file path it changes. Do not add tasks that "
        "create pyproject.toml or configure pytest - the platform already did it. "
        + _LANGUAGE_RULES
    )
