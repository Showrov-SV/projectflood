"""SQLite connection helper and database creation / migration / account seeding."""

import sqlite3
import hashlib

from flood_app.config import DB_NAME
from flood_app.geography import (
    BD_DIVISIONS,
    DISTRICT_COORDINATES,
    DISTRICT_NAMES,
    DIVISION_AREAS,
    slugify_name,
)


def get_connection():
    return sqlite3.connect(
        DB_NAME,
        check_same_thread=False
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

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sensor_readings_timestamp
        ON sensor_readings(timestamp)
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
