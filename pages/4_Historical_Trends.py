"""Historical trends: weekday vs weekend, hour-by-day heatmap, variability."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from src import analytics, config, ui

ui.page_setup("Historical Trends", icon="📈")
st.title("📈 Historical Trends")

if not ui.data_available():
    ui.empty_state()
    st.stop()

df_all = ui.load_all_observations()
df = ui.sidebar_filters(df_all)
known = df[df["delay_seconds"].notna()].copy()

if known.empty:
    st.info("No matched observations for this filter.")
    st.stop()

known["delay_min"] = known["delay_seconds"] / 60

# weekday vs weekend
st.subheader("Weekday vs weekend")
known["is_weekend"] = known["day_of_week"] >= 5
cmp = (known.groupby("is_weekend")["delay_min"].mean().round(1)
       .rename(index={False: "Weekday", True: "Weekend"}).reset_index())
cmp.columns = ["Period", "Avg delay (min)"]
c1, c2 = st.columns([1, 2])
with c1:
    st.dataframe(cmp, use_container_width=True, hide_index=True)
with c2:
    fig = px.bar(cmp, x="Period", y="Avg delay (min)", color="Period",
                 color_discrete_sequence=["#0b6e4f", "#3b82f6"])
    fig.update_layout(height=280, showlegend=False,
                      margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# hour-by-day-of-week heatmap
st.subheader("Delay heatmap: hour by day of week")
pivot = (known.groupby(["day_of_week", "local_hour"])["delay_min"]
         .mean().reset_index())
if not pivot.empty:
    grid = pivot.pivot(index="day_of_week", columns="local_hour",
                       values="delay_min").reindex(range(7))
    grid.index = [ui.DAY_LABELS[i] for i in grid.index]
    fig = px.imshow(grid, aspect="auto", color_continuous_scale="OrRd",
                    labels=dict(x="Hour", y="Day", color="Avg delay (min)"))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# routes with the most variable service
col1, col2 = st.columns(2)
with col1:
    st.subheader("Most variable routes")
    var = (known.groupby("route_label")["delay_min"]
           .agg(["mean", "std", "size"]).reset_index())
    var = var[var["size"] >= config.MIN_CONFIDENT_OBSERVATIONS]
    var = var.sort_values("std", ascending=False).head(10)
    if var.empty:
        st.info("Not enough data.")
    else:
        var["std"] = var["std"].round(1)
        var["mean"] = var["mean"].round(1)
        st.dataframe(var.rename(columns={
            "route_label": "Route", "mean": "Avg (min)",
            "std": "Std dev (min)", "size": "Observations"}),
            use_container_width=True, hide_index=True)
        st.caption("Higher standard deviation = less predictable service.")

with col2:
    st.subheader("Stops with repeated delays")
    stops = analytics.worst_stops(df, top_n=10)
    if stops.empty:
        st.info("Not enough data.")
    else:
        st.dataframe(stops[["stop_name", "avg_delay_min", "observations"]]
                     .rename(columns={"stop_name": "Stop",
                                      "avg_delay_min": "Avg delay (min)",
                                      "observations": "Observations"}),
                     use_container_width=True, hide_index=True)

st.divider()

# how often major delays happen over time
st.subheader("Major-delay frequency by service date")
known["is_major"] = known["delay_seconds"] > config.SLIGHT_DELAY_MAX
freq = (known.groupby("service_date")["is_major"].mean().mul(100).round(1)
        .reset_index(name="major_pct"))
if not freq.empty:
    fig = px.area(freq, x="service_date", y="major_pct",
                  labels={"service_date": "Service date",
                          "major_pct": "Major delay %"})
    fig.update_traces(line_color="#dc2626", fillcolor="rgba(220,38,38,0.2)")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
