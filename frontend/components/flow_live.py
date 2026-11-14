"""The live view, drawn once and then driven entirely in the browser.

Streamlit sends every widget change to the server and redraws from the answer.
For a slider that is one round trip per step, and a drag feels like hesitation.
So the whole window of telemetry is handed to the page as data, and the
scrubber, the play button, the flow diagram, the KPI cards and the string cards
are all updated in JavaScript: dragging is immediate and nothing waits for
Python. The numbers still come from the ML pipeline - only the drawing moved.

It runs inside st.components.v1.html, which is an iframe, so the stylesheet
travels with it.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from components.flow import BOX, GRID_XY, HOME_XY, HUB, PATHS, PILLS, SOLAR_XY, BATTERY_XY
from components.theme import _style
from config import COLORS, PRICE_BUY_LEI_KWH, PRICE_SELL_LEI_KWH, UI

HEIGHT = 1280


def _samples(ts: pd.DataFrame) -> list[list]:
    """One compact row per quarter hour: the numbers the browser needs, nothing else."""
    df = ts.sort_values("timestamp").copy()
    df["day"] = df["timestamp"].dt.date
    df["prod"] = df.groupby("day")["pv_kw"].cumsum() * 0.25
    df["used"] = df.groupby("day")["load_kw"].cumsum() * 0.25
    df["self"] = df.groupby("day").apply(
        lambda g: (g[["pv_kw", "load_kw"]].min(axis=1) * 0.25).cumsum(),
        include_groups=False).reset_index(level=0, drop=True)
    # A bidirectional electric car, simulated from the same signals: it soaks up
    # the surplus that would be exported, and in the evening it gives energy back
    # to the house (V2H) instead of buying from the grid - the "car as storage"
    # idea, shown rather than told. Only drawn when the household owns an EV.
    car_cap, car_kw_max, car_soc = 55.0, 7.0, 60.0
    rows = []
    for r in df.itertuples():
        soc = getattr(r, "battery_soc", None)
        exp = getattr(r, "expected_kw", None)
        pv = float(r.pv_kw or 0)
        grid = float(r.grid_kw or 0)
        export, imp = max(0.0, -grid), max(0.0, grid)
        car_kw = 0.0
        if export > 0.1 and car_soc < 95:
            room_kw = (95 - car_soc) / 100 * car_cap / 0.25
            car_kw = min(export, car_kw_max, room_kw)          # charge from surplus
            car_soc += car_kw * 0.25 / car_cap * 100
        elif imp > 0.1 and pv < 0.1 and car_soc > 25:
            avail_kw = (car_soc - 20) / 100 * car_cap / 0.25
            car_kw = -min(imp, car_kw_max, avail_kw)           # V2H: power the house
            car_soc += car_kw * 0.25 / car_cap * 100
        rows.append([
            r.timestamp.strftime("%a %d %b, %H:%M"),
            round(pv, 2),
            round(float(r.load_kw or 0), 2),
            round(float(getattr(r, "battery_kw", 0) or 0), 2),
            None if soc is None or pd.isna(soc) else round(float(soc), 1),
            round(grid, 2),
            None if exp is None or pd.isna(exp) else round(float(exp), 2),
            round(float(r.prod), 2), round(float(r.used), 2), round(float(r.self), 2),
            round(car_kw, 2), round(car_soc, 1),
        ])
    return rows


def _car_svg() -> str:
    """The electric car: a bidirectional storage node under the inverter."""
    c = COLORS["bar"]
    card = UI["card"]
    icon = (
        '<g stroke="' + c + '" stroke-width="2" fill="none" stroke-linejoin="round">'
        '<path d="M3 22 L7 12 H27 L31 22 V28 H3 Z"/>'
        '<circle cx="10" cy="28" r="3" fill="' + card + '"/>'
        '<circle cx="24" cy="28" r="3" fill="' + card + '"/>'
        '<path d="M15 16 h6"/></g>'
    )
    return (
        '<g id="car-group" style="display:none">'
        '<path class="track" d="M 440,266 L 440,372"/>'
        '<path class="beam" id="b-car" d="M 440,266 L 440,372" stroke="' + c + '" '
        'stroke-width="6" style="display:none"/>'
        '<path class="pulse" id="p-car" d="M 440,266 L 440,372" stroke="' + c + '" '
        'stroke-width="4" style="display:none"/>'
        '<g id="node-car"><rect class="box" id="box-car" x="352" y="372" width="176" '
        'height="104" rx="16"/>'
        '<g transform="translate(368,405)">' + icon + '</g>'
        '<text class="t-label" x="420" y="410">ELECTRIC CAR</text>'
        '<text class="t-val" x="420" y="436"><tspan id="v-car">0</tspan>'
        '<tspan class="t-sub" id="u-car" dx="4">%</tspan></text>'
        '<text class="t-sub" id="s-car" x="420" y="456"></text></g>'
        '<g id="pill-car" style="display:none">'
        '<rect x="398" y="307" width="84" height="26" rx="13" fill="' + card + '" '
        'stroke="' + c + '" stroke-opacity=".4"/>'
        '<text class="t-pill" id="pill-car-t" x="440" y="325" text-anchor="middle" '
        'fill="' + c + '">0.0 kW</text></g></g>'
    )


def _svg(has_ev: bool = False) -> str:
    """The diagram's skeleton. Everything that moves carries an id for the script."""
    sx, sy = SOLAR_XY
    bx, by = BATTERY_XY
    hx, hy = HOME_XY
    gx, gy = GRID_XY
    w, h = BOX
    cx, cy, r = HUB
    inner = r - 8

    def box(x, y, bid):
        return (f'<rect class="box" id="{bid}" x="{x}" y="{y}" width="{w}" height="{h}" rx="16"/>')

    def label(x, y, text, eid=""):
        i = f' id="{eid}"' if eid else ""
        return f'<text class="t-label"{i} x="{x + 68}" y="{y + 38}">{text}</text>'

    def value(x, y, eid, unit_id, unit):
        return (f'<text class="t-val" x="{x + 68}" y="{y + 64}"><tspan id="{eid}">0.0</tspan>'
                f'<tspan class="t-sub" id="{unit_id}" dx="4">{unit}</tspan></text>')

    def sub(x, y, eid):
        return f'<text class="t-sub" id="{eid}" x="{x + 68}" y="{y + 84}"></text>'

    def line(key, color, eid):
        return (f'<path class="track" d="{PATHS[key]}"/>'
                f'<path class="beam" id="b-{eid}" d="{PATHS[key]}" stroke="{color}" '
                f'stroke-width="6" style="display:none"/>'
                f'<path class="pulse" id="p-{eid}" d="{PATHS[key]}" stroke="{color}" '
                f'stroke-width="4" style="display:none"/>')

    def pill(key, color, eid):
        px, py = PILLS[key]
        return (f'<g id="pill-{eid}" style="display:none">'
                f'<rect x="{px - 42}" y="{py - 13}" width="84" height="26" rx="13" '
                f'fill="{UI["card"]}" stroke="{color}" stroke-opacity=".4"/>'
                f'<text class="t-pill" id="pill-{eid}-t" x="{px}" y="{py + 5}" '
                f'text-anchor="middle" fill="{color}">0.0 kW</text></g>')

    rays = "".join(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>' for x1, y1, x2, y2 in [
        (19, 0, 19, 5), (19, 33, 19, 38), (0, 19, 5, 19), (33, 19, 38, 19),
        (5.6, 5.6, 9.2, 9.2), (28.8, 28.8, 32.4, 32.4),
        (5.6, 32.4, 9.2, 28.8), (28.8, 9.2, 32.4, 5.6)])

    car = _car_svg() if has_ev else ""
    vb_h = 492 if has_ev else 400
    return f'''<div class="ev-flow"><svg viewBox="0 0 880 {vb_h}" id="flow-svg">
  {line("solar", COLORS["solar"], "solar")}
  {line("battery", COLORS["battery"], "batt")}
  {line("home", COLORS["consumption"], "home")}
  {line("grid", COLORS["grid"], "grid")}

  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{UI['card']}" stroke="{UI['border']}" stroke-width="1.2"/>
  <circle cx="{cx}" cy="{cy}" r="{inner}" fill="none" stroke="{UI['track']}" stroke-width="6"/>
  <circle id="hub-arc" cx="{cx}" cy="{cy}" r="{inner}" fill="none" stroke="{UI['primary']}"
          stroke-width="6" stroke-linecap="round" stroke-dasharray="0 999"
          transform="rotate(-90 {cx} {cy})"/>
  <path d="M{cx + 1} {cy - 36} L{cx - 9} {cy - 20} h6.5 l-1.6 11 L{cx + 9} {cy - 25} h-6.5z"
        fill="{COLORS['solar']}"/>
  <text class="t-hub" id="hub-pct" x="{cx}" y="{cy + 14}" text-anchor="middle">0%</text>
  <text class="t-hub-sub" x="{cx}" y="{cy + 30}" text-anchor="middle">SELF-USE</text>
  <text class="t-label" x="{cx}" y="{cy - r - 14}" text-anchor="middle">Inverter</text>

  <g id="node-solar">{box(sx, sy, "box-solar")}
    <g transform="translate({sx + 16},{sy + 33})">
      <g id="sun-rays" style="transform-origin:19px 19px">
        <g stroke="{COLORS['solar']}" stroke-width="2.1" stroke-linecap="round">{rays}</g></g>
      <circle id="sun-core" cx="19" cy="19" r="8.6" fill="{COLORS['solar']}"/></g>
    {label(sx, sy, "SOLAR PANELS")}{value(sx, sy, "v-solar", "u-solar", "kW")}{sub(sx, sy, "s-solar")}</g>

  <g id="node-batt">{box(bx, by, "box-batt")}
    <g transform="translate({bx + 16},{by + 33})" id="bat-icon">
      <rect x="15.5" y="2" width="7" height="4" rx="1.5" fill="{COLORS['battery']}"/>
      <rect x="9" y="5" width="20" height="29" rx="6" fill="{UI['card']}"
            stroke="{COLORS['battery']}" stroke-width="2"/>
      <rect id="bat-fill" x="12" y="20" width="14" height="12" rx="3.5" fill="{COLORS['battery']}"/>
      <path id="bat-bolt" d="M20 13 L13.5 22 h4.2 l-1 7 6.5-9.5h-4.2z" fill="{UI['card']}"
            class="glow" style="display:none"/></g>
    {label(bx, by, "BATTERY")}{value(bx, by, "v-batt", "u-batt", "%")}{sub(bx, by, "s-batt")}</g>

  <g id="node-home">{box(hx, hy, "box-home")}
    <g transform="translate({hx + 16},{hy + 33})">
      <path d="M3 18.5 L19 4 L35 18.5 V35 H3 Z" fill="{UI['card']}"
            stroke="{COLORS['consumption']}" stroke-width="2" stroke-linejoin="round"/>
      <rect id="home-win" x="14.5" y="23" width="9" height="12" rx="1.6"
            fill="{COLORS['consumption']}"/></g>
    {label(hx, hy, "YOUR HOME")}{value(hx, hy, "v-home", "u-home", "kW")}{sub(hx, hy, "s-home")}</g>

  <g id="node-grid">{box(gx, gy, "box-grid")}
    <g transform="translate({gx + 16},{gy + 33})">
      <g id="grid-icon" stroke="{COLORS['grid']}" stroke-width="2" fill="none" stroke-linecap="round"
         stroke-linejoin="round"><path d="M7 35 L19 4 L31 35"/><path d="M11.5 23 H26.5"/>
         <path d="M14 15 H24"/><path d="M4 11 H34"/></g></g>
    {label(gx, gy, "GRID")}{value(gx, gy, "v-grid", "u-grid", "kW")}{sub(gx, gy, "s-grid")}</g>

  {pill("solar", COLORS["solar"], "solar")}
  {pill("battery", COLORS["battery"], "batt")}
  {pill("home", COLORS["consumption"], "home")}
  {pill("grid", COLORS["grid"], "grid")}
  {car}
</svg></div>'''


