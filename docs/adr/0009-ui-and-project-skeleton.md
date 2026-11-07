# ADR-0009: Interfejs zależny od etapu i szkielet projektu tworzony przez kod

- Status: przyjęte
- Data: 2026-11-06

## Kontekst

M5b daje nietechnicznemu użytkownikowi interfejs w przeglądarce. W różnych etapach liczy się
co innego: w wywiadzie i planowaniu rozmowa, w budowie postęp zadań. Przy okazji wyszła luka
w weryfikacji: konfiguracja pytest jest plikiem chronionym (ADR-0005), ale w przepływie Spec
Kit tworzyłby ją agent w zadaniu Setup.

## Decyzje

1. **Ekran zależny od etapu.** E1–E2 (wywiad, planowanie): szeroki czat i podgląd dokumentów.
   E3–E4 (budowa): kanban na pierwszym planie, czat zwinięty z boku, pasek „Co się dzieje”
   pod tablicą, szczegóły zadania po kliknięciu karty. Zmiana fazy na budowę przeładowuje stronę.
2. **Bramki jako karty w czacie** (podsumowanie składane przez kod, ADR-0007) z przyciskami
   „Zatwierdzam” i „Chcę coś zmienić” (przeniesienie do pola wiadomości). Zablokowane
   planowanie to karta z prośbą o wskazówkę.
3. **Log agenta w dwóch miejscach:** wspólny pasek projektu i pełny log zadania na karcie.
   Narracja z ADR-0008; szczegóły (myśli agenta, błędy narzędzi) za przełącznikiem.
   Odpowiedź na pytanie agenta tylko na karcie zadania.
4. **htmx + mały klient SSE** (`static/app.js`): serwer renderuje fragmenty HTML, a klient po
   zdarzeniu z SSE prosi o odświeżenie właściwego fragmentu (`hx-trigger="sf:… from:body"`,
   `hx-sync="this:replace"`). Narrację klient dopisuje przez `textContent`. Bez stylów,
   skryptów i `on*=` inline (CSP); HTML z Markdownu wstawia tylko filtr `md`.
5. **Odrzucone polecenie nie kasuje tekstu:** fragment z komunikatem i nagłówek
   `X-Specflow-Rejected`, po którym klient nie czyści formularza.
6. **Szkielet projektu Python tworzy kod Specflow** (`workspace/scaffold.py`) przy zakładaniu
   projektu: `pyproject.toml` (zależności stosu, grupa dev z pytest, `[tool.pytest.ini_options]`),
   `.gitignore`, pakiet `app/`, katalog `tests/`. Briefy planisty mówią, że szkielet istnieje
   i że nie wolno zmieniać konfiguracji pytest. Agent nie może więc „poprawić” konfiguracji
   testów, żeby przeszły, a weryfikacja nie potrzebuje wyjątku dla zadania Setup.

## Konsekwencje

- Nazwy kolumn kanbanu zostają po angielsku (jak w specyfikacji produktu); reszta UI po polsku.
- Układ jest desktopowy; na wąskim ekranie kolumny układają się jedna pod drugą (podstawowo).
  Pełna wersja mobilna: później.
- Przeładowanie strony przy wejściu w budowę jest prostsze niż przebudowa układu w JS
  i nie gubi stanu, bo stan jest w bazie.
