"""External CSV/XLSX dataset handling: reading, cleaning, predicting and
keeping the uploaded readings in the session."""

import io

import streamlit as st
import numpy as np
import pandas as pd
from datetime import datetime
import re

from flood_app.config import (
    DATASET_VALUE_LIMITS,
    REQUIRED_DATASET_COLUMNS,
)
from flood_app.prediction import hybrid_flood_prediction_batch


def normalize_dataset_columns(df):

    df = df.copy()

    # Tolerant header cleaning: "Rainfall (mm)", "Humidity (%)",
    # "River Flow [m3/s]" and "Water-Level" all reduce to the
    # plain column name (units in brackets are dropped, and any
    # run of non-alphanumeric characters becomes a single "_").
    def _clean_header(column):

        name = re.sub(r"[\(\[\{].*?[\)\]\}]", "", str(column))

        name = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())

        return name.strip("_")

    df.columns = [
        _clean_header(column)
        for column in df.columns
    ]

    aliases = {

        "waterlevel":
            "water_level",

        "water_level_m":
            "water_level",

        "rain":
            "rainfall",

        "rainfall_mm":
            "rainfall",

        "riverflow":
            "river_flow",

        "river_flow_ms":
            "river_flow",

        "temp":
            "temperature",

        "soil":
            "soil_moisture",

        "soil_moisture_percent":
            "soil_moisture",

        "wind":
            "wind_speed",

        "windspeed":
            "wind_speed"

    }

    df = df.rename(
        columns=aliases
    )

    return df


def _read_csv_tolerant(uploaded_file):
    """
    Reads a CSV the normal way first. Only if that doesn't give a
    usable table does it fall back to (a) Latin-1 text encoding
    (older Excel exports with accented characters) and (b)
    automatic delimiter detection, so semicolon- or tab-separated
    files (Excel in many European locales) load too.
    """

    raw = uploaded_file.read()

    text = None

    for encoding in ("utf-8-sig", "latin-1"):

        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    df = pd.read_csv(io.StringIO(text))

    if df.shape[1] <= 1:

        # European-style Excel export: ";" between columns and a
        # decimal COMMA inside numbers (3,1 means 3.1).
        header_line = text.splitlines()[0] if text.strip() else ""

        if header_line.count(";") > header_line.count(","):

            try:
                semicolon_df = pd.read_csv(
                    io.StringIO(text), sep=";", decimal=","
                )
                if semicolon_df.shape[1] > 1:
                    return semicolon_df
            except Exception:
                pass

        try:
            sniffed = pd.read_csv(
                io.StringIO(text), sep=None, engine="python"
            )
            if sniffed.shape[1] > 1:
                df = sniffed
        except Exception:
            pass  # keep the plain result; the caller reports it

    return df


def read_dataset_file(
    uploaded_file
):

    """
    Reads an uploaded CSV or XLSX file into a DataFrame.
    Returns None (after showing st.error) on any failure so
    the app never crashes on a bad file.
    """

    if uploaded_file is None:

        return None

    filename = getattr(
        uploaded_file,
        "name",
        "uploaded_file"
    )

    extension = filename.split(".")[-1].lower() if "." in filename else ""

    try:

        if extension == "csv":

            df = _read_csv_tolerant(uploaded_file)

        elif extension in (
            "xlsx",
            "xls"
        ):

            try:

                df = pd.read_excel(
                    uploaded_file,
                    engine="openpyxl"
                )

            except ImportError:

                st.error(
                    "Reading .xlsx files requires the 'openpyxl' "
                    "package. Please install it "
                    "(pip install openpyxl) or upload a CSV instead."
                )

                return None

        else:

            st.error(
                f"Unsupported file type '.{extension}'. "
                f"Please upload a CSV or XLSX file."
            )

            return None

    except Exception as error:

        st.error(
            f"Unable to read dataset: {error}"
        )

        return None

    if df is None or df.empty:

        st.error(
            "The uploaded file is empty or contains no rows."
        )

        return None

    return df


