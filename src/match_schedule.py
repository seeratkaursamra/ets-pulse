"""Match GTFS-Realtime predictions to the static schedule.

Edmonton's realtime trip updates usually provide a predicted absolute arrival
time but not the delay, and often omit route_id. To compute a real delay we need
the *scheduled* arrival, which lives in the static feed:

    scheduled = start_date (service day) + stop_times.arrival_time
    delay_seconds = predicted - scheduled

This module loads the static schedule once into in-memory lookups and exposes
helpers to resolve a scheduled epoch and a route for a given trip. GTFS times
past 24:00:00 are handled on the correct service day.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, fetch_static_gtfs
from .calculate_delays import parse_gtfs_time_to_seconds

LOCAL = ZoneInfo(config.LOCAL_TZ)


class ScheduleIndex:
    """In-memory index of the static schedule for fast realtime matching."""

    def __init__(self) -> None:
        # trip_id -> {stop_sequence(int): arrival_time_str}
        self._sched: dict[str, dict[int, str]] = {}
        # trip_id -> {stop_id(str): arrival_time_str}  (fallback match)
        self._sched_by_stop: dict[str, dict[str, str]] = {}
        # trip_id -> route_id
        self._trip_route: dict[str, str] = {}
        self.loaded = False

    def load(self) -> "ScheduleIndex":
        stop_times = fetch_static_gtfs.load_stop_times()
        trips = fetch_static_gtfs.load_trips()

        if not trips.empty and "route_id" in trips.columns:
            self._trip_route = dict(
                zip(trips["trip_id"].astype(str), trips["route_id"].astype(str)))

        if not stop_times.empty:
            for row in stop_times.itertuples(index=False):
                trip_id = str(row.trip_id)
                arrival = row.arrival_time
                if arrival is None or (isinstance(arrival, float)):
                    continue
                try:
                    seq = int(row.stop_sequence)
                except (TypeError, ValueError):
                    seq = None
                if seq is not None:
                    self._sched.setdefault(trip_id, {})[seq] = arrival
                if row.stop_id is not None:
                    self._sched_by_stop.setdefault(trip_id, {})[str(row.stop_id)] = arrival

        self.loaded = True
        return self

    def route_for_trip(self, trip_id: str | None) -> str | None:
        if not trip_id:
            return None
        return self._trip_route.get(str(trip_id))

    def scheduled_epoch(self, trip_id: str | None, stop_sequence, stop_id,
                        start_date: str | None) -> int | None:
        """Return the scheduled arrival as a UTC epoch, or None if unmatched.

        start_date is the GTFS trip start_date (YYYYMMDD) marking the service day.
        """
        if not trip_id or not start_date:
            return None
        trip_id = str(trip_id)

        arrival = None
        if stop_sequence is not None:
            try:
                arrival = self._sched.get(trip_id, {}).get(int(stop_sequence))
            except (TypeError, ValueError):
                arrival = None
        if arrival is None and stop_id is not None:
            arrival = self._sched_by_stop.get(trip_id, {}).get(str(stop_id))
        if arrival is None:
            return None

        try:
            base = datetime.strptime(start_date, "%Y%m%d")
        except ValueError:
            return None
        base_local = base.replace(tzinfo=LOCAL)
        secs = parse_gtfs_time_to_seconds(arrival)
        scheduled_local = base_local + timedelta(seconds=secs)
        return int(scheduled_local.astimezone(timezone.utc).timestamp())
