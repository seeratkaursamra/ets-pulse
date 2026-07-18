"""Route analysis: deep dive on a single route's reliability."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from src import analytics, config, ui

ui.page_setup("Route Analysis", icon="📊")
st.title("📊 Route Analysis")

if not ui.data_available():
    ui.empty_state()
    st.stop()

df_all = ui.load_all_observations()

routes = sorted(df_all["route_label"].dropna().unique(),
                key=lambda x: (len(str(x)), str(x)))
route = st.selectbox("Choose a route", routes)
df = df_all[df_all["route_label"] == route]
known = df[df["delay_seconds"].notna()]

n = len(known)
ui.confidence_note(n)

avg = round(known["delay_seconds"].mean() / 60, 1) if n else None
med = round(known["delay_seconds"].median() / 60, 1) if n else None
late_pct = round(100 * (known["delay_seconds"] > config.LATE_THRESHOLD_SECONDS).mean(), 1) if n else None
major_pct = round(100 * (known["delay_seconds"] > config.SLIGHT_DELAY_MAX).mean(), 1) if n else None
score = analytics.reliability_score(df)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Avg delay", ui.fmt_minutes(avg))
c2.metric("Median delay", ui.fmt_minutes(med))
c3.metric("Late %", f"{late_pct:.0f}%" if late_pct is not None else "—")
c4.metric("Major delay %", f"{major_pct:.0f}%" if major_pct is not None else "—")
c5.metric("Reliability", f"{score:.0f}/100", ui.reliability_label(score))

st.caption(f"Based on {n:,} matched observations.")
st.divider()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Delay by hour of day")
    by_hour = analytics.delay_by_hour(df)
    if by_hour.empty:
        st.info("No data.")
    else:
        fig = px.bar(by_hour, x="local_hour", y="avg_delay_min",
                     labels={"local_hour": "Hour", "avg_delay_min": "Avg delay (min)"},
                     color="avg_delay_min", color_continuous_scale="OrRd")
        fig.update_layout(height=320, coloraxis_showscale=False,
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
        best = by_hour.loc[by_hour["avg_delay_min"].idxmin()]
        worst = by_hour.loc[by_hour["avg_delay_min"].idxmax()]
        st.caption(f"Best time: **{int(best['local_hour']):02d}:00** "
                   f"({best['avg_delay_min']} min) · "
                   f"Worst time: **{int(worst['local_hour']):02d}:00** "
                   f"({worst['avg_delay_min']} min)")

with col2:
    st.subheader("Delay history by day")
    hist = (known.assign(service_date=known["service_date"])
            .groupby("service_date")["delay_seconds"]
            .mean().div(60).round(1).reset_index(name="avg_delay_min"))
    if hist.empty:
        st.info("No data.")
    else:
        fig = px.line(hist, x="service_date", y="avg_delay_min", markers=True,
                      labels={"service_date": "Service date",
                              "avg_delay_min": "Avg delay (min)"})
        fig.update_traces(line_color="#0b6e4f")
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("Most problematic stops on this route")
stops = analytics.worst_stops(df, top_n=10)
if stops.empty:
    st.info("Not enough stop-level data.")
else:
    st.dataframe(
        stops[["stop_name", "avg_delay_min", "observations"]].rename(columns={
            "stop_name": "Stop", "avg_delay_min": "Avg delay (min)",
            "observations": "Observations"}),
        use_container_width=True, hide_index=True)

with st.expander("Download this route's observations (CSV)"):
    st.download_button(
        "Download CSV", df.to_csv(index=False).encode("utf-8"),
        file_name=f"ets_route_{route}.csv", mime="text/csv")
