"""System Handler panel for the digital twin: live topology graph,
division health table, alert-delivery path and what-if failure
analysis."""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from flood_app.config import RISK_CIRCLE
from flood_app.digital_twin import (
    RISK_ORDER,
    MODELED_STATUS,
    SERVER_ID,
    alert_delivery_path,
    analyze_failure,
    get_twin_state,
    nodes_from_state,
    twin_summary,
)
from flood_app.geography import BD_DIVISIONS
from flood_app.network_design import (
    FAILABLE_TYPES,
    LAYOUT,
    SENSOR_GATEWAY_ID,
    VLAN_DEPARTMENTS,
)

_STATUS_COLOR = {
    "Online": "#2ecc71",
    "Nominal": "#3498db",
    MODELED_STATUS: "#7f8c8d",
    "Degraded": "#f39c12",
    "Stale": "#f1c40f",
    "Offline": "#e74c3c",
    "No data": "#95a5a6",
    "No sensors": "#bdc3c7",
    "Down (what-if)": "#000000",
    "Cut off (what-if)": "#7f1d1d",
}

_TYPE_ORDER = (
    "core", "router", "switch", "internet", "server", "pc", "gateway",
    "vlan", "sensor"
)

_TYPE_SYMBOL = {
    "core": "diamond",
    "router": "diamond-tall",
    "switch": "square",
    "internet": "cross",
    "server": "hexagon",
    "pc": "square-open",
    "gateway": "pentagon",
    "vlan": "triangle-up",
    "sensor": "circle",
}

_TYPE_SIZE = {
    "core": 24, "router": 19, "switch": 14, "internet": 14,
    "server": 15, "pc": 12, "gateway": 16, "vlan": 13, "sensor": 8,
}


def _layout(state_df):
    """(x, y) for every node: the Packet Tracer infrastructure is
    placed by network_design.LAYOUT, sensors fan out beneath the
    sensor gateway."""

    positions = {
        node_id: xy for node_id, xy in LAYOUT.items()
        if node_id in set(state_df["node_id"])
    }

    gx, gy = LAYOUT[SENSOR_GATEWAY_ID]

    sensor_ids = sorted(
        state_df.loc[state_df["node_type"] == "sensor", "node_id"]
    )

    m = len(sensor_ids)

    for k, node_id in enumerate(sensor_ids):

        x = gx - 1.2 + (2.4 * k / (m - 1) if m > 1 else 1.2)

        positions[node_id] = (x, gy - 0.8 - 0.25 * (k % 3))

    return positions


def _topology_figure(state_df, down_nodes, cut_off):

    positions = _layout(state_df)

    edge_x, edge_y = [], []

    for row in state_df.itertuples():

        if row.parent_id in positions and row.node_id in positions:

            x0, y0 = positions[row.parent_id]
            x1, y1 = positions[row.node_id]

            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1, color="rgba(128,128,128,0.45)"),
        hoverinfo="skip", showlegend=False
    ))

    for node_type in _TYPE_ORDER:

        subset = state_df[state_df["node_type"] == node_type]

        if subset.empty:
            continue

        xs, ys, colors, hover = [], [], [], []

        for row in subset.itertuples():

            if row.node_id not in positions:
                continue

            status = row.effective_status

            if row.node_id in down_nodes:
                status = "Down (what-if)"
            elif row.node_id in cut_off:
                status = "Cut off (what-if)"

            x, y = positions[row.node_id]
            xs.append(x)
            ys.append(y)
            colors.append(_STATUS_COLOR.get(status, "#95a5a6"))

            risk = (
                f"{row.risk_level} ({row.flood_probability:.1f}%)"
                if row.risk_level and pd.notna(row.flood_probability)
                else "—"
            )

            hover.append(
                f"<b>{row.label}</b><br>Status: {status}"
                f"<br>Flood risk: {risk}"
                f"<br>Status source: {row.status_source}"
            )

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=node_type.replace("_", " "),
            marker=dict(
                size=_TYPE_SIZE[node_type],
                symbol=_TYPE_SYMBOL[node_type],
                color=colors,
                line=dict(width=1, color="rgba(0,0,0,0.5)")
            ),
            text=hover, hoverinfo="text"
        ))

    fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        legend=dict(orientation="h", y=-0.02),
    )

    return fig


