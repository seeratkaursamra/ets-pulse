"""Fetch the GTFS-Realtime protobuf feeds from ETS.

Just returns the raw bytes. Parsing lives in parse_realtime so this stays a thin
network boundary that's easy to mock in tests.
"""
from __future__ import annotations

import requests

from . import config


class FeedUnavailable(RuntimeError):
    """Raised when a realtime feed can't be fetched."""


def _get(url: str, timeout: int = 30) -> bytes:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FeedUnavailable(f"Could not fetch {url}: {exc}") from exc
    return resp.content


def fetch_trip_updates(url: str | None = None) -> bytes:
    return _get(url or config.RT_TRIP_UPDATES_URL)


def fetch_vehicle_positions(url: str | None = None) -> bytes:
    return _get(url or config.RT_VEHICLE_POSITIONS_URL)


def fetch_alerts(url: str | None = None) -> bytes:
    return _get(url or config.RT_ALERTS_URL)
