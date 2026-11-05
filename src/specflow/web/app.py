"""Aplikacja FastAPI. W M0 tylko szkielet: health check i strona z układem czat + kanban."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from specflow import __version__
from specflow.domain import KANBAN_COLUMNS

WEB_DIR = Path(__file__).parent

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
        {
            "version": __version__,
            "columns": [(status.value, label) for status, label in KANBAN_COLUMNS],
        },
    )
