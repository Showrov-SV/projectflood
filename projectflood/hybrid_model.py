"""
hybrid_model.py
================================================================
Hybrid Physics-Inspired + Ensemble Machine-Learning Flood
Prediction Framework
================================================================

This module implements the model exactly as specified in Section
2.2.4 of the project write-up:

2.2.4.1 PHYSICS-INSPIRED COMPONENT
    A flood risk score S is computed as a weighted linear
    combination of five sensor variables:

        S = 18*W + 0.28*R + 2.5*F + 0.12*SM + 0.08*H

    where W, R, F, SM, H are water level, rainfall, river flow,
    soil moisture, and humidity. S is mapped to a bounded
    probability P_physics via a logistic (sigmoid) transform:

        P_physics = 100 / (1 + e^(-k * (S - S_ref)))

    S_ref (calibration midpoint) and k (steepness) are documented,
    tunable constants below.

2.2.4.2 MACHINE LEARNING MODELS
    Two ensemble regressors — Random Forest (250 estimators, max
    depth 14) and XGBoost (300 estimators, max depth 7, learning
    rate 0.05) — are genuinely trained via .fit() on the raw
    sensor readings PLUS three physics-derived features (S,
    P_physics, and a water-level estimate derived from S — see
    ESTIMATED_WATER_LEVEL_DIVISOR below). An 80/20 train/test
    split is used; R² and MAE are computed honestly on the held-
    out test set for each model, never hard-coded. Their outputs
    are averaged into one ML estimate:

        P_ml = 0.5 * P_RandomForest + 0.5 * P_XGBoost

2.2.4.3 HYBRID COMBINATION
    P_hybrid = 0.60 * P_ml + 0.40 * P_physics

    If either or both ML models are unavailable (library not
    installed, or training failed), the system degrades honestly:
    P_ml is computed from whichever model(s) actually trained, and
    if NEITHER is available, the result IS P_physics alone — the
    pipeline stays operational, and callers are told exactly which
    components actually ran (never a fabricated ML number).

DATA SOURCE (Section 2.2.5): this module trains on a physics-
informed SYNTHETIC dataset, since no real historical flood dataset
for Bangladesh is bundled with the application. The application
(flooddashboard.py) separately supports uploaded CSV/XLSX datasets
and live sensor readings as the actual PREDICTION input at
runtime — this module is only responsible for producing the
prediction from whatever reading it's given, real or simulated.

This file has NO Streamlit dependency, so it can be imported,
inspected, and unit-tested completely independently of the app.
================================================================
"""

import os
import tempfile

import numpy as np
import pandas as pd

try:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error, r2_score
    SKLEARN_AVAILABLE = True
    SKLEARN_IMPORT_ERROR = None
except ImportError as _sklearn_error:
    SKLEARN_AVAILABLE = False
    SKLEARN_IMPORT_ERROR = str(_sklearn_error)

try:
    from xgboost import XGBRegressor
    XGBOOST_AVAILABLE = True
    XGBOOST_IMPORT_ERROR = None
except ImportError as _xgboost_error:
    XGBOOST_AVAILABLE = False
    XGBOOST_IMPORT_ERROR = str(_xgboost_error)


# ================================================================
# 2.2.4.1 PHYSICS-INSPIRED COMPONENT
# ================================================================

# Fixed coefficients from the specified formula:
#   S = 18*W + 0.28*R + 2.5*F + 0.12*SM + 0.08*H
COEF_WATER_LEVEL = 18.0
COEF_RAINFALL = 0.28
COEF_RIVER_FLOW = 2.5
COEF_SOIL_MOISTURE = 0.12
COEF_HUMIDITY = 0.08

# Calibration constants for the sigmoid transform. Chosen so that
# S_ref sits at a "moderate risk" score under typical conditions
# (roughly matching the earlier linear score/2.2 calibration this
# system used before the sigmoid was introduced) and k gives a
# smooth, not-too-sharp transition across the realistic S range
# (~20 at calm conditions to ~220+ at severe combined conditions).
# Both are ordinary tunable constants, not derived from any fitted
# calibration procedure.
S_REF = 110.0
SIGMOID_STEEPNESS_K = 0.02

