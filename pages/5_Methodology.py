"""Methodology: data sources, delay definition, limitations, disclaimer."""
from __future__ import annotations

import streamlit as st

from src import config, database, ui

ui.page_setup("Methodology", icon="📖")
st.title("📖 Methodology")

st.markdown("""
ETS Pulse turns Edmonton Transit Service (ETS) GTFS data into route- and
stop-level reliability analytics. This page documents exactly how the numbers
are produced so they can be trusted and reproduced.
""")

st.subheader("Data sources")
st.markdown("""
| Feed / file | Purpose |
| --- | --- |
| **GTFS Schedule** | Routes, stops, trips, stop sequences, scheduled times |
| **GTFS-Realtime Trip Updates** | Predicted arrival/departure and delay values |
| **GTFS-Realtime Vehicle Positions** | Live latitude, longitude, bearing, vehicle & trip IDs |
| **GTFS-Realtime Alerts** | Service disruptions and public notices |

Realtime feeds describe what is happening right now. ETS Pulse collects a
snapshot roughly every five minutes and stores each observation to build its
own history.
""")

st.subheader("Delay definition")
st.latex(r"delay\_seconds = predicted\_arrival - scheduled\_arrival")
st.markdown("Positive values are late; negative values are early.")

st.subheader("Status thresholds")
st.markdown(f"""
| Status | Rule |
| --- | --- |
| Early | delay &lt; {config.EARLY_MAX} s |
| On time | {config.EARLY_MAX} s to +{config.ON_TIME_MAX} s |
| Slight delay | +{config.ON_TIME_MAX + 1} s to +{config.SLIGHT_DELAY_MAX} s |
| Major delay | &gt; +{config.SLIGHT_DELAY_MAX} s |
| Unknown | Realtime record missing or unmatched |

A missing realtime update is never treated as on time. It is marked Unknown so
route performance is not falsely improved.
""")

st.subheader("Reliability score")
st.markdown("""
Each matched observation is weighted by status (On time = 1.0, Early = 0.8,
Slight delay = 0.4, Major delay = 0.0; Unknown excluded). The route score is
100 times the mean weight, giving a 0-100 reliability index.
""")

st.subheader("Data-quality rules")
st.markdown("""
- Timestamps stored in a consistent timezone (UTC) and format (ISO 8601).
- GTFS times past midnight (hours >= 24) are handled on the correct service day.
- The same vehicle/trip/stop is not counted twice within one snapshot.
- Observation counts are shown beside every average.
- Small samples are flagged with a confidence warning.
- Raw observations are retained so calculations can be reproduced.
""")

st.subheader("Current data coverage")
counts = database.table_counts()
from src import analytics  # local import to avoid overhead when not needed
cov = analytics.date_coverage()
c1, c2, c3 = st.columns(3)
c1.metric("Observations", f"{counts['delay_observations']:,}")
c2.metric("Routes", f"{counts['routes']:,}")
c3.metric("Stops", f"{counts['stops']:,}")
st.caption(f"Coverage: {cov['first_day']} to {cov['last_day']} | "
           f"last collected {cov['last']}")

st.subheader("Known limitations")
st.markdown("""
- The project only covers data collected after its own start date.
- Realtime records may be absent, delayed, or impossible to match.
- A missing realtime update does not prove a vehicle was on time.
- Vehicle locations and estimates change between collection intervals.
- Results with low observation counts should not be over-interpreted.
- Some demonstration data may be simulated to illustrate the analytics; live
  collection replaces it over time.
""")

st.info(config.DISCLAIMER, icon="ℹ️")
