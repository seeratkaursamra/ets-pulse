"""Live map: current vehicle positions and a stop-level delay heatmap."""
from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

from src import analytics, ui

ui.page_setup("Live Map", icon="🗺️")
st.title("🗺️ Live Map")
st.caption("Current vehicle locations and where delays concentrate.")

if not ui.data_available():
    ui.empty_state()
    st.stop()

veh = ui.live_vehicles()

tab_live, tab_heat = st.tabs(["Live vehicles", "Delay heatmap"])

with tab_live:
    if veh.empty:
        st.info("Live feed unreachable right now. Try again in a moment.")
    else:
        veh = veh.dropna(subset=["latitude", "longitude"]).copy()

        # real, right-now numbers straight from the feed
        known = veh[veh["delay_seconds"].notna()]
        m1, m2, m3 = st.columns(3)
        m1.metric("Buses tracked", f"{len(veh):,}")
        if not known.empty:
            m2.metric("Avg delay now", f"{known['delay_seconds'].mean() / 60:.1f} min")
            late = (known["delay_seconds"] > 120).mean() * 100
            m3.metric("Running late", f"{late:.0f}%")
        st.caption("Pulled live from the Edmonton Transit realtime feed.")
        route_opts = sorted(veh["route_short_name"].dropna().unique(),
                            key=lambda x: (len(str(x)), str(x)))
        chosen = st.multiselect("Filter by route", route_opts, default=[])
        shown = veh[veh["route_short_name"].isin(chosen)] if chosen else veh

        shown = shown.copy()
        shown["color"] = shown["status"].apply(
            lambda s: ui.STATUS_RGB.get(s, [156, 163, 175]))
        shown["delay_min"] = (shown["delay_seconds"] / 60).round(1)

        layer = pdk.Layer(
            "ScatterplotLayer", data=shown,
            get_position="[longitude, latitude]", get_fill_color="color",
            get_radius=150, pickable=True, opacity=0.8)
        view = pdk.ViewState(latitude=53.5461, longitude=-113.4938,
                             zoom=10.3, pitch=0)
        tooltip = {"text": "Route {route_short_name}\nVehicle {vehicle_id}\n"
                           "{status} ({delay_min} min)"}
        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view,
                                 tooltip=tooltip, map_style="road"),
                        use_container_width=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown("🟢 **On time**")
        c2.markdown("🔵 **Early**")
        c3.markdown("🟠 **Slight delay**")
        c4.markdown("🔴 **Major delay**")
        st.caption(f"{len(shown):,} buses shown, fetched live from the ETS feed")

with tab_heat:
    st.subheader("Average delay by stop")
    df = ui.load_all_observations()
    df = ui.sidebar_filters(df)
    stops = analytics.worst_stops(df, top_n=1000)
    stop_geo = df.dropna(subset=["stop_lat", "stop_lon"])[
        ["stop_id", "stop_lat", "stop_lon"]].drop_duplicates("stop_id")
    if stops.empty or stop_geo.empty:
        st.info("Not enough located observations for a heatmap.")
    else:
        merged = stops.merge(stop_geo, on="stop_id", how="inner")
        if merged.empty:
            st.info("No geocoded stops match the current filter.")
        else:
            layer = pdk.Layer(
                "HeatmapLayer", data=merged,
                get_position="[stop_lon, stop_lat]",
                get_weight="avg_delay_min", radiusPixels=55, opacity=0.7)
            view = pdk.ViewState(latitude=53.5461, longitude=-113.4938,
                                 zoom=10.2)
            st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view,
                                     map_style="road"),
                            use_container_width=True)
            st.caption("Warmer areas have higher average delays.")
            st.dataframe(
                merged[["stop_name", "avg_delay_min", "observations"]]
                .rename(columns={"stop_name": "Stop",
                                 "avg_delay_min": "Avg delay (min)",
                                 "observations": "Observations"}),
                use_container_width=True, hide_index=True)
