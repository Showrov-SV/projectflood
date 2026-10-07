"""System Handler control center (nationwide overview, map, districts,
alerts, messages, sensors & data)."""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from flood_app.alerts import (
    create_emergency_alert,
    get_total_unread_emergency_alert_count,
    get_unread_emergency_alert_counts_by_recipient,
    mark_all_emergency_alerts_read_nationwide,
)
from flood_app.config import (
    DISTRICT_ORG_ROLES,
    DIVISION_ORG_ROLES,
    NO_DATA_CIRCLE,
    RISK_CIRCLE,
)
from flood_app.data_ui import sensor_and_dataset_management_section
from flood_app.database import get_connection
from flood_app.geography import (
    BD_DIVISIONS,
    DISTRICT_NAMES,
    DIVISION_AREAS,
    get_division_for_location,
)
from flood_app.mail_roles import mailbox_key
from flood_app.mail_ui import email_center
from flood_app.maps import create_flood_map, worst_risk_circle
from flood_app.messaging import send_email
from flood_app.sensors import generate_all_sensor_data


def summarize_locations(readings):
    """
    One row per monitored location, using that location's WORST
    sensor (highest flood probability) — a location with several
    sensors is only as safe as its most at-risk one — plus how
    many sensors report there and which division it belongs to.
    Sorted most-at-risk first. Returns an empty DataFrame when
    there are no readings.
    """

    if readings is None or readings.empty:
        return pd.DataFrame()

    working = readings.copy()

    working["location"] = working["location"].astype(str).str.strip()

    sensor_counts = (
        working.groupby("location").size().rename("sensors")
    )

    worst = (
        working
        .sort_values("flood_probability", ascending=False)
        .drop_duplicates("location")
        .set_index("location")
        .join(sensor_counts)
        .reset_index()
    )

    worst["division"] = worst["location"].map(
        lambda name: get_division_for_location(name) or "—"
    )

    return worst.sort_values(
        "flood_probability", ascending=False
    ).reset_index(drop=True)


def risk_label(level):
    """'🟠 High' style label; '⚪ No data' when there's no level."""

    if not level or (isinstance(level, float) and pd.isna(level)):
        return f"{NO_DATA_CIRCLE} No data"

    return f"{RISK_CIRCLE.get(level, NO_DATA_CIRCLE)} {level}"


