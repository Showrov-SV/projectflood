"""Sidebar: login form, 2FA verification, account info and navigation."""

import streamlit as st

from flood_app.alerts import get_unread_emergency_alert_count
from flood_app.auth import (
    add_trusted_device,
    admin_otp_resend_cooldown_remaining,
    authenticate_user,
    canonical_username,
    forget_all_trusted_devices,
    generate_and_send_admin_otp,
    get_cookie_controller,
    is_admin_locked,
    is_trusted_device,
    record_failed_admin_password,
    reset_admin_password_attempts,
    safe_get_cookie,
    safe_remove_cookie,
    safe_set_cookie,
    verify_admin_otp,
)
from flood_app.config import (
    ADMIN_OTP_LENGTH,
    ADMIN_OTP_VALID_MINUTES,
    ADMIN_PASSWORD_LOCK_MINUTES,
    ADMIN_TRUSTED_DEVICE_COOKIE_NAME,
    ADMIN_TRUSTED_DEVICE_DAYS,
)
from flood_app.database import get_connection
from flood_app.mail_roles import mailbox_key


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

                username = canonical_username(
                    st.text_input(
                        "Username",
                        key="login_username"
                    )
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
