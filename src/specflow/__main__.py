"""Uruchomienie: `uv run specflow serve --harness mock` (albo `python -m specflow`).

Priorytet ustawień: argumenty > zmienne `SPECFLOW_*` > plik `.env` > wartości domyślne.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import uvicorn

from specflow.settings import Settings


def parse_args(argv: Sequence[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(prog="specflow", description="Specflow - software factory")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="uruchamia serwer (domyślnie)")
    for target in (parser, serve):
        # SUPPRESS: brak argumentu = brak klucza, więc wygrywa zmienna środowiskowa / .env.
        hidden = argparse.SUPPRESS
        target.add_argument("--harness", choices=["mock", "opencode"], default=hidden)
        target.add_argument("--host", default=hidden)
        target.add_argument("--port", type=int, default=hidden)
        target.add_argument("--data-dir", type=Path, default=hidden)
        target.add_argument("--opencode-url", default=hidden)
    args = vars(parser.parse_args(argv))
    args.pop("command", None)
    return args


def main(argv: Sequence[str] | None = None) -> None:
    from specflow.web.app import create_app

    settings = Settings(**parse_args(argv))
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
