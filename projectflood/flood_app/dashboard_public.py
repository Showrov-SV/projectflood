"""Public (not logged in) flood dashboard."""

import streamlit as st

from flood_app.geography import BD_DIVISIONS, DIVISION_AREAS
from flood_app.maps import create_flood_map
from flood_app.prediction_ui import render_flood_probability_gauge
from flood_app.sensors import generate_all_sensor_data


    # ========================================================
    # SENSOR REGISTRATION + EXTERNAL DATASET INPUT
    # ========================================================
    # REMOVED for Police / Fire Service / Hospital / Municipality
    # (every variant this dashboard serves — legacy, division-
    # scoped, district-scoped). Only Administrator, District
    # Admin, Division Admin, and System Handler can register
    # sensors or upload datasets now; those roles each render
    # their own sensor_and_dataset_management_section() call in
    # their own dashboard functions, unaffected by this removal.
    # ========================================================


# ============================================================
# PUBLIC DASHBOARD
# ============================================================

def public_dashboard():

    st.title(
        "🌊 Flood Forecast & Public Monitoring Portal"
    )

    st.write(
        "Select a Division, then a District, to view current "
        "flood conditions and prediction for that district."
    )

    readings = (
        generate_all_sensor_data()
    )

    if readings.empty:

        st.warning(
            "No sensor readings are currently available."
        )

        return

    # --------------------------------------------------------
    # DIVISION -> DISTRICT DRILL-DOWN
    # --------------------------------------------------------
    # Two-step selector: pick one of the 8 divisions first, then
    # one of ONLY that division's real districts — matches how
    # a Division Admin/District Admin picks a location elsewhere
    # in the app, so the public portal behaves the same way.
    # --------------------------------------------------------

    division_col, district_col = st.columns(2)

    with division_col:

        selected_division = st.selectbox(
            "🗺️ Select Division",
            BD_DIVISIONS,
            key="public_division"
        )

    district_options = DIVISION_AREAS.get(selected_division, [])

    with district_col:

        selected_location = st.selectbox(
            "📍 Select District",
            district_options,
            key=f"public_district_{selected_division}"
        )

    division_readings = readings[
        readings["location"].isin(district_options)
    ]

    if division_readings.empty or selected_location not in (
        division_readings["location"].tolist()
    ):

        st.warning(
            f"No sensor readings are currently available for "
            f"{selected_location}."
        )

        return

    selected = division_readings[
        division_readings[
            "location"
        ] == selected_location
    ].iloc[0]

    st.divider()

    # ========================================================
    # CURRENT CONDITIONS
    # ========================================================

    st.subheader(
        f"📍 {selected_location} ({selected_division} Division)"
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "💧 Water Level",
        f"{selected['water_level']} m"
    )

    col2.metric(
        "🌧️ Rainfall",
        f"{selected['rainfall']} mm"
    )

    col3.metric(
        "🌊 River Flow",
        f"{selected['river_flow']} m³/s"
    )

    col4.metric(
        "🤖 Flood Probability",
        f"{selected['flood_probability']}%"
    )

    risk = selected[
        "risk_level"
    ]

    if risk == "Low":

        st.success(
            f"🟢 Flood Risk: {risk}"
        )

    elif risk == "Moderate":

        st.warning(
            f"🟡 Flood Risk: {risk}"
        )

    elif risk == "High":

        st.warning(
            f"🟠 Flood Risk: {risk}"
        )

    else:

        st.error(
            f"🔴 Flood Risk: {risk}"
        )

    st.caption(
        f"Data Source: {selected['data_source']}"
    )

    st.divider()

    # ========================================================
    # PREDICTION
    # ========================================================

    st.subheader(
        "🤖 Flood Prediction"
    )

    # Uses the REAL hybrid physics/ML model's predicted_water_level
    # (already computed in `selected` by hybrid_flood_prediction),
    # not an ad-hoc recomputation — so this always agrees with the
    # flood probability and risk level shown elsewhere on this
    # same reading.

    col1, col2 = st.columns(2)

    with col1:

        st.metric(
            "Current Water Level",
            f"{selected['water_level']} m"
        )

        st.metric(
            "Predicted Water Level",
            f"{selected['predicted_water_level']:.2f} m"
        )

    with col2:

        st.metric(
            "🤖 Flood Probability",
            f"{selected['flood_probability']}%"
        )

        st.metric(
            "⚠️ Risk Level",
            selected.get("risk_level", "—")
        )

    render_flood_probability_gauge(
        selected["flood_probability"],
        risk_level=selected.get("risk_level"),
        label="Flood Probability"
    )

    st.divider()

    # ========================================================
    # FLOOD MAP
    # ========================================================

    st.subheader(
        "🌍 Live Flood Location Map"
    )

    st.caption(
        f"Showing every district in **{selected_division} "
        f"Division**, centered on **{selected_location}** — "
        f"change the selectors above to jump to a different "
        f"district or division."
    )

    st.plotly_chart(

        create_flood_map(
            division_readings,
            focus_location=selected_location
        ),

        width="stretch"

    )

    st.caption(
        "🟢 Low   🟡 Moderate   🟠 High   🔴 Severe — each "
        "marker is labeled with its location and current risk."
    )

    st.caption(
        f"Last updated: {selected['timestamp']}"
    )
