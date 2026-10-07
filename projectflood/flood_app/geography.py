"""Bangladesh divisions, districts (zila), their map coordinates and the
helpers that look up which division/district a location belongs to."""


# ============================================================
# BANGLADESH DIVISION + DISTRICT (ZILA) HIERARCHY
# ============================================================
# Defined here (ahead of init_database(), which seeds accounts
# using these) rather than down near LOCATION_COORDINATES,
# purely because init_database() runs at import time, before
# the rest of the module has executed.
#
# DISTRICT_COORDINATES gives every one of the 64 real
# districts (zilas) of Bangladesh a (lat, lon) — grouped under
# its real parent division, not the old placeholder
# neighborhoods/areas this app used before. DIVISION_AREAS below
# is built directly from this, so "area" now means "real
# district" everywhere in the app: monitoring, prediction,
# sensors, the map, and account scoping are all district-level.
# Coordinates are each district's headquarters town
# (zila sadar), approximate to a few km — accurate enough for
# this app's map/visualization purposes, not surveying-grade.
# ============================================================

DISTRICT_COORDINATES = {

    # ---- Dhaka Division (13 districts) ----
    "Dhaka": (23.8103, 90.4125),
    "Faridpur": (23.6070, 89.8429),
    "Gazipur": (23.9999, 90.4203),
    "Gopalganj": (23.0050, 89.8266),
    "Kishoreganj": (24.4262, 90.9799),
    "Madaripur": (23.1642, 90.1897),
    "Manikganj": (23.8644, 90.0038),
    "Munshiganj": (23.5422, 90.5305),
    "Narayanganj": (23.6238, 90.5000),
    "Narsingdi": (23.9322, 90.7150),
    "Rajbari": (23.7574, 89.6444),
    "Shariatpur": (23.2423, 90.4348),
    "Tangail": (24.2513, 89.9167),

    # ---- Chattogram Division (11 districts) ----
    "Bandarban": (22.1953, 92.2184),
    "Brahmanbaria": (23.9571, 91.1119),
    "Chandpur": (23.2333, 90.6500),
    "Chattogram": (22.3569, 91.7832),
    "Cumilla": (23.4607, 91.1809),
    "Cox's Bazar": (21.4272, 92.0058),
    "Feni": (23.0159, 91.3976),
    "Khagrachhari": (23.1193, 91.9847),
    "Lakshmipur": (22.9440, 90.8285),
    "Noakhali": (22.8696, 91.0995),
    "Rangamati": (22.6533, 92.1729),

    # ---- Rajshahi Division (8 districts) ----
    "Bogura": (24.8465, 89.3773),
    "Joypurhat": (25.1023, 89.0227),
    "Naogaon": (24.7936, 88.9318),
    "Natore": (24.4206, 88.9862),
    "Chapainawabganj": (24.5965, 88.2775),
    "Pabna": (24.0064, 89.2372),
    "Rajshahi": (24.3745, 88.6042),
    "Sirajganj": (24.4533, 89.7006),

    # ---- Khulna Division (10 districts) ----
    "Bagerhat": (22.6602, 89.7895),
    "Chuadanga": (23.6402, 88.8410),
    "Jashore": (23.1667, 89.2167),
    "Jhenaidah": (23.5448, 89.1539),
    "Khulna": (22.8456, 89.5403),
    "Kushtia": (23.9013, 89.1220),
    "Magura": (23.4873, 89.4198),
    "Meherpur": (23.7622, 88.6318),
    "Narail": (23.1725, 89.5126),
    "Satkhira": (22.7085, 89.0705),

    # ---- Barishal Division (6 districts) ----
    "Barguna": (22.0953, 90.1121),
    "Barishal": (22.7010, 90.3535),
    "Bhola": (22.6859, 90.6482),
    "Jhalokati": (22.6406, 90.1987),
    "Patuakhali": (22.3596, 90.3298),
    "Pirojpur": (22.5841, 89.9720),

    # ---- Sylhet Division (4 districts) ----
    "Habiganj": (24.3745, 91.4156),
    "Moulvibazar": (24.4829, 91.7774),
    "Sunamganj": (25.0658, 91.3950),
    "Sylhet": (24.8949, 91.8687),

    # ---- Rangpur Division (8 districts) ----
    "Dinajpur": (25.6279, 88.6332),
    "Gaibandha": (25.3288, 89.5285),
    "Kurigram": (25.8072, 89.6297),
    "Lalmonirhat": (25.9923, 89.2847),
    "Nilphamari": (25.9317, 88.8560),
    "Panchagarh": (26.3411, 88.5541),
    "Rangpur": (25.7439, 89.2752),
    "Thakurgaon": (26.0336, 88.4616),

    # ---- Mymensingh Division (4 districts) ----
    "Jamalpur": (24.9375, 89.9377),
    "Mymensingh": (24.7471, 90.4203),
    "Netrokona": (24.8710, 90.7276),
    "Sherpur": (25.0204, 90.0153)

}


