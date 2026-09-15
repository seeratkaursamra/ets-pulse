"""Delay math and GTFS time helpers.

delay_seconds = predicted_arrival - scheduled_arrival

Watch out for two things: GTFS times can go past 24:00:00 (a trip that runs
past midnight, so "25:10:00" means 1:10 AM the next day), and a missing
prediction has to stay Unknown instead of quietly becoming zero.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from . import config


def parse_gtfs_time_to_seconds(gtfs_time: str) -> int:
    """GTFS "HH:MM:SS" (can be > 24h) to seconds after midnight.

    >>> parse_gtfs_time_to_seconds("08:30:00")
    30600
    >>> parse_gtfs_time_to_seconds("25:10:00")
    90600
    """
    parts = gtfs_time.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid GTFS time: {gtfs_time!r}")
    hours, minutes, seconds = (int(p) for p in parts)
    return hours * 3600 + minutes * 60 + seconds


def scheduled_timestamp(service_date: datetime, gtfs_time: str) -> datetime:
    """Add a GTFS time (possibly past 24h) onto a service day's midnight."""
    base = service_date.replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(seconds=parse_gtfs_time_to_seconds(gtfs_time))


def compute_delay_seconds(
    scheduled: Optional[datetime | int | float],
    predicted: Optional[datetime | int | float],
) -> Optional[int]:
    """predicted - scheduled, in seconds. None if either side is missing.

    Both args can be datetimes or epoch seconds, as long as they match.
    """
    if scheduled is None or predicted is None:
        return None

    if isinstance(scheduled, datetime) and isinstance(predicted, datetime):
        return int((predicted - scheduled).total_seconds())

    try:
        return int(float(predicted) - float(scheduled))
    except (TypeError, ValueError):
        return None


def delay_minutes(delay_seconds: Optional[int]) -> Optional[float]:
    """Seconds to minutes for display. None stays None."""
    if delay_seconds is None:
        return None
    return round(delay_seconds / 60.0, 1)


def classify(delay_seconds: Optional[int]) -> str:
    return config.classify_delay(delay_seconds)
