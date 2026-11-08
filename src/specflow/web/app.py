"""Aplikacja FastAPI: API projektu, strumień SSE i strona startowa (widoki: M5b).

Zasady warstwy web (ADR-0008):
- HTTP nie zmienia stanu projektu, tylko dopisuje polecenia do skrzynki (inbox) i czyta.
  Stan zmienia wyłącznie worker projektu (`specflow.runtime`).
- Endpointy są `async`: wszystko działa w jednej pętli zdarzeń razem z workerami.
- Treści od modelu renderujemy bezpiecznie, a nagłówek CSP jest drugą warstwą obrony.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from specflow import __version__
from specflow.bootstrap import build_runtime
from specflow.domain import KANBAN_COLUMNS
from specflow.domain.project_phase import PHASE_LABELS, ProjectPhase
from specflow.interview import InterviewState
from specflow.interview.slots import progress
from specflow.runtime import Runtime, Supervisor
from specflow.settings import Settings
from specflow.storage import CHAT_COMMANDS, ProjectRow, ProjectStore, ProjectStoreError
from specflow.web.artifacts import ArtifactError, list_artifacts, read_artifact
from specflow.web.commands import BUSY, ProjectCreationError, create_project, submit
from specflow.web.markdown import render_markdown
from specflow.web.sse import event_stream, parse_last_event_id
from specflow.web.views import router as views_router

__all__ = ["BUSY", "KANBAN_COLUMNS", "create_app"]

WEB_DIR = Path(__file__).parent

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
    app.state.start_workers = start_workers
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(views_router)

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
        return {"command_id": submit(app, project_id, kind, **fields), "status": "queued"}

    # --- strony --------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "harness": rt.harness.name}

    # --- projekty ------------------------------------------------------------------

    @app.post("/api/projects", status_code=201)
    async def create_project_api(body: CreateProject) -> dict[str, Any]:
        try:
            return {"id": await create_project(app, body.name)}
        except ProjectCreationError as exc:
            raise HTTPException(502, f"Nie udało się przygotować projektu: {exc}") from exc

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
