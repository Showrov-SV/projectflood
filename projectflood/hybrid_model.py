"""
hybrid_model.py
================================================================
Hybrid Physics-Inspired + Ensemble Machine-Learning Flood
Prediction Framework (version 2)
================================================================

This module implements the model specified in Section 2.3.4 of the
paper ("Hybrid Prediction System").

2.3.4.1 PHYSICS-INSPIRED COMPONENT
    A flood risk score S is computed as a weighted linear
    combination of five sensor variables:

        S = 18*W + 0.28*R + 2.5*F + 0.12*SM + 0.08*H

    where W, R, F, SM, H are water level, rainfall, river flow,
    soil moisture, and humidity. S is mapped to a bounded
    probability P_physics via a logistic (sigmoid) transform:

        P_physics = 100 / (1 + e^(-k * (S - S_ref)))

    with S_ref = 90 and k = 0.03 (see the calibration note below).
    The component also returns a short-term water-level estimate in
    metres: the observed level plus a small fraction of the extra
    load (rainfall, river inflow, wet soil) that S adds on top of it.

2.3.4.2 MACHINE LEARNING MODELS
    Two ensemble regressors - Random Forest (250 trees, max depth
    14, min leaf 2) and XGBoost (300 rounds, max depth 7, learning
    rate 0.05, row/column subsampling 0.85; both models monotone-
    increasing in the physical flood drivers) - are trained via .fit() on the
    seven raw sensor readings PLUS three physics-derived features
    (S, P_physics and the water-level estimate). An 80/20
    train/test split is used; R^2 and MAE are computed on the
    held-out test set for each model and for the whole hybrid,
    never hard-coded. Their outputs are averaged:

        P_ml = 0.5 * P_RandomForest + 0.5 * P_XGBoost

2.3.4.3 HYBRID COMBINATION
    P_hybrid = 0.60 * P_ml + 0.40 * P_physics

    If either or both ML models are unavailable (library not
    installed, or training failed), the system degrades honestly:
    P_ml is computed from whichever model(s) actually trained, and
    if NEITHER is available, the result IS P_physics alone - the
    pipeline stays operational, and callers are told exactly which
    components actually ran (never a fabricated ML number).

DATA SOURCE AND LIMITS (Section 2.3.5)
    The models are trained on a physics-informed SYNTHETIC dataset,
    because no real historical flood dataset for Bangladesh is
    bundled. The synthetic label comes from a nonlinear
    "hydrological stress" function that is deliberately different
    from S (effective rainfall that depends on soil wetness, a
    compounding water-level x rainfall term, small temperature and
    wind effects, and measurement noise), so the ML models have
    something to learn beyond the linear score. The reported R^2
    and MAE therefore measure how well the models learned THAT
    synthetic relationship - they are NOT accuracy on real floods.
    S_REF, SIGMOID_STEEPNESS_K, WATER_LEVEL_RESPONSE and the label
    function are hand-chosen assumptions, not fitted to observed
    events. To use this in a real deployment, replace
    generate_synthetic_training_data() with historical sensor/flood
    observations, refit these constants, and retrain.

RETRAINING ON REAL DATA (live mode)
    Simulated readings are NEVER used for training. Real data
    (uploaded datasets and real sensors) is used only by
    train_with_real_data() below, which flood_app/retraining.py
    calls automatically in live mode: synthetic base set + real rows
    (labelled rows weighted up; unlabelled rows get a weak label
    from the synthetic label function). Before the first retrain,
    and whenever the system is in simulation mode, the models are
    exactly the synthetic-only models described above.

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
# 2.3.4.1 PHYSICS-INSPIRED COMPONENT
# ================================================================

# Fixed coefficients from the specified formula:
#   S = 18*W + 0.28*R + 2.5*F + 0.12*SM + 0.08*H
COEF_WATER_LEVEL = 18.0
COEF_RAINFALL = 0.28
COEF_RIVER_FLOW = 2.5
COEF_SOIL_MOISTURE = 0.12
COEF_HUMIDITY = 0.08

# Calibration constants for the sigmoid transform (paper section
# 2.3.4.1). S_REF is the score at which P_physics is exactly 50 %.
# It is anchored to a stated reference scenario - a river at 2.5 m
# with 60 mm rainfall, 6 river flow, 50 % soil moisture and 70 %
# humidity gives S ~ 88 - so "moderate conditions" sit at roughly
# even odds. k = 0.03 gives a smooth transition across the realistic
# S range (~20 calm to ~240 severe). Both are hand-chosen, NOT
# fitted to observed flood data: validating them against real
# events is future work.
S_REF = 90.0
SIGMOID_STEEPNESS_K = 0.03

# Short-term water-level response. S / 18 re-expresses the WHOLE
# score on the water-level scale, so S / 18 - W is the extra "load"
# (rainfall, river inflow, wet soil, humidity) on top of the
# current level. The estimate is the observed level plus this
# fraction of that load, in metres (typically a rise of a few cm to
# a few tens of cm). It is a documented, uncalibrated model-state
# estimate, not a hydraulic simulation.
WATER_LEVEL_RESPONSE = 0.05


def compute_physics_score(water_level, rainfall, river_flow, soil_moisture, humidity):
    """S = 18*W + 0.28*R + 2.5*F + 0.12*SM + 0.08*H, exactly as
    specified - no other terms, no hidden adjustments."""

    return (
        COEF_WATER_LEVEL * water_level
        + COEF_RAINFALL * rainfall
        + COEF_RIVER_FLOW * river_flow
        + COEF_SOIL_MOISTURE * soil_moisture
        + COEF_HUMIDITY * humidity
    )


def physics_probability_from_score(S):
    """P_physics = 100 / (1 + e^(-k*(S - S_ref))), clipped to a
    valid probability range. Works on scalars and numpy arrays."""

    exponent = np.clip(
        -SIGMOID_STEEPNESS_K * (np.asarray(S, dtype=float) - S_REF),
        -60, 60
    )

    return np.clip(100.0 / (1.0 + np.exp(exponent)), 0, 99.9)


def estimated_water_level(S, water_level):
    """Short-term water-level estimate in metres (see
    WATER_LEVEL_RESPONSE). Never below the observed level, never
    negative."""

    S = np.asarray(S, dtype=float)
    water_level = np.asarray(water_level, dtype=float)

    load = np.maximum(S / COEF_WATER_LEVEL - water_level, 0.0)

    return np.maximum(water_level + WATER_LEVEL_RESPONSE * load, 0.0)


def run_physics_model(water_level, rainfall, river_flow, soil_moisture, humidity):
    """
    Runs the full physics-inspired component on one reading and
    returns the three physics-derived quantities used everywhere
    else in this module: the raw score S, the sigmoid-mapped
    P_physics, and the short-term water-level estimate.
    """

    S = compute_physics_score(
        water_level, rainfall, river_flow, soil_moisture, humidity
    )

    return {
        "physics_score": round(float(S), 4),
        "physics_probability": round(
            float(physics_probability_from_score(S)), 2
        ),
        "physics_water_level_estimate": round(
            float(estimated_water_level(S, water_level)), 4
        ),
    }


def run_physics_model_batch(water_level, rainfall, river_flow, soil_moisture, humidity):
    """
    Vectorised twin of run_physics_model(): identical maths and
    identical rounding, but works on whole arrays at once. Returns a
    dict of numpy arrays with the same three keys.
    """

    water_level = np.asarray(water_level, dtype=float)

    S = compute_physics_score(
        water_level,
        np.asarray(rainfall, dtype=float),
        np.asarray(river_flow, dtype=float),
        np.asarray(soil_moisture, dtype=float),
        np.asarray(humidity, dtype=float),
    )

    return {
        "physics_score": np.round(S, 4),
        "physics_probability": np.round(
            physics_probability_from_score(S), 2
        ),
        "physics_water_level_estimate": np.round(
            estimated_water_level(S, water_level), 4
        ),
    }


# ================================================================
# 2.3.4.2 MACHINE LEARNING MODELS
# ================================================================

RAW_FEATURE_COLUMNS = [
    "water_level", "rainfall", "river_flow", "temperature",
    "humidity", "soil_moisture", "wind_speed"
]

PHYSICS_FEATURE_COLUMNS = [
    "physics_score", "physics_probability", "physics_water_level_estimate"
]

FEATURE_COLUMNS = RAW_FEATURE_COLUMNS + PHYSICS_FEATURE_COLUMNS

# Both models are constrained to be non-decreasing in every
# physical flood driver (water level, rainfall, river flow, humidity,
# soil moisture) and in the three physics features: more water can
# never lower the predicted risk. Temperature and wind speed are left
# unconstrained. The tuple follows FEATURE_COLUMNS order. (Needs
# scikit-learn >= 1.4 for the forest.)
MONOTONE_CONSTRAINTS = (1, 1, 1, 0, 1, 1, 0, 1, 1, 1)

RANDOM_FOREST_PARAMS = {
    "n_estimators": 250,
    "max_depth": 14,
    "min_samples_leaf": 2,
    "monotonic_cst": list(MONOTONE_CONSTRAINTS),
}

XGBOOST_PARAMS = {
    "n_estimators": 300,
    "max_depth": 7,
    "learning_rate": 0.05,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "monotone_constraints": MONOTONE_CONSTRAINTS,
}

DEFAULT_TRAINING_SAMPLES = 5000

# Version tag of the synthetic label function below; part of the
# model-cache signature so changing the label retrains the models.
SYNTHETIC_LABEL_VERSION = "stress-v1"


def synthetic_flood_label(
    water_level, rainfall, river_flow, temperature, humidity,
    soil_moisture, wind_speed, rng=None
):
    """
    Synthetic ground-truth flood probability (0-99.9) used ONLY to
    train and evaluate the ML models. It is a nonlinear
    "hydrological stress" function that is deliberately different
    from the physics score S:

      * effective rainfall = rainfall x (0.4 + 0.6 x soil wetness)
        - wet soil turns more rain into runoff;
      * a compounding water-level x effective-rainfall term;
      * small temperature (evaporation) and wind effects;
      * Gaussian measurement noise on the stress.

    The structure and every constant here are assumptions chosen for
    plausibility, not fitted to observed events.
    """

    effective_rain = rainfall * (0.4 + 0.6 * soil_moisture / 100.0)

    stress = (
        0.85 * water_level
        + 0.012 * effective_rain
        + 0.10 * river_flow
        + 0.35 * water_level * effective_rain / 100.0
        + 0.006 * (humidity - 70.0)
        - 0.03 * np.maximum(temperature - 32.0, 0.0)
        + 0.010 * wind_speed
    )

    if rng is not None:
        stress = stress + rng.normal(0.0, 0.35, np.shape(stress))

    probability = 100.0 / (1.0 + np.exp(-np.clip(
        (stress - 3.8) / 2.0, -60, 60
    )))

    return np.clip(probability, 0.0, 99.9)


def generate_synthetic_training_data(
    n_samples=DEFAULT_TRAINING_SAMPLES, random_state=42
):
    """
    Physics-informed SYNTHETIC training set (see the module-level
    note on data source). Raw readings are drawn from plausible
    ranges; every row's physics-derived features come from ACTUALLY
    running the physics model on that row, and its target comes from
    synthetic_flood_label(). Fully vectorised.
    """

    rng = np.random.default_rng(random_state)

    water_level = rng.uniform(0.2, 6.0, n_samples)
    rainfall = np.clip(rng.gamma(2.0, 35.0, n_samples), 0, 300)
    river_flow = rng.uniform(0.2, 25.0, n_samples)
    temperature = rng.uniform(15, 40, n_samples)
    humidity = rng.uniform(25, 100, n_samples)
    soil_moisture = rng.uniform(5, 100, n_samples)
    wind_speed = rng.uniform(0, 45, n_samples)

    physics = run_physics_model_batch(
        water_level, rainfall, river_flow, soil_moisture, humidity
    )

    targets = synthetic_flood_label(
        water_level, rainfall, river_flow, temperature, humidity,
        soil_moisture, wind_speed, rng=rng
    )

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


def _train_one_model(
    model, model_label, X_train, X_test, y_train, y_test,
    sample_weight=None
):
    """Shared fit + honest-evaluation logic for either regressor."""

    if sample_weight is None:
        model.fit(X_train, y_train)
    else:
        model.fit(X_train, y_train, sample_weight=sample_weight)

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


def _evaluate_components(X_test, y_test, random_forest_result, xgboost_result):
    """Held-out R^2 / MAE for the physics-only estimate, the ML
    ensemble and the full hybrid, on the SAME test rows (synthetic
    labels - see the module docstring). Lets the paper and the code
    report how much each component contributes."""

    def metrics(prediction):
        return {
            "r2_score": round(float(r2_score(y_test, prediction)), 4),
            "mae": round(float(mae_fn(y_test, prediction)), 3),
        }

    mae_fn = mean_absolute_error

    physics = X_test["physics_probability"].to_numpy(dtype=float)

    predictions = [
        p for p in (
            _predict_with_model(random_forest_result, X_test),
            _predict_with_model(xgboost_result, X_test),
        ) if p is not None
    ]

    evaluation = {"physics_only": metrics(physics)}

    if predictions:

        ml = np.mean(predictions, axis=0)

        hybrid = np.clip(
            HYBRID_ML_WEIGHT * ml + HYBRID_PHYSICS_WEIGHT * physics,
            0, 99.9
        )

        evaluation["ml_ensemble"] = metrics(ml)
        evaluation["hybrid"] = metrics(hybrid)

    return evaluation


def train_hybrid_ml_model(
    n_samples=DEFAULT_TRAINING_SAMPLES, random_state=42
):
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
        "evaluation": _evaluate_components(
            X_test, y_test, random_forest_result, xgboost_result
        ),
    }


def _hybrid_from_models(rf_result, xgb_result, feature_df):
    """Hybrid probability (0.6 ML + 0.4 physics) of a set of trained
    models on feature_df rows - used to compare an old and a new
    model on identical rows."""

    predictions = [
        p for p in (
            _predict_with_model(rf_result, feature_df),
            _predict_with_model(xgb_result, feature_df),
        ) if p is not None
    ]

    physics = feature_df["physics_probability"].to_numpy(dtype=float)

    if not predictions:
        return physics

    return np.clip(
        HYBRID_ML_WEIGHT * np.mean(predictions, axis=0)
        + HYBRID_PHYSICS_WEIGHT * physics,
        0, 99.9
    )


def _predict_with_model(model_result, feature_df):
    """Returns clipped 0-100 predictions (a numpy array, one value
    per row of feature_df) from one trained model result, or None
    if that model isn't available."""

    if not model_result or not model_result.get("available"):
        return None

    predictions = model_result["model"].predict(feature_df)

    return np.clip(np.asarray(predictions, dtype=float), 0, 99.9)


