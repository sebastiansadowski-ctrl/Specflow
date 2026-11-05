# Obraz "laboratorium" Specflow: agent OpenCode + Python/uv + Spec Kit.
# Ten sam obraz uruchamia dwa serwisy (patrz compose.yaml):
#   - opencode: serwer agenta,
#   - lab:      powłoka do bezpiecznego wykonywania poleceń (Specflow, testy, nagrywarka).
# Wszystko działa jako nieuprzywilejowany użytkownik `agent`.
FROM node:22-bookworm-slim

ARG OPENCODE_VERSION=2.2.5
ARG SPEC_KIT_VERSION=v1.3.0
ARG PYTHON_VERSION=3.12
ARG AGENT_UID=1000
ARG AGENT_GID=1000

# Python i narzędzia uv instalujemy poza katalogiem domowym, żeby działały
# przy systemie plików tylko do odczytu i wolumenie na /home/agent.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_TOOL_DIR=/opt/uv/tools \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

RUN uv python install "${PYTHON_VERSION}" \
    && ln -s "$(uv python find "${PYTHON_VERSION}")" /usr/local/bin/python3 \
    && ln -s /usr/local/bin/python3 /usr/local/bin/python \
    && uv tool install --python "${PYTHON_VERSION}" specify-cli \
        --from "git+https://github.com/github/spec-kit.git@${SPEC_KIT_VERSION}" \
    && chmod -R a+rX /opt/uv \
    && specify --help > /dev/null

RUN npm install -g "opencode-ai@${OPENCODE_VERSION}" \
    && npm cache clean --force \
    && opencode --version

# Obraz node ma użytkownika `node` z UID 1000 - zastępujemy go użytkownikiem `agent`
# z UID/GID zgodnym z właścicielem repo na serwerze (pliki w /app mają właściwego właściciela).
RUN userdel --remove node 2>/dev/null || true \
    && groupadd --gid "${AGENT_GID}" agent \
    && useradd --create-home --uid "${AGENT_UID}" --gid agent --shell /bin/bash agent \
    && mkdir -p /workspace /app \
    && chown agent:agent /workspace /app \
    && git config --system --add safe.directory '*'

USER agent
WORKDIR /workspace

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]