# Divisor used to express the physics score S as a water-level-
# equivalent estimate. S's largest term is water_level * 18 (the
# other four terms are comparatively small), so S / 18 expresses
# the WHOLE weighted score back on the same scale as water level —
# a single number that also reflects the rainfall/river-flow/soil-
# moisture/humidity contributions, not just the raw current
# reading. This is a documented, explicit modeling choice for
# "the resulting water-level estimate" fed to the ML models, not a
# separately calibrated sub-model.
ESTIMATED_WATER_LEVEL_DIVISOR = COEF_WATER_LEVEL


def compute_physics_score(water_level, rainfall, river_flow, soil_moisture, humidity):
    """S = 18*W + 0.28*R + 2.5*F + 0.12*SM + 0.08*H, exactly as
    specified — no other terms, no hidden adjustments."""

    return (
        COEF_WATER_LEVEL * water_level
        + COEF_RAINFALL * rainfall
        + COEF_RIVER_FLOW * river_flow
        + COEF_SOIL_MOISTURE * soil_moisture
        + COEF_HUMIDITY * humidity
    )


def physics_probability_from_score(S):
    """P_physics = 100 / (1 + e^(-k*(S - S_ref))), clipped to a
    valid probability range."""

    P_physics = 100.0 / (
        1.0 + np.exp(-SIGMOID_STEEPNESS_K * (S - S_REF))
    )

    return float(np.clip(P_physics, 0, 99.9))


def estimated_water_level_from_score(S):
    """See ESTIMATED_WATER_LEVEL_DIVISOR above for why S / 18."""

    return float(S / ESTIMATED_WATER_LEVEL_DIVISOR)


def run_physics_model(water_level, rainfall, river_flow, soil_moisture, humidity):
    """
    Runs the full physics-inspired component on one reading and
    returns the three physics-derived quantities used everywhere
    else in this module: the raw score S, the sigmoid-mapped
    P_physics, and the water-level estimate derived from S.
    """

    S = compute_physics_score(
        water_level, rainfall, river_flow, soil_moisture, humidity
    )

    P_physics = physics_probability_from_score(S)

    water_level_estimate = estimated_water_level_from_score(S)

    return {
        "physics_score": round(float(S), 4),
        "physics_probability": round(P_physics, 2),
        "physics_water_level_estimate": round(water_level_estimate, 4),
    }


# ================================================================
# 2.2.4.2 MACHINE LEARNING MODELS
# ================================================================

RAW_FEATURE_COLUMNS = [
    "water_level", "rainfall", "river_flow", "temperature",
    "humidity", "soil_moisture", "wind_speed"
]

PHYSICS_FEATURE_COLUMNS = [
    "physics_score", "physics_probability", "physics_water_level_estimate"
]

FEATURE_COLUMNS = RAW_FEATURE_COLUMNS + PHYSICS_FEATURE_COLUMNS

RANDOM_FOREST_PARAMS = {
    "n_estimators": 250,
    "max_depth": 14,
}

XGBOOST_PARAMS = {
    "n_estimators": 300,
    "max_depth": 7,
    "learning_rate": 0.05,
}


def run_physics_model_batch(water_level, rainfall, river_flow, soil_moisture, humidity):
    """
    Vectorised twin of run_physics_model(): identical maths and
    identical rounding, but works on whole arrays at once instead
    of one reading per Python call. Returns a dict of numpy arrays
    with the same three keys run_physics_model() returns.
    """

    S = compute_physics_score(
        np.asarray(water_level, dtype=float),
        np.asarray(rainfall, dtype=float),
        np.asarray(river_flow, dtype=float),
        np.asarray(soil_moisture, dtype=float),
        np.asarray(humidity, dtype=float),
    )

    P_physics = np.clip(
        100.0 / (1.0 + np.exp(-SIGMOID_STEEPNESS_K * (S - S_REF))),
        0, 99.9
    )

    return {
        "physics_score": np.round(S, 4),
        "physics_probability": np.round(P_physics, 2),
        "physics_water_level_estimate": np.round(
            S / ESTIMATED_WATER_LEVEL_DIVISOR, 4
        ),
    }