# ================================================================
# RETRAINING ON REAL DATA
# ================================================================

def train_with_real_data(
    real_df,
    previous_bundle=None,
    n_synthetic=DEFAULT_TRAINING_SAMPLES,
    random_state=42,
    labeled_weight=5.0,
    use_unlabeled=True,
    max_synthetic_degradation=0.25,
    min_gate_rows=30,
    min_label_r2=0.15,
    weak_tolerance=0.10,
    labeled_share=0.7,
    max_labeled_weight=50.0,
):
    """
    Trains both models on the synthetic base set PLUS real rows.

    real_df : DataFrame with the seven raw sensor columns and an
              optional `training_label` column (0-99.9 flood
              probability; NaN/missing = unlabelled).
    previous_bundle : the model bundle currently in use. When given,
              the new models are compared with it on the SAME
              held-out rows and the result says whether the new
              models may replace it.

    Row treatment:
      * synthetic rows ............ weight 1
      * real, labelled ............ weight chosen so that these rows
        together carry `labeled_share` of the total training weight
        (never below `labeled_weight`, never above
        `max_labeled_weight`). Real outcomes must be able to
        outweigh the 5000 assumed synthetic rows, otherwise real
        labels that disagree with the synthetic formula would just
        be averaged away.
      * real, unlabelled .......... weight 1, weak label from
        synthetic_flood_label() (only if `use_unlabeled`)

    Acceptance rule (applied only when previous_bundle is given):

      A) Enough real LABELLED rows held out (>= `min_gate_rows`):
         the new hybrid must (1) have a lower MAE than the old one
         on those rows AND (2) explain a real share of their
         variance (R2 >= `min_label_r2`). Condition (2) is what
         rejects garbage / unrelated labels: random labels cannot be
         predicted from the sensor readings. The synthetic base rows
         are NOT used as a veto here - the synthetic formula is only
         an assumption, and if real outcomes differ from it the
         model is supposed to move towards the real outcomes.

      B) Otherwise (no / few real labels - the data teaches value
         ranges, not truth): the new hybrid's MAE on held-out real
         rows (or all held-out rows if too few) may be at most
         `weak_tolerance` (fraction, plus 0.25) worse than the old
         one's - so noise on a small sample does not block it - AND
         on held-out SYNTHETIC rows it may not be more than
         `max_synthetic_degradation` worse.

    Returns (bundle_or_None, report). bundle is None when training
    could not run; otherwise it has the usual bundle layout plus
    "training_info". report["accepted"] says whether the caller
    should switch to it.
    """

    report = {"accepted": False, "reason": ""}

    if not SKLEARN_AVAILABLE:
        report["reason"] = "scikit-learn is not installed."
        return None, report

    X_s, y_s = generate_synthetic_training_data(
        n_samples=n_synthetic, random_state=random_state
    )

    raw = real_df[RAW_FEATURE_COLUMNS].astype(float)

    valid = raw.notna().all(axis=1) & np.isfinite(raw).all(axis=1)

    real_df = real_df[valid.to_numpy()].reset_index(drop=True)

    raw = raw[valid.to_numpy()].reset_index(drop=True)

    if "training_label" in real_df.columns:
        labels = pd.to_numeric(
            real_df["training_label"], errors="coerce"
        ).to_numpy(dtype=float)
    else:
        labels = np.full(len(real_df), np.nan)

    labeled = ~np.isnan(labels)

    keep = labeled | bool(use_unlabeled)

    # Optional stable row ids (live_readings.id). When present, each
    # real row is ALWAYS in the test set or ALWAYS in the training set
    # (decided by a hash of its id), so a later retrain never tests
    # the new model against rows the previous model was trained on.
    ids = (
        real_df["id"].to_numpy(dtype=np.int64)[keep]
        if "id" in real_df.columns else None
    )

    raw = raw[keep].reset_index(drop=True)

    labels = labels[keep]

    labeled = labeled[keep]

    if len(raw) == 0:
        report["reason"] = "No usable real rows."
        return None, report

    weak = synthetic_flood_label(
        raw["water_level"].to_numpy(), raw["rainfall"].to_numpy(),
        raw["river_flow"].to_numpy(), raw["temperature"].to_numpy(),
        raw["humidity"].to_numpy(), raw["soil_moisture"].to_numpy(),
        raw["wind_speed"].to_numpy(), rng=None
    )

    y_r = pd.Series(
        np.where(labeled, np.clip(labels, 0, 99.9), weak),
        name="flood_probability_label"
    )

    physics = run_physics_model_batch(
        raw["water_level"], raw["rainfall"], raw["river_flow"],
        raw["soil_moisture"], raw["humidity"]
    )

    X_r = pd.DataFrame({**{c: raw[c].to_numpy() for c in RAW_FEATURE_COLUMNS},
                        **physics})

    X = pd.concat(
        [X_s[FEATURE_COLUMNS], X_r[FEATURE_COLUMNS]], ignore_index=True
    )

    y = pd.concat([y_s, y_r], ignore_index=True)

    source = np.array(
        ["synthetic"] * len(X_s)
        + ["real_labeled" if flag else "real_weak" for flag in labeled]
    )

    n_syn = len(X_s)

    syn_train, syn_test = train_test_split(
        np.arange(n_syn), test_size=0.2, random_state=random_state
    )

    real_positions = np.arange(n_syn, len(X))

    if ids is not None:

        hashed_test = ((ids * 2654435761) % (2 ** 32)) % 5 == 0

        real_train = real_positions[~hashed_test]

        real_test = real_positions[hashed_test]

    elif len(real_positions) > 1:

        real_train, real_test = train_test_split(
            real_positions, test_size=0.2, random_state=random_state
        )

    else:

        real_train, real_test = real_positions, real_positions[:0]

    train_idx = np.concatenate([syn_train, real_train])

    test_idx = np.concatenate([syn_test, real_test])

    n_labeled_train = int((source[train_idx] == "real_labeled").sum())

    labeled_weight_used = float(labeled_weight)

    if n_labeled_train:

        other_weight = len(train_idx) - n_labeled_train

        wanted = (
            labeled_share / (1.0 - labeled_share)
            * other_weight / n_labeled_train
        )

        labeled_weight_used = float(
            np.clip(wanted, labeled_weight, max_labeled_weight)
        )

    weights = np.where(
        source == "real_labeled", labeled_weight_used, 1.0
    )

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]

    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    w_train = weights[train_idx]

    src_test = source[test_idx]

    random_forest_result = _train_one_model(
        RandomForestRegressor(
            random_state=random_state, n_jobs=-1, **RANDOM_FOREST_PARAMS
        ),
        "Random Forest Regressor (scikit-learn)",
        X_train, X_test, y_train, y_test, sample_weight=w_train
    )

    random_forest_result["model"].set_params(n_jobs=1)

    if XGBOOST_AVAILABLE:

        xgboost_result = _train_one_model(
            XGBRegressor(random_state=random_state, **XGBOOST_PARAMS),
            "XGBoost Regressor",
            X_train, X_test, y_train, y_test, sample_weight=w_train
        )

    else:

        xgboost_result = {
            "available": False, "model": None,
            "model_name": "XGBoost Regressor",
            "error": "xgboost is not installed.",
        }

    n_real = int((source != "synthetic").sum())

    n_labeled = int((source == "real_labeled").sum())

    bundle = {
        "available": True,
        "random_forest": random_forest_result,
        "xgboost": xgboost_result,
        "feature_columns": FEATURE_COLUMNS,
        "n_training_samples": len(X_train),
        "n_test_samples": len(X_test),
        "evaluation": _evaluate_components(
            X_test, y_test, random_forest_result, xgboost_result
        ),
        "training_info": {
            "source": "synthetic + real data",
            "n_synthetic_rows": len(X_s),
            "n_real_rows": n_real,
            "n_real_labeled": n_labeled,
            "n_real_weak": n_real - n_labeled,
        },
    }

    report.update({
        "n_real_rows": n_real,
        "n_real_labeled": n_labeled,
        "n_real_weak": n_real - n_labeled,
        "labeled_weight_used": round(labeled_weight_used, 2),
    })

    if not previous_bundle or not previous_bundle.get("available"):
        report["accepted"] = True
        report["reason"] = "First trained model."
        return bundle, report

    y_true = y_test.to_numpy(dtype=float)

    new_pred = _hybrid_from_models(
        random_forest_result, xgboost_result, X_test
    )

    old_pred = _hybrid_from_models(
        previous_bundle.get("random_forest"),
        previous_bundle.get("xgboost"),
        X_test
    )

    def mae(mask, pred):
        return float(mean_absolute_error(y_true[mask], pred[mask]))

    def r2(mask, pred):
        return float(r2_score(y_true[mask], pred[mask]))

    real_test = src_test != "synthetic"

    labeled_test = src_test == "real_labeled"

    labelled_gate = bool(labeled_test.sum() >= min_gate_rows)

    if labelled_gate:
        gate_mask, gate_name = labeled_test, "held-out real labelled rows"
    elif real_test.sum() >= min_gate_rows:
        gate_mask, gate_name = real_test, "held-out real rows"
    else:
        gate_mask = np.ones(len(src_test), dtype=bool)
        gate_name = "all held-out rows"

    synth_mask = src_test == "synthetic"

    new_gate, old_gate = mae(gate_mask, new_pred), mae(gate_mask, old_pred)

    new_syn, old_syn = mae(synth_mask, new_pred), mae(synth_mask, old_pred)

    report.update({
        "gate_set": gate_name,
        "n_gate_rows": int(gate_mask.sum()),
        "old_gate_mae": round(old_gate, 3),
        "new_gate_mae": round(new_gate, 3),
        "old_synthetic_mae": round(old_syn, 3),
        "new_synthetic_mae": round(new_syn, 3),
    })

    synthetic_ok = new_syn <= old_syn * (1.0 + max_synthetic_degradation)

    if labelled_gate:

        new_r2, old_r2 = r2(gate_mask, new_pred), r2(gate_mask, old_pred)

        report["new_gate_r2"] = round(new_r2, 3)

        report["old_gate_r2"] = round(old_r2, 3)

        improved = new_gate <= old_gate + 1e-9

        predictable = new_r2 >= min_label_r2

        report["accepted"] = bool(improved and predictable)

        if report["accepted"]:
            report["reason"] = (
                f"Accepted: on {gate_name} error (MAE) fell "
                f"{old_gate:.2f} -> {new_gate:.2f} and R2 is "
                f"{new_r2:.2f}."
            )
        elif not predictable:
            report["reason"] = (
                f"Rejected: the real labels are not predictable from "
                f"the sensor readings (R2 {new_r2:.2f} on {gate_name}, "
                f"need {min_label_r2}). Check the label column, or "
                f"remove the bad dataset (External Dataset tab). "
                f"Old model kept."
            )
        else:
            report["reason"] = (
                f"Rejected: new model is not better on {gate_name} "
                f"(MAE {old_gate:.2f} -> {new_gate:.2f}). "
                f"Old model kept."
            )

    else:

        within_tolerance = new_gate <= old_gate * (1.0 + weak_tolerance) + 0.25

        report["accepted"] = bool(within_tolerance and synthetic_ok)

        if report["accepted"]:
            report["reason"] = (
                f"Accepted (no/few real outcome labels, so this only "
                f"adapts to your data's value ranges): MAE on "
                f"{gate_name} {old_gate:.2f} -> {new_gate:.2f}."
            )
        elif not within_tolerance:
            report["reason"] = (
                f"Rejected: new model is worse on {gate_name} "
                f"(MAE {old_gate:.2f} -> {new_gate:.2f}). Old model kept."
            )
        else:
            report["reason"] = (
                f"Rejected: new model is more than "
                f"{int(max_synthetic_degradation * 100)}% worse on the "
                f"synthetic base rows (MAE {old_syn:.2f} -> "
                f"{new_syn:.2f}). Old model kept."
            )

    return bundle, report


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

MODEL_CACHE_VERSION = 2

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
        "xgb_params": {k: str(v) for k, v in XGBOOST_PARAMS.items()},
        "features": list(FEATURE_COLUMNS),
        "physics": [
            COEF_WATER_LEVEL, COEF_RAINFALL, COEF_RIVER_FLOW,
            COEF_SOIL_MOISTURE, COEF_HUMIDITY, S_REF,
            SIGMOID_STEEPNESS_K, WATER_LEVEL_RESPONSE,
        ],
        "label_version": SYNTHETIC_LABEL_VERSION,
        "hybrid_weights": [HYBRID_ML_WEIGHT, HYBRID_PHYSICS_WEIGHT],
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
    n_samples=DEFAULT_TRAINING_SAMPLES, random_state=42, cache_path=DEFAULT_MODEL_CACHE_PATH
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
# 2.3.4.3 HYBRID COMBINATION
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
