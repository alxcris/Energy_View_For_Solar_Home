"""The app's shared look: theme, fonts, cards, badges and the chart template.

Every page calls setup_page() first, so they all look the same. Colours are
defined once in config.COLORS / config.UI, published here as CSS variables
(--ev-*) and reused by every component, including the animated ones.
"""

import html

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from config import COLORS, SERIES, UI

FONT = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"


def _css_vars() -> str:
    """config.UI + config.COLORS as CSS variables, so the CSS below stays plain."""
    pairs = {f"--ev-{k.replace('_', '-')}": v for k, v in UI.items()}
    pairs.update({f"--ev-c-{k.replace('_', '-')}": v for k, v in COLORS.items()})
    pairs.update({f"--ev-s{i}": v for i, v in enumerate(SERIES)})
    return ":root{" + ";".join(f"{k}:{v}" for k, v in pairs.items()) + "}"


_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea, select {
    font-family: var(--ev-font) !important;
    -webkit-font-smoothing: antialiased;
}
.stApp { background: var(--ev-bg); }
/* Hide only the deploy / running / menu cluster - NOT the whole toolbar, because
   this Streamlit build renders the top navigation inside it. */
#MainMenu, footer, [data-testid="stAppDeployButton"], [data-testid="stStatusWidget"],
[data-testid="stToolbarActions"], [data-testid="stMainMenu"] { display: none !important; }
[data-testid="stToolbar"] { display: flex !important; }

/* ---------- top bar: white, full width, logo left, navigation beside it ---------- */
header[data-testid="stHeader"] {
    background: var(--ev-card); border-bottom: 1px solid var(--ev-border);
    box-shadow: 0 1px 3px rgba(15,28,46,.04); height: 3.9rem;
}
header[data-testid="stHeader"] img[data-testid="stHeaderLogo"],
[data-testid="stHeaderLogo"] { height: 1.95rem !important; max-height: 1.95rem !important; }
[data-testid="stTopNav"] a, [data-testid="stTopNavLink"] {
    border-radius: 10px; padding: .34rem .9rem; font-weight: 600; font-size: .95rem;
    color: var(--ev-muted) !important; transition: background .15s ease, color .15s ease;
}
[data-testid="stTopNav"] a:hover, [data-testid="stTopNavLink"]:hover {
    background: var(--ev-grid); color: var(--ev-text) !important;
}
[data-testid="stTopNav"] a[aria-current="page"], [data-testid="stTopNavLink"][aria-current="page"],
[data-testid="stTopNavLink"].active {
    background: var(--ev-primary-soft); color: var(--ev-primary-dark) !important;
}
.block-container { padding-top: 5.4rem; padding-bottom: 2.5rem; max-width: 1680px;
                   padding-left: 2.5rem; padding-right: 2.5rem; }

/* ---------- type ---------- */
h1, h2, h3, h4 { color: var(--ev-text); font-weight: 700 !important; letter-spacing: -.021em; }
h3 { font-size: 1.3rem !important; margin-top: .5rem; }
[data-testid="stCaptionContainer"] { color: var(--ev-muted); font-size: .93rem; }
.ev-num { font-variant-numeric: tabular-nums; }

/* ---------- section header ---------- */
.ev-sec { display: flex; align-items: baseline; gap: 12px; margin: 26px 0 10px;
          flex-wrap: wrap; }
.ev-sec-t { font-size: 1.28rem; font-weight: 700; color: var(--ev-text); letter-spacing: -.02em; }
.ev-sec-c { font-size: .95rem; color: var(--ev-muted); }
.ev-rule { height: 1px; background: var(--ev-border); margin: 6px 0 14px; border: 0; }

