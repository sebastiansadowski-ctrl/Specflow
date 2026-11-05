# ADR-0004: Walidacja wyjścia modelu i reguły budowy DAG-u

- Status: przyjęte
- Data: 2026-11-05

## Kontekst

`tasks.md` pisze planista (LLM). Na jego podstawie kod buduje graf zadań i wykonuje
prawdziwe akcje. Wyjście modelu jest niezaufanym wejściem: może zawierać przykładowe zadania
z szablonu, placeholdery, zależności do nieistniejących zadań, cykle, konflikty plików
i odhaczone checkboxy (fantomowe ukończenia).

## Decyzja

1. **Format w F00:** tolerancyjny parser Markdownu (zgodność ze Spec Kit). W F01 dochodzi
   JSON od planisty i sprawdzanie zgodności obu wersji (hybryda).
2. **Walidacja warstwowa:** parser → schemat (identyfikatory, placeholdery) → graf
   (zależności, cykle, konflikty plików) → polityki (np. testy przed kodem).
   Wynik to ustrukturyzowane błędy (blokują) i ostrzeżenia (zapisywane).
3. **Stan checkboxa w pliku jest ignorowany.** Status pochodzi wyłącznie z bazy.
4. **Reguły zależności (wariant ostrożny):**
   - fazy: Setup → Foundational → każda historyjka osobno → Polish; historyjki nie zależą
     od siebie; fazy "other" i Polish czekają na wszystkie wcześniejsze;
   - w fazie: zadanie bez `[P]` jest barierą; zadanie `[P]` czeka na ostatnią barierę;
     podsekcja `###` też jest barierą;
   - jawne `(depends on T012)` dodają krawędzie;
   - zadania, które mogłyby iść równolegle, a dotykają tego samego pliku, są szeregowane.
5. **Zależność ≠ kolejność.** Priorytety historyjek to reguła harmonogramu
   (`execution_order`), nie krawędź grafu.
6. **Pętla naprawcza:** błędy trafiają do planisty jako numerowana lista (jak komunikaty
   kompilatora). Po wyczerpaniu prób (M4) plan trafia do **Awaiting input**.

## Konsekwencje

- Wariant ostrożny zmniejsza równoległość, ale w F00 i tak wykonujemy zadania po kolei.
- Zmiana formatu szablonu Spec Kit może wymagać zmian w parserze; testy opierają się na
  oryginalnym szablonie przypiętym w `tests/fixtures`.
