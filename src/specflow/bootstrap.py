"""Korzeń kompozycji: z ustawień budujemy harness, bazę i runtime (wstrzykiwanie zależności).

Reszta aplikacji widzi tylko interfejs `Harness` (ADR-0002); jedynie to miejsce wie,
który adapter wybrano w konfiguracji.
"""

from specflow.harness import Harness
from specflow.harness.demo import DemoHarness
from specflow.harness.opencode.adapter import OpenCodeHarness
from specflow.harness.opencode.client import OpenCodeClient
from specflow.orchestrator import OrchestratorConfig
from specflow.runtime import EventBus, Runtime
from specflow.settings import Settings
from specflow.storage import init_db, make_engine, session_factory
from specflow.verification import VerificationPolicy


def build_harness(settings: Settings) -> Harness:
    if settings.harness == "opencode":
        client = OpenCodeClient(settings.opencode_url, password=settings.opencode_password)
        return OpenCodeHarness(
            client,
            host_root=settings.projects_path(),
            container_root=settings.opencode_container_root,
        )
    return DemoHarness(step_delay_s=settings.mock_step_delay_s)


def build_runtime(settings: Settings, harness: Harness | None = None) -> Runtime:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.projects_path().mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.db_url())
    init_db(engine)
    command = settings.verification_command()
    policy = VerificationPolicy(test_command=command) if command else VerificationPolicy()
    return Runtime(
        sessions=session_factory(engine),
        harness=harness or build_harness(settings),
        bus=EventBus(),
        projects_dir=settings.projects_path(),
        verification=policy,
        orchestrator=OrchestratorConfig(task_timeout_s=settings.task_timeout_s),
    )
