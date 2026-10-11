"""Web-only database guards; collectors keep their independent writable engine.

Transaction guards are defense in depth, not a replacement for a SELECT-only
database login. Never change global/role defaults here: collectors share the DB.
"""

from functools import lru_cache

from sqlalchemy import Connection, Engine, event
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url


def _guard_postgres_transaction(connection: Connection) -> None:
    # Fixed SQL, before the first application query. LOCAL settings are reset
    # on commit/rollback, including when a pooled connection is reused.
    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")
    connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
    connection.exec_driver_sql("SET LOCAL idle_in_transaction_session_timeout = '20s'")


def create_web_session_factory(database_url: str) -> sessionmaker[Session]:
    engine: Engine = create_engine_for_url(database_url)
    if engine.dialect.name == "postgresql":
        event.listen(engine, "begin", _guard_postgres_transaction)
    elif engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def sqlite_read_only(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA query_only = ON")
            finally:
                cursor.close()
    else:
        engine.dispose()
        raise ValueError("The web database must use PostgreSQL or SQLite")
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@lru_cache(maxsize=1)
def get_web_session_factory() -> sessionmaker[Session]:
    settings = get_settings()
    return create_web_session_factory(settings.web_database_url or settings.database_url)
