"""Internal mail configuration: mail domains, the list of mail roles/mailboxes
(division and district level) and the mailbox-key helpers."""

from flood_app.geography import BD_DIVISIONS, DISTRICT_NAMES


# ============================================================
# CISCO / EMERGENCY DOMAIN NAMES
# ============================================================
#
# These are kept in one place so they can easily be changed
# according to the Cisco Packet Tracer diagram.
#
# If your Cisco diagram uses different domain names, change
# ONLY these values.
# ============================================================

EMERGENCY_DOMAINS = {

    "Police":
        "flood.com",

    "Fire Service":
        "flood.com",

    "Hospital":
        "flood.com",

    "Municipality":
        "flood.com"

}


# ============================================================
# EMAIL SERVER CONFIGURATION
# ============================================================
#
# Simulated mail server settings. Each emergency organization
# has a mailbox derived from its Cisco domain name above, so
# fixing EMERGENCY_DOMAINS automatically fixes these addresses.
# ============================================================

MAIL_SERVER_NAME = "flood.com Mail Server (SMTP)"


ADMIN_EMAIL = "admin@flood.com"


EMERGENCY_EMAILS = {

    "Police":
        "police@flood.com",

    "Fire Service":
        "fire@flood.com",

    "Hospital":
        "hospital@flood.com",

    "Municipality":
        "municipality@flood.com"

}


# ============================================================
# INTERNAL USER-TO-USER EMAIL: SHARED ROLE CONFIGURATION
# ============================================================
#
# These build directly on top of EMERGENCY_DOMAINS,
# EMERGENCY_EMAILS and ADMIN_EMAIL above (nothing there is
# changed or duplicated) so the internal Inbox/Sent/Compose/Bin
# system stays consistent with the existing SMTP-status panel
# and Cisco domain mapping.
# ============================================================

# Every organization that can hold a mailbox / send & receive
# internal email. "Administrator" is included so Admin has a
# full Inbox/Sent/Bin like everyone else, in addition to the
# existing Admin -> Emergency Organization messaging tool.
#
# LEGACY_MAIL_ROLES is exactly the original 5-role list, kept
# under its own name so the ORIGINAL accounts' Compose-tab
# recipient list (built from this constant at the one call site
# in organization_dashboard()) never changes shape, no matter
# how many hierarchical mailbox keys get added below.
LEGACY_MAIL_ROLES = [
    "Administrator",
    "Police",
    "Fire Service",
    "Hospital",
    "Municipality"
]


# One composite mailbox key per hierarchical account — e.g.
# "Dhaka Police", "Dhaka Division Admin" — built from
# BD_DIVISIONS so it always matches mailbox_key() below and the
# accounts seeded in init_database(). Used only to (a) validate
# sender/recipient roles in send_email() and (b) let System
# Handler / Division Admin dashboards build their own, narrower
# recipient lists — never merged into LEGACY_MAIL_ROLES itself.
HIERARCHICAL_MAIL_ROLES = ["System Handler"]


for _division_name in BD_DIVISIONS:

    HIERARCHICAL_MAIL_ROLES.append(f"{_division_name} Division Admin")

    for _org_role in ("Police", "Fire Service", "Hospital", "Municipality"):

        HIERARCHICAL_MAIL_ROLES.append(f"{_division_name} {_org_role}")


# One composite mailbox key per district-tier account — e.g.
# "Dhaka District Admin", "Dhaka District Police". Built from
# DISTRICT_NAMES so it always matches mailbox_key() below and
# the accounts seeded in init_database(). Without these,
# send_email()'s ALL_MAIL_ROLES membership check rejects every
# District Admin / District Police / District Fire Service /
# District Municipality mailbox — this previously left every
# District Admin's own Messaging/Mailbox tab silently broken
# ("Unknown sender role."), even though the UI rendered fine.
for _district_name in DISTRICT_NAMES:

    HIERARCHICAL_MAIL_ROLES.append(
        f"{_district_name} District Admin"
    )

    for _org_role in (
        "District Police", "District Fire Service",
        "District Municipality"
    ):

        HIERARCHICAL_MAIL_ROLES.append(
            f"{_district_name} {_org_role}"
        )


ALL_MAIL_ROLES = LEGACY_MAIL_ROLES + HIERARCHICAL_MAIL_ROLES


def mailbox_key(role, division=None):
    """
    The single, canonical mailbox/alert-recipient identifier for
    an account. Legacy accounts (division=None/empty) get back
    exactly their plain role string, unchanged — e.g.
    mailbox_key("Police", None) == "Police", identical to every
    mailbox key those accounts have always used. A hierarchical
    account gets a composite key — e.g.
    mailbox_key("Police", "Dhaka") == "Dhaka Police" — which is
    what ties together its own dashboard, its own email_center()
    mailbox, and its own emergency-alert read state.
    """

    if division:
        return f"{division} {role}"

    return role


def get_role_email(role):
    """
    Returns the mailbox address for any mailbox key in
    ALL_MAIL_ROLES. Legacy roles (Administrator and the 4
    original organizations) resolve exactly as before, via
    ADMIN_EMAIL / EMERGENCY_EMAILS / EMERGENCY_DOMAINS — those
    branches are untouched. Any other key (every hierarchical
    mailbox key, e.g. "Dhaka Police") falls through to a
    generated address in the same flood.com domain, e.g.
    dhaka.police@flood.com.
    """

    if role == "Administrator":
        return ADMIN_EMAIL

    if role in EMERGENCY_EMAILS:
        return EMERGENCY_EMAILS[role]

    slug = role.lower().replace(" ", ".")

    return f"{slug}@flood.com"
