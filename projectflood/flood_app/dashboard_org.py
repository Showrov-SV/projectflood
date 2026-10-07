"""Organization portals: Police, Fire Service, Hospital, Municipality
(division and district level)."""

import streamlit as st

from flood_app.alert_ui import render_emergency_alert_banner
from flood_app.geography import DIVISION_AREAS, get_district_areas
from flood_app.mail_roles import (
    EMERGENCY_DOMAINS,
    get_role_email,
    LEGACY_MAIL_ROLES,
    mailbox_key,
)
from flood_app.mail_ui import email_center
from flood_app.maps import create_flood_map, location_badge_row
from flood_app.prediction_ui import render_flood_probability_gauge
from flood_app.sensors import generate_all_sensor_data


# ============================================================
# ORGANIZATION PORTAL
# ============================================================

def organization_dashboard(
    role,
    division=None,
    district=None
):
    """
    division is None for the 5 original global accounts (Police,
    Fire Service, Hospital, Municipality login exactly as
    before — though those accounts have now been removed
    entirely; this branch is kept for any custom account an
    operator might add by hand). For a hierarchical
    division-specific account (e.g. Dhaka Police), division is
    that account's assigned division, and `mailbox` below
    becomes that account's own composite mailbox/alert key (e.g.
    "Dhaka Police") — used for its own Inbox/Sent/Bin, its own
    emergency-alert read state, and to scope monitoring data to
    just that division's areas.

    district is set instead for a district-tier organization
    account (District Police, District Fire Service, District
    Municipality — role itself is already prefixed "District ",
    e.g. role="District Police"). It mirrors the division branch
    exactly, but scopes to DISTRICT_AREAS/get_district_areas()
    instead of DIVISION_AREAS, and messages that district's own
    District Admin instead of a Division Admin. division and
    district are never both set for the same account.
    """

    mailbox = mailbox_key(role, division or district)

    # --------------------------------------------------------
    # Generate latest sensor data
    # --------------------------------------------------------
    # For a hierarchical account, scope every table/map/metric
    # below to ONLY this division's (or district's) areas — this
    # is what makes e.g. Dhaka Police see Dhaka data only, and
    # Dhaka District Police see Dhaka District's areas only.
    # Legacy accounts (division=None, district=None) keep seeing
    # every location exactly as before.
    # --------------------------------------------------------

    readings = (
        generate_all_sensor_data()
    )

    # None for a legacy nationwide account (no scope
    # restriction); set below to this division's or district's
    # own areas for a hierarchical account. Reused further down
    # to scope sensor registration / dataset upload the same way.
    scoped_area_list = None

    if division:

        scoped_area_list = DIVISION_AREAS.get(division, [])

        readings = readings[
            readings["location"].isin(scoped_area_list)
        ]

    elif district:

        scoped_area_list = get_district_areas(district)

        readings = readings[
            readings["location"].isin(scoped_area_list)
        ]

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------
    # Substring checks (not ==) so this also matches the
    # district-tier role strings ("District Fire Service",
    # "District Municipality") without duplicating this block.
    # --------------------------------------------------------

    if "Hospital" in role:

        icon = "🏥"


    elif "Fire Service" in role:

        icon = "🚒"


    elif "Municipality" in role:

        icon = "🏛️"


    else:

        icon = "👮"


    if division:

        st.title(
            f"{icon} {division} {role} Portal"
        )

    elif district:

        st.title(
            f"{icon} {district} {role} Portal"
        )

    else:

        st.title(
            f"{icon} {role} Portal"
        )

    if division:

        _area = st.session_state.get("area")

        st.caption(
            f"👤 Role: {role}  |  Division: {division}"
            + (f"  |  Area: {_area}" if _area else "")
        )

    elif district:

        st.caption(
            f"👤 Role: {role}  |  District: {district}  |  "
            f"Area: {st.session_state.get('area') or '—'}"
        )

    else:

        st.caption(
            f"Emergency Portal Domain: "
            f"{EMERGENCY_DOMAINS.get(role, 'Not configured')}"
        )


    # ========================================================
    # EMERGENCY ALERT BANNER (blinking + sound)
    # ========================================================
    # Consolidated: combines the newer emergency_alerts store
    # and the older emergency_notifications table into ONE
    # banner with ONE "Mark Emergency Alerts as Read" button —
    # previously these were two separate boxes with two
    # separately-labeled buttons, so clearing one didn't clear
    # the other. Independent per-recipient read state, keyed on
    # `mailbox` — so e.g. Dhaka Police and Dhaka Hospital, or
    # Dhaka Police and the legacy global "Police" account, never
    # share read/unread state with one another.
    # ========================================================

    render_emergency_alert_banner(mailbox)

    # ========================================================
    # EMAIL (Inbox / Sent / Compose / Bin)
    # ========================================================
    # This is the same Admin -> Emergency Organization
    # Messaging / email_log system, now available to this
    # organization too: it can receive email from Admin AND
    # from every other organization, and reply/compose to any
    # of them, with its own private Inbox/Sent/Bin. Separate
    # from the emergency alert banner above, which continues
    # to work exactly as before.
    #
    # recipients_override enforces the hierarchy's access
    # control: a hierarchical account may only message its own
    # Division Admin; a legacy account keeps its EXACT original
    # recipient list (every other legacy role), unaffected by
    # any of the new hierarchical mailbox keys.
    # ========================================================

    st.caption(
        f"📧 Mailbox: {get_role_email(mailbox)}"
    )

    if division:

        email_recipients = [f"{division} Division Admin"]

    elif district:

        email_recipients = [
            mailbox_key("District Admin", district)
        ]

    else:

        email_recipients = [
            r for r in LEGACY_MAIL_ROLES if r != mailbox
        ]

    email_center(
        mailbox,
        recipients_override=email_recipients
    )

    st.divider()

    if readings.empty:

        st.warning(
            "No monitoring readings are currently available."
        )

        return

    # ========================================================
    # SUMMARY METRICS
    # ========================================================

    high = len(
        readings[
            readings[
                "risk_level"
            ] == "High"
        ]
    )

    severe = len(
        readings[
            readings[
                "risk_level"
            ] == "Severe"
        ]
    )

    average_probability = (
        readings[
            "flood_probability"
        ].mean()
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "📍 Monitoring Locations",
        len(readings)
    )

    col2.metric(
        "🟠 High Risk",
        high
    )

    col3.metric(
        "🔴 Severe Risk",
        severe
    )

    col4.metric(
        "🤖 Avg Prediction",
        f"{average_probability:.1f}%"
    )

    st.divider()

    # ========================================================
    # FLOOD PREDICTION
    # ========================================================

    st.subheader(
        "🤖 Live Flood Prediction"
    )

    st.write(
        "Current flood predictions for all monitored locations."
    )

    prediction_columns = [

        "location",

        "water_level",

        "rainfall",

        "river_flow",

        "temperature",

        "humidity",

        "soil_moisture",

        "flood_probability",

        "risk_level",

        "data_source"

    ]

    prediction_table = readings[
        prediction_columns
    ].sort_values(

        "flood_probability",

        ascending=False

    )

    st.dataframe(

        prediction_table,

        width="stretch",

        hide_index=True

    )

    st.divider()

    # ========================================================
    # LOCATION-SPECIFIC PREDICTION
    # ========================================================

    st.subheader(
        "📍 Location-Specific Prediction"
    )

    location_list_for_badges = readings["location"].tolist()

    if location_list_for_badges:

        st.markdown(
            location_badge_row(readings, location_list_for_badges)
        )

        st.caption(
            "🟢 Low   🟡 Moderate   🟠 High   🔴 Severe"
        )

    selected_location = st.selectbox(

        "Select Location",

        readings[
            "location"
        ].tolist(),

        key=f"{mailbox}_location"

    )

    selected = readings[
        readings[
            "location"
        ] == selected_location
    ].iloc[0]

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

    st.caption(
        f"Data Source: {selected['data_source']}"
    )

    # --------------------------------------------------------
    # Predicted water level
    # --------------------------------------------------------
    # Uses the REAL hybrid physics/ML model's predicted_water_level
    # (already computed in `selected` by hybrid_flood_prediction),
    # not an ad-hoc recomputation — so this always agrees with the
    # flood probability and risk level shown elsewhere on this
    # same reading.
    # --------------------------------------------------------

    st.metric(
        "🔮 Predicted Water Level",
        f"{selected['predicted_water_level']:.2f} m"
    )

    st.divider()

    # ========================================================
    # FLOOD MAP
    # ========================================================

    st.subheader(
        "🌍 Live Flood Location Map"
    )

    st.caption(
        f"Centered on **{selected_location}** — every location "
        f"is still shown and hoverable; change Select Location "
        f"above to jump elsewhere."
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
    # FLOOD PROBABILITY GAUGE
    # ========================================================

    st.subheader(
        "📈 Flood Probability"
    )

    render_flood_probability_gauge(
        selected["flood_probability"],
        risk_level=selected.get("risk_level"),
        label=f"{selected_location} Flood Probability"
    )

    st.caption(
        f"Last updated: {selected['timestamp']}"
    )

    st.divider()