def _division_table(state_df):

    sensors = state_df[state_df["node_type"] == "sensor"]

    rows = []

    for division in BD_DIVISIONS + [None]:

        scope = sensors[
            sensors["division"] == division if division
            else sensors["division"].isna()
        ]

        if scope.empty and division is None:
            continue

        risks = [r for r in scope["risk_level"] if r in RISK_ORDER]

        worst = max(risks, key=RISK_ORDER.get) if risks else None

        probability = scope["flood_probability"].max()

        rows.append({
            "Division": division or "Unassigned",
            "Sensors online": (
                f"{(scope['effective_status'] == 'Online').sum()}"
                f" / {len(scope)}"
            ),
            "Worst risk": (
                f"{RISK_CIRCLE.get(worst, '')} {worst}"
                if worst else "—"
            ),
            "Max flood %": (
                round(float(probability), 1)
                if pd.notna(probability) else None
            ),
        })

    return pd.DataFrame(rows)


def digital_twin_panel():
    """Renders the whole Digital Twin tab."""

    st.subheader("🛰️ Digital twin of the monitoring network")

    state = get_twin_state()

    if state.empty:

        st.info(
            "The twin fills in after the first sensor refresh. Open "
            "another tab or use “Refresh data” in the sidebar."
        )

        return

    summary = twin_summary(state)

    m1, m2, m3, m4 = st.columns(4)

    m1.metric("Sensor nodes", summary["sensors_total"])
    m2.metric("Online", summary["online"])
    m3.metric("Stale", summary["stale"])
    m4.metric(
        "Offline / no data", summary["offline"] + summary["no_data"]
    )

    try:

        age = (
            datetime.now()
            - datetime.strptime(summary["last_sync"], "%Y-%m-%d %H:%M:%S")
        ).total_seconds()

        st.caption(
            f"Last synchronised {summary['last_sync']} "
            f"({int(age)} s ago)."
        )

    except (TypeError, ValueError):

        pass

    nodes = nodes_from_state(state)

    # ---------------- what-if selector (drives the figure) ----------
    labels = {n["node_id"]: n["label"] for n in nodes}

    failable = [
        n["node_id"] for n in nodes
        if n["node_type"] in FAILABLE_TYPES
    ]

    down = st.multiselect(
        "What-if: take these network nodes down",
        failable,
        format_func=lambda node_id: labels[node_id],
        key="twin_whatif_nodes",
        help=(
            "Reachability is computed from the central server (Server0) "
            "over the network links. Anything beneath a failed node "
            "is cut off."
        )
    )

    analysis = analyze_failure(nodes, down)

    cut_off = set(analysis["sensors_cut_off"]) | {
        n["node_id"] for n in nodes
        if n["node_id"] not in analysis["reachable"]
        and n["node_id"] not in down
    }

    st.plotly_chart(
        _topology_figure(state, set(down), cut_off),
        width="stretch"
    )

    st.markdown("**Sensor health by division**")

    st.dataframe(
        _division_table(state), width="stretch", hide_index=True
    )

    # ---------------- alert delivery path --------------------------
    st.markdown("**Alert delivery path**")

    path_department = st.selectbox(
        "Department", list(VLAN_DEPARTMENTS.values()),
        key="twin_path_department"
    )

    path = alert_delivery_path(nodes, path_department, down)

    if path:

        st.success(
            " → ".join(labels[node_id] for node_id in path)
            + f"  ({len(path) - 1} hops)"
        )

    else:

        st.error(
            "No path: this department can't receive alerts from the "
            "central server under the current what-if failures."
        )

    # ---------------- what-if results ------------------------------
    if down:

        st.markdown("**Impact of the selected failures**")

        if SERVER_ID in down:
            st.warning(
                "The central services server is down: no alert can be "
                "created or delivered to anyone."
            )

        r1, r2 = st.columns(2)

        r1.metric(
            "Sensors cut off",
            f"{len(analysis['sensors_cut_off'])} / "
            f"{summary['sensors_total']}"
        )

        r2.metric(
            "Departments / servers cut off",
            len(analysis["services_cut_off"])
        )

        affected = analysis["division_summary"]

        affected = affected[affected["sensors_cut_off"] > 0]

        if not affected.empty:

            st.dataframe(
                affected, width="stretch", hide_index=True
            )

        if not analysis["services_cut_off"].empty:

            with st.expander("Which departments and servers are cut off"):

                st.dataframe(
                    analysis["services_cut_off"],
                    width="stretch", hide_index=True
                )
