"""Szkielet projektu Python tworzony przez kod Specflow, nie przez agenta.

Stos w F00 jest stały (ADR-0007), więc konfiguracja projektu też może być stała.
Konfiguracja pytest jest plikiem chronionym w weryfikacji (ADR-0005): gdyby tworzył ją
agent w zadaniu Setup, weryfikacja musiałaby mu na to pozwolić, a agent mógłby wtedy
"poprawić" konfigurację testów tak, żeby testy przechodziły. Szkielet od kodu zamyka tę lukę:
agent dodaje zależności (`uv add`), ale sekcji `[tool.pytest.ini_options]` nie zmienia.
"""

import unicodedata

from specflow.workspace.manager import Workspace, slugify

PACKAGE_DIR = "app"
TESTS_DIR = "tests"

PYPROJECT = """\
[project]
name = "{name}"
version = "0.1.0"
description = "Aplikacja zbudowana przez Specflow"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "jinja2>=3.1",
    "uvicorn>=0.32",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["{tests}"]
"""

GITIGNORE = """\
__pycache__/
*.pyc
.venv/
.pytest_cache/
.specflow/
*.sqlite3
"""


def package_name(project_name: str) -> str:
    """ "Lista zadań" → "lista-zadan" (polskie znaki bez ogonków)."""
    ascii_name = (
        unicodedata.normalize("NFKD", project_name.replace("ł", "l").replace("Ł", "L"))
        .encode("ascii", "ignore")
        .decode()
    )
    return slugify(ascii_name)


def scaffold_python(workspace: Workspace, project_name: str) -> str | None:
    """Zapisuje szkielet i robi commit. Zwraca sha commita (None, gdy nic się nie zmieniło)."""
    files = {
        "pyproject.toml": PYPROJECT.format(name=package_name(project_name), tests=TESTS_DIR),
        ".gitignore": GITIGNORE,
        f"{PACKAGE_DIR}/__init__.py": "",
        f"{TESTS_DIR}/.gitkeep": "",
    }
    for relative, content in files.items():
        target = workspace.path / relative
        if target.exists():
            continue  # nie nadpisujemy tego, co już jest (np. po `specify init`)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return workspace.commit("chore: szkielet projektu Python (Specflow)")
