from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def _ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return
    database_path = Path(database_url.removeprefix(prefix))
    database_path.parent.mkdir(parents=True, exist_ok=True)


def create_engine_for_url(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine with SQLite safety and concurrency pragmas enabled."""

    _ensure_sqlite_parent(database_url)
    is_sqlite = database_url.startswith("sqlite:")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine_options: dict[str, object] = {
        "echo": echo,
        "connect_args": connect_args,
        "pool_pre_ping": not is_sqlite,
        "pool_recycle": 300 if not is_sqlite else -1,
    }
    if not is_sqlite:
        # Keep each autoscaled Cloud Run instance from reserving SQLAlchemy's
        # much larger default connection pool against a small Supabase tier.
        engine_options.update(pool_size=2, max_overflow=1, pool_timeout=15)
    engine = create_engine(database_url, **engine_options)

    if database_url.startswith("sqlite:"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.close()

    return engine
