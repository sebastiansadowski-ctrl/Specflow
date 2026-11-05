# ADR-0006: Pętla orkiestratora, weryfikacja w sandboxie agenta, obsługa porażek

- Status: przyjęte
- Data: 2026-11-05

## Kontekst

M3 łączy orkiestrator, agenta i weryfikację w działający przepływ. Trzeba ustalić, gdzie
uruchamiać testy kodu napisanego przez agenta, jak często weryfikować, ile podejść dać
agentowi i co robić po porażkach.

## Decyzje

1. **Weryfikacja w środowisku agenta przez `POST /api/shell`** (OpenCode; w Mocku podproces).
   Komenda działa bez udziału modelu, w tym samym kontenerze co agent. Zasada: nigdy nie
   uruchamiamy niezaufanego kodu tam, gdzie działa Specflow (`lab` ma zapis do repo Specflow).
2. **Weryfikacja nie ufa agentowi (reward hacking).** Kontrole: raport `done`, niepusty diff
   z gita, pliki chronione (`tests/**`, `conftest.py`, konfiguracja pytest, także
   `[tool.pytest]` w `pyproject.toml`), liczba testów nie spada, brak regresji względem
   ostatniego udanego zadania, testy się zbierają. Plik JUnit kasujemy przed uruchomieniem,
   żeby nie dało się podsunąć starego wyniku.
3. **Częstotliwość:** kontrole po każdym zadaniu; na końcu historyjki (Checkpoint ze Spec Kit)
   wszystkie testy historyjki muszą przejść. Zadania testowe: nowe testy mają się zbierać
   i nie przechodzić (faza "czerwona" TDD).
4. **Podział ról:** weryfikacja ocenia (werdykt + przycięta informacja zwrotna, maks. ok. 4000
   znaków); orkiestrator decyduje i wykonuje (Rework, Awaiting input).
5. **3 podejścia na zadanie** (licznik rośnie przy każdym wejściu do In progress). Rework
   w tej samej sesji z informacją zwrotną. Naruszenie plików chronionych: zmiany cofane od razu.
6. **Po wyczerpaniu prób:** zmiany zapisywane na gałęzi `attempt/<zadanie>-<run>`, workspace
   wraca do stanu bazowego, zadanie trafia do Awaiting input (`attempts_exhausted`).
   Wskazówka użytkownika → nowa sesja, licznik od zera, prompt z historią porażek.
7. **Pytanie agenta (`blocked`):** Awaiting input (`question`); odpowiedź trafia do tej samej
   sesji, licznik prób bez zmian. Odpowiedzi i wskazówki zapisujemy jako decyzje projektu.
8. **Awaria infrastruktury (`HarnessError`)** nie jest porażką zadania: ponowienia z przerwami;
   gdy awaria trwa, zmiany są cofane, zadanie wraca do Ready (nowe przejście
   In progress → Ready dla orkiestratora), projekt jest wstrzymywany.
9. **Obserwowalność:** każde podejście to wiersz `runs` (sesja, profil, wersja promptu,
   tokeny, koszt, wynik weryfikacji, gałąź próby).

## Konsekwencje

- Testy działają w środowisku, które agent może zmieniać; pozostaje ryzyko obejścia, którego
  kontrole nie wykryją (np. podmiana narzędzi w środowisku Pythona). Kolejne warstwy:
  recenzent LLM (F01) i akceptacja użytkownika.
- Wersja F00 zakłada projekty w Pythonie z pytest. Inne stosy wymagają konfigurowalnych
  komend weryfikacji (F01).
