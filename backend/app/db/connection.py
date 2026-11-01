from sqlalchemy import text

from .session import create_database_engine


def check_database_connection(url: str | None = None) -> bool:
    engine = create_database_engine(url)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()
