"""Eksport diagnostyczny: komplet danych przebiegu w jednym pliku, bez sekretów."""

import json
import zipfile
from pathlib import Path

import pytest

from runtime_helpers import make_runtime, new_project, to_building
from specflow.__main__ import main
from specflow.export import MAX_UNTRACKED_FILE, export_project
from specflow.workspace import Workspace, run_command

SECRET = "tajne-haslo-opencode-123"


def test_export_contains_run_history_and_workspace(tmp_path: Path) -> None:
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    to_building(rt, pid)
    with rt.sessions() as session:
        store = rt.store(session, pid)
        store.add_message(pid, "user", f"przypadkiem wklejone hasło: {SECRET}")
        store.commit()
        out = tmp_path / "out" / "e.zip"
        path = export_project(session, rt.projects_dir, pid, out, harness="mock", secrets=[SECRET])

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "project.json", "chat.jsonl", "events.jsonl"} <= names
        assert {"tasks.jsonl", "decisions.jsonl"} <= names
        assert {"runs.jsonl", "commands.jsonl", "workspace.bundle", "workspace-status.txt"} <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["project"] == {"id": pid, "name": "Lista zadań", "phase": "building"}
        assert manifest["counts"]["tasks"] == 5 and manifest["harness"] == "mock"
        events = [json.loads(line) for line in archive.read("events.jsonl").decode().splitlines()]
        assert any(e["narration"] == "Piszę specyfikację…" for e in events)
        everything = b"".join(archive.read(n) for n in names if n != "workspace.bundle").decode()
        assert SECRET not in everything and "przypadkiem wklejone hasło: ***" in everything
        archive.extract("workspace.bundle", tmp_path)

    clone = tmp_path / "clone"
    run_command(["git", "clone", "-q", str(tmp_path / "workspace.bundle"), str(clone)], tmp_path)
    log = run_command(["git", "log", "--format=%s"], clone)
    assert "docs: specyfikacja i plan (Spec Kit)" in log and "szkielet projektu" in log


def test_export_cli_uses_settings_and_redacts_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPECFLOW_OPENCODE_PASSWORD", SECRET)
    with rt.sessions() as session:
        rt.store(session, pid).add_message(pid, "assistant", f"token {SECRET}")
        session.commit()
    output = tmp_path / "cli.zip"
    main(["export", str(pid), "-o", str(output), "--data-dir", str(tmp_path)])
    assert f"Zapisano eksport: {output}" in capsys.readouterr().out
    with zipfile.ZipFile(output) as archive:
        assert SECRET not in archive.read("chat.jsonl").decode()


def test_export_includes_untracked_text_files(tmp_path: Path) -> None:
    """Regresja M6b: przed akceptacją planu specs/ nie jest w gicie, więc bundle i diff
    go nie zawierały - nie dało się ocenić tasks.md projektu zatrzymanego na bramce."""
    rt, _ = make_runtime(tmp_path)
    pid = new_project(rt)
    with rt.sessions() as session:
        name = rt.store(session, pid).get_project(pid).name
    root = Workspace.path_for(rt.projects_dir, pid, name)
    (root / "specs" / "001-x").mkdir(parents=True)
    (root / "specs" / "001-x" / "tasks.md").write_text(f"- [ ] T001 zadanie {SECRET}\n")
    (root / "obraz.bin").write_bytes(b"\xff\xfe\x00binarne")
    (root / "duzy.md").write_text("x" * (MAX_UNTRACKED_FILE + 1))
    (root / "link.md").symlink_to(tmp_path / "poza-workspace.md")
    (tmp_path / "poza-workspace.md").write_text("nie powinno trafić do eksportu")

    with rt.sessions() as session:
        out = tmp_path / "e.zip"
        path = export_project(session, rt.projects_dir, pid, out, secrets=[SECRET])

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        tasks = archive.read("workspace-untracked/specs/001-x/tasks.md").decode()
        assert tasks == "- [ ] T001 zadanie ***\n"
        assert not {"workspace-untracked/obraz.bin", "workspace-untracked/duzy.md"} & names
        assert "workspace-untracked/link.md" not in names
        skipped = archive.read("workspace-untracked.skipped.txt").decode()
        assert "obraz.bin (plik binarny)" in skipped and "duzy.md" in skipped
