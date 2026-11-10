"""Uruchomienie: `uv run specflow serve --harness mock` (albo `python -m specflow`).

    specflow serve [--harness mock|opencode] [--port 8000] ...
    specflow export <id_projektu> [-o plik.zip]      # eksport diagnostyczny przebiegu

Priorytet ustawień: argumenty > zmienne `SPECFLOW_*` > plik `.env` > wartości domyślne.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import uvicorn

from specflow.settings import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="specflow", description="Specflow - software factory")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="uruchamia serwer (domyślnie)")
    export = sub.add_parser("export", help="eksport diagnostyczny projektu do pliku .zip")
    export.add_argument("project_id", type=int)
    export.add_argument("-o", "--output", type=Path, default=argparse.SUPPRESS)
    export.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
    for target in (parser, serve):
        # SUPPRESS: brak argumentu = brak klucza, więc wygrywa zmienna środowiskowa / .env.
        hidden = argparse.SUPPRESS
        target.add_argument("--harness", choices=["mock", "opencode"], default=hidden)
        target.add_argument("--host", default=hidden)
        target.add_argument("--port", type=int, default=hidden)
        target.add_argument("--data-dir", type=Path, default=hidden)
        target.add_argument("--opencode-url", default=hidden)
    return parser


def parse_args(argv: Sequence[str] | None = None) -> dict[str, Any]:
    """Argumenty `serve` jako nadpisania ustawień (tylko podane)."""
    args = vars(_parser().parse_args(argv))
    args.pop("command", None)
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = vars(_parser().parse_args(argv))
    if args.pop("command", None) == "export":
        from specflow.storage import ProjectStoreError

        try:
            run_export(args)
        except ProjectStoreError as exc:  # np. zły numer projektu: komunikat zamiast tracebacku
            raise SystemExit(f"Błąd: {exc}") from None
        return
    from specflow.web.app import create_app

    settings = Settings(**args)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


def run_export(args: dict[str, Any]) -> Path:
    from specflow.export import export_project
    from specflow.storage import make_engine, session_factory

    project_id = args.pop("project_id")
    output = args.pop("output", None)
    settings = Settings(**args)
    engine = make_engine(settings.db_url())
    with session_factory(engine)() as session:
        path = export_project(
            session,
            settings.projects_path(),
            project_id,
            output,
            harness=settings.harness,
            secrets=[settings.opencode_password],
        )
    print(f"Zapisano eksport: {path}")
    return path


if __name__ == "__main__":
    main()
