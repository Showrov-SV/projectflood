import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import hashlib
from datetime import datetime, timedelta
import random
import smtplib
import secrets as pysecrets
from email.mime.text import MIMEText
from streamlit_cookies_controller import CookieController
import hybrid_model


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Flood Monitoring & Prediction System",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# DATABASE
# ============================================================

DB_NAME = "flood_monitoring.db"


def get_connection():
    return sqlite3.connect(
        DB_NAME,
        check_same_thread=False
    )


# ============================================================
# BANGLADESH DIVISION + DISTRICT (ZILA) HIERARCHY
# ============================================================
# Defined here (ahead of init_database(), which seeds accounts
# using these) rather than down near LOCATION_COORDINATES,
# purely because init_database() runs at import time, before
# the rest of the module has executed.
#
# DISTRICT_COORDINATES gives every one of the 64 real
# districts (zilas) of Bangladesh a (lat, lon) — grouped under
# its real parent division, not the old placeholder
# neighborhoods/areas this app used before. DIVISION_AREAS below
# is built directly from this, so "area" now means "real
# district" everywhere in the app: monitoring, prediction,
# sensors, the map, and account scoping are all district-level.
# Coordinates are each district's headquarters town
# (zila sadar), approximate to a few km — accurate enough for
# this app's map/visualization purposes, not surveying-grade.
# ============================================================

DISTRICT_COORDINATES = {

    # ---- Dhaka Division (13 districts) ----
    "Dhaka": (23.8103, 90.4125),
    "Faridpur": (23.6070, 89.8429),
    "Gazipur": (23.9999, 90.4203),
    "Gopalganj": (23.0050, 89.8266),
    "Kishoreganj": (24.4262, 90.9799),
    "Madaripur": (23.1642, 90.1897),
    "Manikganj": (23.8644, 90.0038),
    "Munshiganj": (23.5422, 90.5305),
    "Narayanganj": (23.6238, 90.5000),
    "Narsingdi": (23.9322, 90.7150),
    "Rajbari": (23.7574, 89.6444),
    "Shariatpur": (23.2423, 90.4348),
    "Tangail": (24.2513, 89.9167),

    # ---- Chattogram Division (11 districts) ----
    "Bandarban": (22.1953, 92.2184),
    "Brahmanbaria": (23.9571, 91.1119),
    "Chandpur": (23.2333, 90.6500),
    "Chattogram": (22.3569, 91.7832),
    "Cumilla": (23.4607, 91.1809),
    "Cox's Bazar": (21.4272, 92.0058),
    "Feni": (23.0159, 91.3976),
    "Khagrachhari": (23.1193, 91.9847),
    "Lakshmipur": (22.9440, 90.8285),
    "Noakhali": (22.8696, 91.0995),
    "Rangamati": (22.6533, 92.1729),

    # ---- Rajshahi Division (8 districts) ----
    "Bogura": (24.8465, 89.3773),
    "Joypurhat": (25.1023, 89.0227),
    "Naogaon": (24.7936, 88.9318),
    "Natore": (24.4206, 88.9862),
    "Chapainawabganj": (24.5965, 88.2775),
    "Pabna": (24.0064, 89.2372),
    "Rajshahi": (24.3745, 88.6042),
    "Sirajganj": (24.4533, 89.7006),

    # ---- Khulna Division (10 districts) ----
    "Bagerhat": (22.6602, 89.7895),
    "Chuadanga": (23.6402, 88.8410),
    "Jashore": (23.1667, 89.2167),
    "Jhenaidah": (23.5448, 89.1539),
    "Khulna": (22.8456, 89.5403),
    "Kushtia": (23.9013, 89.1220),
    "Magura": (23.4873, 89.4198),
    "Meherpur": (23.7622, 88.6318),
    "Narail": (23.1725, 89.5126),
    "Satkhira": (22.7085, 89.0705),

    # ---- Barishal Division (6 districts) ----
    "Barguna": (22.0953, 90.1121),
    "Barishal": (22.7010, 90.3535),
    "Bhola": (22.6859, 90.6482),
    "Jhalokati": (22.6406, 90.1987),
    "Patuakhali": (22.3596, 90.3298),
    "Pirojpur": (22.5841, 89.9720),

    # ---- Sylhet Division (4 districts) ----
    "Habiganj": (24.3745, 91.4156),
    "Moulvibazar": (24.4829, 91.7774),
    "Sunamganj": (25.0658, 91.3950),
    "Sylhet": (24.8949, 91.8687),

    # ---- Rangpur Division (8 districts) ----
    "Dinajpur": (25.6279, 88.6332),
    "Gaibandha": (25.3288, 89.5285),
    "Kurigram": (25.8072, 89.6297),
    "Lalmonirhat": (25.9923, 89.2847),
    "Nilphamari": (25.9317, 88.8560),
    "Panchagarh": (26.3411, 88.5541),
    "Rangpur": (25.7439, 89.2752),
    "Thakurgaon": (26.0336, 88.4616),

    # ---- Mymensingh Division (4 districts) ----
    "Jamalpur": (24.9375, 89.9377),
    "Mymensingh": (24.7471, 90.4203),
    "Netrokona": (24.8710, 90.7276),
    "Sherpur": (25.0204, 90.0153)

}

BD_DIVISIONS = [
    "Dhaka",
    "Chattogram",
    "Rajshahi",
    "Khulna",
    "Barishal",
    "Sylhet",
    "Rangpur",
    "Mymensingh"
]

# Which real districts belong to each division — the single
# source of truth for the whole app's division-level scoping
# (Division Admin/Police/Fire Service/Hospital/Municipality all
# see exactly these districts and nothing else).
DIVISION_AREAS = {

    "Dhaka": [
        "Dhaka", "Faridpur", "Gazipur", "Gopalganj",
        "Kishoreganj", "Madaripur", "Manikganj", "Munshiganj",
        "Narayanganj", "Narsingdi", "Rajbari", "Shariatpur",
        "Tangail"
    ],

    "Chattogram": [
        "Bandarban", "Brahmanbaria", "Chandpur", "Chattogram",
        "Cumilla", "Cox's Bazar", "Feni", "Khagrachhari",
        "Lakshmipur", "Noakhali", "Rangamati"
    ],

    "Rajshahi": [
        "Bogura", "Joypurhat", "Naogaon", "Natore",
        "Chapainawabganj", "Pabna", "Rajshahi", "Sirajganj"
    ],

    "Khulna": [
        "Bagerhat", "Chuadanga", "Jashore", "Jhenaidah",
        "Khulna", "Kushtia", "Magura", "Meherpur", "Narail",
        "Satkhira"
    ],

    "Barishal": [
        "Barguna", "Barishal", "Bhola", "Jhalokati",
        "Patuakhali", "Pirojpur"
    ],

    "Sylhet": [
        "Habiganj", "Moulvibazar", "Sunamganj", "Sylhet"
    ],

    "Rangpur": [
        "Dinajpur", "Gaibandha", "Kurigram", "Lalmonirhat",
        "Nilphamari", "Panchagarh", "Rangpur", "Thakurgaon"
    ],

    "Mymensingh": [
        "Jamalpur", "Mymensingh", "Netrokona", "Sherpur"
    ]

}

# Reverse lookup: district name -> its division, e.g.
# "Gazipur" -> "Dhaka". Used by the automatic emergency alert
# system so an auto-alert for one district also reaches that
# district's Division Admin + division-specific Police/Fire
# Service/Hospital/Municipality, not just the national legacy
# accounts.
LOCATION_TO_DIVISION = {
    area: division
    for division, areas in DIVISION_AREAS.items()
    for area in areas
}

# Case/whitespace-insensitive version of the same lookup —
# sensor locations can be freely typed (Admin's "Register New
# Sensor" form is a plain text field, not a dropdown), so a
# location entered as "dhaka" or " Dhaka " must still match
# "Dhaka" here. Built once at import time from
# LOCATION_TO_DIVISION above.
_LOCATION_TO_DIVISION_NORMALIZED = {
    area.strip().lower(): division
    for area, division in LOCATION_TO_DIVISION.items()
}


def get_division_for_location(location):
    """
    Case/whitespace-insensitive lookup of which division (if
    any) a district belongs to. Returns None if the location
    isn't one of the 64 real districts (e.g. a custom "➕ Other"
    location entered by hand).
    """

    if not location:
        return None

    return _LOCATION_TO_DIVISION_NORMALIZED.get(
        str(location).strip().lower()
    )


# ============================================================
# DISTRICT ADMIN HIERARCHY
# ============================================================
# A separate, parallel admin tier to Division Admin — a District
# Admin (and District Police/Fire Service/Municipality) gets the
# same dashboard capabilities as their division-level
# counterpart, but scoped to exactly ONE real district instead
# of that district's whole division.
#
# DISTRICT_NAMES is now every one of the 64 real districts (zilas)
# — one set of District Admin/Police/Fire Service/Municipality
# accounts per district, 256 accounts total. DISTRICT_AREAS is
# an identity mapping (a district's only "area" is itself) since
# districts are already the finest granularity this app
# monitors — there's no further sub-district breakdown.
# ============================================================

DISTRICT_NAMES = [
    district
    for division_districts in DIVISION_AREAS.values()
    for district in division_districts
]

DISTRICT_AREAS = {
    district_name: [district_name]
    for district_name in DISTRICT_NAMES
}


def get_district_areas(district):
    """Every area a District Admin for this district may work
    with — always just [district] itself, since districts are
    this app's finest monitoring granularity. Returns [] for an
    unrecognized district — callers must treat that as "no areas
    available", never as "unrestricted"."""

    return DISTRICT_AREAS.get(district, [])


def get_districts_for_location(location):
    """
    Every district (there can be more than one in principle,
    though with the real 64-district model there's normally
    exactly one) whose area list contains this location.
    Case/whitespace-insensitive. Used by the automatic emergency
    alert system so a District Admin is notified when their own
    district crosses the alert threshold.
    """

    if not location:
        return []

    normalized = str(location).strip().lower()

    return [
        district
        for district, areas in DISTRICT_AREAS.items()
        if normalized in {a.strip().lower() for a in areas}
    ]


def slugify_name(name):
    """
    Turns a display name into a clean, login-friendly username
    fragment: lowercase, spaces/apostrophes/punctuation removed
    (kept as nothing, not underscores, so "Cox's Bazar" becomes
    "coxsbazar" rather than a username containing a literal
    space or quote character — either of which would still work
    as a SQLite value, but makes for an awkward, error-prone
    login username). Used for every one of the 64 real
    districts' seeded usernames.
    """

    return "".join(
        character
        for character in str(name).lower()
        if character.isalnum()
    )


