"""Login, admin lockout, email OTP (2FA) and trusted-device cookies."""

import streamlit as st
from datetime import datetime, timedelta
import hashlib
import hmac
import smtplib
import secrets as pysecrets
from email.mime.text import MIMEText
from streamlit_cookies_controller import CookieController

from flood_app.config import (
    ADMIN_OTP_LENGTH,
    ADMIN_OTP_MAX_ATTEMPTS,
    ADMIN_OTP_RESEND_COOLDOWN_SECONDS,
    ADMIN_OTP_VALID_MINUTES,
    ADMIN_PASSWORD_LOCK_MINUTES,
    ADMIN_PASSWORD_MAX_ATTEMPTS,
    ADMIN_TRUSTED_DEVICE_DAYS,
)
from flood_app.database import get_connection


# ============================================================
# AUTHENTICATION
# ============================================================

def canonical_username(typed_username):
    """
    Forgiving username entry: ignores accidental leading/trailing
    spaces (common when pasting) and letter case (phone keyboards
    auto-capitalise the first letter). Returns the username exactly
    as stored in the database when exactly one account matches,
    otherwise the trimmed text unchanged.

    Everything downstream (admin lockout, OTP, trusted devices,
    the session) then works with the one canonical spelling, so
    different capitalisations can never be used to dodge the
    lockout counters.
    """

    cleaned = (typed_username or "").strip()

    if not cleaned:
        return cleaned

    conn = get_connection()

    try:
        matches = conn.execute(
            "SELECT username FROM users "
            "WHERE LOWER(username) = LOWER(?)",
            (cleaned,)
        ).fetchall()
    finally:
        conn.close()

    return matches[0][0] if len(matches) == 1 else cleaned


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

        # timeout: without one, an unreachable/slow network makes
        # the whole login page hang for minutes instead of failing
        # fast with the friendly error below.
        with smtplib.SMTP(
            "smtp.gmail.com", 587, timeout=10
        ) as server:

            server.starttls()
            server.login(sender, app_password)
            server.sendmail(
                sender,
                recipients,
                message.as_string()
            )

        return True, None

    except Exception:

        # Never surface SMTP internals (which could hint at the
        # credentials) to the UI — just a generic failure.
        return False, "Could not send the OTP email. Please try again."


def generate_and_send_admin_otp(username):
    """Creates a brand-new 6-digit OTP for this admin username,
    invalidating any previous OTP (only its hash is stored),
    and emails it. Returns (success, error_message)."""

    # Cryptographically secure digits (the random module is a
    # predictable generator and must not be used for 2FA codes).
    otp_code = "".join(
        str(pysecrets.randbelow(10))
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

    if hmac.compare_digest(
        _hash_code(submitted_code), str(state["otp_hash"])
    ):

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
