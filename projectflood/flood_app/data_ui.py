"""Data-related UI: dataset upload panel and sensor & dataset management."""

import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3

from flood_app.activity_log import (
    ACTION_DATASET_LOADED,
    ACTION_SENSOR_ADDED,
    log_activity,
)
from flood_app.config import (
    DATA_MODE_LIVE,
    DATA_MODE_SIMULATION,
    LIVE_MODE_AUTO_SWITCH,
    LIVE_SENSOR_MAX_AGE_MINUTES,
    REQUIRED_DATASET_COLUMNS,
    SUPPORTED_DATASET_TYPES,
)
from flood_app.data_mode import (
    SOURCE_DATASET,
    SOURCE_SENSOR,
    get_mode_info,
    is_live_mode,
    live_data_summary,
    set_data_mode,
)
from flood_app.database import get_connection
from flood_app.retraining import (
    get_status as get_training_status,
    request_retrain,
    rollback_to_original,
)
from flood_app.datasets import (
    commit_dataset,
    ensure_dataset_state,
    get_full_dataset,
    get_uploaded_locations,
    normalize_dataset_columns,
    pick_latest_record,
    process_uploaded_dataframe,
    read_dataset_file,
    remove_dataset_location,
)
from flood_app.geography import LOCATION_COORDINATES
from flood_app.sensors import get_sensors


# ============================================================
# DATASET UPLOAD PANEL
# ============================================================

def data_mode_banner():
    """One-line status shown on every page, so simulated and real
    readings can never be mistaken for each other."""

    if is_live_mode():

        st.caption("🟢 Live mode — showing real data only.")

    else:

        st.caption(
            "🧪 Demo mode — readings are SIMULATED, not real "
            "measurements."
        )


def data_mode_panel():
    """System Handler panel: shows the data mode and lets the
    System Handler switch it manually (e.g. back to simulation, or to
    live before any data is connected)."""

    st.subheader("🔀 Data Mode")

    info = get_mode_info()

    live = info["mode"] == DATA_MODE_LIVE

    if live:

        st.success(
            "🟢 **LIVE mode** — simulation is off. Dashboards, map, "
            "alerts and the digital twin use only real data."
        )

    else:

        st.info(
            "🧪 **SIMULATION mode** — every registered sensor gets "
            "random demo readings."
            + (
                " Connecting real data (CSV upload or a real "
                "sensor) switches to live mode automatically."
                if LIVE_MODE_AUTO_SWITCH
                else " Automatic switching is OFF "
                     "(LIVE_MODE_AUTO_SWITCH in config.py)."
            )
        )

    if info["changed_at"]:

        st.caption(
            f"Last change: {info['changed_at']} by "
            f"{info['changed_by']} — {info['reason'] or 'no reason'}"
        )

    summary = live_data_summary()

    dataset = summary.get(SOURCE_DATASET, {})
    sensor = summary.get(SOURCE_SENSOR, {})

    col1, col2, col3 = st.columns(3)

    col1.metric("Dataset rows stored", dataset.get("rows", 0))

    col2.metric("Real-sensor readings stored", sensor.get("rows", 0))

    col3.metric(
        "Old simulated rows (history)",
        summary["simulated_rows_in_history"]
    )

    if LIVE_SENSOR_MAX_AGE_MINUTES:

        st.caption(
            f"A real sensor silent for more than "
            f"{LIVE_SENSOR_MAX_AGE_MINUTES} min shows as 'no data' "
            f"(LIVE_SENSOR_MAX_AGE_MINUTES in config.py)."
        )

    if live:

        confirm = st.checkbox(
            "I understand this turns simulation back ON and the "
            "dashboards will show random demo values again.",
            key="data_mode_confirm_back"
        )

        if st.button(
            "↩️ Switch back to Simulation mode",
            disabled=not confirm,
            key="data_mode_back"
        ):

            set_data_mode(
                DATA_MODE_SIMULATION,
                reason="Switched back manually",
                changed_by=st.session_state.get("username")
            )

            st.rerun()

    else:

        if st.button(
            "🟢 Switch to LIVE mode now",
            key="data_mode_live"
        ):

            set_data_mode(
                DATA_MODE_LIVE,
                reason="Switched to live manually",
                changed_by=st.session_state.get("username")
            )

            st.rerun()


