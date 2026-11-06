from specflow.orchestrator import (
    PROMPT_VERSION,
    DependencyNote,
    TaskContext,
    build_answer_prompt,
    build_rework_prompt,
    build_task_prompt,
    extract_story_section,
)

SPEC = """# Feature: Todo

## User Scenarios & Testing

### User Story 1 - Log in (Priority: P1)

A user logs in with email and password.

**Acceptance Scenarios**:

1. **Given** a registered user, **When** they submit valid credentials, **Then** they log in.
2. **Given** a wrong password, **When** they submit, **Then** they get an error.

---

### User Story 2 - Manage todos (Priority: P2)

Create and delete todos.

## Requirements
- FR-001 ...
"""


def test_extracts_only_the_requested_story() -> None:
    section = extract_story_section(SPEC, "US1")
    assert section is not None
    assert section.startswith("### User Story 1 - Log in")
    assert "valid credentials" in section
    assert "Manage todos" not in section
    us2 = extract_story_section(SPEC, "US2")
    assert us2 is not None and "Requirements" not in us2
    assert extract_story_section(SPEC, "US9") is None


def test_task_prompt_has_targeted_context_and_report_format() -> None:
    prompt = build_task_prompt(
        TaskContext(
            key="T010",
            title="Implement login service in src/auth.py",
            story="US1",
            files=["src/auth.py"],
            feature_dir="specs/001-todo",
            acceptance="1. Given ... Then ...",
            dependency_notes=[
                DependencyNote(key="T009", notes="verify_password() w src/security.py"),
                DependencyNote(key="T001", notes=""),
            ],
        )
    )
    assert prompt.startswith("Zadanie T010 [US1]: Implement login service")
    assert "Nie zmieniaj testów" in prompt
    assert "specs/001-todo/spec.md" in prompt
    assert "- T009: verify_password() w src/security.py" in prompt
    assert "T001:" not in prompt  # puste notatki pomijamy
    assert '"status": "blocked"' in prompt
    assert "Wskazówka" not in prompt


def test_test_writer_prompt_and_hint_with_failure_history() -> None:
    prompt = build_task_prompt(
        TaskContext(
            key="T007",
            title="Contract test for login",
            is_test=True,
            user_hint="Użyj kodu 401 dla złego hasła",
            previous_failure="- TDD: nie dodano nowych testów",
        )
    )
    assert "WYŁĄCZNIE testy" in prompt
    assert "Wskazówka od użytkownika (ważna): Użyj kodu 401" in prompt
    assert "nie dodano nowych testów" in prompt


def test_rework_and_answer_prompts_name_the_task() -> None:
    rework = build_rework_prompt("T010", "- regresje: ...", attempt=2, max_attempts=3)
    assert rework.startswith(
        "Zadanie T010: automatyczna weryfikacja nie przeszła (podejście 2 z 3)"
    )
    answer = build_answer_prompt("T010", "Jaki algorytm?", "bcrypt")
    assert 'Pytałeś: "Jaki algorytm?"' in answer and "Odpowiedź: bcrypt" in answer
    assert PROMPT_VERSION.startswith("task-prompt/")