BD_DIVISIONS = [
    "Dhaka",
    "Chattogram",
    "Rajshahi",
    "Khulna",
    "Barishal",
    "Sylhet",
    "Rangpur",
    "Mymensingh"
]


# Which real districts belong to each division — the single
# source of truth for the whole app's division-level scoping
# (Division Admin/Police/Fire Service/Hospital/Municipality all
# see exactly these districts and nothing else).
DIVISION_AREAS = {

    "Dhaka": [
        "Dhaka", "Faridpur", "Gazipur", "Gopalganj",
        "Kishoreganj", "Madaripur", "Manikganj", "Munshiganj",
        "Narayanganj", "Narsingdi", "Rajbari", "Shariatpur",
        "Tangail"
    ],

    "Chattogram": [
        "Bandarban", "Brahmanbaria", "Chandpur", "Chattogram",
        "Cumilla", "Cox's Bazar", "Feni", "Khagrachhari",
        "Lakshmipur", "Noakhali", "Rangamati"
    ],

    "Rajshahi": [
        "Bogura", "Joypurhat", "Naogaon", "Natore",
        "Chapainawabganj", "Pabna", "Rajshahi", "Sirajganj"
    ],

    "Khulna": [
        "Bagerhat", "Chuadanga", "Jashore", "Jhenaidah",
        "Khulna", "Kushtia", "Magura", "Meherpur", "Narail",
        "Satkhira"
    ],

    "Barishal": [
        "Barguna", "Barishal", "Bhola", "Jhalokati",
        "Patuakhali", "Pirojpur"
    ],

    "Sylhet": [
        "Habiganj", "Moulvibazar", "Sunamganj", "Sylhet"
    ],

    "Rangpur": [
        "Dinajpur", "Gaibandha", "Kurigram", "Lalmonirhat",
        "Nilphamari", "Panchagarh", "Rangpur", "Thakurgaon"
    ],

    "Mymensingh": [
        "Jamalpur", "Mymensingh", "Netrokona", "Sherpur"
    ]

}


# Reverse lookup: district name -> its division, e.g.
# "Gazipur" -> "Dhaka". Used by the automatic emergency alert
# system so an auto-alert for one district also reaches that
# district's Division Admin + division-specific Police/Fire
# Service/Hospital/Municipality, not just the national legacy
# accounts.
LOCATION_TO_DIVISION = {
    area: division
    for division, areas in DIVISION_AREAS.items()
    for area in areas
}


# Case/whitespace-insensitive version of the same lookup —
# sensor locations can be freely typed (Admin's "Register New
# Sensor" form is a plain text field, not a dropdown), so a
# location entered as "dhaka" or " Dhaka " must still match
# "Dhaka" here. Built once at import time from
# LOCATION_TO_DIVISION above.
_LOCATION_TO_DIVISION_NORMALIZED = {
    area.strip().lower(): division
    for area, division in LOCATION_TO_DIVISION.items()
}


def get_division_for_location(location):
    """
    Case/whitespace-insensitive lookup of which division (if
    any) a district belongs to. Returns None if the location
    isn't one of the 64 real districts (e.g. a custom "➕ Other"
    location entered by hand).
    """

    if not location:
        return None

    return _LOCATION_TO_DIVISION_NORMALIZED.get(
        str(location).strip().lower()
    )


