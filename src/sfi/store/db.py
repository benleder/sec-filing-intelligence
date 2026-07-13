"""SQLite access. L1 — imports common only.

schema.sql stays verbatim §3.1 (no IF NOT EXISTS edits); init_db keeps
application idempotent by checking sqlite_master first. FactWriter and
FactReader land at P0.5.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..common import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = config.DB_PATH if path is None else path
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(path: Path | None = None) -> None:
    path = config.DB_PATH if path is None else path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = connect(path)
    try:
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "facts" not in tables:
            con.executescript(SCHEMA_PATH.read_text())
            con.commit()
    finally:
        con.close()
