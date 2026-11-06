"""Orkiestrator (ADR-0001, ADR-0006).

Deterministyczna pętla i maszyna stanów, NIE agent LLM. Wybiera zadania Ready, składa
prompty, uruchamia agenta przez port Harness, przekazuje wynik do weryfikacji i obsługuje
Rework, Awaiting input oraz awarie infrastruktury.
"""

from specflow.orchestrator.engine import Orchestrator, OrchestratorConfig, StepOutcome
from specflow.orchestrator.prompts import (
    PROMPT_VERSION,
    DependencyNote,
    TaskContext,
    build_answer_prompt,
    build_rework_prompt,
    build_task_prompt,
    extract_story_section,
)

__all__ = [
    "PROMPT_VERSION",
    "DependencyNote",
    "Orchestrator",
    "OrchestratorConfig",
    "StepOutcome",
    "TaskContext",
    "build_answer_prompt",
    "build_rework_prompt",
    "build_task_prompt",
    "extract_story_section",
]
