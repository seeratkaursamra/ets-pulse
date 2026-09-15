"""Shared settings: feed URLs, delay thresholds, and paths."""
from __future__ import annotations

import os
from pathlib import Path

# paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
STATIC_DIR = DATA_DIR / "static"
DB_PATH = Path(os.getenv("ETS_DB_PATH", DATA_DIR / "ets_delays.db"))

# Edmonton is Mountain Time. Timestamps are stored in UTC and converted to this
# zone when we need the local hour or service day.
LOCAL_TZ = "America/Edmonton"

# GTFS feeds (Edmonton Transit). Realtime only shows "now", so we snapshot it.
GTFS_STATIC_URL = os.getenv(
    "ETS_GTFS_STATIC_URL",
    "https://gtfs.edmonton.ca/TMGTFSRealTimeWebService/GTFS/gtfs.zip",
)
RT_TRIP_UPDATES_URL = os.getenv(
    "ETS_RT_TRIP_UPDATES_URL",
    "http://gtfs.edmonton.ca/TMGTFSRealTimeWebService/TripUpdate/TripUpdates.pb",
)
RT_VEHICLE_POSITIONS_URL = os.getenv(
    "ETS_RT_VEHICLE_POSITIONS_URL",
    "http://gtfs.edmonton.ca/TMGTFSRealTimeWebService/Vehicle/VehiclePositions.pb",
)
RT_ALERTS_URL = os.getenv(
    "ETS_RT_ALERTS_URL",
    "http://gtfs.edmonton.ca/TMGTFSRealTimeWebService/Alert/Alerts.pb",
)

# delay = predicted - scheduled (positive is late). Thresholds in seconds.
EARLY_MAX = -60          # below this: early
ON_TIME_MAX = 120        # up to +2 min: on time
SLIGHT_DELAY_MAX = 300   # up to +5 min: slight delay, above that: major

STATUS_EARLY = "Early"
STATUS_ON_TIME = "On time"
STATUS_SLIGHT = "Slight delay"
STATUS_MAJOR = "Major delay"
STATUS_UNKNOWN = "Unknown"

# anything more than 2 min late counts as "late" for headline numbers
LATE_THRESHOLD_SECONDS = ON_TIME_MAX

# warn about averages built on fewer observations than this
MIN_CONFIDENT_OBSERVATIONS = 30


def classify_delay(delay_seconds) -> str:
    """Turn a delay in seconds into a status label.

    None stays Unknown. Don't ever treat a missing value as on time, or the
    numbers end up looking better than reality.
    """
    if delay_seconds is None:
        return STATUS_UNKNOWN
    try:
        d = float(delay_seconds)
    except (TypeError, ValueError):
        return STATUS_UNKNOWN
    if d < EARLY_MAX:
        return STATUS_EARLY
    if d <= ON_TIME_MAX:
        return STATUS_ON_TIME
    if d <= SLIGHT_DELAY_MAX:
        return STATUS_SLIGHT
    return STATUS_MAJOR


DISCLAIMER = (
    "ETS Pulse is an independent educational and portfolio project. It is not "
    "affiliated with, endorsed by, or an official product of Edmonton Transit "
    "Service or the City of Edmonton."
)
