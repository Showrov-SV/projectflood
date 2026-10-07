"""Data-related UI: dataset upload panel, sensor & dataset management and
the sidebar 'Refresh data' control."""

import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3

from flood_app.config import (
    REQUIRED_DATASET_COLUMNS,
    SIMULATION_REFRESH_SECONDS,
    SUPPORTED_DATASET_TYPES,
)
from flood_app.database import get_connection
from flood_app.datasets import (
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
from flood_app.sensors import get_sensors, refresh_simulated_data


def render_data_refresh_control():
    """Sidebar: when the data was last generated + a manual
    refresh button. Called at the END of main() so the timestamp
    reflects the render that just happened."""

    updated_at = st.session_state.get("data_updated_at")

    if updated_at is None:
        return

    with st.sidebar:

        st.divider()

        if SIMULATION_REFRESH_SECONDS > 0:
            st.caption(
                f"🕒 Data updated {updated_at:%H:%M:%S} · "
                f"new readings every {SIMULATION_REFRESH_SECONDS}s"
            )
        else:
            st.caption(f"🕒 Data updated {updated_at:%H:%M:%S}")

        if st.button(
            "🔄 Refresh data",
            key="sidebar_refresh_data",
            width="stretch"
        ):
            refresh_simulated_data()
            st.rerun()


# ============================================================
# DATASET UPLOAD PANEL
# ============================================================

def dataset_upload_panel(target_location, scope_locations=None):

    """
    target_location comes from the single, shared 📍 Location
    Selection control in admin_dashboard() — this panel no
    longer owns its own location selector (previously
    "Select Location for this Dataset" lived here). Upload +
    validate + load still work exactly as before; only the
    location now comes from outside, so the same location stays
    consistent across dataset assignment, prediction, and the
    map, per the redesign.

    scope_locations, when provided (a list of area names), scopes
    the "Data Source Status" / "Active External Datasets" views
    below to only that caller's authorized areas — used by
    Division Admin, District Admin, Division/District
    Police/Fire/Hospital/Municipality, so a scoped account never
    sees another division's/district's registered sensors or
    datasets listed here. None (the default) preserves the
    original unrestricted nationwide behavior (System Handler,
    the main Administrator).
    """

    ensure_dataset_state()

    st.subheader(
        "📂 External Dataset Input"
    )

    st.info(
        """
        Upload a CSV or XLSX dataset of sensor/environmental
        observations. The file itself does not need a location
        column — it is assigned to whichever location is
        currently chosen in 📍 Location Selection above.

        Once you load a dataset for a location, that location
        stops using simulated data and uses your uploaded values
        instead for prediction and the map. Other locations keep
        simulating as normal. You can upload datasets for
        several different locations at once — just change the
        Location Selection above between uploads.
        """
    )

    # --------------------------------------------------------
    # TARGET LOCATION (read-only here — set above, not here)
    # --------------------------------------------------------

    if target_location:

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

                    st.session_state.uploaded_datasets[
                        target_location
                    ] = processed

                    st.session_state.uploaded_datasets_meta[
                        target_location
                    ] = {

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

                    st.success(
                        f"Dataset loaded for {target_location}. "
                        f"Simulation is now disabled for this location."
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
        # account (Division/District Admin, Division/District
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
            "No external datasets loaded. All locations are "
            "using simulated data."
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
    block for dashboards OTHER than admin_dashboard() (which has
    its own equivalent block already, scoped by district there).
    Used by system_handler_dashboard() (scope_locations=None,
    meaning nationwide), division_admin_dashboard()
    (scope_locations=that division's own areas), and
    organization_dashboard() (scope_locations=that division's or
    district's own areas, or None for a legacy nationwide
    account).

    Enforces the same restriction at BOTH the UI level (a
    selectbox instead of free text when scoped — no "type
    manually" bypass) AND the database-write level below (defense
    in depth, matching the pattern already used for District
    Admin in admin_dashboard()).
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
                "external CSV/XLSX dataset input. Real sensors can "
                "later be connected using ESP32, Arduino, MQTT, a "
                "REST API or another IoT gateway."
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