_EXTRA_CSS = """
<style>
html, body { margin: 0; padding: 0; background: transparent; }
.wrap { max-width: 1480px; margin: 0 auto; }
.ev-flow svg { max-width: 1200px; margin: 0 auto; }
.ctl { display: flex; align-items: center; gap: 18px; margin: 2px 0 14px; }
.ctl button {
    border: 1px solid var(--ev-border); background: var(--ev-card); color: var(--ev-text);
    font: 600 1rem var(--ev-font); padding: .58rem 1.3rem; border-radius: 11px; cursor: pointer;
    transition: transform .06s ease, filter .06s ease, box-shadow .15s ease; white-space: nowrap;
}
.ctl button:hover { box-shadow: 0 4px 12px rgba(15,28,46,.10); }
.ctl button:active { transform: scale(.97); filter: brightness(.95); }
.ctl button.on { background: var(--ev-primary); border-color: var(--ev-primary); color: #fff; }
#scrub { -webkit-appearance: none; appearance: none; flex: 1; height: 8px; border-radius: 999px;
         background: var(--ev-track); outline: none; cursor: pointer; }
#scrub::-webkit-slider-thumb {
    -webkit-appearance: none; width: 24px; height: 24px; border-radius: 50%;
    background: var(--ev-primary); border: 3px solid #fff; box-shadow: 0 1px 4px rgba(15,28,46,.3);
}
#scrub::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%;
    background: var(--ev-primary); border: 3px solid #fff; }
/* the strings stay on one row, so the block keeps a predictable height */
#panels { grid-template-columns: repeat(auto-fit, minmax(228px, 1fr)); }
.when { font: 600 .95rem var(--ev-font); color: var(--ev-text); min-width: 170px; text-align: right; }
.when em { color: var(--ev-muted); font-style: normal; font-weight: 500; }
</style>
"""