def generate_synthetic_training_data(n_samples=4000, random_state=42):
    """
    Physics-informed SYNTHETIC training set (see the module-level
    note on data source). Every row's physics-derived features
    come from ACTUALLY running the physics model on that row's
    raw values. The target label is generated from a nonlinear
    function distinct from P_physics itself, with injected
    Gaussian noise, so the ML models have a genuine noisy
    nonlinear relationship to learn rather than a value they could
    trivially memorize from the physics features alone.

    (Vectorised: the whole dataset is built with numpy array
    operations instead of a 4000-iteration Python loop.)
    """

    rng = np.random.default_rng(random_state)

    water_level = rng.uniform(0.3, 5.5, n_samples)
    rainfall = np.clip(rng.gamma(2.0, 30.0, n_samples), 0, 250)
    river_flow = rng.uniform(0.2, 20.0, n_samples)
    temperature = rng.uniform(15, 40, n_samples)
    humidity = rng.uniform(25, 100, n_samples)
    soil_moisture = rng.uniform(5, 100, n_samples)
    wind_speed = rng.uniform(0, 45, n_samples)

    physics = run_physics_model_batch(
        water_level, rainfall, river_flow, soil_moisture, humidity
    )

    base = (
        16.0 * physics["physics_water_level_estimate"]
        + 0.20 * rainfall
        + 1.8 * river_flow
        + 0.06 * humidity
        + 0.08 * soil_moisture
        - 0.12 * np.maximum(temperature - 30, 0)
        + 0.02 * wind_speed
    )

    noise = rng.normal(0, 6.0, n_samples)

    targets = np.clip(base / 2.0 + noise, 0, 100)

    X = pd.DataFrame({
        "water_level": water_level,
        "rainfall": rainfall,
        "river_flow": river_flow,
        "temperature": temperature,
        "humidity": humidity,
        "soil_moisture": soil_moisture,
        "wind_speed": wind_speed,
        **physics,
    })

    y = pd.Series(targets, name="flood_probability_label")

    return X, y


def _train_one_model(model, model_label, X_train, X_test, y_train, y_test):
    """Shared fit + honest-evaluation logic for either regressor."""

    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    r2 = r2_score(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)

    feature_importances = {
        column: round(float(importance), 4)
        for column, importance in zip(
            FEATURE_COLUMNS, model.feature_importances_
        )
    }

    return {
        "available": True,
        "model": model,
        "model_name": model_label,
        "r2_score": round(float(r2), 4),
        "mae": round(float(mae), 3),
        "feature_importances": feature_importances,
    }


def train_hybrid_ml_model(n_samples=4000, random_state=42):
    """
    Trains BOTH ensemble models (whichever libraries are actually
    installed) on the same 80/20 split of the synthetic dataset,
    and returns a bundle describing exactly what trained and how
    well it performed on held-out data. Callers (the Streamlit
    app) should cache this bundle so training happens once per
    process, not on every rerun.
    """

    if not SKLEARN_AVAILABLE:

        return {
            "available": False,
            "random_forest": None,
            "xgboost": None,
            "feature_columns": FEATURE_COLUMNS,
            "error": (
                "scikit-learn is not installed "
                f"({SKLEARN_IMPORT_ERROR}). Install it with "
                "'pip install scikit-learn' to enable the "
                "Random Forest component."
            ),
        }

    X, y = generate_synthetic_training_data(
        n_samples=n_samples,
        random_state=random_state
    )

    X_train, X_test, y_train, y_test = train_test_split(
        X[FEATURE_COLUMNS],
        y,
        test_size=0.2,
        random_state=random_state
    )

    random_forest_result = _train_one_model(
        RandomForestRegressor(
            random_state=random_state,
            n_jobs=-1,
            **RANDOM_FOREST_PARAMS
        ),
        "Random Forest Regressor (scikit-learn)",
        X_train, X_test, y_train, y_test
    )

    # Training used every core (n_jobs=-1). Prediction on a few
    # dozen rows is far faster single-threaded: spinning up a
    # thread pool for 250 trees costs more than the work itself.
    random_forest_result["model"].set_params(n_jobs=1)

    if XGBOOST_AVAILABLE:

        xgboost_result = _train_one_model(
            XGBRegressor(
                random_state=random_state,
                **XGBOOST_PARAMS
            ),
            "XGBoost Regressor",
            X_train, X_test, y_train, y_test
        )

    else:

        xgboost_result = {
            "available": False,
            "model": None,
            "model_name": "XGBoost Regressor",
            "error": (
                "xgboost is not installed "
                f"({XGBOOST_IMPORT_ERROR}). Install it with "
                "'pip install xgboost' to enable the XGBoost "
                "component — the Random Forest component and the "
                "physics-only estimate remain fully operational "
                "without it."
            ),
        }

    return {
        "available": True,
        "random_forest": random_forest_result,
        "xgboost": xgboost_result,
        "feature_columns": FEATURE_COLUMNS,
        "n_training_samples": len(X_train),
        "n_test_samples": len(X_test),
    }


