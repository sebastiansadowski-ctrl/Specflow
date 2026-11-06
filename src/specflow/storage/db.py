"""Silnik bazy i sesje. W F00 schemat tworzony przez `create_all`;
migracje Alembic dochodzą, gdy schemat się ustabilizuje (najpóźniej w F04).

Ustawienia SQLite (ADR-0008):
- WAL: odczyty (SSE, widoki) nie blokują zapisów workera i odwrotnie;
- synchronous=FULL: zatwierdzony zapis przeżywa także utratę zasilania;
- busy_timeout: krótkie czekanie na blokadę zamiast błędu "database is locked".
Zasada w kodzie: transakcja zapisu nie może być otwarta podczas `await` na agencie
(patrz `runtime.boundary`), bo blokowałaby wszystkie inne zapisy.
"""

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from specflow.storage.models import Base

DEFAULT_URL = "sqlite:///var/specflow.sqlite3"
BUSY_TIMEOUT_MS = 5000
SQLITE_PRAGMAS = (
    "PRAGMA foreign_keys=ON",
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=FULL",
    f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
)


def make_engine(url: str = DEFAULT_URL) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url)
    # Jedna pętla asyncio, ale endpointy synchroniczne FastAPI działają w puli wątków.
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)  # w bazie w pamięci WAL po cichu zostaje "memory"
        cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
