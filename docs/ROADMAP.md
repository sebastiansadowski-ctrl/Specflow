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
| **M2 – Harness i workspace** | Port `Harness` i słownik zdarzeń, raport agenta w JSON, profile uprawnień bez `ask`, adapter Mock (scenariusze), adapter OpenCode v2.2.5, menedżer workspace (`git init`, `specify init`, commit po zadaniu), obraz Docker (ADR-0005) | Mock w CI; OpenCode odpowiada lokalnie (nagranie zdarzeń) |
| **M3 – Orkiestrator i weryfikacja** | Pętla orkiestratora (3 podejścia, Rework w tej samej sesji, Awaiting input z odpowiedzią lub wskazówką, gałęzie `attempt/`, pauza przy awarii), prompty z wersją, weryfikacja w sandboxie agenta (`/api/shell`): diff, pliki chronione, JUnit, regresje, TDD, checkpoint historyjki; tabela `runs` (ADR-0006). Strumień SSE do interfejsu: M5 | Pełny przebieg zadań na Mocku, wszystkie ścieżki statusów |
| **M4 – Wywiad i planowanie** | Etapy projektu (maszyna faz), wywiad slot-filling z JSON-em tury i walidacją, konstytucja z domyślnych zasad + 2 pytania, bramki akceptacji (podsumowania składane przez kod), własny clarify przez znaczniki `[NEEDS CLARIFICATION]`, planista `/speckit.*` z kontrolami artefaktów, pętlą naprawczą `tasks.md` i `analyze` z jedną poprawką CRITICAL; F00 tylko Python (ADR-0007) | Rozmowa daje kompletne artefakty i zadania na tablicy (Mock w CI, potem OpenCode) |
| **M5a – Backend czasu rzeczywistego** | Ustawienia (CLI > env > `.env`), skrzynka poleceń i worker projektu, odzyskiwanie po awarii i łagodne zamykanie, SQLite WAL, SSE z zapisem do bazy i `Last-Event-ID`, narracja zdarzeń, bezpieczny Markdown i CSP, API projektu, demo na Mocku (ADR-0008) | Demo przechodzi od pierwszego pytania do Done przez API i workera; testy awarii |
| **M5b – Interfejs** | Lista projektów, ekran zależny od etapu (czat + dokumenty / kanban + log), bramki jako karty w czacie, karta zadania z logiem i odpowiedzią, pauza/wznowienie, klient SSE zgodny z CSP; szkielet projektu Python tworzony przez kod (ADR-0009) | Demo przechodzi w przeglądarce od nazwy projektu do „Gotowe” |
| **M6a – Uruchomienie w Dockerze** | Usługa Specflow w compose (port tylko na 127.0.0.1, ten sam UID co agent, baza w wolumenie niewidocznym dla agenta), `specflow export` (eksport diagnostyczny bez sekretów), test E2E przez cały stos (HTTP, workery w tle, SSE), README od zera (ADR-0010) | Demo przechodzi przez cały stos w teście; compose się waliduje |
| **M6b – Pierwszy prawdziwy przebieg i wydanie** | Etapami na OpenCode: smoke (nagranie zdarzeń → test mapowania), wywiad, planowanie, jedno zadanie, pełna budowa; poprawki promptów po każdym etapie; tag `v0.0.0` | Kryteria akceptacji v0.0.0 spełnione |

**Uwaga:** lokalnie nie ma klucza API, więc czat wywiadu również idzie przez OpenCode
(osobna sesja bez narzędzi). Bezpośrednie wywołania API modeli dochodzą w F02.

### Kryteria akceptacji v0.0.0

1. Pełny przepływ na adapterze Mock przechodzi automatycznie w CI.
2. Lokalnie, z OpenCode na planie ChatGPT, z ok. 10-minutowej rozmowy powstaje aplikacja demo
   („lista zadań z logowaniem”) z przechodzącymi testami.
3. Każde zrobione zadanie ma swój commit; kanban odzwierciedla statusy na żywo.
4. Instrukcja w README pozwala uruchomić całość od zera.

## Pomysły na później

- **Osobny kontener wykonawczy dla poleceń agenta.** Dziś agent uruchamia polecenia w kontenerze
  OpenCode, w którym jest też token do modelu. Docelowo polecenia (bash, testy) startują
  w osobnym, krótko żyjącym kontenerze bez sekretów i z ograniczonym internetem (lista
  dozwolonych adresów przez proxy). Zamyka to ryzyko wycieku tokenu przez prompt injection.

- **Profile stosów technologicznych.** W F00 stos jest stały (Python 3.12, FastAPI + Jinja2,
  SQLite, pytest). Później: kilka gotowych profili (np. Node/TypeScript, Django), które
  użytkownik akceptuje albo wybiera na podstawie preferencji z wywiadu; każdy profil niesie
  własne komendy weryfikacji i pliki chronione (zob. ADR-0006, ADR-0007).
