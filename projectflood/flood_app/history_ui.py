"""Historical data view: past sensor readings and flood predictions
for a location, as an interactive chart plus a downloadable table.

In simulation mode every simulated reading is saved to the
`sensor_readings` table (with its flood probability and risk level)
and kept for SENSOR_READING_RETENTION_DAYS. In live mode the history
comes from the `live_readings` table (real data only). This module
only READS those tables; it never writes or deletes anything.

render_history_panel(scope_locations, key_prefix) is shared by every
dashboard: the System Handler passes None (all locations), a
Division Admin / division organization passes its own division's
areas, so a scoped account can never see another division's history.
"""

from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from flood_app.config import (
    RISK_CIRCLE,
    SENSOR_READING_RETENTION_DAYS,
)
from flood_app.data_mode import is_live_mode
from flood_app.database import get_connection
from flood_app.geography import DISTRICT_NAMES


HISTORY_WINDOWS = {
    "Last hour": timedelta(hours=1),
    "Last 6 hours": timedelta(hours=6),
    "Last 24 hours": timedelta(hours=24),
    "Last 7 days": timedelta(days=7),
    "Last 30 days": timedelta(days=30),
}

HISTORY_VARIABLES = {
    "Flood probability (%)": "flood_probability",
    "Water level (m)": "water_level",
    "Rainfall (mm)": "rainfall",
    "River flow (m³/s)": "river_flow",
    "Temperature (°C)": "temperature",
    "Humidity (%)": "humidity",
    "Soil moisture (%)": "soil_moisture",
    "Wind speed (km/h)": "wind_speed",
}

MAX_CHART_POINTS = 600


def get_reading_history(location, since):
    """Stored readings for every sensor at `location` taken at or
    after `since` (a datetime), oldest first. Empty DataFrame when
    there are none."""

    conn = get_connection()

    try:
        if is_live_mode():

            # LIVE MODE: history of REAL readings only (uploaded
            # datasets + real sensors); simulated rows are ignored.
            history = pd.read_sql_query(
                """
                SELECT sensor_id, location, timestamp,
                       water_level, rainfall, river_flow,
                       temperature, humidity, soil_moisture,
                       wind_speed, flood_probability, risk_level
                FROM live_readings
                WHERE location = ? AND timestamp >= ?
                ORDER BY timestamp
                """,
                conn,
                params=(
                    location,
                    since.strftime("%Y-%m-%d %H:%M:%S")
                )
            )

        else:

            history = pd.read_sql_query(
                """
                SELECT s.sensor_id, s.location, r.timestamp,
                       r.water_level, r.rainfall, r.river_flow,
                       r.temperature, r.humidity, r.soil_moisture,
                       r.wind_speed, r.flood_probability, r.risk_level
                FROM sensor_readings r
                JOIN sensors s ON s.sensor_id = r.sensor_id
                WHERE s.location = ? AND r.timestamp >= ?
                ORDER BY r.timestamp
                """,
                conn,
                params=(
                    location,
                    since.strftime("%Y-%m-%d %H:%M:%S")
                )
            )
    finally:
        conn.close()

    if not history.empty:
        history["timestamp"] = pd.to_datetime(
            history["timestamp"], errors="coerce"
        )
        history = history.dropna(subset=["timestamp"])

    return history


def _downsample(history, column):
    """Keeps long histories readable: averages each sensor's series
    into at most ~MAX_CHART_POINTS time buckets. Short histories are
    returned untouched."""

    if len(history) <= MAX_CHART_POINTS:
        return history[["timestamp", "sensor_id", column]]

    span = history["timestamp"].max() - history["timestamp"].min()

    bucket = max(span / MAX_CHART_POINTS, pd.Timedelta(seconds=1))

    return (
        history.set_index("timestamp")
        .groupby("sensor_id")[column]
        .resample(bucket)
        .mean()
        .dropna()
        .reset_index()
    )


def render_history_panel(scope_locations=None, key_prefix="history"):
    """Interactive history chart + table for one location.

    scope_locations: list of allowed locations, or None for every
    monitored district (System Handler)."""

    locations = (
        sorted(scope_locations)
        if scope_locations is not None
        else sorted(DISTRICT_NAMES)
    )

    if not locations:
        st.info("No locations are available for historical data.")
        return

    c1, c2, c3 = st.columns(3)

    location = c1.selectbox(
        "📍 Location", locations, key=f"{key_prefix}_location"
    )

    window_label = c2.selectbox(
        "Time window", list(HISTORY_WINDOWS),
        index=2, key=f"{key_prefix}_window"
    )

    variable_label = c3.selectbox(
        "Show", list(HISTORY_VARIABLES), key=f"{key_prefix}_variable"
    )

    column = HISTORY_VARIABLES[variable_label]

    history = get_reading_history(
        location, datetime.now() - HISTORY_WINDOWS[window_label]
    )

    if history.empty:

        st.info(
            f"No stored readings for {location} in this time "
            f"window yet. Readings are recorded each time the "
            f"monitoring data refreshes."
        )

        return

    m1, m2, m3, m4 = st.columns(4)

    m1.metric("Readings", f"{len(history):,}")

    m2.metric(
        "Peak flood probability",
        f"{history['flood_probability'].max():.1f}%"
    )

    m3.metric(
        "Peak water level",
        f"{history['water_level'].max():.2f} m"
    )

    m4.metric(
        "Severe readings",
        int((history["risk_level"] == "Severe").sum())
    )

    chart_data = _downsample(history, column)

    figure = px.line(
        chart_data,
        x="timestamp",
        y=column,
        color="sensor_id",
        labels={
            "timestamp": "Time",
            column: variable_label,
            "sensor_id": "Sensor",
        },
        title=f"{variable_label} — {location}"
    )

    if column == "flood_probability":
        figure.update_yaxes(range=[0, 100])

    figure.update_layout(
        height=380, margin=dict(l=10, r=10, t=50, b=10)
    )

    st.plotly_chart(figure, width="stretch")

    risk_counts = (
        history["risk_level"]
        .value_counts()
        .reindex(["Low", "Moderate", "High", "Severe"], fill_value=0)
    )

    st.caption(
        "Readings by risk level — "
        + "   ".join(
            f"{RISK_CIRCLE.get(level, '')} {level}: {count}"
            for level, count in risk_counts.items()
        )
    )

    with st.expander("📋 Stored readings table"):

        st.dataframe(
            history.sort_values("timestamp", ascending=False),
            width="stretch",
            hide_index=True
        )

    st.download_button(
        "⬇️ Download history (CSV)",
        data=history.to_csv(index=False).encode("utf-8"),
        file_name=(
            f"history_{location}_{datetime.now():%Y%m%d_%H%M}.csv"
        ),
        mime="text/csv",
        key=f"{key_prefix}_download"
    )

    if SENSOR_READING_RETENTION_DAYS:
        st.caption(
            f"Readings are kept for {SENSOR_READING_RETENTION_DAYS} "
            f"days."
        )
