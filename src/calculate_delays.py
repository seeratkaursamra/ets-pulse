"""Delay calculation and GTFS time helpers.

The delay definition is intentionally simple and reproducible:

    delay_seconds = predicted_arrival_timestamp - scheduled_arrival_timestamp

The tricky parts are:
  * GTFS schedule times can exceed 24:00:00 (a trip that starts before midnight
    and continues into the next service day). "25:10:00" means 1:10 AM on the
    day after the service date.
  * A missing prediction must stay Unknown, never silently become 0/on-time.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from . import config


def parse_gtfs_time_to_seconds(gtfs_time: str) -> int:
    """Convert a GTFS "HH:MM:SS" time (possibly > 24h) into seconds after
    midnight of the service day.

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
    """Combine a service date (midnight) with a GTFS time that may exceed 24h.

    service_date should be the midnight datetime of the service day.
    """
    base = service_date.replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(seconds=parse_gtfs_time_to_seconds(gtfs_time))


def compute_delay_seconds(
    scheduled: Optional[datetime | int | float],
    predicted: Optional[datetime | int | float],
) -> Optional[int]:
    """Return delay in seconds (predicted - scheduled), or None if unknown.

    Accepts either datetimes or POSIX epoch seconds for each argument, as long
    as both are the same kind. Returns None when either side is missing.
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
    """Human-facing minutes, rounded to one decimal. None stays None."""
    if delay_seconds is None:
        return None
    return round(delay_seconds / 60.0, 1)


def classify(delay_seconds: Optional[int]) -> str:
    """Convenience re-export so callers can import everything from one module."""
    return config.classify_delay(delay_seconds)