/* ---------- hero ---------- */
.ev-hero {
    position: relative; overflow: hidden; border-radius: 22px; padding: 32px 36px 34px;
    margin: 8px 0 20px; box-shadow: var(--ev-shadow-lg);
    background: linear-gradient(118deg, var(--ev-hero-from) 0%, var(--ev-hero-mid) 52%,
                var(--ev-hero-to) 100%);
}
.ev-hero::after {
    content: ""; position: absolute; right: -70px; top: -110px; width: 340px; height: 340px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(245,158,11,.34) 0%, rgba(245,158,11,0) 68%);
}
.ev-hero::before {
    content: ""; position: absolute; left: 32%; bottom: -170px; width: 300px; height: 300px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(124,58,237,.26) 0%, rgba(124,58,237,0) 70%);
}
.ev-eyebrow {
    position: relative; z-index: 1; font-size: .72rem; font-weight: 700; letter-spacing: .12em;
    text-transform: uppercase; color: var(--ev-hero-eyebrow); margin-bottom: 8px;
}
.ev-hero-title {
    position: relative; z-index: 1; font-size: 2.3rem; font-weight: 700; color: var(--ev-hero-text);
    line-height: 1.16; letter-spacing: -.025em;
}
.ev-hero-sub {
    position: relative; z-index: 1; font-size: 1.1rem; color: var(--ev-hero-sub);
    margin-top: 10px; max-width: 900px; line-height: 1.5;
}
.ev-hero-meta { position: relative; z-index: 1; display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
.ev-hero-meta span {
    font-size: .9rem; font-weight: 600; color: rgba(255,255,255,.92); padding: 5px 11px;
    border-radius: 999px; background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.16);
    backdrop-filter: blur(2px);
}

/* ---------- status strip + chips ---------- */
.ev-status { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 2px 0 12px; }
.ev-item {
    display: inline-flex; align-items: center; gap: 8px; padding: 7px 14px; border-radius: 999px;
    background: var(--ev-card); border: 1px solid var(--ev-border); font-size: .88rem;
    font-weight: 600; color: var(--ev-text); box-shadow: 0 1px 2px rgba(15,28,46,.04);
}
.ev-item em { color: var(--ev-muted); font-style: normal; font-weight: 500; }
.ev-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ev-faint); flex: none; }
.ev-dot.ok { background: var(--ev-ok); }
.ev-dot.warn { background: var(--ev-warn); }
.ev-dot.err { background: var(--ev-danger); }
.ev-dot.live { background: var(--ev-ok); animation: ev-ping 1.9s ease-out infinite; }
@keyframes ev-ping {
    0%   { box-shadow: 0 0 0 0 rgba(14,159,110,.55); }
    70%  { box-shadow: 0 0 0 7px rgba(14,159,110,0); }
    100% { box-shadow: 0 0 0 0 rgba(14,159,110,0); }
}
.ev-chip {
    display: inline-flex; align-items: center; gap: 8px; padding: 5px 12px; border-radius: 999px;
    background: var(--ev-card); border: 1px solid var(--ev-border); font-size: .8rem; font-weight: 600;
    color: var(--ev-text); margin-bottom: 10px;
}
.ev-chip i { width: 8px; height: 8px; border-radius: 50%; background: var(--dot); display: inline-block; }
.ev-chip span { color: var(--ev-muted); font-weight: 500; }

