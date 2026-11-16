from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Base
from storage.migrations import run_migrations


def default_database_path() -> Path:
    return Path.home() / ".remote-file-manager" / "app.sqlite3"


def create_database_engine(path: str | Path | None = None):
    db_path = Path(path) if path else default_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", future=True)


def init_database(path: str | Path | None = None) -> sessionmaker[Session]:
    engine = create_database_engine(path)
    run_migrations(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)
