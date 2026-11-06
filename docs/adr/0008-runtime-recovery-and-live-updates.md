# ADR-0008: Praca w tle, odzyskiwanie po awarii i postęp na żywo

- Status: przyjęte
- Data: 2026-11-06

## Kontekst

M5 wystawia przepływ (wywiad, planowanie, budowa) przez przeglądarkę. Tura modelu trwa
sekundy, planowanie minuty, zadanie agenta do 30 minut. Interfejs musi widzieć postęp na
żywo, a restart lub awaria serwera nie może zgubić pracy ani zostawić projektu w stanie
niespójnym. Użytkownik jest nietechniczny, więc opis postępu musi być zrozumiały i prawdziwy.

## Decyzje

1. **Stan żyje w bazie i w gicie; sesja modelu to tylko pamięć podręczna.** Wywiad dostaje
   pełny stan w każdym prompcie; po awarii zadanie agenta zaczyna się od nowa w czystym
   workspace. Nie zakładamy, że sesja OpenCode przeżyje restart.
2. **Skrzynka poleceń (inbox) + jeden worker na projekt.** HTTP tylko dopisuje polecenia
   (`commands`: start, message, approve, answer, pause, resume) i czyta stan. Stan projektu
   zmienia wyłącznie worker: polecenia po kolei, między nimi jedno zadanie orkiestratora.
   Naraz może czekać tylko jedno polecenie czatu (inaczej 409).
3. **At-least-once z wznawianiem.** Polecenie jest oznaczane jako wykonane dopiero po
   wykonaniu, a licznik `attempts` mówi, czy poprzednie wykonanie przerwała awaria. Przerwane
   polecenie czatu jest wznawiane (`ProjectFlow.resume_interrupted`), nie powtarzane na ślepo;
   wiadomości czatu są idempotentne (`command_id`). Po 3 przerwaniach polecenie kończy się błędem.
4. **Dziennik kroków planisty** (`planning_step`): ustawiany przed krokiem, czyszczony po nim.
   Komendy Spec Kit nadpisują pliki, więc przerwany krok można bezpiecznie powtórzyć.
5. **Stan docelowy budowy w bazie** (`run_state`: idle / running / paused). Pauza działa
   między zadaniami (bieżące jest dokańczane). Awaria agenta to osobne `paused_reason` (ADR-0006).
6. **Uzgodnienie przy starcie (recovery)** dla zadań w In progress / Verification / Rework:
   zatrzymanie starej sesji agenta, zapis zmian na gałęzi `attempt/<zadanie>-<run>-interrupted`,
   powrót workspace do stanu sprzed podejścia, run `interrupted`, zadanie do Ready bez zużycia
   podejścia (nowe przejścia Verification/Rework → Ready dla orkiestratora).
7. **Łagodne zamykanie:** workery kończą bieżący krok (domyślnie do 20 s), potem są przerywane,
   a przerwana praca przechodzi tę samą ścieżkę co po awarii. Jedna ścieżka kodu dla obu przypadków.
8. **SQLite w F00:** WAL, `synchronous=FULL`, `busy_timeout=5000`. Zasada w kodzie: żadna
   transakcja zapisu nie jest otwarta podczas `await` na agencie - pilnuje tego
   `CommittingHarness` (commit przed każdym wywołaniem agenta i każdym kolejnym zdarzeniem).
   Bez tego jeden wątek pętli asyncio zakleszczyłby się na blokadzie zapisu SQLite.
9. **Postęp na żywo: SSE z zapisem do bazy.** Zdarzenie najpierw trafia do `events`, potem
   szyna w pamięci budzi strumienie, a te czytają z bazy wszystko po ostatnim id. `id` SSE
   = id wiersza, więc `Last-Event-ID` pozwala nadrobić zaległości po zerwaniu połączenia.
   Odrzucone: polling (opóźnienie, puste zapytania), WebSocket (więcej kodu, nie potrzebujemy
   kanału od klienta).
10. **Narracja składana przez kod** (`web/narration.py`) z naszego słownika zdarzeń, w dwóch
    poziomach: główny i szczegóły. Nie streszczamy pracy agenta modelem: koszt, opóźnienie
    i ryzyko zmyśleń.
11. **Treść od modelu jest niezaufana w przeglądarce:** Markdown bez surowego HTML, linki tylko
    `http(s)`/`mailto`/`#`, bez obrazków; artefakty tylko z listy i tylko wewnątrz workspace
    (po rozwiązaniu symlinków); nagłówek CSP `script-src 'self'` (htmx z własnego serwera,
    bez `eval`).
12. **Konfiguracja raz przy starcie** (`Settings`): argumenty > `SPECFLOW_*` > `.env` > domyślne.
    Harness wybiera korzeń kompozycji (`bootstrap.py`). Tryb `mock` = nagrane demo
    (`harness/demo.py`), które służy też za test end-to-end.

## Konsekwencje

- Odpowiedź na pytanie agenta w innym zadaniu czeka na koniec bieżącego zadania. W F00 agent
  jest jeden, więc nie tracimy przepustowości; przy równoległych agentach (F10) worker per
  zadanie albo kolejka per agent.
- Szyna działa w jednym procesie, a SQLite na jednym serwerze. Wiele instancji (F04/F05):
  Postgres i np. `LISTEN/NOTIFY`; kod czyta zdarzenia z bazy, więc zmieni się tylko szyna.
- Zdarzenia agenta zapisujemy wszystkie (narzędzia, wiadomości), co rośnie z czasem;
  retencja i archiwizacja: F04.
- Trwały silnik workflow (np. Temporal) dopiero w F05; do tego czasu jego rolę pełni
  "zapis po każdym kroku + uzgodnienie przy starcie".
