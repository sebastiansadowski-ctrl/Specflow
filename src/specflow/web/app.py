"""Aplikacja FastAPI: API projektu, strumień SSE i strona startowa (widoki: M5b).

Zasady warstwy web (ADR-0008):
- HTTP nie zmienia stanu projektu, tylko dopisuje polecenia do skrzynki (inbox) i czyta.
  Stan zmienia wyłącznie worker projektu (`specflow.runtime`).
- Endpointy są `async`: wszystko działa w jednej pętli zdarzeń razem z workerami.
- Treści od modelu renderujemy bezpiecznie, a nagłówek CSP jest drugą warstwą obrony.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from specflow import __version__
from specflow.bootstrap import build_runtime
from specflow.domain import KANBAN_COLUMNS, TaskStatus
from specflow.domain.project_phase import PHASE_LABELS, ProjectPhase
from specflow.harness import demo
from specflow.interview import InterviewState
from specflow.interview.slots import progress
from specflow.runtime import Runtime, Supervisor
from specflow.settings import Settings
from specflow.storage import CHAT_COMMANDS, ProjectRow, ProjectStore, ProjectStoreError
from specflow.web.artifacts import ArtifactError, list_artifacts, read_artifact
from specflow.web.markdown import render_markdown
from specflow.web.sse import event_stream, parse_last_event_id
from specflow.workspace import Workspace

__all__ = ["KANBAN_COLUMNS", "create_app"]

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
BUSY = "Poczekaj chwilę, kończę poprzednią odpowiedź."


class CreateProject(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TextBody(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


def create_app(
    settings: Settings | None = None,
    *,
    runtime: Runtime | None = None,
    start_workers: bool = True,
) -> FastAPI:
    """`start_workers=False`: testy same wywołują `ProjectWorker.drain()` (deterministycznie)."""
    settings = settings or Settings()
    rt = runtime or build_runtime(settings)
    supervisor = Supervisor(rt, grace_s=settings.shutdown_grace_s)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if start_workers:
            await supervisor.start()
        yield
        await supervisor.stop()

    app = FastAPI(title="Specflow", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.runtime = rt
    app.state.supervisor = supervisor
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def store_for(session: Any, project_id: int) -> ProjectStore:
        return rt.store(session, project_id)

    def project_or_404(store: ProjectStore, project_id: int) -> ProjectRow:
        try:
            return store.get_project(project_id)
        except ProjectStoreError as exc:
            raise HTTPException(404, str(exc)) from exc

    def enqueue(project_id: int, kind: str, **fields: Any) -> dict[str, Any]:
        with rt.sessions() as session:
            store = store_for(session, project_id)
            project = project_or_404(store, project_id)
            _check_command(store, project, kind, fields.get("task_key"))
            command = store.enqueue(project_id, kind, **fields)
            store.commit()
            if start_workers:
                supervisor.ensure_worker(project_id)
            return {"command_id": command.id, "status": "queued"}

    # --- strony --------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "harness": rt.harness.name}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "version": __version__,
                "columns": [(status.value, label) for status, label in KANBAN_COLUMNS],
            },
        )

    # --- projekty ------------------------------------------------------------------

    @app.post("/api/projects", status_code=201)
    async def create_project(body: CreateProject) -> dict[str, Any]:
        with rt.sessions() as session:
            store = store_for(session, 0)
            project = store.create_project(body.name.strip())
            store.commit()
            workspace = Workspace.create(rt.projects_dir, project.id, project.name)
            if settings.should_init_spec_kit():
                await asyncio.to_thread(workspace.init_spec_kit)
            elif settings.harness == "mock":
                demo.prepare_workspace(workspace)
            store.enqueue(project.id, "start")
            store.commit()
            project_id = project.id
        if start_workers:
            supervisor.ensure_worker(project_id)
        return {"id": project_id}

    @app.get("/api/projects")
    async def projects() -> list[dict[str, Any]]:
        with rt.sessions() as session:
            store = store_for(session, 0)
            return [_project_brief(p) for p in store.projects()]

    @app.get("/api/projects/{project_id}")
    async def project_state(project_id: int) -> dict[str, Any]:
        with rt.sessions() as session:
            store = store_for(session, project_id)
            project = project_or_404(store, project_id)
            busy = bool(store.pending_commands(project_id, CHAT_COMMANDS))
            return {**_project_brief(project), **_project_details(project, busy)}

    @app.get("/api/projects/{project_id}/messages")
    async def messages(project_id: int) -> list[dict[str, Any]]:
        with rt.sessions() as session:
            store = store_for(session, project_id)
            project_or_404(store, project_id)
            return [
                {
                    "id": m.id,
                    "role": m.role,
                    "phase": m.phase,
                    "text": m.text,
                    "html": render_markdown(m.text),
                    "created_at": m.created_at.isoformat(),
                }
                for m in store.messages(project_id)
            ]

    @app.get("/api/projects/{project_id}/tasks")
    async def tasks(project_id: int) -> list[dict[str, Any]]:
        with rt.sessions() as session:
            store = store_for(session, project_id)
            project_or_404(store, project_id)
            return [
                {
                    "key": t.key,
                    "title": t.title,
                    "status": t.status,
                    "story": t.story,
                    "is_test": t.is_test,
                    "attempts": t.attempts,
                    "depends_on": t.depends_on,
                    "files": t.files,
                    "awaiting_reason": t.awaiting_reason,
                    "awaiting_message": t.awaiting_message,
                }
                for t in store.board_tasks(project_id)
            ]

    # --- polecenia (inbox) ---------------------------------------------------------

    @app.post("/api/projects/{project_id}/messages", status_code=202)
    async def send_message(project_id: int, body: TextBody) -> dict[str, Any]:
        return enqueue(project_id, "message", text=body.text.strip())

    @app.post("/api/projects/{project_id}/approve", status_code=202)
    async def approve(project_id: int) -> dict[str, Any]:
        return enqueue(project_id, "approve")

    @app.post("/api/projects/{project_id}/tasks/{key}/answer", status_code=202)
    async def answer(project_id: int, key: str, body: TextBody) -> dict[str, Any]:
        return enqueue(project_id, "answer", task_key=key, text=body.text.strip())

    @app.post("/api/projects/{project_id}/pause", status_code=202)
    async def pause(project_id: int) -> dict[str, Any]:
        return enqueue(project_id, "pause")

    @app.post("/api/projects/{project_id}/resume", status_code=202)
    async def resume(project_id: int) -> dict[str, Any]:
        return enqueue(project_id, "resume")

    # --- strumień i artefakty ------------------------------------------------------

    @app.get("/api/projects/{project_id}/events")
    async def events(
        project_id: int,
        after: int | None = None,
        follow: bool = True,
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> StreamingResponse:
        with rt.sessions() as session:
            project_or_404(store_for(session, project_id), project_id)
        start = parse_last_event_id(last_event_id, after)
        return StreamingResponse(
            event_stream(rt, project_id, after=start, follow=follow),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/projects/{project_id}/artifacts")
    async def artifacts(project_id: int) -> list[dict[str, Any]]:
        with rt.sessions() as session:
            project = project_or_404(store_for(session, project_id), project_id)
            root = rt.workspace(project).path
            return [a.model_dump() for a in list_artifacts(root, project.feature_dir)]

    @app.get("/api/projects/{project_id}/artifacts/{path:path}")
    async def artifact(project_id: int, path: str) -> dict[str, Any]:
        with rt.sessions() as session:
            project = project_or_404(store_for(session, project_id), project_id)
            root = rt.workspace(project).path
            try:
                return read_artifact(root, project.feature_dir, path).model_dump()
            except ArtifactError as exc:
                raise HTTPException(404, str(exc)) from exc

    return app


def _check_command(store: ProjectStore, project: ProjectRow, kind: str, key: str | None) -> None:
    """Szybka odpowiedź 409 dla poleceń, które na pewno się nie udadzą. Ostateczną decyzję
    i tak podejmuje worker (stan mógł się zmienić, zanim polecenie zostanie wykonane)."""
    if kind in CHAT_COMMANDS and store.pending_commands(project.id, CHAT_COMMANDS):
        raise HTTPException(409, BUSY)
    if kind == "approve" and project.gate is None:
        raise HTTPException(409, "Nie ma teraz nic do zatwierdzenia.")
    if kind == "answer":
        try:
            task = store.get_task(project.id, key or "")
        except ProjectStoreError as exc:
            raise HTTPException(404, str(exc)) from exc
        if TaskStatus(task.status) is not TaskStatus.AWAITING_INPUT:
            raise HTTPException(409, f"Zadanie {task.key} nie czeka na odpowiedź.")
    if kind in ("pause", "resume") and ProjectPhase(project.phase) is not ProjectPhase.BUILDING:
        raise HTTPException(409, "Pauzę i wznowienie można ustawić dopiero w trakcie budowy.")


def _project_brief(project: ProjectRow) -> dict[str, Any]:
    phase = ProjectPhase(project.phase)
    return {
        "id": project.id,
        "name": project.name,
        "phase": phase.value,
        "phase_label": PHASE_LABELS[phase],
        "created_at": project.created_at.isoformat(),
    }


def _project_details(project: ProjectRow, busy: bool) -> dict[str, Any]:
    phase = ProjectPhase(project.phase)
    interviewing = phase in (ProjectPhase.CONSTITUTION, ProjectPhase.SPECIFY, ProjectPhase.CLARIFY)
    state = InterviewState.model_validate(project.interview_state or {})
    return {
        "gate": project.gate,
        "gate_summary_html": render_markdown(project.gate_summary)
        if project.gate_summary
        else None,
        "planning_message": project.planning_message,
        "planning_step": project.planning_step,
        "run_state": project.run_state,
        "paused_reason": project.paused_reason,
        "busy": busy or project.planning_step is not None,
        "progress": list(progress(state)) if interviewing else None,
        "feature_dir": project.feature_dir,
    }
