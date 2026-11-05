# Obraz workspace dla agenta: OpenCode (przypięta wersja) + narzędzia do budowania
# i testowania generowanych aplikacji. Agent widzi wyłącznie /workspace (montowany katalog
# projektów) - to twarda granica bezpieczeństwa (ADR-0005).
FROM node:22-bookworm-slim

ARG OPENCODE_VERSION=2.2.5

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3 python3-venv ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

RUN npm install -g "opencode-ai@${OPENCODE_VERSION}" && opencode --version

RUN useradd --create-home agent && mkdir -p /workspace && chown agent:agent /workspace
USER agent
WORKDIR /workspace

EXPOSE 4096
CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]
