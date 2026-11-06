"""Narracja: tłumaczenie zdarzeń z dziennika na zdania dla nietechnicznego użytkownika.

Decyzja (ADR-0008): narrację składa kod z naszego słownika zdarzeń, a nie model.
Streszczenie przez LLM kosztowałoby tokeny, dodawało opóźnienie i mogło zmyślać,
a opis postępu musi być prawdziwy. Surowe zdarzenia zostają dostępne jako szczegóły.

Poziomy: "main" - widoczne w logu od razu; "detail" - pod "pokaż szczegóły".
Zdarzenia bez narracji (np. zużycie tokenów) zwracają None.
"""

from typing import Any, Literal, Protocol

from pydantic import BaseModel

from specflow.domain import TaskStatus
from specflow.domain.project_phase import PHASE_LABELS, ProjectPhase

Level = Literal["main", "detail"]
S = TaskStatus

_EDIT_TOOLS = {"edit", "multiedit", "patch", "apply_patch"}
_BROWSE_TOOLS = {"glob", "grep", "list", "ls"}
_MAX_TEXT = 300

PLANNING_STEPS = {
    "constitution": "Zapisuję zasady projektu…",
    "specify": "Piszę specyfikację…",
    "clarify": "Uzupełniam specyfikację o Twoje odpowiedzi…",
    "plan": "Przygotowuję plan techniczny…",
    "tasks": "Rozpisuję zadania i sprawdzam ich kolejność…",
    "guide": "Przekazuję Twoją wskazówkę planiście…",
}


class Narration(BaseModel):
    text: str
    level: Level = "main"


class EventLike(Protocol):
    type: str
    task_key: str | None
    from_status: str | None
    to_status: str | None
    payload: dict[str, Any]


def narrate(event: EventLike) -> Narration | None:
    payload = event.payload or {}
    key = event.task_key
    match event.type:
        case "status_changed":
            return _status(key or "?", event.from_status, event.to_status, payload.get("reason"))
        case "agent_tool_call":
            return _main(_tool(str(payload.get("tool", "")), payload.get("target")), key)
        case "agent_tool_result":
            if payload.get("ok"):
                return None
            return _detail(f"Narzędzie zgłosiło błąd: {_short(payload.get('summary'))}", key)
        case "agent_message":
            text = _short(payload.get("text"))
            return _detail(f"Agent: {text}", key) if text else None
        case "agent_run_finished":
            return _run_finished(payload, key)
        case "planning_step":
            step = str(payload.get("step", ""))
            return Narration(text=PLANNING_STEPS.get(step, f"Planista: {step}…"))
        case "planning_blocked":
            return Narration(text=f"Planowanie utknęło. {payload.get('message', '')}".strip())
        case "phase_changed":
            return Narration(text=f"Etap: {_phase(payload.get('to'))}")
        case "gate_opened":
            what = "Specyfikacja" if payload.get("gate") == "spec" else "Plan"
            return Narration(text=f"{what} czeka na Twoją akceptację.")
        case "project_paused":
            return Narration(text=f"Budowa wstrzymana: {payload.get('reason', '')}".strip())
        case "project_resumed":
            return Narration(text="Budowa wznowiona.")
        case "run_state_changed":
            return _run_state(str(payload.get("state", "")))
        case "command_failed":
            return Narration(text=f"Nie udało się: {payload.get('error', '')}".strip())
        case "recovery":
            return Narration(text=_recovery(payload))
        case "project_created":
            return Narration(text="Projekt utworzony.", level="detail")
    return None


def _status(key: str, old: str | None, new: str | None, reason: Any) -> Narration | None:
    why = f" ({_short(reason)})" if reason else ""
    match new:
        case S.IN_PROGRESS:
            if old == S.REWORK:
                return _main("agent poprawia swoją pracę po weryfikacji", key)
            return _main("agent zaczyna pracę", key)
        case S.VERIFICATION:
            return _main("sprawdzam wynik: zmiany w plikach i testy", key)
        case S.REWORK:
            return _main(f"weryfikacja nie przeszła{why}", key)
        case S.DONE:
            return _main("zrobione, weryfikacja przeszła", key)
        case S.AWAITING_INPUT:
            return _main("potrzebuję Twojej odpowiedzi (karta zadania)", key)
        case S.READY if old == S.BACKLOG:
            return _detail("może się zacząć (zależności gotowe)", key)
        case S.READY if old == S.AWAITING_INPUT:
            return _main("dziękuję za odpowiedź, zadanie wraca do kolejki", key)
        case S.READY:
            return _main(f"wraca do kolejki{why}", key)
    return None


def _tool(tool: str, target: Any) -> str:
    name = tool.lower()
    what = str(target) if target else None
    if name == "read":
        return f"czyta plik {what}" if what else "czyta pliki projektu"
    if name in _EDIT_TOOLS:
        return f"zmienia plik {what}" if what else "zmienia pliki"
    if name == "write":
        return f"zapisuje plik {what}" if what else "zapisuje plik"
    if name in _BROWSE_TOOLS:
        return "przegląda pliki projektu"
    if name == "bash":
        return _command(what or "")
    if name.startswith("todo"):
        return "planuje kolejne kroki"
    if name in {"webfetch", "websearch"}:
        return "szuka informacji w internecie"
    return f"używa narzędzia {tool}"


def _command(command: str) -> str:
    text = command.lower()
    if "pytest" in text:
        return "uruchamia testy"
    if any(word in text for word in ("pip install", "uv add", "uv sync", "uv pip")):
        return "instaluje zależności"
    if text.startswith("git ") or " git " in text:
        return "sprawdza historię zmian"
    return f"uruchamia polecenie: {_short(command, 80)}" if command else "uruchamia polecenie"


def _run_finished(payload: dict[str, Any], key: str | None) -> Narration:
    status = payload.get("status")
    if status == "timeout":
        return _main("agent przekroczył limit czasu", key)
    if status == "failed":
        return _main(f"agent zakończył się błędem: {_short(payload.get('error'))}", key)
    if status == "aborted":
        return _main("praca agenta została przerwana", key)
    return _detail("agent skończył turę", key)


def _run_state(state: str) -> Narration | None:
    if state == "running":
        return Narration(text="Budowa trwa.")
    if state == "paused":
        return Narration(text="Wstrzymano na Twoją prośbę. Bieżące zadanie zostanie dokończone.")
    return None


def _recovery(payload: dict[str, Any]) -> str:
    tasks = payload.get("tasks") or []
    if not tasks:
        return "Specflow uruchomił się ponownie."
    return (
        "Specflow uruchomił się ponownie. Przerwane zadania wróciły do kolejki: "
        + ", ".join(str(t) for t in tasks)
        + "."
    )


def _phase(value: Any) -> str:
    try:
        return PHASE_LABELS[ProjectPhase(value)]
    except ValueError:
        return str(value)


def _main(text: str, key: str | None) -> Narration:
    return Narration(text=_with_key(text, key))


def _detail(text: str, key: str | None) -> Narration:
    return Narration(text=_with_key(text, key), level="detail")


def _with_key(text: str, key: str | None) -> str:
    return f"{key}: {text}" if key else text[:1].upper() + text[1:]


def _short(value: Any, limit: int = _MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
