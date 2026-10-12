"""Automatic retraining of the flood models on REAL data (live mode).

In simulation mode nothing here does anything: the models stay exactly
as hybrid_model.py trains them (synthetic data only). In live mode the
models are retrained in a background thread as real readings
(`live_readings`) accumulate - see the AUTOMATIC RETRAINING block in
config.py for the rules - and a new model only replaces the current one
if it is not worse on held-out rows. Accepted models are saved as
numbered versions; the System Handler can roll back to the original.

No Streamlit dependency (it runs in a background thread).
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta

import pandas as pd

import hybrid_model
from flood_app.activity_log import ACTION_MODEL_RETRAINED, log_activity
from flood_app.config import (
    DATASET_VALUE_LIMITS,
    RETRAIN_ENABLED,
    RETRAIN_KEEP_VERSIONS,
    RETRAIN_LABELED_SHARE,
    RETRAIN_LABELED_WEIGHT,
    RETRAIN_MAX_LABELED_WEIGHT,
    RETRAIN_MAX_REAL_ROWS,
    RETRAIN_MAX_SYNTHETIC_DEGRADATION,
    RETRAIN_MIN_LABEL_R2,
    RETRAIN_MIN_INTERVAL_MINUTES,
    RETRAIN_MIN_NEW_ROWS,
    RETRAIN_MIN_REAL_ROWS,
    RETRAIN_USE_UNLABELED,
)
from flood_app.data_mode import _get_setting, _set_setting, is_live_mode
from flood_app.database import get_connection


_TS_FORMAT = "%Y-%m-%d %H:%M:%S"

_VERSION_KEY = "model_active_version"

_STATE_KEY = "model_retrain_state"

_MODEL_DIR = os.path.dirname(os.path.abspath(hybrid_model.__file__))

_run_lock = threading.Lock()

_CHECK_EVERY_SECONDS = 20

_last_check = 0.0

_version_memo = (0.0, 0)  # (read at monotonic time, version)


# ============================================================
# ACTIVE MODEL VERSION
# ============================================================

def _model_path(version):

    return os.path.join(_MODEL_DIR, f".hybrid_model_live_v{version}.joblib")


def get_active_version(max_age_seconds=5):
    """0 = original synthetic model; n > 0 = retrained version n.
    Cached for a few seconds so every prediction doesn't hit the
    database."""

    global _version_memo

    read_at, version = _version_memo

    if time.monotonic() - read_at < max_age_seconds:
        return version

    try:
        version = int(_get_setting(_VERSION_KEY, "0") or 0)
    except Exception:
        version = 0

    _version_memo = (time.monotonic(), version)

    return version


def _set_active_version(version):

    global _version_memo

    _set_setting(_VERSION_KEY, str(int(version)))

    _version_memo = (time.monotonic(), int(version))


def load_version_bundle(version):
    """Bundle of retrained version `version`, or None if its file is
    missing / unreadable (callers then fall back to the original)."""

    try:
        import joblib

        stored = joblib.load(_model_path(version))

        if (
            isinstance(stored, dict)
            and stored.get("version") == version
            and stored.get("bundle", {}).get("available")
        ):
            return stored["bundle"]

    except Exception:
        pass

    return None


def _current_bundle():
    """The bundle predictions are using right now (for comparison)."""

    version = get_active_version(max_age_seconds=0)

    if version > 0:
        bundle = load_version_bundle(version)
        if bundle:
            return bundle

    return hybrid_model.load_or_train_hybrid_ml_model()


# ============================================================
# STATE
# ============================================================

def _get_state():

    try:
        raw = _get_setting(_STATE_KEY)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _save_state(state):

    _set_setting(_STATE_KEY, json.dumps(state, default=str))


def _max_live_id():

    conn = get_connection()

    try:
        return conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM live_readings"
        ).fetchone()[0]
    finally:
        conn.close()


def count_real_rows():

    conn = get_connection()

    try:
        return conn.execute(
            "SELECT COUNT(*) FROM live_readings"
        ).fetchone()[0]
    finally:
        conn.close()


def count_new_rows():
    """Real rows that arrived since the last training attempt."""

    last_id = _get_state().get("last_attempt_max_id", 0)

    conn = get_connection()

    try:
        return conn.execute(
            "SELECT COUNT(*) FROM live_readings WHERE id > ?", (last_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def get_status():
    """Everything the training panel shows."""

    state = _get_state()

    version = get_active_version(max_age_seconds=0)

    return {
        "enabled": RETRAIN_ENABLED,
        "live_mode": is_live_mode(),
        "active_version": version,
        "running": _run_lock.locked(),
        "real_rows": count_real_rows(),
        "new_rows": count_new_rows(),
        "min_real_rows": RETRAIN_MIN_REAL_ROWS,
        "min_new_rows": RETRAIN_MIN_NEW_ROWS,
        "min_interval_minutes": RETRAIN_MIN_INTERVAL_MINUTES,
        "last_attempt_at": state.get("last_attempt_at"),
        "last_report": state.get("last_report"),
        "versions": state.get("versions", []),
    }


# ============================================================
# TRAINING DATA
# ============================================================

def _load_real_rows():

    conn = get_connection()

    try:
        frame = pd.read_sql_query(
            "SELECT id, water_level, rainfall, river_flow, temperature, "
            "humidity, soil_moisture, wind_speed, training_label "
            "FROM live_readings ORDER BY id DESC LIMIT ?",
            conn,
            params=(int(RETRAIN_MAX_REAL_ROWS),)
        )
    finally:
        conn.close()

    plausible = pd.Series(True, index=frame.index)

    for column, (low, high) in DATASET_VALUE_LIMITS.items():
        plausible &= frame[column].between(low, high)

    return frame[plausible].reset_index(drop=True)


# ============================================================
# THE RETRAIN JOB
# ============================================================

def _run(force):

    if not _run_lock.acquire(blocking=False):
        return  # a retrain is already running

    try:

        started_max_id = _max_live_id()

        state = _get_state()

        active_version = get_active_version(max_age_seconds=0)

        active = next(
            (v for v in state.get("versions", [])
             if v["version"] == active_version),
            None
        )

        if active and active.get("max_id") == started_max_id:

            _save_state({**state, "last_attempt_at": datetime.now().strftime(
                _TS_FORMAT
            ), "last_report": {
                "accepted": False,
                "skipped": True,
                "reason": (
                    f"No new real data since v{active_version}; "
                    f"nothing to retrain."
                ),
            }})

            return

        real = _load_real_rows()

        attempt = {
            "last_attempt_at": datetime.now().strftime(_TS_FORMAT),
            "last_attempt_max_id": started_max_id,
        }

        if len(real) < RETRAIN_MIN_REAL_ROWS:

            attempt["last_report"] = {
                "accepted": False,
                "skipped": True,
                "reason": (
                    f"Waiting for data: {len(real)} real row(s), "
                    f"need at least {RETRAIN_MIN_REAL_ROWS}."
                ),
            }

            # don't move last_attempt_max_id: rows are still "new"
            attempt["last_attempt_max_id"] = state.get(
                "last_attempt_max_id", 0
            )

            _save_state({**state, **attempt})

            return

        bundle, report = hybrid_model.train_with_real_data(
            real,
            previous_bundle=_current_bundle(),
            labeled_weight=RETRAIN_LABELED_WEIGHT,
            labeled_share=RETRAIN_LABELED_SHARE,
            max_labeled_weight=RETRAIN_MAX_LABELED_WEIGHT,
            use_unlabeled=RETRAIN_USE_UNLABELED,
            max_synthetic_degradation=RETRAIN_MAX_SYNTHETIC_DEGRADATION,
            min_label_r2=RETRAIN_MIN_LABEL_R2,
        )

        report["forced"] = bool(force)

        attempt["last_report"] = report

        versions = list(state.get("versions", []))

        if bundle is not None and report.get("accepted"):

            version = max(
                [v["version"] for v in versions] + [0]
            ) + 1

            _save_bundle(version, bundle)

            versions.append({
                "version": version,
                "trained_at": attempt["last_attempt_at"],
                "n_real_rows": report.get("n_real_rows"),
                "n_real_labeled": report.get("n_real_labeled"),
                "max_id": started_max_id,
                "hybrid_r2": bundle["evaluation"]["hybrid"]["r2_score"],
                "hybrid_mae": bundle["evaluation"]["hybrid"]["mae"],
            })

            versions = _prune_versions(versions)

            _set_active_version(version)

            log_activity(
                ACTION_MODEL_RETRAINED,
                username="system", role="system",
                details=(
                    f"v{version}: {report.get('n_real_rows')} real rows "
                    f"({report.get('n_real_labeled')} labelled). "
                    f"{report.get('reason')}"
                )
            )

        else:

            log_activity(
                ACTION_MODEL_RETRAINED,
                username="system", role="system",
                status="rejected",
                details=report.get("reason", "")
            )

        _save_state({**state, **attempt, "versions": versions})

    except Exception as error:

        try:
            _save_state({
                **_get_state(),
                "last_attempt_at": datetime.now().strftime(_TS_FORMAT),
                "last_report": {
                    "accepted": False,
                    "reason": f"Retraining failed: {error}",
                },
            })
        except Exception:
            pass

    finally:

        _run_lock.release()


def _save_bundle(version, bundle):

    import joblib

    fd, tmp_path = tempfile.mkstemp(dir=_MODEL_DIR, suffix=".tmp")

    os.close(fd)

    joblib.dump({"version": version, "bundle": bundle}, tmp_path)

    os.replace(tmp_path, _model_path(version))  # atomic


def _prune_versions(versions):

    keep = sorted(
        versions, key=lambda v: v["version"]
    )[-int(RETRAIN_KEEP_VERSIONS):]

    keep_numbers = {v["version"] for v in keep}

    for v in versions:
        if v["version"] not in keep_numbers:
            try:
                os.remove(_model_path(v["version"]))
            except OSError:
                pass

    return keep


# ============================================================
# TRIGGERS
# ============================================================

def request_retrain(force=False, background=True):
    """Starts a retrain now (live mode only). `force` skips the
    new-rows and interval rules (used right after a dataset upload
    and by the 'Retrain now' button). Returns (started, message)."""

    if not RETRAIN_ENABLED:
        return False, "Retraining is disabled (RETRAIN_ENABLED)."

    if not is_live_mode():
        return False, (
            "Simulation mode: models stay as they are until live "
            "mode starts."
        )

    if _run_lock.locked():
        return False, "A retrain is already running."

    if background:
        threading.Thread(
            target=_run, args=(force,), daemon=True
        ).start()
    else:
        _run(force)

    return True, "Retraining started."


def maybe_retrain():
    """Cheap, throttled check called from the live pipeline: starts a
    background retrain when enough NEW real rows arrived and enough
    time passed since the last attempt. Never raises."""

    global _last_check

    try:

        if not RETRAIN_ENABLED or not is_live_mode():
            return False

        if time.monotonic() - _last_check < _CHECK_EVERY_SECONDS:
            return False

        _last_check = time.monotonic()

        if _run_lock.locked():
            return False

        state = _get_state()

        last_at = state.get("last_attempt_at")

        if last_at:

            try:
                elapsed = datetime.now() - datetime.strptime(
                    last_at, _TS_FORMAT
                )
                if elapsed < timedelta(minutes=RETRAIN_MIN_INTERVAL_MINUTES):
                    return False
            except ValueError:
                pass

        if count_new_rows() < RETRAIN_MIN_NEW_ROWS:
            return False

        return request_retrain(force=False)[0]

    except Exception:

        return False


def rollback_to_original():
    """Go back to the original synthetic-only model. Saved versions
    are kept; a later retrain simply creates the next version."""

    _set_active_version(0)

    log_activity(
        ACTION_MODEL_RETRAINED,
        details="Rolled back to the original synthetic model."
    )
