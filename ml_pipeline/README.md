# One energy view for solar homes: ML module

Expected PV production from weather, anomaly detection for O&M, consumption habits with targeted nudges and a battery/injection dispatch plan.

The mentor's framing of the product, which the demo follows: **1) centralize** all vendor platforms into one view (dashboard + alerts), **2) compare** - day vs day, plant vs plant, client vs client (benchmark, evaluation), **3) decide** - inject into the grid or charge the battery (dispatch plan), **4) act** (the API below is the hook).

## Run

```
pip install -r requirements.txt
python run_demo.py                 # offline, synthetic weather (always works)
python run_demo.py --real-weather  # Open-Meteo: last 92 days + 3-day forecast
python run_demo.py --pvgis         # also fetch PVGIS baselines (internet once, then cached)
python run_demo.py --tariff tou     # customer on a time-of-use contract (cheaper nights/weekends)
python run_demo.py --baseline-days 5 --crew-hours 12   # today's numbers from the O&M interview
python analyze_real_load.py        # the real PPC load curve
streamlit run app.py               # the dashboard for the demo
python tests/test_connectors.py && python tests/test_pvgis.py
```

## How this answers the brief

| Brief asks | Where |
|---|---|
| One view of energy produced, consumed and stored | `app.py`, Customer tab (solar, home, battery, grid on one chart) |
| Customer uses energy smarter and pays less | habits + nudges in lei (`ml/habits.py`), best window (`ml/advice.py`), inject-or-store plan (`ml/dispatch.py`) |
| O&M catches abnormal operation early | expected-vs-actual alerts ranked by lei (`ml/anomalies.py`), O&M tab |
| Lower than expected / battery poorly used / fault just starting | `sudden_underperformance`, `battery_not_charging`, `gradual_degradation` alerts |
| Visible reduction in wasted energy or time to spot a problem | `ml/impact.py`, Impact tab |
| Works alongside existing inverters and EMS, does not replace them | read-only connectors (`ml/connectors.py`): maker cloud API, Modbus/SunSpec, distributor files |
| Prosumer rules and data protection | consent-gated benchmark, aggregates only, pseudonymous IDs (Data & privacy tab) |
| Sample data from real installations | `analyze_real_load.py` on the PPC file |
| Residential and industrial prosumers | simulated homes + the real factory curve |

Runs in about 5 seconds. Writes to `out/`:

- `sites.csv`: the 8 simulated installations (kWp, tilt, azimuth, battery)
- `telemetry.csv`: 15-minute data (pv_kw, load_kw, battery_kw, battery_soc, grid_kw)
- `expected.csv`: expected production per site per 15 min
- `alerts.csv`: alerts for the O&M dashboard (message + recommended action + estimated cost in lei)
- `faults_daily.png`: expected vs. actual for the faulty sites (for the slides)

## How it works

1. **Expected production.** A physical model (irradiance on the panel plane from Open-Meteo, temperature derating) plus a gradient boosting model trained on each site's healthy history. The ML part learns what physics doesn't know: local shading from a neighbouring building, a tree or the mountains. On shaded roofs the error drops from ~12-13% to ~9-10%.
2. **Anomalies.** Compare actual vs. expected with explainable rules:
   - `inverter_offline`: ~0 production for 1 h while the sun is up (critical)
   - `sudden_underperformance`: daily energy < 80% of expected, abrupt drop vs. the previous week (inverter/string)
   - `gradual_degradation`: 5-day energy < 86% of expected, slow drift (soiling)
   - `battery_not_charging`: solar surplus for 1 h, battery below 90% and not charging
   - `comms_loss`: no data for 1 h
