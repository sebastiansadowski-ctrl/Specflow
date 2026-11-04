# Specflow

Software factory dla osób nietechnicznych: użytkownik opowiada w czacie, czego potrzebuje,
a system prowadzi go przez etapy [Spec Kit](https://github.com/github/spec-kit)
(konstytucja → specyfikacja → plan → zadania), pokazuje pracę agenta AI na tablicy kanban
i weryfikuje wynik testami.

> Status: **F00 – prototyp lokalny (v0.0.0)**, etap M0 (fundamenty). Plan: [docs/ROADMAP.md](docs/ROADMAP.md).

## Dokumentacja

- [Architektura](docs/ARCHITECTURE.md): warstwy, przepływ agentów, co jest AI, a co kodem
- [Roadmapa](docs/ROADMAP.md): fazy F00–F12 i etapy wersji 0.0.0
- [Decyzje architektoniczne (ADR)](docs/adr/)

## Wymagania

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- (od M2) Docker i OpenCode zalogowany do planu ChatGPT

## Uruchomienie

```bash
uv sync
uv run specflow            # http://127.0.0.1:8000
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
