# Architektura

## Warstwy

```mermaid
flowchart TB
  subgraph FE["Frontend (przeglądarka, HTMX)"]
    chat["Czat: wywiad i akceptacje"]
    board["Kanban: statusy na żywo"]
    art["Podgląd artefaktów"]
  end

  subgraph BE["Backend: nasz rdzeń (FastAPI)"]
    interview["Silnik wywiadu"]
    domain["Model domeny: zadania i DAG"]
    orch["Orkiestrator: maszyna stanów"]
    verify["Weryfikacja: build i testy"]
  end

  subgraph AD["Adaptery harnessu"]
    oc["OpenCode"]
    mock["Mock"]
    sdk["Claude Agent SDK (F02)"]
  end

  subgraph WS["Kontener Docker: workspace projektu"]
    serve["opencode serve: pętla agenta"]
    sk["Spec Kit: szablony i komendy"]
    repo["Repo git projektu"]
  end

  models["Modele AI: plan ChatGPT / API"]
  gh["GitHub (F03)"]

  FE -- "REST + SSE" --> BE
  BE -- "jeden interfejs" --> AD
  oc -- "HTTP" --> serve
  serve --> models
  repo -.-> gh
```

## Przepływ pracy

```
[1] Agent wywiadu ──► bramka: użytkownik akceptuje specyfikację
[2] Agent planisty (/speckit.plan, /speckit.tasks, /speckit.analyze) ──► bramka: akceptacja planu
[3] Builder DAG (kod) ──► kanban: Backlog / Ready
[4] Orkiestrator (kod) ──► wybiera następne zadanie Ready
[5] Harness (OpenCode w Dockerze) ──► agent wykonawczy realizuje zadanie
[6] Weryfikacja: build/testy (kod) → recenzent (LLM, F01)
      OK    → Done + commit
      błąd  → Rework (maks. 2 próby) → [5]
      pytanie / decyzja → Awaiting input → użytkownik → [5] albo [1]/[2]
[7] Po wszystkich zadaniach: weryfikacja całości → demo → akceptacja użytkownika
[8] Zmiana wymagań → [1], przeplanowanie tylko części dotkniętych zmianą
```

## Co jest AI, a co kodem

| Element | Kto | Wynik |
|---|---|---|
| Agent wywiadu | LLM (w F00 przez OpenCode, bez narzędzi) | Odpowiedzi → `/speckit.constitution`, `/speckit.specify`, `/speckit.clarify` |
| Agent planisty | LLM w harnessie | `plan.md`, `data-model.md`, `tasks.md` |
| Builder DAG | **kod** | Graf zadań w bazie, po walidacji |
| Orkiestrator | **kod** | Kolejność, limity, statusy |
| Agent wykonawczy | LLM w harnessie | Kod dla jednego zadania |
| Testy | LLM, w **osobnym zadaniu przed implementacją**, na podstawie kryteriów akceptacji | Pliki testów |
| Weryfikacja | **kod** (build, typy, lint, testy), potem LLM-recenzent (F01) | OK / Rework / Awaiting input |
| Kryteria akceptacji i odbiór | **użytkownik** | Zatwierdzona specyfikacja, akceptacja demo |

Zasada: model **proponuje**, kod **sprawdza i decyduje**. Status `Done` ustawia orkiestrator
na podstawie wyniku weryfikacji, nigdy na podstawie deklaracji agenta.

## Źródło prawdy

Artefakty Spec Kit (`spec.md`, `plan.md`, `tasks.md`) są w repo projektu, ale po imporcie
źródłem prawdy dla zadań i statusów jest baza Specflow. Markdown jest wejściem i projekcją,
nie stanem.
