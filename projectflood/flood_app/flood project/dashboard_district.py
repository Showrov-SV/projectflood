"""District Admin dashboard (also used by the legacy Administrator role)."""

import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3

from flood_app.alert_ui import emergency_siren, render_emergency_alert_banner
from flood_app.alerts import create_emergency_alert
from flood_app.config import AUTO_ALERT_COOLDOWN_MINUTES
from flood_app.data_ui import dataset_upload_panel
from flood_app.database import get_connection
from flood_app.datasets import get_uploaded_locations
from flood_app.geography import (
    get_district_areas,
    get_division_for_location,
    LOCATION_COORDINATES,
)
from flood_app.mail_roles import mailbox_key
from flood_app.mail_ui import (
    admin_message_center,
    email_center,
    mail_server_panel,
)
from flood_app.maps import create_flood_map
from flood_app.messaging import send_email
from flood_app.prediction_ui import (
    render_flood_probability_gauge,
    render_hybrid_prediction_details,
)
from flood_app.sensors import (
    generate_all_sensor_data,
    get_location_coordinates,
    get_sensors,
)


# ============================================================
# ADMINISTRATOR DASHBOARD
# ============================================================

def admin_dashboard(district=None):
    """
    district is None for the main, nationwide Administrator —
    everything below behaves exactly as before for that case.
    When district is set (a District Admin account), this EXACT
    SAME dashboard is reused (per the requirement to not build an
    unnecessary separate dashboard), but every section below is
    scoped to that one district's own areas: the location
    selector only offers that district's areas (no "type
    manually" escape hatch), sensor registration is restricted
    to those areas at BOTH the UI and the database-write level,
    dataset upload inherits the same restricted location
    selector, and Emergency Response/Communication targets only
    that district's own emergency organizations instead of the
    whole country.
    """

    if district:

        st.title(
            f"👨‍💻 District Admin Control Center — {district}"
        )


        render_emergency_alert_banner(
            mailbox_key("District Admin", district)
        )

    else:

        st.title(
            "👨‍💻 Administrator Control Center"
        )

        st.caption(
            "Flood monitoring, sensor management, prediction "
            "and emergency response"
        )

    # --------------------------------------------------------
    # LIVE SENSOR GENERATION
    # --------------------------------------------------------
    # For a District Admin, EVERYTHING below is scoped by
    # filtering `readings` down to just this district's areas
    # right here — the same enforcement pattern already used for
    # Division Admin and division-scoped organization accounts.
    # Every section that follows (metrics, map, prediction,
    # tables, charts) reads from this already-filtered
    # DataFrame, so district scoping is automatic and cannot be
    # bypassed by anything downstream.
    # --------------------------------------------------------

    readings = (
        generate_all_sensor_data()
    )

    district_areas = (
        get_district_areas(district) if district else None
    )

    if district:

        readings = readings[
            readings["location"].isin(district_areas)
        ]

    if readings.empty:

        st.warning(
            "No sensor readings are currently available."
        )

        return

    # --------------------------------------------------------
    # TOP SUMMARY METRICS
    # --------------------------------------------------------

    total_sensors = len(
        readings
    )

    severe = len(
        readings[
            readings[
                "risk_level"
            ] == "Severe"
        ]
    )

    high = len(
        readings[
            readings[
                "risk_level"
            ] == "High"
        ]
    )

    average_probability = (
        readings[
            "flood_probability"
        ].mean()
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "📡 Total Active Readings",
        total_sensors
    )

    col2.metric(
        "🟠 High Risk Areas",
        high
    )

    col3.metric(
        "🔴 Severe Areas",
        severe
    )

    col4.metric(
        "📊 Avg Flood Probability",
        f"{average_probability:.1f}%"
    )

    st.divider()

    # ========================================================
    # 1. LOCATION SELECTION
    # ========================================================
    # A single, shared location selector for the whole primary
    # monitoring flow below (map, prediction) AND for dataset
    # assignment further down — the same selected location is
    # used everywhere, per the redesign requirements. This
    # replaces the location selector that previously lived
    # inside the dataset upload panel.
    # ========================================================

    st.subheader(
        "📍 Location Selection"
    )

    if district:

        # District Admin: restricted to this district's own
        # areas ONLY. No "➕ Other (type manually)" option — that
        # free-text escape hatch is exactly the kind of bypass
        # the requirements call out, so it's simply not offered
        # to a district-scoped account.
        master_locations = list(district_areas)

        location_options = master_locations

    else:

        master_locations = sorted(
            set(LOCATION_COORDINATES.keys())
            | set(
                get_sensors()["location"]
                .astype(str)
                .tolist()
            )
            | set(
                get_uploaded_locations()
            )
        )

        location_options = master_locations + [
            "➕ Other (type manually)"
        ]

    if (
        "admin_location_choice" not in st.session_state
        or st.session_state.admin_location_choice
        not in location_options
    ):

        st.session_state.admin_location_choice = (
            location_options[0]
            if location_options
            else "➕ Other (type manually)"
        )

    location_choice = st.selectbox(
        "Choose a location to monitor",
        location_options,
        key="admin_location_choice"
    )

    if location_choice == "➕ Other (type manually)":

        selected_location = st.text_input(
            "Enter Location Name",
            key="admin_location_manual"
        ).strip()

        if (
            selected_location
            and get_location_coordinates(selected_location) is None
        ):

            st.warning(
                f"No coordinates are configured for "
                f"'{selected_location}'. It can still be used "
                f"for prediction and dataset assignment, but it "
                f"won't appear on the map until coordinates are "
                f"added to LOCATION_COORDINATES."
            )

    else:

        selected_location = location_choice

    if selected_location:

        st.caption(
            f"📍 Selected Location: **{selected_location}**"
        )

    st.divider()

    # ========================================================
    # 2. LIVE FLOOD LOCATION MAP
    # ========================================================
    # Unchanged map logic (create_flood_map still plots every
    # currently tracked location) — only its position changed,
    # now directly under Location Selection.
    # ========================================================

    st.subheader(
        "🗺️ Live Flood Location Map"
    )

    if selected_location:

        st.caption(
            f"Centered on **{selected_location}** — every "
            f"location is still shown and hoverable; change "
            f"📍 Location Selection above to jump elsewhere."
        )

    st.plotly_chart(
        create_flood_map(
            readings,
            focus_location=selected_location
        ),
        width="stretch"
    )

    st.caption(
        "🟢 Low   🟡 Moderate   🟠 High   🔴 Severe — each "
        "marker is labeled with its location and current risk."
    )

    st.divider()

    # ========================================================
    # 3. CURRENT PREDICTION FOR THE SELECTED LOCATION
    # ========================================================
    # Unchanged prediction values (straight from `readings`,
    # exactly as calculated elsewhere) — just surfaced for the
    # one selected location, right after the map.
    # ========================================================

    st.subheader(
        f"📊 Current Prediction — {selected_location or '—'}"
    )

    matched = pd.DataFrame()

    if selected_location:

        matched = readings[
            readings["location"]
            .astype(str)
            .str.strip()
            .str.lower()
            == selected_location.strip().lower()
        ]

    if not matched.empty:

        selected_row = matched.iloc[0]

        risk = selected_row["risk_level"]

        if risk == "Low":

            st.success(
                f"🟢 Current Risk: {risk}"
            )

        elif risk == "Moderate":

            st.warning(
                f"🟡 Current Risk: {risk}"
            )

        elif risk == "High":

            st.warning(
                f"🟠 Current Risk: {risk}"
            )

        else:

            st.error(
                f"🔴 Current Risk: {risk}"
            )

        pcol1, pcol2, pcol3, pcol4 = st.columns(4)

        pcol1.metric(
            "💧 Water Level",
            f"{selected_row['water_level']} m"
        )

        pcol2.metric(
            "🌧️ Rainfall",
            f"{selected_row['rainfall']} mm"
        )

        pcol3.metric(
            "🌊 River Flow",
            f"{selected_row['river_flow']} m³/s"
        )

        pcol4.metric(
            "🤖 Flood Probability",
            f"{selected_row['flood_probability']}%"
        )

        st.caption(
            f"Data source: {selected_row['data_source']}  |  "
            f"Last updated: {selected_row['timestamp']}"
        )

        render_flood_probability_gauge(
            selected_row["flood_probability"],
            risk_level=risk,
            label=f"{selected_location} Flood Probability"
        )

        render_hybrid_prediction_details(selected_row)

    else:

        st.info(
            f"No current sensor or dataset reading for "
            f"**{selected_location or 'this location'}** yet. "
            f"Register a sensor or upload an external dataset "
            f"for it under ⚙️ Advanced Configuration below."
        )

    st.divider()

    # ========================================================
    # 4. SENSOR & MONITORING INFORMATION
    # ========================================================
    # Same three views as before (live readings table,
    # all-locations prediction table, bar charts) — now tabbed
    # instead of always-expanded, so they don't dominate the
    # page.
    # ========================================================

    st.subheader(
        "📈 Sensor & Monitoring Information"
    )

    tab_live, tab_pred, tab_charts = st.tabs(
        [
            "📡 Live Sensor Data",
            "🤖 Prediction Overview (All Locations)",
            "📊 Charts"
        ]
    )

    with tab_live:

        display_columns = [

            "sensor_id",

            "location",

            "timestamp",

            "water_level",

            "rainfall",

            "river_flow",

            "temperature",

            "humidity",

            "soil_moisture",

            "wind_speed",

            "flood_probability",

            "risk_level",

            "data_source"

        ]

        st.dataframe(

            readings[
                [
                    column
                    for column in display_columns
                    if column in readings.columns
                ]
            ],

            width="stretch",

            hide_index=True

        )

        simulated_count = len(
            readings[
                readings["data_source"]
                == "Simulation"
            ]
        )

        external_count = len(
            readings[
                readings["data_source"]
                == "External Dataset"
            ]
        )

        if external_count > 0:

            st.success(
                f"🟢 Live stream active. "
                f"{simulated_count} simulated + "
                f"{external_count} external dataset reading(s)."
            )

        else:

            st.success(
                "🟢 Live sensor simulation is active."
            )

    with tab_pred:

        prediction_df = readings[

            [
                "location",

                "water_level",

                "rainfall",

                "river_flow",

                "flood_probability",

                "risk_level",

                "data_source"

            ]

        ].sort_values(

            "flood_probability",

            ascending=False

        )

        st.dataframe(

            prediction_df,

            width="stretch",

            hide_index=True

        )

    with tab_charts:

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:

            fig_water = px.bar(

                readings,

                x="location",

                y="water_level",

                color="risk_level",

                title="Current Water Level"

            )

            st.plotly_chart(
                fig_water,
                width="stretch"
            )

        with chart_col2:

            fig_rain = px.bar(

                readings,

                x="location",

                y="rainfall",

                color="risk_level",

                title="Current Rainfall"

            )

            st.plotly_chart(
                fig_rain,
                width="stretch"
            )

    st.divider()

    # ========================================================
    # 5. EMERGENCY RESPONSE & COMMUNICATION
    # ========================================================
    # Same four capabilities as before (messaging, SMTP status,
    # Admin's own mailbox, siren) — identical underlying calls,
    # just grouped into tabs instead of four stacked sections.
    # ========================================================

    st.subheader(
        "🚨 Emergency Response & Communication"
    )

    st.caption(
        f"🤖 Automatic alerts are active: any location that "
        f"reaches **High** or **Severe** risk automatically "
        f"notifies Police, Fire Service and Hospital (plus that "
        f"area's Division Admin, if it belongs to one of the 8 "
        f"divisions) — no manual click needed. Re-alerts for the "
        f"same location are limited to once every "
        f"{AUTO_ALERT_COOLDOWN_MINUTES} minutes. The tools below "
        f"remain available for sending alerts manually too."
    )

    if district:

        # --------------------------------------------------
        # District Admin: simplified, district-scoped
        # messaging + siren + own mailbox, instead of the
        # nationwide Admin tools below. Resolves this
        # district's relevant emergency organizations via its
        # parent division (e.g. "Jamalpur" -> "Mymensingh
        # Police/Fire Service/Hospital/Municipality"); falls back to System
        # Handler if the district has no parent division
        # mapping, so there's always someone to contact (the
        # legacy national Police/Fire Service/Hospital accounts
        # this used to fall back to have been removed entirely).
        # --------------------------------------------------

        district_mailbox = mailbox_key("District Admin", district)

        parent_division = get_division_for_location(district)

        if parent_division:

            district_org_recipients = [
                mailbox_key(org_role, parent_division)
                for org_role in
                ("Police", "Fire Service", "Hospital", "Municipality")
            ]

        else:

            district_org_recipients = ["System Handler"]

        tab_msg, tab_mailbox, tab_siren = st.tabs(
            [
                "📨 District Messaging",
                "📬 My Mailbox",
                "🚨 Siren"
            ]
        )

        with tab_msg:

            st.info(
                f"Message the emergency organizations covering "
                f"{district} District."
            )

            district_subject = st.text_input(
                "Subject",
                key=f"{district_mailbox}_msg_subject"
            )

            district_message = st.text_area(
                "Message",
                key=f"{district_mailbox}_msg_body"
            )

            district_target = st.selectbox(
                "Send to",
                district_org_recipients,
                key=f"{district_mailbox}_msg_target"
            )

            if st.button(
                "📨 Send",
                key=f"{district_mailbox}_msg_send",
                width="stretch"
            ):

                if district_message.strip():

                    send_email(
                        district_mailbox,
                        district_target,
                        district_subject or "(No subject)",
                        district_message
                    )

                    st.success(
                        f"✅ Message sent to {district_target}."
                    )

                else:

                    st.warning(
                        "Please enter a message before sending."
                    )

        with tab_mailbox:

            email_center(
                district_mailbox,
                recipients_override=district_org_recipients
            )

        with tab_siren:

            st.error(
                f"Emergency Siren: notify the emergency "
                f"organizations covering {district} District."
            )

            siren_title = st.text_input(
                "Alert Title",
                value="Flood Emergency",
                key=f"{district_mailbox}_siren_title"
            )

            siren_message = st.text_area(
                "Alert Message",
                key=f"{district_mailbox}_siren_message"
            )

            siren_level = st.selectbox(
                "Alert Level",
                ["CRITICAL", "HIGH", "MODERATE"],
                key=f"{district_mailbox}_siren_level"
            )

            if st.button(
                f"🚨 NOTIFY {district.upper()} EMERGENCY "
                f"ORGANIZATIONS",
                key=f"{district_mailbox}_siren_send",
                width="stretch"
            ):

                if siren_message.strip():

                    create_emergency_alert(
                        st.session_state.username,
                        district_org_recipients,
                        siren_title or "Flood Emergency",
                        siren_message,
                        level=siren_level,
                        target_division=parent_division,
                        target_area=(
                            selected_location
                            if selected_location in district_areas
                            else district
                        )
                    )

                    st.success(
                        f"✅ Emergency alert sent to "
                        f"{district}'s emergency organizations."
                    )

                else:

                    st.warning(
                        "Please enter an alert message before "
                        "sending."
                    )

    else:

        tab_msg, tab_smtp, tab_mailbox, tab_siren = st.tabs(
            [
                "📨 Messaging",
                "📧 SMTP Status",
                "📬 My Mailbox",
                "🚨 Siren"
            ]
        )

        with tab_msg:

            admin_message_center()

        with tab_smtp:

            mail_server_panel()

        with tab_mailbox:

            # Admin's own personal mailbox on the SAME email system
            # as the messaging panel and SMTP status log above —
            # lets Admin read replies from any organization and
            # compose ordinary (non-emergency) emails to any of
            # them too.

            email_center("Administrator", show_compose=False)

        with tab_siren:

            st.error(
                "Emergency Siren: Use this control to notify "
                "Police, Fire Service or Hospital."
            )

            if st.button(
                "🚨 ACTIVATE EMERGENCY SIREN",
                width="stretch"
            ):

                st.session_state.show_emergency_panel = True

            if st.session_state.get(
                "show_emergency_panel",
                False
            ):

                emergency_siren()

                if st.button(
                    "Close Emergency Panel"
                ):

                    st.session_state.show_emergency_panel = False

                    st.rerun()

    st.divider()

    # ========================================================
    # 6. ADVANCED CONFIGURATION
    # ========================================================
    # Sensor Configuration and External Dataset Input — moved
    # to the bottom together, tabbed, since these are setup /
    # supporting actions rather than the primary monitoring
    # flow above. Same underlying logic as before; the dataset
    # panel now uses the shared Location Selection above
    # instead of its own embedded location selector.
    # ========================================================

    st.subheader(
        "⚙️ Advanced Configuration"
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
                key="sensor_id"
            )

            if district:

                # District Admin: registration restricted to
                # this district's own areas — both at the UI
                # level (a selectbox instead of free text, so
                # there's nothing to type an out-of-district
                # value into) AND, just below, at the database-
                # write level (defense in depth).
                location = st.selectbox(
                    "Location",
                    district_areas,
                    key="sensor_location"
                )

            else:

                location = st.text_input(
                    "Location",
                    key="sensor_location"
                )

            latitude = st.number_input(
                "Latitude",
                value=23.8103,
                min_value=-90.0,
                max_value=90.0,
                format="%.6f"
            )

            longitude = st.number_input(
                "Longitude",
                value=90.4125,
                min_value=-180.0,
                max_value=180.0,
                format="%.6f"
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

                ]

            )

            if st.button(
                "➕ Register Sensor"
            ):

                # Trim stray spaces (see the matching fix in
                # sensor_and_dataset_management_section).
                sensor_id = (sensor_id or "").strip()
                location = (location or "").strip()

                if district and location not in district_areas:

                    # Backend-level enforcement — never trust
                    # the UI alone. This can only be reached if
                    # something bypassed the restricted
                    # selectbox above; it is rejected here
                    # regardless of how that happened.
                    st.error(
                        f"You can only register sensors within "
                        f"{district} District."
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

            if district:

                # Same district-only visibility restriction
                # applied to the read side, not just writes.
                sensors = sensors[
                    sensors["location"].isin(district_areas)
                ]

            st.dataframe(

                sensors,

                width="stretch",

                hide_index=True

            )

    with tab_dataset:

        dataset_upload_panel(
            selected_location,
            scope_locations=district_areas if district else None
        )
