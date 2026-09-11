[Uploading README.md…]()
# Flood Monitoring & Prediction System

A Streamlit-based flood monitoring, prediction, and emergency-response
platform. Simulates IoT sensor networks (or ingests real CSV/XLSX
data) across multiple locations, predicts flood risk using a genuine
**hybrid physics + machine-learning framework**, automatically alerts
emergency organizations when risk gets high, and supports two parallel
admin hierarchies on top of the original single-admin setup: a
national System Handler → Division Admin structure, and an
Administrator-equivalent **District Admin** tier scoped to one
district at a time.

## Running the app

```bash
pip install streamlit pandas numpy plotly openpyxl streamlit-cookies-controller scikit-learn
python -m streamlit run flooddashboard.py
```

**Two files now make up the app**: `flooddashboard.py` (the
Streamlit app itself) and `hybrid_model.py` (the physics + ML
prediction framework it imports) — both must be in the same folder.

The app creates `flood_monitoring.db` (SQLite) automatically on first
run — see **"Viewing the database and saved data"** below for how to
open and inspect it. If you already have a `flood_monitoring.db` from
a previous run, keep it in the same folder: every table below is
created with `CREATE TABLE IF NOT EXISTS`, so an existing database is
safely upgraded in place — your existing users, sensors, and history
are never touched.

- `openpyxl` is required to read `.xlsx` external datasets.
- `scikit-learn` is required for the ML half of the hybrid prediction
  framework. If it isn't installed, the app doesn't crash and doesn't
  fake an ML result — every prediction honestly falls back to
  physics-only, clearly labeled as such (see **Hybrid Prediction
  Framework** below).
- `streamlit-cookies-controller` is required for System Handler
  **"Remember this device"** (skips the OTP step only, password is
  always required). The app still runs without it for every other
  feature, but that checkbox won't work until it's installed.

## Viewing the database and saved data

Everything the app stores lives in one file, `flood_monitoring.db`
(SQLite), next to `flooddashboard.py`. A few ways to look inside it:

**Easiest — DB Browser for SQLite (free, GUI, no command line):**
1. Download from [sqlitebrowser.org](https://sqlitebrowser.org/)
   (Windows/Mac/Linux).
2. Open the app → **File → Open Database** → select
   `flood_monitoring.db`.
3. Click **Browse Data**, pick a table from the dropdown (e.g.
   `users`, `sensor_readings`, `email_log`), and you can scroll,
   sort, filter, and edit rows directly. The **Execute SQL** tab lets
   you run any query, e.g. `SELECT * FROM emergency_alerts ORDER BY
   id DESC LIMIT 20;`.

**VS Code:** install the "SQLite Viewer" or "SQLite" extension, then
right-click `flood_monitoring.db` in the file explorer → **Open
Database** — gives you a similar browsable table view inline.

**Command line** (works anywhere Python/SQLite is installed):
```bash
sqlite3 flood_monitoring.db
.tables                          -- list every table
.schema users                    -- show a table's columns
SELECT * FROM users;             -- view all rows
SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 20;
.quit
```

**From Python** (useful for scripting/exports):
```python
import sqlite3, pandas as pd
conn = sqlite3.connect("flood_monitoring.db")
df = pd.read_sql_query("SELECT * FROM users", conn)
print(df)
```

### What's in each table

| Table | What it holds |
|---|---|
| `users` | Every account: username, hashed password, role, division, area, district. |
| `sensors` | Registered sensor/location metadata (incl. custom coordinates). |
| `sensor_readings` | Historical simulated + dataset-derived readings and computed risk. |
| `email_log` | The simulated internal mailbox system — every Inbox/Sent/Bin message. |
| `emergency_notifications` | The original plain-text alert log (still written for history). |
| `admin_auth_state` | System Handler 2FA state: failed-password count, lockout, hashed OTP. |
| `admin_trusted_devices` | Hashed "Remember this device" tokens (System Handler, OTP-skip only). |
| `emergency_alerts` | Every blinking/sounding alert ever created (manual or automatic). |
| `emergency_alert_reads` | Per-recipient read state for each alert — this is what makes Dhaka Police's read state independent of Dhaka Hospital's, etc. |
| `auto_alert_log` | Last-fired timestamp per location, for the automatic alert cooldown. |

Passwords and every security token (OTP, trusted-device, remembered-login) are stored only as
SHA-256 hashes — you won't find plaintext passwords or tokens in
there even if you open the file directly.

## System Handler email 2FA setup (required for System Handler login)

`system_handler` login requires a one-time passcode (OTP) sent by
email, in addition to the password — this is now the **only**
account that goes through email 2FA (it previously applied to the
`admin` account, which has been removed). This uses a **real Gmail
account** over SMTP purely to deliver that code — it is completely
separate from the app's simulated internal mail system (Inbox / Sent
/ Bin / Emergency Messaging).

