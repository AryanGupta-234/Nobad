from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.private_paths import APP_DIR_NAME, app_data_dir, ensure_private_file
from storage.models import Base
from storage.migrations import run_migrations

DATABASE_FILE_NAME = "app.sqlite3"
IN_MEMORY = ":memory:"


def default_database_path() -> Path:
    return Path.home() / APP_DIR_NAME / DATABASE_FILE_NAME


def create_database_engine(path: str | Path | None = None):
    if str(path) == IN_MEMORY:
        return create_engine(f"sqlite:///{IN_MEMORY}", future=True)
    if path:
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        db_path = app_data_dir() / DATABASE_FILE_NAME
    # Created 0600 before SQLite opens it; SQLite gives its -journal/-wal files the same mode as the database (#31).
    ensure_private_file(db_path)
    return create_engine(f"sqlite:///{db_path}", future=True)


def init_database(path: str | Path | None = None) -> sessionmaker[Session]:
    engine = create_database_engine(path)
    run_migrations(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)
