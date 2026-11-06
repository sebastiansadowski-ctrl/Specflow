"""Silnik wywiadu (ADR-0007).

Etapy: zasady (konstytucja) → specyfikacja → doprecyzowanie. Sloty to lista kontrolna
po naszej stronie; model wyciąga fakty i prowadzi rozmowę, kod liczy kompletność
i składa podsumowania oraz briefy dla komend Spec Kit.
"""

from specflow.interview.engine import FALLBACK_MESSAGE, Interviewer, TurnResult
from specflow.interview.prompts import INTERVIEW_PROMPT_VERSION, build_interview_prompt
from specflow.interview.render import (
    STACK,
    render_clarifications_prompt,
    render_constitution_brief,
    render_plan_brief,
    render_plan_summary,
    render_spec_brief,
    render_spec_summary,
    render_tasks_brief,
)
from specflow.interview.slots import (
    CONSTITUTION_SLOTS,
    SPEC_SLOTS,
    InterviewState,
    Slot,
    Story,
    is_complete,
    missing_slots,
    progress,
)
from specflow.interview.turn import TurnOutput, apply_turn, parse_turn

__all__ = [
    "CONSTITUTION_SLOTS",
    "FALLBACK_MESSAGE",
    "INTERVIEW_PROMPT_VERSION",
    "SPEC_SLOTS",
    "STACK",
    "InterviewState",
    "Interviewer",
    "Slot",
    "Story",
    "TurnOutput",
    "TurnResult",
    "apply_turn",
    "build_interview_prompt",
    "is_complete",
    "missing_slots",
    "parse_turn",
    "progress",
    "render_clarifications_prompt",
    "render_constitution_brief",
    "render_plan_brief",
    "render_plan_summary",
    "render_spec_brief",
    "render_spec_summary",
    "render_tasks_brief",
]
