"""Generate a realistic simulated history so the dashboard is populated day one.

Realtime feeds only describe "now", so a brand-new install has no multi-day
history to analyze. This script seeds the database with plausible delay
observations built on top of the **real** Edmonton GTFS routes and stops, so the
simulated history and the live snapshots collected by scripts/collect_snapshot.py
share the same route IDs, stop IDs, names, and coordinates.

Patterns baked in:
  * Rush-hour peaks (07-09, 15-18) have larger delays.
  * A few routes are chronically worse (routes 8/4/9, matching the blueprint).
  * Weekdays are worse than weekends.
  * A share of observations are Unknown (no realtime match) - never on-time.

If the real static GTFS cannot be downloaded, a small built-in fallback set of
routes/stops is used instead so the script always works offline.

Usage:
    python -m scripts.generate_backfill --days 14
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, database, fetch_static_gtfs  # noqa: E402
from src.calculate_delays import classify  # noqa: E402

LOCAL = ZoneInfo(config.LOCAL_TZ)
random.seed(42)

# Chronic-delay narrative: these route short names are the worst offenders.
CHRONIC = {"8": 1.9, "008": 1.9, "4": 1.7, "004": 1.7, "9": 1.6, "009": 1.6,
           "15": 1.4, "015": 1.4, "120": 1.4, "2": 1.15, "002": 1.15}

# --- Built-in fallback (used only if the real static feed is unavailable) ---
FALLBACK_ROUTES = [
    ("008", "8", "Abbottsfield - Mill Woods", 1.9),
    ("004", "4", "Lewis Farms - Capilano", 1.7),
    ("009", "9", "Southgate - NAIT - Eaux Claires", 1.6),
    ("002", "2", "Clareview - Lewis Farms", 1.15),
    ("001", "1", "Capilano - West Edmonton Mall", 1.0),
    ("005", "5", "Westmount - Coliseum", 1.2),
    ("015", "15", "Mill Woods - Downtown", 1.4),
    ("120", "120", "Clareview - Downtown", 1.4),
    ("747", "747", "Century Park - EIA (Airport)", 0.6),
    ("052", "52", "University - Southgate", 0.7),
]
FALLBACK_STOPS = [
    ("1001", "Downtown - Churchill Square", 53.5445, -113.4894),
    ("1004", "University Transit Centre", 53.5232, -113.5263),
    ("1006", "Southgate Transit Centre", 53.4930, -113.5148),
    ("1007", "Century Park Station", 53.4498, -113.5109),
    ("1011", "Coliseum Station", 53.5700, -113.4650),
    ("1013", "Clareview Station", 53.6050, -113.4090),
    ("1019", "Northgate Transit Centre", 53.6010, -113.4980),
    ("1022", "West Edmonton Mall TC", 53.5225, -113.6240),
    ("1025", "Mill Woods Transit Centre", 53.4640, -113.4470),
    ("1027", "Capilano Transit Centre", 53.5410, -113.4090),
]


def _route_factor(short_name: str) -> float:
    """Chronic delay multiplier for a route (deterministic)."""
    s = str(short_name).strip()
    if s in CHRONIC:
        return CHRONIC[s]
    # Stable pseudo-random factor in ~0.7..1.4 based on the name.
    h = sum(ord(c) for c in s)
    return round(0.7 + (h % 70) / 100, 2)


def _hour_factor(hour: int) -> float:
    if 7 <= hour <= 9:
        return 1.9
    if 15 <= hour <= 18:
        return 2.1
    if 10 <= hour <= 14:
        return 1.2
    if hour >= 22 or hour <= 5:
        return 0.7
    return 1.0


def _dow_factor(dow: int) -> float:
    return 0.7 if dow >= 5 else 1.15


def _sample_delay_seconds(route_factor: float, hour: int, dow: int) -> int | None:
    if random.random() < 0.08:  # ~8% cannot be matched -> Unknown
        return None
    base = 45 * route_factor * _hour_factor(hour) * _dow_factor(dow)
    delay = base + random.gauss(0, 55)
    if random.random() < 0.05:                       # major disruption spike
        delay += random.uniform(240, 700)
    if random.random() < 0.06:                       # occasional early bus
        delay -= random.uniform(70, 180)
    return int(delay)


def _weighted_hour() -> int:
    hours = list(range(5, 24))
    weights = [_hour_factor(h) for h in hours]
    return random.choices(hours, weights=weights, k=1)[0]


def load_reference(max_routes: int, max_stops: int):
    """Return (sim_routes, sim_stops) as lists of tuples, using real GTFS when
    possible. Also upserts the full reference tables into the database.

    sim_routes: [(route_id, short_name, factor), ...]
    sim_stops:  [(stop_id, name, lat, lon), ...]
    """
    routes_df = pd.DataFrame()
    stops_df = pd.DataFrame()
    try:
        fetch_static_gtfs.download_static()
        routes_df = fetch_static_gtfs.load_routes()
        stops_df = fetch_static_gtfs.load_stops()
    except Exception as exc:
        print(f"Static GTFS unavailable, using fallback reference: {exc}")

    if not routes_df.empty and not stops_df.empty:
        database.upsert_routes(routes_df.to_dict("records"))
        # Deduplicate stops that share names/positions; keep those with coords.
        stops_df = stops_df.dropna(subset=["latitude", "longitude"])
        database.upsert_stops(stops_df.to_dict("records"))
        print(f"Loaded real GTFS reference: {len(routes_df)} routes, "
              f"{len(stops_df)} stops")

        # Pick simulation routes: always include the chronic narrative routes,
        # then fill with a spread of other routes.
        routes_df = routes_df.dropna(subset=["route_short_name"])
        chronic_rows = routes_df[routes_df["route_short_name"].isin(CHRONIC.keys())]
        others = routes_df[~routes_df["route_short_name"].isin(CHRONIC.keys())]
        others = others.sample(min(len(others), max_routes), random_state=1)
        chosen = pd.concat([chronic_rows, others]).drop_duplicates("route_id").head(max_routes)
        sim_routes = [(r.route_id, r.route_short_name,
                       _route_factor(r.route_short_name))
                      for r in chosen.itertuples()]

        stops_sample = stops_df.sample(min(len(stops_df), max_stops), random_state=2)
        sim_stops = [(s.stop_id, s.stop_name, float(s.latitude), float(s.longitude))
                     for s in stops_sample.itertuples()]
        return sim_routes, sim_stops

    # Fallback path
    database.upsert_routes([
        {"route_id": rid, "route_short_name": short,
         "route_long_name": long, "route_type": 3}
        for (rid, short, long, _f) in FALLBACK_ROUTES])
    database.upsert_stops([
        {"stop_id": sid, "stop_name": name, "latitude": lat, "longitude": lon}
        for (sid, name, lat, lon) in FALLBACK_STOPS])
    sim_routes = [(rid, short, factor) for (rid, short, _l, factor) in FALLBACK_ROUTES]
    sim_stops = list(FALLBACK_STOPS)
    return sim_routes, sim_stops


def generate_observations(sim_routes, sim_stops, days: int) -> int:
    now_local = datetime.now(LOCAL)
    start_day = (now_local - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0)

    rows = []
    for day_offset in range(days):
        day = start_day + timedelta(days=day_offset)
        dow = day.weekday()
        for (rid, _short, rfactor) in sim_routes:
            daily = int(random.uniform(35, 70) * (0.6 + rfactor / 2))
            k = min(len(sim_stops), random.randint(6, 12))
            route_stops = random.sample(sim_stops, k=k)
            for _ in range(daily):
                hour = _weighted_hour()
                minute = random.randint(0, 59)
                stop = random.choice(route_stops)
                sched_local = day.replace(hour=hour, minute=minute,
                                          second=0, microsecond=0)
                delay = _sample_delay_seconds(rfactor, hour, dow)

                sched_utc = sched_local.astimezone(timezone.utc)
                predicted_utc = (sched_utc + timedelta(seconds=delay)
                                 if delay is not None else None)
                collected = sched_utc + timedelta(minutes=random.randint(2, 8))

                rows.append({
                    "collected_at": collected.isoformat(),
                    "service_date": day.strftime("%Y-%m-%d"),
                    "trip_id": f"SIM-{rid}-{day.strftime('%Y%m%d')}-{hour:02d}{minute:02d}",
                    "route_id": rid,
                    "vehicle_id": f"V{random.randint(1000, 1999)}",
                    "stop_id": stop[0],
                    "stop_sequence": random.randint(1, 40),
                    "scheduled_time": sched_utc.isoformat(),
                    "predicted_time": predicted_utc.isoformat() if predicted_utc else None,
                    "delay_seconds": delay,
                    "status": classify(delay),
                    "local_hour": hour,
                    "day_of_week": dow,
                    "latitude": None,
                    "longitude": None,
                })

    added = 0
    for i in range(0, len(rows), 2000):
        added += database.insert_observations(rows[i:i + 2000])
    return added


def generate_current_vehicles(sim_routes, sim_stops, n: int = 160) -> int:
    now = datetime.now(timezone.utc)
    now_local = now.astimezone(LOCAL)
    rows = []
    for _ in range(n):
        rid, _short, rfactor = random.choice(sim_routes)
        anchor = random.choice(sim_stops)
        lat = anchor[2] + random.uniform(-0.02, 0.02)
        lon = anchor[3] + random.uniform(-0.02, 0.02)
        delay = _sample_delay_seconds(rfactor, now_local.hour, now_local.weekday())
        rows.append({
            "vehicle_id": f"V{random.randint(1000, 1999)}",
            "trip_id": f"SIM-{rid}-live",
            "route_id": rid,
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "bearing": round(random.uniform(0, 359), 1),
            "status": classify(delay),
            "delay_seconds": delay,
            "recorded_at": now.isoformat(),
            "collected_at": now.isoformat(),
        })
    return database.replace_vehicles(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed simulated ETS history")
    parser.add_argument("--days", type=int, default=14,
                        help="Number of days of history to generate")
    parser.add_argument("--routes", type=int, default=25,
                        help="Number of routes to simulate")
    parser.add_argument("--stops", type=int, default=60,
                        help="Number of stops to simulate")
    args = parser.parse_args()

    database.initialize()
    sim_routes, sim_stops = load_reference(args.routes, args.stops)
    n_obs = generate_observations(sim_routes, sim_stops, args.days)
    n_veh = generate_current_vehicles(sim_routes, sim_stops)
    counts = database.table_counts()

    print(f"Seeded {n_obs} observations across {args.days} days "
          f"({len(sim_routes)} routes, {len(sim_stops)} stops).")
    print(f"Seeded {n_veh} current vehicles.")
    print("Table row counts:")
    for table, n in counts.items():
        print(f"  {table:20s} {n}")


if __name__ == "__main__":
    main()
