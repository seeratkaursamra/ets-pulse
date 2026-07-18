"""Parse GTFS-Realtime protobuf messages into plain Python dicts.

Uses the official google gtfs-realtime-bindings. Each parser is defensive: real
feeds routinely have missing fields, so we read what exists and leave the rest
as None (never guessing a value that would improve delay stats).
"""
from __future__ import annotations

from typing import List

from google.transit import gtfs_realtime_pb2


def _feed(raw: bytes) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(raw)
    return feed


def parse_trip_updates(raw: bytes) -> List[dict]:
    """Flatten TripUpdate entities into one dict per stop_time_update.

    Each record carries scheduled vs predicted (arrival) epoch seconds when the
    feed provides them, plus the feed-reported delay if present.
    """
    feed = _feed(raw)
    records: List[dict] = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip = tu.trip
        vehicle_id = tu.vehicle.id if tu.HasField("vehicle") else None
        for stu in tu.stop_time_update:
            arrival = stu.arrival if stu.HasField("arrival") else None
            departure = stu.departure if stu.HasField("departure") else None
            event = arrival or departure

            predicted_time = event.time if event and event.time else None
            # GTFS-RT may give an explicit delay even without absolute times.
            feed_delay = None
            if event is not None and event.HasField("delay"):
                feed_delay = event.delay

            records.append({
                "trip_id": trip.trip_id or None,
                "route_id": trip.route_id or None,
                "start_date": trip.start_date or None,
                "vehicle_id": vehicle_id,
                "stop_id": stu.stop_id or None,
                "stop_sequence": stu.stop_sequence if stu.HasField("stop_sequence") else None,
                "predicted_time": predicted_time,
                "feed_delay_seconds": feed_delay,
            })
    return records


def parse_vehicle_positions(raw: bytes) -> List[dict]:
    """One dict per vehicle with position and trip linkage."""
    feed = _feed(raw)
    records: List[dict] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        pos = v.position
        records.append({
            "vehicle_id": v.vehicle.id if v.HasField("vehicle") else None,
            "trip_id": v.trip.trip_id if v.HasField("trip") else None,
            "route_id": v.trip.route_id if v.HasField("trip") else None,
            "latitude": pos.latitude if v.HasField("position") else None,
            "longitude": pos.longitude if v.HasField("position") else None,
            "bearing": pos.bearing if v.HasField("position") and pos.HasField("bearing") else None,
            "recorded_at": v.timestamp if v.timestamp else None,
        })
    return records


def parse_alerts(raw: bytes) -> List[dict]:
    """One dict per (alert, affected route/stop) pair."""
    feed = _feed(raw)
    records: List[dict] = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        a = entity.alert
        header = a.header_text.translation[0].text if a.header_text.translation else None
        desc = a.description_text.translation[0].text if a.description_text.translation else None
        active_start = a.active_period[0].start if a.active_period else None
        active_end = a.active_period[0].end if a.active_period else None
        if not a.informed_entity:
            records.append({
                "alert_id": entity.id, "route_id": None, "stop_id": None,
                "header": header, "description": desc,
                "active_start": active_start, "active_end": active_end,
            })
            continue
        for informed in a.informed_entity:
            records.append({
                "alert_id": entity.id,
                "route_id": informed.route_id or None,
                "stop_id": informed.stop_id or None,
                "header": header,
                "description": desc,
                "active_start": active_start,
                "active_end": active_end,
            })
    return records
