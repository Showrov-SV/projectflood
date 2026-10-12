"""Risk colours/badges and the Plotly flood map."""

import math
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from flood_app.config import NO_DATA_CIRCLE, RISK_CIRCLE, RISK_DISPLAY_LABELS
from flood_app.sensors import get_location_coordinates


def location_risk_circle(readings, location):
    """
    Returns the small risk-circle emoji for ONE location, given
    a readings DataFrame (as produced by
    generate_all_sensor_data()). Returns NO_DATA_CIRCLE if that
    location has no current reading — this is what lets a
    selector show "⚪ Sylhet" instead of silently looking exactly
    like a real risk level.
    """

    if readings is None or readings.empty or not location:
        return NO_DATA_CIRCLE

    match = readings[
        readings["location"]
        .astype(str)
        .str.strip()
        .str.lower()
        == str(location).strip().lower()
    ]

    if match.empty:
        return NO_DATA_CIRCLE

    return RISK_CIRCLE.get(
        match.iloc[0]["risk_level"],
        NO_DATA_CIRCLE
    )


def worst_risk_circle(readings, location_list):
    """
    Returns the single worst risk-circle emoji across every
    location in location_list — used to give a whole division
    (or any other group of areas) one at-a-glance status icon.
    NO_DATA_CIRCLE only if NONE of the locations have a reading
    yet.
    """

    if readings is None or readings.empty or not location_list:
        return NO_DATA_CIRCLE

    severity_order = ["Severe", "High", "Moderate", "Low"]

    group = readings[
        readings["location"].isin(location_list)
    ]

    if group.empty:
        return NO_DATA_CIRCLE

    present_levels = set(group["risk_level"])

    for level in severity_order:

        if level in present_levels:
            return RISK_CIRCLE.get(level, NO_DATA_CIRCLE)

    return NO_DATA_CIRCLE


def location_badge_row(readings, location_list):
    """
    Builds one plain-text line like
    "🟢 Dhaka  •  🔴 Jamalpur  •  ⚪ Sylhet" for a quick-glance
    risk overview across several locations. Uses only plain
    characters (no HTML entities like &nbsp;, which would just
    show up as literal text without unsafe_allow_html) so it
    renders correctly with a plain st.markdown() call — no HTML
    parsing involved at all, so none of the indentation pitfalls
    fixed elsewhere in this file apply here.
    """

    badges = [
        f"{location_risk_circle(readings, location)} {location}"
        for location in location_list
    ]

    return "  •  ".join(badges)


def _fit_view(latitudes, longitudes, width_px=900, height_px=600):
    """
    Returns ({"lat":..,"lon":..}, zoom) so that a map of roughly
    width_px x height_px shows every given point with ~30 %
    padding. A single point (or points on top of each other)
    gets a close-up zoom.
    """

    lat_min, lat_max = min(latitudes), max(latitudes)
    lon_min, lon_max = min(longitudes), max(longitudes)

    center = {
        "lat": (lat_min + lat_max) / 2,
        "lon": (lon_min + lon_max) / 2
    }

    lon_span = lon_max - lon_min

    def mercator_y(latitude):
        return math.log(
            math.tan(math.pi / 4 + math.radians(latitude) / 2)
        )

    lat_fraction = (
        mercator_y(lat_max) - mercator_y(lat_min)
    ) / (2 * math.pi)

    if lon_span < 1e-4 and lat_fraction < 1e-6:
        return center, 11

    padding = 1.3

    zoom_candidates = []

    if lon_span > 1e-4:
        zoom_candidates.append(
            math.log2(360 * width_px / (256 * lon_span * padding))
        )

    if lat_fraction > 1e-6:
        zoom_candidates.append(
            math.log2(height_px / (256 * lat_fraction * padding))
        )

    return center, max(3, min(11, min(zoom_candidates)))


