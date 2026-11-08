from fnmatch import fnmatch

import pytest

from specflow.harness import AgentProfile, PermissionRule, rules_for


def effect(rules: list[PermissionRule], action: str, resource: str) -> str:
    """Semantyka OpenCode: wygrywa OSTATNIA pasująca reguła."""
    result = "allow"
    for rule in rules:
        if rule.action in ("*", action) and fnmatch(resource, rule.resource):
            result = rule.effect
    return result


@pytest.mark.parametrize("profile", list(AgentProfile))
def test_no_profile_uses_ask(profile: AgentProfile) -> None:
    assert {rule.effect for rule in rules_for(profile)} <= {"allow", "deny"}


def test_implementer_writes_code_but_not_tests() -> None:
    rules = rules_for(AgentProfile.IMPLEMENTER)
    assert effect(rules, "edit", "src/todo/services/auth.py") == "allow"
    assert effect(rules, "edit", "tests/contract/test_login.py") == "deny"
    assert effect(rules, "edit", "backend/tests/test_api.py") == "deny"
    assert effect(rules, "bash", "uv run pytest") == "allow"


def test_test_writer_writes_only_tests() -> None:
    rules = rules_for(AgentProfile.TEST_WRITER)
    assert effect(rules, "edit", "tests/test_login.py") == "allow"
    assert effect(rules, "edit", "src/todo/app.py") == "deny"


def test_planner_writes_only_spec_artifacts() -> None:
    rules = rules_for(AgentProfile.PLANNER)
    assert effect(rules, "edit", "specs/001-todo/tasks.md") == "allow"
    assert effect(rules, "edit", ".specify/memory/constitution.md") == "allow"
    assert effect(rules, "edit", "src/app.py") == "deny"


def test_interviewer_has_no_tools() -> None:
    rules = rules_for(AgentProfile.INTERVIEWER)
    for action in ("edit", "bash", "read", "webfetch"):
        assert effect(rules, action, "anything") == "deny"


@pytest.mark.parametrize("profile", list(AgentProfile))
def test_safety_rules_win_for_every_profile(profile: AgentProfile) -> None:
    rules = rules_for(profile)
    assert effect(rules, "bash", "git push origin main") == "deny"
    assert effect(rules, "shell", "git push origin main") == "deny"  # nazwa w OpenCode 2.x
    assert effect(rules, "read", ".env") == "deny"
    assert effect(rules, "doom_loop", "edit") == "deny"
