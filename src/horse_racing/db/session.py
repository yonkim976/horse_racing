from sqlalchemy.orm import Session, sessionmaker

from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url

engine = create_engine_for_url(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def open_session() -> Session:
    return SessionLocal()