def model_training_panel():
    """System Handler panel: automatic retraining status, plus a
    manual 'Retrain now' and a rollback to the original model."""

    st.subheader("🧠 Model Training")

    status = get_training_status()

    if not status["live_mode"]:

        st.info(
            "🧪 Simulation mode — the models stay exactly as they are "
            "(trained once on the synthetic dataset). Automatic "
            "retraining on real data starts when live mode starts."
        )

        return

    version = status["active_version"]

    if version == 0:

        st.warning(
            "Currently using the ORIGINAL model (synthetic data only). "
            "It has not been retrained on real data yet."
        )

    else:

        latest = next(
            (v for v in status["versions"] if v["version"] == version),
            None
        )

        st.success(
            f"Using retrained model **v{version}**"
            + (
                f" — trained {latest['trained_at']} on "
                f"{latest['n_real_rows']} real rows "
                f"({latest['n_real_labeled']} with real outcome "
                f"labels)."
                if latest else "."
            )
        )

    col1, col2, col3 = st.columns(3)

    col1.metric("Real rows stored", status["real_rows"])

    col2.metric(
        "New rows since last attempt",
        f"{status['new_rows']} / {status['min_new_rows']}"
    )

    col3.metric(
        "Training now",
        "Yes" if status["running"] else "No"
    )

    st.caption(
        f"Automatic: retrains after each dataset upload, then when "
        f"{status['min_new_rows']} new real rows have arrived "
        f"(at most every {status['min_interval_minutes']} min). "
        f"A new model is only used if it is not worse than the "
        f"current one on held-out rows."
    )

    report = status["last_report"]

    if report:

        icon = "✅" if report.get("accepted") else "⏸️"

        st.markdown(
            f"**Last attempt** ({status['last_attempt_at']}) {icon} "
            f"{report.get('reason', '')}"
        )

        if report.get("gate_set"):

            st.caption(
                f"Compared on {report['n_gate_rows']} "
                f"{report['gate_set']}: error (MAE) "
                f"{report['old_gate_mae']} → {report['new_gate_mae']}. "
                f"On the synthetic base rows: "
                f"{report['old_synthetic_mae']} → "
                f"{report['new_synthetic_mae']}."
                + (
                    f" R² on those rows: {report['new_gate_r2']}."
                    if "new_gate_r2" in report else ""
                )
            )

        if report.get("n_real_rows"):

            st.caption(
                f"Real rows used: {report['n_real_rows']} "
                f"({report.get('n_real_labeled', 0)} with real "
                f"outcome labels, {report.get('n_real_weak', 0)} "
                f"unlabelled/weak). Only labelled rows teach the "
                f"model what actually happened."
            )

    if status["versions"]:

        st.dataframe(
            pd.DataFrame(status["versions"]).drop(
                columns=["max_id"], errors="ignore"
            ).rename(columns={
                "version": "Version", "trained_at": "Trained at",
                "n_real_rows": "Real rows",
                "n_real_labeled": "Labelled",
                "hybrid_r2": "R²", "hybrid_mae": "MAE",
            }),
            hide_index=True,
            width="stretch"
        )

    b1, b2 = st.columns(2)

    with b1:

        if st.button(
            "🔁 Retrain now",
            disabled=status["running"],
            key="model_retrain_now"
        ):

            started, message = request_retrain(force=True)

            st.info(message)

            st.rerun()

    with b2:

        confirm = st.checkbox(
            "Go back to the original model",
            key="model_rollback_confirm",
            disabled=version == 0
        )

        if st.button(
            "↩️ Roll back",
            disabled=version == 0 or not confirm,
            key="model_rollback"
        ):

            rollback_to_original()

            st.rerun()


