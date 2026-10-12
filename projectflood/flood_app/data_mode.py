"""Simulation / live data mode, and storage of REAL readings.

The system starts in SIMULATION mode (random demo readings for every
registered sensor, exactly as before). As soon as real data is
connected - an uploaded CSV/XLSX dataset, or a reading pushed by a
real sensor through ingest_sensor_reading() - it switches to LIVE
mode and stays there (the mode is stored in the `app_settings` table,
so it survives restarts). In live mode no simulated reading is
generated, predicted or saved any more.

All REAL readings (uploaded datasets and sensors) are stored in the
`live_readings` table. Simulated readings never go there, which keeps
that table clean for future model training.

This module has no Streamlit dependency.
"""

import json
from datetime import datetime

import numpy as np
import pandas as pd

from flood_app.activity_log import ACTION_DATA_MODE_CHANGED, log_activity
from flood_app.config import (
    DATA_MODE_LIVE,
    DATA_MODE_SIMULATION,
    DATASET_VALUE_LIMITS,
    LIVE_MODE_AUTO_SWITCH,
    LIVE_SENSOR_MAX_AGE_MINUTES,
    REQUIRED_DATASET_COLUMNS,
)
from flood_app.database import get_connection


SOURCE_DATASET = "External Dataset"

SOURCE_SENSOR = "Real Sensor"

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"

_MODE_KEY = "data_mode"

_MODE_INFO_KEY = "data_mode_info"

_DATASET_META_PREFIX = "dataset_meta::"

LIVE_COLUMNS = [
    "sensor_id", "location", "timestamp",
    "water_level", "rainfall", "river_flow", "temperature",
    "humidity", "soil_moisture", "wind_speed",
    "flood_probability", "risk_level", "predicted_water_level",
    "physics_probability", "ml_probability", "ml_used",
    "model_name", "training_label", "data_source",
]


# ============================================================
# SETTINGS (key / value)
# ============================================================

def _get_setting(key, default=None):

    conn = get_connection()

    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    finally:
        conn.close()

    return row[0] if row else default


def _set_setting(key, value):

    conn = get_connection()

    try:
        with conn:
            conn.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, datetime.now().strftime(_TS_FORMAT))
            )
    finally:
        conn.close()


# ============================================================
# DATA MODE
# ============================================================

def get_data_mode():
    """'simulation' (default) or 'live'. Any database problem falls
    back to simulation so the app never crashes on this lookup."""

    try:
        mode = _get_setting(_MODE_KEY, DATA_MODE_SIMULATION)
    except Exception:
        return DATA_MODE_SIMULATION

    return DATA_MODE_LIVE if mode == DATA_MODE_LIVE else DATA_MODE_SIMULATION


def is_live_mode():

    return get_data_mode() == DATA_MODE_LIVE


def get_mode_info():
    """Dict with `mode`, and when / why / by whom it last changed
    (empty strings if it never changed)."""

    info = {"mode": get_data_mode(), "changed_at": "", "reason": "",
            "changed_by": ""}

    try:
        raw = _get_setting(_MODE_INFO_KEY)
        if raw:
            info.update(json.loads(raw))
    except Exception:
        pass

    return info


def set_data_mode(mode, reason="", changed_by=None):
    """Sets the mode explicitly (System Handler panel, or the
    automatic switch). Returns True if the mode actually changed."""

    if mode not in (DATA_MODE_SIMULATION, DATA_MODE_LIVE):
        raise ValueError(
            f"mode must be '{DATA_MODE_SIMULATION}' or '{DATA_MODE_LIVE}'"
        )

    previous = get_data_mode()

    if previous == mode:
        return False

    _set_setting(_MODE_KEY, mode)

    _set_setting(_MODE_INFO_KEY, json.dumps({
        "changed_at": datetime.now().strftime(_TS_FORMAT),
        "reason": reason,
        "changed_by": changed_by or "system",
    }))

    log_activity(
        ACTION_DATA_MODE_CHANGED,
        details=f"{previous} -> {mode}: {reason}"
    )

    return True


def activate_live_mode(reason):
    """Called whenever REAL data is connected. Switches simulation
    -> live (once; it never flips back by itself). Does nothing if
    LIVE_MODE_AUTO_SWITCH is off. Returns True if it switched."""

    if not LIVE_MODE_AUTO_SWITCH:
        return False

    return set_data_mode(DATA_MODE_LIVE, reason=reason)


# ============================================================
# REAL READINGS: STORAGE
# ============================================================

def _clean_value(value):

    if hasattr(value, "item"):
        value = value.item()

    if isinstance(value, float) and not np.isfinite(value):
        return None

    if value is pd.NaT or value is None:
        return None

    return value


