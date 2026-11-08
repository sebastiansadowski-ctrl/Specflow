# Specflow

Software factory dla osób nietechnicznych: użytkownik opowiada w czacie, czego potrzebuje,
a system prowadzi go przez etapy [Spec Kit](https://github.com/github/spec-kit)
(konstytucja → specyfikacja → plan → zadania), pokazuje pracę agenta AI na tablicy kanban
i weryfikuje wynik testami.

> Status: **F00 – prototyp lokalny (v0.0.0)**, etap M6 (end-to-end). Plan: [docs/ROADMAP.md](docs/ROADMAP.md).

## Dokumentacja

- [Architektura](docs/ARCHITECTURE.md): warstwy, przepływ agentów, co jest AI, a co kodem
- [Roadmapa](docs/ROADMAP.md): fazy F00–F12 i etapy wersji 0.0.0
- [Decyzje architektoniczne (ADR)](docs/adr/)

## Wymagania

- tryb demo: Python 3.12+ i [uv](https://docs.astral.sh/uv/)
- prawdziwy agent: Docker (np. Docker Desktop) i plan ChatGPT do zalogowania w OpenCode

## Uruchomienie

**Prawdziwy agent (Specflow + OpenCode w Dockerze):** instrukcja od zera w
[docker/README.md](docker/README.md). W skrócie: `cd docker && cp .env.example .env`,
ustaw hasło, `docker compose build`, zaloguj OpenCode, `docker compose up -d`,
otwórz http://localhost:8000.

**Demo bez modelu (lokalnie, bez Dockera):**

```bash
uv sync
uv run specflow serve --harness mock        # http://127.0.0.1:8000
```

Ustawienia (priorytet: argumenty > zmienne `SPECFLOW_*` > plik `.env` > domyślne) są opisane
w `src/specflow/settings.py`; przykład w `.env.example`. Dane (baza SQLite, workspace'y
projektów) trafiają do `var/`. W trybie `mock` odpowiedzi asystenta i praca agenta są
nagrane (scenariusz „lista zadań”), ale testy i weryfikacja działają naprawdę.

Eksport diagnostyczny przebiegu: `uv run specflow export <id_projektu>`.

Szybki test API:

```bash
curl -X POST localhost:8000/api/projects -H 'content-type: application/json' -d '{"name":"Demo"}'
curl -N localhost:8000/api/projects/1/events     # zdarzenia na żywo (SSE)
```

## Praca deweloperska

```bash
uv run pytest              # testy
uv run ruff check .        # lint
uv run ruff format .       # formatowanie
uv run mypy                # typy
```

## Licencja

Oprogramowanie zamknięte. Wszelkie prawa zastrzeżone, patrz [LICENSE](LICENSE).
