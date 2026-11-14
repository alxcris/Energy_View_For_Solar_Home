# Energy_View_For_Solar_Home
AI_Bootcamp implementation of the "One view of the energy a prosumer produces, consumes and stores" challenge.

## Run it end to end

```
# 1. ML pipeline: simulated fleet, expected production, alerts, nudges, battery plan
cd ml_pipeline
pip install -r requirements.txt
python run_demo.py              # writes ml_pipeline/out/
python analyze_real_load.py     # optional, needs the PPC file in ml_pipeline/data/
streamlit run app.py            # optional, the ML dashboard

# 2. API, filled from the ML output
cd ../backend
pip install -r requirements.txt
python -m app.db.seed_from_ml   # fills solar_energy.db (sites, inverters, alerts, load curves)
uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
```

`/recommendations` asks the AI advisor first; if it is not running, it answers with the ML recommendations (`"source": "ml_fallback"`).

The PPC load curve is client data: keep it out of this repo (see `.gitignore`) and ask the mentors how it may be used.

