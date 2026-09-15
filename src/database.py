"""SQLite storage.

delay_observations holds one row per matched trip/stop per snapshot; routes,
stops, vehicles and alerts are reference/latest-state tables. Writes go through
the stdlib sqlite3 driver and reads come back as pandas DataFrames.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS routes (
    route_id        TEXT PRIMARY KEY,
    route_short_name TEXT,
    route_long_name  TEXT,
    route_type       INTEGER
);

CREATE TABLE IF NOT EXISTS stops (
    stop_id   TEXT PRIMARY KEY,
    stop_name TEXT,
    latitude  REAL,
    longitude REAL
);

CREATE TABLE IF NOT EXISTS delay_observations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at   TEXT NOT NULL,          -- ISO8601 UTC snapshot time
    service_date   TEXT,                   -- YYYY-MM-DD local service day
    trip_id        TEXT,
    route_id       TEXT,
    vehicle_id     TEXT,
    stop_id        TEXT,
    stop_sequence  INTEGER,
    scheduled_time TEXT,                   -- ISO8601 UTC
    predicted_time TEXT,                   -- ISO8601 UTC
    delay_seconds  INTEGER,                -- NULL means unknown
    status         TEXT,
    local_hour     INTEGER,                -- 0-23 local time of scheduled arrival
    day_of_week    INTEGER,                -- 0=Mon .. 6=Sun
    latitude       REAL,
    longitude      REAL,
    -- stops one trip/stop being counted twice in the same snapshot
    UNIQUE(collected_at, trip_id, stop_id, stop_sequence)
);

CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id  TEXT,
    trip_id     TEXT,
    route_id    TEXT,
    latitude    REAL,
    longitude   REAL,
    bearing     REAL,
    status      TEXT,
    delay_seconds INTEGER,
    recorded_at TEXT,
    collected_at TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id     TEXT,
    route_id     TEXT,
    stop_id      TEXT,
    header       TEXT,
    description  TEXT,
    active_start TEXT,
    active_end   TEXT,
    collected_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_obs_route ON delay_observations(route_id);
CREATE INDEX IF NOT EXISTS idx_obs_stop ON delay_observations(stop_id);
CREATE INDEX IF NOT EXISTS idx_obs_collected ON delay_observations(collected_at);
CREATE INDEX IF NOT EXISTS idx_obs_service_date ON delay_observations(service_date);
"""


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or config.DB_PATH)
    _ensure_parent(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize(db_path: Path | None = None) -> None:
    """Create the tables and indexes if they aren't there yet."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_routes(rows: Iterable[dict], db_path: Path | None = None) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with connect(db_path) as conn:
        conn.executemany(
            """INSERT INTO routes(route_id, route_short_name, route_long_name, route_type)
               VALUES(:route_id, :route_short_name, :route_long_name, :route_type)
               ON CONFLICT(route_id) DO UPDATE SET
                 route_short_name=excluded.route_short_name,
                 route_long_name=excluded.route_long_name,
                 route_type=excluded.route_type""",
            rows,
        )
    return len(rows)


def upsert_stops(rows: Iterable[dict], db_path: Path | None = None) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with connect(db_path) as conn:
        conn.executemany(
            """INSERT INTO stops(stop_id, stop_name, latitude, longitude)
               VALUES(:stop_id, :stop_name, :latitude, :longitude)
               ON CONFLICT(stop_id) DO UPDATE SET
                 stop_name=excluded.stop_name,
                 latitude=excluded.latitude,
                 longitude=excluded.longitude""",
            rows,
        )
    return len(rows)


def insert_observations(rows: Iterable[dict], db_path: Path | None = None) -> int:
    """Insert observations, skipping duplicates inside a snapshot."""
    rows = list(rows)
    if not rows:
        return 0
    cols = [
        "collected_at", "service_date", "trip_id", "route_id", "vehicle_id",
        "stop_id", "stop_sequence", "scheduled_time", "predicted_time",
        "delay_seconds", "status", "local_hour", "day_of_week",
        "latitude", "longitude",
    ]
    placeholders = ", ".join(f":{c}" for c in cols)
    with connect(db_path) as conn:
        cur = conn.executemany(
            f"INSERT OR IGNORE INTO delay_observations({', '.join(cols)}) "
            f"VALUES({placeholders})",
            [{c: r.get(c) for c in cols} for r in rows],
        )
        return cur.rowcount


def replace_vehicles(rows: Iterable[dict], db_path: Path | None = None) -> int:
    """Append a vehicle snapshot; the dashboard just reads the newest one."""
    rows = list(rows)
    if not rows:
        return 0
    cols = [
        "vehicle_id", "trip_id", "route_id", "latitude", "longitude",
        "bearing", "status", "delay_seconds", "recorded_at", "collected_at",
    ]
    placeholders = ", ".join(f":{c}" for c in cols)
    with connect(db_path) as conn:
        conn.executemany(
            f"INSERT INTO vehicles({', '.join(cols)}) VALUES({placeholders})",
            [{c: r.get(c) for c in cols} for r in rows],
        )
    return len(rows)


def read_sql(query: str, params: tuple | dict | None = None,
             db_path: Path | None = None) -> pd.DataFrame:
    path = Path(db_path or config.DB_PATH)
    if not path.exists():
        return pd.DataFrame()
    with connect(path) as conn:
        return pd.read_sql_query(query, conn, params=params)


def table_counts(db_path: Path | None = None) -> dict:
    """Row counts for the main tables."""
    out = {}
    for tbl in ("delay_observations", "routes", "stops", "vehicles", "alerts"):
        try:
            df = read_sql(f"SELECT COUNT(*) AS n FROM {tbl}", db_path=db_path)
            out[tbl] = int(df["n"].iloc[0]) if not df.empty else 0
        except Exception:
            out[tbl] = 0
    return out
