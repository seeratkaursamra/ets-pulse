"""Aggregations and the reliability score over delay_observations.

Everything returns a DataFrame (or dict) the dashboard can drop straight in.
Unknown rows are counted on their own and never mixed into "on time", and every
average comes back with its observation count.
"""
from __future__ import annotations

import pandas as pd

from . import config, database

# weights for the reliability score, 0..1 (Unknown is left out)
_STATUS_WEIGHTS = {
    config.STATUS_ON_TIME: 1.0,
    config.STATUS_EARLY: 0.8,
    config.STATUS_SLIGHT: 0.4,
    config.STATUS_MAJOR: 0.0,
}


def _where(filters: dict | None) -> tuple[str, dict]:
    """Build the shared WHERE clause from the optional filter dict."""
    filters = filters or {}
    clauses: list[str] = []
    params: dict = {}
    if filters.get("route_id"):
        clauses.append("route_id = :route_id")
        params["route_id"] = filters["route_id"]
    if filters.get("stop_id"):
        clauses.append("stop_id = :stop_id")
        params["stop_id"] = filters["stop_id"]
    if filters.get("start_date"):
        clauses.append("service_date >= :start_date")
        params["start_date"] = filters["start_date"]
    if filters.get("end_date"):
        clauses.append("service_date <= :end_date")
        params["end_date"] = filters["end_date"]
    if filters.get("day_of_week") is not None:
        clauses.append("day_of_week = :day_of_week")
        params["day_of_week"] = filters["day_of_week"]
    if filters.get("hour_start") is not None:
        clauses.append("local_hour >= :hour_start")
        params["hour_start"] = filters["hour_start"]
    if filters.get("hour_end") is not None:
        clauses.append("local_hour <= :hour_end")
        params["hour_end"] = filters["hour_end"]
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def load_observations(filters: dict | None = None) -> pd.DataFrame:
    """Observations joined to route and stop names, with filters applied."""
    where, params = _where(filters)
    query = f"""
        SELECT o.*, r.route_short_name, r.route_long_name,
               s.stop_name, s.latitude AS stop_lat, s.longitude AS stop_lon
        FROM delay_observations o
        LEFT JOIN routes r ON o.route_id = r.route_id
        LEFT JOIN stops s ON o.stop_id = s.stop_id
        {where}
    """
    df = database.read_sql(query, params=params)
    return df


def headline_metrics(df: pd.DataFrame) -> dict:
    """Numbers for the four summary cards."""
    known = df[df["delay_seconds"].notna()] if not df.empty else df
    total_known = len(known)
    avg_delay_min = round(known["delay_seconds"].mean() / 60, 1) if total_known else None
    late = known[known["delay_seconds"] > config.LATE_THRESHOLD_SECONDS]
    late_pct = round(100 * len(late) / total_known, 1) if total_known else None

    worst_route = None
    if total_known:
        grp = known.groupby("route_short_name")["delay_seconds"]
        by_route = grp.mean().dropna()
        counts = grp.size()
        # only rank routes that have enough data; fall back if none do
        confident = by_route[counts >= config.MIN_CONFIDENT_OBSERVATIONS]
        pick_from = confident if not confident.empty else by_route
        if not pick_from.empty:
            worst_route = pick_from.idxmax()

    return {
        "avg_delay_min": avg_delay_min,
        "late_pct": late_pct,
        "worst_route": worst_route,
        "known_observations": total_known,
        "total_observations": len(df),
        "unknown_observations": len(df) - total_known if not df.empty else 0,
    }


