# Frontend - One Energy View

Streamlit interface for the PPC challenge "One energy view for solar homes".

Everyone signs in first, so the questionnaire answers, the accepted plan and the
tips someone turned down belong to an account instead of a browser tab.

Four pages:

- **Home (views/home.py):** the live energy view. An animated diagram shows where
  the current is actually going right now - panels, inverter, home, battery, grid -
  with a clock that can replay a whole day 15 minutes at a time. Under it: the array
  string by string, where a typical day's kWh go, the three-day chart and the
  recommendations with "Accept / Not today / Don't suggest again".
- **Consumption (pages/1_Consumption_analysis.py):** the 15-minute curve, expected
  vs. actual production, the hourly profile and energy per day - this is where you
  see why the customer gets the tips they get.
- **O&M monitoring (pages/2_Installation_monitoring.py):** the page for the
  operations and maintenance team: alert cards sorted by what they cost in lei, the
  recommended action, acknowledge / send-a-technician, and the string-level view
  that says which part of an installation is down.
- **Account (pages/3_Account.py):** everything stored about this user, their
  decisions and an activity log, with a way to clear it.

## Running it

```
cd frontend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Demo accounts are created on first run: `demo@ppc.ro` / `demo1234` (prosumer) and
`om@ppc.ro` / `demo1234` (O&M operator). There is also a "look around without an
account" mode, which keeps everything in the session only.

## The live energy flow

`components/flow.py` draws the diagram as SVG with CSS animation - no extra
Streamlit component and no JavaScript. Direction, speed and thickness all come
from the telemetry:

| data | what it does on screen |
| --- | --- |
| `pv_kw` | panels to inverter, always this direction |
| `load_kw` | inverter to home, always this direction |
| `battery_kw` | positive = charging, so the pulses run towards the battery; negative = discharging, they run back |
| `grid_kw` | positive = importing, pulses come from the grid; negative = exporting, they go to it |

The ring in the middle is self-consumption (how much of the house runs on its own
energy), and one sentence under the diagram says the same thing in words. Anyone
whose system asks for reduced motion gets the same diagram, standing still.

The whole block is drawn once and then driven in the browser
(`components/flow_live.py`): the day's telemetry is handed to the page as data,
and the scrubber, the play button, the KPI cards and the string cards are
updated in JavaScript. Dragging the slider redraws in under a millisecond,
because nothing goes back to Python. Streamlit widgets send every change to the
server and redraw from the answer, which for a slider is one round trip per
step - that is the hesitation this avoids.

## Panels, string by string

The telemetry reports one production figure per installation, so
`services/plant.py` splits a site into the strings its kWp implies and spreads the
measured production over them. When there is an active array fault, most of the
missing power is placed on one string - that is what sends a technician to the
right place. These per-string numbers are derived, not a second measurement, and
the pages say so.

## Where the data comes from

The frontend picks its source on its own, in this order:

1. **The ML pipeline** - if `../ml_pipeline/out/` exists (generated with
   `cd ml_pipeline && python run_demo.py`). This is the preferred source: it has
   production, consumption, battery, grid, weather-expected production, alerts in
   lei and the personalised recommendations from `customer.json`.
2. **The FastAPI backend** - if it answers at `http://localhost:8000/health` and
   has data. To start it:

   ```
   cd backend
   pip install -r requirements.txt
   python ../frontend/tools/seed_db.py   # once: fills the database from the xlsx
   uvicorn app.main:app --reload --port 8000
   ```

3. **Simulated data** - if neither source above is available.

The status strip at the top of every page says which source is in use, how old the
newest reading is, whether the backend answers and whether anything is being saved.

Optional variables: `API_URL` (another host/port for the backend), `ML_OUT`
(another path to out/), `USE_MOCK=true` (forces simulated data), `USER_DB`
(another path for the accounts database).

## The user database

