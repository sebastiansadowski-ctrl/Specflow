"""Widoki HTML (htmx): lista projektów i ekran projektu zależny od etapu (M5b).

Układ:
- wywiad i planowanie (E1-E2): szeroki czat + podgląd artefaktów, bramki jako karty w czacie;
- budowa (E3-E4): kanban na pierwszym planie, czat zwinięty z boku, pasek logu pod tablicą,
  szczegóły zadania (pełny log, odpowiedź na pytanie agenta) po kliknięciu karty.

Fragmenty (partiale) odświeża `static/app.js` po zdarzeniach SSE. Formularze wysyłają
polecenia przez `web.commands.submit` - te same sprawdzenia co API.

Bezpieczeństwo: szablony escapują wszystko; HTML z Markdownu wstawia tylko filtr `md`
(bezpieczny renderer), więc w szablonach nigdy nie ma `|safe`. Bez stylów i skryptów
inline - wymaga tego CSP.
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from specflow import __version__
from specflow.domain import KANBAN_COLUMNS, TaskStatus
from specflow.domain.project_phase import PHASE_LABELS, ProjectPhase
from specflow.interview import InterviewState
from specflow.interview.slots import progress
from specflow.runtime import Runtime
from specflow.storage import CHAT_COMMANDS, EventRow, ProjectRow, ProjectStore, ProjectStoreError
from specflow.web.artifacts import ArtifactError, list_artifacts, read_artifact
from specflow.web.commands import ProjectCreationError, create_project, submit
from specflow.web.markdown import render_markdown
from specflow.web.narration import PLANNING_STEPS, narrate

P = ProjectPhase
S = TaskStatus
WEB_DIR = Path(__file__).parent
BUILD_PHASES = (P.BUILDING, P.DONE)
STAGES = [P.CONSTITUTION, P.SPECIFY, P.CLARIFY, P.PLAN, P.TASKS, P.REVIEW, P.BUILDING, P.DONE]
FEED_SIZE = 60
TASK_LOG_SIZE = 200
TEXT_LIMIT = 10_000
REJECTED_HEADER = "X-Specflow-Rejected"

templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.filters["md"] = lambda text: Markup(render_markdown(text or ""))
router = APIRouter(include_in_schema=False)


def _rt(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


def _render(request: Request, name: str, context: dict[str, Any], status: int = 200) -> Response:
    return templates.TemplateResponse(request, name, {"version": __version__, **context}, status)


def _project(store: ProjectStore, project_id: int) -> ProjectRow:
    try:
        return store.get_project(project_id)
    except ProjectStoreError as exc:
        raise HTTPException(404, str(exc)) from exc


# --- strony ------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def projects_page(request: Request, error: str | None = None) -> Response:
    rt = _rt(request)
    with rt.sessions() as session:
        projects = [
            {"id": p.id, "name": p.name, "phase": PHASE_LABELS[P(p.phase)]}
            for p in reversed(rt.store(session, 0).projects())
        ]
    context = {"projects": projects, "error": error}
    return _render(request, "projects.html", context, status=502 if error else 200)


@router.post("/projects")
async def create_project_form(request: Request, name: str = Form("")) -> Response:
    name = name.strip()
    if not name or len(name) > 200:
        return await projects_page(request)
    try:
        project_id = await create_project(request.app, name)
    except ProjectCreationError as exc:
        return await projects_page(request, error=str(exc))
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_page(request: Request, project_id: int) -> Response:
    rt = _rt(request)
    with rt.sessions() as session:
        store = rt.store(session, project_id)
        project = _project(store, project_id)
        events = store.events(project_id)
        build = P(project.phase) in BUILD_PHASES
        context: dict[str, Any] = {
            "project": project,
            "mode": "build" if build else "chat",
            "last_event": events[-1].id if events else 0,
            "stages": _stages(project),
            "chat": _chat(store, project),
            "artifacts": _artifacts(rt, project),
        }
        if build:
            context["board"] = _board(store, project)
            context["feed"] = _feed(events[-FEED_SIZE:])
    return _render(request, "project.html", context)


# --- fragmenty -----------------------------------------------------------------------


@router.get("/projects/{project_id}/stages", response_class=HTMLResponse)
async def stages_partial(request: Request, project_id: int) -> Response:
    rt = _rt(request)
    with rt.sessions() as session:
        project = _project(rt.store(session, project_id), project_id)
        return _render(request, "partials/stages.html", {"stages": _stages(project)})


@router.get("/projects/{project_id}/chat", response_class=HTMLResponse)
async def chat_partial(request: Request, project_id: int, notice: str | None = None) -> Response:
    rt = _rt(request)
    with rt.sessions() as session:
        store = rt.store(session, project_id)
        project = _project(store, project_id)
        chat = _chat(store, project, notice=notice)
        return _render(request, "partials/chat_log.html", {"project": project, "chat": chat})


@router.post("/projects/{project_id}/chat", response_class=HTMLResponse)
async def chat_send(request: Request, project_id: int, text: str = Form("")) -> Response:
    text = text.strip()
    if not text:
        return await chat_partial(request, project_id, notice="Napisz wiadomość.")
    notice = _try_submit(request, project_id, "message", text=text[:TEXT_LIMIT])
    return _rejected(await chat_partial(request, project_id, notice=notice), notice)


@router.post("/projects/{project_id}/approve", response_class=HTMLResponse)
async def chat_approve(request: Request, project_id: int) -> Response:
    notice = _try_submit(request, project_id, "approve")
    return await chat_partial(request, project_id, notice=notice)


@router.get("/projects/{project_id}/board", response_class=HTMLResponse)
async def board_partial(request: Request, project_id: int, notice: str | None = None) -> Response:
    rt = _rt(request)
    with rt.sessions() as session:
        store = rt.store(session, project_id)
        project = _project(store, project_id)
        board = _board(store, project, notice=notice)
        return _render(request, "partials/board.html", {"project": project, "board": board})


@router.post("/projects/{project_id}/pause", response_class=HTMLResponse)
async def board_pause(request: Request, project_id: int) -> Response:
    notice = _try_submit(request, project_id, "pause")
    return await board_partial(request, project_id, notice=notice)


@router.post("/projects/{project_id}/resume", response_class=HTMLResponse)
async def board_resume(request: Request, project_id: int) -> Response:
    notice = _try_submit(request, project_id, "resume")
    return await board_partial(request, project_id, notice=notice)


@router.get("/projects/{project_id}/tasks/{key}", response_class=HTMLResponse)
async def task_partial(
    request: Request, project_id: int, key: str, notice: str | None = None
) -> Response:
    rt = _rt(request)
    with rt.sessions() as session:
        store = rt.store(session, project_id)
        project = _project(store, project_id)
        try:
            task = store.get_task(project_id, key)
        except ProjectStoreError as exc:
            raise HTTPException(404, str(exc)) from exc
        events = [e for e in store.events(project_id) if e.task_key == key]
        context = {
            "project": project,
            "task": task,
            "status_label": dict(KANBAN_COLUMNS)[S(task.status)],
            "awaiting": S(task.status) is S.AWAITING_INPUT,
            "answer_pending": _pending_answer(store, project_id, key),
            "log": _feed(events[-TASK_LOG_SIZE:]),
            "notice": notice,
        }
        return _render(request, "partials/task.html", context)


@router.post("/projects/{project_id}/tasks/{key}/answer", response_class=HTMLResponse)
async def task_answer(
    request: Request, project_id: int, key: str, text: str = Form("")
) -> Response:
    text = text.strip()
    if not text:
        return await task_partial(request, project_id, key, notice="Napisz odpowiedź.")
    notice = _try_submit(request, project_id, "answer", task_key=key, text=text[:TEXT_LIMIT])
    return _rejected(await task_partial(request, project_id, key, notice=notice), notice)


@router.get("/projects/{project_id}/artifacts", response_class=HTMLResponse)
async def artifacts_partial(request: Request, project_id: int) -> Response:
    rt = _rt(request)
    with rt.sessions() as session:
        project = _project(rt.store(session, project_id), project_id)
        context = {"project": project, "artifacts": _artifacts(rt, project)}
        return _render(request, "partials/artifacts.html", context)


@router.get("/projects/{project_id}/artifact", response_class=HTMLResponse)
async def artifact_partial(request: Request, project_id: int, path: str) -> Response:
    rt = _rt(request)
    with rt.sessions() as session:
        project = _project(rt.store(session, project_id), project_id)
        try:
            artifact = read_artifact(rt.workspace(project).path, project.feature_dir, path)
        except ArtifactError as exc:
            raise HTTPException(404, str(exc)) from exc
        context = {"project": project, "artifact": artifact}
        return _render(request, "partials/artifact.html", context)


# --- dane dla szablonów ----------------------------------------------------------------


def _try_submit(request: Request, project_id: int, kind: str, **fields: Any) -> str | None:
    """Polecenie do skrzynki; zwraca komunikat dla użytkownika, gdy się nie da."""
    try:
        submit(request.app, project_id, kind, **fields)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        return str(exc.detail)
    return None


def _rejected(response: Response, notice: str | None) -> Response:
    """Polecenie odrzucone: fragment z komunikatem, ale formularz zachowuje wpisany tekst
    (app.js czyści pole tylko bez tego nagłówka)."""
    if notice:
        response.headers[REJECTED_HEADER] = "1"
    return response


def _stages(project: ProjectRow) -> list[dict[str, str]]:
    current = STAGES.index(P(project.phase))
    clarified = bool((project.interview_state or {}).get("open_questions"))
    result = []
    for index, phase in enumerate(STAGES):
        if phase is P.CLARIFY and not clarified and P(project.phase) is not P.CLARIFY:
            continue  # doprecyzowanie pokazujemy tylko, gdy były pytania
        state = "done" if index < current else "current" if index == current else "todo"
        result.append({"label": PHASE_LABELS[phase], "state": state})
    return result


def _chat(store: ProjectStore, project: ProjectRow, *, notice: str | None = None) -> dict[str, Any]:
    messages = store.messages(project.id)
    logged = {m.command_id for m in messages if m.command_id is not None}
    pending = store.pending_commands(project.id, CHAT_COMMANDS)
    phase = P(project.phase)
    state = InterviewState.model_validate(project.interview_state or {})
    busy = bool(pending) or project.planning_step is not None
    return {
        "messages": messages,
        "pending": [c.text for c in pending if c.kind == "message" and c.id not in logged],
        "busy": busy,
        "busy_text": PLANNING_STEPS.get(project.planning_step or "", "Asystent pisze…"),
        "gate": project.gate if not busy else None,
        "gate_summary": project.gate_summary,
        "blocked": project.planning_message,
        "progress": progress(state) if phase in (P.CONSTITUTION, P.SPECIFY) else None,
        "notice": notice,
    }


def _board(
    store: ProjectStore, project: ProjectRow, *, notice: str | None = None
) -> dict[str, Any]:
    tasks = store.board_tasks(project.id)
    columns = [
        {"status": status.value, "label": label, "tasks": [t for t in tasks if t.status == status]}
        for status, label in KANBAN_COLUMNS
    ]
    done = sum(1 for t in tasks if t.status == S.DONE)
    return {
        "columns": columns,
        "done": done,
        "total": len(tasks),
        "run_state": project.run_state,
        "paused_reason": project.paused_reason,
        "finished": P(project.phase) is P.DONE,
        "notice": notice,
    }


def _feed(events: list[EventRow]) -> list[dict[str, Any]]:
    items = []
    for event in events:
        narration = narrate(event)
        if narration is not None:
            items.append(
                {"text": narration.text, "level": narration.level, "task": event.task_key or ""}
            )
    return items


def _artifacts(rt: Runtime, project: ProjectRow) -> list[dict[str, str]]:
    root = rt.workspace(project).path
    if not root.exists():
        return []
    return [a.model_dump() for a in list_artifacts(root, project.feature_dir)]


def _pending_answer(store: ProjectStore, project_id: int, key: str) -> bool:
    return any(c.task_key == key for c in store.pending_commands(project_id, frozenset({"answer"})))
