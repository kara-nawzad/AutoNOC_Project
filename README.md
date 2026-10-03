# AutoNOC — a predictive NOC for a simulated LTE network in Sulaymaniyah

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/kara-nawzad/AutoNOC_Project/actions/workflows/ci.yml/badge.svg)](https://github.com/kara-nawzad/AutoNOC_Project/actions/workflows/ci.yml)

A digital-twin simulation of a 300-tower LTE network in Sulaymaniyah, Iraq,
with an AI layer that **diagnoses** faults (the Doctor), **predicts** failures
(the Oracle), **acts** on them (the Commander), and **proves** the acting is
worth it (the counterfactual study).

Designed around the **O-RAN Non-Real-Time RIC** architecture: the Doctor is a
Root-Cause-Analysis rApp correlating 3GPP PM/FM counters, the Oracle is a
Predictive-Maintenance rApp over time-series telemetry, and the Commander is
the **A1 policy enforcement engine** automating closed-loop RAN intent. The
dashboard speaks operator language — **VSWR alarms, PRB utilisation, CQI,
E-RAB drop rate, ITU-T X.733 severities** — and models the #1 OPEX line in
Iraqi telecom: **site power** (diesel generators, battery banks, fuel theft).

Built as a portfolio / learning project. Python 3.12+, FastAPI + Leaflet,
XGBoost, PyTorch. **Deterministic** — the same seed produces the same world.

> **In a hurry?** The [90-second executive pitch](docs/PITCH.md) is the
> fastest way to see what this project is worth to an operator.

---

## Table of Contents

- [Features](#features)
- [Telecom standards alignment](#telecom-standards-alignment-3gpp--itu-t--o-ran)
- [Architecture](#architecture)
- [Project layout](#project-layout)
- [The demo — "Storm over Goizha"](#the-demo--storm-over-goizha)
- [Quickstart](#quickstart)
- [API reference](#api-reference)
- [Testing](#testing)
- [Project notes (full deep-dive reference)](docs/PROJECT_NOTES.md)
- [Design vision (UI direction & motion system)](docs/DESIGN_VISION.md)
- [Results (honest versions)](#results-honest-versions)
- [Honest limitations](#honest-limitations)
- [Invariants](#invariants-why-the-architecture-is-the-way-it-is)
- [Roadmap](#roadmap)
- [Tech stack](#tech-stack)
- [License](#license)

---

## Features

| Component | What it does |
|---|---|
| **Doctor** — RCA rApp (XGBoost) | Root-cause analysis over 3GPP PM/FM counters: diagnoses already-broken nodes |
| **Oracle** — PdM rApp (GRU) | Predictive maintenance: flags *upcoming* failures from contiguous telemetry windows |
| **Commander** — A1 policy engine | Decision-theory layer that acts on predictions (p > 0.4375), tiered autonomy |
| **Counterfactual study** | Proves the AI is worth it — 4 arms, identical schedules per seed |
| **Site power model** | Type A/B/C power plants, battery fade, **ATS failure-to-crank** and **fuel-theft** alarms |
| **API + dashboard** | FastAPI backend pushing a dark operations console (NEXUS-style layout, spring-physics motion engine, live sparklines, X.733 feed) — see [design vision](docs/DESIGN_VISION.md) |

A 300-tower LTE digital twin with real Sulaymaniyah geography, COST-231
propagation, dual-core fiber/microwave topology, weather-driven exogenous
faults, ITU-T X.733 alarm severity, and a fully-tested engine.

---

## Telecom standards alignment (3GPP / ITU-T / O-RAN)

The dashboard and FM log speak the language operators actually use. Internal
ids, the 71-feature contract and the trained models are unchanged — the
standards layer is derived readouts and vocabulary, never new dynamics.

| Generic term | What AutoNOC shows | Standard |
|---|---|---|
| Antenna fault | **VSWR alarm** (VSWR = (1+|Γ|)/(1−|Γ|) from S11; 1.5 field threshold ⇔ −14 dB) | RAN FM practice |
| Traffic congestion | **PRB utilisation ≥ 85% + CQI collapse** | 3GPP PM counters |
| Throughput | **User throughput (QCI 9, best effort)** | 3GPP QoS (TS 23.203) |
| Packet loss | **E-RAB drop rate (%)** | 3GPP accessibility KPI |
| CQI 0–15 | derived from SINR | TS 36.213 Table 7.2.3-1 (linear approx.) |
| Log severities | **CRITICAL / MAJOR / MINOR / WARNING / CLEARED** | ITU-T X.733 |
| AI layer | **Non-RT RIC rApps + A1 policy enforcement** | O-RAN WG2 |

**Site power architecture** (the #1 OPEX line in Iraq — diesel, batteries,
grid instability):

| Type | Configuration | Districts |
|---|---|---|
| **A** | Grid + standby diesel generator (DG) | strong-grid urban (Salim St, University, …) |
| **B** | Hybrid DG + deep-cycle VRLA battery bank, fuel-saving cycling | bad-grid **Bakrajo** (UNSTABLE mains) |
| **C** | Off-grid solar PV + LFP bank + DG backup | remote **Goizha** ridge (EXPOSED) |

Plus the two alarms every telecom engineer recognises instantly:

- **ATS FAILURE TO CRANK** — mains down, battery at the generator-start
  level, and the diesel set does *not* start. The site drains toward site-down
  until the switch recovers or a crew services it. (X.733 CRITICAL)
- **FUEL THEFT / ABNORMAL FUEL DROP** — the tank loses 15–25% in one
  telemetry interval while the DG is off; consumption cannot explain it.
  (X.733 CRITICAL, counted in the header's PWR ALARMS metric)

---

## Architecture

```
        ┌──────────────────────────────────────────────┐
        │  autonoc/engine   (PURE — stdlib only, no I/O)│
        │  physics · network · faults · dispatch        │
        │  NOCEngine.step()  owns the clock (I1)        │
        └──────────────────────┬───────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  autonoc/ai         │
                    │  Doctor · Oracle    │
                    │  batched inference  │
                    └──────────┬──────────┘
                               │
              ┌────────────────▼────────────────┐
              │  autonoc/api  (FastAPI)         │
              │  lifespan clock · cursor deltas │
              │  /api/config is the truth (I5)  │
              └────────────────┬────────────────┘
                               │ HTTP / tick-cursor deltas
                    ┌──────────▼──────────┐
                    │  autonoc/web        │
                    │  Leaflet dashboard  │
                    │  renders, never     │
                    │  computes (I6)      │
                    └─────────────────────┘
```

The engine is deliberately **pure** (stdlib only, no I/O, no framework, no wall
clock). Everything time-related is owned by `NOCEngine.step()`, called from
exactly one place in production (a lifespan task in the API) — enforced by the
invariant tests.

## Project layout

```
autonoc/
  engine/            PURE. stdlib only. no I/O, no framework, no wall clock.
    config.py        every tunable constant (single source of truth)
    models.py        ENodeB, AggSite, FiberRing, FiberCut, Team, Incident
    engine.py        NOCEngine.step(), ledger, KPIs, cut_fiber()
    placement.py     tower positions (clutter-scaled variable grid)
    faults.py        exogenous schedule, causal degradation, curves
    physics.py       COST-231, thermal, power, dust, rain fade
    network.py       topology, neighbour graph, fiber rings
    dispatch.py      correlate_alarms(), priority_score(), best_team()
    commander.py     M6: expected-value decision layer (NOT machine learning)
    geo.py / noise.py
  ai/
    features.py      71-feature builder, shared train + inference
    dataset.py       engine -> train/val/test.csv (tabular, Doctor)
    train.py         Doctor: XGBoost + baselines B0/B1
    seqdata.py       engine -> contiguous 60-min windows (Oracle)
    oracle.py        Oracle: B0/B1/B2/B3 vs GRU benchmark
    serve.py         M6: batched live inference, rules-mode fallback
  api/               FastAPI, lifespan clock, cursor deltas, control endpoints
  web/               Leaflet dashboard (renders, never computes)
  scripts/
    sanity_check.py  headless physics report
    export_sites.py  sites_300.json / .csv
    counterfactual.py   M7: the four-arm study
    cast_seed.py        M8: search seeds for the demo world
tests/               64 tests: 11 invariant guards + 24 regressions
                     + 8 AI-leakage guards + 13 Commander + 8 counterfactual
docs/                PROJECT_NOTES.md — the full deep-dive reference
```

---

## The demo — "Storm over Goizha" (5 minutes)

One cast seed contains the whole story, **emergent** — nothing is scripted.
`python -m autonoc.scripts.cast_seed --seeds 300` found seed **131**, whose
exogenous schedules naturally produce:

| Beat | What happens | Sim time (seed 131) |
|---|---|---|
| Act 0 | Calm opening — crews idle, ~99% availability | D1 00:00 |
| Act 1 | SLY-eNB-080 (Salim St) degrades; the Oracle flags it, the Commander acts | D1 05:55 |
| Act 2 | Crew pre-positioned on site before failure | — |
| Act 3 | **Storm over Goizha (81 km/h) + a natural storm-caused fiber cut** | D1 10:15 |
| Act 4 | Instant power fault during the storm — no warning, by design | D1 11:20 |
| Act 5 | Counterfactual table: same seed, AI on vs off | — |

Run it:

```powershell
$env:AUTONOC_SEED = 131
python -m uvicorn autonoc.api.main:app --port 8000
```

Open http://localhost:8000, click **ENABLE AI** in the AI panel (or start
with `$env:AUTONOC_AI = 1`). At 1× speed one tick ≈ one second, so the acts
fall at roughly 0:00 / 1:00 / 2:00 / 2:30 of the demo. When the storm hits,
click **CUT FIBER** for the isolation spectacle (34 alarms → 1 incident) — a
natural double cut is ~2×/year, far too rare to wait for on camera.

> Prefer a one-click start? Use `Start-Demo.ps1` (background server, AI
> auto-on) or `Start-Demo.bat`. Both use relative paths and work from any clone.

---

## Quickstart

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu

python -m autonoc.scripts.sanity_check    # headless physics report
python -m autonoc.ai.dataset              # ~3 min -> data/*.csv
python -m autonoc.ai.train                # ~40 s  -> Doctor
python -m autonoc.ai.seqdata              # ~2 min -> data/seq_*.npz
python -m autonoc.ai.oracle               # ~2 min -> Oracle
python -m pytest tests/ -q                # 64 passed
python -m autonoc.scripts.counterfactual --seeds 30 --days 10 --workers 8   # M7
python -m autonoc.scripts.cast_seed --seeds 5000 --workers 8               # M8
python -m uvicorn autonoc.api.main:app --reload --port 8000
```

`data/` is regenerable and does not survive workspace snapshots; if a CSV is
missing, re-run `dataset` / `seqdata`. The Oracle run also writes
`models/oracle_stats.npz`, which the live GRU serving requires — re-run it if
you ever see **RULES MODE** in the dashboard.

## API reference

Base URL: `http://localhost:8000`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the Leaflet dashboard |
| `GET` | `/api/config` | Single source of truth (status names/colors, thresholds, map) |
| `GET` | `/api/delta?since=<tick>` | Cursor-based state deltas (read-only & idempotent) |
| `GET` | `/api/health` | Status: tick, seed, ai_enabled, ai_policy, paused, speed |
| `POST` | `/api/control/pause` | Pause the simulation |
| `POST` | `/api/control/resume` | Resume the simulation |
| `POST` | `/api/control/step` | Advance one tick |
| `POST` | `/api/control/speed?value=1.0` | Set speed (0.25–10) |
| `POST` | `/api/control/inject?node_id&kind` | Inject a fault (1–5) on a node |
| `POST` | `/api/control/cut-fiber?ring_id&isolate` | Trigger the Act 3 double-cut scenario |
| `POST` | `/api/control/ai?enabled&auto_approve_seconds` | Toggle the Commander |
| `POST` | `/api/control/approve/{action_id}` | Approve a Commander action |
| `POST` | `/api/control/veto/{action_id}` | Veto a Commander action |

Interactive docs are served by FastAPI at `http://localhost:8000/docs`.

**Environment variables:**

| Var | Default | Purpose |
|---|---|---|
| `AUTONOC_SEED` | `42` | Simulation seed (the demo uses `131`) |
| `AUTONOC_AI` | `0` | `1` auto-enables the Commander at boot |
| `AUTONOC_AUTO_APPROVE` | `0` | Auto-approve Commander actions after N seconds |

---

## Testing

```powershell
python -m pytest tests/ -q
```

87 tests across the suite:

- **11 invariant guards** (`test_invariants.py`) — pure-engine, determinism,
  banned imports via AST, single-source-of-truth, no-preview leakage
- **20 regression tests** (`test_regressions.py`) — availability, ring reroute,
  team arrival, fault repair, realistic tower spacing …
- **17 telecom-standards tests** (`test_telecom.py`) — VSWR identity, CQI/PRB
  behaviour, X.733 vocabulary, site-power types, ATS + fuel-theft alarms
- **12 AI-leakage guards** (`test_ai.py`) — no test-set information in features
- **14 Commander tests** (`test_commander.py`) — decision-theory behaviour
- **7 counterfactual tests** (`test_counterfactual.py`)
- **6 polish tests** (`test_polish.py`) — API payload/schema hygiene

CI: the committed [workflow](.github/workflows/ci.yml) is deploy-only; a
test-gated replacement (ubuntu, Python 3.12, deploy `needs: test`) is ready
at [`docs/ci-proposed.yml`](docs/ci-proposed.yml) — copy it over the workflow
file and commit with workflow-write access to activate it (the app token on
the branch that prepared it lacks GitHub's `workflows` permission).

## Results (honest versions)

**M3 — alarm correlation.** Trigger a double fiber cut: 34 nodes dark,
34 alarms correlated to 1 incident, fully restored in 21 ticks. The naive
path sends 10 crews that all arrive to find nothing wrong — 13× fewer
crew-ticks, 34 nodes fixed vs 0.

**M4 — the Doctor (XGBoost).** precision 0.993 / recall 1.000 / FPR 0.0001 at
true prevalence; B0 "always healthy" scores 98.68% (published deliberately);
B1 v1 thresholds: 0.623 / 0.535. *Caveat kept in the write-up:* diagnosing an
already-broken node is easy — degradation has already moved the metrics.

**M5 — the Oracle (GRU).** B3 XGBoost AUC-PR 0.501 vs GRU **0.547 (+9.2%)** on
identical contiguous windows. Recall 0.450 — with 25% of faults instant by
construction, the honest claim is "caught 45% of the 75% that were physically
predictable." B1's net benefit is MINUS 11.5 million tower-minutes: it catches
half of all failures and is still worse than doing nothing.

**M6 — the Commander.** Decision theory, not ML: act when
`p·(COST_FAILURE − COST_PREEMPT) > (1−p)·COST_FALSE_DISPATCH`, which reduces
exactly to p > 0.4375 — **derived** from the cost model, never hard-coded.
Tiered autonomy: auto (throttle/shed/switch/reboot), approve (crew
pre-dispatch), never (config changes).

**M7 — counterfactual study.** Four arms on identical schedules per seed:
A no-AI, B advisory, C autonomous, D clairvoyant. Committed headline run,
**30 seeds × 10 days** (`reports/counterfactual_summary.json`):

```
arm   availability   downtime min     cost tower-min  pre-empted  false
A     98.75 ± 0.02    54,033 ± 775     104,229            0        0
B     98.75 ± 0.02    54,070 ± 773     104,385            0        4.4
C     98.88 ± 0.02    48,369 ± 770      84,811          448        3.8
D     98.96 ± 0.02    44,857 ± 743      83,121          491        0.0
```

**C cuts 5,664 downtime tower-minutes and 18.6% of OPEX vs no-AI — 61.7% of
the clairvoyant bound.** Advisory (B) is indistinguishable from no-AI: human
approval latency eats the entire predictive advantage — the argument for
autonomy. D bounds *predictive* maintenance, not omniscience: instant faults
are excluded by construction.

---

## Honest limitations

- **It is a simulation, not a network.** The fault rate is ~100× real,
  deliberately, so a demo shows something. The physics is COST-231 + documented
  approximations, not a drive test. Nothing here claims to transfer to a real
  LTE network.
- **The AI learns from its own simulation.** The models are trained on data
  this engine generates, so they are internally consistent by construction.
  Real-world generalisation is unproven and untested — say so in interviews.
- **COST-231 extrapolated** from 2000 → 2100 MHz costs 0.72 dB, ~10× smaller
  than the injected 6–8 dB shadow fading. Documented, not hidden.
- **Dust is mechanical damage** (filter clogging, soiling, connector drift),
  not RF attenuation — dust does not attenuate 2.1 GHz.
- **75/25 gradual/instant split** sets an honest recall ceiling: 25% of
  faults are unpredictable by construction.
- **The Doctor's 99% is on already-broken nodes** — the hard part is the
  Oracle's 0.45 recall, and that is the number to defend.
- **The rules fallback is catastrophically bad** (B1: precision ~0.04). The
  dashboard degrades to it gracefully when models are missing — it is a
  robustness demo, not a feature.
- **Determinism is within a machine.** Float reduction and library versions
  can differ across platforms; the I3/I4 tests assert within-machine
  determinism and machine-relative performance.
- **One city, one operator, no user mobility** — no handover, no inter-cell
  interference beyond the neighbour ripple, no demand shocks beyond traffic
  curves.

---

## Invariants (why the architecture is the way it is)

Tested, not conversational (tests/test_invariants.py):

| # | Guard |
|---|---|
| I1 | the engine owns time — no `engine.step()` in route handlers |
| I2 | the engine is pure — banned imports enforced by an AST test |
| I3 | determinism — seed 42 twice ⇒ identical state at tick 5000 |
| I4 | `step()` fast — hardware-calibrated, asserts on a ratio |
| I5 | one source of truth — no colours/thresholds in `web/` |
| I6 | frontend renders, never computes |
| I7 | headless first — every feature testable without a browser |
| I8 | no metric without a holdout |
| I9 | five separate RNG streams |
| I10 | exogenous event schedule, generated pre-run, immutable |
| I11 | features never peek ahead |
| I12 | no subsystem deleted to improve a number |

---

## Roadmap

- [ ] Add a GitHub Actions badge to the README once CI is green
- [ ] Publish a screenshot / animated GIF of the dashboard
- [ ] Add a `.env.example` for the environment variables
- [ ] Document generating the demo world (M8) in more depth
- [ ] Package as a proper PyPI-installable project (`pyproject.toml`)

---

## Tech stack

- **Runtime:** Python 3.12+, FastAPI, Uvicorn, Pydantic
- **AI:** XGBoost, PyTorch (GRU), scikit-learn, NumPy, pandas
- **Frontend:** Leaflet (bundled, offline-capable), vanilla JS/HTML/CSS
- **Dev:** pytest, GitHub Actions (Linux + Windows)

---

## License

[MIT](LICENSE) © 2026 AutoNOC Project Authors



