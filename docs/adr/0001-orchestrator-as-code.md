# ADR-0001: Orkiestrator jest kodem, a nie agentem LLM

- Status: przyjęte
- Data: 2026-11-04

## Kontekst

Orkiestrator wybiera kolejne zadania z DAG-u, pilnuje limitów czasu i liczby prób,
zmienia statusy kart i decyduje o Rework / Awaiting input. Można to zlecić agentowi LLM
(„multi-agent supervisor”) albo napisać jako zwykłą maszynę stanów.

## Decyzja

Orkiestrator to deterministyczna pętla i maszyna stanów w Pythonie. LLM jest wołany tylko
tam, gdzie potrzebna jest ocena: realizacja zadania (harness), recenzja (F01),
klasyfikacja porażki i przeplanowanie (F01).

## Uzasadnienie

- Decyzje orkiestratora są regułowe („zależności zrobione → Ready”); kod robi to bezbłędnie.
- Powtarzalność: ten sam stan wejściowy daje tę samą decyzję, łatwo testować i debugować.
- Koszt: brak tokenów zużywanych na oczywiste decyzje.
- Bezpieczeństwo: agent nie może „uznać” zadania za zrobione; `Done` wymaga przejścia weryfikacji.

## Konsekwencje

- Elastyczne decyzje (np. „czy to błąd kodu, czy brak informacji?”) trzeba jawnie wydzielić
  jako wywołania LLM z ustrukturyzowanym wynikiem, a kod je waliduje.
- Zmiana logiki przepływu to zmiana kodu, nie promptu.
