"""Division Admin dashboard."""

import streamlit as st

from flood_app.alert_ui import render_emergency_alert_banner
from flood_app.alerts import create_emergency_alert
from flood_app.data_ui import sensor_and_dataset_management_section
from flood_app.geography import DIVISION_AREAS
from flood_app.mail_roles import get_role_email, mailbox_key
from flood_app.mail_ui import email_center
from flood_app.maps import create_flood_map, location_badge_row
from flood_app.messaging import get_email_log
from flood_app.prediction_ui import (
    render_flood_probability_gauge,
    render_hybrid_prediction_details,
)
from flood_app.sensors import generate_all_sensor_data


def division_admin_dashboard(division):
    """
    Own dashboard/monitoring area/messaging system for ONE
    Bangladesh division, per the requirements. `division` comes
    from st.session_state (set at login from the users table),
    never chosen by the admin themselves — so a Dhaka Admin can
    never switch to viewing Chattogram's data.
    """

    if not division:

        st.error(
            "This Division Admin account has no division "
            "assigned. Please contact the System Handler."
        )

        return

    mailbox = mailbox_key(
        "Division Admin",
        division
    )

    st.title(
        f"🧭 {division} Division Admin Dashboard"
    )

    st.caption(
        f"👤 {st.session_state.username}  |  Role: Division Admin  "
        f"|  Division: {division}"
    )

    # --------------------------------------------------------
    # NEW EMERGENCY ALERT SYSTEM (blinking + sound)
    # --------------------------------------------------------

    render_emergency_alert_banner(mailbox)

    st.divider()

    # --------------------------------------------------------
    # 1 & 2. AREA SELECTION, then 3 & 4. MAP + PREDICTION
    # --------------------------------------------------------

    st.subheader(
        "📍 Area Selection"
    )

    area_options = DIVISION_AREAS.get(
        division,
        [division]
    )

    readings = generate_all_sensor_data()

    division_readings = readings[
        readings["location"].isin(area_options)
    ]

    # Quick-glance risk overview for every area in this
    # division, before picking one from the dropdown below.
    st.markdown(
        location_badge_row(division_readings, area_options)
    )

    st.caption(
        "🟢 Low   🟡 Moderate   🟠 High   🔴 Severe   "
        "⚪ No reading yet"
    )

    selected_area = st.selectbox(
        "Choose an area within your division to monitor",
        area_options,
        key=f"{mailbox}_area"
    )

    if division_readings.empty:

        st.warning(
            f"No sensor readings are currently available for "
            f"{division} Division."
        )

    else:

        st.divider()

        st.subheader(
            "🗺️ Live Flood Location Map"
        )


        st.plotly_chart(
            create_flood_map(
                division_readings,
                focus_location=selected_area
            ),
            width="stretch"
        )

        st.caption(
            "🟢 Low   🟡 Moderate   🟠 High   🔴 Severe — each "
            "marker is labeled with its location and current "
            "risk."
        )

        st.divider()

        st.subheader(
            f"📊 Current Prediction — {selected_area}"
        )

        matched = division_readings[
            division_readings["location"]
            .astype(str)
            .str.strip()
            .str.lower()
            == selected_area.strip().lower()
        ]

        if not matched.empty:

            row = matched.iloc[0]

            risk = row["risk_level"]

            if risk == "Low":
                st.success(f"🟢 Current Risk: {risk}")
            elif risk == "Moderate":
                st.warning(f"🟡 Current Risk: {risk}")
            elif risk == "High":
                st.warning(f"🟠 Current Risk: {risk}")
            else:
                st.error(f"🔴 Current Risk: {risk}")

            m1, m2, m3, m4 = st.columns(4)

            m1.metric(
                "💧 Water Level", f"{row['water_level']} m"
            )
            m2.metric(
                "🌧️ Rainfall", f"{row['rainfall']} mm"
            )
            m3.metric(
                "🌊 River Flow", f"{row['river_flow']} m³/s"
            )
            m4.metric(
                "🤖 Flood Probability",
                f"{row['flood_probability']}%"
            )

            st.caption(
                f"Data source: {row['data_source']}  |  "
                f"Last updated: {row['timestamp']}"
            )

            render_flood_probability_gauge(
                row["flood_probability"],
                risk_level=risk,
                label=f"{selected_area} Flood Probability"
            )

            render_hybrid_prediction_details(row)

        else:

            st.info(
                f"No current reading for {selected_area} yet."
            )

        st.divider()

        st.subheader(
            f"📈 {division} Division Monitoring Data"
        )

        monitoring_columns = [
            "location", "water_level", "rainfall", "river_flow",
            "temperature", "humidity", "soil_moisture",
            "wind_speed", "flood_probability", "risk_level",
            "data_source"
        ]

        st.dataframe(
            division_readings[
                [
                    column for column in monitoring_columns
                    if column in division_readings.columns
                ]
            ],
            width="stretch",
            hide_index=True
        )

    st.divider()

    # --------------------------------------------------------
    # 5. EMERGENCY ORGANIZATIONS (this division only)
    # --------------------------------------------------------

    st.subheader(
        "🚓 Emergency Organizations"
    )

    org_icons = {
        "Police": "👮",
        "Fire Service": "🚒",
        "Hospital": "🏥",
        "Municipality": "🏛️"
    }

    org_columns = st.columns(4)

    for org_column, org_role in zip(
        org_columns,
        ("Police", "Fire Service", "Hospital", "Municipality")
    ):

        org_mailbox = mailbox_key(org_role, division)

        with org_column:

            st.markdown(
                f"#### {org_icons[org_role]} {org_role}"
            )

            st.success(
                "🟢 Active"
            )

            org_inbox = get_email_log(org_mailbox)

            unread_messages = (
                len(org_inbox[org_inbox["is_read"] == 0])
                if not org_inbox.empty
                else 0
            )

            st.caption(
                f"📧 {unread_messages} unread message(s)"
            )

            st.caption(
                f"`{get_role_email(org_mailbox)}`"
            )

    st.divider()

    # --------------------------------------------------------
    # NOTIFY THIS DIVISION'S EMERGENCY ORGANIZATIONS
    # --------------------------------------------------------
    # Reuses the exact same create_emergency_alert() /
    # render_emergency_alert_banner() blink+sound system as the
    # Administrator's global siren — just scoped to this one
    # division's 3 organizations instead of nationwide.
    # --------------------------------------------------------

    st.subheader(
        "📢 Notify Division Emergency Organizations"
    )

    alert_title = st.text_input(
        "Alert Title",
        value="Flood Emergency",
        key=f"{mailbox}_alert_title"
    )

    alert_message = st.text_area(
        "Alert Message",
        key=f"{mailbox}_alert_message"
    )

    alert_level = st.selectbox(
        "Alert Level",
        ["CRITICAL", "HIGH", "MODERATE"],
        key=f"{mailbox}_alert_level"
    )

    if st.button(
        f"🚨 Notify {division} Police + Fire + Hospital + Municipality",
        width="stretch"
    ):

        if alert_message.strip():

            recipient_keys = [
                mailbox_key(org_role, division)
                for org_role in
                ("Police", "Fire Service", "Hospital", "Municipality")
            ]

            create_emergency_alert(
                st.session_state.username,
                recipient_keys,
                alert_title or "Flood Emergency",
                alert_message,
                level=alert_level,
                target_division=division,
                target_area=selected_area
            )

            st.success(
                f"✅ Emergency alert sent to {division} Police, "
                f"Fire Service, Hospital, and Municipality."
            )

        else:

            st.warning(
                "Please enter an alert message before sending."
            )

    st.divider()

    # --------------------------------------------------------
    # 6. MESSAGING (Inbox / Sent / Compose / Bin — reused)
    # --------------------------------------------------------

    st.subheader(
        "📨 Messaging"
    )

    division_admin_recipients = [
        mailbox_key(org_role, division)
        for org_role in (
            "Police", "Fire Service", "Hospital", "Municipality"
        )
    ] + ["System Handler"]

    email_center(
        mailbox,
        recipients_override=division_admin_recipients
    )

    st.divider()

    # --------------------------------------------------------
    # 7. SENSOR REGISTRATION + EXTERNAL DATASET INPUT
    # --------------------------------------------------------
    # Restricted to this division's own areas ONLY — both via a
    # restricted dropdown (no free-text escape hatch) and again
    # at the database-write level inside the shared helper below.
    # --------------------------------------------------------

    sensor_and_dataset_management_section(
        scope_locations=area_options,
        scope_label=f"{division} Division",
        key_prefix=mailbox
    )
