# ADR-0005: Sesje agenta, uprawnienia bez `ask`, raport końcowy w JSON

- Status: przyjęte
- Data: 2026-11-05

## Kontekst

M2 łączy system z prawdziwym agentem (OpenCode). Trzeba zdecydować: ile kontekstu agent
niesie między zadaniami, co może robić bez człowieka i jak kod rozpoznaje wynik jego pracy.

## Decyzje

1. **Świeża sesja na każde zadanie; Rework w tej samej sesji.**
   Kontekst między zadaniami płynie przez: (a) repozytorium projektu - wspólną pamięć,
   (b) artefakty Spec Kit - kontrakt ustalony z góry, (c) notatki przekazania `notes`
   z raportów **bezpośrednich zależności w DAG-u** (prompt składany w M3).
2. **Uprawnienia bez `ask`.** Profile (`implementer`, `test_writer`, `planner`,
   `interviewer`) to wyłącznie reguły `allow`/`deny`, przekazywane przy tworzeniu sesji.
   Wygrywa ostatnia pasująca reguła; zakazy bezpieczeństwa (`git push`, `.env`, `doom_loop`,
   katalogi zewnętrzne) są na końcu. Wykonawca nie może edytować testów.
   Twardą granicą jest kontener Docker z jednym zamontowanym katalogiem; reguły to porządek,
   nie kontrola dostępu (agent może je obejść przez bash).
3. **Raport końcowy w JSON:** `{"status": "done"|"blocked", "summary", "question", "notes"}`.
   Kod go waliduje (`blocked` wymaga pytania). Brak lub zły format raportu to błąd, nie sukces.
   Raport nie jest dowodem wykonania - o `Done` decyduje weryfikacja (ADR-0001).
4. **Sieć w kontenerze otwarta w F00** (pakiety, model). Lista dozwolonych adresów: F05/F08.
5. **Przypięte wersje:** OpenCode **v2.2.5** (API `/api/...`), Spec Kit **v1.3.0**.
   Adapter jest pisany pod specyfikację OpenAPI przypiętej wersji; zmiany API OpenCode
   wymagają zmian tylko w `specflow.harness.opencode`.

## Ochrona testów (defense in depth)

Instrukcja w prompcie → reguła `deny edit tests/**` w profilu → kontrola diffu
w weryfikacji (M3). Mock celowo NIE egzekwuje reguł, żeby testy sprawdzały ostatnią warstwę.

## Konsekwencje

- Świeże sesje są tańsze i mniej podatne na „zatrucie” kontekstu, ale agent musi sam
  czytać kod poprzednich zadań; jakość zależy od dobrych artefaktów Spec Kit.
- Brak `ask` oznacza, że zablokowane narzędzie kończy się błędem narzędzia, a agent
  musi poradzić sobie inaczej albo zgłosić `blocked`.
- Mapowanie zdarzeń OpenCode trzeba potwierdzić nagraniem z prawdziwego serwera
  (`specflow.harness.opencode.record`) - nagrania stają się fiksturami testów.
