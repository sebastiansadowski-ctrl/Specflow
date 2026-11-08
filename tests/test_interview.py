import asyncio
from datetime import date
from pathlib import Path

from conftest import say
from specflow.harness.mock import MockHarness, Scenario
from specflow.interview import (
    FALLBACK_MESSAGE,
    Interviewer,
    InterviewState,
    Story,
    apply_turn,
    build_interview_prompt,
    is_complete,
    missing_slots,
    parse_turn,
    progress,
    render_constitution_brief,
    render_spec_brief,
    render_spec_summary,
)
from specflow.interview.prompts import INTERVIEW_PROMPT_VERSION
from specflow.interview.slots import PersonalData
from specflow.interview.turn import TurnOutput


def say_json(**payload: object) -> str:
    text = say(**payload).final_text
    assert text is not None
    return text


LOGIN = Story(
    title="Logowanie",
    actor="użytkownik",
    action="loguje się e-mailem",
    benefit="widzi swoje zadania",
    acceptance=["po dobrym haśle widzi listę", "po złym haśle widzi komunikat"],
)


def spec_state(**answers: str) -> InterviewState:
    return InterviewState(stage="specify", answers=answers)


def test_code_counts_missing_slots_and_progress() -> None:
    state = spec_state(name="Todo", goal="porządek")
    assert missing_slots(state) == ["users", "stories"]
    assert progress(state) == (2, 4)
    state.answers["users"] = "ja i rodzina"
    state.stories = [Story(title="Logowanie")]  # bez kryterium akceptacji
    assert missing_slots(state) == ["stories"]
    state.stories = [LOGIN]
    assert missing_slots(state) == [] and is_complete(state)


def test_user_can_finish_early_but_only_with_a_testable_story() -> None:
    state = spec_state(name="Todo")
    state.user_wants_to_finish = True
    assert not is_complete(state)
    state.stories = [LOGIN]
    assert is_complete(state)


def test_free_talk_fills_several_slots_at_once() -> None:
    turn = TurnOutput(
        message="Super. Co jeszcze?",
        updates={"name": "Todo", "goal": "porządek", "users": "rodzina", "foo": "x"},
        stories=[LOGIN],
        assumptions=["Tylko e-mail i hasło"],
    )
    state, ignored = apply_turn(spec_state(), turn)
    assert state.answers == {"name": "Todo", "goal": "porządek", "users": "rodzina"}
    assert ignored == ["foo"]  # nieznany punkt jest pomijany, nie psuje stanu
    assert state.stories == [LOGIN]
    again, _ = apply_turn(state, TurnOutput(message="ok", assumptions=["Tylko e-mail i hasło"]))
    assert again.assumptions == ["Tylko e-mail i hasło"]  # bez duplikatów
    assert again.stories == [LOGIN]  # brak "stories" = bez zmian


def test_clarifications_must_match_open_questions() -> None:
    state = InterviewState(stage="clarify", open_questions=["Jaki język?"])
    turn = TurnOutput(message="ok", clarifications={"Jaki język?": "polski", "Inne?": "x"})
    new, ignored = apply_turn(state, turn)
    assert new.clarifications == {"Jaki język?": "polski"}
    assert ignored and missing_slots(new) == []


def test_parse_turn_takes_last_json_block_and_reports_errors() -> None:
    turn, error = parse_turn('Myślę...\n```json\n{"message": "Cześć", "updates": {}}\n```')
    assert error is None and turn is not None and turn.message == "Cześć"
    assert parse_turn("bez JSON-a") == (None, "brak bloku JSON z polem 'message'")
    bad, problem = parse_turn('```json\n{"message": ""}\n```')
    assert bad is None and problem is not None and problem.startswith("zły format")


def test_prompt_shows_state_missing_slots_and_rules() -> None:
    prompt = build_interview_prompt(spec_state(name="Todo"), "chcę listę zadań")
    assert prompt.startswith("[wywiad]")
    assert "NIE pytaj o technologie" in prompt
    assert "Brakuje jeszcze: goal, users, stories" in prompt
    assert "Wiadomość użytkownika:\nchcę listę zadań" in prompt


def run_turn(harness: MockHarness, state: InterviewState, tmp_path: Path, text: str | None):  # type: ignore[no-untyped-def]
    async def go():  # type: ignore[no-untyped-def]
        interviewer = Interviewer(harness)
        session = await interviewer.open_session(tmp_path)
        return await interviewer.turn(session, state, text)

    return asyncio.run(go())