3. **When to consume.** Expected production tomorrow minus a load forecast (household's median profile) gives the best 2-hour window per day.
4. **Decide: inject or store** (`ml/dispatch.py`). For every 15-min slot of the next day: charge the battery, inject, hold or discharge, against a day-ahead price curve. Reproduces the decision from the mentor's live demo - a site that refuses to inject when the price is ~0 and stores instead - and prices the plan in lei vs. always-inject. Every slot carries its reason (explainable, not a black box). Swap the synthetic price curve for the real OPCOM feed.
5. **Habits and nudges** (mentor feedback, 14 Nov). Recurring heavy-appliance runs are found in each household's load (spikes over a rolling baseline, clustered by time of day): the evening washing machine, an EV charged at 21:00. Each habit that runs on grid power gets one targeted push notification: when to run it tomorrow on solar and the lei saved per run and per month. A peer benchmark compares the household's evening-peak share with the fleet median. Real analytics behind every message, not an LLM prompt.

## Results on simulated data (20 random runs)

| Fault | Detected | Median time to detection |
|---|---|---|
| Inverter offline | 20/20 | 1 h |
| Battery not charging | 20/20 | 7 h |
| Inverter at -30% | 20/20 | 22 h |
| Gradual soiling (up to -25%) | 19/20 | ~22 days (at ~15-18% loss) |
| Logger offline | 20/20 | 1 h |

False alarms on healthy installations: 2 in 20 runs (5 healthy sites x 35 days each).

## Impact: before vs after

`ml/impact.py` turns every detected fault into the brief's metric. For each fault: hours until we flag it vs hours until O&M finds out today, energy and lei lost in both cases, and for an inverter trip the monthly availability PPC guarantees (90%).

On the simulated fleet (true faults only, the false alarm is excluded): median 14 h to spot a problem (measured from when each fault really began), 282 kWh (~367 lei) saved on 4 faults, and an inverter trip goes from 73% monthly availability to 96%. Gradual soiling is the honest exception: flagged after ~21 days, later than the assumed baseline, because a stricter threshold raises false alarms on cloudy days.

**The "today" numbers are assumptions until the O&M interview** (default: found after 7 days, fixed 24 h later). Pass the real ones with `--baseline-days` and `--crew-hours`, or move the sliders in the Impact tab. Every output says ASSUMED while the defaults are in use.

## Connectors: next to the existing equipment

`ml/connectors.py` only reads, never writes, and maps every source to the same data contract:

- `VendorCloudConnector`: a maker's cloud API (phase 1 in the mentor's plan). Each maker names fields differently, so each gets a small mapping to our contract.
- `SunSpecModbus`: reads the inverter on site over Modbus TCP with the public SunSpec map (phase 2): AC power, reactive and apparent power, energy counter, cabinet temperature and the operating state, including FAULT. For sites whose network PPC may not use, it runs behind a separate GSM modem. Tested on synthetic register blocks (`tests/test_connectors.py`), not yet on a real inverter.
- `ExcelLoadCurve`: the distributor's 15-minute load curve.

## PVGIS check

The organisers suggest PVGIS (European Commission JRC) as a starting point for "lower than expected". `ml/pvgis.py` fetches the average production per month for each site and compares it with actual kWh/day (`out/pvgis_check.csv`, O&M tab). It is a coarse monthly check next to the 15-minute weather model. It needs internet once; results are cached in `data/pvgis_cache.json`. The development sandbox blocks the PVGIS host, so it is tested on a payload shaped like the API answer (`tests/test_pvgis.py`): run `python run_demo.py --pvgis` once on a laptop with internet.

## Data protection

- Energy readings can be personal data under GDPR: they show when people are home.
- The analytics use 15-minute energy values under a pseudonymous site ID: no names, addresses or meter IDs.
- The peer benchmark only uses customers who accepted it (`consent_benchmark` in the site table; two simulated customers said no), and only ever shows a median of at least 3 consenting peers.
- Still to confirm with the mentors: what the prosumer rules allow PPC to collect, store and show, and how the sample data may be used.

## What breaks at real scale

- Alerts and nudges loop over sites in Python: fine for hundreds, needs batching or a job queue for tens of thousands.
- Maker cloud APIs have rate limits and different auth; each vendor needs its own adapter and polling schedule.
- The expected-production model is trained on a short history; at scale it needs a year of data per region and weekly retraining that excludes periods with alerts.
- Modbus needs a gateway or modem per site; the cloud APIs do not.

## Real data: the mentor's load curve

