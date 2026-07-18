"""Stop analysis: routes serving a stop and its delay profile."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from src import analytics, ui

ui.page_setup("Stop Analysis", icon="🚏")
st.title("🚏 Stop Analysis")

if not ui.data_available():
    ui.empty_state()
    st.stop()

df_all = ui.load_all_observations()

stop_names = (df_all.dropna(subset=["stop_name"])
              .drop_duplicates("stop_id")
              .sort_values("stop_name")["stop_name"].tolist())
if not stop_names:
    st.info("No stops with names available.")
    st.stop()

stop = st.selectbox("Choose a stop", stop_names)
df = df_all[df_all["stop_name"] == stop]
known = df[df["delay_seconds"].notna()]
n = len(known)
ui.confidence_note(n)

avg = round(known["delay_seconds"].mean() / 60, 1) if n else None
late_pct = round(100 * (known["delay_seconds"] > 120).mean(), 1) if n else None

c1, c2, c3 = st.columns(3)
c1.metric("Average delay", ui.fmt_minutes(avg))
c2.metric("Late %", f"{late_pct:.0f}%" if late_pct is not None else "—")
c3.metric("Observations", f"{n:,}")

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Routes serving this stop")
    by_route = analytics.delay_by_route(df)
    if by_route.empty:
        st.info("No route data.")
    else:
        show = by_route[["route_short_name", "avg_delay_min",
                         "late_pct", "reliability", "observations"]].rename(columns={
            "route_short_name": "Route", "avg_delay_min": "Avg delay (min)",
            "late_pct": "Late %", "reliability": "Reliability",
            "observations": "Observations"})
        st.dataframe(show.sort_values("Avg delay (min)"),
                     use_container_width=True, hide_index=True)
        best = by_route.sort_values("avg_delay_min").iloc[0]
        st.success(f"Most reliable route here: **Route {best['route_short_name']}** "
                   f"({best['avg_delay_min']} min avg, "
                   f"{best['reliability']:.0f}/100 reliability)")

with col2:
    st.subheader("Delay by hour of day")
    by_hour = analytics.delay_by_hour(df)
    if by_hour.empty:
        st.info("No data.")
    else:
        fig = px.line(by_hour, x="local_hour", y="avg_delay_min", markers=True,
                      labels={"local_hour": "Hour", "avg_delay_min": "Avg delay (min)"})
        fig.update_traces(line_color="#0b6e4f")
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