def _predict_with_model(model_result, feature_df):
    """Returns clipped 0-100 predictions (a numpy array, one value
    per row of feature_df) from one trained model result, or None
    if that model isn't available."""

    if not model_result or not model_result.get("available"):
        return None

    predictions = model_result["model"].predict(feature_df)

    return np.clip(np.asarray(predictions, dtype=float), 0, 99.9)


# ================================================================
# TRAINED-MODEL DISK CACHE
# ================================================================
# Training (4000 rows, 250-tree forest + 300-round XGBoost) takes
# several seconds. The result is deterministic (fixed seed), so it
# is saved next to this file and reused on every later launch. The
# cache is only trusted when its signature (library versions,
# hyper-parameters, physics constants, sample count, seed) matches
# exactly; otherwise, or if the file is missing/corrupt/unreadable,
# the models are simply retrained. It can never serve a stale or
# mismatched model.

MODEL_CACHE_VERSION = 1

DEFAULT_MODEL_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".hybrid_model_cache.joblib"
)


def _cache_signature(n_samples, random_state):

    signature = {
        "cache_version": MODEL_CACHE_VERSION,
        "n_samples": n_samples,
        "random_state": random_state,
        "rf_params": dict(RANDOM_FOREST_PARAMS),
        "xgb_params": dict(XGBOOST_PARAMS),
        "features": list(FEATURE_COLUMNS),
        "physics": [
            COEF_WATER_LEVEL, COEF_RAINFALL, COEF_RIVER_FLOW,
            COEF_SOIL_MOISTURE, COEF_HUMIDITY, S_REF,
            SIGMOID_STEEPNESS_K, ESTIMATED_WATER_LEVEL_DIVISOR,
        ],
        "sklearn_available": SKLEARN_AVAILABLE,
        "xgboost_available": XGBOOST_AVAILABLE,
    }

    if SKLEARN_AVAILABLE:
        import sklearn
        signature["sklearn_version"] = sklearn.__version__

    if XGBOOST_AVAILABLE:
        import xgboost
        signature["xgboost_version"] = xgboost.__version__

    return signature


def load_or_train_hybrid_ml_model(
    n_samples=4000, random_state=42, cache_path=DEFAULT_MODEL_CACHE_PATH
):
    """
    Same result as train_hybrid_ml_model(), but reuses a previously
    trained model from disk when one exists and is provably
    compatible (see the note above). Callers should still wrap this
    in their own in-process cache (st.cache_resource).
    """

    signature = _cache_signature(n_samples, random_state)

    if cache_path and SKLEARN_AVAILABLE:

        try:
            import joblib

            if os.path.exists(cache_path):

                cached = joblib.load(cache_path)

                if (
                    isinstance(cached, dict)
                    and cached.get("signature") == signature
                    and cached.get("bundle", {}).get("available")
                ):
                    return cached["bundle"]

        except Exception:
            pass  # unreadable / incompatible cache -> retrain below

    bundle = train_hybrid_ml_model(
        n_samples=n_samples, random_state=random_state
    )

    if cache_path and bundle.get("available"):

        try:
            import joblib

            directory = os.path.dirname(cache_path) or "."

            fd, tmp_path = tempfile.mkstemp(
                dir=directory, suffix=".tmp"
            )
            os.close(fd)

            joblib.dump(
                {"signature": signature, "bundle": bundle}, tmp_path
            )

            os.replace(tmp_path, cache_path)  # atomic swap

        except Exception:
            pass  # read-only folder etc. -> just skip caching

    return bundle


# ================================================================
# 2.2.4.3 HYBRID COMBINATION
# ================================================================

HYBRID_ML_WEIGHT = 0.60
HYBRID_PHYSICS_WEIGHT = 0.40