_SCRIPT = """
<script>
const D = __DATA__;
const S = D.samples, L = D.layout, C = D.colors;
const $ = id => document.getElementById(id);
const MIN = 0.05;
let idx = S.length - 1, playing = false, timer = null;

function lineFor(key, color, kw, reverse, peak) {
  $('b-' + key).setAttribute('stroke', color); $('p-' + key).setAttribute('stroke', color);
  const beam = $('b-' + key), pulse = $('p-' + key);
  if (kw < MIN) { beam.style.display = 'none'; pulse.style.display = 'none'; return; }
  const ratio = Math.max(0.06, Math.min(1, kw / peak));
  const width = 4 + 7 * ratio;
  const speed = Math.max(0.55, Math.min(2.3, 2.3 - 1.75 * ratio));
  beam.style.display = ''; pulse.style.display = '';
  beam.setAttribute('stroke-width', width.toFixed(1));
  pulse.setAttribute('stroke-width', (width * 0.55).toFixed(1));
  pulse.style.animationDuration = speed.toFixed(2) + 's';
  pulse.style.animationDirection = reverse ? 'reverse' : 'normal';
}
function pillFor(key, kw, color) {
  const g = $('pill-' + key);
  if (kw < MIN) { g.style.display = 'none'; return; }
  g.style.display = '';
  const t = $('pill-' + key + '-t');
  t.textContent = kw.toFixed(1) + ' kW';
  if (color) { t.setAttribute('fill', color); g.querySelector('rect').setAttribute('stroke', color); }
}
function narrative(pv, load, batt, grid, soc) {
  if (pv < MIN) {
    const src = batt < -MIN ? 'the battery is running the house'
      : grid > MIN ? 'the house is running on the grid' : 'the house is using almost nothing';
    return 'The panels are not producing right now, so ' + src + '.';
  }
  const cover = load > 0.01 ? Math.min(pv, load) / load * 100 : 100;
  const parts = ['your panels are producing ' + pv.toFixed(1) + ' kW and cover '
                 + cover.toFixed(0) + '% of what the house uses'];
  if (batt > MIN) parts.push(batt.toFixed(1) + ' kW is going into the battery'
                             + (soc !== null ? ' (' + soc.toFixed(0) + '% full)' : ''));
  else if (batt < -MIN) parts.push('the battery is adding ' + Math.abs(batt).toFixed(1) + ' kW');
  if (grid < -MIN) parts.push('the surplus of ' + Math.abs(grid).toFixed(1) + ' kW is sold to the grid');
  else if (grid > MIN) parts.push('the missing ' + grid.toFixed(1) + ' kW comes from the grid');
  const t = parts.join(', ') + '.';
  return t[0].toUpperCase() + t.slice(1);
}
function strings(pv, expected) {
  const n = L.strings.length;
  const deficit = Math.max(0, (expected === null ? 0 : expected) - pv);
  const fault = L.array_fault && deficit > 0.05 && expected !== null;
  return L.strings.map(s => {
    const exp = (expected === null ? pv : expected) * s.share;
    let cur;
    if (fault) cur = Math.max(0, exp - deficit * (s.faulty ? 0.78 : 0.22 / Math.max(1, n - 1)));
    else cur = pv * s.share * s.jitter;
    const ratio = exp > 0.05 ? cur / exp : null;
    let state, note;
    if (exp <= 0.05) { state = 'idle'; note = 'no sun on it right now'; }
    else if (ratio >= 0.92) { state = 'ok'; note = 'producing as expected'; }
    else if (ratio >= 0.75) { state = 'watch'; note = ((1 - ratio) * 100).toFixed(0) + '% below expected'; }
    else { state = 'alarm'; note = 'only ' + (ratio * 100).toFixed(0) + '% of what the weather allows'; }
    return { s, cur, exp, ratio, state, note };
  });
}
const BADGE = { ok: ['Producing', 'ok'], watch: ['Check', 'warn'], alarm: ['Fault', 'err'],
                idle: ['Resting', 'mute'] };
const CLS = { ok: 'live', watch: 'watch', alarm: 'alarm', idle: '' };
function drawStrings(pv, expected) {
  $('panels').innerHTML = strings(pv, expected).map(r => {
    const scale = Math.max(r.exp, r.cur, 0.1) * 1.15;
    const cells = Math.min(r.s.panels, 12);
    const colour = r.state === 'idle' ? '#D8E0E8' : r.state === 'alarm' ? '#E7B4B4'
      : 'color-mix(in srgb, ' + C.solar + ' ' + ((0.45 + 0.55 * Math.min(1, r.ratio || 0.6)) * 100).toFixed(0)
        + '%, #DCE4EC)';
    const [txt, tone] = BADGE[r.state];
    return '<div class="ev-panel ' + CLS[r.state] + '">'
      + '<div class="ev-panel-top"><div><div class="ev-panel-name">' + r.s.name + '</div>'
      + '<div class="ev-panel-sub">' + r.s.panels + ' panels &middot; ' + r.s.kwp.toFixed(2)
      + ' kWp &middot; ' + r.s.facing + '</div></div>'
      + '<span class="ev-badge ' + tone + '">' + txt + '</span></div>'
      + '<div class="ev-panel-val">' + r.cur.toFixed(2) + '<small>kW</small></div>'
      + '<div class="ev-panel-bar" style="--w:' + Math.min(100, r.cur / scale * 100).toFixed(0)
      + '%;--exp:' + Math.min(100, r.exp / scale * 100).toFixed(0) + '%;--bc:'
      + (r.state === 'alarm' ? C.peak : C.solar) + '"><i></i><u></u></div>'
      + '<div class="ev-panel-foot"><span>expected ' + r.exp.toFixed(2) + ' kW</span><span>'
      + (r.ratio === null ? '-' : (r.ratio * 100).toFixed(0) + '% of expected') + '</span></div>'
      + '<div class="ev-cells" style="--cell:' + colour + '">' + '<b></b>'.repeat(cells) + '</div>'
      + '<div class="ev-panel-sub" style="margin-top:8px">' + r.note + '</div></div>';
  }).join('');
}

function render(i) {
  const r = S[i];
  const [when, pv, load, battRaw, soc, grid, expected, prod, used, selfKwh] = r;
  const hasBatt = D.battery_kwh > 0 && soc !== null;
  const batt = hasBatt ? battRaw : 0;
  const peak = Math.max(2, D.kwp, pv, load, Math.abs(grid), Math.abs(batt));
  const importShown = Math.max(0, grid + (D.has_ev ? r[10] : 0));
  const selfUse = load <= 0.01 ? 1 : Math.max(0, Math.min(1, (load - importShown) / load));

  // energy leaving the house gets its own colour: violet comes in, cyan goes out
  // the bidirectional car: + charging from surplus, - feeding the house (V2H)
  const carKw = D.has_ev ? r[10] : 0;
  const carSoc = r[11];
  // when the car powers the house, the grid import it covers simply disappears;
  // when it soaks up surplus, there is that much less to export
  const gridShown = grid + carKw;
  const gridColour = gridShown < -MIN ? C.export : C.grid;
  lineFor('solar', C.solar, pv, false, peak);
  lineFor('home', C.consumption, load, false, peak);
  lineFor('batt', C.battery, Math.abs(batt), batt > 0, peak);
  lineFor('grid', gridColour, Math.abs(gridShown), gridShown > 0, peak);
  pillFor('solar', pv, C.solar); pillFor('home', load, C.consumption);
  pillFor('batt', Math.abs(batt), C.battery); pillFor('grid', Math.abs(gridShown), gridColour);
  $('grid-icon').setAttribute('stroke', gridColour);

  const carG = $('car-group');
  if (D.has_ev && carG) {
    carG.style.display = '';
    lineFor('car', C.bar, Math.abs(carKw), carKw < 0, peak);   // - = car -> hub (V2H)
    pillFor('car', Math.abs(carKw), C.bar);
    $('v-car').textContent = carSoc.toFixed(0);
    $('s-car').textContent = carKw > MIN ? 'charging from your surplus'
      : carKw < -MIN ? 'powering your home (V2H)' : 'parked, ' + carSoc.toFixed(0) + '% charged';
    $('node-car').setAttribute('opacity', Math.abs(carKw) >= MIN ? '1' : '.7');
  } else if (carG) {
    carG.style.display = 'none';
  }

  $('v-solar').textContent = pv.toFixed(1);
  $('s-solar').textContent = 'of ' + D.kwp.toFixed(1) + ' kWp installed';
  $('node-solar').setAttribute('opacity', pv >= MIN ? '1' : '.55');
  $('sun-rays').style.animationPlayState = pv >= MIN ? 'running' : 'paused';
  $('sun-core').setAttribute('opacity', pv >= MIN ? '1' : '.45');

  $('v-home').textContent = load.toFixed(1);
  $('s-home').textContent = load >= MIN ? 'using now' : 'almost nothing';
  $('node-home').setAttribute('opacity', load >= MIN ? '1' : '.55');
  $('home-win').setAttribute('class', load >= MIN ? 'glow' : '');

  $('v-grid').textContent = Math.abs(gridShown).toFixed(1);
  $('s-grid').textContent = gridShown > MIN ? 'importing' : gridShown < -MIN ? 'exporting' : 'balanced';
  $('node-grid').setAttribute('opacity', Math.abs(gridShown) >= MIN ? '1' : '.55');

  if (hasBatt) {
    $('v-batt').textContent = soc.toFixed(0); $('u-batt').textContent = '%';
    $('s-batt').textContent = batt > MIN ? 'charging at ' + batt.toFixed(1) + ' kW'
      : batt < -MIN ? 'supplying ' + Math.abs(batt).toFixed(1) + ' kW'
      : 'idle \\u00b7 ' + D.battery_kwh.toFixed(0) + ' kWh';
    const fill = Math.max(2, 25 * Math.max(0, Math.min(100, soc)) / 100);
    $('bat-fill').setAttribute('y', (7 + (25 - fill)).toFixed(1));
    $('bat-fill').setAttribute('height', fill.toFixed(1));
    $('bat-bolt').style.display = batt > MIN ? '' : 'none';
  } else {
    $('v-batt').textContent = 'none'; $('u-batt').textContent = '';
    $('s-batt').textContent = 'not installed';
    $('node-batt').setAttribute('opacity', '.55');
  }

  const circ = 2 * Math.PI * (D.hub_r - 8);
  $('hub-arc').setAttribute('stroke-dasharray', (circ * selfUse).toFixed(1) + ' '
                            + (circ - circ * selfUse).toFixed(1));
  $('hub-pct').textContent = (selfUse * 100).toFixed(0) + '%';
  let story;
  if (D.has_ev && carKw < -MIN) {
    story = pv < MIN
      ? 'The panels are off, so your bidirectional car is running the house (V2H): '
        + Math.abs(carKw).toFixed(1) + ' kW straight from the car, '
        + (gridShown > MIN ? 'and only ' + gridShown.toFixed(1) + ' kW from the grid.'
                           : 'nothing from the grid.')
      : narrative(pv, load, batt, gridShown, hasBatt ? soc : null)
        + ' Your car is feeding the house too (V2H).';
  } else if (D.has_ev && carKw > MIN) {
    story = narrative(pv, load, batt, gridShown, hasBatt ? soc : null)
      + ' Spare solar is topping up the car instead of being sold cheap.';
  } else {
    story = narrative(pv, load, batt, gridShown, hasBatt ? soc : null);
  }
  $('narrative').textContent = story;

  $('k-prod').textContent = prod.toFixed(1);
  $('k-used').textContent = used.toFixed(1);
  $('k-used-sub').textContent = used > 0 ? (selfKwh / used * 100).toFixed(0)
                                + '% of it from your own panels' : '';
  $('k-batt').textContent = hasBatt ? soc.toFixed(0) : 'none';
  $('k-batt-u').textContent = hasBatt ? '%' : '';
  $('k-batt-sub').textContent = !hasBatt ? 'not installed' : batt > MIN ? 'charging'
    : batt < -MIN ? 'supplying the house' : 'idle';
  $('k-saved').textContent = (selfKwh * D.gap).toFixed(1);
  $('when').innerHTML = (i === S.length - 1 ? 'Latest reading' : 'Replaying')
    + ' <em>&middot; ' + when + '</em>';
  $('dot').className = 'ev-dot ' + (i === S.length - 1 && !playing ? 'live' : 'ok');
  drawStrings(pv, expected);
}

function step() { idx = (idx + 1) % S.length; $('scrub').value = idx; render(idx); }
function setPlaying(on) {
  playing = on;
  $('play').textContent = on ? 'Pause' : 'Replay the day';
  $('play').classList.toggle('on', on);
  if (timer) { clearInterval(timer); timer = null; }
  if (on) timer = setInterval(step, 130);
}
$('scrub').addEventListener('input', e => {   // fires while dragging: no round trip
  idx = +e.target.value; setPlaying(false); render(idx);
});
$('play').addEventListener('click', () => setPlaying(!playing));
$('latest').addEventListener('click', () => {
  setPlaying(false); idx = S.length - 1; $('scrub').value = idx; render(idx);
});
$('scrub').max = S.length - 1; $('scrub').value = idx;
render(idx);

// Tell Streamlit how tall this really is, so nothing is ever cut off and there
// is no dead space under it, whatever the window width.
function fit() {
  const h = Math.ceil(document.querySelector('.wrap').getBoundingClientRect().height) + 14;
  window.parent.postMessage(
    {isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: h}, '*');
}
window.addEventListener('resize', fit);
[60, 300, 900].forEach(ms => setTimeout(fit, ms));
</script>
"""


