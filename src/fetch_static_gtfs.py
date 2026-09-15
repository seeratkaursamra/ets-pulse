"""Download and read the static GTFS schedule (routes, stops, trips, times).

The static feed barely changes, so the zip is cached under data/static/ and only
re-downloaded when asked. Loaders hand back DataFrames.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from . import config

STATIC_ZIP = config.STATIC_DIR / "gtfs_static.zip"


def download_static(url: str | None = None, force: bool = False) -> Path:
    """Grab the GTFS zip into data/static/ and return its path."""
    url = url or config.GTFS_STATIC_URL
    config.STATIC_DIR.mkdir(parents=True, exist_ok=True)
    if STATIC_ZIP.exists() and not force:
        return STATIC_ZIP
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    STATIC_ZIP.write_bytes(resp.content)
    return STATIC_ZIP


def _read_from_zip(name: str, zip_path: Path | None = None) -> pd.DataFrame:
    """Read one .txt file out of the GTFS zip."""
    zip_path = Path(zip_path or STATIC_ZIP)
    if not zip_path.exists():
        return pd.DataFrame()
    with zipfile.ZipFile(zip_path) as zf:
        if name not in zf.namelist():
            return pd.DataFrame()
        with zf.open(name) as fh:
            return pd.read_csv(io.TextIOWrapper(fh, "utf-8-sig"), dtype=str)


def load_routes(zip_path: Path | None = None) -> pd.DataFrame:
    df = _read_from_zip("routes.txt", zip_path)
    if df.empty:
        return df
    keep = ["route_id", "route_short_name", "route_long_name", "route_type"]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    return df[keep]


def load_stops(zip_path: Path | None = None) -> pd.DataFrame:
    df = _read_from_zip("stops.txt", zip_path)
    if df.empty:
        return df
    df = df.rename(columns={"stop_lat": "latitude", "stop_lon": "longitude"})
    keep = ["stop_id", "stop_name", "latitude", "longitude"]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    return df[keep]


def load_trips(zip_path: Path | None = None) -> pd.DataFrame:
    return _read_from_zip("trips.txt", zip_path)


def load_stop_times(zip_path: Path | None = None) -> pd.DataFrame:
    """stop_times is big, so just return the columns matching needs."""
    df = _read_from_zip("stop_times.txt", zip_path)
    if df.empty:
        return df
    keep = ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    return df[keep]