def dataset_upload_panel(target_location, scope_locations=None):

    """
    target_location comes from the single, shared 📍 Location
    Selection control — this panel no
    longer owns its own location selector (previously
    "Select Location for this Dataset" lived here). Upload +
    validate + load still work exactly as before; only the
    location now comes from outside, so the same location stays
    consistent across dataset assignment, prediction, and the
    map, per the redesign.

    scope_locations, when provided (a list of area names), scopes
    the "Data Source Status" / "Active External Datasets" views
    below to only that caller's authorized areas — used by
    Division Admin, Division
    Police/Fire/Hospital/Municipality, so a scoped account never
    sees another division's registered sensors or
    datasets listed here. None (the default) preserves the
    original unrestricted nationwide behavior (System Handler,
    the main Administrator).
    """

    ensure_dataset_state()

    st.subheader(
        "📂 External Dataset Input"
    )

    _flash = st.session_state.pop("_flash_dataset_msg", None)

    if _flash:

        st.success(_flash)

    st.info(
        """
        Upload a CSV or XLSX dataset of sensor/environmental
        observations. The file itself does not need a location
        column — it is assigned to whichever location is
        currently chosen in 📍 Location Selection above.

        Loading the first real dataset switches the WHOLE system
        from simulation to LIVE mode: simulated readings stop
        everywhere, and the map, alerts and predictions use only
        real data (uploaded datasets and real sensors).
        You can upload datasets for several different locations —
        just change the Location Selection above between uploads.
        """
    )

    if not is_live_mode() and LIVE_MODE_AUTO_SWITCH:

        st.warning(
            "⚠️ The system is currently in SIMULATION mode. Loading "
            "a dataset will switch it to LIVE mode (simulation off "
            "for every location)."
        )

    # --------------------------------------------------------
    # TARGET LOCATION (read-only here — set above, not here)
    # --------------------------------------------------------

    if target_location:

        # The System Handler dashboard does not show this note.
        if st.session_state.get("role") != "System Handler":

            st.success(
                f"🎯 This dataset will be assigned to "
                f"**{target_location}**. To assign it elsewhere, "
                f"change 📍 Location Selection above first."
            )

    else:

        st.warning(
            "Choose a location in 📍 Location Selection above "
            "before uploading a dataset."
        )

    # --------------------------------------------------------
    # FILE UPLOAD
    # --------------------------------------------------------

    uploaded_file = st.file_uploader(
        "Upload Sensor Dataset (CSV or XLSX)",
        type=SUPPORTED_DATASET_TYPES,
        key="flood_dataset_upload"
    )

    if uploaded_file is not None:

        raw_df = read_dataset_file(
            uploaded_file
        )

        if raw_df is not None:

            file_type = (
                uploaded_file.name.split(".")[-1].upper()
            )

            normalized_preview = normalize_dataset_columns(
                raw_df
            )

            missing_columns = [

                column

                for column in REQUIRED_DATASET_COLUMNS

                if column not in normalized_preview.columns

            ]

            st.write(
                "**Dataset Preview**"
            )

            preview_col1, preview_col2, preview_col3 = st.columns(3)

            preview_col1.metric(
                "File Name",
                uploaded_file.name
            )

            preview_col2.metric(
                "File Type",
                file_type
            )

            preview_col3.metric(
                "Rows",
                len(raw_df)
            )

            st.write(
                f"**Columns detected ({len(raw_df.columns)}):** "
                + ", ".join(str(c) for c in raw_df.columns)
            )

            st.write(
                f"**Selected location:** "
                f"{target_location if target_location else '_(none selected)_'}"
            )

            if missing_columns:

                st.error(
                    "❌ Dataset Status: Invalid — missing required "
                    "columns: " + ", ".join(missing_columns)
                )

                st.info(
                    "Required columns: "
                    + ", ".join(REQUIRED_DATASET_COLUMNS)
                )

            else:

                st.success(
                    "✅ Dataset Status: Valid — all required "
                    "columns detected."
                )

            st.dataframe(
                raw_df.head(10),
                width="stretch",
                hide_index=True
            )

            can_load = (
                not missing_columns
                and bool(target_location)
            )

            if st.button(
                f"📥 Load Dataset for "
                f"{target_location if target_location else '...'}",
                width="stretch",
                disabled=not can_load
            ):

                processed = process_uploaded_dataframe(
                    raw_df,
                    target_location
                )

                if processed is not None:

                    switched_to_live = commit_dataset(
                        target_location,
                        processed,
                        {

                            "filename":
                                uploaded_file.name,

                            "file_type":
                                file_type,

                            "rows":
                                len(processed),

                            "columns":
                                list(raw_df.columns),

                            "loaded_at":
                                datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                )

                        }
                    )

                    log_activity(
                        ACTION_DATASET_LOADED,
                        details=(
                            f"{uploaded_file.name} -> "
                            f"{target_location} "
                            f"({len(processed)} rows)"
                        )
                    )

                    st.session_state["_flash_dataset_msg"] = (
                        f"Dataset loaded for {target_location}. "
                        + (
                            "The system is now in LIVE mode: "
                            "simulation is off for every location."
                            if switched_to_live
                            else "Live mode: only real data is used."
                            if is_live_mode()
                            else "Mode unchanged (auto-switch is "
                                 "off); the System Handler can "
                                 "switch to live mode."
                        )
                    )

                    st.rerun()

            if not target_location:

                st.warning(
                    "Select or enter a location above before loading."
                )

    st.divider()

    # --------------------------------------------------------
    # DATA SOURCE STATUS PER LOCATION
    # --------------------------------------------------------

    st.write(
        "**Data Source Status**"
    )

    uploaded_locations = get_uploaded_locations()

    sensor_locations = set(
        get_sensors()["location"].astype(str).tolist()
    )

    if scope_locations is not None:

        # Defense in depth for the read side too: a scoped
        # account (Division Admin, Division
        # org accounts) never sees another area's registered
        # sensors or uploaded datasets listed here, not just be
        # blocked from uploading to them.
        sensor_locations = sensor_locations & set(scope_locations)

        uploaded_locations = [
            loc for loc in uploaded_locations
            if loc in scope_locations
        ]

    all_tracked_locations = sorted(
        sensor_locations | set(uploaded_locations)
    )

    if all_tracked_locations:

        status_rows = [

            {

                "Location":
                    loc,

                "Data Source":
                    "🔵 External Dataset"
                    if loc in uploaded_locations
                    else "🟢 Simulated Data"

            }

            for loc in all_tracked_locations

        ]

        st.dataframe(
            pd.DataFrame(status_rows),
            width="stretch",
            hide_index=True
        )

    # --------------------------------------------------------
    # ACTIVE EXTERNAL DATASETS (per location)
    # --------------------------------------------------------

    if not uploaded_locations:

        st.info(
            "No external datasets loaded. "
            + (
                "Live mode: locations with no real data show "
                "'no data'."
                if is_live_mode()
                else "All locations are using simulated data."
            )
        )

        return

    st.write(
        "**Active External Datasets**"
    )

    for location in uploaded_locations:

        dataset_df = get_full_dataset(
            location
        )

        meta = st.session_state.uploaded_datasets_meta.get(
            location,
            {}
        )

        with st.expander(
            f"🔵 {location} — {meta.get('rows', len(dataset_df))} row(s)",
            expanded=False
        ):

            st.caption(
                f"File: {meta.get('filename', 'unknown')}  |  "
                f"Type: {meta.get('file_type', 'unknown')}  |  "
                f"Loaded: {meta.get('loaded_at', 'unknown')}"
            )

            st.dataframe(
                dataset_df,
                width="stretch",
                hide_index=True
            )

            # ------------------------------------------------
            # PREDICTION FOR THIS LOCATION (latest record)
            # ------------------------------------------------

            latest = pick_latest_record(
                dataset_df
            )

            if latest is not None:

                st.write(
                    f"**🎯 Prediction for {location} "
                    f"(latest record)**"
                )

                pred_col1, pred_col2, pred_col3, pred_col4 = st.columns(4)

                pred_col1.metric(
                    "💧 Water Level",
                    f"{latest['water_level']} m"
                )

                pred_col2.metric(
                    "🌧️ Rainfall",
                    f"{latest['rainfall']} mm"
                )

                pred_col3.metric(
                    "🤖 Flood Probability",
                    f"{latest['flood_probability']}%"
                )

                pred_col4.metric(
                    "⚠️ Risk Level",
                    latest["risk_level"]
                )

                st.caption(
                    f"Record timestamp: {latest['timestamp']}"
                )

            if st.button(
                f"🗑️ Remove Dataset for {location}",
                key=f"remove_dataset_{location}",
                width="stretch"
            ):

                remove_dataset_location(
                    location
                )

                st.success(
                    f"External dataset removed for {location}. "
                    f"Simulation will resume for this location."
                )

                st.rerun()


