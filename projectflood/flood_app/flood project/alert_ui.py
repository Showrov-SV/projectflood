"""Emergency alert banner (blinking + sound) and the emergency siren panel."""

import html
import streamlit as st

from flood_app.alert_sound import EMERGENCY_ALERT_SOUND_B64
from flood_app.alerts import (
    create_emergency_alert,
    get_unread_emergency_alert_count,
    get_unread_emergency_alerts,
    mark_emergency_alerts_read,
)
from flood_app.messaging import (
    get_emergency_notifications,
    mark_notifications_read,
    send_emergency_notification,
)


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


def _esc(value):
    """
    HTML-escapes user-supplied text (alert titles, messages,
    sender names...) before it is placed inside the raw-HTML
    alert cards, so text such as "Water level > 4m & rising" or
    anything containing < > & " shows up literally instead of
    breaking the layout (or injecting markup/scripts into every
    recipient's page). Line breaks become <br> — a blank line
    would otherwise end the HTML block and mangle the card.
    """

    text = "" if value is None else str(value)

    return (
        html.escape(text)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
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
                f"Division: {_esc(alert_row['target_division'])}"
            )

        if alert_row["target_area"]:
            location_bits.append(
                f"Area: {_esc(alert_row['target_area'])}"
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
        {_esc(alert_row['title'])}
        </div>
        <div style="font-size:16px; margin-top:8px;">
        {_esc(alert_row['message'])}
        </div>
        <div style="font-size:14px; margin-top:12px;">
        Alert Level: <b>{_esc(alert_row['level'])}</b><br>
        {location_line}
        </div>
        <div style="font-size:13px; margin-top:8px; opacity:0.9;">
        Sender: {_esc(alert_row['sender'])}  |
        Time: {_esc(alert_row['created_at'])}
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
        {_esc(notification_row['message'])}
        </div>
        <div style="font-size:13px; margin-top:8px; opacity:0.9;">
        Time: {_esc(notification_row['timestamp'])}
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
