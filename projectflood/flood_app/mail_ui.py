"""Email-related screens: admin message center, mail server panel and the
organization email center (Inbox / Sent / Compose / Bin)."""

import streamlit as st
import pandas as pd

from flood_app.mail_roles import (
    ADMIN_EMAIL,
    ALL_MAIL_ROLES,
    EMERGENCY_DOMAINS,
    EMERGENCY_EMAILS,
    get_role_email,
    MAIL_SERVER_NAME,
)
from flood_app.messaging import (
    empty_bin,
    get_bin_mail,
    get_email_log,
    get_sent_mail,
    mark_email_read,
    move_email_to_bin,
    permanently_delete_email,
    restore_email_from_bin,
    send_email,
    send_emergency_notification,
)


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
