# Frontend - One Energy View

Interfata pentru challenge-ul PPC "One energy view for solar homes", in Streamlit.

Trei pagini:

- **Clientul (app.py):** chestionar scurt de intrare, starea de acum (solar, casa,
  baterie, retea), recomandari cu "Accepta / Nu azi / Nu-mi mai propune", planul
  de economii si planul bateriei pe a doua zi.
- **Analiza consum (pages/1_Analiza_consum.py):** curba la 15 min, productia
  asteptata vs. reala, profilul orar si energia pe zile - de aici se vede de ce
  primeste clientul sfaturile.
- **Monitorizare instalatii (pages/2_Monitorizare_instalatii.py):** pagina
  echipei de operare si mentenanta: alertele ordonate dupa cat costa (lei),
  actiunea recomandata si graficul asteptat vs. real per instalatie.

## Rulare

```
cd frontend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## De unde vin datele

Frontend-ul isi alege singur sursa, in ordinea asta:

1. **Pipeline-ul ML** - daca exista `../ml_pipeline/out/` (generat cu
   `cd ml_pipeline && python run_demo.py`). E sursa preferata: are productie,
   consum, baterie, retea, productia asteptata din vreme, alerte in lei si
   recomandarile personalizate din `customer.json`.
2. **Backend-ul FastAPI** - daca raspunde la `http://localhost:8000/health` si
   are date. Pornire:

   ```
   cd backend
   pip install -r requirements.txt
   python ../frontend/tools/seed_db.py   # o singura data: umple baza din xlsx
   uvicorn app.main:app --reload --port 8000
   ```

3. **Date simulate** - daca niciuna dintre sursele de sus nu e disponibila.
   Un banner spune cand se intampla asta. Demo-ul merge in orice conditii.

Variabile optionale: `API_URL` (alt host/port pentru backend), `ML_OUT` (alta
cale catre out/), `USE_MOCK=true` (forteaza simularea).

## Structura

```
frontend/
  app.py                          ecranul clientului + chestionarul
  pages/
    1_Analiza_consum.py           graficele de consum si productie
    2_Monitorizare_instalatii.py  pagina echipei de mentenanta
  components/
    wizard.py                     chestionarul de intrare (5 pasi)
    notifications.py              cardurile de recomandari
    charts.py                     graficele (plotly)
    kpi_cards.py                  cardurile cu cifre
  services/
    ml_source.py                  citeste ml_pipeline/out/ (sursa preferata)
    api_client.py                 backend-ul FastAPI, cu fallback pe mock
    mock_data.py                  date simulate in formatul API-ului
  tools/seed_db.py                umple baza backend-ului din xlsx-ul PPC
  config.py                       URL API, fereastra solara, preturi, culori
```

## De discutat in echipa

- Textele din `customer.json` si `alerts.csv` (pipeline-ul ML) sunt in engleza;
  interfata e in romana. De ales o limba inainte de demo.
- Site-urile din ML (S01-S08, simulate) si cele din backend (SITE-01/02, din
  seed) sunt liste diferite; cand ambele surse exista, frontend-ul le arata pe
  cele din ML. Ideal, backend-ul ar servi si rezultatele ML, ca sa fie o
  singura lista.
- Preturile din `config.py` sunt orientative; cele reale sunt in
  `ml_pipeline/ml/tariffs.py` la colegul de ML - de aliniat.
