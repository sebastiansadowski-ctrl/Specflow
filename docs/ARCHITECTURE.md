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
    inbox["API + skrzynka poleceń, SSE"]
    worker["Worker projektu (runtime)"]
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

## Orkiestrator: pętla jednego zadania

Kod (deterministyczny) decyduje o każdym kroku; model pracuje tylko w kroku „Agent pracuje”.
Szczegóły: `src/specflow/orchestrator/engine.py`, ADR-0001, ADR-0006.

```mermaid
flowchart TD
  ready["Zadanie Ready<br/><small>następne wg harmonogramu</small>"]:::status
  prompt["Sesja i prompt<br/><small>świeża sesja + kontekst</small>"]:::code
  agent["Agent pracuje<br/><small>model w harnessie</small>"]:::model
  blocked{"Raport: blocked?"}:::code
  awaitQ["Awaiting input<br/><small>pytanie do użytkownika</small>"]:::status
  verify["Weryfikacja<br/><small>diff, testy, checkpoint</small>"]:::code
  passed{"Przeszło?"}:::code
  done["Done + commit<br/><small>tylko przez weryfikację</small>"]:::status
  attempts{"Podejście < 3?"}:::code
  save["Zapis próby<br/><small>gałąź attempt/, reset</small>"]:::code
  awaitH["Awaiting input<br/><small>czeka na wskazówkę</small>"]:::status

  ready --> prompt --> agent --> blocked
  blocked -- tak --> awaitQ
  blocked -- nie --> verify --> passed
  passed -- tak --> done
  passed -- nie --> attempts
  attempts -- "tak: Rework (ta sama sesja)" --> agent
  attempts -- nie --> save --> awaitH

  classDef code fill:#EEEDFE,stroke:#534AB7,color:#3C3489
  classDef model fill:#FAECE7,stroke:#993C1D,color:#712B13
  classDef status fill:#F1EFE8,stroke:#5F5E5A,color:#444441
```

## Orkiestrator: powroty z Awaiting input i awarie

Wszystkie ścieżki kończą się powrotem zadania do Ready, ale z innym kontekstem.

```mermaid
flowchart LR
  q["Pytanie agenta<br/><small>Awaiting input</small>"]:::status --> a["Odpowiedź<br/><small>decyzja projektu</small>"]:::user --> s1["Ta sama sesja<br/><small>licznik bez zmian</small>"]:::code
  e["Wyczerpane próby<br/><small>Awaiting input</small>"]:::status --> h["Wskazówka<br/><small>od użytkownika</small>"]:::user --> s2["Nowa sesja<br/><small>licznik od zera + historia porażek</small>"]:::code
  f["Awaria agenta<br/><small>HarnessError</small>"]:::status --> r["Ponowienia<br/><small>2 s, 10 s, 30 s</small>"]:::code --> p["Ready + pauza projektu<br/><small>podejście nie przepada</small>"]:::code

  classDef code fill:#EEEDFE,stroke:#534AB7,color:#3C3489
  classDef user fill:#E1F5EE,stroke:#0F6E56,color:#085041
  classDef status fill:#F1EFE8,stroke:#5F5E5A,color:#444441
```

## Praca w tle i postęp na żywo (ADR-0008)

```
przeglądarka ──POST──► API ──► tabela commands (inbox)
                                   │
                         worker projektu (jedyny, kto zmienia stan)
                           ├─ polecenia czatu → ProjectFlow (wywiad, planista)
                           └─ budowa → Orkiestrator (jedno zadanie na krok)
                                   │ każdy krok i każde zdarzenie agenta
                                   ▼
                             tabela events ──► szyna w pamięci ──► SSE ──► przeglądarka
                                                (powiadomienie)     (czyta z bazy po Last-Event-ID)
```

W przeglądarce (ADR-0009) klient SSE nie składa widoków sam: po zdarzeniu prosi serwer
o świeży fragment HTML (czat, tablica, karta zadania), a narrację dopisuje jako tekst.

Przy starcie Specflow uzgadnia stan (przerwane zadania wracają do Ready, przerwane polecenia
są wznawiane). Narrację dla użytkownika składa kod (`web/narration.py`), nie model.

## Co jest AI, a co kodem

| Element | Kto | Wynik |
|---|---|---|
| Agent wywiadu | LLM (w F00 przez OpenCode, bez narzędzi) | Odpowiedzi → `/speckit.constitution`, `/speckit.specify`, `/speckit.clarify` |
| Agent planisty | LLM w harnessie | `plan.md`, `data-model.md`, `tasks.md` |
| Builder DAG | **kod** | Graf zadań w bazie, po walidacji |
| Orkiestrator | **kod** | Kolejność, limity, statusy |
| Worker, odzyskiwanie po awarii, narracja postępu | **kod** | Polecenia po kolei, wznowienia, opis zdarzeń dla użytkownika |
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
