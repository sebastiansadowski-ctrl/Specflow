# ADR-0007: Wywiad, bramki akceptacji i planowanie przez Spec Kit

- Status: przyjęte
- Data: 2026-11-06

## Kontekst

Użytkownik Specflow nie jest programistą. M4 zamienia rozmowę na artefakty Spec Kit
(konstytucja, `spec.md`, `plan.md`, `tasks.md`) i zadania na tablicy. Trzeba ustalić, co
robi model, a co kod, jak prowadzić rozmowę, kto wybiera technologię i jak pilnować jakości
artefaktów, które pisze LLM.

## Decyzje

1. **Fazy projektu to maszyna stanów w kodzie** (`domain/project_phase.py`):
   constitution → specify → (clarify) → plan → tasks → review → building → done. Przejścia
   wykonuje `ProjectFlow`, nie model. Z review można wrócić do specify (zmiana wymagań).
2. **Wywiad = slot filling z swobodą.** Lista slotów na etap jest w kodzie
   (`interview/slots.py`), a model w każdej turze zwraca JSON (`message`, `updates`,
   `stories`, `assumptions`, `clarifications`, `user_wants_to_finish`). Model może wyciągnąć
   wiele slotów z jednej wypowiedzi i pyta o jedną rzecz naraz. Kompletność ocenia kod.
   Użytkownik może skończyć wcześniej, ale wymagana jest co najmniej jedna historyjka
   z kryterium akceptacji (bez tego nie ma testów).
3. **Wyjście modelu jest niezaufane.** JSON tury jest walidowany (pydantic); nieznane sloty
   są ignorowane, odpowiedzi na pytania muszą pasować do otwartych pytań. Przy błędzie jedna
   tura naprawcza z opisem błędu, potem bezpieczna wiadomość zastępcza i stan bez zmian.
4. **Technologię ustala Specflow.** W F00 tylko Python 3.12, FastAPI + Jinja2, SQLite,
   pytest. Wywiad nie pyta o technologie. Profile stosów: pomysł na później (ROADMAP).
5. **Konstytucja** = domyślne zasady Specflow (Test-First, Simplicity, Clear Errors)
   + 2 pytania (dane osobowe, urządzenia). Dane osobowe dodają zasadę ochrony danych.
6. **Bramki akceptacji:** po wywiadzie (specyfikacja) i po planowaniu (plan). Podsumowania
   składa kod z danych wywiadu i zwalidowanego grafu zadań, nie model. Użytkownik akceptuje
   dokładnie to, co trafi do planisty. Wiadomość zamiast akceptacji wraca do wywiadu.
7. **Clarify po naszemu.** Nie używamy interaktywnego `/speckit.clarify`: `/speckit.specify`
   zostawia maks. 3 znaczniki `[NEEDS CLARIFICATION]`, kod je wyciąga, wywiad zadaje pytania
   prostym językiem, a planista wpisuje odpowiedzi do `spec.md` (maks. 2 próby).
8. **Język artefaktów:** treść po polsku, nagłówki Spec Kit i **Given**/**When**/**Then**
   po angielsku (parsery i szablony Spec Kit się nie psują).
9. **Planista = jedna sesja OpenCode** na całe planowanie (`/speckit.constitution`,
   `specify`, `plan`, `tasks`, `analyze`). Po każdej komendzie deterministyczne kontrole
   (`planning/checks.py`): placeholdery szablonu, liczba historyjek, Given w każdej, stos
   w planie. Jedna prośba o poprawkę na artefakt.
10. **`tasks.md`:** walidacja z ADR-0004 (testy przed implementacją) z pętlą naprawczą
    (maks. 2), potem `/speckit.analyze`; przy znaleziskach CRITICAL jedna automatyczna
    poprawka i ponowna walidacja.
11. **Gdy planowanie utknie**, projekt czeka na użytkownika (komunikat w czacie); jego
    wskazówka trafia do planisty, a krok, który się nie udał, jest powtarzany.
12. **Graf do kanbanu** trafia z bezpośrednimi zależnościami (redukcja przechodnia):
    gotowość zadań się nie zmienia, a notatki o zależnościach w promptach są krótsze.

## Konsekwencje

- Model nigdy nie decyduje o etapie, technologii ani o tym, co zobaczy użytkownik w bramce;
  błędy modelu kończą się naprawą albo czekaniem na człowieka, nie cichą degradacją.
- Wywiad i planista działają przez harness (w F00 OpenCode), więc koszt i jakość zależą od
  modelu w OpenCode. Bezpośrednie API: F02.
- Zmiana wymagań po bramce planu wraca do specify i powtarza planowanie w całości
  (przeplanowanie przyrostowe: F01).
- Kontrole artefaktów są heurystyczne (nagłówki, słowa kluczowe); nie gwarantują jakości
  treści, tylko łapią typowe usterki.