def init_database():

    conn = get_connection()
    cursor = conn.cursor()

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    """)

    # --------------------------------------------------------
    # SAFE MIGRATION: hierarchical administration columns
    # --------------------------------------------------------
    # Adds `division` and `area` to the existing users table so
    # the same table can hold both the original global accounts
    # (Administrator / Police / Fire Service / Hospital /
    # Municipality — division and area stay NULL for these,
    # exactly as before) AND the newer hierarchical accounts
    # (System Handler, Division Admins, division-specific
    # Police/Fire Service/Hospital). Nothing about the existing
    # rows or the `role` column changes.
    # --------------------------------------------------------

    existing_user_columns = {
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    }

    for column_name in ("division", "area", "district"):

        if column_name not in existing_user_columns:

            cursor.execute(
                f"ALTER TABLE users ADD COLUMN {column_name} TEXT"
            )

    # --------------------------------------------------------
    # SENSORS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sensors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sensor_id TEXT UNIQUE,
            location TEXT,
            latitude REAL,
            longitude REAL,
            sensor_type TEXT,
            status TEXT
        )
    """)

    # --------------------------------------------------------
    # SENSOR READINGS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sensor_id TEXT,
            timestamp TEXT,
            water_level REAL,
            rainfall REAL,
            river_flow REAL,
            temperature REAL,
            humidity REAL,
            soil_moisture REAL,
            wind_speed REAL,
            flood_probability REAL,
            risk_level TEXT
        )
    """)

    # --------------------------------------------------------
    # EMERGENCY NOTIFICATIONS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emergency_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_role TEXT,
            message TEXT,
            timestamp TEXT,
            status TEXT
        )
    """)

    # --------------------------------------------------------
    # EMAIL SERVER LOG
    # --------------------------------------------------------
    # Simulates an outgoing mail server: every emergency
    # notification is also dispatched as an "email" so the
    # system can demonstrate that the mail server is working.
    #
    # This SAME table now also powers proper two-way,
    # user-to-user email between Admin, Police, Fire Service,
    # Hospital and Municipality (see the ALTER TABLE / migration
    # block right below). There is only ONE email system in
    # this app — this table — it has just been extended with
    # the columns needed for a real Inbox/Sent/Bin per
    # organization, instead of only Admin -> Org broadcasts.
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            recipient TEXT,
            target_role TEXT,
            subject TEXT,
            body TEXT,
            timestamp TEXT,
            status TEXT
        )
    """)

    # --------------------------------------------------------
    # SAFE MIGRATION: extend email_log for two-way mail
    # --------------------------------------------------------
    # Adds the columns needed to turn the existing email_log
    # table into a proper per-organization mailbox:
    #   sender_role  - which role actually sent this email
    #                  (previously always assumed "Administrator")
    #   owner_role   - whose mailbox this ROW belongs to
    #                  (each email is stored as one row for the
    #                  recipient's Inbox and one row for the
    #                  sender's Sent — see send_email())
    #   folder       - 'inbox' or 'sent'
    #   is_read      - read/unread flag for Inbox rows
    #   in_bin       - whether this user has moved their own
    #                  copy to their own Bin
    #   deleted_at   - when it was moved to the Bin
    #
    # Existing rows/columns are never dropped. ALTER TABLE ADD
    # COLUMN is used (wrapped so re-running it on an
    # already-migrated database is a harmless no-op), and
    # existing historical emails are migrated in place so
    # nothing already sent is lost.
    # --------------------------------------------------------

    existing_columns = {
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(email_log)"
        ).fetchall()
    }

    new_email_log_columns = {
        "sender_role": "TEXT",
        "owner_role": "TEXT",
        "folder": "TEXT",
        "is_read": "INTEGER DEFAULT 0",
        "in_bin": "INTEGER DEFAULT 0",
        "deleted_at": "TEXT"
    }

    for column_name, column_type in new_email_log_columns.items():

        if column_name not in existing_columns:

            cursor.execute(
                f"ALTER TABLE email_log "
                f"ADD COLUMN {column_name} {column_type}"
            )

    # One-time backfill of pre-existing rows (created before
    # this migration) into the new per-owner mailbox model.
    # Every legacy row was an Admin -> Org broadcast, so it
    # becomes that org's Inbox copy, and a matching Sent copy
    # is created for Administrator so Admin's own Sent/mailbox
    # history is complete too. This only ever runs for rows
    # that haven't been migrated yet (owner_role IS NULL), so
    # it is safe to run on every app start.

    legacy_rows = cursor.execute(
        """
        SELECT id, sender, recipient, target_role,
               subject, body, timestamp, status
        FROM email_log
        WHERE owner_role IS NULL
        """
    ).fetchall()

    for (
        legacy_id, legacy_sender, legacy_recipient,
        legacy_target_role, legacy_subject, legacy_body,
        legacy_timestamp, legacy_status
    ) in legacy_rows:

        # Create Administrator's Sent copy of this legacy email.
        cursor.execute(
            """
            INSERT INTO email_log(
                sender, recipient, target_role,
                subject, body, timestamp, status,
                sender_role, owner_role, folder,
                is_read, in_bin
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                legacy_sender, legacy_recipient, legacy_target_role,
                legacy_subject, legacy_body, legacy_timestamp,
                legacy_status, "Administrator", "Administrator",
                "sent", 1, 0
            )
        )

        # Turn the original row into that org's Inbox copy.
        cursor.execute(
            """
            UPDATE email_log
            SET sender_role = ?,
                owner_role = ?,
                folder = 'inbox',
                is_read = 1,
                in_bin = 0
            WHERE id = ?
            """,
            (
                "Administrator", legacy_target_role, legacy_id
            )
        )

    # --------------------------------------------------------
    # ADMIN 2FA SECURITY STATE
    # --------------------------------------------------------
    # Tracks, PER ADMIN USERNAME, everything needed for the
    # email-based two-factor login flow. This lives in the
    # database (not st.session_state) specifically so that a
    # page refresh cannot be used to reset a failed-password
    # counter, clear a 15-minute lockout, or restart the OTP
    # attempt counter early. It is completely separate from the
    # existing simulated internal `email_log` mail system below
    # and is only ever read/written by the admin-2FA helper
    # functions.
    #
    #   failed_attempts   - consecutive wrong-password count
    #   locked_until       - ISO timestamp the password lock
    #                         expires, or NULL if not locked
    #   otp_hash            - SHA-256 hash of the current valid
    #                         OTP, or NULL if none is pending
    #                         (the plaintext OTP is never stored)
    #   otp_expires_at       - ISO timestamp the current OTP
    #                         expires
    #   otp_attempts        - consecutive wrong-OTP count for
    #                         the current OTP
    #   otp_last_sent_at    - ISO timestamp of the last OTP
    #                         email dispatch (drives the resend
    #                         cooldown)
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_auth_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            failed_attempts INTEGER DEFAULT 0,
            locked_until TEXT,
            otp_hash TEXT,
            otp_expires_at TEXT,
            otp_attempts INTEGER DEFAULT 0,
            otp_last_sent_at TEXT
        )
        """
    )

    # --------------------------------------------------------
    # ADMIN TRUSTED DEVICES ("Remember this device")
    # --------------------------------------------------------
    # Lets an administrator skip the OTP step on a device they
    # have already verified once. A random token is issued to
    # the browser as a real cookie (via streamlit-cookies-
    # controller) when the admin opts in on the OTP screen; only
    # a SHA-256 hash of that token is ever stored here, never
    # the raw token, mirroring how passwords/OTPs are hashed
    # elsewhere in this app. The password step is NEVER skipped
    # by a trusted device — only the OTP step is.
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_trusted_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            token_hash TEXT UNIQUE,
            created_at TEXT,
            expires_at TEXT
        )
        """
    )

    # --------------------------------------------------------
    # EMERGENCY ALERTS (blinking + sound alert system)
    # --------------------------------------------------------
    # Separate from the pre-existing `emergency_notifications`
    # table (which still works exactly as before, unchanged).
    # This is the NEW alert system: one row per alert created,
    # plus one independent read-state row per RECIPIENT
    # mailbox key (see mailbox_key()) in emergency_alert_reads
    # — e.g. "Dhaka Police" and "Dhaka Hospital" each get their
    # own row and can be marked read completely independently
    # of one another, and of every other recipient.
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS emergency_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            target_role TEXT,
            target_division TEXT,
            target_area TEXT,
            title TEXT,
            message TEXT,
            level TEXT,
            created_at TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS emergency_alert_reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            recipient_key TEXT,
            is_read INTEGER DEFAULT 0,
            read_at TEXT
        )
        """
    )

    # --------------------------------------------------------
    # PERFORMANCE INDEXES
    # --------------------------------------------------------
    # This is the "transfer load to the database" fix: these
    # tables are now queried on essentially every dashboard
    # render (sidebar unread counts, the emergency alert banner,
    # legacy notification lookups) and have grown into the
    # thousands of rows — without an index, SQLite has to scan
    # every row of a table for each of those lookups. Indexes
    # don't change what any query returns, only how fast SQLite
    # can find the matching rows, so this is a pure speed
    # improvement with zero behavior change and nothing to
    # migrate or lose.
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_reads_recipient_unread
        ON emergency_alert_reads(recipient_key, is_read)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_reads_alert_id
        ON emergency_alert_reads(alert_id)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notifications_role_status
        ON emergency_notifications(target_role, status)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_email_log_owner_folder
        ON email_log(owner_role, folder, in_bin)
        """
    )

    # --------------------------------------------------------
    # ONE-TIME CLEANUP: orphaned national alert recipients
    # --------------------------------------------------------
    # The original bare "Police" / "Fire Service" / "Hospital"
    # national accounts were removed (System Handler is now the
    # sole national-level account), but the automatic alert
    # system kept fanning out to those exact mailbox keys — no
    # account can ever log in and read/clear them, so they just
    # accumulated forever (469 / 416 / 406 unread rows found on
    # this database). Deleting only these specific orphaned
    # emergency_alert_reads rows is safe: no current account
    # uses these keys, so nothing that can actually be read is
    # touched, and the parent emergency_alerts rows themselves
    # are untouched (other recipients of the same alert, e.g.
    # "Dhaka Police", keep their own read state exactly as
    # before). Idempotent — deletes 0 rows on every run after
    # the first.
    # --------------------------------------------------------

    cursor.execute(
        """
        DELETE FROM emergency_alert_reads
        WHERE recipient_key IN ('Police', 'Fire Service', 'Hospital')
        """
    )

    # --------------------------------------------------------
    # AUTOMATIC EMERGENCY ALERTS
    # --------------------------------------------------------
    # One row per location that has ever triggered an automatic
    # alert, recording when it last fired — this is what lets
    # the auto-alert system debounce itself: since the
    # simulation re-randomizes every location's reading on every
    # rerun, a location sitting at High/Severe risk would
    # otherwise re-trigger an alert on every single rerun. A
    # cooldown per location (AUTO_ALERT_COOLDOWN_MINUTES) keeps
    # that from turning into spam while still firing promptly
    # the first time a location crosses into High/Severe risk,
    # and again after the cooldown if it's still (or newly)
    # elevated.
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS auto_alert_log (
            location TEXT PRIMARY KEY,
            last_alert_at TEXT
        )
        """
    )

    # --------------------------------------------------------
    # LEGACY ACCOUNTS: REMOVED
    # --------------------------------------------------------
    # The original 5 global accounts (admin / hospital / fire /
    # police / municipality) are no longer seeded, and are
    # actively deleted below if they exist in an
    # already-created database — System Handler is now the
    # sole national-level account, and Gmail OTP/2FA applies
    # only to it. This DELETE is scoped to these 5 exact
    # usernames only, so it can never touch a division- or
    # district-specific account that happens to share the same
    # `role` string (e.g. "Dhaka Police").
    # --------------------------------------------------------

    cursor.execute(
        """
        DELETE FROM users
        WHERE username IN (
            'admin', 'hospital', 'fire', 'police', 'municipality'
        )
        """
    )

    default_users = []

    # --------------------------------------------------------
    # HIERARCHICAL ACCOUNTS (System Handler, Division Admins,
    # division-specific Police/Fire Service/Hospital)
    # --------------------------------------------------------
    # These are ADDITIONAL accounts, seeded the same
    # INSERT-OR-IGNORE-on-conflict way as the 5 above, so
    # re-running this on an existing database never touches an
    # already-created account (including if an operator has
    # since changed one of these passwords).
    # --------------------------------------------------------

    default_users.append(
        ("system_handler", "syshandler123", "System Handler", None, None, None)
    )

    for division_name in BD_DIVISIONS:

        division_slug = division_name.lower()

        default_users.append(
            (
                f"{division_slug}_admin",
                f"{division_slug}admin123",
                "Division Admin",
                division_name,
                None,
                None
            )
        )

        default_area = DIVISION_AREAS.get(
            division_name,
            [division_name]
        )[0]

        for org_role, org_slug in (
            ("Police", "police"),
            ("Fire Service", "fire"),
            ("Hospital", "hospital"),
            ("Municipality", "municipality")
        ):

            default_users.append(
                (
                    f"{division_slug}_{org_slug}",
                    f"{division_slug}{org_slug}123",
                    org_role,
                    division_name,
                    default_area,
                    None
                )
            )

    # --------------------------------------------------------
    # DISTRICT ADMINS
    # --------------------------------------------------------
    # A separate, parallel admin tier: Administrator-equivalent
    # capabilities scoped to one district (see DISTRICT_NAMES /
    # DISTRICT_AREAS above). Uses the `district` column, kept
    # entirely separate from `division`/`area` (which remain
    # NULL here) so a District Admin can never be mistaken for a
    # Division Admin or vice versa by any code that checks those
    # columns.
    # --------------------------------------------------------

    for district_name in DISTRICT_NAMES:

        district_slug = slugify_name(district_name)

        default_users.append(
            (
                f"admin_{district_slug}",
                f"{district_slug}district123",
                "District Admin",
                None,
                None,
                district_name
            )
        )

        # ----------------------------------------------------
        # DISTRICT POLICE / FIRE SERVICE / MUNICIPALITY
        # ----------------------------------------------------
        # Every district gets its own Police, Fire Service and
        # Municipality account too (District Admin already
        # existed above) — role strings are prefixed
        # "District " so they can never be confused with a
        # division-specific org account (e.g. "Dhaka Police"
        # vs. "District Police" for Dhaka District), even
        # though both may share the same district/division
        # name.
        # ----------------------------------------------------

        for org_role, org_slug in (
            ("District Police", "police"),
            ("District Fire Service", "fire"),
            ("District Municipality", "municipality")
        ):

            default_users.append(
                (
                    f"{district_slug}_district_{org_slug}",
                    f"{district_slug}district{org_slug}123",
                    org_role,
                    None,
                    None,
                    district_name
                )
            )

    for username, password, role, division, area, district in default_users:

        hashed_password = hashlib.sha256(
            password.encode()
        ).hexdigest()

        try:

            cursor.execute(
                """
                INSERT INTO users(
                    username,
                    password,
                    role,
                    division,
                    area,
                    district
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    hashed_password,
                    role,
                    division,
                    area,
                    district
                )
            )

        except sqlite3.IntegrityError:
            pass

    # --------------------------------------------------------
    # DEFAULT SENSOR LOCATIONS
    # --------------------------------------------------------
    # One default sensor per real district (all 64) — built
    # programmatically from DISTRICT_NAMES/DISTRICT_COORDINATES
    # (the single source of truth for the 64-district model)
    # rather than hand-written per-district, so every district
    # always has at least one sensor and there's no risk of the
    # list drifting out of sync with DIVISION_AREAS. Without
    # this, generate_all_sensor_data() would have zero rows for
    # any district lacking a sensor — exactly what previously
    # caused incorrect "No data" messages. IDs are prefixed
    # "D-" (not "W-", used by this app's old, now-retired,
    # placeholder locations) purely to avoid any collision with
    # sensor rows an already-running deployment may still have
    # under the old naming.
    # --------------------------------------------------------

    sensors = [
        (
            f"D-{index:03d}",
            district_name,
            DISTRICT_COORDINATES[district_name][0],
            DISTRICT_COORDINATES[district_name][1],
            "Water Level",
            "Online"
        )
        for index, district_name in enumerate(DISTRICT_NAMES, start=1)
    ]

    for sensor in sensors:

        try:

            cursor.execute(
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
                sensor
            )

        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()


init_database()


# ============================================================
# LOCATION → COORDINATES MAPPING
# ============================================================
#
# Uploaded datasets do NOT contain location or coordinate
# columns. The user selects a location externally (outside the
# dataset), so this table is the single source of truth for
# where each named location sits on the Live Flood Location Map.
#
# Includes the default registered sensor neighborhoods plus
# major Bangladesh districts/divisions so newly uploaded
# datasets for areas like Jamalpur, Mymensingh, Dhaka, or
# Sylhet can be placed on the map immediately.
# ============================================================

LOCATION_COORDINATES = dict(DISTRICT_COORDINATES)

# --------------------------------------------------------------
# LEGACY ALIASES (backward compatibility only)
# --------------------------------------------------------------
# These are OLD placeholder location names this app used before
# the real 64-district model — no longer part of DIVISION_AREAS
# / DISTRICT_NAMES, so they no longer appear in any selector and
# can't be picked by a scoped account. Kept here only so
# get_location_coordinates() / the map can still resolve
# coordinates for any sensor rows or uploaded datasets an
# existing, already-running deployment created against these
# names before this change, instead of silently failing to plot
# them. Spelling variants (pre-2018 English spellings) are kept
# for the same reason.
# --------------------------------------------------------------

LOCATION_COORDINATES.update({
    "Mirpur": (23.8223, 90.3654),
    "Uttara": (23.8759, 90.3795),
    "Dhanmondi": (23.7461, 90.3742),
    "Tejgaon": (23.7590, 90.3880),
    "Jatrabari": (23.7104, 90.4351),
    "Keraniganj": (23.6800, 90.3300),
    "Savar": (23.8583, 90.2667),
    "Chittagong": (22.3569, 91.7832),
    "Barisal": (22.7010, 90.3535),
    "Comilla": (23.4607, 91.1809),
})


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
# CISCO / EMERGENCY DOMAIN NAMES
# ============================================================
#
# These are kept in one place so they can easily be changed
# according to the Cisco Packet Tracer diagram.
#
# If your Cisco diagram uses different domain names, change
# ONLY these values.
# ============================================================

EMERGENCY_DOMAINS = {

    "Police":
        "flood.com",

    "Fire Service":
        "flood.com",

    "Hospital":
        "flood.com",

    "Municipality":
        "flood.com"

}

# ============================================================
# EMAIL SERVER CONFIGURATION
# ============================================================
#
# Simulated mail server settings. Each emergency organization
# has a mailbox derived from its Cisco domain name above, so
# fixing EMERGENCY_DOMAINS automatically fixes these addresses.
# ============================================================

MAIL_SERVER_NAME = "flood.com Mail Server (SMTP)"

ADMIN_EMAIL = "admin@flood.com"

EMERGENCY_EMAILS = {

    "Police":
        "police@flood.com",

    "Fire Service":
        "fire@flood.com",

    "Hospital":
        "hospital@flood.com",

    "Municipality":
        "municipality@flood.com"

}


# ============================================================
# INTERNAL USER-TO-USER EMAIL: SHARED ROLE CONFIGURATION
# ============================================================
#
# These build directly on top of EMERGENCY_DOMAINS,
# EMERGENCY_EMAILS and ADMIN_EMAIL above (nothing there is
# changed or duplicated) so the internal Inbox/Sent/Compose/Bin
# system stays consistent with the existing SMTP-status panel
# and Cisco domain mapping.
# ============================================================

# Every organization that can hold a mailbox / send & receive
# internal email. "Administrator" is included so Admin has a
# full Inbox/Sent/Bin like everyone else, in addition to the
# existing Admin -> Emergency Organization messaging tool.
#
# LEGACY_MAIL_ROLES is exactly the original 5-role list, kept
# under its own name so the ORIGINAL accounts' Compose-tab
# recipient list (built from this constant at the one call site
# in organization_dashboard()) never changes shape, no matter
# how many hierarchical mailbox keys get added below.
LEGACY_MAIL_ROLES = [
    "Administrator",
    "Police",
    "Fire Service",
    "Hospital",
    "Municipality"
]

# One composite mailbox key per hierarchical account — e.g.
# "Dhaka Police", "Dhaka Division Admin" — built from
# BD_DIVISIONS so it always matches mailbox_key() below and the
# accounts seeded in init_database(). Used only to (a) validate
# sender/recipient roles in send_email() and (b) let System
# Handler / Division Admin dashboards build their own, narrower
# recipient lists — never merged into LEGACY_MAIL_ROLES itself.
HIERARCHICAL_MAIL_ROLES = ["System Handler"]

for _division_name in BD_DIVISIONS:

    HIERARCHICAL_MAIL_ROLES.append(f"{_division_name} Division Admin")

    for _org_role in ("Police", "Fire Service", "Hospital", "Municipality"):

        HIERARCHICAL_MAIL_ROLES.append(f"{_division_name} {_org_role}")

# One composite mailbox key per district-tier account — e.g.
# "Dhaka District Admin", "Dhaka District Police". Built from
# DISTRICT_NAMES so it always matches mailbox_key() below and
# the accounts seeded in init_database(). Without these,
# send_email()'s ALL_MAIL_ROLES membership check rejects every
# District Admin / District Police / District Fire Service /
# District Municipality mailbox — this previously left every
# District Admin's own Messaging/Mailbox tab silently broken
# ("Unknown sender role."), even though the UI rendered fine.
for _district_name in DISTRICT_NAMES:

    HIERARCHICAL_MAIL_ROLES.append(
        f"{_district_name} District Admin"
    )

    for _org_role in (
        "District Police", "District Fire Service",
        "District Municipality"
    ):

        HIERARCHICAL_MAIL_ROLES.append(
            f"{_district_name} {_org_role}"
        )

ALL_MAIL_ROLES = LEGACY_MAIL_ROLES + HIERARCHICAL_MAIL_ROLES


def mailbox_key(role, division=None):
    """
    The single, canonical mailbox/alert-recipient identifier for
    an account. Legacy accounts (division=None/empty) get back
    exactly their plain role string, unchanged — e.g.
    mailbox_key("Police", None) == "Police", identical to every
    mailbox key those accounts have always used. A hierarchical
    account gets a composite key — e.g.
    mailbox_key("Police", "Dhaka") == "Dhaka Police" — which is
    what ties together its own dashboard, its own email_center()
    mailbox, and its own emergency-alert read state.
    """

    if division:
        return f"{division} {role}"

    return role


def get_role_email(role):
    """
    Returns the mailbox address for any mailbox key in
    ALL_MAIL_ROLES. Legacy roles (Administrator and the 4
    original organizations) resolve exactly as before, via
    ADMIN_EMAIL / EMERGENCY_EMAILS / EMERGENCY_DOMAINS — those
    branches are untouched. Any other key (every hierarchical
    mailbox key, e.g. "Dhaka Police") falls through to a
    generated address in the same flood.com domain, e.g.
    dhaka.police@flood.com.
    """

    if role == "Administrator":
        return ADMIN_EMAIL

    if role in EMERGENCY_EMAILS:
        return EMERGENCY_EMAILS[role]

    slug = role.lower().replace(" ", ".")

    return f"{slug}@flood.com"


# ============================================================
# AUTHENTICATION
# ============================================================

def authenticate_user(
    username,
    password
):
    """
    Returns (username, role, division, area, district) on
    success, or None. division/area/district are None for every
    pre-existing account (Administrator, and the original global
    Police/Fire Service/Hospital/Municipality/Admin) — only the
    hierarchical accounts have division/area set (Division
    Admins, division-specific Police/Fire Service/Hospital), or
    district set (District Admins). Callers that only ever
    unpacked (username, role) before still work: those two
    fields are still the first two elements, in the same order.
    """

    conn = get_connection()

    hashed_password = hashlib.sha256(
        password.encode()
    ).hexdigest()

    result = conn.execute(
        """
        SELECT username, role, division, area, district
        FROM users
        WHERE username = ?
        AND password = ?
        """,
        (
            username,
            hashed_password
        )
    ).fetchone()

    conn.close()

    return result


# ============================================================
# ADMIN 2FA (EMAIL OTP) SECURITY
# ============================================================
# Everything in this section is ADDITIVE and only ever runs for
# the "Administrator" role. Police / Fire Service / Hospital /
# Municipality logins never touch any of this and go through
# authenticate_user() exactly as before, with no extra steps.
#
# This uses a REAL Gmail SMTP account (via STARTTLS on port 587)
# purely to deliver the one-time passcode to the administrator's
# inbox. It is entirely separate from, and does not modify or
# replace, the existing simulated internal `email_log` mail
# system used by Emergency Organization Messaging / Inbox /
# Sent / Bin elsewhere in this app.
# ------------------------------------------------------------

ADMIN_PASSWORD_MAX_ATTEMPTS = 5
ADMIN_PASSWORD_LOCK_MINUTES = 15

ADMIN_OTP_LENGTH = 6
ADMIN_OTP_VALID_MINUTES = 5
ADMIN_OTP_MAX_ATTEMPTS = 5
ADMIN_OTP_RESEND_COOLDOWN_SECONDS = 30

ADMIN_TRUSTED_DEVICE_COOKIE_NAME = "flood_admin_trusted_device"
ADMIN_TRUSTED_DEVICE_DAYS = 30


def _hash_code(code):
    """SHA-256 hash of an OTP (or password) — the plaintext OTP
    is never written to the database or logged anywhere."""

    return hashlib.sha256(
        code.encode()
    ).hexdigest()


def _now():
    return datetime.now()


def _parse_ts(value):

    if not value:
        return None

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        return None


