"""Login history and activity audit trail (stored in the `activity_log`
table).

log_activity() is deliberately fail-safe: a logging problem (locked
database, missing table...) must NEVER break a login or an emergency
alert, so every error is swallowed. Passwords, OTP codes and tokens
must never be passed in `details`."""

from datetime import datetime

import pandas as pd

from flood_app.database import get_connection


# Standard action names (kept in one place so the UI filter, the
# README and the code agree on the vocabulary).
ACTION_LOGIN = "LOGIN"
ACTION_LOGIN_FAILED = "LOGIN_FAILED"
ACTION_LOGIN_BLOCKED = "LOGIN_BLOCKED"
ACTION_OTP_SENT = "OTP_SENT"
ACTION_OTP_VERIFY = "OTP_VERIFY"
ACTION_LOGOUT = "LOGOUT"
ACTION_PASSWORD_UPGRADED = "PASSWORD_HASH_UPGRADED"
ACTION_ALERT_SENT = "ALERT_SENT"
ACTION_MESSAGE_SENT = "MESSAGE_SENT"
ACTION_SENSOR_ADDED = "SENSOR_ADDED"
ACTION_DATASET_LOADED = "DATASET_LOADED"
ACTION_DATA_MODE_CHANGED = "DATA_MODE_CHANGED"
ACTION_MODEL_RETRAINED = "MODEL_RETRAINED"

_MAX_FIELD_LENGTH = 300


def _clean(value, limit=_MAX_FIELD_LENGTH):

    if value is None:
        return None

    text = str(value).replace("\r", " ").replace("\n", " ").strip()

    return text[:limit]


def _session_identity():
    """(username, role, division, district) of the current Streamlit
    session, or Nones when called outside one."""

    try:

        import streamlit as st

        state = st.session_state

        return (
            state.get("username"),
            state.get("role"),
            state.get("division"),
            state.get("district"),
        )

    except Exception:

        return (None, None, None, None)


def log_activity(
    action,
    username=None,
    role=None,
    details=None,
    status="success",
    division=None,
    district=None
):
    """Append one event to activity_log. Identity defaults to the
    logged-in session; pass username/role explicitly for events that
    happen before a session exists (login attempts). Returns True if
    the row was written, False if logging failed (never raises)."""

    try:

        if username is None and role is None:

            (
                username, role,
                session_division, session_district
            ) = _session_identity()

            division = division or session_division
            district = district or session_district

        conn = get_connection()

        try:

            conn.execute(
                """
                INSERT INTO activity_log(
                    timestamp, username, role, division,
                    district, action, status, details
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    _clean(username, 80),
                    _clean(role, 80),
                    _clean(division, 80),
                    _clean(district, 80),
                    _clean(action, 40),
                    _clean(status, 20),
                    _clean(details),
                )
            )

            conn.commit()

        finally:

            conn.close()

        return True

    except Exception:

        return False


def get_activity_log(
    limit=500,
    username=None,
    action=None,
    status=None,
    role=None,
    since_hours=None
):
    """Newest-first DataFrame of activity events, optionally
    filtered. Returns an empty DataFrame if the table can't be read."""

    columns = [
        "id", "timestamp", "username", "role", "division",
        "district", "action", "status", "details"
    ]

    query = "SELECT " + ", ".join(columns) + " FROM activity_log"

    clauses = []
    params = []

    if username:
        clauses.append("username LIKE ?")
        params.append(f"%{username}%")

    if action:
        clauses.append("action = ?")
        params.append(action)

    if status:
        clauses.append("status = ?")
        params.append(status)

    if role:
        clauses.append("role = ?")
        params.append(role)

    if since_hours:
        clauses.append(
            "timestamp >= datetime('now', 'localtime', ?)"
        )
        params.append(f"-{int(since_hours)} hours")

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))

    try:

        conn = get_connection()

        try:

            return pd.read_sql_query(query, conn, params=params)

        finally:

            conn.close()

    except Exception:

        return pd.DataFrame(columns=columns)


def count_activity(action=None, status=None, since_hours=None):
    """Number of events matching the filters (0 on any error)."""

    query = "SELECT COUNT(*) FROM activity_log"
    clauses, params = [], []

    if action:
        clauses.append("action = ?")
        params.append(action)

    if status:
        clauses.append("status = ?")
        params.append(status)

    if since_hours:
        clauses.append(
            "timestamp >= datetime('now', 'localtime', ?)"
        )
        params.append(f"-{int(since_hours)} hours")

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    try:

        conn = get_connection()

        try:

            return conn.execute(query, params).fetchone()[0]

        finally:

            conn.close()

    except Exception:

        return 0
