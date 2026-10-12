"""Central settings and constants you may want to tweak (database file name,
login/OTP limits, simulation refresh timer, alert cooldown, risk colours...)."""


# ============================================================
# DATABASE
# ============================================================

DB_NAME = "flood_monitoring.db"


# ============================================================
# ADMIN 2FA (EMAIL OTP) SECURITY
# ============================================================
# Everything in this section is ADDITIVE and only ever runs for
# the "System Handler" role (the top-level account). Every other
# role - Division Admin, Police, Fire Service,
# Hospital, Municipality - never touches any of this and goes
# through authenticate_user() with no extra steps.
#
# This uses a REAL Gmail SMTP account (via STARTTLS on port 587)
# purely to deliver the one-time passcode to the System Handler's
# inbox. It is entirely separate from, and does not modify or
# replace, the existing in-app (simulated) internal `email_log` mail
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


# ============================================================
# DIGITAL TWIN (state mirror of the sensor + network architecture)
# ============================================================
# flood_app/digital_twin.py keeps a persistent, synchronised model of
# the monitoring network. The network itself (routers, OSPF areas,
# VLANs, servers and links) is defined in flood_app/network_design.py,
# taken from the Cisco Packet Tracer prototype - edit that file, not
# this one, if the design changes.
#
#   * TWIN_EXTRA_LINKS      - optional redundant links, as pairs of
#                             node ids, e.g. ("R2", "R3"). By default
#                             the network is a pure tree, as in the
#                             prototype, so any single router failure
#                             cuts off everything beneath it.
#   * TWIN_STALE_AFTER_SECONDS / TWIN_OFFLINE_AFTER_SECONDS -
#                             how long a sensor may stay silent
#                             before the twin shows it Stale, then
#                             Offline.

TWIN_EXTRA_LINKS = ()

TWIN_STALE_AFTER_SECONDS = 180

TWIN_OFFLINE_AFTER_SECONDS = 600


# ============================================================
# PASSWORD HASHING
# ============================================================
# Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes (see
# flood_app/passwords.py). 600,000 iterations is the OWASP-recommended
# minimum for PBKDF2-HMAC-SHA256 at the time of writing; raise it as
# hardware improves - existing accounts are upgraded automatically
# the next time each user logs in. Each login costs roughly 0.1-0.4 s
# of CPU at this setting, and creating a brand-new database (which
# seeds ~300 default accounts) takes a while, one time only.
# Lower it ONLY for automated tests.

PASSWORD_HASH_ITERATIONS = 600_000


# ============================================================
# ACTIVITY / LOGIN AUDIT LOG
# ============================================================
# Every login attempt (success, failure, lockout, OTP outcome),
# logout, and key operational action (alerts/siren, messages,
# sensor registration, dataset loads) is written to the
# `activity_log` table by flood_app/activity_log.py. Entries
# older than ACTIVITY_LOG_RETENTION_DAYS are pruned at startup
# (set it to 0 to keep everything). Passwords, OTP codes and
# tokens are NEVER written to this log.

ACTIVITY_LOG_RETENTION_DAYS = 365


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


# Physically plausible (min, max) for each uploaded sensor value.
# Rows outside these ranges (e.g. humidity 500 %, negative
# rainfall, a water level of a million metres) are skipped
# instead of producing a confident-looking but meaningless flood
# prediction that could raise false alarms. The limits are
# deliberately generous - widen them only if your data really
# uses other units.
DATASET_VALUE_LIMITS = {
    "water_level": (0, 100),           # metres
    "rainfall": (0, 2000),             # mm
    "river_flow": (0, 1_000_000),      # m3/s
    "temperature": (-50, 60),          # degrees C
    "humidity": (0, 100),              # %
    "soil_moisture": (0, 100),         # %
    "wind_speed": (0, 400),            # km/h
}


# ------------------------------------------------------------
# SIMULATION REFRESH TIMER
# ------------------------------------------------------------
# Simulated sensor readings used to be re-randomised on EVERY
# click, so opening a dropdown or typing in a box made every
# number, risk colour and map marker jump around (and could fire
# fake alerts). Readings are now generated once per
# SIMULATION_REFRESH_SECONDS and shared by everyone, so the page
# stays steady between refreshes. A "Refresh data" button in the
# sidebar forces a new set immediately.
#   * set SIMULATION_REFRESH_SECONDS = 0 to get the old
#     "new readings on every click" behaviour back.
#   * simulated readings older than SENSOR_READING_RETENTION_DAYS
#     are pruned from the sensor_readings history table so it
#     cannot grow without limit (set it to 0 to keep everything).
# ------------------------------------------------------------
SIMULATION_REFRESH_SECONDS = 30


SENSOR_READING_RETENTION_DAYS = 30


