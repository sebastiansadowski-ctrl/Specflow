"""Podgląd artefaktów Spec Kit (tylko do odczytu).

Bezpieczeństwo:
- czytamy wyłącznie pliki z listy (allowlist), nigdy ścieżkę podaną przez klienta wprost;
- ścieżka po rozwiązaniu dowiązań musi leżeć w workspace: agent pisze w tym katalogu
  i mógłby podłożyć symlink np. do pliku z sekretami Specflow;
- treść renderujemy bezpiecznie (`web.markdown`), bo pisał ją model.
"""

from pathlib import Path

from pydantic import BaseModel

from specflow.web.markdown import render_markdown

MAX_BYTES = 512_000
CONSTITUTION = ".specify/memory/constitution.md"
FEATURE_FILES = ("spec.md", "plan.md", "research.md", "data-model.md", "quickstart.md", "tasks.md")
FEATURE_DIRS = ("contracts", "checklists")
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".txt"}


class ArtifactInfo(BaseModel):
    path: str
    title: str


class Artifact(ArtifactInfo):
    markdown: str
    """Źródło do renderowania (pliki inne niż .md jako blok kodu)."""
    html: str


class ArtifactError(Exception):
    pass


def list_artifacts(root: Path, feature_dir: str | None) -> list[ArtifactInfo]:
    candidates = [CONSTITUTION]
    if feature_dir:
        candidates += [f"{feature_dir}/{name}" for name in FEATURE_FILES]
        for sub in FEATURE_DIRS:
            folder = root / feature_dir / sub
            if folder.is_dir():
                candidates += sorted(
                    f"{feature_dir}/{sub}/{p.name}"
                    for p in folder.iterdir()
                    if p.suffix in TEXT_SUFFIXES
                )
    return [
        ArtifactInfo(path=rel, title=_title(rel))
        for rel in candidates
        if _safe(root, rel) is not None
    ]


def read_artifact(root: Path, feature_dir: str | None, relative: str) -> Artifact:
    allowed = {a.path: a for a in list_artifacts(root, feature_dir)}
    info = allowed.get(relative)
    path = _safe(root, relative) if info else None
    if info is None or path is None:
        raise ArtifactError("Nie ma takiego artefaktu.")
    if path.stat().st_size > MAX_BYTES:
        raise ArtifactError("Plik jest za duży do podglądu.")
    text = path.read_text(errors="replace")
    if path.suffix != ".md":
        text = f"```{path.suffix.lstrip('.')}\n{text}\n```"
    return Artifact(path=info.path, title=info.title, markdown=text, html=render_markdown(text))


def _safe(root: Path, relative: str) -> Path | None:
    """Ścieżka wewnątrz workspace (po rozwiązaniu symlinków) albo None."""
    base = root.resolve()
    try:
        path = (base / relative).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not path.is_file() or not path.is_relative_to(base):
        return None
    return path


def _title(relative: str) -> str:
    name = Path(relative).name
    return {
        "constitution.md": "Zasady projektu",
        "spec.md": "Specyfikacja",
        "plan.md": "Plan techniczny",
        "research.md": "Analiza",
        "data-model.md": "Model danych",
        "quickstart.md": "Jak uruchomić",
        "tasks.md": "Zadania",
    }.get(name, name)
