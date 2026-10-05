# Flood Monitoring & Prediction System

A Streamlit-based flood monitoring, prediction, and emergency-response
platform for Bangladesh. Simulates IoT sensor networks (or ingests real
CSV/XLSX data), predicts flood risk using a genuine **hybrid physics +
machine-learning framework**, automatically alerts emergency
organizations when risk gets high, and enforces a strict three-level
administrative hierarchy covering all **8 real divisions and 64 real
districts (zilas)** of Bangladesh.

## What this project actually is

At its core, the app does three things:

1. **Monitors flood risk** for every registered location — either from
   simulated IoT sensor readings or from uploaded CSV/XLSX datasets —
   and turns that into a flood probability, a predicted water level,
   and a Low/Moderate/High/Severe risk classification.
2. **Enforces a real administrative hierarchy**: a single national
   System Handler oversees 8 Division Admins, each of whom oversees
   the districts in their division, each of which has its own
   District Admin plus division- and district-level Police, Fire
   Service, Hospital, and Municipality accounts — all strictly scoped
   to their own geography, enforced in the database and backend logic,
   not just hidden in the UI.
3. **Automatically alerts the right people** — a blinking, sounding
   emergency banner — the moment any location's prediction reaches
   Severe risk, routed only to the organizations actually responsible
   for that location.

## Running the app

```bash
pip install streamlit pandas numpy plotly openpyxl streamlit-cookies-controller scikit-learn
python -m streamlit run flooddashboard.py
```

**Two files make up the app** and must be in the same folder:
`flooddashboard.py` (the Streamlit app) and `hybrid_model.py` (the
physics + ML prediction framework it imports).

- `openpyxl` is required to read `.xlsx` external datasets.
- `scikit-learn` powers the ML half of the hybrid prediction
  framework. If it isn't installed, predictions fall back to
  physics-only rather than crashing or faking an ML result.
- `streamlit-cookies-controller` is required for the System Handler's
  "Remember this device" (OTP-skip) and other roles' "Keep me logged
  in" features.

The app creates/upgrades `flood_monitoring.db` (SQLite) automatically
on first run. Every table is created with `CREATE TABLE IF NOT EXISTS`
and columns are added with safe `ALTER TABLE` migrations, so an
existing database is upgraded in place — nothing is ever deleted.

## The administrative hierarchy

```
                         System Handler (1 account)
                                  │
                    ┌─────────────┴─────────────┐
                    │        8 Divisions          │
                    └─────────────┬─────────────┘
                                  │
              Division Admin, Division Police,
              Division Fire Service, Division
              Hospital, Division Municipality
              (5 accounts × 8 divisions = 40)
                                  │
                    ┌─────────────┴─────────────┐
                    │       64 Districts          │
                    └─────────────┬─────────────┘
                                  │
              District Admin, District Police,
              District Fire Service, District
              Municipality
              (4 accounts × 64 districts = 256)
```

**Total accounts: 297** (1 + 40 + 256).

- **System Handler** — the sole national-level account (this replaced
  the original single "Administrator" account; Administrator-2FA now
  applies here). Sees all 8 divisions, all 64 districts, nationwide
  map/prediction/alerts, and can message any Division Admin
  individually or all of them at once.
- **Division Admin** — Administrator-equivalent capabilities (same
  dashboard, reused, not a separate one), restricted to their own
  division's districts only.
- **District Admin** — same again, restricted to their own single
  district.
- **Division/District Police, Fire Service, Municipality** — each
  sees only their own division's or district's map, live sensor
  readings, and prediction; each has its own private mailbox and
  emergency-alert state, completely isolated from every other
  account.

**Note on Hospital**: Hospital accounts exist at the **division**
level only (8 total) — there is no District Hospital role. If your
deployment needs per-district hospital accounts, that would need to be
added; it wasn't part of the current district build-out.

**Note on the original Administrator account**: it no longer exists.
`admin_dashboard(district=None)` (the true nationwide-admin code path)
is still present but unreachable from login, since no account carries
the `Administrator` role anymore — District Admin and Division Admin
now cover what that used to do, scoped appropriately.

## Sensor & dataset access control

**Only System Handler, Division Admin, and District Admin can
register sensors or upload CSV/XLSX datasets.** Police, Fire Service,
Hospital, and Municipality accounts — at every level — have zero
access to sensor registration or dataset upload; they are monitoring
and communication accounts only. This is enforced by simply never
rendering or calling those functions from their dashboard, not by
hiding a button behind a permission flag.

