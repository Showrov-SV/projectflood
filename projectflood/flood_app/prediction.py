"""Flood probability calculation, risk classification and the hybrid
physics + machine-learning prediction (single and batched)."""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import hybrid_model


# ============================================================
# FLOOD PREDICTION
# ============================================================

def calculate_flood_probability(
    water_level,
    rainfall,
    river_flow,
    soil_moisture,
    humidity
):
    """
    SUPERSEDED — kept only for reference/comparison (this
    function's own formula is now effectively duplicated, with
    identical coefficients, as hybrid_model.compute_physics_score
    — the physics component of the live pipeline below). The live
    prediction path now uses hybrid_flood_prediction() below,
    which runs the physics-inspired score/sigmoid model
    (hybrid_model.run_physics_model) whose outputs feed TWO
    trained ensemble regressors — Random Forest and XGBoost
    (hybrid_model.train_hybrid_ml_model) — averaged together, then
    blended with the physics estimate. This function itself is no
    longer called by generate_sensor_data() or
    process_uploaded_dataframe() — see hybrid_model.py for the
    actual hybrid framework.
    """

    score = (

        water_level * 18

        + rainfall * 0.28

        + river_flow * 2.5

        + soil_moisture * 0.12

        + humidity * 0.08

    )

    probability = score / 2.2

    probability += np.random.uniform(
        -5,
        5
    )

    probability = np.clip(
        probability,
        0,
        99.9
    )

    return round(
        probability,
        2
    )


def classify_risk(probability):
    """
    Single source of truth for risk classification — every
    other place in the app (map markers, risk badges, automatic
    alerts, the gauge) calls THIS function rather than
    re-implementing its own thresholds, so all of them always
    agree with each other.

    Thresholds (on the real hybrid_probability, 0-100):
        Low      : < 50
        Moderate : 50  - 69.99
        High     : 70  - 89.99
        Severe   : >= 90
        Unknown  : probability missing / NaN
    """

    # A missing / non-numeric probability must never be reported as
    # the worst risk level (NaN fails every comparison below and
    # would otherwise fall through to "Severe" and trigger alerts).
    try:

        if probability is None or probability != probability:

            return "Unknown"

    except Exception:

        return "Unknown"

    if probability < 50:

        return "Low"

    elif probability < 70:

        return "Moderate"

    elif probability < 90:

        return "High"

    else:

        return "Severe"


# ============================================================
# HYBRID PHYSICS + MACHINE LEARNING PREDICTION (live path)
# ============================================================
# The actual physics model, ML training, and hybrid blending
# logic live in hybrid_model.py (kept Streamlit-independent so
# it can be reviewed/tested standalone). This section just:
#   1. Trains the ML component ONCE per running app process
#      (via st.cache_resource — training takes a few seconds;
#      re-training on every Streamlit rerun would be wasteful
#      and pointless, since the synthetic training data and
#      model don't change between reruns).
#   2. Wraps hybrid_model.hybrid_predict() with
#      classify_risk() so the rest of this app — the map,
#      risk badges, emergency alerts, cooldown, everything —
#      keeps working against the exact same "flood_probability"
#      / "risk_level" fields it always has, unmodified.
# ============================================================

@st.cache_resource(show_spinner=False)
def get_trained_hybrid_model():
    """
    Trains hybrid_model's RandomForestRegressor once per server
    process and caches the resulting bundle (trained model +
    real held-out R²/MAE + feature importances). Cached by
    Streamlit, so every rerun reuses the SAME trained model
    instance rather than retraining from scratch.
    """

    return hybrid_model.load_or_train_hybrid_ml_model()


