"""Menedżer workspace projektu: katalog, git, Spec Kit, commit po zadaniu.

Repozytorium projektu to wspólna pamięć agentów: kolejne zadania czytają kod
stworzony przez poprzednie, a commit po każdym zadaniu pozwala cofnąć Rework.
"""

import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

SPEC_KIT_VERSION = "v1.3.0"
"""Przypięta wersja Spec Kit (CLI `specify` instalowane na hoście, patrz docker/README.md)."""

AGENT_AUTHOR = "Specflow Agent <agent@specflow.local>"

Runner = Callable[[Sequence[str], Path], str]
"""Uruchamia komendę w katalogu i zwraca stdout; rzuca WorkspaceError przy błędzie."""


class WorkspaceError(Exception):
    pass


_ERROR_TAIL = 2000
"""Ile znaków wyjścia nieudanej komendy trafia do komunikatu błędu."""


def run_command(args: Sequence[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            list(args), cwd=cwd, capture_output=True, text=True, check=False, timeout=600
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"{' '.join(args)}: {exc}") from exc
    if result.returncode != 0:
        # Część narzędzi (np. CLI na Typer/Rich jak `specify`) wypisuje błędy na stdout.
        output = (result.stderr.strip() or result.stdout.strip())[-_ERROR_TAIL:]
        raise WorkspaceError(f"{' '.join(args)} -> {result.returncode}: {output}")
    return result.stdout


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-") or "project"


class Workspace:
    def __init__(self, path: Path, runner: Runner = run_command) -> None:
        self.path = path
        self._run = runner

    @classmethod
    def create(
        cls, root: Path, project_id: int, name: str, runner: Runner = run_command
    ) -> "Workspace":
        path = cls.path_for(root, project_id, name)
        if path.exists() and any(path.iterdir()):
            raise WorkspaceError(f"Katalog {path} już istnieje i nie jest pusty.")
        path.mkdir(parents=True, exist_ok=True)
        workspace = cls(path, runner)
        workspace._git("init", "-q", "-b", "main")
        workspace._git("config", "user.name", "Specflow Agent")
        workspace._git("config", "user.email", "agent@specflow.local")
        # Katalog roboczy Specflow (np. wyniki JUnit z weryfikacji) nie trafia do diffu.
        (path / ".gitignore").write_text(".specflow/\n.venv/\n__pycache__/\n.pytest_cache/\n")
        return workspace

    @staticmethod
    def path_for(root: Path, project_id: int, name: str) -> Path:
        """Katalog projektu: `<root>/0007-lista-zadan`."""
        return root / f"{project_id:04d}-{slugify(name)}"

    def init_spec_kit(self, integration: str = "opencode") -> None:
        """`specify init --here` w przypiętej wersji; potem commit bazowy."""
        self._run(
            [
                "specify",
                "init",
                "--here",
                "--force",
                "--non-interactive",
                "--integration",
                integration,
                "--script",
                "sh",
            ],
            self.path,
        )
        self.commit("chore: specify init (Spec Kit)")

    def read(self, relative: str) -> str:
        return (self.path / relative).read_text()

    def head(self) -> str | None:
        try:
            return self._git("rev-parse", "HEAD").strip()
        except WorkspaceError:
            return None

    def changed_files(self, since: str | None = None) -> list[str]:
        """Pliki zmienione od commita `since` (albo od HEAD) plus nieśledzone.
        Źródło prawdy dla weryfikacji - nie lista FileChanged od agenta."""
        tracked = self._git("diff", "--name-only", since or "HEAD") if self.head() else ""
        untracked = self._git("ls-files", "--others", "--exclude-standard")
        return sorted({line for line in (tracked + untracked).splitlines() if line})

    def commit(self, message: str) -> str | None:
        """Commituje wszystkie zmiany; zwraca SHA albo None, gdy nie było zmian."""
        self._git("add", "-A")
        if not self._git("status", "--porcelain").strip():
            return None
        self._git("commit", "-q", "-m", message, f"--author={AGENT_AUTHOR}")
        return self.head()

    def commit_task(self, key: str, title: str) -> str | None:
        return self.commit(f"{key}: {title}")

    def diff(self, since: str | None, path: str) -> str:
        """Diff jednego pliku względem commita `since` (albo HEAD); pusty, gdy brak historii."""
        if not self.head():
            return ""
        return self._git("diff", since or "HEAD", "--", path)

    def files(self) -> list[str]:
        """Pliki projektu znane gitowi (śledzone i nowe, z pominięciem ignorowanych)."""
        listed = self._git("ls-files", "--cached", "--others", "--exclude-standard")
        return sorted({line for line in listed.splitlines() if line})

    def save_attempt(self, branch: str, message: str) -> str | None:
        """Zapisuje bieżące (nieudane) zmiany na osobnej gałęzi i wraca na gałąź główną
        w stanie sprzed próby. Zwraca SHA zapisu albo None, gdy nie było zmian."""
        if not self._git("status", "--porcelain").strip():
            return None
        current = self._git("rev-parse", "--abbrev-ref", "HEAD").strip()
        self._git("checkout", "-q", "-b", branch)
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message, f"--author={AGENT_AUTHOR}")
        sha = self.head()
        self._git("checkout", "-q", current)
        return sha

    def reset_to(self, sha: str) -> None:
        """Cofa wszystkie zmiany do commita `sha` (np. przed ponowną próbą)."""
        self._git("reset", "-q", "--hard", sha)
        self._git("clean", "-q", "-fd")

    def _git(self, *args: str) -> str:
        return self._run(["git", *args], self.path)
