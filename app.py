"""ETS Pulse overview dashboard. This is the Streamlit entry point.

    streamlit run app.py
"""
from __future__ import annotations

import plotly.express as px
import pydeck as pdk
import streamlit as st

from src import analytics, ui

ui.page_setup("Overview")

st.title("🚍 ETS Pulse")
st.caption("Edmonton Transit Delay Analytics - an independent portfolio project")

ui.ensure_data()

if not ui.data_available():
    ui.empty_state()
    st.stop()

df_all = ui.load_all_observations()
df = ui.sidebar_filters(df_all)

# summary cards
m = analytics.headline_metrics(df)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Average delay", ui.fmt_minutes(m["avg_delay_min"]),
          help="Mean delay across the filtered, matched observations.")
c2.metric("Late observations",
          f"{m['late_pct']:.0f}%" if m["late_pct"] is not None else "n/a",
          help="Share of matched observations more than 2 minutes late.")
c3.metric("Most delayed route",
          f"Route {m['worst_route']}" if m["worst_route"] else "n/a",
          help="Highest average delay in the current filter.")
c4.metric("Active vehicles", f"{len(ui.live_vehicles()):,}",
          help="Buses currently reporting on the live ETS feed.")

st.caption(f"Based on {m['known_observations']:,} matched observations "
           f"({m['unknown_observations']:,} unknown / unmatched).")
ui.confidence_note(m["known_observations"])
st.divider()

# delay trend by hour, next to the live map
left, right = st.columns([1, 1])

with left:
    st.subheader("Delay through the day")
    by_hour = analytics.delay_by_hour(df)
    if by_hour.empty:
        st.info("No matched observations for this filter.")
    else:
        fig = px.line(by_hour, x="local_hour", y="avg_delay_min", markers=True,
                      labels={"local_hour": "Hour of day",
                              "avg_delay_min": "Avg delay (min)"})
        fig.update_traces(line_color="#0b6e4f")
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Live vehicles")
    veh = ui.live_vehicles()
    if veh.empty:
        st.info("No vehicle snapshot yet. Run a collection to populate the map.")
    else:
        veh = veh.dropna(subset=["latitude", "longitude"]).copy()
        veh["color"] = veh["status"].apply(
            lambda s: ui.STATUS_RGB.get(s, [156, 163, 175]))
        layer = pdk.Layer(
            "ScatterplotLayer", data=veh,
            get_position="[longitude, latitude]", get_fill_color="color",
            get_radius=140, pickable=True, opacity=0.75)
        view = pdk.ViewState(latitude=53.5461, longitude=-113.4938,
                             zoom=10.2, pitch=0)
        tooltip = {"text": "Route {route_short_name}\n{status}"}
        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view,
                                 tooltip=tooltip,
                                 map_style="road"), use_container_width=True)
        st.caption("🟢 On time | 🔵 Early | 🟠 Slight delay | 🔴 Major delay")

st.divider()

# worst routes and day-of-week pattern
left2, right2 = st.columns([1, 1])

with left2:
    st.subheader("Most delayed routes")
    routes = analytics.delay_by_route(df, top_n=10, min_observations=20)
    if routes.empty:
        st.info("No route data for this filter.")
    else:
        fig = px.bar(routes.sort_values("avg_delay_min"),
                     x="avg_delay_min", y="route_short_name", orientation="h",
                     labels={"avg_delay_min": "Avg delay (min)",
                             "route_short_name": "Route"},
                     color="avg_delay_min", color_continuous_scale="OrRd")
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

with right2:
    st.subheader("Delay by day of week")
    by_dow = analytics.delay_by_day_of_week(df)
    if by_dow.empty:
        st.info("No data for this filter.")
    else:
        fig = px.bar(by_dow, x="day", y="avg_delay_min",
                     labels={"day": "Day", "avg_delay_min": "Avg delay (min)"},
                     color="avg_delay_min", color_continuous_scale="OrRd")
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

st.divider()

st.subheader("Recent delayed trips")
recent = analytics.recent_delayed(df, limit=25)
if recent.empty:
    st.info("No late observations in the current filter.")
else:
    recent = recent.rename(columns={
        "collected_at": "Collected (UTC)", "route_short_name": "Route",
        "stop_name": "Stop", "delay_min": "Delay (min)", "status": "Status"})
    st.dataframe(recent, use_container_width=True, hide_index=True)

cov = analytics.date_coverage()
st.caption(f"Data coverage: {cov['first_day']} to {cov['last_day']} | "
           f"{cov['n']:,} total observations | last collected {cov['last']}")