def _fmt_ts(dt):

    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_admin_auth_state(username):
    """Fetches this admin username's security row, creating a
    fresh (zeroed-out) one on first use. All lock / attempt /
    OTP state is persisted here so a page refresh can never
    reset it."""

    conn = get_connection()

    row = conn.execute(
        """
        SELECT username, failed_attempts, locked_until,
               otp_hash, otp_expires_at, otp_attempts,
               otp_last_sent_at
        FROM admin_auth_state
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    if row is None:

        conn.execute(
            """
            INSERT INTO admin_auth_state(
                username, failed_attempts, locked_until,
                otp_hash, otp_expires_at, otp_attempts,
                otp_last_sent_at
            )
            VALUES (?, 0, NULL, NULL, NULL, 0, NULL)
            """,
            (username,)
        )

        conn.commit()

        row = (username, 0, None, None, None, 0, None)

    conn.close()

    keys = [
        "username", "failed_attempts", "locked_until",
        "otp_hash", "otp_expires_at", "otp_attempts",
        "otp_last_sent_at"
    ]

    return dict(zip(keys, row))


def is_admin_locked(username):
    """Returns (is_locked, seconds_remaining)."""

    state = get_admin_auth_state(username)

    locked_until = _parse_ts(state["locked_until"])

    if locked_until is None:
        return False, 0

    remaining = (locked_until - _now()).total_seconds()

    if remaining <= 0:

        # Lock has naturally expired — clear it and reset the
        # counter so the admin gets a clean slate.
        conn = get_connection()

        conn.execute(
            """
            UPDATE admin_auth_state
            SET failed_attempts = 0,
                locked_until = NULL
            WHERE username = ?
            """,
            (username,)
        )

        conn.commit()
        conn.close()

        return False, 0

    return True, int(remaining)


def record_failed_admin_password(username):
    """Increments the failed-password counter for this admin
    username and applies a 15-minute lock once it reaches the
    maximum. Returns the number of attempts remaining before a
    lock (0 if a lock was just applied)."""

    state = get_admin_auth_state(username)

    new_count = state["failed_attempts"] + 1

    conn = get_connection()

    if new_count >= ADMIN_PASSWORD_MAX_ATTEMPTS:

        locked_until = _fmt_ts(
            _now() + timedelta(
                minutes=ADMIN_PASSWORD_LOCK_MINUTES
            )
        )

        conn.execute(
            """
            UPDATE admin_auth_state
            SET failed_attempts = ?,
                locked_until = ?
            WHERE username = ?
            """,
            (new_count, locked_until, username)
        )

        remaining_attempts = 0

    else:

        conn.execute(
            """
            UPDATE admin_auth_state
            SET failed_attempts = ?
            WHERE username = ?
            """,
            (new_count, username)
        )

        remaining_attempts = (
            ADMIN_PASSWORD_MAX_ATTEMPTS - new_count
        )

    conn.commit()
    conn.close()

    return remaining_attempts


def reset_admin_password_attempts(username):

    conn = get_connection()

    conn.execute(
        """
        UPDATE admin_auth_state
        SET failed_attempts = 0,
            locked_until = NULL
        WHERE username = ?
        """,
        (username,)
    )

    conn.commit()
    conn.close()


def get_admin_2fa_recipients():
    """Reads the Gmail sender / app password / OTP recipient(s)
    from Streamlit secrets. Nothing here is ever hard-coded or
    shown in the UI — a missing/misconfigured secrets.toml
    raises a caught exception with no credential values in the
    message.

    admin_2fa_email in secrets.toml may be EITHER a single
    string address, OR a list of addresses (a TOML array), OR a
    comma-separated string — all three are normalized into a
    de-duplicated list here, so every configured address gets
    the same OTP."""

    email_secrets = st.secrets["email"]

    sender = email_secrets["sender"]
    app_password = email_secrets["app_password"]
    raw_recipients = email_secrets["admin_2fa_email"]

    if isinstance(raw_recipients, str):
        candidates = raw_recipients.split(",")
    else:
        candidates = list(raw_recipients)

    recipients = []

    for candidate in candidates:

        cleaned = candidate.strip()

        if cleaned and cleaned not in recipients:
            recipients.append(cleaned)

    if not recipients:
        raise ValueError("No admin_2fa_email address configured.")

    return sender, app_password, recipients


def send_otp_email(otp_code):
    """Sends the OTP to every configured admin 2FA address via
    real Gmail SMTP (STARTTLS, port 587). Returns
    (success, error_message)."""

    try:
        sender, app_password, recipients = (
            get_admin_2fa_recipients()
        )
    except Exception:
        return False, (
            "Email 2FA is not configured. Add an [email] "
            "section to your Streamlit secrets."
        )

    message = MIMEText(
        f"Your Flood Monitoring & Prediction System "
        f"administrator login code is:\n\n"
        f"    {otp_code}\n\n"
        f"This code expires in {ADMIN_OTP_VALID_MINUTES} "
        f"minutes and can only be used once. If you did not "
        f"request this, you can safely ignore this email."
    )

    message["Subject"] = (
        "Your Admin Login Code - Flood Monitoring System"
    )
    message["From"] = sender
    message["To"] = ", ".join(recipients)

    try:

        with smtplib.SMTP("smtp.gmail.com", 587) as server:

            server.starttls()
            server.login(sender, app_password)
            server.sendmail(
                sender,
                recipients,
                message.as_string()
            )

        return True, None

    except Exception as exc:

        # Never surface SMTP internals (which could hint at the
        # credentials) to the UI — just a generic failure.
        return False, "Could not send the OTP email. Please try again."


def generate_and_send_admin_otp(username):
    """Creates a brand-new 6-digit OTP for this admin username,
    invalidating any previous OTP (only its hash is stored),
    and emails it. Returns (success, error_message)."""

    otp_code = "".join(
        str(random.randint(0, 9))
        for _ in range(ADMIN_OTP_LENGTH)
    )

    success, error = send_otp_email(otp_code)

    if not success:
        return False, error

    otp_expires_at = _fmt_ts(
        _now() + timedelta(minutes=ADMIN_OTP_VALID_MINUTES)
    )

    conn = get_connection()

    conn.execute(
        """
        UPDATE admin_auth_state
        SET otp_hash = ?,
            otp_expires_at = ?,
            otp_attempts = 0,
            otp_last_sent_at = ?
        WHERE username = ?
        """,
        (
            _hash_code(otp_code),
            otp_expires_at,
            _fmt_ts(_now()),
            username
        )
    )

    conn.commit()
    conn.close()

    return True, None


def admin_otp_resend_cooldown_remaining(username):
    """Seconds left before Resend OTP is allowed again."""

    state = get_admin_auth_state(username)

    last_sent = _parse_ts(state["otp_last_sent_at"])

    if last_sent is None:
        return 0

    elapsed = (_now() - last_sent).total_seconds()

    remaining = ADMIN_OTP_RESEND_COOLDOWN_SECONDS - elapsed

    return max(0, int(remaining))


def verify_admin_otp(username, submitted_code):
    """Checks a submitted OTP against the stored hash. Returns
    one of: 'ok', 'expired', 'no_otp', 'locked_out', 'wrong'.

    On 'ok', the OTP is immediately cleared so it cannot be
    reused. On the 5th wrong attempt, the OTP is invalidated
    (so the admin must request a new one / restart login),
    which is reported as 'locked_out'."""

    state = get_admin_auth_state(username)

    if not state["otp_hash"]:
        return "no_otp"

    expires_at = _parse_ts(state["otp_expires_at"])

    if expires_at is None or _now() > expires_at:

        conn = get_connection()

        conn.execute(
            """
            UPDATE admin_auth_state
            SET otp_hash = NULL,
                otp_expires_at = NULL,
                otp_attempts = 0
            WHERE username = ?
            """,
            (username,)
        )

        conn.commit()
        conn.close()

        return "expired"

    if _hash_code(submitted_code) == state["otp_hash"]:

        # One-time use: clear the OTP immediately on success.
        conn = get_connection()

        conn.execute(
            """
            UPDATE admin_auth_state
            SET otp_hash = NULL,
                otp_expires_at = NULL,
                otp_attempts = 0,
                failed_attempts = 0,
                locked_until = NULL
            WHERE username = ?
            """,
            (username,)
        )

        conn.commit()
        conn.close()

        return "ok"

    # Wrong code.
    new_attempts = state["otp_attempts"] + 1

    conn = get_connection()

    if new_attempts >= ADMIN_OTP_MAX_ATTEMPTS:

        conn.execute(
            """
            UPDATE admin_auth_state
            SET otp_hash = NULL,
                otp_expires_at = NULL,
                otp_attempts = 0
            WHERE username = ?
            """,
            (username,)
        )

        conn.commit()
        conn.close()

        return "locked_out"

    conn.execute(
        """
        UPDATE admin_auth_state
        SET otp_attempts = ?
        WHERE username = ?
        """,
        (new_attempts, username)
    )

    conn.commit()
    conn.close()

    return "wrong"


def get_cookie_controller():
    """Creates the browser-cookie bridge component. Cheap to
    construct, so this is simply called once near the top of
    sidebar() on every rerun (the library's intended usage
    pattern) rather than cached."""

    return CookieController()


def safe_get_cookie(controller, name):
    """Reads a cookie defensively. The cookie component can
    briefly return None on the very first render of a fresh
    browser session before its JS bridge has synced — treating
    that the same as "no cookie" simply means the admin sees
    the OTP step that one time, never a security bypass, so
    this always fails closed."""

    try:
        return controller.get(name)
    except Exception:
        return None


def safe_set_cookie(controller, name, value, max_age_seconds):

    try:
        controller.set(name, value, max_age=max_age_seconds)
    except Exception:
        pass


def safe_remove_cookie(controller, name):

    try:
        controller.remove(name)
    except Exception:
        pass


def add_trusted_device(username, days=ADMIN_TRUSTED_DEVICE_DAYS):
    """Issues a new cryptographically random trusted-device
    token for this admin username, stores only its SHA-256
    hash, and returns the raw token so the caller can hand it
    to the browser as a cookie. The raw token itself is never
    written to the database or logged."""

    raw_token = pysecrets.token_urlsafe(32)

    expires_at = _fmt_ts(
        _now() + timedelta(days=days)
    )

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO admin_trusted_devices(
            username, token_hash, created_at, expires_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            username,
            _hash_code(raw_token),
            _fmt_ts(_now()),
            expires_at
        )
    )

    conn.commit()
    conn.close()

    return raw_token


def is_trusted_device(username, raw_token):
    """True only if raw_token hashes to a stored, unexpired
    token that belongs to THIS admin username — a trusted
    device for one admin account never grants access to
    another. An expired match is cleaned up and treated as
    untrusted."""

    if not username or not raw_token:
        return False

    token_hash = _hash_code(raw_token)

    conn = get_connection()

    row = conn.execute(
        """
        SELECT expires_at
        FROM admin_trusted_devices
        WHERE username = ?
        AND token_hash = ?
        """,
        (username, token_hash)
    ).fetchone()

    if row is None:
        conn.close()
        return False

    expires_at = _parse_ts(row[0])

    if expires_at is None or _now() > expires_at:

        conn.execute(
            """
            DELETE FROM admin_trusted_devices
            WHERE token_hash = ?
            """,
            (token_hash,)
        )

        conn.commit()
        conn.close()

        return False

    conn.close()

    return True


def forget_all_trusted_devices(username):
    """Revokes every trusted-device token for this admin
    username (used by the "Forget this device" action)."""

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM admin_trusted_devices
        WHERE username = ?
        """,
        (username,)
    )

    conn.commit()
    conn.close()


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
# FLOOD PREDICTION
# ============================================================

def calculate_flood_probability(
    water_level,
    rainfall,
    river_flow,
    soil_moisture,
    humidity
):
    """
    SUPERSEDED — kept only for reference/comparison. The live
    prediction path now uses hybrid_flood_prediction() below,
    which runs a genuine reduced-order physics/water-balance model
    (hybrid_model.run_physics_model) whose outputs feed a trained
    scikit-learn RandomForestRegressor (hybrid_model.
    train_hybrid_ml_model), then blends both results. This
    original simple weighted-sum formula is no longer called by
    generate_sensor_data() or process_uploaded_dataframe() — see
    hybrid_model.py for the actual hybrid framework.
    """

    score = (

        water_level * 18

        + rainfall * 0.28

        + river_flow * 2.5

        + soil_moisture * 0.12

        + humidity * 0.08

    )

    probability = score / 2.2

    probability += np.random.uniform(
        -5,
        5
    )

    probability = np.clip(
        probability,
        0,
        99.9
    )

    return round(
        probability,
        2
    )


def classify_risk(probability):
    """
    Single source of truth for risk classification — every
    other place in the app (map markers, risk badges, automatic
    alerts, the gauge) calls THIS function rather than
    re-implementing its own thresholds, so all of them always
    agree with each other.

    Thresholds (on the real hybrid_probability, 0-100):
        Low      : < 50
        Moderate : 50  - 69.99
        High     : 70  - 89.99
        Severe   : >= 90
    """

    if probability < 50:

        return "Low"

    elif probability < 70:

        return "Moderate"

    elif probability < 90:

        return "High"

    else:

        return "Severe"


# ============================================================
# HYBRID PHYSICS + MACHINE LEARNING PREDICTION (live path)
# ============================================================
# The actual physics model, ML training, and hybrid blending
# logic live in hybrid_model.py (kept Streamlit-independent so
# it can be reviewed/tested standalone). This section just:
#   1. Trains the ML component ONCE per running app process
#      (via st.cache_resource — training takes a few seconds;
#      re-training on every Streamlit rerun would be wasteful
#      and pointless, since the synthetic training data and
#      model don't change between reruns).
#   2. Wraps hybrid_model.hybrid_predict() with
#      classify_risk() so the rest of this app — the map,
#      risk badges, emergency alerts, cooldown, everything —
#      keeps working against the exact same "flood_probability"
#      / "risk_level" fields it always has, unmodified.
# ============================================================

@st.cache_resource(show_spinner=False)
def get_trained_hybrid_model():
    """
    Trains hybrid_model's RandomForestRegressor once per server
    process and caches the resulting bundle (trained model +
    real held-out R²/MAE + feature importances). Cached by
    Streamlit, so every rerun reuses the SAME trained model
    instance rather than retraining from scratch.
    """

    return hybrid_model.train_hybrid_ml_model()


def hybrid_flood_prediction(
    water_level,
    rainfall,
    river_flow,
    temperature,
    humidity,
    soil_moisture,
    wind_speed
):
    """
    The live prediction entry point used by both
    generate_sensor_data() (simulation) and
    process_uploaded_dataframe() (CSV/XLSX) — genuinely runs the
    physics model AND the trained ML model (see hybrid_model.py),
    then blends them. Returns a dict with everything the
    dashboards need: the existing "flood_probability" / risk
    fields (for full backward compatibility with the map, alerts,
    badges, cooldown, etc.), plus the new hybrid-specific fields
    for the "Prediction" UI and model-transparency section.
    """

    model_bundle = get_trained_hybrid_model()

    result = hybrid_model.hybrid_predict(
        water_level=water_level,
        rainfall=rainfall,
        river_flow=river_flow,
        temperature=temperature,
        humidity=humidity,
        soil_moisture=soil_moisture,
        wind_speed=wind_speed,
        model_bundle=model_bundle
    )

    flood_probability = round(result["hybrid_probability"], 2)

    risk_level = classify_risk(flood_probability)

    return {
        "flood_probability": flood_probability,
        "risk_level": risk_level,
        "predicted_water_level": result["predicted_water_level"],
        "physics_probability": result["physics_probability"],
        "ml_probability": result["ml_probability"],
        "ml_used": result["ml_used"],
        "model_name": result["model_name"],
        "physics_features": result["physics"],
    }


# ============================================================
# SIMULATED SENSOR DATA
# ============================================================

def generate_sensor_data(sensor):

    water_level = np.random.uniform(
        1.0,
        4.8
    )

    rainfall = np.random.uniform(
        5,
        150
    )

    river_flow = np.random.uniform(
        1,
        15
    )

    temperature = np.random.uniform(
        24,
        34
    )

    humidity = np.random.uniform(
        55,
        98
    )

    soil_moisture = np.random.uniform(
        30,
        98
    )

    wind_speed = np.random.uniform(
        1,
        20
    )

    hybrid_result = hybrid_flood_prediction(
        water_level=water_level,
        rainfall=rainfall,
        river_flow=river_flow,
        temperature=temperature,
        humidity=humidity,
        soil_moisture=soil_moisture,
        wind_speed=wind_speed
    )

    return {

        "sensor_id":
            sensor["sensor_id"],

        "location":
            sensor["location"],

        "timestamp":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "water_level":
            round(
                water_level,
                2
            ),

        "rainfall":
            round(
                rainfall,
                2
            ),

        "river_flow":
            round(
                river_flow,
                2
            ),

        "temperature":
            round(
                temperature,
                2
            ),

        "humidity":
            round(
                humidity,
                2
            ),

        "soil_moisture":
            round(
                soil_moisture,
                2
            ),

        "wind_speed":
            round(
                wind_speed,
                2
            ),

        "flood_probability":
            hybrid_result["flood_probability"],

        "risk_level":
            hybrid_result["risk_level"],

        "predicted_water_level":
            hybrid_result["predicted_water_level"],

        "physics_probability":
            hybrid_result["physics_probability"],

        "ml_probability":
            hybrid_result["ml_probability"],

        "ml_used":
            hybrid_result["ml_used"],

        "model_name":
            hybrid_result["model_name"],

        "data_source":
            "Simulation"

    }


# ============================================================
# DATASET HANDLING
# ============================================================

REQUIRED_DATASET_COLUMNS = [

    "water_level",

    "rainfall",

    "river_flow",

    "temperature",

    "humidity",

    "soil_moisture",

    "wind_speed"

]

SUPPORTED_DATASET_TYPES = [
    "csv",
    "xlsx"
]


def normalize_dataset_columns(df):

    df = df.copy()

    df.columns = [

        str(column)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")

        for column in df.columns

    ]

    aliases = {

        "waterlevel":
            "water_level",

        "water_level_m":
            "water_level",

        "rain":
            "rainfall",

        "rainfall_mm":
            "rainfall",

        "riverflow":
            "river_flow",

        "river_flow_ms":
            "river_flow",

        "temp":
            "temperature",

        "soil":
            "soil_moisture",

        "soil_moisture_percent":
            "soil_moisture",

        "wind":
            "wind_speed",

        "windspeed":
            "wind_speed"

    }

    df = df.rename(
        columns=aliases
    )

    return df


