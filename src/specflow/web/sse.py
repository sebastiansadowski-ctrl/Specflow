"""Strumień zdarzeń projektu (Server-Sent Events) z nadrabianiem po `Last-Event-ID`.

Kolejność (ADR-0008): zdarzenie najpierw trafia do bazy, potem szyna budzi strumień,
a strumień czyta z bazy wszystko po ostatnim wysłanym id. `id` zdarzenia SSE = id wiersza,
więc po zerwaniu połączenia przeglądarka sama wyśle `Last-Event-ID` i dostanie brakujące.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from specflow.runtime import Runtime
from specflow.storage import EventRow, ProjectStore
from specflow.web.narration import narrate

BATCH = 200
KEEPALIVE_S = 15.0


def event_data(row: EventRow) -> dict[str, Any]:
    narration = narrate(row)
    return {
        "id": row.id,
        "type": row.type,
        "task_key": row.task_key,
        "actor": row.actor,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "payload": row.payload,
        "created_at": row.created_at.isoformat(),
        "narration": narration.model_dump() if narration else None,
    }


def format_sse(row: EventRow) -> str:
    data = json.dumps(event_data(row), ensure_ascii=False)
    return f"id: {row.id}\nevent: {row.type}\ndata: {data}\n\n"


def parse_last_event_id(header: str | None, after: int | None) -> int:
    if header and header.strip().isdigit():
        return int(header.strip())
    return max(after or 0, 0)


async def event_stream(
    rt: Runtime,
    project_id: int,
    *,
    after: int = 0,
    follow: bool = True,
    keepalive_s: float = KEEPALIVE_S,
) -> AsyncIterator[str]:
    """`follow=False`: tylko zaległe zdarzenia i koniec (skrypty, testy, odpytywanie)."""
    last = after
    with rt.bus.subscribe(project_id) as signal:
        yield "retry: 3000\n\n"
        while True:
            signal.clear()  # przed odczytem: sygnał w trakcie odczytu nie przepadnie
            rows = _read(rt, project_id, last)
            for row in rows:
                yield format_sse(row)
                last = row.id
            if len(rows) == BATCH:
                continue
            if not follow:
                return
            try:
                await asyncio.wait_for(signal.wait(), timeout=keepalive_s)
            except TimeoutError:
                yield ": ping\n\n"  # utrzymuje połączenie przez proxy


def _read(rt: Runtime, project_id: int, after: int) -> list[EventRow]:
    with rt.sessions() as session:
        return ProjectStore(session).events(project_id, after=after, limit=BATCH)
