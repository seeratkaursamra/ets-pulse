"""Match realtime predictions back to the static schedule.

ETS trip updates usually give a predicted arrival time but no delay, and often
leave out route_id. To get a real delay we need the scheduled arrival from the
static feed:

    scheduled = start_date (service day) + stop_times.arrival_time
    delay_seconds = predicted - scheduled

The schedule is loaded once into in-memory lookups. GTFS times past 24:00:00 are
handled on the right service day.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, fetch_static_gtfs
from .calculate_delays import parse_gtfs_time_to_seconds

LOCAL = ZoneInfo(config.LOCAL_TZ)


class ScheduleIndex:
    """In-memory view of the schedule, keyed for quick lookups."""

    def __init__(self) -> None:
        self._sched: dict[str, dict[int, str]] = {}          # trip -> {seq: time}
        self._sched_by_stop: dict[str, dict[str, str]] = {}  # trip -> {stop: time}
        self._trip_route: dict[str, str] = {}                # trip -> route
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
        """Scheduled arrival as a UTC epoch, or None if we can't match it.

        start_date is the trip's GTFS start_date (YYYYMMDD), i.e. the service day.
        """
        if not trip_id or not start_date:
            return None
        trip_id = str(trip_id)

        # match on stop_sequence first, fall back to stop_id
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