def read_dataset_file(
    uploaded_file
):

    """
    Reads an uploaded CSV or XLSX file into a DataFrame.
    Returns None (after showing st.error) on any failure so
    the app never crashes on a bad file.
    """

    if uploaded_file is None:

        return None

    filename = getattr(
        uploaded_file,
        "name",
        "uploaded_file"
    )

    extension = filename.split(".")[-1].lower() if "." in filename else ""

    try:

        if extension == "csv":

            df = pd.read_csv(
                uploaded_file
            )

        elif extension in (
            "xlsx",
            "xls"
        ):

            try:

                df = pd.read_excel(
                    uploaded_file,
                    engine="openpyxl"
                )

            except ImportError:

                st.error(
                    "Reading .xlsx files requires the 'openpyxl' "
                    "package. Please install it "
                    "(pip install openpyxl) or upload a CSV instead."
                )

                return None

        else:

            st.error(
                f"Unsupported file type '.{extension}'. "
                f"Please upload a CSV or XLSX file."
            )

            return None

    except Exception as error:

        st.error(
            f"Unable to read dataset: {error}"
        )

        return None

    if df is None or df.empty:

        st.error(
            "The uploaded file is empty or contains no rows."
        )

        return None

    return df


def process_uploaded_dataframe(
    df,
    location
):

    """
    Validates and prepares an already-loaded DataFrame for use
    as external sensor data for the given (externally selected)
    location. The dataset itself is NOT expected to contain a
    location column — if one exists it is ignored, since the
    location is always the one chosen by the user outside the
    file.
    """

    if not location or not str(location).strip():

        st.error(
            "Please select or enter a location before "
            "loading the dataset."
        )

        return None

    location = str(location).strip()

    df = normalize_dataset_columns(
        df
    )

    # Location is provided externally; drop any location-like
    # column from the file itself so it can never conflict.

    for stray_column in (
        "location",
        "area",
        "district"
    ):

        if stray_column in df.columns:

            df = df.drop(
                columns=[stray_column]
            )

    missing = [

        column

        for column in REQUIRED_DATASET_COLUMNS

        if column not in df.columns

    ]

    if missing:

        st.error(
            "Dataset is missing required columns: "
            + ", ".join(missing)
        )

        st.info(
            "Required columns: "
            + ", ".join(REQUIRED_DATASET_COLUMNS)
        )

        return None

    numeric_columns = [

        "water_level",

        "rainfall",

        "river_flow",

        "temperature",

        "humidity",

        "soil_moisture",

        "wind_speed"

    ]

    for column in numeric_columns:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df = df.dropna(
        subset=numeric_columns
    )

    if df.empty:

        st.error(
            "No valid numeric rows were found in the dataset "
            "(check for missing or non-numeric values)."
        )

        return None

    if "sensor_id" not in df.columns:

        df["sensor_id"] = ""

    if "timestamp" not in df.columns:

        df["timestamp"] = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    results = []

    multi_row = len(df) > 1

    base_sensor_id = (
        "DATA-"
        + location.upper().replace(
            " ",
            "-"
        )
    )

    for row_index, (_, row) in enumerate(
        df.iterrows(),
        start=1
    ):

        hybrid_result = hybrid_flood_prediction(
            water_level=float(row["water_level"]),
            rainfall=float(row["rainfall"]),
            river_flow=float(row["river_flow"]),
            temperature=float(row["temperature"]),
            humidity=float(row["humidity"]),
            soil_moisture=float(row["soil_moisture"]),
            wind_speed=float(row["wind_speed"])
        )

        sensor_id = str(
            row["sensor_id"]
        ).strip()

        if not sensor_id:

            sensor_id = base_sensor_id

            if multi_row:

                sensor_id = f"{base_sensor_id}-{row_index}"

        timestamp = str(
            row["timestamp"]
        )

        results.append({

            "sensor_id":
                sensor_id,

            "location":
                location,

            "timestamp":
                timestamp,

            "water_level":
                round(
                    float(row["water_level"]),
                    2
                ),

            "rainfall":
                round(
                    float(row["rainfall"]),
                    2
                ),

            "river_flow":
                round(
                    float(row["river_flow"]),
                    2
                ),

            "temperature":
                round(
                    float(row["temperature"]),
                    2
                ),

            "humidity":
                round(
                    float(row["humidity"]),
                    2
                ),

            "soil_moisture":
                round(
                    float(row["soil_moisture"]),
                    2
                ),

            "wind_speed":
                round(
                    float(row["wind_speed"]),
                    2
                ),

            "flood_probability":
                hybrid_result["flood_probability"],

            "risk_level":
                hybrid_result["risk_level"],

            "predicted_water_level":
                hybrid_result["predicted_water_level"],

            "physics_probability":
                hybrid_result["physics_probability"],

            "ml_probability":
                hybrid_result["ml_probability"],

            "ml_used":
                hybrid_result["ml_used"],

            "model_name":
                hybrid_result["model_name"],

            "data_source":
                "External Dataset"

        })

    return pd.DataFrame(
        results
    )


def ensure_dataset_state():

    """
    Makes sure the multi-location dataset storage exists in
    session state. Called defensively wherever dataset state
    is read or written, in addition to the one-time init in
    main(), so no code path can hit a missing key.
    """

    if "uploaded_datasets" not in st.session_state:

        st.session_state.uploaded_datasets = {}

    if "uploaded_datasets_meta" not in st.session_state:

        st.session_state.uploaded_datasets_meta = {}


def pick_latest_record(df):

    """
    Returns the single most-recent row of a dataframe as a
    Series, using the timestamp column when it can be parsed
    as a date/time, and falling back to the last row in file
    order otherwise (instead of an arbitrary row).
    """

    if df is None or df.empty:

        return None

    working = df.copy()

    parsed_time = pd.to_datetime(
        working["timestamp"],
        errors="coerce"
    )

    if parsed_time.notna().any():

        working = working.assign(
            _parsed_ts=parsed_time
        )

        working = working.sort_values(
            "_parsed_ts"
        )

    return working.iloc[-1]


def get_full_dataset(location):

    """Returns all uploaded rows for a location (for previews)."""

    ensure_dataset_state()

    return st.session_state.uploaded_datasets.get(
        location,
        pd.DataFrame()
    )


def get_uploaded_locations():

    """Locations currently backed by an external dataset."""

    ensure_dataset_state()

    return list(
        st.session_state.uploaded_datasets.keys()
    )


def get_dataset_readings():

    """
    Returns one CURRENT row per external-dataset location (the
    latest record, per pick_latest_record), for use by the same
    prediction/map/simulation pipeline that handles simulated
    sensor data.
    """

    ensure_dataset_state()

    datasets = st.session_state.uploaded_datasets

    if not datasets:

        return pd.DataFrame()

    latest_rows = []

    for location, df in datasets.items():

        latest = pick_latest_record(
            df
        )

        if latest is not None:

            latest_rows.append(
                latest
            )

    if not latest_rows:

        return pd.DataFrame()

    return pd.DataFrame(
        latest_rows
    ).reset_index(
        drop=True
    )


def remove_dataset_location(location):

    """Removes the uploaded dataset for one location only."""

    ensure_dataset_state()

    st.session_state.uploaded_datasets.pop(
        location,
        None
    )

    st.session_state.uploaded_datasets_meta.pop(
        location,
        None
    )


# ============================================================
# GENERATE ALL SENSOR DATA
# ============================================================

def generate_all_sensor_data():

    sensors = get_sensors()

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

    readings = []

    for _, row in sensors.iterrows():

        location = str(
            row["location"]
        ).strip()

        # ----------------------------------------------------
        # IMPORTANT:
        # If external dataset contains this location,
        # simulation is disabled for that location.
        # ----------------------------------------------------

        if location.lower() in dataset_locations:

            continue

        sensor = {

            "sensor_id":
                row["sensor_id"],

            "location":
                location

        }

        data = generate_sensor_data(
            sensor
        )

        save_sensor_reading(
            data
        )

        readings.append(
            data
        )

    simulated_df = pd.DataFrame(
        readings
    )

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

    st.caption(
        f"Register sensors and upload CSV/XLSX datasets for "
        f"{scope_label} only."
    )

    tab_sensor_cfg, tab_dataset = st.tabs(
        [
            "⚙️ Sensor Configuration",
            "📂 External Dataset Input"
        ]
    )

    with tab_sensor_cfg:

        st.info(
            """
            The system supports simulated sensor data and
            external CSV dataset input.

            Real sensors can later be connected using:
            ESP32, Arduino, MQTT, REST API or another IoT gateway.
            """
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
                format="%.6f",
                key=f"{key_prefix}_sensor_lat"
            )

            longitude = st.number_input(
                "Longitude",
                value=90.4125,
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


# ============================================================
# FLOOD MAP
# ============================================================

RISK_DISPLAY_LABELS = {

    "Low":
        "🟢 Safe / Low Risk",

    "Moderate":
        "🟡 Warning / Moderate Risk",

    "High":
        "🟠 High Risk",

    "Severe":
        "🔴 Flood / Critical Risk"

}

# Just the circle for a risk level, no label — used for compact
# per-area/per-location badges next to selectors and cards.
RISK_CIRCLE = {

    "Low": "🟢",

    "Moderate": "🟡",

    "High": "🟠",

    "Severe": "🔴"

}

# Shown when a location/area has no current reading at all
# (no registered sensor and no uploaded dataset for it yet) —
# distinct from every real risk level so it's never confused
# with "Low risk".
NO_DATA_CIRCLE = "⚪"


def location_risk_circle(readings, location):
    """
    Returns the small risk-circle emoji for ONE location, given
    a readings DataFrame (as produced by
    generate_all_sensor_data()). Returns NO_DATA_CIRCLE if that
    location has no current reading — this is what lets a
    selector show "⚪ Sylhet" instead of silently looking exactly
    like a real risk level.
    """

    if readings is None or readings.empty or not location:
        return NO_DATA_CIRCLE

    match = readings[
        readings["location"]
        .astype(str)
        .str.strip()
        .str.lower()
        == str(location).strip().lower()
    ]

    if match.empty:
        return NO_DATA_CIRCLE

    return RISK_CIRCLE.get(
        match.iloc[0]["risk_level"],
        NO_DATA_CIRCLE
    )


def worst_risk_circle(readings, location_list):
    """
    Returns the single worst risk-circle emoji across every
    location in location_list — used to give a whole division
    (or any other group of areas) one at-a-glance status icon.
    NO_DATA_CIRCLE only if NONE of the locations have a reading
    yet.
    """

    if readings is None or readings.empty or not location_list:
        return NO_DATA_CIRCLE

    severity_order = ["Severe", "High", "Moderate", "Low"]

    group = readings[
        readings["location"].isin(location_list)
    ]

    if group.empty:
        return NO_DATA_CIRCLE

    present_levels = set(group["risk_level"])

    for level in severity_order:

        if level in present_levels:
            return RISK_CIRCLE.get(level, NO_DATA_CIRCLE)

    return NO_DATA_CIRCLE


def location_badge_row(readings, location_list):
    """
    Builds one plain-text line like
    "🟢 Dhaka  •  🔴 Jamalpur  •  ⚪ Sylhet" for a quick-glance
    risk overview across several locations. Uses only plain
    characters (no HTML entities like &nbsp;, which would just
    show up as literal text without unsafe_allow_html) so it
    renders correctly with a plain st.markdown() call — no HTML
    parsing involved at all, so none of the indentation pitfalls
    fixed elsewhere in this file apply here.
    """

    badges = [
        f"{location_risk_circle(readings, location)} {location}"
        for location in location_list
    ]

    return "  •  ".join(badges)


def create_flood_map(
    readings,
    focus_location=None
):

    """
    Builds the Live Flood Location Map from the CURRENT reading
    per location (one row per location, whether simulated or
    from an external dataset). Coordinates come from
    LOCATION_COORDINATES / get_location_coordinates() rather
    than a merge against the sensors table, so uploaded-dataset
    locations that aren't registered sensors (e.g. Jamalpur,
    Sylhet) still appear correctly on the map.

    focus_location is optional. When given (and it has known
    coordinates), the map centers on and zooms into that one
    location instead of auto-fitting every plotted location —
    used so the Admin dashboard's map "jumps to" whichever
    location is chosen in Location Selection. All markers for
    every other location are still drawn and still hoverable;
    only the initial camera position/zoom changes. Callers that
    don't pass focus_location (organization/public dashboards)
    get the exact same all-locations view as before.
    """

    empty_layout = {
        "height": 600,
        "margin": {
            "r": 0,
            "t": 0,
            "l": 0,
            "b": 0
        }
    }

    if readings is None or readings.empty:

        fig = go.Figure()

        fig.update_layout(**empty_layout)

        return fig

    map_rows = []

    unmapped_locations = []

    for _, row in readings.iterrows():

        location = str(
            row.get(
                "location",
                ""
            )
        ).strip()

        if not location:

            continue

        coords = get_location_coordinates(
            location
        )

        if coords is None:

            unmapped_locations.append(
                location
            )

            continue

        latitude, longitude = coords

        entry = row.to_dict()

        entry["latitude"] = latitude
        entry["longitude"] = longitude

        entry["risk_display"] = RISK_DISPLAY_LABELS.get(
            row.get("risk_level"),
            str(row.get("risk_level"))
        )

        # Always-visible label directly on the map for this
        # location — the risk circle + name, so the status is
        # visible at a glance without having to hover, and
        # without depending on marker color/size alone.
        entry["map_label"] = (
            f"{RISK_CIRCLE.get(row.get('risk_level'), NO_DATA_CIRCLE)} "
            f"{location}"
        )

        # Marker size: a visible FLOOR (18) regardless of risk,
        # so a Low-risk reading (which can be a single-digit
        # probability) is never reduced to a near-invisible dot
        # — probability still scales the size up further for
        # higher-risk locations, for visual emphasis, but never
        # shrinks a marker below a clearly clickable/visible
        # size.
        entry["marker_size"] = 18 + (
            float(
                row.get(
                    "flood_probability",
                    0
                ) or 0
            ) * 0.35
        )

        map_rows.append(entry)

    if unmapped_locations:

        st.warning(
            "⚠️ No map coordinates configured for: "
            + ", ".join(sorted(set(unmapped_locations)))
            + ". Add them to LOCATION_COORDINATES to display "
              "these locations on the map."
        )

    if not map_rows:

        fig = go.Figure()

        fig.update_layout(**empty_layout)

        return fig

    map_df = pd.DataFrame(
        map_rows
    )

    color_map = {

        RISK_DISPLAY_LABELS["Low"]:
            "#2ECC71",

        RISK_DISPLAY_LABELS["Moderate"]:
            "#FFB300",

        RISK_DISPLAY_LABELS["High"]:
            "#FF7F00",

        RISK_DISPLAY_LABELS["Severe"]:
            "#E53935"

    }

    # --------------------------------------------------------
    # Focus/zoom: default is Plotly's own auto-fit over every
    # plotted point (zoom=9, no explicit center — unchanged
    # behavior). If a valid focus_location was given, center on
    # its exact coordinates and zoom in closer instead.
    # --------------------------------------------------------

    map_center = None

    map_zoom = 9

    if focus_location:

        focus_coords = get_location_coordinates(
            focus_location
        )

        if focus_coords is not None:

            focus_latitude, focus_longitude = focus_coords

            map_center = {

                "lat": focus_latitude,

                "lon": focus_longitude

            }

            map_zoom = 12

    # --------------------------------------------------------
    # Plotly 7.x uses scatter_map instead of scatter_mapbox.
    # --------------------------------------------------------

    scatter_map_kwargs = {

        "lat": "latitude",

        "lon": "longitude",

        "color": "risk_display",

        "color_discrete_map": color_map,

        "size": "marker_size",

        "size_max": 32,

        "text": "map_label",

        "hover_name": "location",

        "hover_data": {

            "sensor_id":
                True,

            "water_level":
                True,

            "rainfall":
                True,

            "river_flow":
                True,

            "temperature":
                True,

            "humidity":
                True,

            "soil_moisture":
                True,

            "wind_speed":
                True,

            "flood_probability":
                True,

            "risk_display":
                True,

            "data_source":
                True,

            "marker_size":
                False,

            "latitude":
                False,

            "longitude":
                False

        },

        "zoom": map_zoom,

        "height": 600

    }

    if map_center is not None:

        scatter_map_kwargs["center"] = map_center

    fig = px.scatter_map(

        map_df,

        **scatter_map_kwargs

    )

    # Always show each marker's label (risk circle + location
    # name) directly on the map — not just on hover — so the
    # status is visible for every location at a glance.
    fig.update_traces(
        mode="markers+text",
        textposition="top center",
        textfont=dict(size=13, color="black")
    )

    fig.update_layout(

        map_style=
            "open-street-map",

        margin={
            "r": 0,
            "t": 0,
            "l": 0,
            "b": 0
        },

        legend=dict(
            title="Flood Risk Status"
        )

    )

    return fig


# ============================================================
# EMERGENCY NOTIFICATION FUNCTIONS
# ============================================================

# ============================================================
# EMAIL SYSTEM (two-way, per-organization Inbox/Sent/Bin)
# ============================================================
# This is the SAME email_log table/system used by the
# Admin -> Emergency Organization Messaging panel, the
# Emergency Siren, and the Email Server (SMTP) Status panel.
# It has been generalized so ANY role (Administrator, Police,
# Fire Service, Hospital, Municipality) can be the sender, not
# just Administrator, while every existing call/behavior below
# keeps working exactly as before.
# ============================================================

def send_email(
    sender_role,
    target_role,
    subject,
    body
):
    """
    Core send function for the whole app. Writes ONE email as
    TWO rows in email_log: an Inbox copy owned by target_role
    and a Sent copy owned by sender_role. Because each mailbox
    copy is its own row, per-user Delete / Bin / Restore /
    Permanent Delete (see below) can only ever affect the
    caller's own copy.

    sender_role must always come from the authenticated
    session (st.session_state.role) at the call site — never
    from a value the user can edit — so no one can spoof who
    an email is "From".
    """

    if sender_role == target_role:
        raise ValueError(
            "Users cannot send an email to themselves."
        )

    if sender_role not in ALL_MAIL_ROLES:
        raise ValueError("Unknown sender role.")

    if target_role not in ALL_MAIL_ROLES:
        raise ValueError("Unknown recipient role.")

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    sender_email = get_role_email(sender_role)
    recipient_email = get_role_email(target_role)

    conn = get_connection()

    # Recipient's Inbox copy.
    conn.execute(
        """
        INSERT INTO email_log(
            sender, recipient, target_role,
            subject, body, timestamp, status,
            sender_role, owner_role, folder,
            is_read, in_bin
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'inbox', 0, 0)
        """,
        (
            sender_email, recipient_email, target_role,
            subject, body, timestamp, "Delivered",
            sender_role, target_role
        )
    )

    # Sender's Sent copy.
    conn.execute(
        """
        INSERT INTO email_log(
            sender, recipient, target_role,
            subject, body, timestamp, status,
            sender_role, owner_role, folder,
            is_read, in_bin
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'sent', 1, 0)
        """,
        (
            sender_email, recipient_email, target_role,
            subject, body, timestamp, "Delivered",
            sender_role, sender_role
        )
    )

    conn.commit()
    conn.close()


def send_system_email(
    target_role,
    subject,
    body
):
    """
    Preserved for backward compatibility — this is what
    send_emergency_notification() (the Emergency Siren / Admin
    messaging panel) already calls. Still simulates the
    outgoing mail server exactly as before; it now simply
    delegates to send_email() so the same email also shows up
    correctly in Administrator's own Sent view.
    """

    send_email(
        "Administrator",
        target_role,
        subject,
        body
    )


def get_email_log(
    target_role=None
):
    """
    Preserved signature/behavior:
    - get_email_log() with no argument -> the full outgoing
      mail server log used by the Email Server (SMTP) Status
      panel (one row per email actually sent, regardless of
      who sent it).
    - get_email_log(role) -> that organization's Inbox
      (used by the organization portal's Email Inbox view).
    """

    conn = get_connection()

    if target_role is None:

        df = pd.read_sql_query(
            """
            SELECT *
            FROM email_log
            WHERE folder = 'sent'
            ORDER BY id DESC
            """,
            conn
        )

    else:

        df = pd.read_sql_query(
            """
            SELECT *
            FROM email_log
            WHERE owner_role = ?
            AND folder = 'inbox'
            AND in_bin = 0
            ORDER BY id DESC
            """,
            conn,
            params=(target_role,)
        )

    conn.close()

    return df


def get_sent_mail(
    owner_role
):
    """This organization's own Sent items (not in their Bin)."""

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT *
        FROM email_log
        WHERE owner_role = ?
        AND folder = 'sent'
        AND in_bin = 0
        ORDER BY id DESC
        """,
        conn,
        params=(owner_role,)
    )

    conn.close()

    return df


def get_bin_mail(
    owner_role
):
    """
    Everything owner_role has moved to their OWN Bin. Other
    organizations' mailboxes are never touched or visible here.
    """

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT *
        FROM email_log
        WHERE owner_role = ?
        AND in_bin = 1
        ORDER BY deleted_at DESC
        """,
        conn,
        params=(owner_role,)
    )

    conn.close()

    return df


