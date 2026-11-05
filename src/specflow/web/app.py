"""Aplikacja FastAPI. W M0 tylko szkielet: health check i strona z układem czat + kanban."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from specflow import __version__

WEB_DIR = Path(__file__).parent

# Kolumny kanbanu. W M1 przeniesione do maszyny stanów w `specflow.domain`.
KANBAN_COLUMNS: list[tuple[str, str]] = [
    ("backlog", "Backlog"),
    ("ready", "Ready"),
    ("in_progress", "In progress"),
    ("verification", "Verification"),
    ("awaiting_input", "Awaiting input"),
    ("rework", "Rework"),
    ("done", "Done"),
]

app = FastAPI(title="Specflow", version=__version__)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"version": __version__, "columns": KANBAN_COLUMNS},
    )
