# Specflow i laboratorium w Dockerze

Osobny projekt compose **`specflow-lab`**, który można postawić obok innych stacków na tym samym
serwerze albo na własnym komputerze (Docker Desktop). Decyzje: ADR-0010.

| Serwis | Obraz | Rola |
|---|---|---|
| `specflow` | `specflow:f00` (`specflow.Dockerfile`) | interfejs, workery, weryfikacja; port tylko na `127.0.0.1:8000` |
| `opencode` | `specflow-lab:f00` (`Dockerfile`) | serwer agenta OpenCode **v2.2.5**; dostępny tylko w sieci compose |
| `lab` | `specflow-lab:f00` | ręczna konsola: testy, nagrywarka, uruchamianie zbudowanej aplikacji |

| Wolumen | Kto widzi | Zawartość |
|---|---|---|
| `projects` | specflow, opencode, lab (`/workspace`) | repozytoria projektów |
| `specflow-data` | **tylko** specflow (`/data`) | baza SQLite, eksporty. Agent jej nie widzi: nie może sam oznaczyć zadań jako Done |
| `opencode-home` | **tylko** opencode | logowanie do modelu (token ChatGPT) |
| `lab-home` | tylko lab | cache narzędzi |

## Izolacja

| Warstwa | Ustawienie |
|---|---|
| Osobny projekt compose | własna sieć `specflow-lab_lab`, własne wolumeny; nic wspólnego z innymi stackami |
| Tylko localhost | jedyny port to interfejs Specflow na `127.0.0.1`; OpenCode jest dostępny wyłącznie w sieci compose |
| Użytkownik bez uprawnień | wszystko działa jako `agent`, nie root |
| `read_only: true` | obraz tylko do odczytu; zapis wyłącznie w wolumenach i `/tmp` |
| `cap_drop: [ALL]`, `no-new-privileges` | brak dodatkowych uprawnień jądra i eskalacji |
| Limity | pamięć, CPU, liczba procesów: agent nie zagłodzi innych usług |
| Brak `docker.sock` | kontenery nie mogą sterować Dockerem |
| Wolumen `projects` | agent widzi tylko projekty, nie dysk serwera |
| (zalecane) gVisor | patrz niżej |

Sieć wychodząca jest w F00 otwarta (model, pakiety). Lista dozwolonych adresów: F05/F08.
Kontener `lab` ma dostęp do zapisu w repo (`/app`), bo tam piszesz kod i fikstury.

**Znane ryzyko F00:** agent wykonuje polecenia w kontenerze `opencode`, w którym jest też token
do modelu. Agent zmanipulowany treścią, którą czyta (prompt injection), mógłby go odczytać.
Docelowo polecenia agenta pójdą do osobnego kontenera bez sekretów (ROADMAP).

## Uruchomienie (własny komputer albo serwer)

Wymagany Docker: na macOS i Windows **Docker Desktop**, na serwerze Docker Engine z pluginem
compose. Polecenia działają w terminalu macOS i Linuksa.

### 1. Kod i ustawienia

```bash
git clone git@gitlab.com:none9324545/specflow.git specflow
#   albo z pliku: git clone specflow.bundle specflow
cd specflow/docker

cp .env.example .env
# losowe hasło serwera OpenCode i Twój UID/GID (sed -i.bak działa na macOS i Linuksie)
sed -i.bak "s/^OPENCODE_SERVER_PASSWORD=.*/OPENCODE_SERVER_PASSWORD=$(openssl rand -hex 24)/" .env
sed -i.bak "s/^AGENT_UID=.*/AGENT_UID=$(id -u)/; s/^AGENT_GID=.*/AGENT_GID=$(id -g)/" .env
rm .env.bak
```

### 2. Obrazy

```bash
docker compose build          # pierwszy raz kilka minut
```

### 3. Logowanie OpenCode do planu ChatGPT (jednorazowo)

```bash
docker compose run --rm opencode opencode auth login
```

Wybierz **OpenAI**, a potem **ChatGPT Pro/Plus (headless)**. Kontener nie ma przeglądarki, więc
OpenCode pokaże link i kod: otwórz link w przeglądarce na komputerze, zaloguj się do ChatGPT
i wpisz kod. Wariant „browser” nie zadziała w kontenerze (czeka na odpowiedź na `localhost`
wewnątrz kontenera). Logowanie zostaje w wolumenie `opencode-home`.

