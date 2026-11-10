"""Eksport diagnostyczny projektu: jeden plik .zip do analizy przebiegu poza serwerem.

`specflow export 1` → `specflow-export-0001-<data>.zip` z:
- manifest.json   - wersja Specflow, harness, projekt, liczniki;
- project.json    - stan projektu (faza, bramka, stan wywiadu, dziennik planisty);
- *.jsonl         - czat, zdarzenia (z narracją), zadania, runy (z promptami), decyzje, polecenia;
- workspace.bundle - pełna historia gita projektu (`git clone workspace.bundle`);
- workspace-status.txt - niezatwierdzone zmiany (np. przerwane podejście);
- workspace-untracked/ - treść nowych, jeszcze niezacommitowanych plików tekstowych
  (np. specs/ przed akceptacją planu, które nie trafiają do bundle'a ani do diffu).

Sekrety: eksport nie zawiera ustawień ani tokenów; dodatkowo każde wystąpienie hasła
OpenCode w treści jest zamieniane na `***` (na wypadek, gdyby trafiło do logu agenta).
"""

import json
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from specflow import __version__
from specflow.storage import ProjectStore
from specflow.storage.models import Base
from specflow.web.narration import narrate
from specflow.workspace import Workspace, WorkspaceError, run_command

REDACTED = "***"
UNTRACKED_DIR = "workspace-untracked"
MAX_UNTRACKED_FILE = 256 * 1024
MAX_UNTRACKED_TOTAL = 4 * 1024 * 1024


def export_project(
    session: Session,
    projects_dir: Path,
    project_id: int,
    output: Path | None = None,
    *,
    harness: str = "?",
    secrets: Iterable[str | None] = (),
) -> Path:
    store = ProjectStore(session)
    project = store.get_project(project_id)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = output or Path(f"specflow-export-{project_id:04d}-{stamp}.zip")
    hidden = [s for s in secrets if s]

    events = store.events(project_id)
    tasks = store.board_tasks(project_id)
    tables: dict[str, list[dict[str, Any]]] = {
        "chat.jsonl": [_row(m) for m in store.messages(project_id)],
        "events.jsonl": [_event(e) for e in events],
        "tasks.jsonl": [_row(t) for t in tasks],
        "runs.jsonl": [_row(r) for r in store.runs(project_id)],
        "decisions.jsonl": [_row(d) for d in store.decisions(project_id)],
        "commands.jsonl": [_row(c) for c in store.commands(project_id)],
    }
    manifest = {
        "specflow_version": __version__,
        "exported_at": datetime.now(UTC).isoformat(),
        "harness": harness,
        "project": {"id": project.id, "name": project.name, "phase": project.phase},
        "counts": {name.removesuffix(".jsonl"): len(rows) for name, rows in tables.items()},
    }

    workspace = Workspace(Workspace.path_for(projects_dir, project.id, project.name))
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _redact(_json(manifest, indent=2), hidden))
        archive.writestr("project.json", _redact(_json(_row(project), indent=2), hidden))
        for name, rows in tables.items():
            lines = "".join(_json(row) + "\n" for row in rows)
            archive.writestr(name, _redact(lines, hidden))
        if (workspace.path / ".git").exists():
            _add_workspace(archive, workspace, hidden)
    return target


def _add_workspace(archive: zipfile.ZipFile, workspace: Workspace, hidden: list[str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bundle = Path(tmp) / "workspace.bundle"
        try:
            run_command(["git", "bundle", "create", str(bundle), "--all"], workspace.path)
            archive.write(bundle, "workspace.bundle")
        except WorkspaceError as exc:
            archive.writestr("workspace-error.txt", str(exc))
    status = run_command(["git", "status", "--short"], workspace.path)
    diff = run_command(["git", "diff"], workspace.path)
    archive.writestr("workspace-status.txt", _redact(f"{status}\n\n{diff}", hidden))
    _add_untracked(archive, workspace, hidden)


def _add_untracked(archive: zipfile.ZipFile, workspace: Workspace, hidden: list[str]) -> None:
    """Nowe pliki tekstowe spoza gita (z .gitignore pomijanymi), z limitem rozmiaru."""
    listing = run_command(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], workspace.path
    )
    root = workspace.path.resolve()
    skipped: list[str] = []
    total = 0
    for name in sorted(n for n in listing.split("\0") if n):
        path = workspace.path / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        size = path.stat().st_size
        if size > MAX_UNTRACKED_FILE or total + size > MAX_UNTRACKED_TOTAL:
            skipped.append(f"{name} ({size} B: za duży)")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append(f"{name} (plik binarny)")
            continue
        total += size
        archive.writestr(f"{UNTRACKED_DIR}/{name}", _redact(text, hidden))
    if skipped:
        archive.writestr(f"{UNTRACKED_DIR}.skipped.txt", "\n".join(skipped) + "\n")


def _event(event: Any) -> dict[str, Any]:
    narration = narrate(event)
    return {**_row(event), "narration": narration.text if narration else None}


def _row(row: Base) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def _json(data: Any, indent: int | None = None) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, indent=indent)


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text
