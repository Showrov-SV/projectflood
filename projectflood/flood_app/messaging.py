"""Internal email (inbox / sent / bin) and the legacy emergency notifications."""

import pandas as pd
from datetime import datetime

from flood_app.database import get_connection
from flood_app.mail_roles import ALL_MAIL_ROLES, get_role_email


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