1. **Create a Gmail App Password** (not your normal Gmail password):
   - Turn on 2-Step Verification on the sending Gmail account:
     `myaccount.google.com/security`
   - Create an App Password at `myaccount.google.com/apppasswords`
     and copy the 16-character code.
2. **Add a `secrets.toml`** file at `.streamlit/secrets.toml` (next
   to `flooddashboard.py`) — copy `secrets.toml.example` and fill it
   in:

   ```toml
   [email]
   sender = "yourgmail@gmail.com"
   app_password = "your16charapppassword"

   # One recipient:
   # admin_2fa_email = "yourgmail@gmail.com"

   # Or several — every address listed receives the same OTP:
   admin_2fa_email = ["yourgmail@gmail.com", "second.admin@gmail.com"]
   ```

   Never commit the real `secrets.toml` to version control.

3. That's it — no changes needed elsewhere. If `secrets.toml` is
   missing or incomplete, the System Handler login form shows a clear
   "Email 2FA is not configured" error instead of crashing; every
   other role is unaffected either way.

## Login credentials

### The original 5 global accounts have been removed

`admin`, `hospital`, `fire`, `police` and `municipality` no longer
exist — they are deleted automatically (by username) from any
existing `flood_monitoring.db` the first time the app starts after
this change, and are never re-created. **System Handler is now the
sole national-level account**, and the Gmail email OTP/2FA step
described below applies only to it.

### Hierarchical accounts (System Handler → Division Admin → Police/Fire/Hospital/Municipality)

