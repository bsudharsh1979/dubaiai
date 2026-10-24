"""Startup: migrations (Alembic), seed, worker.  Also the demo reset."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import API_DIR, get_settings
from .db import get_engine, reset_engine, session_scope

log = logging.getLogger("rainready.bootstrap")


def alembic_config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def migrate() -> None:
    command.upgrade(alembic_config(), "head")


def seed_if_empty() -> dict:
    from .seed.fixtures import seed
    with session_scope() as db:
        return seed(db)


def startup() -> dict:
    s = get_settings()
    get_engine()
    info = {"migrated": False, "seeded": False}
    if s.auto_migrate:
        migrate()
        info["migrated"] = True
    if s.auto_seed:
        info["seeded"] = seed_if_empty().get("seeded", False)
    return info


def _wipe_sqlite(path: str) -> None:
    """Remove a SQLite database file; if the OS refuses because another thread still holds it open
    (Windows), fall back to dropping every table so the schema is recreated by the migration."""
    import sqlite3
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except PermissionError:
        con = sqlite3.connect(path)
        try:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")]
            for n in names:
                con.execute(f'DROP TABLE IF EXISTS "{n}"')
            con.commit()
        finally:
            con.close()
    for side in ("-wal", "-shm"):
        try:
            Path(path + side).unlink()
        except (FileNotFoundError, PermissionError):
            pass


def reset_database() -> None:
    """Demo-only: drop everything (including graph checkpoints) and re-seed."""
    from .agents import runner
    from .agents.graph import checkpoint_db_path
    s = get_settings()
    runner.reset_graph()
    reset_engine()
    if s.is_sqlite:
        path = s.database_url.replace("sqlite:///", "")
        for p in (path, checkpoint_db_path()):
            _wipe_sqlite(p)
    else:
        from sqlalchemy import text
        eng = get_engine()
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        reset_engine()
    get_engine()
    migrate()
    seed_if_empty()
