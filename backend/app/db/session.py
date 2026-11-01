import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def resolve_database_url(url: str | None = None) -> str:
    resolved = url or os.getenv("DATABASE_URL")
    if not resolved:
        raise RuntimeError("DATABASE_URL must be set before connecting to the database")
    return resolved


def create_database_engine(url: str | None = None) -> Engine:
    database_url = resolve_database_url(url)
    engine = create_engine(database_url, pool_pre_ping=True)

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(connection, _record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache(maxsize=1)
def get_database_engine() -> Engine:
    return create_database_engine()


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = session_factory(get_database_engine())()
    try:
        yield session
    finally:
        session.close()
