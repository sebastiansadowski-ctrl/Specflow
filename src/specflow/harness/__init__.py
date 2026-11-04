"""Adaptery harnessu (M2).

Jeden interfejs (sesja, prompt, strumień zdarzeń, anulowanie) i implementacje:
- `mock`     - udawany agent ze scenariuszami, do testów i CI,
- `opencode` - `opencode serve` w kontenerze Docker, sterowany przez HTTP.
Reszta systemu nie wie, który agent działa pod spodem (patrz docs/adr/0002).
"""
