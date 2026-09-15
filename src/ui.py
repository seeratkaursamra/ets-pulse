"""Shared Streamlit bits: data loading, filters, formatting, colors.

Pages import from here so filtering, caching and the look stay consistent.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import analytics, config, database

# status colors used across the charts and maps
STATUS_COLORS = {
    config.STATUS_ON_TIME: "#0b6e4f",
    config.STATUS_EARLY: "#3b82f6",
    config.STATUS_SLIGHT: "#f59e0b",
    config.STATUS_MAJOR: "#dc2626",
    config.STATUS_UNKNOWN: "#9ca3af",
}

# same colors as RGB for the pydeck layers
STATUS_RGB = {
    config.STATUS_ON_TIME: [11, 110, 79],
    config.STATUS_EARLY: [59, 130, 246],
    config.STATUS_SLIGHT: [245, 158, 11],
    config.STATUS_MAJOR: [220, 38, 38],
    config.STATUS_UNKNOWN: [156, 163, 175],
}

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def page_setup(title: str, icon: str = "🚍") -> None:
    st.set_page_config(page_title=f"ETS Pulse - {title}", page_icon=icon,
                       layout="wide", initial_sidebar_state="expanded")


@st.cache_data(ttl=120, show_spinner=False)
def load_all_observations() -> pd.DataFrame:
    """Load every observation and add a couple of helper columns. Cached."""
    df = analytics.load_observations()
    if df.empty:
        return df
    df["collected_at_dt"] = pd.to_datetime(df["collected_at"], errors="coerce", utc=True)
    df["route_label"] = df["route_short_name"].fillna(df["route_id"])
    return df


@st.cache_data(ttl=60, show_spinner=False)
def load_vehicles() -> pd.DataFrame:
    """Newest vehicle snapshot for the live map."""
    latest = database.read_sql(
        "SELECT MAX(collected_at) AS c FROM vehicles")
    if latest.empty or latest["c"].iloc[0] is None:
        return pd.DataFrame()
    c = latest["c"].iloc[0]
    df = database.read_sql(
        """SELECT v.*, r.route_short_name
           FROM vehicles v LEFT JOIN routes r ON v.route_id = r.route_id
           WHERE v.collected_at = :c""",
        params={"c": c})
    return df


@st.cache_data(ttl=60, show_spinner=False)
def fetch_live_vehicles() -> pd.DataFrame:
    """Pull vehicles straight from the ETS realtime feed right now.

    Uses the delay the feed reports on each trip's next stop, so it stays light
    (no schedule download) and works on hosts that can't run the collector.
    Returns an empty frame if the feed can't be reached.
    """
    from datetime import datetime, timezone
    from src import fetch_realtime as fr, parse_realtime as pr
    from src.calculate_delays import classify

    try:
        updates = pr.parse_trip_updates(fr.fetch_trip_updates())
        vehicles = pr.parse_vehicle_positions(fr.fetch_vehicle_positions())
    except Exception:
        return pd.DataFrame()

    # delay for each trip, taken at its next upcoming stop
    best: dict[str, tuple[int, int]] = {}
    for r in updates:
        tid = r.get("trip_id")
        if not tid or r.get("feed_delay_seconds") is None:
            continue
        seq = r.get("stop_sequence")
        seq = seq if seq is not None else 10**9
        cur = best.get(tid)
        if cur is None or seq < cur[0]:
            best[tid] = (seq, r.get("feed_delay_seconds"))
    trip_delay = {tid: d for tid, (_s, d) in best.items()}

    rows = []
    for v in vehicles:
        if v.get("latitude") is None or v.get("longitude") is None:
            continue
        d = trip_delay.get(v.get("trip_id"))
        rows.append({
            "vehicle_id": v.get("vehicle_id"),
            "trip_id": v.get("trip_id"),
            "route_id": v.get("route_id"),
            "latitude": v.get("latitude"),
            "longitude": v.get("longitude"),
            "bearing": v.get("bearing"),
            "delay_seconds": d,
            "status": classify(d),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    routes = database.read_sql("SELECT route_id, route_short_name FROM routes")
    if not routes.empty:
        df = df.merge(routes, on="route_id", how="left")
    if "route_short_name" not in df.columns:
        df["route_short_name"] = df["route_id"]
    df["route_short_name"] = df["route_short_name"].fillna(df["route_id"])
    df["collected_at"] = datetime.now(timezone.utc).isoformat()
    return df


def live_vehicles() -> pd.DataFrame:
    """Real vehicles from the feed, falling back to the stored snapshot."""
    df = fetch_live_vehicles()
    if df.empty:
        return load_vehicles()
    return df


def data_available() -> bool:
    counts = database.table_counts()
    return counts.get("delay_observations", 0) > 0


def empty_state() -> None:
    st.warning(
        "No data yet. Seed a realistic history with "
        "`python -m scripts.generate_backfill --days 14`, or collect live "
        "snapshots with `python -m scripts.collect_snapshot`.")


def ensure_data(days: int = 14) -> None:
    """Seed a demo history the first time the app runs.

    On a fresh deploy the database is empty (it isn't checked into git), so
    build a backfill once off the real route/stop network. Falls back to the
    built-in set if the static feed can't be reached.
    """
    if data_available():
        return
    database.initialize()
    with st.spinner("First run: building a demo history, give it a few seconds..."):
        try:
            from scripts import generate_backfill as gb
            sim_routes, sim_stops = gb.load_reference(25, 60)
            gb.generate_observations(sim_routes, sim_stops, days)
            gb.generate_current_vehicles(sim_routes, sim_stops)
        except Exception as exc:
            st.error(f"Could not seed demo data: {exc}")
            return
    # drop the cached (empty) loads so the fresh data shows up
    load_all_observations.clear()
    load_vehicles.clear()


def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Draw the global filters and return the filtered frame."""
    st.sidebar.header("Filters")
    if df.empty:
        return df

    routes = sorted(df["route_label"].dropna().unique(),
                    key=lambda x: (len(str(x)), str(x)))
    route_sel = st.sidebar.multiselect("Route", routes, default=[])

    day_sel = st.sidebar.multiselect(
        "Day of week", options=list(range(7)),
        format_func=lambda i: DAY_LABELS[i], default=[])

    hour_range = st.sidebar.slider("Hour of day", 0, 23, (0, 23))

    dates = pd.to_datetime(df["service_date"], errors="coerce").dropna()
    if not dates.empty:
        min_d, max_d = dates.min().date(), dates.max().date()
        date_range = st.sidebar.date_input(
            "Service date range", value=(min_d, max_d),
            min_value=min_d, max_value=max_d)
    else:
        date_range = None

    out = df
    if route_sel:
        out = out[out["route_label"].isin(route_sel)]
    if day_sel:
        out = out[out["day_of_week"].isin(day_sel)]
    out = out[(out["local_hour"] >= hour_range[0]) &
              (out["local_hour"] <= hour_range[1])]
    if date_range and isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        sd = pd.to_datetime(out["service_date"], errors="coerce")
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        out = out[(sd >= start) & (sd <= end)]

    st.sidebar.caption(f"{len(out):,} observations selected")
    st.sidebar.divider()
    st.sidebar.caption(config.DISCLAIMER)
    return out


def confidence_note(n: int) -> None:
    if n < config.MIN_CONFIDENT_OBSERVATIONS:
        st.info(f"Small sample ({n} observations), read with caution.",
                icon="⚠️")


def fmt_minutes(value) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.1f} min"


def reliability_label(score: float) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 55:
        return "Fair"
    if score >= 40:
        return "Poor"
    return "Very poor"