def sensor_and_dataset_management_section(
    scope_locations,
    scope_label,
    key_prefix
):
    """
    Reusable "Sensor Registration + External Dataset Upload"
    block. Used by system_handler_dashboard() (scope_locations=None,
    meaning nationwide), division_admin_dashboard()
    (scope_locations=that division's own areas), and
    organization_dashboard() (scope_locations=that division's own
    areas, or None for a legacy nationwide account).

    Enforces the same restriction at BOTH the UI level (a
    selectbox instead of free text when scoped — no "type
    manually" bypass) AND the database-write level below (defense
    in depth).
    """

    st.subheader(
        "⚙️ Sensor & Dataset Management"
    )

    tab_sensor_cfg, tab_dataset = st.tabs(
        [
            "⚙️ Sensor Configuration",
            "📂 External Dataset Input"
        ]
    )

    with tab_sensor_cfg:

        with st.expander("ℹ️ About sensor data sources"):

            st.write(
                "The system supports simulated sensor data and "
                "external CSV/XLSX dataset input."
            )

        col1, col2 = st.columns(2)

        with col1:

            st.markdown(
                "### ➕ Register New Sensor"
            )

            sensor_id = st.text_input(
                "Sensor ID",
                key=f"{key_prefix}_sensor_id"
            )

            if scope_locations is not None:

                # Scoped account: restricted to this scope's own
                # areas ONLY — no free-text escape hatch.
                location = st.selectbox(
                    "Location",
                    scope_locations,
                    key=f"{key_prefix}_sensor_location"
                )

            else:

                location = st.text_input(
                    "Location",
                    key=f"{key_prefix}_sensor_location"
                )

            latitude = st.number_input(
                "Latitude",
                value=23.8103,
                min_value=-90.0,
                max_value=90.0,
                format="%.6f",
                key=f"{key_prefix}_sensor_lat"
            )

            longitude = st.number_input(
                "Longitude",
                value=90.4125,
                min_value=-180.0,
                max_value=180.0,
                format="%.6f",
                key=f"{key_prefix}_sensor_lon"
            )

            sensor_type = st.selectbox(
                "Sensor Type",
                [
                    "Water Level",
                    "Rainfall",
                    "River Flow",
                    "Soil Moisture",
                    "Weather Station",
                    "Multi-Sensor"
                ],
                key=f"{key_prefix}_sensor_type"
            )

            if st.button(
                "➕ Register Sensor",
                key=f"{key_prefix}_register_btn"
            ):

                # Trim stray spaces so "S1 " and "S1" can't become
                # two different sensors and a whitespace-only value
                # can't pass the "not empty" check below.
                sensor_id = (sensor_id or "").strip()
                location = (location or "").strip()

                if (
                    scope_locations is not None
                    and location not in scope_locations
                ):

                    # Backend-level enforcement — never trust the
                    # UI alone. Only reachable if something
                    # bypassed the restricted selectbox above.
                    st.error(
                        f"You can only register sensors within "
                        f"{scope_label}."
                    )

                elif sensor_id and location:

                    conn = get_connection()

                    try:

                        conn.execute(
                            """
                            INSERT INTO sensors(
                                sensor_id,
                                location,
                                latitude,
                                longitude,
                                sensor_type,
                                status
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sensor_id,
                                location,
                                latitude,
                                longitude,
                                sensor_type,
                                "Online"
                            )
                        )

                        conn.commit()

                        log_activity(
                            ACTION_SENSOR_ADDED,
                            details=(
                                f"{sensor_id} ({sensor_type}) at "
                                f"{location}"
                            )
                        )

                        st.success(
                            "Sensor registered successfully."
                        )

                    except sqlite3.IntegrityError:

                        st.error(
                            "Sensor ID already exists."
                        )

                    finally:

                        conn.close()

                else:

                    st.warning(
                        "Please enter Sensor ID and Location."
                    )

        with col2:

            st.markdown(
                "### 📡 Registered Sensors"
            )

            sensors = get_sensors()

            if scope_locations is not None:

                # Read-side restriction too, not just writes —
                # a scoped account can't see other areas' sensors
                # here either.
                sensors = sensors[
                    sensors["location"].isin(scope_locations)
                ]

            st.dataframe(
                sensors,
                width="stretch",
                hide_index=True
            )

    with tab_dataset:

        if scope_locations is not None:

            dataset_target_location = st.selectbox(
                "🎯 Location for dataset upload",
                scope_locations,
                key=f"{key_prefix}_dataset_location"
            )

        else:

            master_locations = sorted(
                set(LOCATION_COORDINATES.keys())
                | set(
                    get_sensors()["location"].astype(str).tolist()
                )
                | set(get_uploaded_locations())
            )

            dataset_target_location = st.selectbox(
                "🎯 Location for dataset upload",
                master_locations,
                key=f"{key_prefix}_dataset_location"
            ) if master_locations else None

        dataset_upload_panel(
            dataset_target_location,
            scope_locations=scope_locations
        )