def hybrid_predict_batch(readings, model_bundle):
    """
    Runs the physics component and both ML models (whichever are
    available) on MANY readings at once and returns a DataFrame
    with one row per input row (same order/index). This is the
    fast path: one vectorised physics pass and ONE predict() call
    per model, instead of one Python call per reading.

    `readings` must contain the seven raw sensor columns
    (RAW_FEATURE_COLUMNS).

    P_ml = 0.5 * P_RandomForest + 0.5 * P_XGBoost when both are
    available; if only one is available, P_ml IS that one model's
    prediction; if neither is available, the hybrid result IS
    P_physics alone — the pipeline never stops working and never
    fabricates a missing component's output.
    """

    raw = readings[RAW_FEATURE_COLUMNS].astype(float).reset_index(drop=True)

    physics = run_physics_model_batch(
        raw["water_level"], raw["rainfall"], raw["river_flow"],
        raw["soil_moisture"], raw["humidity"]
    )

    n = len(raw)

    physics_probability = physics["physics_probability"]

    rf_probability = None
    xgb_probability = None
    ml_probability = np.full(n, np.nan)
    ml_used = False
    ml_models_used = []

    if n and model_bundle and model_bundle.get("available"):

        feature_df = raw.assign(**physics)[
            model_bundle["feature_columns"]
        ]

        rf_probability = _predict_with_model(
            model_bundle.get("random_forest"), feature_df
        )

        xgb_probability = _predict_with_model(
            model_bundle.get("xgboost"), feature_df
        )

        available_predictions = [
            p for p in (rf_probability, xgb_probability)
            if p is not None
        ]

        if rf_probability is not None:
            ml_models_used.append("Random Forest")

        if xgb_probability is not None:
            ml_models_used.append("XGBoost")

        if available_predictions:
            ml_probability = np.mean(available_predictions, axis=0)
            ml_used = True

    if ml_used:
        hybrid_probability = (
            HYBRID_ML_WEIGHT * ml_probability
            + HYBRID_PHYSICS_WEIGHT * physics_probability
        )
    else:
        # Honest degradation: no ML available, so the hybrid
        # result IS the physics-only estimate — never fabricated.
        hybrid_probability = physics_probability

    hybrid_probability = np.clip(np.round(hybrid_probability, 2), 0, 99.9)

    def _rounded_or_none(values):
        return (
            np.round(values, 2) if values is not None
            else np.full(n, np.nan)
        )

    model_name = " + ".join(ml_models_used) if ml_models_used else None

    return pd.DataFrame({
        "physics_score": physics["physics_score"],
        "physics_water_level_estimate":
            physics["physics_water_level_estimate"],
        "physics_probability": np.round(physics_probability, 2),
        "rf_probability": _rounded_or_none(rf_probability),
        "xgb_probability": _rounded_or_none(xgb_probability),
        "ml_probability": np.round(ml_probability, 2),
        "ml_used": ml_used,
        "hybrid_probability": hybrid_probability,
        "predicted_water_level": physics["physics_water_level_estimate"],
        "model_name": model_name,
    })


def hybrid_predict(
    water_level,
    rainfall,
    river_flow,
    temperature,
    humidity,
    soil_moisture,
    wind_speed,
    model_bundle
):
    """
    Single-reading convenience wrapper around hybrid_predict_batch()
    (same return format as before). Prefer the batch function when
    you have more than one reading.
    """

    out = hybrid_predict_batch(
        pd.DataFrame([{
            "water_level": water_level,
            "rainfall": rainfall,
            "river_flow": river_flow,
            "temperature": temperature,
            "humidity": humidity,
            "soil_moisture": soil_moisture,
            "wind_speed": wind_speed,
        }]),
        model_bundle
    ).iloc[0]

    def _opt(value):
        return None if pd.isna(value) else float(value)

    ml_models_used = (
        out["model_name"].split(" + ") if out["model_name"] else []
    )

    return {
        "physics": {
            "physics_score": float(out["physics_score"]),
            "physics_probability": float(out["physics_probability"]),
            "physics_water_level_estimate":
                float(out["physics_water_level_estimate"]),
        },
        "physics_probability": float(out["physics_probability"]),
        "rf_probability": _opt(out["rf_probability"]),
        "xgb_probability": _opt(out["xgb_probability"]),
        "ml_probability": _opt(out["ml_probability"]),
        "ml_used": bool(out["ml_used"]),
        "ml_models_used": ml_models_used,
        "hybrid_probability": float(out["hybrid_probability"]),
        "predicted_water_level": float(out["predicted_water_level"]),
        "model_name": out["model_name"],
    }
