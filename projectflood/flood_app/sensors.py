"""Sensors and sensor readings: simulation (on a refresh timer), saving
readings, and assembling the combined readings every dashboard uses."""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from flood_app.alerts import check_and_send_auto_alerts
from flood_app.config import (
    SENSOR_READING_RETENTION_DAYS,
    SIMULATION_REFRESH_SECONDS,
)
from flood_app.database import get_connection
from flood_app.datasets import get_dataset_readings
from flood_app.geography import LOCATION_COORDINATES
from flood_app.prediction import hybrid_flood_prediction_batch


def get_location_coordinates(location):

    """
    Look up (latitude, longitude) for a location name.

    Checks LOCATION_COORDINATES first (case-insensitive), then
    falls back to the sensors table for locations registered
    manually with custom coordinates. Returns None if no
    coordinates can be found anywhere, so callers can show a
    clear message instead of crashing.
    """

    if location is None:

        return None

    location_key = str(location).strip()

    for name, coords in LOCATION_COORDINATES.items():

        if name.strip().lower() == location_key.lower():

            return coords

    try:

        sensors = get_sensors()

        match = sensors[
            sensors["location"].astype(str).str.strip().str.lower()
            == location_key.lower()
        ]

        if not match.empty:

            row = match.iloc[0]

            if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):

                return (
                    float(row["latitude"]),
                    float(row["longitude"])
                )

    except Exception:

        pass

    return None


# ============================================================
# SENSOR FUNCTIONS
# ============================================================



def get_sensors():

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT *
        FROM sensors
        """,
        conn
    )

    conn.close()

    return df


def save_sensor_reading(data):

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO sensor_readings(
            sensor_id,
            timestamp,
            water_level,
            rainfall,
            river_flow,
            temperature,
            humidity,
            soil_moisture,
            wind_speed,
            flood_probability,
            risk_level
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["sensor_id"],
            data["timestamp"],
            data["water_level"],
            data["rainfall"],
            data["river_flow"],
            data["temperature"],
            data["humidity"],
            data["soil_moisture"],
            data["wind_speed"],
            data["flood_probability"],
            data["risk_level"]
        )
    )

    conn.commit()
    conn.close()


# ============================================================
# GENERATE ALL SENSOR DATA
# ============================================================

def simulate_sensor_readings(sensors):
    """
    Simulates one fresh reading per row of `sensors` (needs
    `sensor_id` and `location` columns) using the same value
    ranges as generate_sensor_data(), but generates every value
    and runs the hybrid prediction for ALL sensors in one
    vectorised batch. Returns a DataFrame with the same columns
    generate_sensor_data() returns per reading.
    """

    n = len(sensors)

    if n == 0:
        return pd.DataFrame()

    raw = pd.DataFrame({
        "water_level": np.random.uniform(1.0, 4.8, n),
        "rainfall": np.random.uniform(5, 150, n),
        "river_flow": np.random.uniform(1, 15, n),
        "temperature": np.random.uniform(24, 34, n),
        "humidity": np.random.uniform(55, 98, n),
        "soil_moisture": np.random.uniform(30, 98, n),
        "wind_speed": np.random.uniform(1, 20, n),
    })

    prediction = hybrid_flood_prediction_batch(raw)

    result = pd.DataFrame({
        "sensor_id": sensors["sensor_id"].to_numpy(),
        "location": sensors["location"].to_numpy(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    result = pd.concat(
        [result, raw.round(2), prediction],
        axis=1
    )

    result["data_source"] = "Simulation"

    return result


def save_sensor_readings(readings):
    """Writes many sensor readings in ONE connection / ONE
    transaction (instead of one connect + commit per sensor)."""

    if readings is None or readings.empty:
        return

    columns = [
        "sensor_id", "timestamp", "water_level", "rainfall",
        "river_flow", "temperature", "humidity", "soil_moisture",
        "wind_speed", "flood_probability", "risk_level"
    ]

    rows = [
        tuple(
            value.item() if hasattr(value, "item") else value
            for value in record
        )
        for record in readings[columns].itertuples(
            index=False, name=None
        )
    ]

    conn = get_connection()

    try:
        with conn:
            conn.executemany(
                "INSERT INTO sensor_readings("
                + ", ".join(columns)
                + ") VALUES ("
                + ", ".join("?" * len(columns))
                + ")",
                rows
            )
    finally:
        conn.close()


def _sensor_signature():
    """(count, highest id) of registered sensors — part of the
    snapshot cache key, so registering a new sensor shows up
    immediately instead of after the next timer tick."""

    conn = get_connection()

    try:
        return tuple(
            conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM sensors"
            ).fetchone()
        )
    finally:
        conn.close()


def _prune_old_sensor_readings():

    if not SENSOR_READING_RETENTION_DAYS:
        return  # 0 / None = keep everything forever

    cutoff = (
        datetime.now()
        - timedelta(days=SENSOR_READING_RETENTION_DAYS)
    ).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()

    try:
        with conn:
            conn.execute(
                "DELETE FROM sensor_readings WHERE timestamp < ?",
                (cutoff,)
            )
    finally:
        conn.close()


def _build_simulation_snapshot():
    """Simulates one reading per registered sensor, saves them to
    the history table, and returns (readings_df, generated_at)."""

    sensors = get_sensors()

    sensors = sensors.assign(
        location=sensors["location"].astype(str).str.strip()
    )

    readings = simulate_sensor_readings(sensors)

    save_sensor_readings(readings)

    _prune_old_sensor_readings()

    return readings, datetime.now()


@st.cache_data(
    ttl=max(SIMULATION_REFRESH_SECONDS, 1),
    show_spinner=False
)
def _cached_simulation_snapshot(sensor_signature):

    return _build_simulation_snapshot()


def refresh_simulated_data():
    """Throw away the current snapshot so the next render
    simulates fresh readings."""

    _cached_simulation_snapshot.clear()


def get_simulated_readings():

    if SIMULATION_REFRESH_SECONDS > 0:

        readings, generated_at = _cached_simulation_snapshot(
            _sensor_signature()
        )

    else:

        readings, generated_at = _build_simulation_snapshot()

    st.session_state["data_updated_at"] = generated_at

    return readings


def generate_all_sensor_data():

    dataset_readings = (
        get_dataset_readings()
    )

    dataset_locations = set()

    if not dataset_readings.empty:

        dataset_locations = set(

            dataset_readings[
                "location"
            ]
            .astype(str)
            .str.strip()
            .str.lower()

        )

    simulated_df = get_simulated_readings()

    # IMPORTANT:
    # If an external dataset contains a location, simulation is
    # disabled for that location (its uploaded data is used).
    if not simulated_df.empty and dataset_locations:

        simulated_df = simulated_df[
            ~simulated_df["location"]
            .astype(str).str.strip().str.lower()
            .isin(dataset_locations)
        ]

    if not dataset_readings.empty:

        combined = pd.concat(
            [
                simulated_df,
                dataset_readings
            ],
            ignore_index=True
        )

    else:

        combined = simulated_df

    check_and_send_auto_alerts(combined)

    return combined
