# Roadmapa

## Fazy rozwoju

| Faza | Zakres |
|---|---|
| **F00** | Prototyp lokalny (v0.0.0) |
| F01 | Stabilizacja przepływu: recenzent na innym modelu, zadania w JSON, przeplanowanie przy zmianie wymagań, testy E2E interfejsu |
| F02 | Integracja z API modeli (Anthropic, OpenAI, BYOK), adapter Claude Agent SDK, pomiar kosztów |
| F03 | Integracja z GitHub: repo projektu, PR-y, CI |
| F04 | Konta i wielu użytkowników: logowanie, izolacja projektów, Postgres |
| F05 | Infrastruktura chmurowa: sandbox w chmurze, trwały silnik workflow |
| F06 | Podgląd działającej aplikacji (środowiska preview) dla nietechnicznych użytkowników |
| F07 | Rozliczenia: pakiety, limity, kredyty, płatności |
| F08 | Bezpieczeństwo i zgodność: RODO, umowy powierzenia danych, audyt, rezydencja danych w UE |
| F09 | Zamknięta beta z klientami: onboarding, analityka, zbieranie opinii |
| F10 | Równoległe agenty: worktree, integracja i rozwiązywanie konfliktów |
| F11 | Hosting aplikacji klientów (PaaS) i opcja „Continue with ChatGPT” |
| F12 | Wersja publiczna 1.0 |

## F00: prototyp lokalny (v0.0.0)

**Cel:** lokalnie, na jednym komputerze, pokazać cały przepływ: wywiad w czacie → artefakty
Spec Kit → kanban → agent realizuje zadania → weryfikacja → działający kod z testami.

**Stos:** Python 3.12+, `uv`, FastAPI, Pydantic v2, SQLite + SQLAlchemy 2.0 (Alembic później),
Jinja2 + HTMX + SSE, pytest, ruff, mypy, GitHub Actions. Agent: OpenCode (`opencode serve`)
w kontenerze Docker, na planie ChatGPT. Spec Kit przypięty do konkretnej wersji.

| Etap | Zakres | Gotowe, gdy… |
|---|---|---|
| **M0 – Fundamenty** | Szkielet projektu, CI, README, ARCHITECTURE, ROADMAP, ADR-0001..0003 | CI przechodzi na szkielecie |
| **M1 – Rdzeń domeny** | Model (Project, Task, Event), SQLite, maszyna stanów zadań z aktorami, parser `tasks.md` → DAG z walidacją (ADR-0004). Run dochodzi w M3, Artifact w M4, migracje Alembic najpóźniej w F04 | Testy jednostkowe na przykładowych `tasks.md` przechodzą |
| **M2 – Harness i workspace** | Interfejs adaptera, adapter Mock (scenariusze), menedżer workspace (`git init`, `specify init`, commit po zadaniu), adapter OpenCode, obraz Docker | Mock w CI; OpenCode odpowiada lokalnie |
| **M3 – Orkiestrator i weryfikacja** | Pętla orkiestratora, limity, Rework / Awaiting input, build+testy z konfiguracji, blokada zmian w testach, zdarzenia SSE | Pełny przebieg zadań na Mocku, wszystkie ścieżki statusów |
| **M4 – Wywiad** | Etapy, checklisty kompletności, podsumowania do akceptacji, wywołania `/speckit.*` | Rozmowa daje kompletne artefakty (Mock, potem OpenCode) |
| **M5 – Interfejs** | Czat, kanban, podgląd artefaktów, log agenta, pasek etapów | Całość da się przeklikać w przeglądarce |
| **M6 – End-to-end i wydanie** | `docker compose`, test E2E na Mocku w CI, instrukcja z OpenCode, scenariusz demo, tag `v0.0.0` | Kryteria akceptacji spełnione |

**Uwaga:** lokalnie nie ma klucza API, więc czat wywiadu również idzie przez OpenCode
(osobna sesja bez narzędzi). Bezpośrednie wywołania API modeli dochodzą w F02.

### Kryteria akceptacji v0.0.0

1. Pełny przepływ na adapterze Mock przechodzi automatycznie w CI.
2. Lokalnie, z OpenCode na planie ChatGPT, z ok. 10-minutowej rozmowy powstaje aplikacja demo
   („lista zadań z logowaniem”) z przechodzącymi testami.
3. Każde zrobione zadanie ma swój commit; kanban odzwierciedla statusy na żywo.
4. Instrukcja w README pozwala uruchomić całość od zera.
