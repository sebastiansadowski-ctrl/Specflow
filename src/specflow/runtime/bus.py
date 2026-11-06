"""Szyna powiadomień w pamięci: "w projekcie N jest coś nowego w bazie".

Szyna nie przenosi danych - źródłem prawdy jest tabela `events` (zapis do bazy, potem
powiadomienie). Odbiorca (strumień SSE, worker) po sygnale czyta z bazy wszystko po swoim
ostatnim id, więc żadne zdarzenie nie ginie, nawet gdy sygnał przyjdzie w trakcie odczytu.

Działa w jednym procesie. Przy wielu instancjach (F04/F05) podmienimy ją na np.
Postgres LISTEN/NOTIFY - reszta kodu się nie zmieni.
"""

import asyncio
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager


class EventBus:
    def __init__(self) -> None:
        self._waiters: dict[int, set[asyncio.Event]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def notify(self, project_id: int) -> None:
        """Bezpieczne także z innego wątku (np. synchroniczny kod w puli wątków)."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        loop = self._loop
        if loop is not None and not loop.is_closed() and running is not loop:
            loop.call_soon_threadsafe(self._wake, project_id)
        else:
            self._wake(project_id)

    @contextmanager
    def subscribe(self, project_id: int) -> Iterator[asyncio.Event]:
        """Sygnał dla jednego odbiorcy. Wzorzec użycia: `clear()`, odczyt z bazy, `wait()`."""
        self._loop = asyncio.get_running_loop()
        signal = asyncio.Event()
        self._waiters[project_id].add(signal)
        try:
            yield signal
        finally:
            self._waiters[project_id].discard(signal)

    def subscribers(self, project_id: int) -> int:
        return len(self._waiters.get(project_id, ()))

    def _wake(self, project_id: int) -> None:
        for signal in self._waiters.get(project_id, ()):
            signal.set()
