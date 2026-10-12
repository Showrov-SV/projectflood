"""Flood Monitoring & Prediction System - entry point.

Run with:  python -m streamlit run flooddashboard.py

The application code lives in the flood_app/ package (one file per
responsibility); this file only sets the page up and routes to the
right dashboard."""

import streamlit as st

from flood_app.dashboard_division import division_admin_dashboard
from flood_app.dashboard_org import organization_dashboard
from flood_app.dashboard_public import public_dashboard
from flood_app.dashboard_system_handler import system_handler_dashboard
from flood_app.database import init_database
from flood_app.datasets import ensure_dataset_state
from flood_app.sidebar import sidebar


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Flood Monitoring & Prediction System",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# DATABASE SETUP (creates tables / seeds accounts if missing)
# ============================================================

init_database()


# ============================================================
# MAIN APPLICATION
# ============================================================

def main():

    # --------------------------------------------------------
    # Initialize session state
    # --------------------------------------------------------

    if "logged_in" not in st.session_state:

        st.session_state.logged_in = False

    if "username" not in st.session_state:

        st.session_state.username = None

    if "role" not in st.session_state:

        st.session_state.role = None

    if "show_emergency_panel" not in st.session_state:

        st.session_state.show_emergency_panel = False

    if "admin_2fa_pending" not in st.session_state:

        st.session_state.admin_2fa_pending = False

    if "admin_2fa_username" not in st.session_state:

        st.session_state.admin_2fa_username = None

    if "division" not in st.session_state:

        st.session_state.division = None

    if "area" not in st.session_state:

        st.session_state.area = None

    ensure_dataset_state()

    # --------------------------------------------------------
    # Sidebar
    # --------------------------------------------------------

    sidebar()

    # --------------------------------------------------------
    # AUTHORIZED PORTALS
    # --------------------------------------------------------

    if st.session_state.logged_in:

        role = st.session_state.role

        division = st.session_state.get("division")

        if role == "System Handler":

            system_handler_dashboard()

        elif role == "Division Admin":

            division_admin_dashboard(division)

        elif role == "Hospital":

            organization_dashboard(
                "Hospital",
                division
            )

        elif role == "Fire Service":

            organization_dashboard(
                "Fire Service",
                division
            )

        elif role == "Police":

            organization_dashboard(
                "Police",
                division
            )

        elif role == "Municipality":

            organization_dashboard(
                "Municipality",
                division
            )

    # --------------------------------------------------------
    # PUBLIC PORTAL
    # --------------------------------------------------------

    else:

        public_dashboard()



# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
