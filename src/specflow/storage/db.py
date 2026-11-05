"""Silnik bazy i sesje. W F00 schemat tworzony przez `create_all`;
migracje Alembic dochodzą, gdy schemat się ustabilizuje (najpóźniej w F04)."""

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from specflow.storage.models import Base

DEFAULT_URL = "sqlite:///var/specflow.sqlite3"


def make_engine(url: str = DEFAULT_URL) -> Engine:
    engine = create_engine(url)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
