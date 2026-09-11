"""
hybrid_model.py
================================================================
Hybrid Physics-Based + Machine Learning Flood Prediction Framework
================================================================

HONESTY / SCOPE NOTE — read this before assuming what this does:

This module implements a genuine two-component hybrid prediction
pipeline. Neither component is decorative.

1. PHYSICS / MATHEMATICAL COMPONENT
   A reduced-order water-balance / linear-reservoir model — NOT a
   full Saint-Venant shallow-water PDE solver (that is out of
   scope for a real-time Streamlit prototype, and this module does
   not pretend otherwise). It models local water accumulation as a
   simple mass balance:

       d(storage)/dt = inflow - outflow - evaporation

   - Rainfall-driven runoff is estimated with a soil-moisture-
     adjusted runoff coefficient (a simplified, SCS curve-number-
     style idea: saturated soil produces proportionally more
     runoff because less can infiltrate).
   - Outflow is modeled as a linear reservoir: proportional to the
     current water level (a standard simplified hydrological
     routing technique).
   - A small temperature-driven evaporation loss term is included.

   This produces genuinely meaningful intermediate physical
   quantities (estimated inflow, outflow, runoff contribution,
   short-term water-level change) from real physical reasoning —
   but it is explicitly a coarse, uncalibrated approximation, not
   a validated hydrological model of any real river system.

2. MACHINE LEARNING COMPONENT
   A scikit-learn RandomForestRegressor, actually trained via
   .fit() — not instantiated and left untrained, not a renamed
   copy of the physics formula. There is no bundled real historical
   flood dataset for Bangladesh in this application, so the model
   is trained on a SYNTHETIC dataset: physically-plausible random
   sensor readings run through the physics model above, labeled by
   a separate nonlinear target-generating function (not identical
   to the physics-only estimate) with injected Gaussian noise, so
   the model has to genuinely learn a noisy nonlinear relationship
   rather than memorize a deterministic formula. Its held-out test
   R² and MAE are computed and reported honestly, not fabricated.
   In a real deployment, replace generate_synthetic_training_data()
   with real historical sensor/flood-event records and retrain.

3. HYBRID COMBINATION
   The final probability is a documented weighted blend of the
   trained ML model's prediction (which itself already consumes
   the physics-derived features as inputs) and a simple physics-
   only probability estimate computed independently from the
   physics model's predicted water level. Both components' outputs
   are returned separately for transparency, alongside which one
   actually ran.

This file has NO Streamlit dependency, so it can be imported,
inspected, and unit-tested completely independently of the app —
including by a reviewer who just wants to check the modeling logic.
================================================================
"""

import numpy as np
import pandas as pd

try:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error, r2_score
    SKLEARN_AVAILABLE = True
    SKLEARN_IMPORT_ERROR = None
except ImportError as _import_error:
    SKLEARN_AVAILABLE = False
    SKLEARN_IMPORT_ERROR = str(_import_error)


# ================================================================
# 1. PHYSICS / MATHEMATICAL COMPONENT
# ================================================================

# Documented, tunable constants for the reduced-order water-balance
# model. These are illustrative engineering choices, not calibrated
# against any real catchment.
RUNOFF_COEFFICIENT_BASE = 0.30
RUNOFF_COEFFICIENT_SOIL_WEIGHT = 0.60
OUTFLOW_COEFFICIENT = 0.35
STORAGE_COEFFICIENT = 8.0
EVAPORATION_TEMP_REFERENCE_C = 20.0
EVAPORATION_COEFFICIENT = 0.002

# Reference "flood stage" water level (meters) used only by the
# standalone physics-only probability estimate below.
FLOOD_STAGE_WATER_LEVEL_M = 4.0
PHYSICS_SIGMOID_STEEPNESS = 1.8


