"""Collect one realtime snapshot from ETS feeds and store observations.

Run this on a schedule (e.g. every 5 minutes via cron) to build history:

    python -m scripts.collect_snapshot

Delay definition (blueprint):
    delay_seconds = predicted_arrival - scheduled_arrival
GTFS-Realtime provides this delay directly on each stop_time_update; when a
predicted absolute time is present we derive the scheduled time as
predicted - delay so we can bucket by local hour and service day.
Missing information stays Unknown - never silently on time.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import (  # noqa: E402
    config,
    database,
    fetch_realtime,
    fetch_static_gtfs,
    match_schedule,
    parse_realtime,
)
from src.calculate_delays import classify  # noqa: E402

LOCAL = ZoneInfo(config.LOCAL_TZ)


def _iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _local_parts(epoch: int | None):
    """Return (service_date, local_hour, day_of_week) from a UTC epoch."""
    if epoch is None:
        return None, None, None
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(LOCAL)
    return dt.strftime("%Y-%m-%d"), dt.hour, dt.weekday()


def _next_stop_per_trip(updates: list[dict]) -> list[dict]:
    """Reduce many stop_time_updates to one record per active trip: its next stop.

    Edmonton's feed publishes updates for every scheduled trip of the day, but a
    genuine "observation" is an in-service vehicle's current delay. We therefore
    keep only trips that have a vehicle assigned, and for each we take the next
    upcoming stop (smallest stop_sequence carrying a prediction). Over repeated
    snapshots this builds a clean, real delay history.
    """
    best: dict[str, dict] = {}
    for rec in updates:
        if not rec.get("vehicle_id") or not rec.get("trip_id"):
            continue
        if rec.get("predicted_time") is None and rec.get("feed_delay_seconds") is None:
            continue
        trip_id = rec["trip_id"]
        seq = rec.get("stop_sequence")
        seq_val = seq if seq is not None else 10**9
        cur = best.get(trip_id)
        if cur is None or seq_val < (cur.get("stop_sequence") or 10**9):
            best[trip_id] = rec
    return list(best.values())


def sync_static_reference() -> None:
    """Refresh routes/stops reference tables from the static GTFS (best-effort)."""
    try:
        fetch_static_gtfs.download_static()
        routes = fetch_static_gtfs.load_routes()
        stops = fetch_static_gtfs.load_stops()
        if not routes.empty:
            database.upsert_routes(routes.to_dict("records"))
        if not stops.empty:
            database.upsert_stops(stops.to_dict("records"))
        print(f"Static reference synced: {len(routes)} routes, {len(stops)} stops")
    except Exception as exc:  # keep collecting even if static is unavailable
        print(f"Static reference sync skipped: {exc}")


def collect_once(schedule: match_schedule.ScheduleIndex | None = None) -> int:
    """Fetch, parse, compute delays, and store one snapshot. Returns rows added.

    A loaded ScheduleIndex enables proper matching (predicted - scheduled) and
    route lookup for realtime records that omit route_id. Without it, we fall
    back to any delay the feed reports directly.
    """
    database.initialize()
    collected_at = datetime.now(timezone.utc).isoformat()

    # --- Trip updates -> delay observations --------------------------------
    try:
        raw_tu = fetch_realtime.fetch_trip_updates()
        updates = parse_realtime.parse_trip_updates(raw_tu)
    except fetch_realtime.FeedUnavailable as exc:
        print(f"Trip updates unavailable: {exc}")
        updates = []

    # A trip update predicts every downstream stop; recording all of them would
    # massively over-count and bias stats toward the current day. We keep one
    # observation per trip: the next upcoming stop (lowest stop_sequence that
    # has a prediction). Over repeated snapshots this builds real history.
    updates = _next_stop_per_trip(updates)

    observations = []
    for rec in updates:
        predicted = rec.get("predicted_time")
        feed_delay = rec.get("feed_delay_seconds")
        trip_id = rec.get("trip_id")

        # Resolve route: prefer the feed value, fall back to trips.txt.
        route_id = rec.get("route_id")
        if not route_id and schedule is not None:
            route_id = schedule.route_for_trip(trip_id)

        # Determine scheduled time and delay, in priority order:
        #   1) match static schedule (scheduled -> delay = predicted - scheduled)
        #   2) feed-provided delay (scheduled = predicted - delay)
        scheduled = None
        if schedule is not None:
            scheduled = schedule.scheduled_epoch(
                trip_id, rec.get("stop_sequence"), rec.get("stop_id"),
                rec.get("start_date"))

        delay = None
        if scheduled is not None and predicted is not None:
            delay = predicted - scheduled
        elif feed_delay is not None:
            delay = feed_delay
            if predicted is not None:
                scheduled = predicted - feed_delay

        service_date, local_hour, dow = _local_parts(
            scheduled if scheduled is not None else predicted)

        observations.append({
            "collected_at": collected_at,
            "service_date": service_date,
            "trip_id": trip_id,
            "route_id": route_id,
            "vehicle_id": rec.get("vehicle_id"),
            "stop_id": rec.get("stop_id"),
            "stop_sequence": rec.get("stop_sequence"),
            "scheduled_time": _iso(scheduled),
            "predicted_time": _iso(predicted),
            "delay_seconds": delay,
            "status": classify(delay),
            "local_hour": local_hour,
            "day_of_week": dow,
            "latitude": None,
            "longitude": None,
        })

    added = database.insert_observations(observations)

    # Build a trip -> (delay, status) lookup so live vehicles can be colored.
    trip_delay = {o["trip_id"]: (o["delay_seconds"], o["status"])
                  for o in observations if o.get("trip_id")}

    # --- Vehicle positions -> latest map layer -----------------------------
    try:
        raw_vp = fetch_realtime.fetch_vehicle_positions()
        vehicles = parse_realtime.parse_vehicle_positions(raw_vp)
    except fetch_realtime.FeedUnavailable as exc:
        print(f"Vehicle positions unavailable: {exc}")
        vehicles = []

    vehicle_rows = []
    for v in vehicles:
        delay, status = trip_delay.get(v.get("trip_id"), (None, config.STATUS_UNKNOWN))
        route_id = v.get("route_id") or (
            schedule.route_for_trip(v.get("trip_id")) if schedule else None)
        vehicle_rows.append({
            "vehicle_id": v.get("vehicle_id"),
            "trip_id": v.get("trip_id"),
            "route_id": route_id,
            "latitude": v.get("latitude"),
            "longitude": v.get("longitude"),
            "bearing": v.get("bearing"),
            "status": status,
            "delay_seconds": delay,
            "recorded_at": _iso(v.get("recorded_at")),
            "collected_at": collected_at,
        })
    database.replace_vehicles(vehicle_rows)

    print(f"Snapshot {collected_at}: {added} new observations, "
          f"{len(vehicle_rows)} vehicles")
    return added


def main() -> None:
    sync_static_reference()
    print("Loading static schedule for matching (this can take a few seconds)...")
    schedule = None
    try:
        schedule = match_schedule.ScheduleIndex().load()
    except Exception as exc:
        print(f"Schedule matching unavailable, using feed delays only: {exc}")
    collect_once(schedule=schedule)


if __name__ == "__main__":
    main()
