# Laboratorium Specflow w Dockerze

Osobny projekt compose **`specflow-lab`**, który można postawić obok innych stacków na tym samym
serwerze. Dwa serwisy z jednego obrazu:

| Serwis | Rola |
|---|---|
| `opencode` | serwer agenta OpenCode **v2.2.5** (adapter jest pisany pod jej API `/api/...`) |
| `lab` | powłoka, w której bezpiecznie wykonujesz polecenia: testy, nagrywarka, później Specflow |

## Izolacja

| Warstwa | Ustawienie |
|---|---|
| Osobny projekt compose | własna sieć `specflow-lab_lab`, własne wolumeny; nic wspólnego z innymi stackami |
| Brak portów na zewnątrz | `lab` łączy się z `opencode` po sieci wewnętrznej; nic nie jest wystawione na hosta |
| Użytkownik bez uprawnień | wszystko działa jako `agent`, nie root |
| `read_only: true` | obraz tylko do odczytu; zapis wyłącznie w wolumenach i `/tmp` |
| `cap_drop: [ALL]`, `no-new-privileges` | brak dodatkowych uprawnień jądra i eskalacji |
| Limity | pamięć, CPU, liczba procesów: agent nie zagłodzi innych usług |
| Brak `docker.sock` | kontenery nie mogą sterować Dockerem |
| Wolumen `projects` | agent widzi tylko projekty, nie dysk serwera |
| (zalecane) gVisor | patrz niżej |

Sieć wychodząca jest w F00 otwarta (model, pakiety). Lista dozwolonych adresów: F05/F08.
Kontener `lab` ma dostęp do zapisu w repo (`/app`), bo tam piszesz kod i fikstury.

## Uruchomienie na serwerze

```bash
# repo w dowolnym miejscu, np. obok innych projektów
sudo mkdir -p /opt/specflow && sudo chown "$USER" /opt/specflow
git clone https://github.com/sebastiansadowski-ctrl/Specflow.git /opt/specflow
cd /opt/specflow/docker

cp .env.example .env
sed -i "s/^OPENCODE_SERVER_PASSWORD=.*/OPENCODE_SERVER_PASSWORD=$(openssl rand -hex 24)/" .env
sed -i "s/^AGENT_UID=.*/AGENT_UID=$(id -u)/; s/^AGENT_GID=.*/AGENT_GID=$(id -g)/" .env

docker compose build
docker compose run --rm opencode opencode auth login      # jednorazowo: OpenAI → ChatGPT Plus/Pro
docker compose up -d
docker compose ls                                         # obok bw-merger-ovh: specflow-lab
```

### Logowanie bez przeglądarki

Jeśli `opencode auth login` pokaże kod do wpisania, otwórz podany link na laptopie.
Jeśli pokaże link z `localhost:<port>`, potrzebny jest tunel. Daj znać, jaki port pokazał,
dopasujemy jednorazowe wystawienie go na `127.0.0.1` serwera i `ssh -L` z laptopa.

## Praca w laboratorium

```bash
docker compose exec lab bash

# w kontenerze lab (katalog /app = repo):
uv sync
uv run pytest -q
uv run python -m specflow.harness.opencode.record \
    --dir /workspace/smoke --out tests/fixtures/opencode/smoke.jsonl
```

Nagranie trafia do repo na serwerze (`tests/fixtures/opencode/smoke.jsonl`). Zrób z niego commit
albo wyślij mi plik: na jego podstawie potwierdzimy mapowanie zdarzeń.

## gVisor (zalecane na współdzielonym serwerze)

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
