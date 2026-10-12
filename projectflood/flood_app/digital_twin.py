"""Digital twin: a persistent, synchronised state mirror of the flood
monitoring network.

What it is
----------
A model of the network built in the Cisco Packet Tracer prototype (see
network_design.py): IoT sensors -> wireless sensor gateway -> Switch0 ->
R5 (OSPF area 1) -> R0 core (area 0) -> R2 (area 2, emergency-department
VLANs 10-40), R3 (area 3, server farm) and R4 (edge) -> ISP -> Internet.
The central server (Server0, flood.local) sits in area 1. The state is
kept in the `digital_twin_state` table and re-synchronised from the
live sensor readings every time fresh data arrives.

What it does
------------
* sync_twin()        - mirror the latest readings into the twin.
* get_twin_state()   - read the twin with each node's EFFECTIVE status
                       (Online / Stale / Offline / No data / Degraded).
* analyze_failure()  - what-if: take nodes down and see which sensors,
                       department VLANs and servers can no longer be
                       reached from the central server.
* alert_delivery_path() - the hop-by-hop route an alert takes.
* set_node_status()  - hook for a REAL network monitor (SNMP, ping...)
                       to push infrastructure status into the twin.

What it is NOT
--------------
Routers, switches, VLANs and servers have no live telemetry in this
app, so they are reported as "Not monitored" until something calls
set_node_status(). Reachability is graph connectivity only; no latency
or packet-loss figures are produced because none are measured.

This module has no Streamlit dependency."""

import json
from collections import deque
from datetime import datetime

import pandas as pd

from flood_app.config import (
    TWIN_EXTRA_LINKS,
    TWIN_OFFLINE_AFTER_SECONDS,
    TWIN_STALE_AFTER_SECONDS,
)
from flood_app.database import get_connection
from flood_app.geography import get_division_for_location
from flood_app.network_design import (
    CORE_ID,
    DESIGN_NODES,
    SENSOR_GATEWAY_ID,
    SERVER_ID,
    VLAN_DEPARTMENTS,
)

SENSOR_AREA = 1  # OSPF area of the sensor LAN in the prototype
MODELED_STATUS = "Not monitored"

RISK_ORDER = {"Low": 0, "Moderate": 1, "High": 2, "Severe": 3}

ALLOWED_EXTERNAL_STATUSES = ("Online", "Offline", "Degraded", "Nominal")

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


# ============================================================
# TOPOLOGY
# ============================================================

def _node(
    node_id, node_type, label, parent_id,
    division=None, ospf_area=None, vlan=None, location=None
):
    return {
        "node_id": node_id,
        "node_type": node_type,
        "label": label,
        "parent_id": parent_id,
        "division": division,
        "ospf_area": ospf_area,
        "vlan": vlan,
        "location": location,
    }


def sensor_node_id(sensor_id):
    return f"SENSOR-{sensor_id}"


def build_topology(sensors=None):
    """The list of network nodes (dicts) for the current set of
    registered sensors: the fixed Packet Tracer infrastructure from
    network_design.py plus one node per sensor (all attached to the
    sensor gateway, as in the prototype). `sensors` needs `sensor_id`
    and `location` columns (None / empty = infrastructure only). Pure
    function: no database access."""

    nodes = [
        _node(
            node_id, node_type, label, parent, None, area, vlan
        )
        for node_id, node_type, label, parent, area, vlan, _addr
        in DESIGN_NODES
    ]

    if sensors is not None and len(sensors):

        for sensor_id, location in zip(
            sensors["sensor_id"], sensors["location"]
        ):

            nodes.append(_node(
                sensor_node_id(sensor_id), "sensor",
                f"{sensor_id} · {location}", SENSOR_GATEWAY_ID,
                get_division_for_location(location), SENSOR_AREA,
                location=str(location)
            ))

    return nodes


def _adjacency(nodes):
    """Undirected adjacency from the parent links plus any
    TWIN_EXTRA_LINKS (redundant paths) whose endpoints exist."""

    ids = {n["node_id"] for n in nodes}

    adjacency = {node_id: set() for node_id in ids}

    for n in nodes:

        parent = n["parent_id"]

        if parent in ids:
            adjacency[n["node_id"]].add(parent)
            adjacency[parent].add(n["node_id"])

    for a, b in TWIN_EXTRA_LINKS:

        if a in ids and b in ids:
            adjacency[a].add(b)
            adjacency[b].add(a)

    return adjacency