| Role | Username | Password | Division | Default Area |
|---|---|---|---|---|
| System Handler | `system_handler` | `syshandler123` | — (national) | Email OTP |
| Division Admin | `dhaka_admin` | `dhakaadmin123` | Dhaka | — |
| Division Admin | `chattogram_admin` | `chattogramadmin123` | Chattogram | — |
| Division Admin | `rajshahi_admin` | `rajshahiadmin123` | Rajshahi | — |
| Division Admin | `khulna_admin` | `khulnaadmin123` | Khulna | — |
| Division Admin | `barishal_admin` | `barishaladmin123` | Barishal | — |
| Division Admin | `sylhet_admin` | `sylhetadmin123` | Sylhet | — |
| Division Admin | `rangpur_admin` | `rangpuradmin123` | Rangpur | — |
| Division Admin | `mymensingh_admin` | `mymensinghadmin123` | Mymensingh | — |
| Police | `dhaka_police` | `dhakapolice123` | Dhaka | Dhaka |
| Fire Service | `dhaka_fire` | `dhakafire123` | Dhaka | Dhaka |
| Hospital | `dhaka_hospital` | `dhakahospital123` | Dhaka | Dhaka |
| Municipality | `dhaka_municipality` | `dhakamunicipality123` | Dhaka | Dhaka |
| Police | `chattogram_police` | `chattogrampolice123` | Chattogram | Chittagong |
| Fire Service | `chattogram_fire` | `chattogramfire123` | Chattogram | Chittagong |
| Hospital | `chattogram_hospital` | `chattogramhospital123` | Chattogram | Chittagong |
| Municipality | `chattogram_municipality` | `chattogrammunicipality123` | Chattogram | Chittagong |
| Police | `rajshahi_police` | `rajshahipolice123` | Rajshahi | Rajshahi |
| Fire Service | `rajshahi_fire` | `rajshahifire123` | Rajshahi | Rajshahi |
| Hospital | `rajshahi_hospital` | `rajshahihospital123` | Rajshahi | Rajshahi |
| Municipality | `rajshahi_municipality` | `rajshahimunicipality123` | Rajshahi | Rajshahi |
| Police | `khulna_police` | `khulnapolice123` | Khulna | Khulna |
| Fire Service | `khulna_fire` | `khulnafire123` | Khulna | Khulna |
| Hospital | `khulna_hospital` | `khulnahospital123` | Khulna | Khulna |
| Municipality | `khulna_municipality` | `khulnamunicipality123` | Khulna | Khulna |
| Police | `barishal_police` | `barishalpolice123` | Barishal | Barisal |
| Fire Service | `barishal_fire` | `barishalfire123` | Barishal | Barisal |
| Hospital | `barishal_hospital` | `barishalhospital123` | Barishal | Barisal |
| Municipality | `barishal_municipality` | `barishalmunicipality123` | Barishal | Barisal |
| Police | `sylhet_police` | `sylhetpolice123` | Sylhet | Sylhet |
| Fire Service | `sylhet_fire` | `sylhetfire123` | Sylhet | Sylhet |
| Hospital | `sylhet_hospital` | `sylhethospital123` | Sylhet | Sylhet |
| Municipality | `sylhet_municipality` | `sylhetmunicipality123` | Sylhet | Sylhet |
| Police | `rangpur_police` | `rangpurpolice123` | Rangpur | Rangpur |
| Fire Service | `rangpur_fire` | `rangpurfire123` | Rangpur | Rangpur |
| Hospital | `rangpur_hospital` | `rangpurhospital123` | Rangpur | Rangpur |
| Municipality | `rangpur_municipality` | `rangpurmunicipality123` | Rangpur | Rangpur |
| Police | `mymensingh_police` | `mymensinghpolice123` | Mymensingh | Jamalpur |
| Fire Service | `mymensingh_fire` | `mymensinghfire123` | Mymensingh | Jamalpur |
| Hospital | `mymensingh_hospital` | `mymensinghhospital123` | Mymensingh | Jamalpur |
| Municipality | `mymensingh_municipality` | `mymensinghmunicipality123` | Mymensingh | Jamalpur |

Each Division Municipality account logs into the exact same
`organization_dashboard()` used by that division's Police/Fire
Service/Hospital accounts, scoped to only that division's own areas
— sensor readings, flood risk/probability, predicted water level,
map, and messaging (to its own Division Admin) all follow the same
division-only restriction. It's also included in the Division
Admin's own "Notify Division Emergency Organizations" siren and
messaging recipient list, and in the automatic High/Severe-risk
alert broadcast, alongside Police/Fire Service/Hospital.

None of these hierarchical accounts go through email 2FA — that
applies only to `system_handler`.

### District Admin accounts (parallel, district-scoped tier)

A **separate** admin tier from the Division Admin hierarchy above —
a District Admin gets the same Administrator-equivalent dashboard and
capabilities, restricted to exactly one district's own areas.

| Role | Username | Password | District | Areas covered |
|---|---|---|---|---|
| District Admin | `admin_dhaka` | `dhakadistrict123` | Dhaka | Dhaka, Mirpur, Uttara, Dhanmondi, Tejgaon, Jatrabari, Keraniganj, Savar, Narayanganj |
| District Admin | `admin_chattogram` | `chattogramdistrict123` | Chattogram | Chittagong |
| District Admin | `admin_rajshahi` | `rajshahidistrict123` | Rajshahi | Rajshahi |
| District Admin | `admin_khulna` | `khulnadistrict123` | Khulna | Khulna |
| District Admin | `admin_barishal` | `barishaldistrict123` | Barishal | Barisal |
| District Admin | `admin_sylhet` | `sylhetdistrict123` | Sylhet | Sylhet |
| District Admin | `admin_rangpur` | `rangpurdistrict123` | Rangpur | Rangpur |
| District Admin | `admin_mymensingh` | `mymensinghdistrict123` | Mymensingh | Mymensingh, Jamalpur |
| District Admin | `admin_jamalpur` | `jamalpurdistrict123` | Jamalpur | Jamalpur |

