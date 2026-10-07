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


# ============================================================
# SYSTEM HANDLER HELPERS
# ============================================================

DIVISION_ORG_ROLES = (
    "Police", "Fire Service", "Hospital", "Municipality"
)


DISTRICT_ORG_ROLES = (
    "District Police", "District Fire Service",
    "District Municipality"
)