`services/db.py` is a small SQLite database (`frontend/data/app.db`, ignored by
git) with four tables: `users`, `profiles` (the questionnaire answers),
`decisions` (accepted / snoozed / dismissed recommendations) and `events` (the
activity log). Passwords are stored as a PBKDF2-SHA256 hash with a per-user salt.

Pages never touch it directly - they call `services/store.py`, which keeps a copy
in the session and writes through. If the database cannot be opened, the app says
so and keeps working on session state alone.

## Widgets that stay clicked

Every widget in the questionnaire is keyed (`w_*`) and never gets a `default=`
on later runs. A default that changes between runs gives a Streamlit widget a
new identity, and the answer the user just gave is thrown away - which is why a
pill used to need two clicks. `_enter_step()` re-seeds a step's widgets from the
saved answers when you walk back into it, because Streamlit drops the state of
widgets that are not on screen.

## Errors

`components/errors.py` has the three things a demo needs: the status strip, an
error card that says what happened and what to do next, and a `section()` context
manager that keeps one broken part of a page from taking the whole page down.
Whatever failed is collected in a "Technical details" expander at the bottom.

## Appliances and what they are worth

`components/wizard.py` holds `APPLIANCE_PROFILE`: for each big consumer - heated
pool, hot tub, sauna, electric car, heat pump, underfloor heating, water heater,
washing machine, dishwasher, dryer, oven, irrigation pump, home server - a typical
run in kWh, how much of it can realistically move into the solar window, and how
often it happens in a month. The first estimate after the questionnaire and the
recommendation cards both read that one table, so they can never disagree.

A pool gets two follow-up questions (hours a day, season) and an electric car one
(km a day), because those two answers change the number more than anything else:
a pool heated eight hours a day is worth around 340 lei a month on its own.

## Prices

Every savings figure uses the tariff from `ml_pipeline/ml/tariffs.py`
(`RETAIL_LEI_KWH` and `FEED_IN_LEI_KWH`), so the questionnaire, the
recommendations and the ML results agree. If `ml_pipeline` is missing,
`config.py` falls back to the same values (1.30 and 0.30 lei/kWh).

## Look and feel

The theme lives in `components/theme.py` and the colours in `config.py`
(`COLORS` for data, `UI` for the interface). They are published as CSS variables
(`--ev-*`), so changing one value there updates every page, card and the flow
diagram.

## Structure

```
frontend/
  app.py                            entry point and top navigation
  views/home.py                     the customer's live screen
  pages/
    1_Consumption_analysis.py       consumption and production charts
    2_Installation_monitoring.py    the maintenance team's page
    3_Account.py                    what we store about this user
  components/
    theme.py                        shared look: CSS variables, hero, KPI cards
    flow.py                         the energy flow diagram (server-rendered)
    flow_live.py                    the live block: same diagram, scrubbed in the browser
    strings.py                      panel-array cards, consumption breakdown
    alerts.py                       alert cards for the O&M team
    auth.py                         sign in, sign up, guest mode
    errors.py                       status strip, error cards, section guard
    wizard.py                       onboarding questionnaire (5 steps)
    notifications.py                recommendation cards
    charts.py                       charts (plotly)
    kpi_cards.py                    number cards
  services/
    db.py                           SQLite: accounts, profiles, decisions, log
    store.py                        one place to read and write user state
    plant.py                        strings of panels, consumption breakdown
    ml_source.py                    reads ml_pipeline/out/ (preferred source)
    api_client.py                   the FastAPI backend, with a mock fallback
    mock_data.py                    simulated data in the API format
  tools/seed_db.py                  fills the backend database from the PPC xlsx
  config.py                         API URL, solar window, prices, colours
```

## To discuss as a team

- The ML sites (S01-S08, simulated) and the backend sites (SITE-01/02, from the
  seed) are different lists; when both sources exist, the frontend shows the ML
  ones. Ideally the backend would also serve the ML results, so there is a single
  list.
- Accounts live in the frontend's own SQLite file. If the backend grows a users
  table, `services/db.py` is the only file that has to change.