def delay_by_route(df: pd.DataFrame, top_n: int | None = None,
                   min_observations: int = 0) -> pd.DataFrame:
    """Per-route stats: avg/median delay, late %, major %, count, reliability.

    min_observations skips routes with too little data so a handful of records
    can't top the ranking.
    """
    if df.empty:
        return pd.DataFrame()
    known = df[df["delay_seconds"].notna()].copy()
    if known.empty:
        return pd.DataFrame()

    def agg(group: pd.DataFrame) -> pd.Series:
        n = len(group)
        late = (group["delay_seconds"] > config.LATE_THRESHOLD_SECONDS).sum()
        major = (group["delay_seconds"] > config.SLIGHT_DELAY_MAX).sum()
        return pd.Series({
            "avg_delay_min": round(group["delay_seconds"].mean() / 60, 1),
            "median_delay_min": round(group["delay_seconds"].median() / 60, 1),
            "late_pct": round(100 * late / n, 1),
            "major_pct": round(100 * major / n, 1),
            "observations": n,
            "reliability": reliability_score(group),
        })

    out = (
        known.groupby(["route_id", "route_short_name"], dropna=False)
        .apply(agg, include_groups=False)
        .reset_index()
        .sort_values("avg_delay_min", ascending=False)
    )
    if min_observations:
        out = out[out["observations"] >= min_observations]
    if top_n:
        out = out.head(top_n)
    return out


def delay_by_hour(df: pd.DataFrame) -> pd.DataFrame:
    """Average delay and count for each local hour (0-23)."""
    if df.empty:
        return pd.DataFrame()
    known = df[df["delay_seconds"].notna()]
    if known.empty:
        return pd.DataFrame()
    out = (
        known.groupby("local_hour")
        .agg(avg_delay_min=("delay_seconds", lambda s: round(s.mean() / 60, 1)),
             observations=("delay_seconds", "size"))
        .reset_index()
        .sort_values("local_hour")
    )
    return out


def delay_by_day_of_week(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    known = df[df["delay_seconds"].notna()]
    if known.empty:
        return pd.DataFrame()
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    out = (
        known.groupby("day_of_week")
        .agg(avg_delay_min=("delay_seconds", lambda s: round(s.mean() / 60, 1)),
             observations=("delay_seconds", "size"))
        .reset_index()
        .sort_values("day_of_week")
    )
    out["day"] = out["day_of_week"].map(lambda i: labels[int(i)] if pd.notna(i) else "?")
    return out


def worst_stops(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    known = df[df["delay_seconds"].notna()]
    if known.empty:
        return pd.DataFrame()
    out = (
        known.groupby(["stop_id", "stop_name"], dropna=False)
        .agg(avg_delay_min=("delay_seconds", lambda s: round(s.mean() / 60, 1)),
             observations=("delay_seconds", "size"))
        .reset_index()
    )
    out = out[out["observations"] >= 5]
    return out.sort_values("avg_delay_min", ascending=False).head(top_n)


def recent_delayed(df: pd.DataFrame, limit: int = 25) -> pd.DataFrame:
    """Latest observations that came in late."""
    if df.empty:
        return pd.DataFrame()
    late = df[(df["delay_seconds"].notna()) &
              (df["delay_seconds"] > config.LATE_THRESHOLD_SECONDS)].copy()
    if late.empty:
        return pd.DataFrame()
    late["delay_min"] = (late["delay_seconds"] / 60).round(1)
    cols = ["collected_at", "route_short_name", "stop_name", "delay_min", "status"]
    cols = [c for c in cols if c in late.columns]
    return late.sort_values("collected_at", ascending=False).head(limit)[cols]


def status_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    out = df.groupby("status").size().reset_index(name="observations")
    return out


def reliability_score(df: pd.DataFrame) -> float:
    """0-100 score from the status weights (Unknown ignored).

    100 means everything was on time, 0 means every trip was a major delay.
    """
    if df.empty:
        return 0.0
    known = df[df["status"] != config.STATUS_UNKNOWN]
    known = known[known["delay_seconds"].notna()]
    if known.empty:
        return 0.0
    weights = known["status"].map(_STATUS_WEIGHTS).fillna(0.0)
    return round(100 * weights.mean(), 1)


def date_coverage() -> dict:
    """First and last collection time plus the service-day span."""
    df = database.read_sql(
        "SELECT MIN(collected_at) AS first, MAX(collected_at) AS last, "
        "MIN(service_date) AS first_day, MAX(service_date) AS last_day, "
        "COUNT(*) AS n FROM delay_observations"
    )
    if df.empty or df["n"].iloc[0] == 0:
        return {"first": None, "last": None, "first_day": None,
                "last_day": None, "n": 0}
    row = df.iloc[0]
    return {
        "first": row["first"], "last": row["last"],
        "first_day": row["first_day"], "last_day": row["last_day"],
        "n": int(row["n"]),
    }
