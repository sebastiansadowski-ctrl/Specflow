# Docker: agent OpenCode

Obraz z OpenCode **v2.2.5** (przypięta wersja; adapter jest pisany pod jej API `/api/...`).
Agent widzi wyłącznie `var/projects/` zamontowane jako `/workspace`.

## Pierwsze uruchomienie

```bash
# 1. Spec Kit na hoście (Specflow sam wywołuje `specify init` w katalogu projektu)
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git@v1.3.0

# 2. Zbuduj obraz i zaloguj się do planu ChatGPT wewnątrz kontenera (jednorazowo;
#    dane logowania zostają w wolumenie opencode-data)
cd docker
docker compose build
docker compose run --rm opencode opencode auth login     # wybierz OpenAI → ChatGPT Plus/Pro

# 3. Uruchom serwer agenta
docker compose up -d
```

## Test dymny i nagranie zdarzeń

Z katalogu głównego repo, przy działającym kontenerze:

```bash
uv run python -m specflow.harness.opencode.record \
    --password specflow-local \
    --dir var/projects/smoke \
    --out tests/fixtures/opencode/smoke.jsonl
```

Skrypt tworzy sesję z profilem `implementer`, prosi agenta o prosty plik i zapisuje surowe
zdarzenia do JSONL. Wyślij mi ten plik (albo zrób commit): na jego podstawie dopasuję
mapowanie do tego, co OpenCode naprawdę wysyła, a CI będzie je sprawdzać bez uruchamiania
OpenCode.

## Uwagi

- Sieć w kontenerze jest w F00 otwarta (agent instaluje pakiety i łączy się z modelem).
  Lista dozwolonych adresów: F05/F08.
- Reguły uprawnień (profil agenta) są przekazywane przy tworzeniu sesji przez API,
  bez plików konfiguracyjnych. Twardą granicą jest kontener, nie reguły.
