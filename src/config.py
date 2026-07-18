"""Central configuration for ETS Pulse.

Keeps feed URLs, delay thresholds, and filesystem paths in one place so the
collection scripts, analytics layer, and dashboard all agree on the rules.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
STATIC_DIR = DATA_DIR / "static"
DB_PATH = Path(os.getenv("ETS_DB_PATH", DATA_DIR / "ets_delays.db"))

# --- Timezone --------------------------------------------------------------
# Edmonton is Mountain Time. We store timestamps in UTC internally but reason
# about "service day" and local hour using this zone.
LOCAL_TZ = "America/Edmonton"

# --- GTFS feed URLs (Edmonton Transit Service) -----------------------------
# Realtime feeds describe "now"; ETS Pulse collects snapshots to build history.
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

# --- Delay methodology -----------------------------------------------------
# delay_seconds = predicted_arrival - scheduled_arrival
# Positive => late, negative => early.
# Thresholds (seconds) from the project blueprint.
EARLY_MAX = -60          # < -60s  => early
ON_TIME_MAX = 120        # -60..+120s => on time
SLIGHT_DELAY_MAX = 300   # +121..+300s => slight delay
# > +300s => major delay

STATUS_EARLY = "Early"
STATUS_ON_TIME = "On time"
STATUS_SLIGHT = "Slight delay"
STATUS_MAJOR = "Major delay"
STATUS_UNKNOWN = "Unknown"

# A "late" observation for headline stats: slight or major delay.
LATE_THRESHOLD_SECONDS = ON_TIME_MAX  # anything above +120s counts as late

# Sample-size guardrail: warn when aggregates are based on fewer than this.
MIN_CONFIDENT_OBSERVATIONS = 30


def classify_delay(delay_seconds) -> str:
    """Map a delay in seconds to a human-readable status.

    A missing/None delay is Unknown and must never be treated as on time,
    otherwise route performance is falsely improved.
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