def mark_email_read(
    mail_id,
    owner_role
):
    """
    Marks a single mailbox row as read. The owner_role check
    ensures a user can only mark their OWN mailbox copy.
    """

    conn = get_connection()

    conn.execute(
        """
        UPDATE email_log
        SET is_read = 1
        WHERE id = ?
        AND owner_role = ?
        """,
        (mail_id, owner_role)
    )

    conn.commit()
    conn.close()


def move_email_to_bin(
    mail_id,
    owner_role
):
    """
    Moves ONLY this organization's copy of the email to THEIR
    bin. Does not affect the other party's copy in any way.
    """

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()

    conn.execute(
        """
        UPDATE email_log
        SET in_bin = 1, deleted_at = ?
        WHERE id = ?
        AND owner_role = ?
        """,
        (timestamp, mail_id, owner_role)
    )

    conn.commit()
    conn.close()


def restore_email_from_bin(
    mail_id,
    owner_role
):
    """
    Restores this organization's copy from Bin back to its
    original Inbox or Sent location (folder is unchanged, this
    just clears in_bin).
    """

    conn = get_connection()

    conn.execute(
        """
        UPDATE email_log
        SET in_bin = 0, deleted_at = NULL
        WHERE id = ?
        AND owner_role = ?
        """,
        (mail_id, owner_role)
    )

    conn.commit()
    conn.close()


def permanently_delete_email(
    mail_id,
    owner_role
):
    """
    Permanently removes ONLY this organization's own mailbox
    row. Because sender and recipient copies are separate rows,
    this can never affect the other party's copy.
    """

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM email_log
        WHERE id = ?
        AND owner_role = ?
        """,
        (mail_id, owner_role)
    )

    conn.commit()
    conn.close()


def empty_bin(
    owner_role
):
    """
    Permanently deletes EVERY row currently in owner_role's OWN
    Bin (in_bin = 1) — and only owner_role's rows. Since each
    mailbox copy (sender's / recipient's) is its own row keyed
    by owner_role, this can never touch another user's Inbox,
    Sent, or Bin, and it never touches this same user's Inbox
    or Sent items (those have in_bin = 0).
    """

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM email_log
        WHERE owner_role = ?
        AND in_bin = 1
        """,
        (owner_role,)
    )

    conn.commit()
    conn.close()


def send_emergency_notification(
    target_role,
    message=None,
    subject=None
):

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    if message is None:

        message = (
            "🚨 EMERGENCY ALERT: "
            "Administrator has sent an emergency notification. "
            "Please respond immediately."
        )

    if subject is None:

        subject = (
            f"🚨 Flood Emergency Alert for {target_role}"
        )

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO emergency_notifications(
            target_role,
            message,
            timestamp,
            status
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            target_role,
            message,
            timestamp,
            "Unread"
        )
    )

    conn.commit()
    conn.close()

    # ----------------------------------------------------
    # Dispatch the same alert through the mail server so
    # it shows up in the organization's email inbox too.
    # ----------------------------------------------------

    send_system_email(
        target_role,
        subject,
        message
    )