def test_interviewer_merges_model_output(tmp_path: Path) -> None:
    harness = MockHarness(
        by_match={"[wywiad]": say(message="Kto będzie korzystał?", updates={"name": "Todo"})}
    )
    result = run_turn(harness, spec_state(), tmp_path, "Chcę aplikację Todo")
    assert result.ok and result.message == "Kto będzie korzystał?"
    assert result.state.answers["name"] == "Todo" and not result.complete


def test_interviewer_repairs_bad_json_once_then_falls_back(tmp_path: Path) -> None:
    broken = Scenario(name="broken", final_text="Oto odpowiedź bez JSON-a")
    repaired = MockHarness(by_match={"[wywiad]": [broken, say(message="Teraz OK")]})
    assert run_turn(repaired, spec_state(), tmp_path, "hej").message == "Teraz OK"

    hopeless = MockHarness(by_match={"[wywiad]": broken})
    result = run_turn(hopeless, spec_state(name="Todo"), tmp_path, "hej")
    assert not result.ok and result.message == FALLBACK_MESSAGE
    assert result.state.answers == {"name": "Todo"}  # stan bez zmian


def test_summary_and_briefs_are_built_by_code() -> None:
    state = spec_state(name="Todo", goal="porządek", users="rodzina", personal_data="tak, e-maile")
    state.stories = [LOGIN]
    state.assumptions = ["Tylko e-mail i hasło"]
    summary = render_spec_summary(state)
    assert "## Todo" in summary and "**Logowanie**" in summary
    assert "sprawdzimy: po złym haśle widzi komunikat" in summary
    assert "Założenia (do sprawdzenia)" in summary and "Tylko e-mail i hasło" in summary

    brief = render_spec_brief(state)
    assert "1. Logowanie (Priority: P1)" in brief and "acceptance: po dobrym haśle" in brief
    assert "keep ALL Spec Kit template headings in English" in brief
    state.personal_data = PersonalData(stored=True, kinds=["e-maile"])
    constitution = render_constitution_brief(state, "Todo", today=date(2026, 11, 9))
    assert "Test-First" in constitution and "Personal Data Protection" in constitution
    assert "Personal data stored: e-maile." in constitution
    assert "ratified and last amended on 2026-11-09" in constitution


def test_personal_data_is_extracted_by_the_model_not_guessed_by_keywords() -> None:
    """Regresja M6b: odpowiedź „Tylko imiona członków rodziny” nie zawiera słowa „tak”,
    a to są dane osobowe. Model zwraca pole tak/nie, kod decyduje o zasadzie."""
    state = InterviewState(stage="constitution")
    assert missing_slots(state) == ["personal_data", "devices"]
    turn, error = parse_turn(
        say_json(
            message="Rozumiem. Na jakich urządzeniach?",
            updates={"personal_data": "Tylko imiona członków rodziny"},
            personal_data={"stored": True, "kinds": ["imiona"]},
        )
    )
    assert turn is not None and error is None
    state, ignored = apply_turn(state, turn)
    assert ignored == [] and missing_slots(state) == ["devices"]
    assert state.answers["personal_data"] == "tak: imiona"
    assert "Personal Data Protection" in render_constitution_brief(state, "Lista")

    text_only = InterviewState(stage="constitution", answers={"personal_data": "tak, e-maile"})
    assert "personal_data" in missing_slots(text_only)  # sam tekst nie wystarcza

    nothing = InterviewState(stage="constitution", personal_data=PersonalData(stored=False))
    assert "Personal data: none is stored." in render_constitution_brief(nothing, "Lista")
    assert "Personal Data Protection" not in render_constitution_brief(nothing, "Lista")


def test_prompt_v2_asks_no_question_when_done_and_does_not_greet_twice() -> None:
    prompt = build_interview_prompt(InterviewState(stage="specify"), None)
    assert INTERVIEW_PROMPT_VERSION == "interview/v2"
    assert "bez powitania" in prompt and "przywitaj się" not in prompt
    assert "NIE zadawaj" in prompt and "zaraz pokażesz podsumowanie" in prompt
    first = build_interview_prompt(InterviewState(stage="constitution"), None)
    assert "przywitaj się krótko" in first and '"personal_data"' in first
