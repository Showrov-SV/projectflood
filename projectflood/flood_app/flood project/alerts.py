"""Emergency alert system: creating alerts, automatic Severe-risk alerts
(with cooldown) and unread/read tracking."""

import pandas as pd
from datetime import datetime

from flood_app.config import (
    AUTO_ALERT_COOLDOWN_MINUTES,
    AUTO_ALERT_MIN_RISK_LEVELS,
)
from flood_app.database import get_connection
from flood_app.geography import (
    get_districts_for_location,
    get_division_for_location,
)
from flood_app.mail_roles import mailbox_key


def create_emergency_alert(
    sender,
    recipient_keys,
    title,
    message,
    level="CRITICAL",
    target_division=None,
    target_area=None
):
    """
    Creates ONE emergency_alerts record and delivers it to every
    key in recipient_keys by inserting one unread
    emergency_alert_reads row per recipient — each of which can
    later be marked read completely independently of the
    others. recipient_keys is a list of mailbox_key() strings,
    e.g. ["Police", "Fire Service", "Hospital"] for the
    Administrator's global siren, or
    ["Dhaka Police", "Dhaka Fire Service", "Dhaka Hospital"] for
    a Division Admin's own siren.
    """

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()

    cursor = conn.execute(
        """
        INSERT INTO emergency_alerts(
            sender, target_role, target_division, target_area,
            title, message, level, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sender,
            ", ".join(recipient_keys),
            target_division,
            target_area,
            title,
            message,
            level,
            timestamp
        )
    )

    alert_id = cursor.lastrowid

    for recipient_key in recipient_keys:

        conn.execute(
            """
            INSERT INTO emergency_alert_reads(
                alert_id, recipient_key, is_read, read_at
            )
            VALUES (?, ?, 0, NULL)
            """,
            (alert_id, recipient_key)
        )

    conn.commit()
    conn.close()


def _auto_alert_cooldown_ok(location):
    """True if this location is NOT still in its post-alert
    cooldown window (i.e. it's OK to send another automatic
    alert for it right now)."""

    conn = get_connection()

    row = conn.execute(
        """
        SELECT last_alert_at
        FROM auto_alert_log
        WHERE location = ?
        """,
        (location,)
    ).fetchone()

    conn.close()

    if row is None or not row[0]:
        return True

    last_alert_at = datetime.strptime(
        row[0],
        "%Y-%m-%d %H:%M:%S"
    )

    elapsed_minutes = (
        datetime.now() - last_alert_at
    ).total_seconds() / 60

    return elapsed_minutes >= AUTO_ALERT_COOLDOWN_MINUTES


def _record_auto_alert_sent(location):

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO auto_alert_log(location, last_alert_at)
        VALUES (?, ?)
        ON CONFLICT(location)
        DO UPDATE SET last_alert_at = excluded.last_alert_at
        """,
        (location, timestamp)
    )

    conn.commit()
    conn.close()


def check_and_send_auto_alerts(readings):
    """
    Scans a readings DataFrame (as produced by
    generate_all_sensor_data()) and automatically fires an
    emergency alert — via the same create_emergency_alert() /
    mailbox / siren system any manual alert uses, nothing
    separate — for every location whose REAL hybrid-model
    flood_probability has reached Severe risk (>= 90%, per
    classify_risk()) and isn't still in its per-location
    cooldown window. Every national/legacy Police, Fire Service
    and Hospital account always receives it; if the location
    also belongs to one of the 8 divisions, that division's own
    Police/Fire Service/Hospital/Municipality/Division Admin
    receive an additional, identically-timed copy, and every
    District Admin/District Police/District Fire Service/
    District Municipality whose district covers the location
    receive one too — never any unrelated division or district.
    Called automatically from generate_all_sensor_data() — no
    admin interaction needed.
    """

    if readings is None or readings.empty:
        return

    elevated = readings[
        readings["risk_level"].isin(AUTO_ALERT_MIN_RISK_LEVELS)
    ]

    for _, row in elevated.iterrows():

        location = str(row["location"]).strip()

        if not location:
            continue

        if not _auto_alert_cooldown_ok(location):
            continue

        division = get_division_for_location(location)

        # National fallback recipient. The original bare "Police"
        # / "Fire Service" / "Hospital" national accounts were
        # removed from this app (System Handler is now the sole
        # national-level account) — sending alerts to those keys
        # would create unread rows that literally no account can
        # ever read or clear, which is exactly what had piled up
        # to hundreds of orphaned rows before this fix.
        recipient_keys = ["System Handler"]

        if division:

            recipient_keys += [
                mailbox_key(org_role, division)
                for org_role in
                ("Police", "Fire Service", "Hospital", "Municipality")
            ]

            recipient_keys.append(
                mailbox_key("Division Admin", division)
            )

        # Also notify every District Admin, District Police,
        # District Fire Service and District Municipality
        # whose district includes this location (there can be
        # more than one — e.g. both "Mymensingh" and "Jamalpur"
        # district orgs cover the area "Jamalpur").
        for matching_district in get_districts_for_location(
            location
        ):

            recipient_keys.append(
                mailbox_key("District Admin", matching_district)
            )

            recipient_keys += [
                mailbox_key(org_role, matching_district)
                for org_role in (
                    "District Police", "District Fire Service",
                    "District Municipality"
                )
            ]

        risk_level = row["risk_level"]

        timestamp = row.get("timestamp", "")

        predicted_water_level = row.get("predicted_water_level")

        water_level_line = (
            f" Predicted water level: "
            f"{predicted_water_level} m."
            if predicted_water_level is not None
            and not pd.isna(predicted_water_level)
            else ""
        )

        create_emergency_alert(
            "System (Auto-Alert)",
            recipient_keys,
            f"SEVERE Flood Alert — {location}",
            f"Location: {location}. Flood probability has "
            f"automatically reached {risk_level.upper()} RISK "
            f"at {row['flood_probability']}%.{water_level_line} "
            f"Recorded at {timestamp}. Immediate response may "
            f"be required.",
            level="CRITICAL",
            target_division=division,
            target_area=location
        )


        _record_auto_alert_sent(location)


