# ADR-0010: Uruchomienie w Dockerze (Specflow + OpenCode)

- Status: przyjęte
- Data: 2026-11-07

## Kontekst

Pierwszy prawdziwy przebieg (M6b) odbywa się najpierw na komputerze użytkownika (Docker
Desktop), docelowo na serwerze OVH współdzielonym z innym stackiem. Specflow w F00 nie ma
logowania, a agent wykonuje dowolny kod.

## Decyzje

1. **Jeden projekt compose, prywatna sieć.** Specflow łączy się z `http://opencode:4096`;
   port OpenCode nie jest wystawiony nigdzie. Hasło serwera OpenCode z `docker/.env`.
   (Odrzucone: Specflow poza Dockerem z portem OpenCode na hoście - każdy proces na serwerze
   mógłby wołać agenta.)
2. **Interfejs tylko na localhost:** `127.0.0.1:8000`; na serwerze dostęp tunelem SSH.
   Bez logowania wystawienie portu publicznie oznaczałoby zdalne wykonywanie kodu dla każdego.
3. **Wspólny wolumen projektów pod tą samą ścieżką** (`/workspace`) w Specflow, OpenCode i lab;
   mapowanie ścieżek w adapterze jest tożsamościowe.
4. **Ten sam UID (1000) we wszystkich kontenerach:** obie strony zmieniają pliki projektów
   (agent: kod, Specflow: git reset/clean, commity), a git nie odmawia pracy na repo.
5. **Baza Specflow w osobnym wolumenie (`specflow-data`), niewidocznym dla agenta.** Inaczej
   agent mógłby zmienić statusy zadań z pominięciem weryfikacji.
6. **`specify init` wykonuje Specflow** (Spec Kit CLI w obrazie Specflow, wersja przypięta).
7. **Wolumeny nazwane** zamiast katalogów hosta.
8. **`lab` zostaje** jako ręczna konsola (testy, nagrywarka, uruchomienie zbudowanej aplikacji).
9. **Eksport diagnostyczny** (`specflow export`): czat, zdarzenia, zadania, runy z promptami,
   historia gita; bez ustawień i tokenów, hasło OpenCode zamieniane na `***`. To sposób
   przekazywania wyników przebiegu do analizy bez dawania dostępu do serwera.
10. **Twarde ustawienia kontenerów** jak w laboratorium: `read_only`, `cap_drop: ALL`,
    `no-new-privileges`, limity, brak `docker.sock`.

## Konsekwencje

- Znane ryzyko F00: polecenia agenta działają w kontenerze z tokenem modelu. Docelowo osobny
  kontener wykonawczy bez sekretów i z ograniczonym internetem (ROADMAP, „Pomysły na później”).
- Sieć wychodząca OpenCode jest otwarta (model, pakiety); lista dozwolonych adresów później.
- Obrazy nie są budowane w CI; poprawność compose sprawdza `docker compose config`.
