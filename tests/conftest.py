import sys
from pathlib import Path

import pytest

from specflow.harness import AgentReport, RunFinished
from specflow.verification import JUNIT_PATH, VerificationPolicy
from specflow.verification.verifier import NO_BYTECODE
from specflow.workspace import Workspace

# Testy projektu generowanego przez "agenta" uruchamiamy tym samym interpreterem co nasze testy.
TEST_POLICY = VerificationPolicy(
    test_command=(
        f"{NO_BYTECODE} {sys.executable} -m pytest -q -p no:cacheprovider --junitxml={JUNIT_PATH}"
    ),
    test_timeout_s=120,
)


FAILING_TEST_SRC = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def done_run() -> RunFinished:
    return RunFinished(status="completed", report=AgentReport(status="done", summary="ok"))


@pytest.fixture
def project_ws(tmp_path: Path) -> Workspace:
    """Workspace projektu z konfiguracją pytest w commicie bazowym."""
    ws = Workspace.create(tmp_path, 1, "calc")
    (ws.path / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    ws.commit("base")
    return ws