`data/curba_sarcina_test.xlsx` is a real (anonymized) consumer from PPC: one year, Oct 2025 - Sep 2026, in the distributor's 15-minute format. Consumption only, no PV.

```
python analyze_real_load.py                 # or: python analyze_real_load.py other_file.xlsx
```

Writes `out/real_load.csv` (same contract as the simulator, so every module runs on it), `real_drops.csv`, `real_forecast.csv`, `real_pv_what_if.csv` and three plots for the slides: `real_heatmap.png`, `real_daily_drops.png`, `real_forecast.png`.

What we handle in the loader (`ml/real_data.py`), all documented in the file's own Info sheet: local timestamps converted to UTC, the repeated 03:00 hour on 26 Oct 2025 and the missing one on 29 Mar 2026. The source is hourly data split into four equal quarter-hours, so the analysis works at hourly resolution: there is no real information inside an hour.

What the data says:

- **It is a factory on shifts.** Mon 08:00 to Sat 18:00, a day shift and an evening shift that ends at 03:00, Sunday off (~16 kW standby). Lunch dip at 13:00.
- **It is ramping up.** Average power went from 39 kW in Oct 2025 to 206 kW in Sep 2026; the evening shift appears in January and is full from March. Any baseline must be rolling, an annual average would flag the whole first quarter as a fault.
- **Seasonality.** Day-shift load is highest in Dec-Feb, lowest in May-June. Sunday standby doubles in winter (16-34 kW vs 6-11 kW in summer), likely heating. Early July runs around the clock (night load 134 kW vs ~35 kW in other months): extra shift or a big order.
- **Every drop gets an explanation** (`find_drops`): legal holidays including the moving Orthodox ones (`ml/calendar_ro.py`: Good Friday, Easter, Rusalii, plus Boboteaza and Sf. Ioan), bridge days, winter break 24 Dec - 7 Jan, and the ones only the client can explain - multi-day stops in March, June and end of July (summer shutdown?), plus Catholic Easter Monday (6 Apr), which hints at a foreign parent company.
- **Day-ahead forecast** (gradient boosting on lags, holidays and a 7-day level, trained on Oct-Jun, tested on Jul-Sep): daily error 24.6% vs 34.4% for "same hour last week", 20.0% vs 25.3% on normal days. The remaining error is mostly the unannounced stops, which no model can see coming: the product should let the client enter planned stops.
- **PV what-if** (synthetic Bucharest weather): 200 kWp would self-consume 70% of its output, cover 17% of the load and save ~197k lei/year; 400 kWp covers 29%. Up to 45% of the surplus falls on Sundays and holidays when the factory is stopped: that is exactly where the inject-or-store decision (`ml/dispatch.py`) pays off.

## Prices and tariffs

All prices live in `ml/tariffs.py`, nowhere else.

- **Fixed contract** (default): 1.30 lei/kWh, the PPC fixed-price household offer (final price incl. network tariffs and VAT is 1.29-1.37 lei/kWh depending on the distribution zone).
- **Time-of-use contract** (`TimeOfUseTariff`): the PPC Ore Smart+ intervals (press release, 18 March 2026). Reduced price on weekday nights 00:00-05:59 all year, all weekend, and on weekday middays 11:00-14:59 from March to October. Reduced: from 0.98 lei/kWh final. Standard: ~1.55 lei/kWh, our estimate from the offer's active-energy prices (0.823 vs 0.348 lei/kWh) plus VAT; final prices depend on the distribution zone. Legal holidays are not in the offer.
  Note the difference from the wholesale market (`ml/dispatch.py`): on the day-ahead market the evening is the most expensive time and midday solar hours can drop to zero or below. The retail offer makes late night and weekends cheap, plus midday in the sunny months.
- **Exported kWh**: 0.30 lei/kWh. This is an assumption, replace it with the compensation price from the contract.