# ============================================================
# DISTRICT ADMIN HIERARCHY
# ============================================================
# A separate, parallel admin tier to Division Admin — a District
# Admin (and District Police/Fire Service/Municipality) gets the
# same dashboard capabilities as their division-level
# counterpart, but scoped to exactly ONE real district instead
# of that district's whole division.
#
# DISTRICT_NAMES is now every one of the 64 real districts (zilas)
# — one set of District Admin/Police/Fire Service/Municipality
# accounts per district, 256 accounts total. DISTRICT_AREAS is
# an identity mapping (a district's only "area" is itself) since
# districts are already the finest granularity this app
# monitors — there's no further sub-district breakdown.
# ============================================================

DISTRICT_NAMES = [
    district
    for division_districts in DIVISION_AREAS.values()
    for district in division_districts
]


DISTRICT_AREAS = {
    district_name: [district_name]
    for district_name in DISTRICT_NAMES
}


def get_district_areas(district):
    """Every area a District Admin for this district may work
    with — always just [district] itself, since districts are
    this app's finest monitoring granularity. Returns [] for an
    unrecognized district — callers must treat that as "no areas
    available", never as "unrestricted"."""

    return DISTRICT_AREAS.get(district, [])


def get_districts_for_location(location):
    """
    Every district (there can be more than one in principle,
    though with the real 64-district model there's normally
    exactly one) whose area list contains this location.
    Case/whitespace-insensitive. Used by the automatic emergency
    alert system so a District Admin is notified when their own
    district crosses the alert threshold.
    """

    if not location:
        return []

    normalized = str(location).strip().lower()

    return [
        district
        for district, areas in DISTRICT_AREAS.items()
        if normalized in {a.strip().lower() for a in areas}
    ]


def slugify_name(name):
    """
    Turns a display name into a clean, login-friendly username
    fragment: lowercase, spaces/apostrophes/punctuation removed
    (kept as nothing, not underscores, so "Cox's Bazar" becomes
    "coxsbazar" rather than a username containing a literal
    space or quote character — either of which would still work
    as a SQLite value, but makes for an awkward, error-prone
    login username). Used for every one of the 64 real
    districts' seeded usernames.
    """

    return "".join(
        character
        for character in str(name).lower()
        if character.isalnum()
    )


# ============================================================
# LOCATION → COORDINATES MAPPING
# ============================================================
#
# Uploaded datasets do NOT contain location or coordinate
# columns. The user selects a location externally (outside the
# dataset), so this table is the single source of truth for
# where each named location sits on the Live Flood Location Map.
#
# Includes the default registered sensor neighborhoods plus
# major Bangladesh districts/divisions so newly uploaded
# datasets for areas like Jamalpur, Mymensingh, Dhaka, or
# Sylhet can be placed on the map immediately.
# ============================================================

LOCATION_COORDINATES = dict(DISTRICT_COORDINATES)


# --------------------------------------------------------------
# LEGACY ALIASES (backward compatibility only)
# --------------------------------------------------------------
# These are OLD placeholder location names this app used before
# the real 64-district model — no longer part of DIVISION_AREAS
# / DISTRICT_NAMES, so they no longer appear in any selector and
# can't be picked by a scoped account. Kept here only so
# get_location_coordinates() / the map can still resolve
# coordinates for any sensor rows or uploaded datasets an
# existing, already-running deployment created against these
# names before this change, instead of silently failing to plot
# them. Spelling variants (pre-2018 English spellings) are kept
# for the same reason.
# --------------------------------------------------------------

LOCATION_COORDINATES.update({
    "Mirpur": (23.8223, 90.3654),
    "Uttara": (23.8759, 90.3795),
    "Dhanmondi": (23.7461, 90.3742),
    "Tejgaon": (23.7590, 90.3880),
    "Jatrabari": (23.7104, 90.4351),
    "Keraniganj": (23.6800, 90.3300),
    "Savar": (23.8583, 90.2667),
    "Chittagong": (22.3569, 91.7832),
    "Barisal": (22.7010, 90.3535),
    "Comilla": (23.4607, 91.1809),
})