def hybrid_flood_prediction(
    water_level,
    rainfall,
    river_flow,
    temperature,
    humidity,
    soil_moisture,
    wind_speed
):
    """
    The live prediction entry point used by both
    generate_sensor_data() (simulation) and
    process_uploaded_dataframe() (CSV/XLSX) — genuinely runs the
    physics model AND the trained ML model (see hybrid_model.py),
    then blends them. Returns a dict with everything the
    dashboards need: the existing "flood_probability" / risk
    fields (for full backward compatibility with the map, alerts,
    badges, cooldown, etc.), plus the new hybrid-specific fields
    for the "Prediction" UI and model-transparency section.
    """

    model_bundle = get_trained_hybrid_model()

    result = hybrid_model.hybrid_predict(
        water_level=water_level,
        rainfall=rainfall,
        river_flow=river_flow,
        temperature=temperature,
        humidity=humidity,
        soil_moisture=soil_moisture,
        wind_speed=wind_speed,
        model_bundle=model_bundle
    )

    flood_probability = round(result["hybrid_probability"], 2)

    risk_level = classify_risk(flood_probability)

    return {
        "flood_probability": flood_probability,
        "risk_level": risk_level,
        "predicted_water_level": result["predicted_water_level"],
        "physics_probability": result["physics_probability"],
        "ml_probability": result["ml_probability"],
        "ml_used": result["ml_used"],
        "model_name": result["model_name"],
        "physics_features": result["physics"],
    }


def hybrid_flood_prediction_batch(readings):
    """
    Vectorised version of hybrid_flood_prediction(): predicts a
    whole DataFrame of readings (must contain the seven raw sensor
    columns) with ONE physics pass and ONE predict() call per ML
    model, instead of one full prediction per row. Returns a
    DataFrame (same row order) with the columns the dashboards use:
    flood_probability, risk_level, predicted_water_level,
    physics_probability, ml_probability, ml_used, model_name.
    """

    out = hybrid_model.hybrid_predict_batch(
        readings,
        get_trained_hybrid_model()
    )

    flood_probability = out["hybrid_probability"].round(2)

    return pd.DataFrame({
        "flood_probability": flood_probability,
        "risk_level": [classify_risk(p) for p in flood_probability],
        "predicted_water_level": out["predicted_water_level"],
        "physics_probability": out["physics_probability"],
        "ml_probability": out["ml_probability"],
        "ml_used": out["ml_used"],
        "model_name": out["model_name"],
    })


# ============================================================
# SIMULATED SENSOR DATA
# ============================================================

def generate_sensor_data(sensor):

    water_level = np.random.uniform(
        1.0,
        4.8
    )

    rainfall = np.random.uniform(
        5,
        150
    )

    river_flow = np.random.uniform(
        1,
        15
    )

    temperature = np.random.uniform(
        24,
        34
    )

    humidity = np.random.uniform(
        55,
        98
    )

    soil_moisture = np.random.uniform(
        30,
        98
    )

    wind_speed = np.random.uniform(
        1,
        20
    )

    hybrid_result = hybrid_flood_prediction(
        water_level=water_level,
        rainfall=rainfall,
        river_flow=river_flow,
        temperature=temperature,
        humidity=humidity,
        soil_moisture=soil_moisture,
        wind_speed=wind_speed
    )

    return {

        "sensor_id":
            sensor["sensor_id"],

        "location":
            sensor["location"],

        "timestamp":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "water_level":
            round(
                water_level,
                2
            ),

        "rainfall":
            round(
                rainfall,
                2
            ),

        "river_flow":
            round(
                river_flow,
                2
            ),

        "temperature":
            round(
                temperature,
                2
            ),

        "humidity":
            round(
                humidity,
                2
            ),

        "soil_moisture":
            round(
                soil_moisture,
                2
            ),

        "wind_speed":
            round(
                wind_speed,
                2
            ),

        "flood_probability":
            hybrid_result["flood_probability"],

        "risk_level":
            hybrid_result["risk_level"],

        "predicted_water_level":
            hybrid_result["predicted_water_level"],

        "physics_probability":
            hybrid_result["physics_probability"],

        "ml_probability":
            hybrid_result["ml_probability"],

        "ml_used":
            hybrid_result["ml_used"],

        "model_name":
            hybrid_result["model_name"],

        "data_source":
            "Simulation"

    }