def get_recent_alert_events(limit=25):
    """
    The latest `limit` alert EVENTS (one row per alert, not one
    per recipient copy) with how many recipients got it and how
    many of those haven't read it yet.
    """

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT a.id, a.created_at, a.level, a.title,
                   a.target_division, a.target_area,
                   COUNT(r.id),
                   COALESCE(SUM(CASE WHEN r.is_read = 0
                                     THEN 1 ELSE 0 END), 0)
            FROM (
                SELECT * FROM emergency_alerts
                ORDER BY id DESC LIMIT ?
            ) a
            LEFT JOIN emergency_alert_reads r ON r.alert_id = a.id
            GROUP BY a.id
            ORDER BY a.id DESC
            """,
            (limit,)
        ).fetchall()
    finally:
        conn.close()

    return pd.DataFrame(
        rows,
        columns=[
            "id", "created_at", "level", "title", "division",
            "area", "recipients", "unread"
        ]
    )


def count_alert_events_since(hours=24):

    cutoff = (
        datetime.now() - timedelta(hours=hours)
    ).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()

    try:
        return conn.execute(
            "SELECT COUNT(*) FROM emergency_alerts "
            "WHERE created_at >= ?",
            (cutoff,)
        ).fetchone()[0]
    finally:
        conn.close()


def unread_alert_copies_by_division(unread_by_mailbox):
    """Unread alert copies per division, counting the division's
    own accounts AND every district account inside it."""

    totals = {}

    for division in BD_DIVISIONS:

        total = unread_by_mailbox.get(
            mailbox_key("Division Admin", division), 0
        )

        for org_role in DIVISION_ORG_ROLES:
            total += unread_by_mailbox.get(
                mailbox_key(org_role, division), 0
            )

        for district_name in DIVISION_AREAS.get(division, []):

            total += unread_by_mailbox.get(
                mailbox_key("District Admin", district_name), 0
            )

            for org_role in DISTRICT_ORG_ROLES:
                total += unread_by_mailbox.get(
                    mailbox_key(org_role, district_name), 0
                )

        totals[division] = total

    return totals


def broadcast_recipient_keys(divisions, include_districts):
    """Mailbox keys that should receive a manual System Handler
    alert for the given divisions."""

    keys = []

    for division in divisions:

        keys.append(mailbox_key("Division Admin", division))

        keys += [
            mailbox_key(org_role, division)
            for org_role in DIVISION_ORG_ROLES
        ]

        if include_districts:

            for district_name in DIVISION_AREAS.get(division, []):

                keys.append(
                    mailbox_key("District Admin", district_name)
                )

                keys += [
                    mailbox_key(org_role, district_name)
                    for org_role in DISTRICT_ORG_ROLES
                ]

    return keys


# ============================================================
# SYSTEM HANDLER DASHBOARD
# ============================================================

def system_handler_dashboard():
    """
    Nationwide control center: headline numbers, what needs
    attention right now, the live map, a filterable district
    table, alert history + broadcast, division messaging and
    sensor / dataset management — organised into tabs so the
    most urgent information is always first and nothing needs
    endless scrolling.
    """

    st.title("🧭 System Handler Control Center")

    st.caption(f"👤 {st.session_state.username}")

    readings = generate_all_sensor_data()

    locations = summarize_locations(readings)

    has_data = not locations.empty

    # --------------------------------------------------------
    # HEADLINE NUMBERS
    # --------------------------------------------------------

    severe_count = (
        int((locations["risk_level"] == "Severe").sum())
        if has_data else 0
    )

    high_count = (
        int((locations["risk_level"] == "High").sum())
        if has_data else 0
    )

    k1, k2, k3, k4, k5 = st.columns(5)

    k1.metric(
        "Locations monitored",
        len(locations) if has_data else 0
    )

    k2.metric("🔴 Severe", severe_count)

    k3.metric("🟠 High", high_count)

    k4.metric(
        "Avg flood risk",
        f"{readings['flood_probability'].mean():.1f}%"
        if has_data else "—"
    )

    k5.metric(
        "Alert events (24h)",
        count_alert_events_since(24)
    )

    if not has_data:
        st.warning("No sensor readings are currently available.")

    (
        tab_overview, tab_map, tab_districts,
        tab_alerts, tab_messages, tab_data
    ) = st.tabs([
        "📊 Overview",
        "🗺️ Live Map",
        "🔍 Districts",
        "🚨 Alerts",
        "📨 Messages",
        "⚙️ Sensors & Data"
    ])

    # --------------------------------------------------------
    # OVERVIEW
    # --------------------------------------------------------

    with tab_overview:

        st.subheader("🚨 Needs attention now")

        if has_data:

            attention = locations[
                locations["risk_level"].isin(["Severe", "High"])
            ]

            if attention.empty:

                st.success(
                    "No location is currently at High or "
                    "Severe risk."
                )

            else:

                shown = attention.head(15)

                st.dataframe(
                    pd.DataFrame({
                        "Risk": shown["risk_level"].map(risk_label),
                        "Location": shown["location"],
                        "Division": shown["division"],
                        "Flood probability":
                            shown["flood_probability"],
                        "Water level (m)":
                            shown["water_level"],
                        "Predicted level (m)":
                            shown["predicted_water_level"],
                        "Rainfall (mm)": shown["rainfall"],
                        "Sensors": shown["sensors"],
                    }),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Flood probability":
                            st.column_config.ProgressColumn(
                                "Flood probability",
                                min_value=0,
                                max_value=100,
                                format="%.1f%%"
                            ),
                    }
                )

                if len(attention) > len(shown):
                    st.caption(
                        f"Showing the {len(shown)} highest-risk "
                        f"of {len(attention)} locations at High "
                        f"or Severe risk — see the Districts tab "
                        f"for the full list."
                    )

        st.subheader("🏛️ Divisions at a glance")

        unread_by_division = unread_alert_copies_by_division(
            get_unread_emergency_alert_counts_by_recipient()
        )

        card_columns = st.columns(4) + st.columns(4)

        for card_column, division in zip(card_columns, BD_DIVISIONS):

            areas = DIVISION_AREAS.get(division, [])

            division_readings = (
                readings[readings["location"].isin(areas)]
                if has_data else readings
            )

            division_locations = (
                locations[locations["division"] == division]
                if has_data else locations
            )

            with card_column:

                with st.container(border=True):

                    st.markdown(
                        f"**{worst_risk_circle(readings, areas)} "
                        f"{division}**"
                    )

                    if has_data and not division_readings.empty:

                        st.metric(
                            "Avg flood risk",
                            f"{division_readings['flood_probability'].mean():.1f}%"
                        )

                        hot = int(
                            division_locations["risk_level"]
                            .isin(["High", "Severe"]).sum()
                        )

                        st.caption(
                            f"⚠️ {hot} of {len(division_locations)} "
                            f"districts at High/Severe risk"
                        )

                    else:

                        st.metric("Avg flood risk", "No data")

                    unread = unread_by_division.get(division, 0)

                    if unread:
                        st.caption(f"📬 {unread} unread alerts")

    # --------------------------------------------------------
    # LIVE MAP
    # --------------------------------------------------------

    with tab_map:

        map_division = st.selectbox(
            "Show",
            ["All divisions"] + BD_DIVISIONS,
            key="sh_map_division"
        )

        if not has_data:

            st.warning("No sensor readings are currently available.")

        else:

            map_readings = (
                readings
                if map_division == "All divisions"
                else readings[
                    readings["location"].isin(
                        DIVISION_AREAS.get(map_division, [])
                    )
                ]
            )

            st.plotly_chart(
                create_flood_map(map_readings),
                width="stretch"
            )

            st.caption(
                "🟢 Low   🟡 Moderate   🟠 High   🔴 Severe — "
                "each marker is labeled with its location and "
                "current risk."
            )

    # --------------------------------------------------------
    # DISTRICTS
    # --------------------------------------------------------

    with tab_districts:

        f1, f2, f3 = st.columns([2, 1, 2])

        with f1:
            district_search = st.text_input(
                "Search by district name",
                key="sh_district_search",
                placeholder="e.g. Gazipur, Cox's Bazar, Rangamati..."
            )

        with f2:
            division_filter = st.selectbox(
                "Division",
                ["All Divisions"] + BD_DIVISIONS,
                key="sh_division_filter"
            )

        with f3:
            risk_filter = st.multiselect(
                "Risk level",
                ["Severe", "High", "Moderate", "Low", "No data"],
                default=["Severe", "High", "Moderate", "Low", "No data"],
                key="sh_risk_filter"
            )

        unread_by_mailbox = (
            get_unread_emergency_alert_counts_by_recipient()
        )

        by_location = (
            locations.set_index("location") if has_data else None
        )

        district_rows = []

        for district_name in DISTRICT_NAMES:

            division_of_district = (
                get_division_for_location(district_name) or "—"
            )

            if (
                division_filter != "All Divisions"
                and division_of_district != division_filter
            ):
                continue

            if (
                district_search
                and district_search.strip().lower()
                not in district_name.lower()
            ):
                continue

            if has_data and district_name in by_location.index:
                row = by_location.loc[district_name]
                level = row["risk_level"]

                if level not in ("Severe", "High", "Moderate", "Low"):
                    level = "No data"
            else:
                row = None
                level = "No data"

            if level not in risk_filter:
                continue

            unread = unread_by_mailbox.get(
                mailbox_key("District Admin", district_name), 0
            ) + sum(
                unread_by_mailbox.get(
                    mailbox_key(org_role, district_name), 0
                )
                for org_role in DISTRICT_ORG_ROLES
            )

            district_rows.append({
                "Risk level": level,
                "District": district_name,
                "Division": division_of_district,
                "Flood probability (%)":
                    float(row["flood_probability"])
                    if row is not None else None,
                "Water level (m)":
                    float(row["water_level"])
                    if row is not None else None,
                "Rainfall (mm)":
                    float(row["rainfall"])
                    if row is not None else None,
                "Sensors":
                    int(row["sensors"]) if row is not None else 0,
                "Unread alerts": int(unread),
            })

        if district_rows:

            district_table = pd.DataFrame(
                district_rows
            ).sort_values(
                "Flood probability (%)",
                ascending=False,
                na_position="last"
            ).reset_index(drop=True)

            display_table = district_table.assign(**{
                "Risk": district_table["Risk level"].map(risk_label)
            })[[
                "Risk", "District", "Division",
                "Flood probability (%)", "Water level (m)",
                "Rainfall (mm)", "Sensors", "Unread alerts"
            ]]

            st.dataframe(
                display_table,
                width="stretch",
                hide_index=True,
                column_config={
                    "Flood probability (%)":
                        st.column_config.ProgressColumn(
                            "Flood probability",
                            min_value=0,
                            max_value=100,
                            format="%.1f%%"
                        ),
                }
            )

            info_col, download_col = st.columns([3, 1])

            with info_col:
                st.caption(
                    f"Showing {len(district_table)} of "
                    f"{len(DISTRICT_NAMES)} districts, highest "
                    f"risk first (worst sensor per district)."
                )

            with download_col:
                st.download_button(
                    "⬇️ Download CSV",
                    data=district_table.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name=(
                        f"district_flood_risk_"
                        f"{datetime.now():%Y%m%d_%H%M}.csv"
                    ),
                    mime="text/csv",
                    width="stretch"
                )

        else:

            st.info("No districts match that search/filter.")

    # --------------------------------------------------------
    # ALERTS
    # --------------------------------------------------------

    with tab_alerts:

        nationwide_unread = get_total_unread_emergency_alert_count()

        a1, a2, a3 = st.columns([1, 1, 1])

        a1.metric(
            "Alert events (24h)", count_alert_events_since(24)
        )

        a2.metric("Unread alert copies", nationwide_unread)

        with a3:
            st.write("")
            if st.button(
                "🧹 Mark all read (nationwide)",
                width="stretch",
                disabled=(nationwide_unread == 0),
                key="sh_mark_all_read"
            ):
                cleared = mark_all_emergency_alerts_read_nationwide()
                st.success(
                    f"Cleared {cleared} unread alert notifications."
                )
                st.rerun()

        st.caption(
            "Each alert is delivered to every responsible account, "
            "so unread copies are always higher than the number of "
            "alert events."
        )

        st.subheader("Recent alert events")

        events = get_recent_alert_events(25)

        if events.empty:

            st.info("No alerts have been sent yet.")

        else:

            level_icon = {"CRITICAL": "🔴", "HIGH": "🟠"}

            st.dataframe(
                pd.DataFrame({
                    "Time": events["created_at"],
                    "Level": events["level"].map(
                        lambda lv: f"{level_icon.get(lv, '⚪')} {lv}"
                    ),
                    "Alert": events["title"],
                    "Division": events["division"].fillna("—"),
                    "Unread": [
                        f"{u} of {r}"
                        for u, r in zip(
                            events["unread"], events["recipients"]
                        )
                    ],
                }),
                width="stretch",
                hide_index=True
            )

        st.subheader("Unread alerts by division")

        unread_division_table = pd.DataFrame(
            [
                {"Division": division, "Unread alert copies": count}
                for division, count in
                unread_alert_copies_by_division(
                    get_unread_emergency_alert_counts_by_recipient()
                ).items()
            ]
        ).sort_values("Unread alert copies", ascending=False)

        st.dataframe(
            unread_division_table,
            width="stretch",
            hide_index=True
        )

        with st.expander("📣 Send an emergency alert"):

            bc_scope = st.selectbox(
                "Send to",
                ["All divisions"] + BD_DIVISIONS,
                key="sh_bc_scope"
            )

            bc_level = st.selectbox(
                "Level",
                ["CRITICAL", "HIGH"],
                key="sh_bc_level"
            )

            bc_districts = st.checkbox(
                "Also alert district-level accounts",
                value=True,
                key="sh_bc_districts"
            )

            bc_title = st.text_input(
                "Alert title",
                key="sh_bc_title"
            )

            bc_message = st.text_area(
                "Alert message",
                key="sh_bc_message"
            )

            bc_confirm = st.checkbox(
                "I confirm this alert should be sent now",
                key="sh_bc_confirm"
            )

            if st.button(
                "🚨 Send alert",
                key="sh_bc_send",
                width="stretch"
            ):

                if not bc_title.strip() or not bc_message.strip():

                    st.warning(
                        "Please enter both a title and a message."
                    )

                elif not bc_confirm:

                    st.warning(
                        "Tick the confirmation box to send."
                    )

                else:

                    target_divisions = (
                        BD_DIVISIONS
                        if bc_scope == "All divisions"
                        else [bc_scope]
                    )

                    recipient_keys = broadcast_recipient_keys(
                        target_divisions, bc_districts
                    )

                    create_emergency_alert(
                        st.session_state.username,
                        recipient_keys,
                        bc_title.strip(),
                        bc_message.strip(),
                        level=bc_level,
                        target_division=(
                            None if bc_scope == "All divisions"
                            else bc_scope
                        )
                    )

                    st.success(
                        f"🚨 Alert sent to {len(recipient_keys)} "
                        f"accounts ({bc_scope})."
                    )

    # --------------------------------------------------------
    # MESSAGES
    # --------------------------------------------------------
    # Reuses the existing send_email() / email_center()
    # machinery — no separate messaging system was built.
    # --------------------------------------------------------

    with tab_messages:

        tab_one, tab_all, tab_mailbox = st.tabs(
            [
                "✉️ Message One Admin",
                "📢 Message All Admins",
                "📬 My Mailbox"
            ]
        )

        with tab_one:

            target_division = st.selectbox(
                "Division",
                BD_DIVISIONS,
                key="sh_target_division"
            )

            one_subject = st.text_input(
                "Subject",
                key="sh_one_subject"
            )

            one_message = st.text_area(
                "Message",
                key="sh_one_message"
            )

            if st.button(
                "📨 Send to Selected Division Admin",
                width="stretch"
            ):

                if one_message.strip():

                    send_email(
                        "System Handler",
                        mailbox_key("Division Admin", target_division),
                        one_subject or "(No subject)",
                        one_message
                    )

                    st.success(
                        f"✅ Message sent to {target_division} "
                        f"Division Admin."
                    )

                else:

                    st.warning(
                        "Please enter a message before sending."
                    )

        with tab_all:

            all_subject = st.text_input(
                "Subject",
                key="sh_all_subject"
            )

            all_message = st.text_area(
                "Message",
                key="sh_all_message"
            )

            if st.button(
                "📢 Send to ALL Division Admins",
                width="stretch"
            ):

                if all_message.strip():

                    for division in BD_DIVISIONS:

                        send_email(
                            "System Handler",
                            mailbox_key("Division Admin", division),
                            all_subject or "(No subject)",
                            all_message
                        )

                    st.success(
                        "✅ Message sent to all 8 Division Admins."
                    )

                else:

                    st.warning(
                        "Please enter a message before sending."
                    )

        with tab_mailbox:

            email_center(
                "System Handler",
                show_compose=True,
                recipients_override=[
                    mailbox_key("Division Admin", division)
                    for division in BD_DIVISIONS
                ]
            )

    # --------------------------------------------------------
    # SENSORS & DATA (nationwide, no scope restriction)
    # --------------------------------------------------------

    with tab_data:

        sensor_and_dataset_management_section(
            scope_locations=None,
            scope_label="the nation",
            key_prefix="sh"
        )