def reachable_nodes(nodes, down_nodes=()):
    """Node ids reachable from the central server when `down_nodes`
    have failed (a down node neither carries traffic nor counts as
    reachable). If the server itself is down, nothing is reachable."""

    down = set(down_nodes)

    if SERVER_ID in down:
        return set()

    adjacency = _adjacency(nodes)

    if SERVER_ID not in adjacency:
        return set()

    seen = {SERVER_ID}
    queue = deque([SERVER_ID])

    while queue:

        current = queue.popleft()

        for neighbour in adjacency[current]:

            if neighbour in seen or neighbour in down:
                continue

            seen.add(neighbour)
            queue.append(neighbour)

    return seen


def shortest_path(nodes, source, target, down_nodes=()):
    """Fewest-hop list of node ids from `source` to `target` avoiding
    `down_nodes`, or None if no path exists."""

    down = set(down_nodes)

    adjacency = _adjacency(nodes)

    if (
        source not in adjacency or target not in adjacency
        or source in down or target in down
    ):
        return None

    previous = {source: None}
    queue = deque([source])

    while queue:

        current = queue.popleft()

        if current == target:

            path = []

            while current is not None:
                path.append(current)
                current = previous[current]

            return path[::-1]

        for neighbour in adjacency[current]:

            if neighbour in previous or neighbour in down:
                continue

            previous[neighbour] = current
            queue.append(neighbour)

    return None


def alert_delivery_path(nodes, department, down_nodes=()):
    """Route an alert takes from the central server to one
    department's VLAN (list of node ids), or None if that VLAN is
    currently cut off."""

    vlan_ids = {name: vid for vid, name in VLAN_DEPARTMENTS.items()}

    if department not in vlan_ids:
        return None

    return shortest_path(
        nodes, SERVER_ID, f"VLAN{vlan_ids[department]}", down_nodes
    )


def analyze_failure(nodes, down_nodes=()):
    """What-if analysis. Returns a dict:

        reachable           set of node ids still reachable from the server
        sensors_cut_off     list of sensor node ids that lost connectivity
        division_summary    DataFrame: division, sensors_total, sensors_cut_off
        services_cut_off    DataFrame: service, address of every department
                            VLAN / server-farm server that is cut off
    """

    reachable = reachable_nodes(nodes, down_nodes)

    sensors = [n for n in nodes if n["node_type"] == "sensor"]

    cut_off = [
        n["node_id"] for n in sensors if n["node_id"] not in reachable
    ]

    cut_off_set = set(cut_off)

    totals = {}

    for n in sensors:

        key = n["division"] or "Unassigned"

        total, cut = totals.get(key, (0, 0))

        totals[key] = (
            total + 1,
            cut + (1 if n["node_id"] in cut_off_set else 0)
        )

    division_summary = pd.DataFrame(
        [
            {
                "division": key,
                "sensors_total": total,
                "sensors_cut_off": cut
            }
            for key, (total, cut) in sorted(totals.items())
        ],
        columns=["division", "sensors_total", "sensors_cut_off"]
    )

    address = {row[0]: row[6] for row in DESIGN_NODES}

    services_cut_off = pd.DataFrame(
        [
            {
                "service": n["label"],
                "address": address.get(n["node_id"]),
            }
            for n in nodes
            if n["node_type"] in ("vlan", "server")
            and n["node_id"] not in reachable
        ],
        columns=["service", "address"]
    )

    return {
        "reachable": reachable,
        "sensors_cut_off": cut_off,
        "division_summary": division_summary,
        "services_cut_off": services_cut_off,
    }


# ============================================================
# SYNCHRONISATION (readings -> twin state)
# ============================================================

def _worst(risks):

    known = [r for r in risks if r in RISK_ORDER]

    return max(known, key=RISK_ORDER.get) if known else None