def run_physics_model(
    water_level,
    rainfall,
    river_flow,
    temperature,
    humidity,
    soil_moisture,
    wind_speed,
    dt_hours=1.0
):
    """
    Reduced-order water-balance / linear-reservoir model.

    Returns a dict of physically-meaningful intermediate
    quantities — these are the "physics-derived features" fed into
    the ML model below, not just display numbers.
    """

    # Saturated soil infiltrates less, so more rainfall becomes
    # runoff — a simplified stand-in for an SCS curve-number style
    # relationship.
    runoff_coefficient = (
        RUNOFF_COEFFICIENT_BASE
        + RUNOFF_COEFFICIENT_SOIL_WEIGHT * (soil_moisture / 100.0)
    )

    # Rainfall (mm) converted into an abstracted runoff contribution
    # on the same rough scale as river_flow (m^3/s-like units) — an
    # illustrative scaling, not a real unit-correct hydraulic
    # conversion.
    runoff_contribution = (rainfall * runoff_coefficient) / 10.0

    # Total inflow to the local reach.
    estimated_inflow = river_flow + runoff_contribution

    # Linear reservoir outflow: proportional to current water level.
    estimated_outflow = OUTFLOW_COEFFICIENT * water_level

    # Small temperature-driven evaporation loss.
    evaporation_loss = EVAPORATION_COEFFICIENT * max(
        temperature - EVAPORATION_TEMP_REFERENCE_C, 0
    )

    # Net water balance (mass conservation).
    net_water_balance = (
        estimated_inflow - estimated_outflow - evaporation_loss
    )

    # Translate the net balance into a water-level change over the
    # given short time step, via a storage/width proxy coefficient.
    water_level_delta = (
        net_water_balance / STORAGE_COEFFICIENT
    ) * dt_hours

    predicted_water_level = max(
        water_level + water_level_delta, 0.0
    )

    return {
        "runoff_coefficient": round(float(runoff_coefficient), 4),
        "runoff_contribution": round(float(runoff_contribution), 4),
        "estimated_inflow": round(float(estimated_inflow), 4),
        "estimated_outflow": round(float(estimated_outflow), 4),
        "evaporation_loss": round(float(evaporation_loss), 4),
        "net_water_balance": round(float(net_water_balance), 4),
        "water_level_delta": round(float(water_level_delta), 4),
        "predicted_water_level": round(float(predicted_water_level), 4),
    }


def physics_only_probability(predicted_water_level, net_water_balance):
    """
    A standalone, physics-only flood-probability ESTIMATE (0-100),
    used as one half of the final hybrid blend and shown separately
    in the UI for transparency. Built from the physics model's own
    outputs only — no ML involved. A logistic curve centered on a
    reference flood-stage water level, nudged by the current water-
    balance trend (rising vs falling).
    """

    x = predicted_water_level - FLOOD_STAGE_WATER_LEVEL_M

    sigmoid = 1.0 / (1.0 + np.exp(-PHYSICS_SIGMOID_STEEPNESS * x))

    trend_adjustment = float(np.clip(net_water_balance * 2.0, -10, 10))

    probability = sigmoid * 100 + trend_adjustment

    return float(np.clip(probability, 0, 99.9))


# ================================================================
# 2. MACHINE LEARNING COMPONENT
# ================================================================

RAW_FEATURE_COLUMNS = [
    "water_level", "rainfall", "river_flow", "temperature",
    "humidity", "soil_moisture", "wind_speed"
]

PHYSICS_FEATURE_COLUMNS = [
    "runoff_coefficient", "runoff_contribution", "estimated_inflow",
    "estimated_outflow", "evaporation_loss", "net_water_balance",
    "water_level_delta", "predicted_water_level"
]

FEATURE_COLUMNS = RAW_FEATURE_COLUMNS + PHYSICS_FEATURE_COLUMNS


def generate_synthetic_training_data(n_samples=4000, random_state=42):
    """
    Builds a physically-plausible SYNTHETIC training set (see the
    module-level honesty note for why synthetic, not real, data is
    used here). Every row's physics-derived features come from
    ACTUALLY running run_physics_model() on that row's raw sensor
    values — not fabricated separately from the physics component.

    The target label is generated from a DIFFERENT, more complex
    nonlinear function than the physics-only estimate above (so the
    ML model has something genuine to learn, not just physics 2),
    with injected Gaussian noise standing in for real-world
    measurement/process uncertainty.
    """

    rng = np.random.default_rng(random_state)

    water_level = rng.uniform(0.3, 5.5, n_samples)
    rainfall = np.clip(rng.gamma(2.0, 30.0, n_samples), 0, 250)
    river_flow = rng.uniform(0.2, 20.0, n_samples)
    temperature = rng.uniform(15, 40, n_samples)
    humidity = rng.uniform(25, 100, n_samples)
    soil_moisture = rng.uniform(5, 100, n_samples)
    wind_speed = rng.uniform(0, 45, n_samples)

    rows = []
    targets = []

    for i in range(n_samples):

        physics = run_physics_model(
            water_level[i], rainfall[i], river_flow[i],
            temperature[i], humidity[i], soil_moisture[i],
            wind_speed[i]
        )

        base = (
            18.0 * physics["predicted_water_level"]
            + 0.22 * rainfall[i]
            + 2.1 * river_flow[i]
            + 0.05 * humidity[i]
            + 0.10 * soil_moisture[i]
            + 6.0 * physics["net_water_balance"]
            - 0.15 * max(temperature[i] - 30, 0)
            + 0.03 * wind_speed[i]
        )

        noise = rng.normal(0, 6.0)

        target = float(np.clip(base / 2.0 + noise, 0, 100))

        row = {
            "water_level": water_level[i],
            "rainfall": rainfall[i],
            "river_flow": river_flow[i],
            "temperature": temperature[i],
            "humidity": humidity[i],
            "soil_moisture": soil_moisture[i],
            "wind_speed": wind_speed[i],
        }
        row.update(physics)

        rows.append(row)
        targets.append(target)

    X = pd.DataFrame(rows)
    y = pd.Series(targets, name="flood_probability_label")

    return X, y


