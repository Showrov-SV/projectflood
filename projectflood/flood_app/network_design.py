"""The network design of the Cisco Packet Tracer prototype
(Flood_Monitoring_Emergency_Response_Network_Project.pkt), as data.

This is the single source of truth for the network side of the system:
the digital twin (digital_twin.py) builds its topology from it, so the
software and the paper's prototype cannot drift apart. If the Packet
Tracer design changes, edit ONLY this file.

Design summary (all addresses/areas are the ones configured in the
prototype's routers):

  OSPF area 0   R0 (core, RID 1.1.1.1) - 10.0.0.0/30 .. 10.0.0.20/30
                point-to-point links to R2, R3, R4 and R5
  OSPF area 1   R5 (RID 6.6.6.6)  192.168.10.0/24  sensor LAN: wireless
                sensor gateway + Switch0, Server0 (flood.local,
                192.168.10.11) and PC0
  OSPF area 2   R2 (RID 3.3.3.3)  router-on-a-stick to SW-A2 with four
                emergency-department VLANs (10 Police, 20 Fire Service,
                30 Hospital, 40 Municipality)
  OSPF area 3   R3 (RID 4.4.4.4)  192.168.30.0/24 server farm on SW-A3:
                Cloud-Registration, DNS, Web and Email (flood.com) servers
  Edge          R4 (RID 5.5.5.5, area 0, originates the default route)
                -> ISP (203.0.113.0/30 towards Cloud0)
"""

# Every node: id -> (type, label, parent, ospf_area, vlan, subnet/ip)
# Types: core, router, switch, gateway, server, pc, vlan, internet.
# Parents define the physical links (the prototype is a pure tree).

CORE_ID = "R0"
SERVER_ID = "Server0"
SENSOR_GATEWAY_ID = "WirelessRouter0"

DESIGN_NODES = (
    # id, type, label, parent, ospf_area, vlan, address
    ("R0", "core", "R0 · Core Router (OSPF area 0)", None, 0, None,
     "RID 1.1.1.1"),

    # ---- area 1: sensor LAN + central server ----------------------
    ("R5", "router", "R5 · Sensor-LAN Router (OSPF area 1)", "R0", 1,
     None, "192.168.10.2/24"),
    ("Switch0", "switch", "Switch0 · Sensor-LAN Switch", "R5", 1, None,
     None),
    ("Server0", "server", "Server0 · Central Server (flood.local)",
     "Switch0", 1, None, "192.168.10.11"),
    ("PC0", "pc", "PC0 · Control PC", "Switch0", 1, None,
     "192.168.10.10"),
    ("WirelessRouter0", "gateway", "Wireless Router0 · Sensor Gateway",
     "Switch0", 1, None, "192.168.10.1"),

    # ---- area 2: emergency departments (VLANs) --------------------
    ("R2", "router", "R2 · Emergency-Services Router (OSPF area 2)",
     "R0", 2, None, "10.0.0.6/30"),
    ("SW-A2", "switch", "SW-A2 · Emergency-Services Switch", "R2", 2,
     None, None),
    ("VLAN10", "vlan", "VLAN 10 · Police", "SW-A2", 2, 10,
     "192.168.20.0/24"),
    ("VLAN20", "vlan", "VLAN 20 · Fire Service", "SW-A2", 2, 20,
     "192.168.21.0/24"),
    ("VLAN30", "vlan", "VLAN 30 · Hospital", "SW-A2", 2, 30,
     "192.168.22.0/24"),
    ("VLAN40", "vlan", "VLAN 40 · Municipality", "SW-A2", 2, 40,
     "192.168.23.0/24"),

    # ---- area 3: server farm --------------------------------------
    ("R3", "router", "R3 · Server-Farm Router (OSPF area 3)", "R0", 3,
     None, "192.168.30.1/24"),
    ("SW-A3", "switch", "SW-A3 · Server-Farm Switch", "R3", 3, None,
     None),
    ("Cloud-Registration-Server", "server",
     "Cloud-Registration-Server", "SW-A3", 3, None, "192.168.30.10"),
    ("DNS-Server", "server", "DNS-Server", "SW-A3", 3, None,
     "192.168.30.11"),
    ("Web-Server", "server", "Web-Server", "SW-A3", 3, None,
     "192.168.30.12"),
    ("Email-Server", "server", "Email-Server (flood.com)", "SW-A3", 3,
     None, "192.168.30.13"),

    # ---- edge / internet ------------------------------------------
    ("R4", "router", "R4 · Edge Router (area 0, default route)", "R0",
     0, None, "10.0.0.17/30"),
    ("ISP", "internet", "ISP Router", "R4", None, None, "10.0.0.18/30"),
    ("Cloud0", "internet", "Cloud0 · Internet", "ISP", None, None,
     "203.0.113.0/30"),
)

# Names shown for each department VLAN (VLAN id -> department).
VLAN_DEPARTMENTS = {10: "Police", 20: "Fire Service", 30: "Hospital",
                    40: "Municipality"}

# Node types an operator can take down in the what-if analysis.
FAILABLE_TYPES = ("core", "router", "switch", "gateway", "server", "internet")

# Hand-placed (x, y) for the topology drawing (sensors are laid out
# automatically beneath SENSOR_GATEWAY_ID). x spans roughly 0..10.
LAYOUT = {
    "Cloud0": (9.0, 7.0), "ISP": (9.0, 6.0), "R4": (9.0, 5.0),
    "R0": (5.0, 5.0),
    "R5": (1.5, 4.0), "R2": (5.0, 4.0), "R3": (8.0, 4.0),
    "Switch0": (1.5, 3.0), "SW-A2": (5.0, 3.0), "SW-A3": (8.0, 3.0),
    "Server0": (0.2, 2.0), "PC0": (1.0, 2.0),
    "WirelessRouter0": (2.2, 2.0),
    "VLAN10": (4.0, 2.0), "VLAN20": (4.7, 2.0),
    "VLAN30": (5.4, 2.0), "VLAN40": (6.1, 2.0),
    "Cloud-Registration-Server": (7.2, 2.0), "DNS-Server": (7.8, 2.0),
    "Web-Server": (8.4, 2.0), "Email-Server": (9.0, 2.0),
}