Where access does exist, it's also scoped geographically and enforced
at the database-write level, not just in the UI:

- System Handler can register/upload anywhere.
- A Division Admin's sensor form only offers their own division's
  districts, **and** the backend independently rejects any submission
  outside that division even if the UI restriction were bypassed.
- A District Admin's form is restricted the same way to their single
  district.

## Login credentials

Given the scale (297 accounts), credentials follow a predictable
pattern rather than being individually listed here:

| Role | Username pattern | Password pattern |
|---|---|---|
| System Handler | `system_handler` | `syshandler123` |
| Division Admin | `<division>_admin` | `<division>admin123` |
| Division Police/Fire/Hospital/Municipality | `<division>_police` etc. | `<division>police123` etc. |
| District Admin | `admin_<district>` | `<district>district123` |
| District Police/Fire/Municipality | `<district>_police` etc. | `<district>police123` etc. |

(division/district names lowercased, e.g. `dhaka_admin` /
`dhakaadmin123`, `admin_coxsbazar` / `coxsbazardistrict123`.) Query
the `users` table directly if you need the exact list for your
database — see below.

The login form is a proper Streamlit form: press **Enter** after
typing your password instead of clicking **Login**; same at the OTP
step.

## Hybrid Physics + Machine Learning Prediction Framework

Implemented in `hybrid_model.py` — Streamlit-independent, so it can be
read, imported, and tested on its own by anyone reviewing the
modeling logic.

**Physics / mathematical component** — a reduced-order water-balance
/ linear-reservoir model (explicitly *not* a full Saint-Venant
hydrodynamic solver, and the code says so): estimated inflow (river
flow + rainfall-driven runoff, adjusted by a soil-moisture runoff
coefficient), estimated outflow (proportional to current water
level), a small evaporation term, and the resulting predicted
water-level change.

**Machine learning component** — a scikit-learn `RandomForestRegressor`,
genuinely trained via `.fit()` on a physics-informed **synthetic**
dataset (there's no bundled real historical flood dataset for
Bangladesh, and the code is honest about that). Its held-out test R²
and MAE are computed for real, not hard-coded.

**Hybrid combination** — final probability blends the trained ML
model's prediction with a standalone physics-only estimate; the ML
model's own inputs already include every physics-derived feature, so
physics shapes the result twice over.

**Where this shows up in the UI**: District Admin and Division Admin
dashboards show a "Predicted Water Level" metric and an expandable
"How this prediction was produced" explanation. Police, Fire Service,
Hospital, Municipality, and the Public Portal deliberately do **not**
show any of this — no "Hybrid Physics + ML" label, no model name, no
feature importances — those views just show the risk status itself.

## Risk thresholds

```
< 50%       → 🟢 Low
50 – 69.99% → 🟡 Moderate
70 – 89.99% → 🟠 High
≥ 90%       → 🔴 Severe
```

Defined once, in `classify_risk()` — every other place that shows a
risk level (map markers, risk badges, the gauge, automatic alerts)
calls this same function, so they can never disagree with each other.

## Emergency Alert System

- **Automatic**: the moment any location's prediction reaches
  **Severe (≥90%)**, an alert fires with no admin click needed —
  routed to that location's district-level Police/Fire
  Service/Municipality, its division-level equivalents, the relevant
  District Admin and Division Admin, and System Handler. A 5-minute
  per-location cooldown prevents the same location from spamming new
  alerts every time the simulator re-randomizes its readings.
- **Manual**: Division Admin, District Admin, and System Handler can
  also send alerts on demand to their own scope.