### 4. Domyślny model (jednorazowo)

Specflow w F00 nie wybiera modelu: używa domyślnego modelu OpenCode (ADR-0010, M6b).
Najpierw sprawdź dokładne nazwy modeli dostępnych w Twoim planie:

```bash
docker compose run --rm opencode opencode models openai
```

Potem zapisz wybrany model (przykład: `openai/gpt-5.4` - dobry kompromis jakości i limitów
planu Plus; przy wyczerpywaniu limitów przejdź na mniejszy wariant, np. `-mini`):

```bash
docker compose run --rm opencode sh -c 'mkdir -p ~/.config/opencode && printf "%s\n" \
  "{\"\$schema\": \"https://opencode.ai/config.json\", \"model\": \"openai/gpt-5.4\"}" \
  > ~/.config/opencode/opencode.json && cat ~/.config/opencode/opencode.json'
```

### 5. Start

```bash
docker compose up -d
docker compose ps             # specflow: healthy
```

Interfejs: **http://localhost:8000**. Na serwerze port jest tylko na `127.0.0.1` serwera,
więc z laptopa łączysz się tunelem SSH:

```bash
ssh -L 8000:127.0.0.1:8000 uzytkownik@serwer      # potem w przeglądarce http://localhost:8000
```

Specflow w F00 nie ma logowania: kto ma dostęp do tego portu, może zlecać agentowi pracę.
Dlatego nigdy nie wystawiaj go na publiczny adres.

## Praca w laboratorium

```bash
docker compose exec lab bash

# w kontenerze lab (katalog /app = repo):
uv sync
uv run pytest -q
uv run python -m specflow.harness.opencode.record \
    --dir /workspace/smoke --out tests/fixtures/opencode/smoke.jsonl
```

Nagranie trafia do Twojej kopii repo (`tests/fixtures/opencode/smoke.jsonl`, katalog repo jest
zamontowany w `lab` jako `/app`). Wyślij mi ten plik: na jego podstawie potwierdzimy mapowanie
zdarzeń OpenCode (etap 0 pierwszego przebiegu, M6b). `uv sync` w `lab` tworzy w repo katalog
`.venv` dla Linuksa - jest w `.gitignore`, nie przeszkadza.

## Eksport diagnostyczny przebiegu

Po każdym etapie pierwszego prawdziwego przebiegu (ROADMAP: M6b) wyślij mi eksport:

```bash
docker compose exec specflow specflow export 1 -o /data/export-1.zip
docker compose cp specflow:/data/export-1.zip .
```

W pliku są czat, zdarzenia, zadania, runy z promptami i historia gita projektu. Ustawień
i tokenów nie ma, a hasło OpenCode jest zamieniane na `***`.

## Obejrzenie zbudowanej aplikacji (lab)

```bash
docker compose run --rm -p 127.0.0.1:8001:8000 -w /workspace/0001-lista-zadan lab \
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8000      # http://localhost:8001
```

## gVisor (zalecane na współdzielonym serwerze)

Na Docker Desktop (własny komputer) gVisor nie jest dostępny i nie jest potrzebny: kontenery
i tak działają w osobnej maszynie wirtualnej.

Demon Dockera działa jako root, więc ucieczka z kontenera oznaczałaby dostęp do całego serwera,
także do innych stacków. gVisor przechwytuje wywołania systemowe kontenera we własnym jądrze
w przestrzeni użytkownika i dokłada dodatkową barierę. Włącza się go tylko dla naszych serwisów.

```bash
# instalacja: https://gvisor.dev/docs/user_guide/install/
sudo runsc install                 # dopisuje runtime "runsc" do /etc/docker/daemon.json
sudo systemctl restart docker      # UWAGA: restartuje też kontenery innych stacków
```

Potem odkomentuj `runtime: runsc` w `compose.yaml` i `docker compose up -d`.

## Sprzątanie

```bash
docker compose down                 # zatrzymanie
docker compose down -v              # + usunięcie wolumenów (projekty, logowanie do modelu)
```
