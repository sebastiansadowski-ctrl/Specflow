"""Konfiguracja Specflow, czytana raz przy starcie (ADR-0008).

Źródła, od najważniejszego:
1. argumenty wiersza poleceń (`specflow serve --harness mock`),
2. zmienne środowiskowe z prefiksem `SPECFLOW_` (np. `SPECFLOW_HARNESS=opencode`),
3. plik `.env` w bieżącym katalogu,
4. wartości domyślne poniżej.

Zmiana harnessu wymaga restartu: sesje jednego harnessu nie istnieją w drugim.
"""

import sys
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from specflow.verification import JUNIT_PATH
from specflow.verification.verifier import NO_BYTECODE

HarnessKind = Literal["mock", "opencode"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPECFLOW_", env_file=".env", extra="ignore")

    harness: HarnessKind = "mock"
    """mock = nagrany scenariusz demo (bez modelu); opencode = prawdziwy agent."""

    host: str = "127.0.0.1"
    port: int = 8000

    data_dir: Path = Path("var")
    database_url: str | None = None
    """Domyślnie `sqlite:///<data_dir>/specflow.sqlite3`."""
    projects_dir: Path | None = None
    """Katalog workspace'ów projektów. Domyślnie `<data_dir>/projects`."""

    opencode_url: str = "http://127.0.0.1:4096"
    opencode_password: str | None = None
    opencode_container_root: str = "/workspace"
    """Pod jaką ścieżką `projects_dir` jest widoczny w kontenerze agenta."""

    spec_kit_init: bool | None = None
    """`specify init` w nowym projekcie. Domyślnie tylko z OpenCode (wymaga CLI Spec Kit)."""
    test_command: str | None = None
    """Komenda testów w weryfikacji. Domyślnie `uv run pytest`; w demo bieżący interpreter."""

    mock_step_delay_s: float = Field(default=0.4, ge=0)
    """Przerwa między zdarzeniami Mocka, żeby w demo było widać postęp na żywo."""
    task_timeout_s: float = Field(default=1800, gt=0)
    shutdown_grace_s: float = Field(default=20, ge=0)
    """Ile czekamy na dokończenie bieżącego kroku przy zamykaniu, zanim go przerwiemy."""

    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'specflow.sqlite3'}"

    def projects_path(self) -> Path:
        return self.projects_dir or self.data_dir / "projects"

    def should_init_spec_kit(self) -> bool:
        return self.harness == "opencode" if self.spec_kit_init is None else self.spec_kit_init

    def verification_command(self) -> str | None:
        """None = domyślna komenda z VerificationPolicy."""
        if self.test_command:
            return self.test_command
        if self.harness == "mock":
            # Mock uruchamia testy lokalnie, tym samym interpreterem co Specflow.
            return (
                f"{NO_BYTECODE} {sys.executable} -m pytest -q -p no:cacheprovider "
                f"--junitxml={JUNIT_PATH}"
            )
        return None
