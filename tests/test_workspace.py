from collections.abc import Sequence
from pathlib import Path

import pytest

from specflow.workspace import SPEC_KIT_VERSION, Workspace, WorkspaceError, run_command, slugify


def test_create_initializes_git_repo_with_stable_dir_name(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path, 7, "Todo z logowaniem!")
    assert ws.path == tmp_path / "0007-todo-z-logowaniem"
    assert (ws.path / ".git").is_dir()
    assert ws.head() is None


def test_commit_task_and_changed_files(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path, 1, "demo")
    (ws.path / "README.md").write_text("demo\n")
    base = ws.commit("init")
    assert base is not None

    (ws.path / "src").mkdir()
    (ws.path / "src/app.py").write_text("print('hi')\n")
    (ws.path / "README.md").write_text("demo 2\n")
    assert ws.changed_files() == ["README.md", "src/app.py"]

    sha = ws.commit_task("T001", "Create app")
    assert sha is not None and sha != base
    assert ws.changed_files() == []
    assert ws.changed_files(since=base) == ["README.md", "src/app.py"]
    assert "T001: Create app" in run_command(["git", "log", "-1", "--format=%s"], ws.path)


def test_commit_without_changes_returns_none(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path, 1, "demo")
    (ws.path / "a.txt").write_text("a")
    ws.commit("init")
    assert ws.commit_task("T002", "nothing") is None


def test_reset_to_discards_agent_changes(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path, 1, "demo")
    (ws.path / "a.txt").write_text("a")
    base = ws.commit("init")
    assert base is not None
    (ws.path / "a.txt").write_text("zepsute")
    (ws.path / "junk.py").write_text("x")
    ws.reset_to(base)
    assert (ws.path / "a.txt").read_text() == "a"
    assert not (ws.path / "junk.py").exists()


def test_existing_non_empty_dir_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "0001-demo"
    target.mkdir()
    (target / "x").write_text("x")
    with pytest.raises(WorkspaceError):
        Workspace.create(tmp_path, 1, "demo")


def test_init_spec_kit_calls_pinned_cli_and_commits(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args: Sequence[str], cwd: Path) -> str:
        calls.append(list(args))
        if args[0] == "specify":
            (cwd / ".specify").mkdir()
            (cwd / ".specify/marker").write_text("ok")
            return ""
        return run_command(args, cwd)

    ws = Workspace.create(tmp_path, 1, "demo", runner=runner)
    ws.init_spec_kit()
    specify_call = next(c for c in calls if c[0] == "specify")
    assert specify_call[:3] == ["specify", "init", "--here"]
    assert specify_call[specify_call.index("--integration") :][:2] == ["--integration", "opencode"]
    assert ws.head() is not None
    assert SPEC_KIT_VERSION.startswith("v")


def test_slugify() -> None:
    assert slugify("  Lista Zadań 2.0 ") == "lista-zada-2-0"
    assert slugify("!!!") == "project"


def test_scaffold_creates_python_skeleton_with_protected_pytest_config(tmp_path: Path) -> None:
    import tomllib

    from specflow.workspace.scaffold import package_name, scaffold_python

    ws = Workspace.create(tmp_path, 3, "Lista zadań")
    assert package_name("Łąka Żółwia") == "laka-zolwia"
    assert scaffold_python(ws, "Lista zadań") is not None
    config = tomllib.loads(ws.read("pyproject.toml"))
    assert config["project"]["name"] == "lista-zadan"
    assert config["tool"]["pytest"]["ini_options"] == {"pythonpath": ["."], "testpaths": ["tests"]}
    assert (ws.path / "app/__init__.py").exists() and (ws.path / "tests").is_dir()
    assert "__pycache__/" in ws.read(".gitignore")
    assert "szkielet projektu" in run_command(["git", "log", "--format=%s"], ws.path)

    (ws.path / "pyproject.toml").write_text("[project]\nname = 'moje'\n")
    ws.commit("zmiana")
    assert scaffold_python(ws, "Lista zadań") is None  # nic nie nadpisuje
    assert "moje" in ws.read("pyproject.toml")