`consumption_advice`, `habit_recommendations` and `plan_dispatch` take `tariff=` (a tariff object, a number in lei/kWh or nothing for the default). The best window is the cheapest one, not just the sunniest: grid energy at the tariff price plus own solar at the export price, compared with running the same appliance at the usual evening time. With a fixed price the sunniest window wins. Appliances are only scheduled between 07:00 and 23:00 by default (`earliest_h`, `latest_h`). For a water heater or an EV on a timer, pass `earliest_h=0, latest_h=24`: on a cloudy weekday with Ore Smart+ the advice then moves to 00:00-02:00 at the reduced price.

### Device schedule (smart plug, timer, delay start)

`appliance_plan()` in `ml/advice.py` turns the forecast into a schedule for the customer's own devices: when to switch each one on and off, how to set it and the lei saved. Presets: electric car (3.7 kW wallbox, 4 h, any hour), water heater (2 kW, 2 h, any hour, on a smart plug or timer socket), dishwasher (delay start, any hour) and washing machine (delay start, 07:00-23:00 only). The biggest load gets the solar first and books it, so two devices never count the same kWh. A window is suggested only if it saves at least 5% of the usual cost. Phones, tablets and laptops are left out on purpose: a few cents a day.

The platform only suggests: the customer sets the schedule. Nothing is sent to the devices, in line with the read-only constraint in `ml/connectors.py`. `run_demo.py` writes `out/schedule_<site>.ics` (calendar reminders, 10 minutes before each start), the dashboard shows the table and a download button.

## For the backend / dashboard

```python
from ml.model import ExpectedProductionModel, build_features
from ml.anomalies import detect_alerts, Config
from ml.advice import consumption_advice

feats = build_features(weather, sites)               # weather: timestamp, site_id, gti, ghi, temp_c, wind_ms
model = ExpectedProductionModel().fit(healthy_telemetry, feats)
expected = model.predict(feats)                      # timestamp, site_id, expected_kw, physics_kw
alerts = detect_alerts(telemetry, expected, sites, Config())   # prices from ml/tariffs.py
tips = consumption_advice(expected, telemetry, "S01")

from ml.habits import detect_events, find_habits, habit_recommendations, peer_benchmark
habits = find_habits(detect_events(telemetry, "S01"))   # learned from 28 days of load data
plan = appliance_plan(expected, telemetry, "S01", tariff=TimeOfUseTariff())   # [{name, start_local, end_local, saving_lei, schedule, text}]
nudges = habit_recommendations(habits, expected, telemetry, "S01")  # [{text, saving_lei_per_month, ...}]
bench = peer_benchmark(telemetry, sites, "S01")         # evening share vs fleet median

from ml.dispatch import plan_dispatch
d = plan_dispatch(expected, telemetry, sites, "S01")    # d["plan"], d["uplift_lei"], d["texts"]
```

`run_demo.py` also writes `out/dispatch_plan.csv` (per-slot action + reason) for the dashboard.

All timestamps are UTC. Convert to Europe/Bucharest only for display.

## Known limitations

- **Seasonal drift on shaded roofs.** The model is trained on September-October. In November the sun is lower than anything it has seen, so shading can be underestimated by a few percent. Both false alarms come from this. In production: train on at least a year, or retrain weekly excluding periods with alerts.
- **Open-Meteo** was not tested from the development environment (network blocked). If the call fails, the demo automatically falls back to synthetic weather. Run `--real-weather` once at the start.
- Soiling is detected slowly on purpose: a stricter threshold catches it earlier but produces false alarms on cloudy days.
- **Consent and privacy.** The peer benchmark compares behaviour across users, which needs explicit in-app consent. Per-household habit detection uses only that household's own meter data.
- **No real client names anywhere.** The mentor filtered client names out of his own demo; simulated sites use invented neighbourhood names, keep it that way in screenshots.
- **Reactive/apparent energy not modeled.** Real platforms log active, reactive and apparent energy at 15 min; the contract has room for the extra columns.
- **Day-ahead prices are synthetic.** Plug in OPCOM day-ahead data for the dispatch plan.
- **The real load file is client data.** Anonymized, but keep it out of public repos and screenshots of the raw table.
- **One profile per customer type.** A home and a firm behave differently; the load forecast and the nudges should be parameterized by customer type (the site table has the hook for it).