def _jsonable(value):

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_UPSERT = """
INSERT INTO digital_twin_state(
    node_id, node_type, label, parent_id, division, location,
    ospf_area, vlan, reported_status, status_source, risk_level,
    flood_probability, last_reading_at, last_sync_at, details
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(node_id) DO UPDATE SET
    node_type = excluded.node_type,
    label = excluded.label,
    parent_id = excluded.parent_id,
    division = excluded.division,
    location = excluded.location,
    ospf_area = excluded.ospf_area,
    vlan = excluded.vlan,
    reported_status = CASE
        WHEN digital_twin_state.status_source = 'external'
        THEN digital_twin_state.reported_status
        ELSE excluded.reported_status END,
    status_source = CASE
        WHEN digital_twin_state.status_source = 'external'
        THEN 'external'
        ELSE excluded.status_source END,
    risk_level = excluded.risk_level,
    flood_probability = excluded.flood_probability,
    last_reading_at = COALESCE(
        excluded.last_reading_at, digital_twin_state.last_reading_at
    ),
    last_sync_at = excluded.last_sync_at,
    details = COALESCE(excluded.details, digital_twin_state.details)
"""


def sync_twin(readings, sensors, now=None):
    """Mirrors the latest sensor readings into the twin.

    `readings`: DataFrame with sensor_id, timestamp, flood_probability,
    risk_level and the raw sensor columns (as produced by the
    simulation or a real feed). `sensors`: the registered-sensors table
    (sensor_id, location, status). Sensors missing from `readings` keep
    their previous reading time, so they age to Stale / Offline.
    Sensors that were removed from the registry are removed from the
    twin. Returns the number of nodes written."""

    now = now or datetime.now()

    nodes = build_topology(sensors)

    registered_status = {}

    if sensors is not None and len(sensors):

        registered_status = dict(zip(
            sensors["sensor_id"].astype(str),
            sensors["status"].astype(str)
        ))

    latest = {}

    if readings is not None and len(readings):

        for record in readings.to_dict("records"):
            latest[str(record["sensor_id"])] = record

    # Aggregate flood risk upwards: sensor -> nation.
    nation_risks, nation_prob = [], []

    for n in nodes:

        if n["node_type"] != "sensor":
            continue

        record = latest.get(n["node_id"][len("SENSOR-"):])

        if not record:
            continue

        nation_risks.append(record.get("risk_level"))
        nation_prob.append(_jsonable(record.get("flood_probability")))

    sync_time = now.strftime(_TS_FORMAT)

    rows = []

    for n in nodes:

        node_id = n["node_id"]

        risk, probability = None, None
        reported, source = MODELED_STATUS, "modeled"
        last_reading_at, details = None, None

        if n["node_type"] == "sensor":

            raw_id = node_id[len("SENSOR-"):]

            reported = registered_status.get(raw_id, "Online")
            source = "sensor_registry"

            record = latest.get(raw_id)

            if record:

                risk = record.get("risk_level")
                probability = _jsonable(record.get("flood_probability"))
                last_reading_at = str(record.get("timestamp"))

                details = json.dumps({
                    key: _jsonable(record.get(key))
                    for key in (
                        "water_level", "rainfall", "river_flow",
                        "temperature", "humidity", "soil_moisture",
                        "wind_speed"
                    )
                })

        elif node_id in (CORE_ID, SERVER_ID):

            risk = _worst(nation_risks)
            valid = [p for p in nation_prob if p is not None]
            probability = max(valid) if valid else None

        elif n["node_type"] == "gateway":

            risk = _worst(nation_risks)
            valid = [p for p in nation_prob if p is not None]
            probability = max(valid) if valid else None
            source = "sensor_registry"

        rows.append((
            node_id, n["node_type"], n["label"], n["parent_id"],
            n["division"], n["location"], n["ospf_area"], n["vlan"],
            reported, source, risk, probability, last_reading_at,
            sync_time, details
        ))

    conn = get_connection()

    try:

        with conn:

            conn.executemany(_UPSERT, rows)

            known = {n["node_id"] for n in nodes}

            stale = [
                (row[0],)
                for row in conn.execute(
                    "SELECT node_id FROM digital_twin_state"
                )
                if row[0] not in known
            ]

            conn.executemany(
                "DELETE FROM digital_twin_state WHERE node_id = ?",
                stale
            )

    finally:

        conn.close()

    return len(rows)


