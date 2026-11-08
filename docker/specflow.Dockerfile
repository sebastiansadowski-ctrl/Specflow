# Obraz aplikacji Specflow (interfejs, workery, weryfikacja przez API OpenCode).
# Budowany z katalogu głównego repo (compose: context ..), uruchamiany jako `agent` (UID 1000)
# - ten sam UID co agent w kontenerze OpenCode, więc obie strony mogą zmieniać pliki projektów.
FROM python:3.12-slim-bookworm

ARG SPEC_KIT_VERSION=v1.3.0
ARG AGENT_UID=1000
ARG AGENT_GID=1000

ENV UV_TOOL_DIR=/opt/uv/tools \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/specflow/.venv \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

# Spec Kit CLI w przypiętej wersji: `specify init` robi Specflow (krok deterministyczny).
RUN uv tool install specify-cli \
        --from "git+https://github.com/github/spec-kit.git@${SPEC_KIT_VERSION}" \
    && chmod -R a+rX /opt/uv \
    && specify --help > /dev/null

WORKDIR /opt/specflow
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv sync --no-dev --no-editable \
    && /opt/specflow/.venv/bin/specflow --help > /dev/null

RUN groupadd --gid "${AGENT_GID}" agent \
    && useradd --create-home --uid "${AGENT_UID}" --gid agent --shell /bin/bash agent \
    && mkdir -p /data /workspace \
    && chown agent:agent /data /workspace \
    && git config --system --add safe.directory '*'

USER agent
ENV PATH=/opt/specflow/.venv/bin:$PATH \
    HOME=/tmp/home \
    SPECFLOW_HOST=0.0.0.0 \
    SPECFLOW_PORT=8000 \
    SPECFLOW_DATA_DIR=/data \
    SPECFLOW_PROJECTS_DIR=/workspace \
    SPECFLOW_OPENCODE_CONTAINER_ROOT=/workspace
WORKDIR /data
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["specflow", "serve"]