- **Delivery**: a large, continuously blinking red banner plus an
  automatically-playing siren sound (offline-generated, no internet
  dependency), until **"Mark Emergency Alerts as Read"** is clicked —
  which stops both immediately and is completely independent per
  recipient (marking Dhaka Police's alerts read never touches Dhaka
  Hospital's).
- **Performance-capped rendering**: only the 8 most recent alerts are
  ever rendered as full cards at once, with an accurate "showing 8 of
  N" notice when there's a larger backlog — clicking "Mark as Read"
  still clears the entire backlog in one click, not just what's
  shown. (This was added after an account was found with 400+ unread
  alerts silently rendering as 400+ blinking divs on every page
  load — see Performance notes below.)
- Every alert-receiving role has a live **"🚨 Emergency Alerts: N"**
  indicator in the sidebar.

## Live Flood Location Map & Gauge

- Every marker is always labeled with its risk circle + location name
  directly on the map, sized so even low-probability readings are
  never shrunk to an invisible dot.
- A 0–100% gauge shows the current probability with colored zone
  bands matching the thresholds above, rendered with an explicitly
  opaque background and matching text color so it stays readable
  regardless of whether the surrounding Streamlit theme is light or
  dark.
- Picking a location/district re-centers and zooms the map onto it.

## Public Portal (no login required)

Cascading **Division → District** selectors: pick a division, then
one of its districts, and the portal shows that district's live map
marker, current sensor readings, and prediction/risk status — never
another district's data. No technical model details are shown here
either.

## Dataset & sensor input

Required columns: `water_level`, `rainfall`, `river_flow`,
`temperature`, `humidity`, `soil_moisture`, `wind_speed` (`sensor_id`
and `timestamp` optional). Common column-name variants are normalized
automatically. Both CSV and XLSX are supported. Once a location has an
uploaded dataset, simulation for it stops and prediction uses the
latest uploaded record; other locations keep simulating normally. A
"Remove Dataset" action resumes simulation.

## Security

- **System Handler 2FA**: password + emailed one-time code (Gmail
  SMTP via `.streamlit/secrets.toml`), 5-attempt password lockout
  (15-minute lock), 5-minute OTP expiry, one-time use, 30-second
  resend cooldown — all enforced server-side in the database, so a
  page refresh can't reset a lockout or an OTP's state.
- **"Remember this device"** (System Handler) — skips the OTP step
  only on a device that's already verified once; password is always
  still required.
- Passwords, OTPs, and every device-trust token are stored only as
  SHA-256 hashes.

## Database

`flood_monitoring.db` — 12 tables: `users`, `sensors`,
`sensor_readings`, `email_log`, `emergency_notifications` (legacy,
still written for history), `admin_auth_state`, `admin_trusted_devices`,
`remembered_logins`, `emergency_alerts`, `emergency_alert_reads`,
`auto_alert_log`, plus SQLite's own `sqlite_sequence`. Four indexes
(`idx_alert_reads_recipient_unread`, `idx_alert_reads_alert_id`,
`idx_notifications_role_status`, `idx_email_log_owner_folder`) keep
the alert/mailbox lookups that run on every dashboard render fast even
as the tables grow into the thousands of rows.

To inspect it directly: [DB Browser for SQLite](https://sqlitebrowser.org/)
(open the file, Browse Data), the `sqlite3` CLI (`.tables`,
`SELECT * FROM users;`), or a VS Code SQLite extension.

## Performance notes

At 297 accounts and a real division/district hierarchy, a few things
that were fine at small scale needed attention:

- Emergency-alert lookups are now indexed (see above) instead of
  doing a full table scan on every sidebar render.
- Alert card rendering is capped to 8 at a time regardless of backlog
  size (see Emergency Alert System above).
- A one-time cleanup removes any emergency-alert rows addressed to
  mailbox keys that no longer correspond to a real account (this
  happened once, when the original 5 legacy accounts were replaced by
  System Handler, and left ~1,300 permanently-unreadable rows behind
  until it was cleaned up).

## Notes

- The Emergency Messaging / Inbox / Sent / Bin mail system is
  **simulated** — no real SMTP server or internet mail. Unrelated to
  the real Gmail SMTP connection used only for System Handler 2FA.
- Uploaded datasets persist only for the current browser session.
- To add or adjust a district's coordinates, edit
  `DISTRICT_COORDINATES` near the top of `flooddashboard.py`.

### Speed-up changes (latest)

- Sensor predictions are now **batched** (`hybrid_model.hybrid_predict_batch`,
  `flooddashboard.hybrid_flood_prediction_batch`): one vectorised physics pass and
  one `predict()` call per ML model for all sensors, instead of one full model
  call per sensor. Results are numerically identical to the old per-row path.
- The trained model is cached on disk (`.hybrid_model_cache.joblib`, created
  automatically on first launch, ~5 s once). It is only reused when library
  versions and model settings match; otherwise it retrains. Safe to delete.
- Sensor readings are saved in a single database transaction.
- System Handler alert counts use one grouped query instead of ~300.
- Uploaded datasets are predicted in one batch (20,000 rows in under 1 s) and
  column headers with units, e.g. `Rainfall (mm)` or `Humidity (%)`, are accepted.
- The OTP email now has a 10-second network timeout, so login can't hang if Gmail
  is unreachable.
- `xgboost` was added to `requirements.txt` (the model uses both Random Forest and XGBoost).