def get_emergency_notifications(
    role
):

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT *
        FROM emergency_notifications
        WHERE target_role = ?
        ORDER BY id DESC
        """,
        conn,
        params=(role,)
    )

    conn.close()

    return df


def mark_notifications_read(
    role
):

    conn = get_connection()

    conn.execute(
        """
        UPDATE emergency_notifications
        SET status = 'Read'
        WHERE target_role = ?
        """,
        (role,)
    )

    conn.commit()
    conn.close()


# ============================================================
# NEW EMERGENCY ALERT SYSTEM (blinking + sound)
# ============================================================
# Fully additive — the emergency_notifications table and the
# two functions directly above are untouched and keep working
# exactly as before. This is a SEPARATE, independent alert
# system built on emergency_alerts / emergency_alert_reads,
# purpose-built for a persistent, per-recipient, blinking +
# sounding banner that only stops when THAT recipient marks it
# read.
#
# "Recipient" here is always a mailbox_key() string (e.g.
# "Police" for a legacy account, "Dhaka Police" for a
# hierarchical one) — so Dhaka Police and Dhaka Hospital always
# have completely independent read state, and so do e.g. the
# legacy "Police" account and "Dhaka Police".
# ============================================================

EMERGENCY_ALERT_SOUND_B64 = "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"


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


# ============================================================
# AUTOMATIC EMERGENCY ALERTS (no admin click required)
# ============================================================
# Whenever any location's REAL hybrid-model flood_probability
# reaches Severe risk (>= 90%, per classify_risk() above), an
# alert is created automatically — using the exact same
# create_emergency_alert() any manual siren uses, so recipients
# get the identical blinking + sounding banner either way.
# Debounced per location with AUTO_ALERT_COOLDOWN_MINUTES so the
# simulation's every-rerun randomness (and every Streamlit
# rerun in general) can't spam the same location's alert
# repeatedly.
# ============================================================

AUTO_ALERT_MIN_RISK_LEVELS = ("Severe",)

AUTO_ALERT_COOLDOWN_MINUTES = 5


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


def _html_no_indent(html_text):
    """
    Strips leading whitespace from every line of an HTML/CSS
    string before it goes into st.markdown(unsafe_allow_html=
    True). Markdown treats any line starting with 4+ spaces as
    a preformatted code block — so HTML built from an indented
    Python f-string (indentation coming from the surrounding
    function body) would otherwise render as ESCAPED, VISIBLE
    TEXT instead of being parsed as HTML, which is exactly why
    the emergency card was showing up as literal <div> markup
    on the page instead of a styled banner. Removing every
    line's leading whitespace (which HTML/CSS never depends on
    for rendering) fixes that regardless of how the calling
    Python code is indented.
    """

    return "\n".join(
        line.lstrip() for line in html_text.split("\n")
    )


def render_emergency_alert_banner(recipient_key):
    """
    Renders ONE consolidated 🚨 EMERGENCY ALERT banner for
    recipient_key, combining BOTH alert stores this app has:
    the newer blinking/sounding emergency_alerts system, and
    the older plain emergency_notifications table (which the
    Administrator's siren also still writes to, for history/
    compatibility). They used to be shown as two separate boxes
    with two separately-labeled "Mark Emergency Alerts as Read"
    buttons — clicking one didn't clear the other, which is
    confusing. Now there is exactly one banner and one button
    that clears both at once.

    recipient_key is a mailbox_key() — for a hierarchical
    account (e.g. "Dhaka Police") the older table simply never
    has any matching rows (it only ever used plain role names),
    so this safely reduces to "new system only" for those
    accounts, with no extra code path needed.

    Renders nothing at all when there is nothing unread in
    EITHER store — which is also exactly how the sound stops
    the instant "Mark Emergency Alerts as Read" is clicked: on
    the rerun that follows, both counts are 0, so this function
    draws nothing and the <audio> element is gone from the page.

    The alert (blink + sound) starts automatically the moment
    the admin/division admin sends it — recipients do not have
    to click anything to activate it. The <audio autoplay loop>
    element is rendered unconditionally below; most browsers
    allow JS-triggered audio autoplay once the user has
    interacted with the page at all (which they always have, by
    logging in), so this plays immediately on the very next
    rerun after the alert is created. A short, purely
    informational hint (not a gate) is shown underneath for the
    rare browser that still blocks it silently.
    """

    # --------------------------------------------------------
    # Performance: fetch only a bounded number of full alert
    # cards to actually render (an account was found with 400+
    # unread alerts — building that many large blinking HTML
    # cards on every single rerun was the main cause of the
    # slowdown reported). The TRUE total still comes from the
    # fast, indexed COUNT query, and "Mark Emergency Alerts as
    # Read" below still clears the entire backlog, not just the
    # displayed subset — nothing is hidden or lost, only how
    # much gets rendered at once.
    # --------------------------------------------------------

    MAX_ALERT_CARDS_SHOWN = 8

    total_unread_alert_count = get_unread_emergency_alert_count(
        recipient_key
    )

    unread_alerts = get_unread_emergency_alerts(
        recipient_key,
        limit=MAX_ALERT_CARDS_SHOWN
    )

    legacy_notifications = get_emergency_notifications(
        recipient_key
    )

    legacy_unread_all = legacy_notifications[
        legacy_notifications["status"] == "Unread"
    ]

    total_legacy_unread_count = len(legacy_unread_all)

    legacy_unread = legacy_unread_all.head(
        MAX_ALERT_CARDS_SHOWN
    )

    if unread_alerts.empty and legacy_unread.empty:
        return

    total_unread_everywhere = (
        total_unread_alert_count + total_legacy_unread_count
    )

    total_shown = len(unread_alerts) + len(legacy_unread)

    if total_unread_everywhere > total_shown:

        st.warning(
            f"🚨 Showing the {total_shown} most recent of "
            f"**{total_unread_everywhere} unread emergency "
            f"alerts**. Click \"Mark Emergency Alerts as Read\" "
            f"below to clear all of them, not just the ones "
            f"shown here."
        )

    # --------------------------------------------------------
    # Blinking CSS + one card per unread item, from EITHER
    # store. Scoped to the ".emergency-blink" class only, so
    # nothing else on the page blinks.
    # --------------------------------------------------------

    cards_html = ""

    for _, alert_row in unread_alerts.iterrows():

        location_bits = []

        if alert_row["target_division"]:
            location_bits.append(
                f"Division: {alert_row['target_division']}"
            )

        if alert_row["target_area"]:
            location_bits.append(
                f"Area: {alert_row['target_area']}"
            )

        location_line = (
            "<br>".join(location_bits)
            if location_bits else ""
        )

        cards_html += _html_no_indent(f"""
        <div class="emergency-blink" style="
        background-color:#B00020;
        color:white;
        border:4px solid #FFCDD2;
        border-radius:14px;
        padding:22px;
        margin-bottom:14px;
        text-align:center;
        box-shadow:0 0 25px rgba(255,0,0,0.6);
        ">
        <div style="font-size:30px; font-weight:800;">
        🚨🚨🚨 EMERGENCY ALERT 🚨🚨🚨
        </div>
        <div style="font-size:20px; margin-top:10px;">
        {alert_row['title']}
        </div>
        <div style="font-size:16px; margin-top:8px;">
        {alert_row['message']}
        </div>
        <div style="font-size:14px; margin-top:12px;">
        Alert Level: <b>{alert_row['level']}</b><br>
        {location_line}
        </div>
        <div style="font-size:13px; margin-top:8px; opacity:0.9;">
        Sender: {alert_row['sender']}  |
        Time: {alert_row['created_at']}
        </div>
        </div>
        """)

    for _, notification_row in legacy_unread.iterrows():

        cards_html += _html_no_indent(f"""
        <div class="emergency-blink" style="
        background-color:#B00020;
        color:white;
        border:4px solid #FFCDD2;
        border-radius:14px;
        padding:22px;
        margin-bottom:14px;
        text-align:center;
        box-shadow:0 0 25px rgba(255,0,0,0.6);
        ">
        <div style="font-size:30px; font-weight:800;">
        🚨🚨🚨 EMERGENCY ALERT 🚨🚨🚨
        </div>
        <div style="font-size:16px; margin-top:8px;">
        {notification_row['message']}
        </div>
        <div style="font-size:13px; margin-top:8px; opacity:0.9;">
        Time: {notification_row['timestamp']}
        </div>
        </div>
        """)

    blink_css = _html_no_indent("""
    <style>
    @keyframes emergency-blink-keyframes {
    0%   { opacity: 1; }
    50%  { opacity: 0.15; }
    100% { opacity: 1; }
    }
    .emergency-blink {
    animation: emergency-blink-keyframes 0.9s infinite;
    }
    </style>
    """)

    st.markdown(
        blink_css + cards_html,
        unsafe_allow_html=True
    )

    # --------------------------------------------------------
    # Sound — starts automatically, no click required. Kept as
    # its own st.markdown call (not concatenated with the cards
    # above) so it re-renders identically every rerun and the
    # browser doesn't need to re-parse a huge combined string
    # just to find the <audio> tag.
    # --------------------------------------------------------

    st.markdown(
        _html_no_indent(f"""
        <audio autoplay loop>
        <source src="data:audio/wav;base64,{EMERGENCY_ALERT_SOUND_B64}"
        type="audio/wav">
        </audio>
        """),
        unsafe_allow_html=True
    )

    st.caption(
        "🔊 Emergency sound is playing automatically. If your "
        "browser blocked it, click anywhere on this page once "
        "to allow sound. It stops the moment the alert below "
        "is marked as read."
    )

    if st.button(
        "✅ Mark Emergency Alerts as Read",
        key=f"mark_emergency_alerts_read_{recipient_key}",
        width="stretch"
    ):

        mark_emergency_alerts_read(recipient_key)

        # Safe no-op for a hierarchical account: this only ever
        # matches rows for plain legacy role names, which a
        # composite key like "Dhaka Police" never has.
        mark_notifications_read(recipient_key)

        st.rerun()


# ============================================================
# ADMIN MESSAGE CENTER
# ============================================================

def admin_message_center():

    st.subheader(
        "📨 Admin → Emergency Organization Messaging"
    )

    st.write(
        "Send a message from the Administrator portal "
        "to any emergency organization."
    )

    # ------------------------------------------------------
    # Reset the compose fields BEFORE the widgets below are
    # created. A widget's session_state value can only be
    # reassigned before that widget is instantiated on a
    # given run, so a successful send (below) sets this flag
    # and reruns; on the very next run we clear the fields
    # here, ahead of the selectbox/text_input/text_area calls.
    # ------------------------------------------------------

    if st.session_state.get(
        "admin_message_clear_pending",
        False
    ):

        st.session_state.admin_message_target = "Police"

        st.session_state.admin_message_subject = ""

        st.session_state.admin_emergency_message = ""

        st.session_state.admin_message_clear_pending = False

    # One-shot success message carried over from the previous
    # (successful) send via st.rerun(), shown once here, then
    # discarded so it doesn't linger on future reruns.

    if st.session_state.get("admin_message_last_success"):

        st.success(
            st.session_state.admin_message_last_success
        )

        del st.session_state["admin_message_last_success"]

    target = st.selectbox(

        "Select Emergency Organization",

        [
            "Police",
            "Fire Service",
            "Hospital",
            "Municipality"
        ],

        key="admin_message_target"

    )

    st.caption(
        f"Emergency webpage/domain: "
        f"{EMERGENCY_DOMAINS.get(target, 'Not configured')} "
        f"  |  Mailbox: {EMERGENCY_EMAILS.get(target, 'Not configured')}"
    )

    subject = st.text_input(

        "Email Subject",

        value=f"🚨 Flood Emergency Alert for {target}",

        key="admin_message_subject"

    )

    message = st.text_area(

        "Emergency Message",

        value=(
            "🚨 EMERGENCY ALERT\n\n"
            "Please respond immediately to the current "
            "flood situation."
        ),

        height=140,

        key="admin_emergency_message"

    )

    col1, col2 = st.columns(2)

    with col1:

        if st.button(
            f"📨 Send to {target}",
            width="stretch",
            key="admin_send_single"
        ):

            if message.strip():

                # Sending logic is UNCHANGED — same call as
                # before. Only the feedback + form-clear below
                # is new.
                send_emergency_notification(
                    target,
                    message.strip(),
                    subject.strip()
                )

                st.session_state.admin_message_last_success = (
                    f"✅ Message sent successfully to {target} "
                    f"({EMERGENCY_EMAILS.get(target)})."
                )

                st.session_state.admin_message_clear_pending = True

                st.rerun()

            else:

                st.warning(
                    "Please enter a message."
                )

    with col2:

        if st.button(
            "🚨 Send to ALL",
            width="stretch",
            key="admin_send_all"
        ):

            if message.strip():

                for role in [

                    "Police",

                    "Fire Service",

                    "Hospital",

                    "Municipality"

                ]:

                    send_emergency_notification(
                        role,
                        message.strip(),
                        subject.strip()
                    )

                st.session_state.admin_message_last_success = (
                    "✅ Emails sent successfully to all emergency "
                    "organizations (Police, Fire Service, "
                    "Hospital, Municipality)."
                )

                st.session_state.admin_message_clear_pending = True

                st.rerun()

            else:

                st.warning(
                    "Please enter a message."
                )


# ============================================================
# EMAIL / MAIL SERVER PANEL (ADMIN)
# ============================================================

def mail_server_panel():

    st.subheader(
        "📧 Email Server (SMTP) Status"
    )

    st.success(
        f"🟢 {MAIL_SERVER_NAME} — Online  |  "
        f"Sending as: {ADMIN_EMAIL}"
    )

    with st.expander(
        "📇 Emergency Organization Mailboxes"
    ):

        mailbox_df = pd.DataFrame([

            {
                "Organization": role,
                "Domain": EMERGENCY_DOMAINS.get(role),
                "Email Address": address
            }

            for role, address in EMERGENCY_EMAILS.items()

        ])

        st.dataframe(
            mailbox_df,
            width="stretch",
            hide_index=True
        )

    email_log = get_email_log()

    st.write(
        f"**Outgoing Mail Log** — {len(email_log)} email(s) sent"
    )

    if email_log.empty:

        st.info(
            "No emails have been sent yet. Use the messaging "
            "or emergency siren tools above to send one."
        )

    else:

        st.dataframe(

            email_log[[
                "timestamp",
                "sender",
                "recipient",
                "target_role",
                "subject",
                "status"
            ]],

            width="stretch",

            hide_index=True

        )


# ============================================================
# ORGANIZATION EMAIL CENTER UI (Inbox / Sent / Compose / Bin)
# ============================================================
#
# This is the SAME "Admin -> Emergency Organization Messaging"
# / email_log feature, generalized so every role (Administrator,
# Police, Fire Service, Hospital, Municipality) gets a full
# mailbox on top of it — not a second, separate email system.
# All reads/writes here go through the email_log-backed
# functions above (send_email, get_email_log, get_sent_mail,
# get_bin_mail, mark_email_read, move_email_to_bin,
# restore_email_from_bin, permanently_delete_email).
#
# The sender identity is always `role`, taken from
# st.session_state.role at the call site — never editable by
# the user — so no one can spoof who an email is "From".
# ============================================================

def email_center(role, show_compose=True, recipients_override=None):
    """
    show_compose controls whether a standalone "Compose" tab is
    shown. Administrator already has a dedicated compose surface
    (Emergency Organization Messaging, above), so Admin's call
    passes show_compose=False to avoid a duplicate compose UI.
    All other roles keep their existing Compose tab unchanged.

    `role` here is really a mailbox_key() — a plain role string
    for the original 5 accounts (e.g. "Police"), or a composite
    "<Division> <Role>" string for a hierarchical account (e.g.
    "Dhaka Police"). Every internal key/query below is already
    parametrized on this value, so hierarchical accounts get a
    fully independent Inbox/Sent/Compose/Bin for free.

    recipients_override, when given, replaces the default
    "everyone in ALL_MAIL_ROLES except me" Compose recipient
    list with exactly this list instead — used to enforce the
    division-based access control in the requirements (e.g. a
    Division Admin may only message their own division's three
    organizations, not the whole hierarchy). Legacy call sites
    that don't pass it keep their original recipient list.
    """

    st.subheader("📧 Organization Email")

    st.caption(
        f"Signed in as: {role}  "
        f"({get_role_email(role)})"
    )

    inbox_df = get_email_log(role)
    sent_df = get_sent_mail(role)
    bin_df = get_bin_mail(role)

    unread_count = int(
        (inbox_df["is_read"] == 0).sum()
    ) if not inbox_df.empty else 0

    inbox_label = (
        f"📬 Inbox ({unread_count} unread)"
        if unread_count > 0 else "📬 Inbox"
    )

    if show_compose:

        tab_labels = [
            inbox_label,
            "📤 Sent",
            "✉️ Compose",
            "🗑️ Bin"
        ]

        inbox_tab, sent_tab, compose_tab, bin_tab = st.tabs(
            tab_labels
        )

    else:

        tab_labels = [
            inbox_label,
            "📤 Sent",
            "🗑️ Bin"
        ]

        inbox_tab, sent_tab, bin_tab = st.tabs(
            tab_labels
        )

        compose_tab = None

    # --------------------------------------------------------
    # INBOX
    # --------------------------------------------------------

    with inbox_tab:

        if inbox_df.empty:

            st.info("Inbox is empty.")

        else:

            for _, row in inbox_df.iterrows():

                mail_id = int(row["id"])

                read_icon = "📖" if row["is_read"] else "🔵"

                sender_role = row["sender_role"] or "Administrator"

                header = (
                    f"{read_icon} **From:** {sender_role}  "
                    f"|  **Subject:** {row['subject']}  "
                    f"|  **Time:** {row['timestamp']}"
                )

                # A stable key (based on mail_id, not the label
                # text) so Streamlit remembers whether THIS
                # specific email is expanded even after the
                # header's read-icon changes on the next rerun.
                expander_key = f"inbox_expander_{role}_{mail_id}"

                with st.expander(header, key=expander_key):

                    st.markdown(
                        f"**From:** {sender_role} "
                        f"({row['sender']})\n\n"
                        f"**To:** {role} "
                        f"({row['recipient']})\n\n"
                        f"**Subject:** {row['subject']}\n\n"
                        f"**Time:** {row['timestamp']}\n\n"
                        "---\n\n"
                        f"{row['body']}"
                    )

                    if st.button(
                        "🗑️ Delete",
                        key=f"inbox_delete_{role}_{mail_id}"
                    ):
                        move_email_to_bin(mail_id, role)
                        st.rerun()

                # The body of a `with st.expander(...)` block
                # always executes on every rerun regardless of
                # collapsed/expanded state — only the expander's
                # key tells us whether the USER has actually
                # opened it. So the "mark as read" side effect is
                # done out here, gated on the expander's real
                # expanded state, not unconditionally per row.
                # This is what makes the unread count drop by
                # exactly one each time a single email is opened,
                # instead of every unread email in the list being
                # marked read at once just because the Inbox tab
                # was rendered.
                if (
                    st.session_state.get(expander_key, False)
                    and not row["is_read"]
                ):
                    mark_email_read(mail_id, role)
                    st.rerun()

    # --------------------------------------------------------
    # SENT
    # --------------------------------------------------------

    with sent_tab:

        if sent_df.empty:

            st.info("No sent emails yet.")

        else:

            for _, row in sent_df.iterrows():

                mail_id = int(row["id"])

                header = (
                    f"**To:** {row['target_role']}  "
                    f"|  **Subject:** {row['subject']}  "
                    f"|  **Time:** {row['timestamp']}"
                )

                with st.expander(header):

                    st.markdown(
                        f"**From:** {role} "
                        f"({row['sender']})\n\n"
                        f"**To:** {row['target_role']} "
                        f"({row['recipient']})\n\n"
                        f"**Subject:** {row['subject']}\n\n"
                        f"**Time:** {row['timestamp']}\n\n"
                        "---\n\n"
                        f"{row['body']}"
                    )

                    if st.button(
                        "🗑️ Delete",
                        key=f"sent_delete_{role}_{mail_id}"
                    ):
                        move_email_to_bin(mail_id, role)
                        st.rerun()

    # --------------------------------------------------------
    # COMPOSE
    # --------------------------------------------------------
    # Only rendered when show_compose is True. Administrator
    # does NOT get this tab — Admin sends mail exclusively
    # through "Emergency Organization Messaging", so no
    # duplicate compose surface is created for that role.
    # --------------------------------------------------------

    if show_compose:

        with compose_tab:

            # ------------------------------------------------
            # Reset compose fields BEFORE the widgets below are
            # created, same pattern as Admin's messaging panel:
            # a widget's session_state value can only be
            # reassigned before that widget is instantiated on
            # a given run. A successful send (below) sets this
            # flag and reruns; on the very next run we clear the
            # fields here, ahead of the selectbox/text_input/
            # text_area calls. Keyed per role so clearing one
            # organization's Compose tab never touches another's.
            # ------------------------------------------------

            clear_key = f"compose_clear_pending_{role}"

            if st.session_state.get(clear_key, False):

                st.session_state[f"compose_subject_{role}"] = ""

                st.session_state[f"compose_body_{role}"] = ""

                st.session_state[clear_key] = False

            # One-shot success message carried over from the
            # previous (successful) send via st.rerun(). Shown
            # once here, then discarded so it doesn't linger.
            # (Previously the code called st.success() and then
            # st.rerun() in the same click — the rerun replaced
            # the page before the message could ever be seen.)

            success_key = f"compose_last_success_{role}"

            if st.session_state.get(success_key):

                st.success(st.session_state[success_key])

                del st.session_state[success_key]

            # recipients_override, when given, replaces the
            # default "everyone except me" list — every caller
            # that passes it is guaranteed (by construction) to
            # pass a non-empty list.
            recipients = (
                recipients_override
                if recipients_override is not None
                else [r for r in ALL_MAIL_ROLES if r != role]
            )

            recipient = st.selectbox(
                "To:",
                recipients,
                key=f"compose_to_{role}"
            )

            st.caption(
                f"Mailbox: {get_role_email(recipient)}"
            )

            subject = st.text_input(
                "Subject:",
                key=f"compose_subject_{role}"
            )

            body = st.text_area(
                "Message:",
                height=140,
                key=f"compose_body_{role}"
            )

            if st.button(
                "✉️ Send Email",
                key=f"compose_send_{role}",
                width="stretch"
            ):

                if not subject.strip() or not body.strip():

                    st.warning(
                        "Please enter both a subject and a message."
                    )

                else:

                    # Sender is ALWAYS the authenticated session
                    # role — never something chosen by the user.
                    # Sending logic itself is UNCHANGED.
                    send_email(
                        role,
                        recipient,
                        subject.strip(),
                        body.strip()
                    )

                    st.session_state[success_key] = (
                        f"✅ Email sent successfully to {recipient} "
                        f"({get_role_email(recipient)})."
                    )

                    st.session_state[clear_key] = True

                    st.rerun()

    # --------------------------------------------------------
    # BIN
    # --------------------------------------------------------

    with bin_tab:

        if bin_df.empty:

            st.info("Bin is empty.")

        else:

            st.caption(
                "Deleted emails stay here until you permanently "
                "delete them. This is only YOUR bin — deleting "
                "or restoring here never affects the other "
                "party's copy."
            )

            # ----------------------------------------------
            # EMPTY BIN (with confirmation step)
            # ----------------------------------------------
            # Affects ONLY this owner_role's own Bin rows
            # (in_bin = 1). Never touches this role's own
            # Inbox/Sent (in_bin = 0), and never touches any
            # other role's mailbox at all — enforced by the
            # "WHERE owner_role = ?" in empty_bin().
            # ----------------------------------------------

            confirm_key = f"confirm_empty_bin_{role}"

            if st.session_state.get(confirm_key, False):

                st.warning(
                    "Are you sure you want to permanently "
                    "delete all emails in your Bin? This "
                    "cannot be undone."
                )

                confirm_col, cancel_col = st.columns(2)

                with confirm_col:

                    if st.button(
                        "✅ Yes, empty my Bin",
                        key=f"empty_bin_confirm_{role}",
                        width="stretch"
                    ):
                        empty_bin(role)
                        st.session_state[confirm_key] = False
                        st.success("Your Bin has been emptied.")
                        st.rerun()

                with cancel_col:

                    if st.button(
                        "Cancel",
                        key=f"empty_bin_cancel_{role}",
                        width="stretch"
                    ):
                        st.session_state[confirm_key] = False
                        st.rerun()

            else:

                if st.button(
                    "🗑️ Empty Bin",
                    key=f"empty_bin_btn_{role}"
                ):
                    st.session_state[confirm_key] = True
                    st.rerun()

            st.divider()

            # ----------------------------------------------
            # BIN LIST — direct Restore / Delete Permanently
            # icons beside each email, no need to open it
            # first. An optional expander is still available
            # underneath for viewing the full message.
            # ----------------------------------------------

            for _, row in bin_df.iterrows():

                mail_id = int(row["id"])

                if row["folder"] == "inbox":
                    counterpart_label = (
                        f"From: {row['sender_role'] or 'Administrator'}"
                    )
                else:
                    counterpart_label = (
                        f"To: {row['target_role']}"
                    )

                info_col, restore_col, delete_col = st.columns(
                    [6, 1, 1]
                )

                with info_col:

                    st.markdown(
                        f"🗑️ **{counterpart_label}**  |  "
                        f"**Subject:** {row['subject']}  |  "
                        f"**Deleted:** {row['deleted_at']}"
                    )

                with restore_col:

                    if st.button(
                        "↩️",
                        key=f"bin_restore_{role}_{mail_id}",
                        help="Restore",
                        width="stretch"
                    ):
                        restore_email_from_bin(mail_id, role)
                        st.rerun()

                with delete_col:

                    if st.button(
                        "🗑️",
                        key=f"bin_permadelete_{role}_{mail_id}",
                        help="Delete Permanently",
                        width="stretch"
                    ):
                        permanently_delete_email(mail_id, role)
                        st.rerun()

                with st.expander("🔍 View email"):

                    st.markdown(
                        f"**From:** {row['sender_role'] or 'Administrator'}\n\n"
                        f"**To:** {row['target_role']}\n\n"
                        f"**Subject:** {row['subject']}\n\n"
                        f"**Time:** {row['timestamp']}\n\n"
                        "---\n\n"
                        f"{row['body']}"
                    )

                st.divider()



# ============================================================
# EMERGENCY SIREN
# ============================================================

def emergency_siren():

    # _html_no_indent() strips leading whitespace from every
    # line first — otherwise Markdown treats the indented lines
    # below as a preformatted code block and shows the raw
    # <div>/<h1>/<p> tags as literal text instead of rendering
    # them (the same bug that affected the emergency alert
    # banner). This header was affected by that bug too, even
    # before the new alert system was added.
    st.markdown(
        _html_no_indent("""
        <div style="
        background-color:#8B0000;
        padding:20px;
        border-radius:12px;
        text-align:center;
        color:white;
        margin-bottom:20px;
        ">

        <h1>🚨 EMERGENCY SIREN</h1>

        <p>
        Select the emergency organization you want to notify.
        </p>

        </div>
        """),
        unsafe_allow_html=True
    )

    st.warning(
        "⚠️ Activating an emergency notification will immediately "
        "create an alert in the selected organization's portal."
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        if st.button(
            "👮 CALL POLICE",
            width="stretch"
        ):

            send_emergency_notification(
                "Police"
            )

            # NEW blinking + sound alert system, ADDITIONAL to
            # the existing notification above — does not touch
            # or replace it.
            create_emergency_alert(
                st.session_state.username,
                ["Police"],
                "Emergency Siren Activated",
                "Police have been called for an active flood "
                "emergency. Please respond immediately.",
                level="CRITICAL"
            )

            st.success(
                "🚨 Emergency notification sent to Police."
            )

    with col2:

        if st.button(
            "🚒 CALL FIRE SERVICE",
            width="stretch"
        ):

            send_emergency_notification(
                "Fire Service"
            )

            create_emergency_alert(
                st.session_state.username,
                ["Fire Service"],
                "Emergency Siren Activated",
                "Fire Service has been called for an active "
                "flood emergency. Please respond immediately.",
                level="CRITICAL"
            )

            st.success(
                "🚨 Emergency notification sent to Fire Service."
            )

    with col3:

        if st.button(
            "🏥 CALL HOSPITAL",
            width="stretch"
        ):

            send_emergency_notification(
                "Hospital"
            )

            create_emergency_alert(
                st.session_state.username,
                ["Hospital"],
                "Emergency Siren Activated",
                "Hospital has been called for an active flood "
                "emergency. Please respond immediately.",
                level="CRITICAL"
            )

            st.success(
                "🚨 Emergency notification sent to Hospital."
            )

    st.divider()

    st.subheader(
        "📢 Notify All Emergency Organizations"
    )

    if st.button(
        "🚨 CALL POLICE + FIRE + HOSPITAL + MUNICIPALITY",
        width="stretch"
    ):

        for role in [

            "Police",

            "Fire Service",

            "Hospital",

            "Municipality"

        ]:

            send_emergency_notification(
                role
            )

        # NEW blinking + sound alert system. Targets the same
        # Police / Fire Service / Hospital organizations named
        # in the requirements; Municipality's existing behavior
        # (the send_emergency_notification loop above) is left
        # exactly as it was — it is not part of the new
        # blink/sound system, per the requirements only naming
        # Police, Fire Service and Hospital as its targets.
        create_emergency_alert(
            st.session_state.username,
            ["Police", "Fire Service", "Hospital"],
            "Flood Emergency — All Organizations Notified",
            "The Administrator has activated an emergency "
            "alert for all emergency organizations. Please "
            "respond immediately.",
            level="CRITICAL"
        )

        st.success(
            "🚨 Emergency notifications sent to all emergency organizations."
        )


# ============================================================
# HYBRID PREDICTION DISPLAY (shared across dashboards)
# ============================================================

def render_hybrid_prediction_details(selected_row):
    """
    Shows the system's Predicted Water Level for one reading.

    This intentionally does NOT expose which internal model
    component(s) produced the prediction, physics/ML sub-scores,
    model names, or any other technical breakdown — the
    prediction engine itself (see hybrid_model.py) is unchanged
    and fully implemented, but normal dashboard users are only
    shown the system's plain-language outputs (Flood Probability,
    Prediction, Predicted Water Level, Flood Risk Status), not
    how they were produced internally.

    Degrades gracefully and silently for any row that predates
    this upgrade (missing the new columns) — never errors.
    """

    if "predicted_water_level" not in selected_row.index:
        return

    if pd.isna(selected_row.get("predicted_water_level")):
        return

    st.metric(
        "🌊 Predicted Water Level",
        f"{selected_row['predicted_water_level']} m"
    )


# ============================================================
# SHARED FLOOD-PROBABILITY GAUGE
# ============================================================
# ONE gauge implementation, reused identically by every
# dashboard that shows a single location's prediction
# (organization_dashboard — Police/Fire Service/Hospital/
# Municipality/District Police/District Fire Service/District
# Municipality — plus admin_dashboard i.e. District Admin,
# division_admin_dashboard, and the public dashboard) so the
# same reading always looks the same everywhere. Risk-zone
# colors and the threshold line match classify_risk() EXACTLY
# (Low < 50, Moderate 50-69.99, High 70-89.99, Severe >= 90),
# so the gauge can never visually disagree with the risk badge
# shown next to it.
# ============================================================

RISK_ZONE_COLOR = {
    "Low": "#2ecc71",
    "Moderate": "#f1c40f",
    "High": "#e67e22",
    "Severe": "#e74c3c"
}


def render_flood_probability_gauge(
    probability,
    risk_level=None,
    label="Flood Probability"
):
    """
    Renders one fixed 0-100% flood-probability gauge plus a
    large, color-matched risk-level line underneath it.

    `probability` must be the REAL hybrid-model
    flood_probability value already used everywhere else in the
    app (the map, the risk badge, the automatic-alert check) —
    this function only visualizes that number, it never
    computes, estimates, or overrides it. `risk_level` is
    optional; if omitted it's derived from `probability` via
    classify_risk() itself, so the label and the gauge's colored
    zones are always self-consistent.
    """

    if probability is None or (
        isinstance(probability, float) and pd.isna(probability)
    ):
        return

    probability = float(probability)

    if risk_level is None:
        risk_level = classify_risk(probability)

    bar_color = RISK_ZONE_COLOR.get(risk_level, "#34495e")

    gauge_figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=probability,
            number={
                "suffix": "%",
                "font": {"size": 46}
            },
            title={
                "text": label,
                "font": {"size": 16}
            },
            gauge={
                "axis": {
                    "range": [0, 100],
                    "tickmode": "array",
                    "tickvals": [0, 50, 70, 90, 100],
                    "tickwidth": 1
                },
                "bar": {
                    "color": bar_color,
                    "thickness": 0.30
                },
                "bgcolor": "#262730",
                "borderwidth": 1,
                "bordercolor": "#4a4a55",
                # Steps double as a fixed color-coded legend for
                # the 4 risk zones — always the same 4 boundaries
                # as classify_risk(), regardless of the current
                # value. Darker/muted tints (instead of near-white
                # pastels) so they still read as a light-to-dark
                # risk gradient on the dark gauge card, without
                # glaring against the surrounding dark UI.
                "steps": [
                    {"range": [0, 50], "color": "#1e3d2f"},
                    {"range": [50, 70], "color": "#4a3f14"},
                    {"range": [70, 90], "color": "#4d3419"},
                    {"range": [90, 100], "color": "#4d1f1c"}
                ],
                # A bold red line right at the Severe cutoff
                # (90%) makes it visually unmistakable whenever
                # the bar reaches or crosses it.
                "threshold": {
                    "line": {"color": "#c0392b", "width": 5},
                    "thickness": 0.92,
                    "value": 90
                }
            }
        )
    )

    gauge_figure.update_layout(
        height=300,
        margin={"l": 25, "r": 25, "t": 55, "b": 15},
        # Explicitly opaque, regardless of whether the Streamlit
        # app itself is in light or dark mode. Originally this used
        # a hardcoded white card (#ffffff bg + #1a1a1a text) so it
        # would never go invisible on a dark page — but that made
        # it a glaring white box in night mode. Switched to a dark
        # "card" (#262730, matching Streamlit's own dark-theme
        # secondary background) with light text instead, so it
        # still reads correctly and stays self-consistent
        # regardless of theme, but no longer looks like a bright
        # white hole punched into a dark page. This is a fixed
        # dark card (not a theme-adaptive one) since Streamlit's
        # active theme isn't reliably queryable across versions/
        # activation methods (OS-level dark mode, config.toml, or
        # the in-app toggle can all enable it) — if the app is
        # normally used in light mode too, consider detecting
        # st.get_option("theme.base") and swapping palettes.
        paper_bgcolor="#262730",
        plot_bgcolor="#262730",
        font={"color": "#fafafa"}
    )

    st.plotly_chart(
        gauge_figure,
        width="stretch"
    )

    risk_circle = RISK_CIRCLE.get(risk_level, "")

    st.markdown(
        f"<div style='text-align:center; font-size:1.4rem; "
        f"font-weight:700; margin-top:-8px; color:#fafafa; "
        f"background-color:#262730; border-radius:0 0 8px 8px; "
        f"padding:6px 0 10px 0;'>"
        f"{risk_circle} {risk_level} Risk — {probability:.1f}% "
        f"flood probability</div>",
        unsafe_allow_html=True
    )


def render_model_information_panel():
    """
    A dedicated, compact model-transparency panel — real training
    metrics (not fabricated), computed once when the model was
    trained. Intended for anyone (including a researcher/
    reviewer) who wants to check what's actually running under
    the hood, beyond the per-prediction explanation in
    render_hybrid_prediction_details().
    """

    model_bundle = get_trained_hybrid_model()

    st.markdown(
        "### Hybrid Physics + Machine Learning Flood Prediction "
        "Framework"
    )

    physics_text = _html_no_indent("""
    **Physics / Mathematical Component**

    A reduced-order water-balance / linear-reservoir model —
    explicitly NOT a full Saint-Venant shallow-water solver (out
    of scope for a real-time Streamlit prototype). It computes:

    - Runoff coefficient from soil moisture (saturated soil ->
      more runoff), in the spirit of an SCS curve-number
      approach
    - Estimated inflow: river flow + rainfall-driven runoff
    - Estimated outflow: a linear-reservoir term proportional to
      current water level
    - A small temperature-driven evaporation loss
    - Net water balance and a resulting predicted water-level
      change over a short time step

    See `hybrid_model.py` (`run_physics_model`) for the exact,
    fully-commented formulas and constants.
    """)

    st.markdown(physics_text)

    if model_bundle.get("available"):

        ml_text = _html_no_indent(f"""
        **Machine Learning Component**

        Model: **{model_bundle['model_name']}**, genuinely
        trained via `.fit()` on a physics-informed synthetic
        dataset (there's no bundled real historical flood
        dataset for Bangladesh in this app — see the honesty
        note at the top of `hybrid_model.py`).

        - Training samples: **{model_bundle['n_training_samples']}**
        - Held-out test samples: **{model_bundle['n_test_samples']}**
        - Test R² score: **{model_bundle['r2_score']}**
        - Test MAE: **{model_bundle['mae']}** probability points

        These are the actual metrics from the model that is
        running right now, computed on data it was NOT trained
        on — not hard-coded placeholder numbers.
        """)

        st.markdown(ml_text)

        with st.expander("📊 Feature importances (from the trained model)"):

            importances_df = pd.DataFrame(
                sorted(
                    model_bundle["feature_importances"].items(),
                    key=lambda item: -item[1]
                ),
                columns=["Feature", "Importance"]
            )

            st.dataframe(
                importances_df,
                width="stretch",
                hide_index=True
            )

    else:

        st.error(
            model_bundle.get(
                "error",
                "The ML component is unavailable."
            )
        )

    hybrid_text = _html_no_indent(f"""
    **Hybrid Combination**

    Final probability = **{hybrid_model.HYBRID_ML_WEIGHT * 100:.0f}%
    x ML prediction + {hybrid_model.HYBRID_PHYSICS_WEIGHT * 100:.0f}%
    x physics-only estimate** (when the ML component is
    available; physics-only otherwise). The ML model's own inputs
    already include every physics-derived feature above, so the
    physics component shapes the final result twice over — once
    through those learned features, and once directly in this
    blend.
    """)

    st.markdown(hybrid_text)


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

        st.caption(
            f"Flood monitoring, sensor management, prediction "
            f"and emergency response for {district} District only"
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

        st.info(
            """
            The system supports simulated sensor data and
            external CSV dataset input.

            Real sensors can later be connected using:
            ESP32, Arduino, MQTT, REST API or another IoT gateway.
            """
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
                format="%.6f"
            )

            longitude = st.number_input(
                "Longitude",
                value=90.4125,
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

        description = (
            "Flood monitoring and prediction "
            "for emergency medical preparedness."
        )

    elif "Fire Service" in role:

        icon = "🚒"

        description = (
            "Flood monitoring and prediction "
            "for rescue and emergency response."
        )

    elif "Municipality" in role:

        icon = "🏛️"

        description = (
            "Flood monitoring and prediction "
            "for municipal coordination and public safety."
        )

    else:

        icon = "👮"

        description = (
            "Flood monitoring and prediction "
            "for public safety and emergency response."
        )

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

    st.info(
        description
    )

    if division:

        st.caption(
            f"👤 Role: {role}  |  Division: {division}  |  "
            f"Area: {st.session_state.get('area') or '—'}"
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

    # ========================================================
    # SENSOR REGISTRATION + EXTERNAL DATASET INPUT
    # ========================================================
    # REMOVED for Police / Fire Service / Hospital / Municipality
    # (every variant this dashboard serves — legacy, division-
    # scoped, district-scoped). Only Administrator, District
    # Admin, Division Admin, and System Handler can register
    # sensors or upload datasets now; those roles each render
    # their own sensor_and_dataset_management_section() call in
    # their own dashboard functions, unaffected by this removal.
    # ========================================================


# ============================================================
# PUBLIC DASHBOARD
# ============================================================

def public_dashboard():

    st.title(
        "🌊 Flood Forecast & Public Monitoring Portal"
    )

    st.write(
        "Select a Division, then a District, to view current "
        "flood conditions and prediction for that district."
    )

    readings = (
        generate_all_sensor_data()
    )

    if readings.empty:

        st.warning(
            "No sensor readings are currently available."
        )

        return

    # --------------------------------------------------------
    # DIVISION -> DISTRICT DRILL-DOWN
    # --------------------------------------------------------
    # Two-step selector: pick one of the 8 divisions first, then
    # one of ONLY that division's real districts — matches how
    # a Division Admin/District Admin picks a location elsewhere
    # in the app, so the public portal behaves the same way.
    # --------------------------------------------------------

    division_col, district_col = st.columns(2)

    with division_col:

        selected_division = st.selectbox(
            "🗺️ Select Division",
            BD_DIVISIONS,
            key="public_division"
        )

    district_options = DIVISION_AREAS.get(selected_division, [])

    with district_col:

        selected_location = st.selectbox(
            "📍 Select District",
            district_options,
            key=f"public_district_{selected_division}"
        )

    division_readings = readings[
        readings["location"].isin(district_options)
    ]

    if division_readings.empty or selected_location not in (
        division_readings["location"].tolist()
    ):

        st.warning(
            f"No sensor readings are currently available for "
            f"{selected_location}."
        )

        return

    selected = division_readings[
        division_readings[
            "location"
        ] == selected_location
    ].iloc[0]

    st.divider()

    # ========================================================
    # CURRENT CONDITIONS
    # ========================================================

    st.subheader(
        f"📍 {selected_location} ({selected_division} Division)"
    )

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
            f"🟢 Flood Risk: {risk}"
        )

    elif risk == "Moderate":

        st.warning(
            f"🟡 Flood Risk: {risk}"
        )

    elif risk == "High":

        st.warning(
            f"🟠 Flood Risk: {risk}"
        )

    else:

        st.error(
            f"🔴 Flood Risk: {risk}"
        )

    st.caption(
        f"Data Source: {selected['data_source']}"
    )

    st.divider()

    # ========================================================
    # PREDICTION
    # ========================================================

    st.subheader(
        "🤖 Flood Prediction"
    )

    # Uses the REAL hybrid physics/ML model's predicted_water_level
    # (already computed in `selected` by hybrid_flood_prediction),
    # not an ad-hoc recomputation — so this always agrees with the
    # flood probability and risk level shown elsewhere on this
    # same reading.

    col1, col2 = st.columns(2)

    with col1:

        st.metric(
            "Current Water Level",
            f"{selected['water_level']} m"
        )

        st.metric(
            "Predicted Water Level",
            f"{selected['predicted_water_level']:.2f} m"
        )

    with col2:

        st.metric(
            "🤖 Flood Probability",
            f"{selected['flood_probability']}%"
        )

        st.metric(
            "⚠️ Risk Level",
            selected.get("risk_level", "—")
        )

    render_flood_probability_gauge(
        selected["flood_probability"],
        risk_level=selected.get("risk_level"),
        label="Flood Probability"
    )

    st.divider()

    # ========================================================
    # FLOOD MAP
    # ========================================================

    st.subheader(
        "🌍 Live Flood Location Map"
    )

    st.caption(
        f"Showing every district in **{selected_division} "
        f"Division**, centered on **{selected_location}** — "
        f"change the selectors above to jump to a different "
        f"district or division."
    )

    st.plotly_chart(

        create_flood_map(
            division_readings,
            focus_location=selected_location
        ),

        width="stretch"

    )

    st.caption(
        "🟢 Low   🟡 Moderate   🟠 High   🔴 Severe — each "
        "marker is labeled with its location and current risk."
    )

    st.caption(
        f"Last updated: {selected['timestamp']}"
    )


# ============================================================
# SIDEBAR
# ============================================================

def sidebar():

    st.sidebar.title(
        "🌊 Flood Portal"
    )

    st.sidebar.divider()

    # Bridge to the real browser cookie used for "remember this
    # device" (Administrator OTP step only). Constructed once
    # per rerun — cheap — and used by both branches below.
    cookie_controller = get_cookie_controller()

    # --------------------------------------------------------
    # LOGGED-IN USER
    # --------------------------------------------------------

    if st.session_state.get(
        "logged_in",
        False
    ):

        st.sidebar.success(
            f"👤 {st.session_state.username}"
        )

        if st.session_state.get("division"):

            st.sidebar.write(
                f"Role: **{st.session_state.role}** "
                f"({st.session_state.division})"
            )

        elif st.session_state.get("district"):

            st.sidebar.write(
                f"Role: **{st.session_state.role}** "
                f"({st.session_state.district} District)"
            )

        else:

            st.sidebar.write(
                f"Role: **{st.session_state.role}**"
            )

        # --------------------------------------------------
        # 🚨 Emergency Alerts indicator (new blink/sound
        # system). Shown for every role that can receive an
        # emergency alert — every organization role, legacy
        # or division-specific, plus Division Admin and
        # District Admin. Uses the exact same mailbox_key() as
        # the dashboards themselves, so the count here always
        # matches what that dashboard's banner is showing.
        # --------------------------------------------------

        alert_recipient_roles = (
            "Police", "Fire Service", "Hospital",
            "Municipality", "Division Admin", "District Admin",
            "District Police", "District Fire Service",
            "District Municipality"
        )

        district_tier_roles = (
            "District Admin", "District Police",
            "District Fire Service", "District Municipality"
        )

        if st.session_state.role in alert_recipient_roles:

            if st.session_state.role in district_tier_roles:

                sidebar_mailbox = mailbox_key(
                    st.session_state.role,
                    st.session_state.get("district")
                )

            else:

                sidebar_mailbox = mailbox_key(
                    st.session_state.role,
                    st.session_state.get("division")
                )

            unread_alert_count = (
                get_unread_emergency_alert_count(
                    sidebar_mailbox
                )
            )

            if unread_alert_count > 0:

                st.sidebar.error(
                    f"🚨 Emergency Alerts: {unread_alert_count}"
                )

            else:

                st.sidebar.caption(
                    "Emergency Alerts: 0"
                )

        st.sidebar.divider()

        if st.sidebar.button(
            "🚪 Logout",
            width="stretch"
        ):

            st.session_state.logged_in = False

            st.session_state.username = None

            st.session_state.role = None

            st.session_state.division = None

            st.session_state.area = None

            st.session_state.district = None

            st.session_state.show_emergency_panel = False

            st.session_state.admin_2fa_pending = False

            st.session_state.admin_2fa_username = None

            st.rerun()

        # Logging out intentionally does NOT revoke a trusted
        # device — that is the whole point of "remember this
        # device" (skip OTP again after logging back in). This
        # button is the explicit, separate way to revoke it.
        if st.session_state.role == "System Handler":

            if st.sidebar.button(
                "🔓 Forget this device",
                width="stretch",
                key="forget_device_button"
            ):

                forget_all_trusted_devices(
                    st.session_state.username
                )

                safe_remove_cookie(
                    cookie_controller,
                    ADMIN_TRUSTED_DEVICE_COOKIE_NAME
                )

                st.sidebar.success(
                    "This device will require a code on the "
                    "next admin login."
                )

    # --------------------------------------------------------
    # LOGIN
    # --------------------------------------------------------

    else:

        # ----------------------------------------------------
        # STEP 2 OF ADMIN LOGIN: waiting for the OTP that was
        # emailed after a correct Administrator password.
        # Only ever entered for Administrator accounts — every
        # other role never sets admin_2fa_pending and always
        # falls through to the ordinary password form below,
        # completely unchanged.
        # ----------------------------------------------------

        if st.session_state.get("admin_2fa_pending"):

            otp_username = st.session_state.get(
                "admin_2fa_username"
            )

            st.sidebar.subheader(
                "📧 Enter Login Code"
            )

            st.sidebar.caption(
                f"A {ADMIN_OTP_LENGTH}-digit code was emailed "
                f"to the configured admin address for "
                f"**{otp_username}**. It expires in "
                f"{ADMIN_OTP_VALID_MINUTES} minutes and can "
                f"only be used once."
            )

            with st.sidebar.form(
                "admin_otp_form",
                clear_on_submit=False
            ):

                otp_input = st.text_input(
                    "6-digit code",
                    key="admin_otp_input",
                    max_chars=ADMIN_OTP_LENGTH
                )

                remember_device = st.checkbox(
                    f"Remember this device for "
                    f"{ADMIN_TRUSTED_DEVICE_DAYS} days "
                    f"(skip the code next time)",
                    value=False,
                    key="admin_otp_remember_device"
                )

                otp_submitted = st.form_submit_button(
                    "Verify Code",
                    width="stretch"
                )

            resend_col, cancel_col = st.sidebar.columns(2)

            cooldown_remaining = (
                admin_otp_resend_cooldown_remaining(
                    otp_username
                )
            )

            resend_label = "🔁 Resend OTP"

            if cooldown_remaining:
                resend_label += f" ({cooldown_remaining}s)"

            resend_clicked = resend_col.button(
                resend_label,
                width="stretch",
                disabled=cooldown_remaining > 0,
                key="admin_otp_resend"
            )

            cancel_clicked = cancel_col.button(
                "✖️ Cancel",
                width="stretch",
                key="admin_otp_cancel"
            )

            if otp_submitted:

                if (
                    not otp_input
                    or not otp_input.isdigit()
                    or len(otp_input) != ADMIN_OTP_LENGTH
                ):

                    st.sidebar.error(
                        f"Enter the {ADMIN_OTP_LENGTH}-digit "
                        f"code."
                    )

                else:

                    verdict = verify_admin_otp(
                        otp_username,
                        otp_input
                    )

                    if verdict == "ok":

                        if remember_device:

                            new_token = add_trusted_device(
                                otp_username
                            )

                            safe_set_cookie(
                                cookie_controller,
                                ADMIN_TRUSTED_DEVICE_COOKIE_NAME,
                                new_token,
                                max_age_seconds=(
                                    ADMIN_TRUSTED_DEVICE_DAYS
                                    * 24 * 60 * 60
                                )
                            )

                        st.session_state.logged_in = True

                        st.session_state.username = otp_username

                        st.session_state.role = "System Handler"

                        st.session_state.division = None

                        st.session_state.area = None

                        st.session_state.district = None

                        st.session_state.show_emergency_panel = (
                            False
                        )

                        st.session_state.admin_2fa_pending = False

                        st.session_state.admin_2fa_username = None

                        st.rerun()

                    elif verdict == "expired":

                        st.sidebar.error(
                            "This code has expired. Use "
                            "Resend OTP to get a new one."
                        )

                    elif verdict == "no_otp":

                        st.sidebar.error(
                            "No active code for this session. "
                            "Use Resend OTP to get a new one."
                        )

                    elif verdict == "locked_out":

                        st.sidebar.error(
                            "Too many incorrect codes. Please "
                            "log in again to request a new "
                            "code."
                        )

                        st.session_state.admin_2fa_pending = False

                        st.session_state.admin_2fa_username = None

                    else:

                        st.sidebar.error(
                            "Incorrect code. Please try again."
                        )

            if resend_clicked:

                otp_success, otp_error = (
                    generate_and_send_admin_otp(otp_username)
                )

                if otp_success:
                    st.sidebar.success(
                        "A new code has been sent."
                    )
                else:
                    st.sidebar.error(otp_error)

                st.rerun()

            if cancel_clicked:

                st.session_state.admin_2fa_pending = False

                st.session_state.admin_2fa_username = None

                st.rerun()

        # ----------------------------------------------------
        # STEP 1: username + password (all roles).
        # ----------------------------------------------------

        else:

            st.sidebar.subheader(
                "🔐 Authorized Login"
            )

            # Wrapping the fields + submit button in
            # st.sidebar.form means pressing Enter inside
            # either field submits the form exactly as if
            # "Login" were clicked — Streamlit's built-in
            # form-submit behavior. For every role except
            # Administrator, the authentication call below is
            # unchanged: same authenticate_user() call, same
            # session-state assignment, same error handling as
            # before, just triggered by `submitted` instead of
            # a bare button click. Administrator accounts take
            # a second step (email OTP) before logged_in is
            # ever set — see above.

            with st.sidebar.form(
                "login_form",
                clear_on_submit=False
            ):

                username = st.text_input(
                    "Username",
                    key="login_username"
                )

                password = st.text_input(
                    "Password",
                    type="password",
                    key="login_password"
                )

                submitted = st.form_submit_button(
                    "Login",
                    width="stretch"
                )

            if submitted:

                # Look up the account's role first, WITHOUT
                # checking the password yet — purely to decide
                # whether this attempt needs the Administrator
                # lockout / 2FA path. This never reveals
                # whether the password itself is correct.

                conn = get_connection()

                role_row = conn.execute(
                    """
                    SELECT role
                    FROM users
                    WHERE username = ?
                    """,
                    (username,)
                ).fetchone()

                conn.close()

                attempted_role = (
                    role_row[0] if role_row else None
                )

                # ------------------------------------------
                # SYSTEM HANDLER: password lockout + email OTP
                # (the only account that ever gets a Gmail OTP
                # — every legacy Administrator/Hospital/Fire
                # Service/Police/Municipality account has been
                # removed entirely).
                # ------------------------------------------

                if attempted_role == "System Handler":

                    locked, seconds_remaining = (
                        is_admin_locked(username)
                    )

                    if locked:

                        minutes_remaining = max(
                            1, seconds_remaining // 60
                        )

                        st.sidebar.error(
                            f"Too many failed attempts. Admin "
                            f"login is locked for about "
                            f"{minutes_remaining} more "
                            f"minute(s)."
                        )

                    else:

                        result = authenticate_user(
                            username,
                            password
                        )

                        if result:

                            reset_admin_password_attempts(
                                username
                            )

                            # Password is correct. Only the OTP
                            # step can ever be skipped by a
                            # trusted device — never the
                            # password itself.
                            device_cookie_value = (
                                safe_get_cookie(
                                    cookie_controller,
                                    ADMIN_TRUSTED_DEVICE_COOKIE_NAME
                                )
                            )

                            if is_trusted_device(
                                username,
                                device_cookie_value
                            ):

                                st.session_state.logged_in = (
                                    True
                                )

                                st.session_state.username = (
                                    username
                                )

                                st.session_state.role = (
                                    "System Handler"
                                )

                                st.session_state.division = None

                                st.session_state.area = None

                                st.session_state.district = None

                                st.session_state.show_emergency_panel = (
                                    False
                                )

                                st.rerun()

                            else:

                                otp_success, otp_error = (
                                    generate_and_send_admin_otp(
                                        username
                                    )
                                )

                                if otp_success:

                                    st.session_state.admin_2fa_pending = (
                                        True
                                    )

                                    st.session_state.admin_2fa_username = (
                                        username
                                    )

                                    st.rerun()

                                else:

                                    st.sidebar.error(otp_error)

                        else:

                            remaining_attempts = (
                                record_failed_admin_password(
                                    username
                                )
                            )

                            if remaining_attempts > 0:

                                st.sidebar.error(
                                    f"Invalid username or "
                                    f"password. "
                                    f"{remaining_attempts} "
                                    f"attempt(s) remaining "
                                    f"before a temporary lock."
                                )

                            else:

                                st.sidebar.error(
                                    f"Too many failed "
                                    f"attempts. Admin login "
                                    f"is now locked for "
                                    f"{ADMIN_PASSWORD_LOCK_MINUTES} "
                                    f"minutes."
                                )

                # ------------------------------------------
                # EVERY OTHER ROLE: unchanged, single-step
                # ------------------------------------------

                else:

                    result = authenticate_user(
                        username,
                        password
                    )

                    if result:

                        st.session_state.logged_in = True

                        st.session_state.username = result[0]

                        st.session_state.role = result[1]

                        st.session_state.division = result[2]

                        st.session_state.area = result[3]

                        st.session_state.district = result[4]

                        st.session_state.show_emergency_panel = (
                            False
                        )

                        st.rerun()

                    else:

                        st.sidebar.error(
                            "Invalid username or password."
                        )


def system_handler_dashboard():
    """
    Highest-level operational role. Oversees all 8 Division
    Admins (and, transitively, the emergency organizations
    under them) without being "just another Admin" — this is a
    completely separate function from admin_dashboard(), with
    its own distinct role string ("System Handler") and its own
    login (the normal single-step username/password form, same
    as Police/Fire Service/Hospital — no 2FA is added here, so
    as to not touch the Administrator-only 2FA code path).
    """

    st.title(
        "🧭 System Handler Control Center"
    )

    st.caption(
        f"👤 {st.session_state.username}  |  Role: System Handler  "
        f"|  Highest-level operational oversight"
    )

    st.info(
        "The System Handler oversees all 8 Division Admins and "
        "the emergency organizations under them, nationwide."
    )

    readings = generate_all_sensor_data()

    # --------------------------------------------------------
    # NATIONWIDE ALERT SUMMARY + BULK CLEAR
    # --------------------------------------------------------
    # A single automatic alert fans out to many mailboxes at
    # once (that district's/division's org accounts), so unread
    # counts can climb quickly if nobody opens those inboxes.
    # This gives System Handler one place to see the true
    # nationwide total and clear it in one click, instead of
    # visiting 300+ mailboxes individually.
    # --------------------------------------------------------

    nationwide_unread = get_total_unread_emergency_alert_count()

    summary_col, button_col = st.columns([3, 1])

    with summary_col:

        if nationwide_unread > 0:

            st.warning(
                f"🚨 {nationwide_unread} unread alert "
                f"notifications nationwide, across every "
                f"division and district mailbox combined. This "
                f"counts every recipient copy of every alert "
                f"separately — one Severe alert can appear as "
                f"10+ unread rows across a division's and "
                f"district's org accounts, so this number is "
                f"expected to be larger than the number of "
                f"actual flood events."
            )

        else:

            st.success(
                "🟢 No unread alert notifications anywhere in "
                "the system."
            )

    with button_col:

        if st.button(
            "🧹 Mark All Read (Nationwide)",
            width="stretch",
            disabled=(nationwide_unread == 0)
        ):

            cleared = mark_all_emergency_alerts_read_nationwide()

            st.success(
                f"Cleared {cleared} unread alert "
                f"notifications nationwide."
            )

            st.rerun()

    st.divider()

    # --------------------------------------------------------
    # 1. SYSTEM OVERVIEW — 8 DIVISION CARDS
    # --------------------------------------------------------

    st.subheader(
        "🗺️ System Overview — 8 Divisions"
    )

    division_summaries = []

    for division in BD_DIVISIONS:

        area_list = DIVISION_AREAS.get(division, [])

        division_readings = (
            readings[readings["location"].isin(area_list)]
            if not readings.empty
            else readings
        )

        if not division_readings.empty:

            avg_probability = (
                division_readings["flood_probability"].mean()
            )

            high_risk_count = len(
                division_readings[
                    division_readings["risk_level"].isin(
                        ["High", "Severe"]
                    )
                ]
            )

        else:

            avg_probability = None

            high_risk_count = 0

        unread_total = get_unread_emergency_alert_count(
            mailbox_key("Division Admin", division)
        )

        for org_role in (
            "Police", "Fire Service", "Hospital", "Municipality"
        ):

            unread_total += get_unread_emergency_alert_count(
                mailbox_key(org_role, division)
            )

        division_summaries.append(
            {
                "division": division,
                "risk_circle": worst_risk_circle(readings, area_list),
                "avg_probability": avg_probability,
                "high_risk_count": high_risk_count,
                "unread_total": unread_total,
                "admin_username": f"{division.lower()}_admin"
            }
        )

    card_columns = st.columns(4) + st.columns(4)

    for card_column, summary in zip(
        card_columns, division_summaries
    ):

        with card_column:

            st.markdown(
                f"#### {summary['risk_circle']} {summary['division']}"
            )

            if summary["avg_probability"] is not None:

                st.metric(
                    "Avg Flood Risk",
                    f"{summary['avg_probability']:.1f}%"
                )

            else:

                st.metric(
                    "Avg Flood Risk",
                    "No data"
                )

            st.caption(
                f"⚠️ High-risk areas: {summary['high_risk_count']}"
            )

            if summary["unread_total"] > 0:

                st.error(
                    f"🚨 {summary['unread_total']} unread"
                )

            else:

                st.success(
                    "🟢 No unread alerts"
                )

            st.caption(
                f"Admin: `{summary['admin_username']}`"
            )

    st.divider()

    # --------------------------------------------------------
    # 1B. ALL 64 DISTRICTS — SEARCHABLE TABLE
    # --------------------------------------------------------
    # The 8 division cards above are a good coarse overview, but
    # with 64 real districts System Handler also needs to drill
    # into any ONE district directly without guessing which
    # division it belongs to — this table covers every district
    # nationwide, filterable by name or by division, sorted
    # worst-risk-first so the most urgent districts surface
    # immediately.
    # --------------------------------------------------------

    st.subheader(
        "🔍 All 64 Districts"
    )

    filter_col1, filter_col2 = st.columns([2, 1])

    with filter_col1:

        district_search = st.text_input(
            "Search by district name",
            key="sh_district_search",
            placeholder="e.g. Gazipur, Cox's Bazar, Rangamati..."
        )

    with filter_col2:

        division_filter = st.selectbox(
            "Filter by division",
            ["All Divisions"] + BD_DIVISIONS,
            key="sh_division_filter"
        )

    district_rows = []

    for district_name in DISTRICT_NAMES:

        division_of_district = get_division_for_location(
            district_name
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

        district_reading = readings[
            readings["location"] == district_name
        ]

        if not district_reading.empty:

            reading_row = district_reading.iloc[0]

            probability = reading_row["flood_probability"]

            risk = reading_row["risk_level"]

        else:

            probability = None

            risk = None

        district_unread = get_unread_emergency_alert_count(
            mailbox_key("District Admin", district_name)
        )

        for org_role in (
            "District Police", "District Fire Service",
            "District Municipality"
        ):

            district_unread += get_unread_emergency_alert_count(
                mailbox_key(org_role, district_name)
            )

        district_rows.append(
            {
                "Risk": (
                    RISK_CIRCLE.get(risk, NO_DATA_CIRCLE)
                ),
                "District": district_name,
                "Division": division_of_district or "—",
                "Flood Probability": (
                    f"{probability:.1f}%"
                    if probability is not None else "No data"
                ),
                "Unread Alerts": district_unread,
                "_sort_probability": (
                    probability
                    if probability is not None else -1
                )
            }
        )

    if district_rows:

        district_table = pd.DataFrame(
            district_rows
        ).sort_values(
            "_sort_probability",
            ascending=False
        ).drop(
            columns=["_sort_probability"]
        )

        st.dataframe(
            district_table,
            width="stretch",
            hide_index=True
        )

        st.caption(
            f"Showing {len(district_table)} of "
            f"{len(DISTRICT_NAMES)} districts nationwide."
        )

    else:

        st.info(
            "No districts match that search/filter."
        )

    st.divider()

    # --------------------------------------------------------
    # 2. DIVISION ADMIN COMMUNICATION
    # --------------------------------------------------------
    # Reuses the existing send_email() / email_center()
    # machinery — no separate messaging system was built.
    # --------------------------------------------------------

    st.subheader(
        "📨 Division Admin Communication"
    )

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

    st.divider()

    # --------------------------------------------------------
    # 3. NATIONWIDE LIVE FLOOD MAP
    # --------------------------------------------------------

    st.subheader(
        "🗺️ Live Flood Location Map — All Divisions"
    )

    if readings.empty:

        st.warning(
            "No sensor readings are currently available."
        )

    else:

        st.plotly_chart(
            create_flood_map(readings),
            width="stretch"
        )

        st.caption(
            "🟢 Low   🟡 Moderate   🟠 High   🔴 Severe — each "
            "marker is labeled with its location and current "
            "risk."
        )

    st.divider()

    # --------------------------------------------------------
    # 4. SENSOR REGISTRATION + EXTERNAL DATASET INPUT
    # --------------------------------------------------------
    # System Handler is nationwide, so no scope restriction —
    # mirrors the main Administrator's own (unscoped) equivalent
    # in admin_dashboard().
    # --------------------------------------------------------

    sensor_and_dataset_management_section(
        scope_locations=None,
        scope_label="the nation",
        key_prefix="sh"
    )


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

    st.info(
        f"You can monitor and manage **{division} Division** "
        f"only — other divisions' operational data is not "
        f"accessible from this account."
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

        st.caption(
            f"Centered on **{selected_area}** — only "
            f"{division} Division's areas are shown."
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


# ============================================================
# MAIN APPLICATION
# ============================================================

def main():

    # --------------------------------------------------------
    # Initialize session state
    # --------------------------------------------------------

    if "logged_in" not in st.session_state:

        st.session_state.logged_in = False

    if "username" not in st.session_state:

        st.session_state.username = None

    if "role" not in st.session_state:

        st.session_state.role = None

    if "show_emergency_panel" not in st.session_state:

        st.session_state.show_emergency_panel = False

    if "admin_2fa_pending" not in st.session_state:

        st.session_state.admin_2fa_pending = False

    if "admin_2fa_username" not in st.session_state:

        st.session_state.admin_2fa_username = None

    if "division" not in st.session_state:

        st.session_state.division = None

    if "area" not in st.session_state:

        st.session_state.area = None

    if "district" not in st.session_state:

        st.session_state.district = None

    ensure_dataset_state()

    # --------------------------------------------------------
    # Sidebar
    # --------------------------------------------------------

    sidebar()

    # --------------------------------------------------------
    # AUTHORIZED PORTALS
    # --------------------------------------------------------

    if st.session_state.logged_in:

        role = st.session_state.role

        division = st.session_state.get("division")

        district = st.session_state.get("district")

        if role == "District Admin":

            admin_dashboard(district=district)

        elif role == "System Handler":

            system_handler_dashboard()

        elif role == "Division Admin":

            division_admin_dashboard(division)

        elif role == "Hospital":

            organization_dashboard(
                "Hospital",
                division
            )

        elif role == "Fire Service":

            organization_dashboard(
                "Fire Service",
                division
            )

        elif role == "Police":

            organization_dashboard(
                "Police",
                division
            )

        elif role == "Municipality":

            organization_dashboard(
                "Municipality",
                division
            )

        elif role == "District Police":

            organization_dashboard(
                "District Police",
                district=district
            )

        elif role == "District Fire Service":

            organization_dashboard(
                "District Fire Service",
                district=district
            )

        elif role == "District Municipality":

            organization_dashboard(
                "District Municipality",
                district=district
            )

    # --------------------------------------------------------
    # PUBLIC PORTAL
    # --------------------------------------------------------

    else:

        public_dashboard()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()