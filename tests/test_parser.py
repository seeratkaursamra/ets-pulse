"""Tests for GTFS-Realtime parsing and the analytics reliability score."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import analytics, config  # noqa: E402
from src.parse_realtime import parse_trip_updates, parse_vehicle_positions  # noqa: E402

# Skip protobuf tests gracefully if bindings are not installed.
pb = pytest.importorskip("google.transit.gtfs_realtime_pb2")


def _trip_update_feed():
    feed = pb.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"

    ent = feed.entity.add()
    ent.id = "e1"
    tu = ent.trip_update
    tu.trip.trip_id = "T1"
    tu.trip.route_id = "8"
    tu.vehicle.id = "V100"
    stu = tu.stop_time_update.add()
    stu.stop_id = "S1"
    stu.stop_sequence = 3
    stu.arrival.time = 1_700_000_300
    stu.arrival.delay = 300  # 5 minutes late

    # Second stop with no prediction (should stay unknown-ish downstream).
    stu2 = tu.stop_time_update.add()
    stu2.stop_id = "S2"
    stu2.stop_sequence = 4
    return feed.SerializeToString()


def _vehicle_feed():
    feed = pb.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    ent = feed.entity.add()
    ent.id = "v1"
    v = ent.vehicle
    v.vehicle.id = "V100"
    v.trip.trip_id = "T1"
    v.trip.route_id = "8"
    v.position.latitude = 53.54
    v.position.longitude = -113.49
    v.position.bearing = 90.0
    v.timestamp = 1_700_000_000
    return feed.SerializeToString()


def test_parse_trip_updates_extracts_delay():
    records = parse_trip_updates(_trip_update_feed())
    assert len(records) == 2
    first = records[0]
    assert first["trip_id"] == "T1"
    assert first["route_id"] == "8"
    assert first["stop_id"] == "S1"
    assert first["stop_sequence"] == 3
    assert first["predicted_time"] == 1_700_000_300
    assert first["feed_delay_seconds"] == 300


def test_parse_trip_updates_missing_prediction():
    records = parse_trip_updates(_trip_update_feed())
    second = records[1]
    assert second["stop_id"] == "S2"
    assert second["predicted_time"] is None
    assert second["feed_delay_seconds"] is None


def test_parse_vehicle_positions():
    records = parse_vehicle_positions(_vehicle_feed())
    assert len(records) == 1
    v = records[0]
    assert v["vehicle_id"] == "V100"
    assert v["route_id"] == "8"
    assert round(v["latitude"], 2) == 53.54
    assert v["bearing"] == 90.0


def test_reliability_score_bounds():
    on_time = pd.DataFrame({
        "status": [config.STATUS_ON_TIME] * 5,
        "delay_seconds": [10, 20, 0, 30, 15],
    })
    major = pd.DataFrame({
        "status": [config.STATUS_MAJOR] * 5,
        "delay_seconds": [400, 500, 600, 450, 700],
    })
    assert analytics.reliability_score(on_time) == 100.0
    assert analytics.reliability_score(major) == 0.0


def test_reliability_excludes_unknown():
    mixed = pd.DataFrame({
        "status": [config.STATUS_ON_TIME, config.STATUS_UNKNOWN],
        "delay_seconds": [10, None],
    })
    # Only the on-time row counts -> perfect score.
    assert analytics.reliability_score(mixed) == 100.0