Note the deliberate overlap: Jamalpur is a real sub-area of Mymensingh
in this app's data, so both the Mymensingh and Jamalpur district
admins can see that one area — mirroring genuine nested administrative
hierarchy, not a bug.

### District Police / Fire Service / Municipality accounts

Every district also has its own Police, Fire Service and Municipality
account, alongside its District Admin above — each restricted to
exactly that district's own areas, with its own mailbox and its own
emergency-alert read state (role strings are prefixed "District " so
they're never confused with a division-specific org account such as
"Dhaka Police").

| Role | Username | Password | District |
|---|---|---|---|
| District Police | `dhaka_district_police` | `dhakadistrictpolice123` | Dhaka |
| District Fire Service | `dhaka_district_fire` | `dhakadistrictfire123` | Dhaka |
| District Municipality | `dhaka_district_municipality` | `dhakadistrictmunicipality123` | Dhaka |
| District Police | `chattogram_district_police` | `chattogramdistrictpolice123` | Chattogram |
| District Fire Service | `chattogram_district_fire` | `chattogramdistrictfire123` | Chattogram |
| District Municipality | `chattogram_district_municipality` | `chattogramdistrictmunicipality123` | Chattogram |
| District Police | `rajshahi_district_police` | `rajshahidistrictpolice123` | Rajshahi |
| District Fire Service | `rajshahi_district_fire` | `rajshahidistrictfire123` | Rajshahi |
| District Municipality | `rajshahi_district_municipality` | `rajshahidistrictmunicipality123` | Rajshahi |
| District Police | `khulna_district_police` | `khulnadistrictpolice123` | Khulna |
| District Fire Service | `khulna_district_fire` | `khulnadistrictfire123` | Khulna |
| District Municipality | `khulna_district_municipality` | `khulnadistrictmunicipality123` | Khulna |
| District Police | `barishal_district_police` | `barishaldistrictpolice123` | Barishal |
| District Fire Service | `barishal_district_fire` | `barishaldistrictfire123` | Barishal |
| District Municipality | `barishal_district_municipality` | `barishaldistrictmunicipality123` | Barishal |
| District Police | `sylhet_district_police` | `sylhetdistrictpolice123` | Sylhet |
| District Fire Service | `sylhet_district_fire` | `sylhetdistrictfire123` | Sylhet |
| District Municipality | `sylhet_district_municipality` | `sylhetdistrictmunicipality123` | Sylhet |
| District Police | `rangpur_district_police` | `rangpurdistrictpolice123` | Rangpur |
| District Fire Service | `rangpur_district_fire` | `rangpurdistrictfire123` | Rangpur |
| District Municipality | `rangpur_district_municipality` | `rangpurdistrictmunicipality123` | Rangpur |
| District Police | `mymensingh_district_police` | `mymensinghdistrictpolice123` | Mymensingh |
| District Fire Service | `mymensingh_district_fire` | `mymensinghdistrictfire123` | Mymensingh |
| District Municipality | `mymensingh_district_municipality` | `mymensinghdistrictmunicipality123` | Mymensingh |
| District Police | `jamalpur_district_police` | `jamalpurdistrictpolice123` | Jamalpur |
| District Fire Service | `jamalpur_district_fire` | `jamalpurdistrictfire123` | Jamalpur |
| District Municipality | `jamalpur_district_municipality` | `jamalpurdistrictmunicipality123` | Jamalpur |

Each of these reuses `organization_dashboard()` (the exact same
dashboard the division-specific Police/Fire Service/Hospital accounts
use) scoped by `district` instead of `division`: area selection,
sensor readings, flood risk/probability, predicted water level, the
hybrid model breakdown and the map are all restricted to that
district's own areas, and messaging is restricted to that district's
own District Admin.

