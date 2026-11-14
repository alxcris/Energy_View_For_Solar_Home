"""One Energy View - entry point.

    streamlit run app.py

Sets up the top navigation (like a website, no sidebar) and runs the chosen page:
    Home                     the customer's screen (views/home.py)
    Consumption analysis     why the customer gets each tip
    Installation monitoring  PPC's operations and maintenance team
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
    st.Page("pages/2_Installation_monitoring.py", title="O&M monitoring",
            icon=":material/engineering:", url_path="monitoring"),
]
st.navigation(pages, position="top").run()
footer()