def create_flood_map(
    readings,
    focus_location=None,
    auto_fit=False
):

    """
    Builds the Live Flood Location Map from the CURRENT reading
    per location (one row per location, whether simulated or
    from an external dataset). Coordinates come from
    LOCATION_COORDINATES / get_location_coordinates() rather
    than a merge against the sensors table, so uploaded-dataset
    locations that aren't registered sensors (e.g. Jamalpur,
    Sylhet) still appear correctly on the map.

    focus_location is optional. When given (and it has known
    coordinates), the map centers on and zooms into that one
    location instead of auto-fitting every plotted location —
    used so the Admin dashboard's map "jumps to" whichever
    location is chosen in Location Selection.
    auto_fit (default False = unchanged behaviour) centers and
    zooms the map so that ALL plotted markers are visible — used
    by the System Handler map, where the set of locations shown
    ranges from the whole country down to a single division. All markers for
    every other location are still drawn and still hoverable;
    only the initial camera position/zoom changes. Callers that
    don't pass focus_location (organization/public dashboards)
    get the exact same all-locations view as before.
    """

    empty_layout = {
        "height": 600,
        "margin": {
            "r": 0,
            "t": 0,
            "l": 0,
            "b": 0
        }
    }

    if readings is None or readings.empty:

        fig = go.Figure()

        fig.update_layout(**empty_layout)

        return fig

    map_rows = []

    unmapped_locations = []

    for _, row in readings.iterrows():

        location = str(
            row.get(
                "location",
                ""
            )
        ).strip()

        if not location:

            continue

        coords = get_location_coordinates(
            location
        )

        if coords is None:

            unmapped_locations.append(
                location
            )

            continue

        latitude, longitude = coords

        entry = row.to_dict()

        entry["latitude"] = latitude
        entry["longitude"] = longitude

        entry["risk_display"] = RISK_DISPLAY_LABELS.get(
            row.get("risk_level"),
            str(row.get("risk_level"))
        )

        # Always-visible label directly on the map for this
        # location — the risk circle + name, so the status is
        # visible at a glance without having to hover, and
        # without depending on marker color/size alone.
        entry["map_label"] = (
            f"{RISK_CIRCLE.get(row.get('risk_level'), NO_DATA_CIRCLE)} "
            f"{location}"
        )

        # Marker size: a visible FLOOR (18) regardless of risk,
        # so a Low-risk reading (which can be a single-digit
        # probability) is never reduced to a near-invisible dot
        # — probability still scales the size up further for
        # higher-risk locations, for visual emphasis, but never
        # shrinks a marker below a clearly clickable/visible
        # size.
        entry["marker_size"] = 18 + (
            float(
                row.get(
                    "flood_probability",
                    0
                ) or 0
            ) * 0.35
        )

        map_rows.append(entry)

    if unmapped_locations:

        st.warning(
            "⚠️ No map coordinates configured for: "
            + ", ".join(sorted(set(unmapped_locations)))
            + ". Add them to LOCATION_COORDINATES to display "
              "these locations on the map."
        )

    if not map_rows:

        fig = go.Figure()

        fig.update_layout(**empty_layout)

        return fig

    map_df = pd.DataFrame(
        map_rows
    )

    color_map = {

        RISK_DISPLAY_LABELS["Low"]:
            "#2ECC71",

        RISK_DISPLAY_LABELS["Moderate"]:
            "#FFB300",

        RISK_DISPLAY_LABELS["High"]:
            "#FF7F00",

        RISK_DISPLAY_LABELS["Severe"]:
            "#E53935"

    }

    # --------------------------------------------------------
    # Focus/zoom: default is Plotly's own auto-fit over every
    # plotted point (zoom=9, no explicit center — unchanged
    # behavior). If a valid focus_location was given, center on
    # its exact coordinates and zoom in closer instead.
    # --------------------------------------------------------

    map_center = None

    map_zoom = 9

    if focus_location:

        focus_coords = get_location_coordinates(
            focus_location
        )

        if focus_coords is not None:

            focus_latitude, focus_longitude = focus_coords

            map_center = {

                "lat": focus_latitude,

                "lon": focus_longitude

            }

            map_zoom = 12

    # --------------------------------------------------------
    # Auto-fit: when asked (and no single location is in focus),
    # center on the middle of the plotted markers and pick the
    # zoom level at which the whole spread is visible, instead of
    # the fixed zoom=9 which crops anything wider than ~2.5
    # degrees (e.g. the nationwide view).
    # --------------------------------------------------------

    if auto_fit and map_center is None:

        map_center, map_zoom = _fit_view(
            map_df["latitude"].tolist(),
            map_df["longitude"].tolist()
        )

    # --------------------------------------------------------
    # Plotly 7.x uses scatter_map instead of scatter_mapbox.
    # --------------------------------------------------------

    scatter_map_kwargs = {

        "lat": "latitude",

        "lon": "longitude",

        "color": "risk_display",

        "color_discrete_map": color_map,

        "size": "marker_size",

        "size_max": 32,

        "text": "map_label",

        "hover_name": "location",

        "hover_data": {

            "sensor_id":
                True,

            "water_level":
                True,

            "rainfall":
                True,

            "river_flow":
                True,

            "temperature":
                True,

            "humidity":
                True,

            "soil_moisture":
                True,

            "wind_speed":
                True,

            "flood_probability":
                True,

            "risk_display":
                True,

            "data_source":
                True,

            "marker_size":
                False,

            "latitude":
                False,

            "longitude":
                False

        },

        "zoom": map_zoom,

        "height": 600

    }

    if map_center is not None:

        scatter_map_kwargs["center"] = map_center

    fig = px.scatter_map(

        map_df,

        **scatter_map_kwargs

    )

    # Always show each marker's label (risk circle + location
    # name) directly on the map — not just on hover — so the
    # status is visible for every location at a glance.
    fig.update_traces(
        mode="markers+text",
        textposition="top center",
        textfont=dict(size=13, color="black")
    )

    fig.update_layout(

        map_style=
            "open-street-map",

        margin={
            "r": 0,
            "t": 0,
            "l": 0,
            "b": 0
        },

        legend=dict(
            title="Flood Risk Status"
        )

    )

    return fig
