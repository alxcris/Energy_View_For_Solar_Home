"""One Energy View - entry point.

    streamlit run app.py

Sets up the top navigation (like a website, no sidebar) and runs the chosen page:
    Home                     the customer's live screen (views/home.py)
    Consumption              why the customer gets each tip
    Maintenance              PPC's operations & maintenance (O&M) team
    Account                  what we saved about this user, and how to undo it

Every page signs the user in first (components/auth.py), so the questionnaire
answers and the accepted plan belong to one account instead of one browser tab.
"""

from pathlib import Path

import streamlit as st

from components.theme import footer

HERE = Path(__file__).parent

st.set_page_config(page_title="One Energy View", page_icon=str(HERE / "assets" / "icon.svg"),
                   layout="wide")
st.logo(str(HERE / "assets" / "logo.svg"), size="large")

pages = [
    st.Page("views/home.py", title="Home", icon=":material/home:", url_path="home", default=True),
    st.Page("pages/1_Consumption_analysis.py", title="Consumption",
            icon=":material/monitoring:", url_path="consumption"),
    st.Page("pages/2_Installation_monitoring.py", title="Maintenance",
            icon=":material/engineering:", url_path="monitoring"),
    st.Page("pages/3_Account.py", title="Account", icon=":material/person:", url_path="account"),
]
st.navigation(pages, position="top").run()
footer()