# ============================================================
# DATA MODE  (simulation  ->  live)
# ============================================================
# The system starts in SIMULATION mode: every registered sensor gets
# random demo readings (exactly the behaviour it always had).
#
# The moment REAL data is connected (an uploaded CSV/XLSX dataset, or
# a reading pushed by a real sensor through ingest_sensor_reading())
# the system switches to LIVE mode and STAYS there (the choice is
# stored in the database, so it survives restarts). In live mode:
#   * simulated readings are no longer generated, predicted or saved;
#   * dashboards, the map, alerts and the digital twin use only real
#     readings (a sensor with no real reading shows "no data");
#   * every real reading is stored in the `live_readings` table,
#     which is the table future model training will read from.
# Switching back to simulation is done in code (data_mode.set_data_mode).
#
#   * LIVE_MODE_AUTO_SWITCH - True: connecting real data switches the
#     whole system to live mode automatically. False: real data is
#     still stored and shown, but the System Handler must switch the
#     mode manually.
#   * LIVE_SENSOR_MAX_AGE_MINUTES - a REAL SENSOR whose newest
#     reading is older than this is treated as "no data" instead of
#     being shown (and alerting) as if it were current. It does NOT
#     apply to uploaded datasets, which are historical by nature.
#     Set to 0 to disable.
# ============================================================

DATA_MODE_SIMULATION = "simulation"

DATA_MODE_LIVE = "live"

LIVE_MODE_AUTO_SWITCH = True

LIVE_SENSOR_MAX_AGE_MINUTES = 60


# ============================================================
# AUTOMATIC RETRAINING (live mode only)
# ============================================================
# While the system is in SIMULATION mode the models stay exactly as
# they are (trained once on the synthetic dataset). Once it is in
# LIVE mode, the models retrain by themselves as real data
# (uploaded datasets + real sensors, table `live_readings`) grows:
#
#   * a retrain starts right after a dataset is loaded, and then
#     whenever RETRAIN_MIN_NEW_ROWS new real rows have arrived and
#     at least RETRAIN_MIN_INTERVAL_MINUTES have passed;
#   * it runs in the background (the dashboard never freezes);
#   * training data = the synthetic base set + the real rows, so the
#     model never "forgets" and never depends on a tiny real set;
#   * the new model replaces the live one ONLY if it is not worse
#     than the current one on held-out rows (see the retraining
#     panel for the numbers); otherwise the old model is kept;
#   * every accepted model is saved as a numbered version; the
#     System Handler can roll back to the original model.
#
# LABELS - what the model can really learn from:
#   * a real row WITH a label (the uploaded file has a
#     flood_probability / flood_label / flood_occurred column, or a
#     sensor reading was sent with label=...) teaches the model
#     what actually happened. Together they get about
#     RETRAIN_LABELED_SHARE of the total training weight (each row
#     counts at least RETRAIN_LABELED_WEIGHT and at most
#     RETRAIN_MAX_LABELED_WEIGHT times), so real outcomes can
#     outweigh the assumed synthetic rows.
#   * a real row WITHOUT a label cannot teach the truth. If
#     RETRAIN_USE_UNLABELED is True it is still used, with a
#     "weak" label from the same synthetic label function the base
#     model uses - so the model learns the value ranges of YOUR data
#     (not real flood outcomes). Set it to False to train on
#     labelled rows only.
#   * with enough labelled rows, a new model is accepted only if it
#     beats the old one on held-out labelled rows AND explains at
#     least RETRAIN_MIN_LABEL_R2 of their variance (this is what
#     rejects wrong / random label columns).
# ============================================================

RETRAIN_ENABLED = True

RETRAIN_MIN_REAL_ROWS = 30

RETRAIN_MIN_NEW_ROWS = 200

RETRAIN_MIN_INTERVAL_MINUTES = 30

RETRAIN_MAX_REAL_ROWS = 50_000

RETRAIN_LABELED_WEIGHT = 5.0

RETRAIN_LABELED_SHARE = 0.7

RETRAIN_MAX_LABELED_WEIGHT = 50.0

RETRAIN_USE_UNLABELED = True

RETRAIN_MAX_SYNTHETIC_DEGRADATION = 0.25

RETRAIN_MIN_LABEL_R2 = 0.15

RETRAIN_KEEP_VERSIONS = 5


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


# ============================================================
# SHARED FLOOD-PROBABILITY GAUGE
# ============================================================
# ONE gauge implementation, reused identically by every
# dashboard that shows a single location's prediction
# (organization_dashboard — Police/Fire Service/Hospital/
# Municipality — plus division_admin_dashboard and the public
# dashboard) so the
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


# ============================================================
# SYSTEM HANDLER HELPERS
# ============================================================

DIVISION_ORG_ROLES = (
    "Police", "Fire Service", "Hospital", "Municipality"
)