def set_node_status(node_id, status):
    """Lets a real network monitor (SNMP poller, ping check, a
    Packet Tracer export...) push the status of any node into the
    twin. The status is kept across later syncs. Returns True if the
    node exists."""

    if status not in ALLOWED_EXTERNAL_STATUSES:
        raise ValueError(
            f"status must be one of {ALLOWED_EXTERNAL_STATUSES}"
        )

    conn = get_connection()

    try:

        with conn:

            cursor = conn.execute(
                """
                UPDATE digital_twin_state
                SET reported_status = ?,
                    status_source = 'external',
                    last_sync_at = ?
                WHERE node_id = ?
                """,
                (
                    status,
                    datetime.now().strftime(_TS_FORMAT),
                    node_id
                )
            )

            return cursor.rowcount > 0

    finally:

        conn.close()


# ============================================================
# READING THE TWIN
# ============================================================

def _parse_ts(value):

    try:
        return datetime.strptime(str(value), _TS_FORMAT)
    except (TypeError, ValueError):
        return None


def sensor_effective_status(reported, last_reading_at, now):
    """Online / Stale / Offline / No data for one sensor, from its
    registered status and how long ago it last reported."""

    if str(reported).strip().lower() != "online":
        return "Offline"

    seen = _parse_ts(last_reading_at)

    if seen is None:
        return "No data"

    age = (now - seen).total_seconds()

    if age <= TWIN_STALE_AFTER_SECONDS:
        return "Online"

    if age <= TWIN_OFFLINE_AFTER_SECONDS:
        return "Stale"

    return "Offline"


def get_twin_state(now=None):
    """The whole twin as a DataFrame with an `effective_status`
    column: sensors from reading age; gateways aggregated from their
    sensors (Online / Degraded / Offline / No sensors); externally
    reported nodes as reported; everything else 'Not monitored' (modeled)."""

    now = now or datetime.now()

    conn = get_connection()

    try:

        df = pd.read_sql_query(
            "SELECT * FROM digital_twin_state ORDER BY node_id", conn
        )

    except Exception:

        return pd.DataFrame()

    finally:

        conn.close()

    if df.empty:
        return df

    effective = {}

    for row in df.itertuples():

        if row.node_type == "sensor":

            effective[row.node_id] = (
                row.reported_status
                if row.status_source == "external"
                else sensor_effective_status(
                    row.reported_status, row.last_reading_at, now
                )
            )

    children = df[df["node_type"] == "sensor"].groupby("parent_id")

    for row in df[df["node_type"] == "gateway"].itertuples():

        if row.status_source == "external":

            effective[row.node_id] = row.reported_status
            continue

        if row.node_id not in children.groups:

            effective[row.node_id] = "No sensors"
            continue

        statuses = [
            effective[node_id]
            for node_id in children.get_group(row.node_id)["node_id"]
        ]

        online = sum(1 for s in statuses if s == "Online")

        effective[row.node_id] = (
            "Online" if online == len(statuses)
            else "Offline" if online == 0
            else "Degraded"
        )

    df["effective_status"] = [
        effective.get(row.node_id, row.reported_status)
        for row in df.itertuples()
    ]

    return df


def nodes_from_state(state_df):
    """Rebuilds the node dicts (for the reachability helpers) from a
    get_twin_state() DataFrame."""

    def clean(value):
        # SQL NULL arrives from pandas as NaN, which is truthy and
        # unorderable - normalise it back to None.
        return None if pd.isna(value) else value

    return [
        {
            "node_id": row.node_id,
            "node_type": row.node_type,
            "label": row.label,
            "parent_id": clean(row.parent_id),
            "division": clean(row.division),
            "ospf_area": (
                None if pd.isna(row.ospf_area) else int(row.ospf_area)
            ),
            "vlan": None if pd.isna(row.vlan) else int(row.vlan),
            "location": clean(row.location),
        }
        for row in state_df.itertuples()
    ]


def twin_summary(state_df):
    """Headline numbers for the dashboard."""

    sensors = state_df[state_df["node_type"] == "sensor"]

    counts = sensors["effective_status"].value_counts().to_dict()

    return {
        "sensors_total": len(sensors),
        "online": counts.get("Online", 0),
        "stale": counts.get("Stale", 0),
        "offline": counts.get("Offline", 0),
        "no_data": counts.get("No data", 0),
        "last_sync": state_df["last_sync_at"].max(),
    }
