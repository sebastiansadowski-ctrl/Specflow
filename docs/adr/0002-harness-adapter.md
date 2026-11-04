# ADR-0002: Dostęp do agentów przez wspólny interfejs adaptera

- Status: przyjęte
- Data: 2026-11-04

## Kontekst

Agentów (harnessów) jest wiele: OpenCode, Claude Agent SDK, Codex CLI, OpenHands.
Lokalnie mamy plan ChatGPT (OpenCode), w produkcji będą klucze API i być może inny harness.
Regulaminy i ceny dostawców zmieniają się szybko.

## Decyzja

Cały system rozmawia z agentem wyłącznie przez interfejs w `specflow.harness`
(sesja, prompt, strumień zdarzeń, anulowanie). Implementacje w F00: `mock` i `opencode`.
`claude_sdk` dochodzi w F02.

## Uzasadnienie

- Testy i CI bez konta i bez kosztów (adapter Mock ze scenariuszami).
- Wymiana dostawcy lub modelu to zmiana konfiguracji, nie przepisywanie orkiestratora.
- Ochrona przed ryzykiem platformowym (zmiany regulaminów subskrypcji).

## Konsekwencje

- Interfejs musi obejmować część wspólną harnessów; funkcje specyficzne (np. hooki Agent SDK)
  udostępniamy jako opcjonalne możliwości adaptera.
- Zdarzenia z harnessów mapujemy na własny, wspólny format zdarzeń.