The login form is a proper Streamlit form, so after typing your
password you can just press **Enter** — no need to click **Login**.
This also applies at the OTP step (press Enter instead of clicking
**Verify Code**).

## Features

### 1. Sensor monitoring & hybrid flood prediction
- Simulated sensor readings (water level, rainfall, river flow,
  temperature, humidity, soil moisture, wind speed) per location.
- Flood probability from a genuine **hybrid physics + machine-learning
  framework** (see section 13 below) and 4-band risk classification
  (Low / Moderate / High / Severe).
- Interactive map and historical charts.

### 2. Administrator dashboard layout
The Administrator dashboard follows one consistent flow, top to
bottom:

```
📍 Location Selection
        ↓
🗺️ Live Flood Location Map
        ↓
📊 Current Prediction (for the selected location)
        ↓
📈 Sensor & Monitoring Information (tabs: Live Data / All-Location
   Predictions / Charts)
        ↓
🚨 Emergency Response & Communication (tabs: Messaging / SMTP
   Status / My Mailbox / Siren)
        ↓
⚙️ Advanced Configuration (tabs: Sensor Configuration / External
   Dataset Input)
```

**📍 Location Selection** is a single shared control near the top.
Whatever location is chosen there is used consistently for the map,
the Current Prediction card, and external dataset assignment.

### 3. System Handler email-based Two-Factor Authentication (2FA)
```
Username + Password → Correct password → 6-digit OTP emailed
        → Enter OTP in portal → Admin Dashboard
```
- **Password protection** — 5 wrong passwords locks the account for
  **15 minutes**, enforced in the database so refreshing can't reset it.
- **OTP delivery** — random 6-digit code, emailed via Gmail SMTP,
  hashed at rest, plaintext never stored.
- **OTP expiry & reuse** — expires after **5 minutes**, single use.
- **OTP attempts** — 5 wrong codes invalidates it.
- **Resend OTP** — 30-second cooldown.
- Every other role logs in with just a username and password.

### 4. "Remember this device" (System Handler — skips OTP only)
On the OTP screen, checking **"Remember this device"** stores a
hashed token as a real browser cookie. On a later visit, the
**password is still always required**, but the OTP step is skipped
if the cookie matches. Trust lasts 30 days. A **"🔓 Forget this
device"** button in the sidebar revokes it immediately. Logging out
does **not** revoke it (that's the point — you'd have to explicitly
forget it).

### 5. External dataset input (CSV or XLSX)
Upload real sensor observations from **📂 External Dataset Input**
(inside ⚙️ Advanced Configuration). The file doesn't need a location
column — it's assigned to whichever location is currently selected
in 📍 Location Selection.

Required columns: `water_level`, `rainfall`, `river_flow`,
`temperature`, `humidity`, `soil_moisture`, `wind_speed`
(`sensor_id`/`timestamp` optional, auto-filled if missing). Common
column-name variants (`rain`, `temp`, `windspeed`, ...) are
normalized automatically.

Once a location has an uploaded dataset, simulation for it stops and
prediction uses the **latest** uploaded record instead; other
locations keep simulating normally. A **🗑️ Remove Dataset** button
per location resumes simulation for it.

### 6. Emergency messaging & simulated internal email server
- **📨 Admin → Emergency Organization Messaging** — send to one
  organization or all at once.
- **🚨 Emergency Siren** — one-click alerts to Police, Fire Service,
  Hospital, or all.
- **📧 Email Server (SMTP) Status** — shows the simulated server
  online, lists mailbox addresses, logs every outgoing message.

This internal system is entirely simulated and is **not** connected
to the real Gmail account used for System Handler 2FA.

### 7. Two-way mailbox: Inbox / Sent / Compose / Bin
Every role has its own private mailbox — Inbox (with live unread
count), Sent, Compose (not shown for System Handler, which uses
Emergency Messaging instead), and Bin (Restore / Delete Permanently
/ Empty Bin). Strictly per-account: a hierarchical account like
Dhaka Police has its own fully separate mailbox from the legacy
`police` account, and can only compose to its own Division Admin —
see **Hierarchical Administration** below.