.ev-badge {
    display: inline-flex; align-items: center; gap: 5px; padding: 4px 11px; border-radius: 8px;
    font-size: .79rem; font-weight: 700; letter-spacing: .02em; text-transform: uppercase;
}
.ev-badge.ok   { background: var(--ev-ok-soft);      color: var(--ev-ok-dark); }
.ev-badge.warn { background: var(--ev-warn-soft);    color: #9A6400; }
.ev-badge.err  { background: var(--ev-danger-soft);  color: #B3282C; }
.ev-badge.info { background: var(--ev-info-soft);    color: #1D4ED8; }
.ev-badge.accent { background: var(--ev-accent-soft); color: #6029C1; }
.ev-badge.cool { background: var(--ev-cool-soft);    color: #0B6E87; }
.ev-badge.mute { background: var(--ev-grid);         color: var(--ev-muted); }

/* Inverter brand chip on the maintenance alert cards; one visible proof that
   the fleet mixes Huawei, Fronius and SMA in one view. */
.ev-brand {
    display: inline-flex; align-items: center; padding: 3px 9px; border-radius: 6px;
    font-size: .74rem; font-weight: 700; letter-spacing: .03em; text-transform: uppercase;
    background: var(--ev-grid); color: var(--ev-muted); margin-left: 2px;
    border: 1px solid rgba(0,0,0,.05);
}

/* ---------- KPI cards ---------- */
.ev-kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
               gap: 16px; margin: 6px 0 20px; }
.ev-kpi {
    position: relative; overflow: hidden; background: var(--ev-card); border: 1px solid var(--ev-border);
    border-radius: 17px; padding: 18px 20px 16px; box-shadow: var(--ev-shadow);
    animation: ev-rise .3s ease both;
}
.ev-kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); }
.ev-kpi-label { display: flex; align-items: center; gap: 8px; font-size: .78rem; font-weight: 700;
                letter-spacing: .07em; text-transform: uppercase; color: var(--ev-muted); }
.ev-kpi-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex: none; }
.ev-kpi-value { font-size: 2.05rem; font-weight: 700; color: var(--ev-text); margin-top: 6px;
                line-height: 1.1; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }
.ev-kpi-value small { font-size: 1.05rem; font-weight: 600; color: var(--ev-muted); margin-left: 3px; }
.ev-kpi-sub { font-size: .88rem; color: var(--ev-muted); margin-top: 5px; }
.ev-delta { display: inline-flex; align-items: center; gap: 3px; font-size: .8rem; font-weight: 700;
            padding: 2px 7px; border-radius: 999px; margin-left: 7px; vertical-align: middle; }
.ev-delta.up   { background: var(--ev-primary-soft); color: var(--ev-primary-dark); }
.ev-delta.down { background: var(--ev-danger-soft); color: #B3282C; }
.ev-delta.flat { background: var(--ev-grid); color: var(--ev-muted); }
@keyframes ev-rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

/* ---------- Streamlit widgets ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, .stPageLink a {
    border-radius: 11px !important; font-weight: 600; padding: .55rem 1.25rem;
    font-size: 1rem;
    transition: transform .06s ease, box-shadow .15s ease, background .15s ease, filter .06s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
    transform: translateY(-1px); box-shadow: 0 6px 16px rgba(15,28,46,.10);
}
.stButton > button[kind="primary"] { box-shadow: 0 6px 16px var(--ev-primary-shadow); }

/* A colour per action, so the three choices under a tip are told apart at a
   glance instead of three near-identical grey buttons. Streamlit tags each
   widget's container with st-key-<key>, which is what these hook onto. */
[class*="st-key-acc_"] > div button { background: var(--ev-primary) !important;
    border-color: var(--ev-primary) !important; color: #fff !important; }
[class*="st-key-later_"] > div button { color: var(--ev-warn-dark) !important;
    border-color: var(--ev-warn) !important; background: var(--ev-warn-soft) !important; }
[class*="st-key-later_"] > div button:hover { filter: brightness(.98); }
[class*="st-key-dis_"] > div button { color: var(--ev-danger-dark) !important;
    border-color: var(--ev-danger) !important; background: var(--ev-danger-soft) !important; }
[class*="st-key-dis_"] > div button:hover { filter: brightness(.98); }
/* O&M actions */
[class*="st-key-ack_"] > div button { color: var(--ev-info-dark) !important;
    border-color: var(--ev-info) !important; background: var(--ev-info-soft) !important; }
[class*="st-key-wo_"] > div button { background: var(--ev-primary) !important;
    border-color: var(--ev-primary) !important; color: #fff !important; }

/* The press has to be felt before the server answers: these react to the finger,
   not to the rerun. Without them a 150 ms round trip reads as a frozen button. */
.stButton > button:active, .stDownloadButton > button:active,
.stFormSubmitButton > button:active, [data-testid="stButtonGroup"] button:active,
button[data-variant="pills"]:active, [data-baseweb="segmented-control"] button:active {
    transform: translateY(0) scale(.975) !important;
    filter: brightness(.95);
    box-shadow: inset 0 2px 5px rgba(15,28,46,.16) !important;
    transition-duration: .02s !important;
}
button[data-variant="pills"], [data-testid="stButtonGroup"] button {
    transition: transform .06s ease, filter .06s ease, background .15s ease;
}
/* and the whole app says it is working, since Streamlit's own indicator is hidden */
[data-testid="stApp"][data-test-script-state="running"]::before,
[data-testid="stApp"][data-test-script-state="rerunRequested"]::before {
    content: ""; position: fixed; inset: 0 0 auto 0; height: 3px; z-index: 9999;
    background: linear-gradient(90deg, rgba(14,159,110,0), var(--ev-primary), rgba(14,159,110,0));
    background-size: 45% 100%; background-repeat: no-repeat;
    animation: ev-bar .9s linear infinite;
}
@keyframes ev-bar { from { background-position: -45% 0; } to { background-position: 145% 0; } }
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {
    background: var(--ev-card); border-color: var(--ev-border) !important; border-radius: 16px;
    box-shadow: var(--ev-shadow);
}
[data-testid="stMetric"] {
    background: var(--ev-card); border: 1px solid var(--ev-border); border-radius: 15px;
    padding: 13px 16px; box-shadow: var(--ev-shadow);
}
[data-testid="stMetricValue"] { font-weight: 700; color: var(--ev-text); }
[data-testid="stPlotlyChart"] {
    background: var(--ev-card); border: 1px solid var(--ev-border); border-radius: 16px;
    padding: 8px; box-shadow: var(--ev-shadow); box-sizing: border-box;
}
[data-testid="stDataFrame"] { border-radius: 13px; overflow: hidden; box-shadow: var(--ev-shadow); }
[data-testid="stExpander"] details { background: var(--ev-card); border-radius: 13px; border-color: var(--ev-border); }
[data-testid="stAlert"] { border-radius: 13px; }
[data-testid="stSlider"] [data-baseweb="slider"] { padding-top: 4px; }

/* ---------- energy flow diagram ---------- */
.ev-flow { position: relative; background: var(--ev-card); border: 1px solid var(--ev-border);
           border-radius: 18px; padding: 4px 8px 0; box-shadow: var(--ev-shadow); }
.ev-flow svg { width: 100%; height: auto; display: block; }
.ev-flow .track { fill: none; stroke: var(--ev-track); stroke-width: 8; stroke-linecap: round; }
.ev-flow .beam { fill: none; stroke-linecap: round; opacity: .22; }
.ev-flow .pulse { fill: none; stroke-linecap: round; stroke-dasharray: 13 23;
                  animation: ev-dash 1.2s linear infinite; }
.ev-flow .pulse.rev { animation-direction: reverse; }
@keyframes ev-dash { to { stroke-dashoffset: -36; } }
.ev-flow .box { fill: var(--ev-surface); stroke: var(--ev-border); stroke-width: 1.2; }
.ev-flow .box.off { fill: var(--ev-bg); stroke-dasharray: 4 4; }
.ev-flow .box.fault { stroke: var(--ev-danger); stroke-width: 1.8; }
.ev-flow .t-label { font: 600 11.5px var(--ev-font); fill: var(--ev-muted); letter-spacing: .04em;
                    text-transform: uppercase; }
.ev-flow .t-val { font: 700 19px var(--ev-font); fill: var(--ev-text); font-variant-numeric: tabular-nums;
                  letter-spacing: -.02em; }
.ev-flow .t-sub { font: 500 11.5px var(--ev-font); fill: var(--ev-muted); }
.ev-flow .t-pill { font: 700 12px var(--ev-font); font-variant-numeric: tabular-nums; }
.ev-flow .t-hub { font: 700 13px var(--ev-font); fill: var(--ev-text); }
.ev-flow .t-hub-sub { font: 600 10px var(--ev-font); fill: var(--ev-muted); letter-spacing: .06em; }
.ev-flow .rays { animation: ev-spin 30s linear infinite; }
@keyframes ev-spin { to { transform: rotate(360deg); } }
.ev-flow .glow { animation: ev-breathe 2.6s ease-in-out infinite; }
@keyframes ev-breathe { 0%,100% { opacity: .35; } 50% { opacity: .85; } }
.ev-flow .ring-arc { transition: stroke-dasharray .4s ease; }
.ev-flow-legend { display: flex; gap: 18px; flex-wrap: wrap; padding: 4px 14px 12px;
                  font-size: .88rem; color: var(--ev-muted); font-weight: 500; }
.ev-flow-legend b { color: var(--ev-text); font-weight: 600; }
.ev-flow-legend i { width: 9px; height: 9px; border-radius: 3px; display: inline-block;
                    margin-right: 5px; background: var(--c); }

/* ---------- panel / string cards ---------- */
.ev-panels { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 16px; }
.ev-panel { position: relative; overflow: hidden; background: var(--ev-card); border: 1px solid var(--ev-border);
            border-radius: 17px; padding: 18px 20px; box-shadow: var(--ev-shadow); }
.ev-panel.alarm { border-color: var(--ev-danger); background: linear-gradient(0deg, var(--ev-danger-soft), var(--ev-card) 60%); }
.ev-panel.watch { border-color: var(--ev-warn); }
.ev-panel-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ev-panel-name { font-size: 1.05rem; font-weight: 700; color: var(--ev-text); }
.ev-panel-sub { font-size: .85rem; color: var(--ev-muted); margin-top: 1px; }
.ev-panel-val { font-size: 1.6rem; font-weight: 700; color: var(--ev-text); margin-top: 12px;
                font-variant-numeric: tabular-nums; letter-spacing: -.02em; }
.ev-panel-val small { font-size: .95rem; font-weight: 600; color: var(--ev-muted); margin-left: 3px; }
.ev-panel-bar { position: relative; height: 9px; border-radius: 999px; background: var(--ev-track);
                margin: 9px 0 7px; overflow: hidden; }
.ev-panel-bar i { position: absolute; inset: 0 auto 0 0; border-radius: 999px; background: var(--bc);
                  width: var(--w); transition: width .5s ease; }
.ev-panel-bar u { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--ev-faint);
                  left: var(--exp); }
.ev-panel-foot { display: flex; justify-content: space-between; font-size: .84rem; color: var(--ev-muted); }
.ev-cells { display: grid; grid-template-columns: repeat(6, 1fr); gap: 3px; margin-top: 10px; }
.ev-cells b { display: block; height: 17px; border-radius: 3px; background: var(--cell);
              box-shadow: inset 0 0 0 1px rgba(255,255,255,.35); }
.ev-panel.live .ev-cells b { animation: ev-shimmer 3.4s ease-in-out infinite; }
.ev-cells b:nth-child(2n) { animation-delay: .35s; }
.ev-cells b:nth-child(3n) { animation-delay: .7s; }
@keyframes ev-shimmer { 0%,100% { filter: brightness(1); } 50% { filter: brightness(1.18); } }
.ev-panel.alarm::after {
    content: ""; position: absolute; inset: 0; border-radius: 15px; pointer-events: none;
    box-shadow: inset 0 0 0 2px rgba(229,72,77,.5); animation: ev-breathe 1.8s ease-in-out infinite;
}

/* ---------- alert cards ---------- */
.ev-alert { display: flex; gap: 12px; background: var(--ev-card); border: 1px solid var(--ev-border);
            border-left: 4px solid var(--sev); border-radius: 13px; padding: 13px 15px; box-shadow: var(--ev-shadow); }
.ev-alert-h { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.ev-alert-t { font-size: 1.08rem; font-weight: 700; color: var(--ev-text); }
.ev-alert-b { font-size: .97rem; color: var(--ev-text); opacity: .82; margin: 5px 0 7px; line-height: 1.45; }
.ev-alert-m { display: flex; gap: 20px; flex-wrap: wrap; font-size: .87rem; color: var(--ev-muted); }
.ev-alert-m b { color: var(--ev-text); font-variant-numeric: tabular-nums; }

/* ---------- recommendations + plan ---------- */
.ev-rec-title { font-size: 1.12rem; font-weight: 700; color: var(--ev-text); letter-spacing: -.01em; }
.ev-rec-body { color: var(--ev-text); opacity: .82; margin: 8px 0 12px; font-size: .98rem; line-height: 1.55; }
.ev-pill { display: inline-block; padding: 6px 14px; border-radius: 999px; font-weight: 700;
           font-size: .88rem; background: var(--ev-primary-soft); color: var(--ev-primary-dark); }
.ev-plan { background: var(--ev-plan-bg); border: 1px solid var(--ev-border); border-radius: 15px;
           padding: 16px 18px; margin-bottom: 12px; }
.ev-plan-big { font-size: 2.1rem; font-weight: 700; color: var(--ev-primary-dark);
               font-variant-numeric: tabular-nums; letter-spacing: -.03em; }
.ev-plan ul { margin: 10px 0 0; padding-left: 1.1rem; color: var(--ev-text); font-size: .97rem; }

/* ---------- error / empty states ---------- */
.ev-err { display: flex; gap: 12px; align-items: flex-start; background: var(--ev-card);
          border: 1px solid var(--ev-border); border-left: 4px solid var(--tone); border-radius: 13px;
          padding: 14px 16px; box-shadow: var(--ev-shadow); margin: 6px 0 12px; }
.ev-err-i { width: 26px; height: 26px; border-radius: 8px; background: var(--tone-soft); flex: none;
            display: grid; place-items: center; font-size: .95rem; }
.ev-err-t { font-size: 1.05rem; font-weight: 700; color: var(--ev-text); }
.ev-err-d { font-size: .94rem; color: var(--ev-muted); margin-top: 3px; line-height: 1.45; }
.ev-err-h { font-size: .83rem; color: var(--ev-text); margin-top: 7px; }
.ev-err-h code { background: var(--ev-grid); padding: 1px 6px; border-radius: 5px; font-size: .82rem; }

/* ---------- auth ---------- */
.ev-auth-head { text-align: center; margin: 8px 0 4px; }
.ev-auth-head h2 { font-size: 1.5rem; margin-bottom: 4px; }
.ev-auth-head p { color: var(--ev-muted); font-size: .92rem; }
.ev-demo { background: var(--ev-surface); border: 1px dashed var(--ev-border); border-radius: 12px;
           padding: 10px 13px; font-size: .82rem; color: var(--ev-muted); }
.ev-demo b { color: var(--ev-text); }

/* ---------- skeleton ---------- */
.ev-skel { height: 86px; border-radius: 15px; background: linear-gradient(90deg,
           var(--ev-grid) 25%, var(--ev-card) 37%, var(--ev-grid) 63%);
           background-size: 400% 100%; animation: ev-slide 1.4s ease infinite; }
@keyframes ev-slide { from { background-position: 100% 0; } to { background-position: 0 0; } }

/* ---------- footer ---------- */
.ev-footer { max-width: 1680px; margin: 30px auto 0; padding: 16px 0 6px; border-top: 1px solid var(--ev-border);
             display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
             color: var(--ev-muted); font-size: .82rem; }
.ev-footer b { color: var(--ev-text); font-weight: 600; }

/* Anyone who asked their system to reduce motion gets the same app, standing still. */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
}
"""


def _style() -> str:
    """The whole stylesheet: colour variables first, then the rules."""
    return "<style>" + _css_vars() + _CSS.replace("var(--ev-font)", FONT) + "</style>"


def _register_plotly_template() -> None:
    tpl = go.layout.Template(pio.templates["plotly_white"])
    tpl.layout.update(
        font=dict(family=FONT, size=12.5, color=UI["text"]),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=SERIES,
        xaxis=dict(gridcolor=UI["grid"], zeroline=False, linecolor=UI["border"],
                   ticklabelstandoff=6),
        yaxis=dict(gridcolor=UI["grid"], zeroline=False, linecolor=UI["border"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
        hoverlabel=dict(bgcolor="white", bordercolor=UI["border"],
                        font=dict(family=FONT, color=UI["text"], size=12)),
        bargap=0.3,
    )
    pio.templates["energy_pro"] = tpl
    pio.templates.default = "energy_pro"


def setup_page(title: str) -> None:
    """Configures the page and applies the theme. Call it first on every page."""
    try:
        st.set_page_config(page_title=f"{title} | One Energy View", layout="wide")
    except Exception:
        pass  # already configured by app.py - nothing to do
    st.markdown(_style(), unsafe_allow_html=True)
    _register_plotly_template()


def hero(title: str, subtitle: str = "", eyebrow: str = "",
         meta: list[str] | None = None) -> None:
    chips = "".join(f"<span>{html.escape(m)}</span>" for m in (meta or []))
    st.markdown(
        '<div class="ev-hero">'
        + (f'<div class="ev-eyebrow">{html.escape(eyebrow)}</div>' if eyebrow else "")
        + f'<div class="ev-hero-title">{html.escape(title)}</div>'
        + (f'<div class="ev-hero-sub">{html.escape(subtitle)}</div>' if subtitle else "")
        + (f'<div class="ev-hero-meta">{chips}</div>' if chips else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def section(title: str, caption: str = "") -> None:
    """A section header: title on the left, one explanatory line beside it."""
    st.markdown(
        f'<div class="ev-sec"><span class="ev-sec-t">{html.escape(title)}</span>'
        + (f'<span class="ev-sec-c">{html.escape(caption)}</span>' if caption else "")
        + "</div>", unsafe_allow_html=True)


def badge(text: str, tone: str = "mute") -> str:
    """Returns the HTML of a small status badge. tone: ok | warn | err | info | mute."""
    return f'<span class="ev-badge {tone}">{html.escape(text)}</span>'


def kpi_row(items: list[dict]) -> None:
    """A row of cards.

    Each item: label, value, unit (opt.), sub (opt.), color (COLORS key or hex),
    delta (opt. text) and delta_dir (up | down | flat).
    """
    cards = []
    for it in items:
        color = COLORS.get(it.get("color", ""), it.get("color", UI["primary"]))
        unit = f"<small>{html.escape(str(it['unit']))}</small>" if it.get("unit") else ""
        sub = f'<div class="ev-kpi-sub">{html.escape(str(it["sub"]))}</div>' if it.get("sub") else ""
        delta = ""
        if it.get("delta"):
            d = it.get("delta_dir", "flat")
            delta = f'<span class="ev-delta {d}">{html.escape(str(it["delta"]))}</span>'
        cards.append(
            f'<div class="ev-kpi" style="--accent:{color}">'
            f'<div class="ev-kpi-label"><span class="ev-kpi-dot"></span>{html.escape(it["label"])}</div>'
            f'<div class="ev-kpi-value">{html.escape(str(it["value"]))}{unit}{delta}</div>{sub}</div>'
        )
    st.markdown(f'<div class="ev-kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def footer() -> None:
    """One line at the bottom of every page: what this is and who built it."""
    st.markdown(
        '<div class="ev-footer"><span><b>One Energy View</b> &middot; production, consumption '
        'and storage in one place</span><span>Chief Bit &middot; AI Validation Bootcamp &middot; '
        'Challenge 1 by PPC</span></div>',
        unsafe_allow_html=True,
    )


def source_chip(use_ml: bool) -> str:
    """Small pill saying where the numbers on the page come from."""
    if use_ml:
        return ('<div class="ev-chip" style="--dot:#0E9F6E"><i></i>ML pipeline data'
                '<span>&middot; expected production, alerts and tips</span></div>')
    return ('<div class="ev-chip" style="--dot:#F59E0B"><i></i>Demo data'
            '<span>&middot; run the ML pipeline for real results</span></div>')