def process_uploaded_dataframe(
    df,
    location
):

    """
    Validates and prepares an already-loaded DataFrame for use
    as external sensor data for the given (externally selected)
    location. The dataset itself is NOT expected to contain a
    location column — if one exists it is ignored, since the
    location is always the one chosen by the user outside the
    file.
    """

    if not location or not str(location).strip():

        st.error(
            "Please select or enter a location before "
            "loading the dataset."
        )

        return None

    location = str(location).strip()

    df = normalize_dataset_columns(
        df
    )

    # Location is provided externally; drop any location-like
    # column from the file itself so it can never conflict.

    for stray_column in (
        "location",
        "area",
        "district"
    ):

        if stray_column in df.columns:

            df = df.drop(
                columns=[stray_column]
            )

    missing = [

        column

        for column in REQUIRED_DATASET_COLUMNS

        if column not in df.columns

    ]

    if missing:

        st.error(
            "Dataset is missing required columns: "
            + ", ".join(missing)
        )

        st.info(
            "Required columns: "
            + ", ".join(REQUIRED_DATASET_COLUMNS)
        )

        return None

    numeric_columns = [

        "water_level",

        "rainfall",

        "river_flow",

        "temperature",

        "humidity",

        "soil_moisture",

        "wind_speed"

    ]

    for column in numeric_columns:

        # +/-infinity (e.g. an "inf" cell) is not a usable
        # reading and would crash the ML models, so it is treated
        # exactly like a missing value.
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        ).replace([np.inf, -np.inf], np.nan)

    rows_in_file = len(df)

    df = df.dropna(
        subset=numeric_columns
    )

    # Skip physically impossible readings (see DATASET_VALUE_LIMITS).
    plausible = pd.Series(True, index=df.index)

    for column, (low, high) in DATASET_VALUE_LIMITS.items():
        plausible &= df[column].between(low, high)

    df = df[plausible]

    if df.empty:

        st.error(
            "No valid rows were found in the dataset. Rows are "
            "skipped when a value is missing, not a number, or "
            "outside a realistic range (e.g. humidity above 100 %)."
        )

        return None

    skipped_rows = rows_in_file - len(df)

    if skipped_rows:

        st.warning(
            f"{skipped_rows} of {rows_in_file} row(s) were skipped "
            f"because of missing, non-numeric or physically "
            f"impossible values. The other {len(df)} row(s) were "
            f"loaded."
        )

    if "sensor_id" not in df.columns:

        df["sensor_id"] = ""

    if "timestamp" not in df.columns:

        df["timestamp"] = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    multi_row = len(df) > 1

    base_sensor_id = (
        "DATA-"
        + location.upper().replace(
            " ",
            "-"
        )
    )

    df = df.reset_index(drop=True)

    # One vectorised prediction for the whole file (instead of
    # one full model call per row).
    prediction = hybrid_flood_prediction_batch(
        df[REQUIRED_DATASET_COLUMNS]
    )

    # Blank / missing sensor_id cells fall back to the generated
    # DATA-<LOCATION>[-n] id (previously a missing cell became the
    # literal text "nan").
    sensor_ids = (
        df["sensor_id"].fillna("").astype(str).str.strip()
        .replace({"nan": "", "None": ""})
    )

    if multi_row:
        fallback_ids = pd.Series(
            [
                f"{base_sensor_id}-{i}"
                for i in range(1, len(df) + 1)
            ],
            index=df.index
        )
    else:
        fallback_ids = pd.Series(base_sensor_id, index=df.index)

    sensor_ids = sensor_ids.where(sensor_ids != "", fallback_ids)

    results = pd.DataFrame({
        "sensor_id": sensor_ids,
        "location": location,
        "timestamp": df["timestamp"].astype(str),
    })

    results = pd.concat(
        [
            results,
            df[REQUIRED_DATASET_COLUMNS].astype(float).round(2),
            prediction
        ],
        axis=1
    )

    results["data_source"] = "External Dataset"

    return results


def ensure_dataset_state():

    """
    Makes sure the multi-location dataset storage exists in
    session state. Called defensively wherever dataset state
    is read or written, in addition to the one-time init in
    main(), so no code path can hit a missing key.
    """

    if "uploaded_datasets" not in st.session_state:

        st.session_state.uploaded_datasets = {}

    if "uploaded_datasets_meta" not in st.session_state:

        st.session_state.uploaded_datasets_meta = {}


def pick_latest_record(df):

    """
    Returns the single most-recent row of a dataframe as a
    Series, using the timestamp column when it can be parsed
    as a date/time, and falling back to the last row in file
    order otherwise (instead of an arbitrary row).
    """

    if df is None or df.empty:

        return None

    working = df.copy()

    parsed_time = pd.to_datetime(
        working["timestamp"],
        errors="coerce"
    )

    if parsed_time.notna().any():

        working = working.assign(
            _parsed_ts=parsed_time
        )

        working = working.sort_values(
            "_parsed_ts"
        )

    return working.iloc[-1]


def get_full_dataset(location):

    """Returns all uploaded rows for a location (for previews)."""

    ensure_dataset_state()

    return st.session_state.uploaded_datasets.get(
        location,
        pd.DataFrame()
    )


def get_uploaded_locations():

    """Locations currently backed by an external dataset."""

    ensure_dataset_state()

    return list(
        st.session_state.uploaded_datasets.keys()
    )


def get_dataset_readings():

    """
    Returns one CURRENT row per external-dataset location (the
    latest record, per pick_latest_record), for use by the same
    prediction/map/simulation pipeline that handles simulated
    sensor data.
    """

    ensure_dataset_state()

    datasets = st.session_state.uploaded_datasets

    if not datasets:

        return pd.DataFrame()

    latest_rows = []

    for location, df in datasets.items():

        latest = pick_latest_record(
            df
        )

        if latest is not None:

            latest_rows.append(
                latest
            )

    if not latest_rows:

        return pd.DataFrame()

    return pd.DataFrame(
        latest_rows
    ).reset_index(
        drop=True
    )


def remove_dataset_location(location):

    """Removes the uploaded dataset for one location only."""

    ensure_dataset_state()

    st.session_state.uploaded_datasets.pop(
        location,
        None
    )

    st.session_state.uploaded_datasets_meta.pop(
        location,
        None
    )