def live_panel(ts: pd.DataFrame, site: dict, layout: dict, fault_note: str = "",
                has_ev: bool = False) -> None:
    """Draws the whole 'Right now' block: scrubber, diagram, KPIs and strings."""
    data = {
        "samples": _samples(ts),
        "layout": layout,
        "kwp": float(site.get("kwp") or 0),
        "battery_kwh": float(site.get("battery_kwh") or 0),
        "gap": PRICE_BUY_LEI_KWH - PRICE_SELL_LEI_KWH,
        "hub_r": HUB[2],
        "colors": COLORS,
        "has_ev": bool(has_ev),
    }
    note = (f'<span style="color:{UI["danger"]};font-weight:600">{fault_note}</span>'
            if fault_note else "")
    html = (
        _style() + _EXTRA_CSS
        + '<div class="wrap">'
        + '<div class="ctl"><button id="play">Replay the day</button>'
          '<input id="scrub" type="range" min="0" max="1" value="1" step="1">'
          '<button id="latest">Latest</button></div>'
        + '<div class="ev-status"><div class="ev-item"><span class="ev-dot live" id="dot"></span>'
          '<span id="when" class="when"></span></div></div>'
        + _svg(has_ev)
        + f'<div class="ev-sec" style="margin:10px 0 6px"><span class="ev-sec-c" id="narrative">'
          f'</span>&nbsp;{note}</div>'
        + '<div class="ev-kpi-grid">'
          f'<div class="ev-kpi" style="--accent:{COLORS["solar"]}">'
          '<div class="ev-kpi-label"><span class="ev-kpi-dot"></span>PRODUCED TODAY</div>'
          '<div class="ev-kpi-value"><span id="k-prod">0</span><small>kWh</small></div>'
          '<div class="ev-kpi-sub">since midnight</div></div>'
          f'<div class="ev-kpi" style="--accent:{COLORS["consumption"]}">'
          '<div class="ev-kpi-label"><span class="ev-kpi-dot"></span>USED TODAY</div>'
          '<div class="ev-kpi-value"><span id="k-used">0</span><small>kWh</small></div>'
          '<div class="ev-kpi-sub" id="k-used-sub"></div></div>'
          f'<div class="ev-kpi" style="--accent:{COLORS["battery"]}">'
          '<div class="ev-kpi-label"><span class="ev-kpi-dot"></span>BATTERY</div>'
          '<div class="ev-kpi-value"><span id="k-batt">0</span><small id="k-batt-u">%</small></div>'
          '<div class="ev-kpi-sub" id="k-batt-sub"></div></div>'
          f'<div class="ev-kpi" style="--accent:{COLORS["price"]}">'
          '<div class="ev-kpi-label"><span class="ev-kpi-dot"></span>KEPT OFF YOUR BILL</div>'
          '<div class="ev-kpi-value"><span id="k-saved">0</span><small>lei</small></div>'
          '<div class="ev-kpi-sub">today, by using your own energy</div></div>'
          '</div>'
        + '<div class="ev-sec" style="margin:16px 0 6px"><span class="ev-sec-t">Your panels</span>'
          '<span class="ev-sec-c">each string, and how much of the weather it catches</span></div>'
          '<div class="ev-panels" id="panels"></div>'
        + "</div>"
        + _SCRIPT.replace("__DATA__", json.dumps(data))
    )
    components.html(html, height=HEIGHT, scrolling=False)
