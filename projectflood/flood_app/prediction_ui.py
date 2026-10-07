"""Shared prediction visuals: hybrid prediction details, the flood probability
gauge and the model information panel."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import hybrid_model

from flood_app.alert_ui import _html_no_indent
from flood_app.config import RISK_CIRCLE, RISK_ZONE_COLOR
from flood_app.prediction import classify_risk, get_trained_hybrid_model


# ============================================================
# HYBRID PREDICTION DISPLAY (shared across dashboards)
# ============================================================

def render_hybrid_prediction_details(selected_row):
    """
    Shows the system's Predicted Water Level for one reading.

    This intentionally does NOT expose which internal model
    component(s) produced the prediction, physics/ML sub-scores,
    model names, or any other technical breakdown — the
    prediction engine itself (see hybrid_model.py) is unchanged
    and fully implemented, but normal dashboard users are only
    shown the system's plain-language outputs (Flood Probability,
    Prediction, Predicted Water Level, Flood Risk Status), not
    how they were produced internally.

    Degrades gracefully and silently for any row that predates
    this upgrade (missing the new columns) — never errors.
    """

    if "predicted_water_level" not in selected_row.index:
        return

    if pd.isna(selected_row.get("predicted_water_level")):
        return

    st.metric(
        "🌊 Predicted Water Level",
        f"{selected_row['predicted_water_level']} m"
    )


def render_flood_probability_gauge(
    probability,
    risk_level=None,
    label="Flood Probability"
):
    """
    Renders one fixed 0-100% flood-probability gauge plus a
    large, color-matched risk-level line underneath it.

    `probability` must be the REAL hybrid-model
    flood_probability value already used everywhere else in the
    app (the map, the risk badge, the automatic-alert check) —
    this function only visualizes that number, it never
    computes, estimates, or overrides it. `risk_level` is
    optional; if omitted it's derived from `probability` via
    classify_risk() itself, so the label and the gauge's colored
    zones are always self-consistent.
    """

    if probability is None or (
        isinstance(probability, float) and pd.isna(probability)
    ):
        return

    probability = float(probability)

    if risk_level is None:
        risk_level = classify_risk(probability)

    bar_color = RISK_ZONE_COLOR.get(risk_level, "#34495e")

    gauge_figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=probability,
            number={
                "suffix": "%",
                "font": {"size": 46}
            },
            title={
                "text": label,
                "font": {"size": 16}
            },
            gauge={
                "axis": {
                    "range": [0, 100],
                    "tickmode": "array",
                    "tickvals": [0, 50, 70, 90, 100],
                    "tickwidth": 1
                },
                "bar": {
                    "color": bar_color,
                    "thickness": 0.30
                },
                "bgcolor": "#262730",
                "borderwidth": 1,
                "bordercolor": "#4a4a55",
                # Steps double as a fixed color-coded legend for
                # the 4 risk zones — always the same 4 boundaries
                # as classify_risk(), regardless of the current
                # value. Darker/muted tints (instead of near-white
                # pastels) so they still read as a light-to-dark
                # risk gradient on the dark gauge card, without
                # glaring against the surrounding dark UI.
                "steps": [
                    {"range": [0, 50], "color": "#1e3d2f"},
                    {"range": [50, 70], "color": "#4a3f14"},
                    {"range": [70, 90], "color": "#4d3419"},
                    {"range": [90, 100], "color": "#4d1f1c"}
                ],
                # A bold red line right at the Severe cutoff
                # (90%) makes it visually unmistakable whenever
                # the bar reaches or crosses it.
                "threshold": {
                    "line": {"color": "#c0392b", "width": 5},
                    "thickness": 0.92,
                    "value": 90
                }
            }
        )
    )

    gauge_figure.update_layout(
        height=300,
        margin={"l": 25, "r": 25, "t": 55, "b": 15},
        # Explicitly opaque, regardless of whether the Streamlit
        # app itself is in light or dark mode. Originally this used
        # a hardcoded white card (#ffffff bg + #1a1a1a text) so it
        # would never go invisible on a dark page — but that made
        # it a glaring white box in night mode. Switched to a dark
        # "card" (#262730, matching Streamlit's own dark-theme
        # secondary background) with light text instead, so it
        # still reads correctly and stays self-consistent
        # regardless of theme, but no longer looks like a bright
        # white hole punched into a dark page. This is a fixed
        # dark card (not a theme-adaptive one) since Streamlit's
        # active theme isn't reliably queryable across versions/
        # activation methods (OS-level dark mode, config.toml, or
        # the in-app toggle can all enable it) — if the app is
        # normally used in light mode too, consider detecting
        # st.get_option("theme.base") and swapping palettes.
        paper_bgcolor="#262730",
        plot_bgcolor="#262730",
        font={"color": "#fafafa"}
    )

    st.plotly_chart(
        gauge_figure,
        width="stretch"
    )

    risk_circle = RISK_CIRCLE.get(risk_level, "")

    st.markdown(
        f"<div style='text-align:center; font-size:1.4rem; "
        f"font-weight:700; margin-top:-8px; color:#fafafa; "
        f"background-color:#262730; border-radius:0 0 8px 8px; "
        f"padding:6px 0 10px 0;'>"
        f"{risk_circle} {risk_level} Risk — {probability:.1f}% "
        f"flood probability</div>",
        unsafe_allow_html=True
    )


def render_model_information_panel():
    """
    A dedicated, compact model-transparency panel — real training
    metrics (not fabricated), computed once when the model was
    trained. Intended for anyone (including a researcher/
    reviewer) who wants to check what's actually running under
    the hood, beyond the per-prediction explanation in
    render_hybrid_prediction_details().
    """

    model_bundle = get_trained_hybrid_model()

    st.markdown(
        "### Hybrid Physics-Inspired + Ensemble Machine Learning "
        "Flood Prediction Framework"
    )

    physics_text = _html_no_indent("""
    **Physics-Inspired Component**

    A flood risk score S is computed as a weighted linear
    combination of five sensor variables:

    S = 18·W + 0.28·R + 2.5·F + 0.12·SM + 0.08·H

    (water level, rainfall, river flow, soil moisture, humidity).
    S is mapped to a bounded probability P_physics via a logistic
    (sigmoid) transform centered on a calibration midpoint. See
    `hybrid_model.py` (`compute_physics_score`,
    `physics_probability_from_score`) for the exact constants.
    """)

    st.markdown(physics_text)

    if model_bundle.get("available"):

        random_forest = model_bundle.get("random_forest") or {}
        xgboost_result = model_bundle.get("xgboost") or {}

        ml_intro_text = _html_no_indent(f"""
        **Machine Learning Components**

        Two ensemble regressors, each genuinely trained via
        `.fit()` on a physics-informed synthetic dataset (there's
        no bundled real historical flood dataset for Bangladesh in
        this app — see the honesty note at the top of
        `hybrid_model.py`). Their outputs are averaged into one ML
        estimate.

        - Training samples: **{model_bundle.get('n_training_samples')}**
        - Held-out test samples: **{model_bundle.get('n_test_samples')}**
        """)

        st.markdown(ml_intro_text)

        rf_col, xgb_col = st.columns(2)

        with rf_col:

            if random_forest.get("available"):

                st.markdown(
                    f"**{random_forest['model_name']}**\n\n"
                    f"Test R²: **{random_forest['r2_score']}**\n\n"
                    f"Test MAE: **{random_forest['mae']}**"
                )

            else:

                st.warning(
                    random_forest.get(
                        "error", "Random Forest unavailable."
                    )
                )

        with xgb_col:

            if xgboost_result.get("available"):

                st.markdown(
                    f"**{xgboost_result['model_name']}**\n\n"
                    f"Test R²: **{xgboost_result['r2_score']}**\n\n"
                    f"Test MAE: **{xgboost_result['mae']}**"
                )

            else:

                st.warning(
                    xgboost_result.get(
                        "error", "XGBoost unavailable."
                    )
                )

        st.caption(
            "These are the actual metrics from whichever model(s) "
            "are running right now, computed on held-out data they "
            "were not trained on — not hard-coded placeholder "
            "numbers. If only one model is available, the ML "
            "estimate is that one model's prediction alone."
        )

        if random_forest.get("available"):

            with st.expander(
                "📊 Random Forest feature importances"
            ):

                importances_df = pd.DataFrame(
                    sorted(
                        random_forest["feature_importances"].items(),
                        key=lambda item: -item[1]
                    ),
                    columns=["Feature", "Importance"]
                )

                st.dataframe(
                    importances_df,
                    width="stretch",
                    hide_index=True
                )

    else:

        st.error(
            model_bundle.get(
                "error",
                "The ML component is unavailable."
            )
        )

    hybrid_text = _html_no_indent(f"""
    **Hybrid Combination**

    P_ml = 0.5 x Random Forest prediction + 0.5 x XGBoost
    prediction (whichever are available).

    Final probability = **{hybrid_model.HYBRID_ML_WEIGHT * 100:.0f}%
    x P_ml + {hybrid_model.HYBRID_PHYSICS_WEIGHT * 100:.0f}%
    x P_physics** — weighting the data-driven estimate more
    heavily while retaining the physics-based estimate as a
    stabilizing prior. If no ML model is available at all, the
    result is P_physics alone, so the pipeline stays operational
    either way.
    """)

    st.markdown(hybrid_text)
