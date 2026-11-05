"""Test dymny i nagrywarka strumienia zdarzeń prawdziwego OpenCode.

Uruchom lokalnie, gdy kontener z `opencode serve` działa (patrz docker/README.md):

    uv run python -m specflow.harness.opencode.record \\
        --dir var/projects/smoke --out tests/fixtures/opencode/smoke.jsonl

Zapisuje surowe zdarzenia (JSONL) jako fikstury do testów adaptera i wypisuje,
jak adapter je przetłumaczył. Dzięki temu CI sprawdza mapowanie bez uruchamiania OpenCode.
"""

import argparse
import asyncio
import json
from pathlib import Path

from specflow.harness.base import SessionSpec
from specflow.harness.opencode.adapter import OpenCodeHarness
from specflow.harness.opencode.client import OpenCodeClient
from specflow.harness.opencode.mapping import SUBSCRIBED_TYPES, OpenCodeEventMapper
from specflow.harness.permissions import AgentProfile, rules_for

DEFAULT_PROMPT = (
    "Create a file hello.py with a function hello() returning 'hello'. "
    "Finish with a JSON block: "
    '```json\n{"status": "done", "summary": "...", "notes": "..."}\n```'
)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:4096")
    parser.add_argument("--password", default=None)
    parser.add_argument("--host-root", default="var/projects")
    parser.add_argument("--container-root", default="/workspace")
    parser.add_argument("--dir", required=True, help="katalog projektu pod --host-root")
    parser.add_argument("--out", required=True, help="plik JSONL na surowe zdarzenia")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    workdir = Path(args.dir)
    workdir.mkdir(parents=True, exist_ok=True)
    client = OpenCodeClient(args.url, password=args.password)
    harness = OpenCodeHarness(
        client, host_root=Path(args.host_root), container_root=args.container_root
    )
    spec = SessionSpec(title="specflow-smoke", workdir=workdir, profile=AgentProfile.IMPLEMENTER)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    session_id = await client.create_session(
        title=spec.title,
        directory=harness.container_path(workdir),
        permissions=[r.model_dump() for r in rules_for(spec.profile)],
    )
    mapper = OpenCodeEventMapper(session_id)
    print(f"sesja {session_id}")
    with out.open("w") as sink:
        async with client.events(SUBSCRIBED_TYPES) as stream:
            await client.prompt(session_id, args.prompt)
            async with asyncio.timeout(args.timeout):
                async for envelope in stream:
                    sink.write(json.dumps(envelope) + "\n")
                    for event in mapper.map(envelope):
                        print(" ", event.model_dump_json(exclude_none=True))
                    if mapper.terminal:
                        break
    print(f"koniec: {mapper.terminal}; zapisano {out}")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
