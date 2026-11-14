# Pitch plan: Chief Bit, Challenge 1 (One energy view for solar homes)

5 minutes on stage: 2 min presentation, 1 min demo, 2 min Q&A. The jury scores problem evidence first, then the working prototype, then the presentation.

Everything in [brackets] has to come from the interviews: exact words, with the role of the person who said them. Do not fill these from memory or from an AI summary.

## 1. The problem and our angle (~30 s)

Checklist from the brief:
- [ ] Who our user is: the prosumer or the O&M technician
- [ ] What goes wrong for them today, and how often

What we have:
- Brief: every device shows its own piece in its own app; O&M finds problems only after they cost money.
- Mentor (PPC, live demo): one platform per inverter maker, each looking different; PPC guarantees clients 90% availability.
- [Our answer to "who feels it more": O&M or prosumer, with one quote]
- [How often it happens: a number from the O&M interview]

## 2. The evidence (~40 s)

Checklist:
- [ ] How customers decide when to run heavy loads, in their own words
- [ ] How the O&M team finds out about a fault today, and how late
- [ ] What the sample data from real installations showed

What we have:
- [Prosumer quote: the last time they ran the washing machine, how they picked the time]
- [O&M quote: the last time an installation underproduced, how they found out, after how long]
- Real PPC load curve (one consumer, one year): a factory on shifts that grew five times in a year; every drop explained (legal holidays incl. Orthodox Easter, a 24 Dec - 7 Jan break) except multi-day stops in March, June and end of July that only the client can explain. Slide: `out/real_heatmap.png`.
- If that client had 200 kWp of PV: up to 45% of the surplus falls on Sundays and holidays, when the factory is stopped.

## 3. Our solution (~20 s)

Checklist:
- [ ] What it does
- [ ] How it works next to the customer's existing inverters and apps

One sentence: one view of what each installation produces, uses and stores, which tells O&M within hours when production falls below what the weather allows and tells the customer, in lei, when to use their own power.

Next to existing equipment: read-only, from the maker clouds (API) and, where needed, from the inverter itself (Modbus/SunSpec); nothing is replaced or controlled.

## 4. How it fixes the problem (~30 s)

Checklist:
- [ ] How much wasted energy, or time to spot a problem, it saves
- [ ] The assumption we tested, and what happened

What we have (simulated fleet, 8 installations, 5 injected faults):
- Faults spotted after a median of 14 h (inverter trip 5 h, battery not charging 7 h, inverter at -30% 22 h) vs [X days today, from the O&M interview]. Slow soiling takes ~21 days: say so if asked.
- 282 kWh (~367 lei) saved on 4 faults; an inverter trip goes from 73% to 96% monthly availability (PPC guarantees 90%). Recompute with the real "today" number: `python run_demo.py --baseline-days X --crew-hours Y`.
- Customer side: a habit found in the data (washing machine around 19:45 on grid power) moved to the solar window, ~15 lei/month; the battery plan earns ~7.5 lei/day vs always injecting (PPC fixed price, ~1.30 lei/kWh).
- [Riskiest assumption and what the interviews said about it]

## Demo (1 min), `streamlit run app.py`

1. O&M tab: the alert list ranked by lei; open S07, the inverter trip, show the gap between expected and actual.
2. Customer tab: S05, one chart for solar, home, battery and grid; the nudge in lei; the battery plan refusing to inject at a zero price.
3. Impact tab: move the "days until O&M finds out" slider to the number from the interview.
4. Real client tab: the heatmap, ten seconds.

## Q&A prep

- **Where is the AI?** A gradient boosting model learns what each roof should produce from the weather (it learns local shading physics cannot), anomaly detection on top of it, habit detection from load data, a day-ahead load forecast on the real PPC curve (25% vs 34% daily error for "same as last week").
- **Is it real data?** The PPC load curve is real; the PV fleet is simulated with injected faults because we have no PV telemetry yet. [Ask the mentors for real inverter data.]
- **What breaks at scale?** See README, "What breaks at real scale".
- **GDPR?** Pseudonymous IDs, consent-gated benchmark, aggregates only. [What the mentors said about prosumer rules.]
- **Why would O&M trust it?** Every alert says why ("produced 68% of what the weather allowed") and what to do.
