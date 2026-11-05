# ADR-0003: Stos Python + FastAPI + HTMX

- Status: przyjęte
- Data: 2026-11-04

## Kontekst

Właściciel projektu woli Pythona niż TypeScript. Interfejs potrzebuje czatu, kanbanu
i aktualizacji na żywo, ale nie wymaga rozbudowanej aplikacji frontendowej.

## Decyzja

- Backend: Python 3.12+, `uv`, FastAPI, Pydantic v2, SQLite + SQLAlchemy 2.0 + Alembic.
- Interfejs: szablony Jinja2 + HTMX + SSE (`sse-starlette`); przeciąganie kart: SortableJS.
- Jakość: pytest, ruff, mypy (strict), GitHub Actions.

Odrzucone: NiceGUI (szybszy start, trudniejsze dopracowanie produktu SaaS),
React/TypeScript (preferencja właściciela).

## Konsekwencje

- Logika i stan po stronie serwera; przeglądarka renderuje fragmenty HTML.
- Klient OpenCode (HTTP) generowany lub pisany w Pythonie na bazie jego specyfikacji OpenAPI.
- Przejście na Postgres (F04) to zmiana adresu bazy i migracje Alembic.