### 8. Live Flood Location Map
- Every marker is **always labeled** with its risk circle + location
  name (e.g. `🟠 Tejgaon`) directly on the map — not hover-only.
- Marker size has a **visible floor**, so even a very-low-risk
  reading is never shrunk to an invisible dot.
- Colors: 🟢 Low, 🟡 Moderate, 🟠 High, 🔴 Severe — a plain-text
  legend caption sits under every map as a backup to the Plotly
  legend.
- On the Admin, Organization, and Division Admin dashboards, picking
  a location/area re-centers and zooms the map onto it (other
  locations stay visible, just not initially in frame).

### 9. Risk-at-a-glance badges
Above the location/area selector on Organization and Division Admin
dashboards, a row of small badges (e.g. `🟢 Tejgaon • 🟠 Mirpur`)
shows every relevant location's current risk before you even pick
one. (Removed from the Admin's nationwide Location Selection, since
that list mixes in many cities with no sensor data yet and just
became visual noise there.)

### 10. 🚨 Emergency Alert System (blinking + sound)
When an alert is created — manually via the siren, or automatically
(see below) — every targeted account's dashboard immediately shows
**one** consolidated, continuously **blinking** red banner with the
title, message, sender, division/area, and time.

- **Sound starts automatically** — no click required. A short
  offline-generated siren tone loops via `<audio autoplay>`. (Most
  browsers allow this once you've interacted with the page at all,
  which logging in already counts as; a small caption under the
  banner tells you to click anywhere once if your browser still
  blocked it.)
- **✅ Mark Emergency Alerts as Read** stops the blinking and sound
  immediately, for every alert currently unread for that account —
  there's exactly one button, and one click clears everything (the
  older plain-text notification log and the newer blinking/sound
  system used to be shown as two separate boxes with two separate
  buttons; they're now merged into this single banner).
- **Independent per-recipient state** — marking Dhaka Hospital's
  alert read never touches Dhaka Police's, or the legacy Hospital
  account's.
- A **"🚨 Emergency Alerts: N"** indicator sits in the sidebar for
  every alert-receiving role.

### 11. 🤖 Automatic Emergency Alerts
No admin click required: whenever any location's prediction reaches
**High or Severe** risk, an alert fires automatically — same
blinking/sound banner as a manual siren alert — to Police, Fire
Service, and Hospital nationally, plus that location's own Division
Admin and division-specific Police/Fire Service/Hospital if it
belongs to one of the 8 divisions.

Since the simulator re-randomizes every reading on every rerun, a
**5-minute cooldown per location** prevents the same location from
spamming a new alert on every page refresh — it alerts once, then
goes quiet for 5 minutes even if it keeps landing in High/Severe,
then is eligible again.

### 12. 🧭 Hierarchical Administration
```
System Handler
   └── Division Admin (one per division)
          └── Police / Fire Service / Hospital (one of each, per division)
```
- **System Handler** — System Overview with one card per division
  (worst-risk circle, avg. flood risk, high-risk area count, unread
  alerts, assigned admin), plus messaging to one or all Division
  Admins.
- **Division Admin** — sees **only** their division's areas/map/
  predictions, can pick an area to focus on, sees their division's
  Police/Fire/Hospital status cards, can fire a division-scoped
  alert, and messages only those 3 organizations + System Handler.
- **Division-specific Police/Fire/Hospital** (e.g. Dhaka Police) —
  same dashboard as the original accounts, scoped to their
  division's areas, with a fully separate mailbox and alert state,
  and a Compose list restricted to their own Division Admin.
- **Access control** is enforced via one composite identifier per
  hierarchical account (e.g. `"Dhaka Police"`) used consistently for
  its data filter, mailbox, and alert read state — a division
  account can never see or message another division's data.
- Areas reuse the app's existing `LOCATION_COORDINATES` locations
  rather than inventing new ones (e.g. Mymensingh → Jamalpur). Add
  more by editing `DIVISION_AREAS` near the top of
  `flooddashboard.py`.