def _frame_to_rows(df, data_source):

    ingested_at = datetime.now().strftime(_TS_FORMAT)

    frame = df.copy()

    frame["data_source"] = data_source

    for column in LIVE_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    rows = []

    for record in frame[LIVE_COLUMNS].itertuples(index=False, name=None):

        values = [_clean_value(v) for v in record]

        ml_used_index = LIVE_COLUMNS.index("ml_used")

        values[ml_used_index] = (
            None if values[ml_used_index] is None
            else int(bool(values[ml_used_index]))
        )

        rows.append(tuple(values) + (ingested_at,))

    return rows


_INSERT_SQL = (
    "INSERT INTO live_readings("
    + ", ".join(LIVE_COLUMNS)
    + ", ingested_at) VALUES ("
    + ", ".join("?" * (len(LIVE_COLUMNS) + 1))
    + ")"
)


def save_dataset(location, processed, meta=None):
    """Stores an uploaded dataset for one location (replacing that
    location's previous dataset) and switches to live mode.
    Returns True if this call switched the system to live mode."""

    location = str(location).strip()

    rows = _frame_to_rows(processed, SOURCE_DATASET)

    conn = get_connection()

    try:
        with conn:
            conn.execute(
                "DELETE FROM live_readings "
                "WHERE data_source = ? AND location = ?",
                (SOURCE_DATASET, location)
            )
            conn.executemany(_INSERT_SQL, rows)
    finally:
        conn.close()

    _set_setting(
        _DATASET_META_PREFIX + location,
        json.dumps(meta or {}, default=str)
    )

    return activate_live_mode(
        f"External dataset loaded for {location} "
        f"({len(rows)} rows)"
    )


def delete_dataset(location):
    """Removes one location's stored dataset. Does NOT switch the
    mode back (live mode is deliberate; only the System Handler
    switches back)."""

    location = str(location).strip()

    conn = get_connection()

    try:
        with conn:
            conn.execute(
                "DELETE FROM live_readings "
                "WHERE data_source = ? AND location = ?",
                (SOURCE_DATASET, location)
            )
            conn.execute(
                "DELETE FROM app_settings WHERE key = ?",
                (_DATASET_META_PREFIX + location,)
            )
    finally:
        conn.close()


def dataset_signature():
    """(row count, highest id) of stored dataset rows - lets each
    browser session notice that a dataset was loaded/removed
    elsewhere."""

    conn = get_connection()

    try:
        return tuple(conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM live_readings "
            "WHERE data_source = ?",
            (SOURCE_DATASET,)
        ).fetchone())
    finally:
        conn.close()


def load_datasets():
    """All stored datasets as ({location: DataFrame}, {location:
    meta}) - the same shape the session state keeps."""

    conn = get_connection()

    try:
        frame = pd.read_sql_query(
            "SELECT " + ", ".join(LIVE_COLUMNS)
            + " FROM live_readings WHERE data_source = ? ORDER BY id",
            conn,
            params=(SOURCE_DATASET,)
        )

        meta_rows = conn.execute(
            "SELECT key, value FROM app_settings WHERE key LIKE ?",
            (_DATASET_META_PREFIX + "%",)
        ).fetchall()
    finally:
        conn.close()

    datasets, metas = {}, {}

    if not frame.empty:

        frame["ml_used"] = frame["ml_used"].fillna(0).astype(bool)

        for location, group in frame.groupby("location", sort=False):
            datasets[location] = group.reset_index(drop=True)

    for key, value in meta_rows:

        location = key[len(_DATASET_META_PREFIX):]

        if location in datasets:
            try:
                metas[location] = json.loads(value)
            except Exception:
                metas[location] = {}

    return datasets, metas


# ============================================================
# REAL SENSORS
# ============================================================