def get_unread_emergency_alerts(recipient_key, limit=None):
    """
    All currently-unread alerts for this ONE recipient key, most
    recent first. `limit`, when given, is applied as a SQL LIMIT
    — SQLite only reads that many rows off the index rather than
    every unread row being pulled into Python and then sliced,
    which matters a lot for an account with a large backlog (one
    was found with 400+ unread alerts). Callers that need the
    TRUE total count should use get_unread_emergency_alert_count()
    instead/in addition — this function's row count is NOT the
    same as the true unread count once `limit` is used.
    """

    conn = get_connection()

    query = """
        SELECT
            emergency_alerts.id,
            emergency_alerts.sender,
            emergency_alerts.target_division,
            emergency_alerts.target_area,
            emergency_alerts.title,
            emergency_alerts.message,
            emergency_alerts.level,
            emergency_alerts.created_at
        FROM emergency_alert_reads
        JOIN emergency_alerts
            ON emergency_alerts.id = emergency_alert_reads.alert_id
        WHERE emergency_alert_reads.recipient_key = ?
        AND emergency_alert_reads.is_read = 0
        ORDER BY emergency_alerts.id DESC
    """

    params = [recipient_key]

    if limit is not None:
        query += " LIMIT ?"
        params.append(int(limit))

    df = pd.read_sql_query(
        query,
        conn,
        params=params
    )

    conn.close()

    return df


def get_unread_emergency_alert_count(recipient_key):

    conn = get_connection()

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM emergency_alert_reads
        WHERE recipient_key = ?
        AND is_read = 0
        """,
        (recipient_key,)
    ).fetchone()[0]

    conn.close()

    return count


def get_unread_emergency_alert_counts_by_recipient():
    """
    Unread alert count for EVERY mailbox in ONE query, as a
    {recipient_key: count} dict. Use this instead of calling
    get_unread_emergency_alert_count() in a loop over many
    accounts (that opens one DB connection per account).
    """

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT recipient_key, COUNT(*)
            FROM emergency_alert_reads
            WHERE is_read = 0
            GROUP BY recipient_key
            """
        ).fetchall()
    finally:
        conn.close()

    return dict(rows)


def mark_emergency_alerts_read(recipient_key):
    """
    Marks ALL of this recipient's currently-unread alerts read,
    in one call — satisfies "clearly handle all unread alerts"
    when several have arrived. Only rows for THIS exact
    recipient_key are touched; every other recipient (including
    other divisions' copies of the very same broadcast alert)
    is completely unaffected.
    """

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()

    conn.execute(
        """
        UPDATE emergency_alert_reads
        SET is_read = 1, read_at = ?
        WHERE recipient_key = ?
        AND is_read = 0
        """,
        (timestamp, recipient_key)
    )

    conn.commit()
    conn.close()


def mark_all_emergency_alerts_read_nationwide():
    """
    System Handler-only bulk action: marks EVERY currently
    unread alert, for every recipient nationwide, as read in one
    single UPDATE — not a loop over mark_emergency_alerts_read()
    per mailbox, since with 64 districts x 4 roles plus 8
    divisions x 5 roles there can be 300+ mailboxes to clear.
    Returns how many rows were actually cleared, so the caller
    can show a meaningful confirmation message. This does not
    change auto-alert behavior or the cooldown at all — it only
    clears the read/unread flag operators already see, exactly
    as if every one of them had opened their own inbox and
    clicked "mark all as read".
    """

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()

    cleared = conn.execute(
        """
        SELECT COUNT(*) FROM emergency_alert_reads
        WHERE is_read = 0
        """
    ).fetchone()[0]

    conn.execute(
        """
        UPDATE emergency_alert_reads
        SET is_read = 1, read_at = ?
        WHERE is_read = 0
        """,
        (timestamp,)
    )

    conn.commit()
    conn.close()

    return cleared


def get_total_unread_emergency_alert_count():
    """
    Total unread alert rows across EVERY mailbox nationwide, in
    one query — used by System Handler's top-level "nationwide
    unread" summary so it doesn't need to loop over 300+
    individual mailbox keys just to show one number.
    """

    conn = get_connection()

    count = conn.execute(
        """
        SELECT COUNT(*) FROM emergency_alert_reads
        WHERE is_read = 0
        """
    ).fetchone()[0]

    conn.close()

    return count