### 13. 🔬 Hybrid Physics + Machine Learning Prediction Framework
The flood prediction engine is a genuine two-component hybrid — not
a renamed version of a simple scoring formula. Implemented in the
new `hybrid_model.py` (Streamlit-independent, so it can be read,
tested, or reviewed on its own).

**Physics / mathematical component** — a reduced-order water-balance
/ linear-reservoir model (explicitly *not* a full Saint-Venant
hydrodynamic solver, which is out of scope for a real-time Streamlit
prototype, and the code doesn't claim otherwise): estimated inflow
(river flow + rainfall-driven runoff, adjusted by a soil-moisture
runoff coefficient), estimated outflow (linear-reservoir term
proportional to current water level), a small evaporation term, and
the resulting predicted water-level change.

**Machine learning component** — a scikit-learn `RandomForestRegressor`,
genuinely trained via `.fit()` (not instantiated and left untrained)
on a physics-informed **synthetic** dataset — there's no bundled real
historical flood dataset for Bangladesh, and the app is honest about
that rather than pretending otherwise. Its held-out test R² and MAE
are computed for real and shown in the app, not hard-coded.

**Hybrid combination** — final probability = 60% the trained ML
model's prediction + 40% a standalone physics-only estimate; the ML
model's own inputs already include every physics-derived feature, so
physics shapes the result twice over. If scikit-learn isn't
installed, the app falls back to physics-only and labels it as such
— it never fabricates an ML result.

Every "Current Prediction" card across the Admin, Organization, and
Division/District Admin dashboards now also shows **Predicted Water
Level** and which model components actually ran, with an expandable
"How this prediction was produced" explanation. The Admin dashboard's
**⚙️ Advanced Configuration → 🔬 Model Information** tab shows the
real training metrics and feature importances.

Trained once per running app process (`st.cache_resource`), not on
every rerun.

### 14. 🏘️ District Admin (Administrator-equivalent, district-scoped)
A **separate, parallel** admin tier to Division Admin — reuses
`admin_dashboard()` itself (the exact same dashboard the main
Administrator uses) rather than a bespoke one, per the "don't build
an unnecessarily different dashboard" principle. Every section is
scoped to one district:

- **Location Selection** offers only that district's own areas — no
  "type manually" option, closing that bypass route entirely.
- **Sensor registration** uses a restricted dropdown instead of free
  text, **and** the backend rejects any out-of-district location even
  if that restriction were somehow bypassed — enforced at the
  database-write level, not just hidden in the UI.
- **Dataset upload** inherits the same restricted location selector,
  so an uploaded dataset can only ever be assigned within-district.
- **Sensor Configuration's "Registered Sensors" table** is filtered
  to that district too — a District Admin can't see other districts'
  sensors, not just be blocked from editing them.
- **Emergency Response & Communication** is replaced with a
  district-scoped Messaging / Mailbox / Siren set, targeting that
  district's parent division's Police/Fire Service/Hospital (e.g.
  Jamalpur → Mymensingh's organizations), falling back to the
  national accounts if the district has no parent division.
- Automatic emergency alerts (section 11) also reach the relevant
  District Admin(s) for any location that crosses High/Severe risk.

Districts are entirely separate from Divisions at the database level
(`users.district`, not `users.division`) so the two hierarchies can
never be confused with one another.

## Notes

- The Emergency Messaging / Inbox / Sent / Bin mail system is
  **simulated** — no real SMTP server or internet mail. Unrelated to
  the real Gmail SMTP connection used only for System Handler 2FA.
- Uploaded datasets persist only for the current browser session
  (`st.session_state.uploaded_datasets`).
- To add a new location (with map support), add it to
  `LOCATION_COORDINATES` near the top of `flooddashboard.py`.
- Reading `.xlsx` files requires the `openpyxl` package; the ML
  component of the hybrid prediction framework requires
  `scikit-learn`.
- All security/session state — 2FA lockouts, OTPs, trusted devices,
  alerts, auto-alert cooldowns — lives in `flood_monitoring.db`, so
  it survives app restarts, not just page refreshes.