def ingest_sensor_reading(sensor_id, values, timestamp=None, label=None):
    """THE entry point for real sensors (an HTTP endpoint, an MQTT
    listener, a serial reader... will all call this).

    sensor_id : must already be registered in the `sensors` table.
    values    : dict with the seven raw readings (water_level,
                rainfall, river_flow, temperature, humidity,
                soil_moisture, wind_speed).
    timestamp : optional; defaults to now.
    label     : optional real flood outcome for this reading, as a
                0-100 flood probability (or 0/1 -> 0/100). Readings
                with a label teach the retraining what really
                happened; without one they are used as weak data.

    The reading is validated (numbers, finite, physically plausible -
    same limits as uploaded datasets), run through the hybrid model,
    stored in `live_readings`, and the system switches to live mode.
    Returns (True, stored_record_dict) or (False, error_message);
    it never raises for bad input.
    """

    # Imported here (not at the top) so this module stays importable
    # without loading the ML stack.
    from flood_app.prediction import hybrid_flood_prediction_batch

    sensor_id = str(sensor_id or "").strip()

    if not sensor_id:
        return False, "sensor_id is required."

    conn = get_connection()

    try:
        row = conn.execute(
            "SELECT location FROM sensors WHERE sensor_id = ?",
            (sensor_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return False, (
            f"Unknown sensor '{sensor_id}'. Register it first "
            "(Sensor Configuration)."
        )

    location = str(row[0]).strip()

    values = values or {}

    missing = [c for c in REQUIRED_DATASET_COLUMNS if c not in values]

    if missing:
        return False, "Missing value(s): " + ", ".join(missing)

    clean = {}

    for column in REQUIRED_DATASET_COLUMNS:

        try:
            number = float(values[column])
        except (TypeError, ValueError):
            return False, f"'{column}' is not a number."

        if not np.isfinite(number):
            return False, f"'{column}' is not a finite number."

        low, high = DATASET_VALUE_LIMITS[column]

        if not low <= number <= high:
            return False, (
                f"'{column}' = {number} is outside the plausible "
                f"range {low} to {high}; reading rejected."
            )

        clean[column] = number

    if timestamp is None:
        parsed = datetime.now()
    else:
        parsed = pd.to_datetime(timestamp, errors="coerce")
        if pd.isna(parsed):
            return False, f"Unreadable timestamp: {timestamp!r}"
        parsed = parsed.to_pydatetime().replace(tzinfo=None)

    training_label = None

    if label is not None:

        try:
            training_label = float(label)
        except (TypeError, ValueError):
            return False, "label is not a number."

        if not np.isfinite(training_label):
            return False, "label is not a finite number."

        if 0 <= training_label <= 1:
            training_label *= 100.0

        training_label = float(np.clip(training_label, 0.0, 99.9))

    prediction = hybrid_flood_prediction_batch(
        pd.DataFrame([clean])
    ).iloc[0]

    record = {
        "sensor_id": sensor_id,
        "location": location,
        "timestamp": parsed.strftime(_TS_FORMAT),
        **{c: round(v, 2) for c, v in clean.items()},
        **prediction.to_dict(),
        "training_label": training_label,
    }

    rows = _frame_to_rows(pd.DataFrame([record]), SOURCE_SENSOR)

    conn = get_connection()

    try:
        with conn:
            conn.executemany(_INSERT_SQL, rows)
    finally:
        conn.close()

    activate_live_mode(
        f"First real sensor reading received from {sensor_id}"
    )

    # Let the models learn from the new data (throttled; runs in
    # the background; does nothing in simulation mode).
    try:
        from flood_app.retraining import maybe_retrain
        maybe_retrain()
    except Exception:
        pass

    return True, record


def get_live_sensor_readings():
    """Newest reading of every REAL sensor, skipping sensors that
    have been silent longer than LIVE_SENSOR_MAX_AGE_MINUTES (they
    count as 'no data', not as current)."""

    conn = get_connection()

    try:
        frame = pd.read_sql_query(
            "SELECT " + ", ".join("r." + c for c in LIVE_COLUMNS)
            + " FROM live_readings r WHERE r.data_source = ? "
            "AND r.id = (SELECT r2.id FROM live_readings r2 "
            "WHERE r2.sensor_id = r.sensor_id "
            "AND r2.data_source = r.data_source "
            "ORDER BY r2.timestamp DESC, r2.id DESC LIMIT 1)",
            conn,
            params=(SOURCE_SENSOR,)
        )
    finally:
        conn.close()

    if frame.empty:
        return frame

    frame["ml_used"] = frame["ml_used"].fillna(0).astype(bool)

    if LIVE_SENSOR_MAX_AGE_MINUTES:

        age = datetime.now() - pd.to_datetime(
            frame["timestamp"], errors="coerce"
        )

        fresh = age <= pd.Timedelta(minutes=LIVE_SENSOR_MAX_AGE_MINUTES)

        frame = frame[fresh.fillna(False)]

    return frame.reset_index(drop=True)


def live_data_signature():
    """(row count, highest id) of ALL live readings - changes when
    any new real reading arrives."""

    conn = get_connection()

    try:
        return tuple(conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM live_readings"
        ).fetchone())
    finally:
        conn.close()


def live_data_summary():
    """Counts for the Data Mode panel."""

    conn = get_connection()

    try:
        rows = conn.execute(
            "SELECT data_source, COUNT(*), COUNT(DISTINCT location), "
            "MAX(timestamp) FROM live_readings GROUP BY data_source"
        ).fetchall()

        simulated_rows = conn.execute(
            "SELECT COUNT(*) FROM sensor_readings"
        ).fetchone()[0]
    finally:
        conn.close()

    summary = {
        source: {"rows": n, "locations": locs, "latest": latest}
        for source, n, locs, latest in rows
    }

    summary["simulated_rows_in_history"] = simulated_rows

    return summary
