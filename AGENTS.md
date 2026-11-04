# Instrukcje dla agentów AI pracujących w tym repo

## Projekt
Specflow: software factory (czat → Spec Kit → kanban → agent → weryfikacja).
Architektura: `docs/ARCHITECTURE.md`. Decyzje: `docs/adr/`. Plan: `docs/ROADMAP.md`.

## Zasady
- Python 3.12+, zarządzanie zależnościami wyłącznie przez `uv` (`uv add`, `uv sync`).
- Kod i identyfikatory po angielsku; dokumentacja i opisy dla użytkownika po polsku.
- Orkiestrator i model domeny są deterministyczne: bez wywołań LLM (ADR-0001).
- Każdy dostęp do agenta idzie przez interfejs w `specflow.harness` (ADR-0002).
- Każda zmiana ma testy. Przed commitem muszą przejść:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
- Elementy związane z AI (prompty, przepływ agentów, weryfikacja) opisuj w PR:
  co robi model, co robi kod i dlaczego.
