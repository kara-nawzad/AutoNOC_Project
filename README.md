# AutoNOC — simulated telecom operations command center

[![Live demo](https://img.shields.io/badge/demo-live-10b981?logo=flydotio&logoColor=white)](https://autonoc-project.fly.dev/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/UI-React%2018-61DAFB?logo=react&logoColor=111)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![O-RAN inspired](https://img.shields.io/badge/architecture-O--RAN%20inspired-5b6abf)](#architecture)
[![Fly.io deploy workflow](https://github.com/kara-nawzad/AutoNOC_Project/actions/workflows/ci.yml/badge.svg)](https://github.com/kara-nawzad/AutoNOC_Project/actions/workflows/ci.yml)

**AutoNOC is a deterministic simulation of a 300-site LTE network scenario centered on Sulaymaniyah,
Iraq; the site positions and telemetry are modeled, not live operator data.** A pure-Python engine
generates radio, traffic, weather, power, fault, and crew state; an XGBoost Doctor diagnoses current
faults, a PyTorch GRU Oracle scores 60-minute failure risk, and an expected-value Commander applies
simulated actions. A FastAPI service feeds a React and TypeScript operations console, while
matched-seed experiments compare policies and keep model-cost proxies separate from explicitly
assumption-based dollar scenarios.

> **Scope:** This is a portfolio simulation and operations-console prototype—not a production NOC,
> an integration with a live mobile network, or an O-RAN-certified implementation. Its models are
> trained and evaluated on simulator-generated data.

**[Open the live demo](https://autonoc-project.fly.dev/)** · [Frontend guide](frontend/README.md) ·
[Design vision](docs/DESIGN_VISION.md)

---

## Contents

- [What you can explore](#what-you-can-explore)
- [Architecture](#architecture)
- [Standards-inspired telemetry and modeled infrastructure](#standards-inspired-telemetry-and-modeled-infrastructure)
- [Study results](#study-results-m7-counterfactual)
- [Illustrative ROI display](#illustrative-roi-display-not-measured-savings)
- [Telemetry history and completed-run summaries](#telemetry-history-and-completed-run-summaries)
- [Run locally](#run-locally)
- [Windows demo and diagnostic scripts](#windows-demo-and-diagnostic-scripts)
- [Tests and reproducibility](#tests-and-reproducibility)
- [API overview](#api-overview)
- [Deployment](#deployment)
- [Repository layout](#repository-layout)
- [Honest limitations and interpretation](#honest-limitations-and-interpretation)
- [License](#license)

## What you can explore

- A seeded, five-minute-tick simulation of **300 modeled LTE sites**, ten districts, fiber rings,
  and a ten-team maintenance fleet.
- A React 18 / TypeScript command center for network state, incidents, site inspection, crew
  movement, AI actions, traffic, power, and current-run history.
- Repeatable scenario controls: pause, resume, step, speed, AI enable/disable, supported fault
  injection, and a fiber-cut demonstration.
- An ML pipeline with separate diagnosis and prediction roles, plus an expected-value policy layer.
- A four-arm, matched-seed study that exposes both operational outcomes and a clearly labeled
  model-cost proxy.
- Isolated, anonymous browser sessions: each visitor receives a server-issued cookie and an
  independent in-memory simulation, controls, AI state, approvals, telemetry, and run history.
- A MapLibre vector basemap using OpenFreeMap-hosted OpenMapTiles/OpenStreetMap data, rendered
  beneath Leaflet overlays. A schematic fallback is available when the street layer cannot load;
  online street tiles require network access.

At 1× speed, the server advances about one simulation tick per second; one tick represents five
simulated minutes. The simulation defaults to seed `42` with AI disabled. Seed `131` is used by the
included Windows demo launchers.

**Stack:** Python 3.12, FastAPI, and Uvicorn; React 18, TypeScript, Vite, Tailwind CSS, Framer
Motion, Leaflet, and MapLibre GL; XGBoost and PyTorch; pytest, Vitest, and Playwright; multi-stage
Docker deployment to Fly.io.

## Architecture

```text
┌────────────────────────────────────────────────────┐
│ autonoc/engine                                      │
│ Deterministic seeded simulation; standard library   │
│ only; NOCEngine.step() owns simulation time         │
└─────────────────────────┬──────────────────────────┘
                          │ locked state snapshot
             ┌────────────▼─────────────┐
             │ autonoc/ai               │
             │ XGBoost Doctor + GRU     │
             │ Oracle + Commander rules│
             └────────────┬─────────────┘
                          │ inference results
             ┌────────────▼─────────────┐
             │ autonoc/api (FastAPI)    │
             │ server clock, controls,  │
             │ config, snapshots, API   │
             └────────────┬─────────────┘
                          │ relative HTTP requests
             ┌────────────▼─────────────┐
             │ frontend/                │
             │ React + TypeScript UI    │
             └──────────────────────────┘
```

- **Engine:** `NOCEngine.step()` advances the simulation. In normal service operation, the FastAPI
  lifespan task owns the clock; GET requests are read-only. Engine code is kept separate from HTTP,
  ML, and rendering dependencies.
- **Doctor:** XGBoost multiclass diagnosis from a 71-feature snapshot. Its target is a fault class
  in the simulated world, not an operator-confirmed real incident.
- **Oracle:** GRU over a contiguous 12-tick, 12-channel history window—60 simulated minutes—to
  estimate failure risk. Instant faults cannot be forecast from prior telemetry.
- **Commander:** an expected-value policy, not a learned model. Its internal break-even threshold is
  derived from the configured failure, pre-emption, and false-dispatch model costs (`90`, `45`, and
  `35` tower-minute units, respectively), yielding `p > 0.4375` for the base decision.
- **API and UI:** FastAPI serves `/api/config`, bounded simulation snapshots, controls, and
  telemetry history. The React client presents server-derived operational state. UI formatting and
  the explicitly labeled ROI scenario are presentation logic, not the simulation's decision policy.

The architecture borrows concepts such as rApps and policy control from O-RAN, but it does not
implement O-RAN interfaces, connect to a RIC, or claim standards certification.

## Standards-inspired telemetry and modeled infrastructure

Standards terms are used as labels and approximations over synthetic counters. They are not evidence
of conformance or production-grade PM/FM measurement.

| Display / behavior   | What the simulator actually does                                                                                                                                                                        |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **VSWR alarm**       | Converts return loss `S11` to VSWR; the alarm threshold is **1.5**, approximately `S11 = −14 dB`. This is distinct from the modeled hard-fault thresholds: `S11 = −10 dB`, or `−13 dB` under high wind. |
| **PRB congestion**   | Uses an **85%** congestion floor in the modeled offered-load counter.                                                                                                                                   |
| **CQI**              | Derives CQI from SINR with a linear approximation inspired by 3GPP TS 36.213; it is not a full link-adaptation implementation.                                                                          |
| **QCI 9 throughput** | Displays the simulator's generated best-effort throughput estimate.                                                                                                                                     |
| **E-RAB drop rate**  | The UI labels a **mean synthetic site counter** as an E-RAB drop proxy; it is not a bearer-weighted production KPI.                                                                                     |
| **Alarm severity**   | Uses ITU-T X.733-style severity labels such as CRITICAL, MAJOR, MINOR, WARNING, and CLEARED.                                                                                                            |

The simulator assigns these simplified power-configuration labels from each district's grid tier;
they are scenario abstractions, not inventories of surveyed sites:

| Type  | Configuration                                 | Example scenario                 |
| ----- | --------------------------------------------- | -------------------------------- |
| **A** | Grid with standby diesel generator (DG)       | Grid-connected sites             |
| **B** | Hybrid DG and VRLA battery                    | Bakrajo / unstable-grid scenario |
| **C** | Off-grid solar PV, LFP battery, and DG backup | Exposed Goizha scenario          |

ATS failure-to-crank and abnormal fuel-drop events are simulated. They are not derived from operator
incident records or measured Iraqi fuel-loss statistics.

## Study results: M7 counterfactual

The checked-in report compares four policies over **30 matched seeds × 10 simulated days per seed**.
Each arm sees the same exogenous schedule for a given seed. The following values are means per
ten-day arm run from [`reports/counterfactual_summary.json`](reports/counterfactual_summary.json);
availability includes the report's 95% confidence interval.

| Arm   | Policy                          |  Availability | Downtime (tower-min) | Pre-empted episodes | False dispatches | Team-occupation hours | Cost proxy (tower-min units) |
| ----- | ------------------------------- | ------------: | -------------------: | ------------------: | ---------------: | --------------------: | ---------------------------: |
| **A** | No AI; reactive                 | 98.75% ± 0.02 |               54,033 |                   0 |                0 |                773.33 |                   104,229.00 |
| **B** | Advisory; 2-tick approval delay | 98.75% ± 0.02 |               54,070 |                   0 |             4.37 |                778.90 |                   104,384.83 |
| **C** | Autonomous Commander            | 98.88% ± 0.02 |               48,369 |              448.03 |             3.77 |                781.89 |                    84,811.33 |
| **D** | Predictive upper bound          | 98.96% ± 0.02 |             44,856.5 |              490.63 |             0.03 |                813.40 |                    83,120.67 |

For **C versus A**, the report records:

- **5,664 fewer tower-minutes** of aggregate downtime (about 10.5% lower) and a **0.13
  percentage-point** increase in availability.
- **19,417.67 fewer cost-proxy units** (about 18.6% lower). The proxy is
  `90 × activated + 45 × pre-empted + 35 × false dispatches`; these are model units, **not dollars
  or measured OPEX**.
- **8.56 more team-occupation hours** in C. The study does not show reduced crew occupation or
  payroll hours.
- C captures **61.7% of the A-to-D downtime-reduction headroom** in this study. Arm D has perfect
  knowledge of gradual scheduled faults while retaining the modeled crew/travel constraints; instant
  faults remain unpredictable, so D is a predictive upper bound, not omniscience.

In this configuration, B's approval delay is **two ticks = ten simulated minutes**, while C's is one
tick = five simulated minutes. B produced no pre-empted episodes in the checked-in report.
Pre-emption and dispatch counts are simulator ledger events, not operator-confirmed incidents. These
are results for this simulator and policy configuration—not monthly forecasts, measured network
savings, or a general claim that human approval always removes predictive value.

## Illustrative ROI display, not measured savings

The live ROI pill applies declared scenario assumptions to current-run counters. It is **not** a
paired live AI-on/AI-off experiment, an invoice, or a measured saving per incident. The current
presentation formula is:

```text
downtime_hours_estimate = pre-emptions × 4.2 − false_dispatches × 0.5
avoided_truck_rolls_assumed = max(0, pre-emptions − false_dispatches)
illustrative_USD = downtime_hours_estimate × $120
                   + avoided_truck_rolls_assumed × $180
```

The `4.2` repair hours, `0.5` travel hours, `$120` per downtime hour, and `$180` per assumed net
avoided truck roll are illustrative inputs, not measured operator rates. One pre-emption with no
false dispatch produces an illustrative **$684** under those assumptions; it does not establish that
an actual incident saved $684.

## Telemetry history and completed-run summaries

- The **30m**, **24h**, and **7d** selector reads simulated telemetry samples recorded by the API
  clock during the current run, at the engine's five-minute simulated-time resolution. Those windows
  contain up to **7**, **289**, and **2,017** samples, respectively; they are simulated-time
  windows, not wall-clock lookbacks.
- History is in memory and bounded to **2,017 samples** (seven simulated days, including the initial
  sample). A newly started run begins a new history; longer windows fill as simulation time
  advances.
- The simulation runs for 30 simulated days, then records an aggregate completion summary and starts
  a fresh Day 1 world using the same seed and network layout. This is a new run, not a continuation.
- Each browser gets an `autonoc_session` HTTP-only, high-entropy cookie. The server resolves that
  cookie to a process-local session; the browser never supplies a session identifier. Engines,
  speed, pause state, AI settings, fault/fiber controls, approvals, current-run telemetry, and
  displayed history are session-scoped, and run IDs are checked only within that session.
- Live sessions are intentionally in memory and are not restored after a restart. By default the
  single Fly machine accepts **8 active sessions** and expires sessions after **30 minutes idle**.
  Configure `AUTONOC_MAX_SESSIONS` and `AUTONOC_SESSION_IDLE_SECONDS` for a deployment. A full
  registry returns HTTP 503 with `code: session_capacity`; closing idle dashboards frees capacity.
  The model bundle is loaded once per process and shared read-only by inference workers. These
  limits keep the design appropriate for the existing 1 shared CPU / 1 GB Fly machine.
- Completed-run History is separate: the API stores aggregate completion summaries in SQLite under
  `AUTONOC_DATA_DIR` (default `./data`). On Fly.io, `/data` is mounted on the app's persistent
  volume.
- **Summary storage is not a live-state checkpoint.** A process restart does not restore or resume
  the prior simulation state.

## Run locally

### Requirements

- Python **3.12+**
- Node.js **22+** and npm (to build or develop the React frontend)
- A CPU-capable PyTorch install for GRU inference; the committed model artifacts are under `models/`

From the repository root:

```bash
python -m venv venv
```

Activate it, then install dependencies. On Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

On macOS/Linux:

```bash
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

Installing CPU PyTorch first avoids selecting the larger default PyPI build where the CPU wheel is
suitable. The committed XGBoost, GRU, scaler, and feature metadata artifacts mean you do **not**
need to regenerate training datasets just to launch the app.

Build the frontend and start the API:

```bash
npm ci --prefix frontend
npm run build --prefix frontend
python -m uvicorn autonoc.api.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The production build is written to `autonoc/web/dist`; FastAPI serves
it at `/`. For hot reload, keep the API running and use a second terminal:

```bash
npm run dev --prefix frontend
```

Open the Vite URL shown in the terminal (normally port `5173`). Vite proxies relative `/api`
requests to the local API. See [`frontend/README.md`](frontend/README.md) for frontend controls,
contracts, and browser-test setup.

To start the seed-131 demo with AI enabled manually (PowerShell):

```powershell
$env:AUTONOC_SEED = "131"
$env:AUTONOC_AI = "1"
python -m uvicorn autonoc.api.main:app --host 127.0.0.1 --port 8000
```

The AI defaults to disabled (`AUTONOC_AI=0`); it can also be enabled from the dashboard. Interactive
API documentation is at <http://127.0.0.1:8000/docs>.

### Environment variables

| Variable               | Default  | Purpose                                                                    |
| ---------------------- | -------- | -------------------------------------------------------------------------- |
| `AUTONOC_SEED`         | `42`     | Initial deterministic simulation seed; the demo scripts use `131`.         |
| `AUTONOC_AI`           | `0`      | Set to `1` to enable the Commander at startup.                             |
| `AUTONOC_AUTO_APPROVE` | `0`      | Auto-approval delay in seconds; `0` leaves crew actions for manual review. |
| `AUTONOC_DATA_DIR`     | `./data` | Directory for completed-run SQLite summaries.                              |

## Windows demo and diagnostic scripts

The root scripts are intentionally retained for demo users:

- **`Start-Demo.ps1`** starts a detached local server, sets seed `131` and AI on, writes
  `server.log` / `server.err`, and opens the dashboard. It looks for `venv\Scripts\python.exe`, then
  falls back to `python` on `PATH`.
- **`Start-Demo.bat`** runs the server in its window and opens the dashboard. It expects the project
  `venv` to exist.
- **`Stop-Demo.bat`** stops the local server listening on port `8000`; it is the matching stop
  helper for both launchers.
- **`diag.ps1`** checks the React source/build files, model artifacts, the backend health endpoint,
  tick advancement, and Python import status. Run it from PowerShell with `.\diag.ps1` after
  activating the project environment.

Create the expected Windows environment with the quickstart above before using `Start-Demo.bat`. For
the detached PowerShell launcher, allow scripts in the current PowerShell process if needed:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\Start-Demo.ps1
```

## Tests and reproducibility

Run the Python and frontend suites from the repository root:

```bash
python -m pytest tests/ -q
npm test --prefix frontend
npm run build --prefix frontend
npm run format:check --prefix frontend
```

Playwright browser tests require a separately installed Chromium and an isolated test API; consult
[`frontend/README.md`](frontend/README.md) before running them. The active
[GitHub Actions workflow](.github/workflows/ci.yml) is **deploy-focused; it does not run these test
suites**.

Optional dataset/model and study commands:

```bash
python -m autonoc.scripts.sanity_check
python -m autonoc.ai.dataset
python -m autonoc.ai.train
python -m autonoc.ai.seqdata
python -m autonoc.ai.oracle
python -m autonoc.scripts.counterfactual --seeds 30 --days 10 --workers 8
```

Dataset generation writes regenerable files under `data/`, which is ignored. Training commands
replace tracked files under `models/`; the counterfactual study rewrites the checked-in
`reports/counterfactual.csv` and `reports/counterfactual_summary.json`. Preserve or back up the
committed artifacts before regenerating them if you want to keep the published baseline unchanged.
The trained `.npz` scaler/statistics files in `models/` and the study CSV/JSON in `reports/` are
intentional repository artifacts and are not scratch files.

## API overview

Base URL: `http://127.0.0.1:8000`. Interactive Swagger documentation is available at `/docs`.

| Method | Endpoint                                                       | Description                                                               |
| ------ | -------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `GET`  | `/api/health`                                                  | Current tick, seed, run ID, pause state, speed, and AI state.             |
| `GET`  | `/api/config`                                                  | Server-owned status labels, colors, thresholds, gauges, and map metadata. |
| `GET`  | `/api/delta?since=<tick>`                                      | Read-only bounded snapshot for the dashboard.                             |
| `GET`  | `/api/telemetry/history?timeframe=30m&run_id=<id>`             | Current-run telemetry samples; timeframe is `30m`, `24h`, or `7d`.        |
| `GET`  | `/api/history`                                                 | Completed-run aggregate summaries, not resumable state.                   |
| `POST` | `/api/control/pause?run_id=<id>`                               | Pause the simulation.                                                     |
| `POST` | `/api/control/resume?run_id=<id>`                              | Resume it.                                                                |
| `POST` | `/api/control/step?run_id=<id>`                                | Step once while paused.                                                   |
| `POST` | `/api/control/speed?value=1&run_id=<id>`                       | Set simulation speed from 0.25× to 10×.                                   |
| `POST` | `/api/control/ai?enabled=true&run_id=<id>`                     | Enable or disable AI.                                                     |
| `POST` | `/api/control/inject?node_id=<id>&kind=<1..5>&run_id=<id>`     | Inject one supported node fault.                                          |
| `POST` | `/api/control/cut-fiber?ring_id=<id>&isolate=true&run_id=<id>` | Trigger the fiber-cut demonstration.                                      |
| `POST` | `/api/control/approve/<action_id>?run_id=<id>`                 | Approve a pending action.                                                 |
| `POST` | `/api/control/veto/<action_id>?run_id=<id>`                    | Veto a pending action.                                                    |

Control requests use the current `run_id`; a command from an older run is rejected. The API's
simulation controls are unauthenticated and are intended for a controlled demo environment, not
direct exposure as an operator service.

## Deployment

The app is deployed at [autonoc-project.fly.dev](https://autonoc-project.fly.dev/). The existing
Fly.io app is built from the repository's multi-stage `Dockerfile`: Node 22 builds the React assets,
then a Python 3.12 runtime serves FastAPI and the bundled frontend. `fly.toml` configures the `ams`
primary region, one shared-CPU / 1 GB machine, and the `/data` volume for completed-run summaries.

The active [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `flyctl deploy --remote-only`
on pushes to `main` and pull requests targeting `main`, and enforces a single primary-region
simulation machine. PR-triggered runs use the existing Fly app; they are deployments, not staging
checks. Despite the workflow's name, it is **not** a Python/frontend test gate. Tests should be run
separately before merging.

## Repository layout

```text
autonoc/
  engine/             Pure seeded simulation: network, radio, power, faults, crews
  ai/                 Feature pipeline, Doctor, Oracle, and inference worker
  api/                FastAPI routes, schemas, telemetry projections, run summaries
  scripts/            Sanity check, counterfactual, seed-casting, and export tools
  web/                Legacy static fallback; current UI is built from frontend/
frontend/
  src/                React command center, API client, charts, map, tests
models/               Tracked trained model, scaler, and metadata artifacts
reports/              Tracked counterfactual CSV and JSON summary
tests/                Python engine, AI, lifecycle, and API contract tests
docs/                 Project and design documentation
Start-Demo.ps1        Windows detached demo launcher
Start-Demo.bat        Windows console demo launcher
Stop-Demo.bat         Windows local server stop helper
diag.ps1              Windows environment and live-server diagnostic
```

## Honest limitations and interpretation

- **Synthetic scenario, not network telemetry.** Site locations, traffic, weather, counters, faults,
  power events, and maintenance schedules are simulated; rates are model parameters, not calibrated
  operator frequencies. The model has not been validated against drive tests, operator OSS data, or
  live network incidents.
- **Propagation approximation.** COST-231 Hata is modeled at **2100 MHz**, outside its nominal
  1500–2000 MHz range; that is an extrapolation, not a validated 2100 MHz deployment model.
- **Standards vocabulary is not certification.** CQI mapping is approximate, E-RAB drop is a
  synthetic site-level proxy, and the O-RAN relationship is architectural inspiration only.
- **ML generalization is unknown.** The Doctor and Oracle are trained on this simulator's own
  generated data. Strong simulated metrics do not establish performance on unseen operators,
  geographies, vendors, or real alarms. Seed repeatability is intended within a consistent runtime;
  library versions and floating-point behavior can differ across platforms. The simulation does not
  model user mobility or production handover behavior.
- **The forecasting ceiling is structural.** A fault with no predictive telemetry cannot be
  pre-empted from history. Arm D leaves instant faults unpredicted as well.
- **Study economics are model units.** M7's cost proxy is not cash expenditure, and study averages
  are not per-month savings forecasts. The dollar ROI display is assumption-based and intentionally
  separate.
- **Not a secure operator service.** Demo control endpoints do not implement user authentication or
  authorization. Do not expose a writable instance to an untrusted network.
- **Street basemap requires external access.** The vector tiles are not bundled; if the provider or
  WebGL is unavailable, the UI falls back to its schematic map.

## License

MIT — see [`LICENSE`](LICENSE).