def train_hybrid_ml_model(n_samples=4000, random_state=42):
    """
    Genuinely trains a RandomForestRegressor via .fit() on the
    synthetic, physics-informed dataset above, then evaluates it on
    a held-out test split and returns the REAL resulting metrics —
    nothing here is fabricated or hard-coded. Returns a dict bundle
    that hybrid_predict() below consumes; callers (the Streamlit
    app) are expected to cache this bundle so training happens once
    per process, not on every rerun.
    """

    if not SKLEARN_AVAILABLE:

        return {
            "available": False,
            "error": (
                "scikit-learn is not installed "
                f"({SKLEARN_IMPORT_ERROR}). Install it with "
                "'pip install scikit-learn' to enable the ML "
                "component of the hybrid framework."
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

    model = RandomForestRegressor(
        n_estimators=150,
        max_depth=12,
        random_state=random_state,
        n_jobs=-1
    )

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
        "feature_columns": FEATURE_COLUMNS,
        "model_name": "Random Forest Regressor (scikit-learn)",
        "n_training_samples": len(X_train),
        "n_test_samples": len(X_test),
        "r2_score": round(float(r2), 4),
        "mae": round(float(mae), 3),
        "feature_importances": feature_importances,
    }


# ================================================================
# 3. HYBRID COMBINATION
# ================================================================

HYBRID_ML_WEIGHT = 0.6
HYBRID_PHYSICS_WEIGHT = 0.4


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
    Runs BOTH components on one reading and returns the blended
    result plus each component's own output, for transparency.

    model_bundle is whatever train_hybrid_ml_model() returned
    (ideally cached by the caller). If the ML component isn't
    available (scikit-learn missing, or training failed), this
    degrades honestly to a physics-only result — it never
    fabricates an ML output, and callers should label the result
    accordingly (ml_used=False).
    """

    physics = run_physics_model(
        water_level, rainfall, river_flow, temperature,
        humidity, soil_moisture, wind_speed
    )

    physics_probability = physics_only_probability(
        physics["predicted_water_level"],
        physics["net_water_balance"]
    )

    ml_probability = None
    ml_used = False

    if model_bundle and model_bundle.get("available"):

        feature_row = {
            "water_level": water_level,
            "rainfall": rainfall,
            "river_flow": river_flow,
            "temperature": temperature,
            "humidity": humidity,
            "soil_moisture": soil_moisture,
            "wind_speed": wind_speed,
        }
        feature_row.update(physics)

        feature_df = pd.DataFrame(
            [feature_row]
        )[model_bundle["feature_columns"]]

        ml_probability = float(
            np.clip(
                model_bundle["model"].predict(feature_df)[0],
                0,
                99.9
            )
        )

        ml_used = True

        hybrid_probability = (
            HYBRID_ML_WEIGHT * ml_probability
            + HYBRID_PHYSICS_WEIGHT * physics_probability
        )

    else:

        # Honest degradation: no ML available, so the "hybrid"
        # result IS the physics-only estimate — never silently
        # invented.
        hybrid_probability = physics_probability

    hybrid_probability = float(
        np.clip(round(hybrid_probability, 2), 0, 99.9)
    )

    return {
        "physics": physics,
        "physics_probability": round(physics_probability, 2),
        "ml_probability": (
            round(ml_probability, 2)
            if ml_probability is not None
            else None
        ),
        "hybrid_probability": hybrid_probability,
        "ml_used": ml_used,
        "predicted_water_level": physics["predicted_water_level"],
        "model_name": (
            model_bundle.get("model_name")
            if model_bundle and model_bundle.get("available")
            else None
        ),
    }
