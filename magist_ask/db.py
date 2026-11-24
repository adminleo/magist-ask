"""The database, opened so that a mistake upstream cannot write to it.

SQLite's URI form takes `mode=ro`, which makes the connection itself refuse
writes. The guard in guard.py is the first line and this is the second: if the
guard ever has a hole, the driver still says no.

The database is the one built by eniac-magist-analysis — 99,441 Brazilian
marketplace orders. It is 115 MB and not redistributed, so the path comes from
MAGIST_DB or from --db.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3

import pandas as pd

DEFAULT = pathlib.Path.home() / "Projects" / "git" / "eniac-magist-analysis" / "magist.db"


def path(explicit: str | None = None) -> pathlib.Path:
    p = pathlib.Path(explicit or os.environ.get("MAGIST_DB") or DEFAULT).expanduser()
    if not p.exists():
        raise FileNotFoundError(
            f"no database at {p}. Build it with eniac-magist-analysis, then set "
            f"MAGIST_DB=/path/to/magist.db")
    return p


def connect(explicit: str | None = None) -> sqlite3.Connection:
    p = path(explicit)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def schema(con: sqlite3.Connection) -> str:
    """Tables, columns and row counts, as the model sees them.

    Row counts are included on purpose. Without them a model will happily
    propose a join that returns eleven million rows, because nothing told it
    that order_items has 112,650 and products has 32,951.
    """
    lines = []
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in tables:
        n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        cols = [f"{r['name']} {r['type'] or 'TEXT'}"
                for r in con.execute(f'PRAGMA table_info("{t}")')]
        lines.append(f"{t} ({n:,} rows)\n  " + "\n  ".join(cols))
    return "\n\n".join(lines)


def run(con: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, con)
