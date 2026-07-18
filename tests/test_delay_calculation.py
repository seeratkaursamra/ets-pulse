"""Tests for delay calculation, GTFS time handling, and status thresholds."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402
from src.calculate_delays import (  # noqa: E402
    compute_delay_seconds,
    delay_minutes,
    parse_gtfs_time_to_seconds,
    scheduled_timestamp,
)


def test_gtfs_time_normal():
    assert parse_gtfs_time_to_seconds("08:30:00") == 8 * 3600 + 30 * 60


def test_gtfs_time_after_midnight():
    # 25:10:00 => 1:10 AM next day = 90600 seconds after service-day midnight.
    assert parse_gtfs_time_to_seconds("25:10:00") == 90600


def test_scheduled_timestamp_rolls_past_midnight():
    service_date = datetime(2026, 1, 5)
    ts = scheduled_timestamp(service_date, "25:10:00")
    assert ts.day == 6 and ts.hour == 1 and ts.minute == 10


def test_compute_delay_from_epochs():
    assert compute_delay_seconds(1000, 1180) == 180


def test_compute_delay_from_datetimes():
    a = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    b = datetime(2026, 1, 1, 8, 5, 0, tzinfo=timezone.utc)
    assert compute_delay_seconds(a, b) == 300


def test_missing_values_are_unknown():
    assert compute_delay_seconds(None, 1200) is None
    assert compute_delay_seconds(1000, None) is None
    assert config.classify_delay(None) == config.STATUS_UNKNOWN


def test_status_thresholds():
    assert config.classify_delay(-120) == config.STATUS_EARLY
    assert config.classify_delay(0) == config.STATUS_ON_TIME
    assert config.classify_delay(120) == config.STATUS_ON_TIME
    assert config.classify_delay(200) == config.STATUS_SLIGHT
    assert config.classify_delay(300) == config.STATUS_SLIGHT
    assert config.classify_delay(600) == config.STATUS_MAJOR


def test_status_boundaries_exact():
    # -60 is the early/on-time boundary: -60 is on time, -61 is early.
    assert config.classify_delay(-60) == config.STATUS_ON_TIME
    assert config.classify_delay(-61) == config.STATUS_EARLY
    # 301 crosses into major.
    assert config.classify_delay(301) == config.STATUS_MAJOR


def test_delay_minutes():
    assert delay_minutes(90) == 1.5
    assert delay_minutes(None) is None
