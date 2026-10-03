# AutoNOC — Project study and change-readiness review

**Reviewed:** 2026-10-03  
**Baseline:** commit `15cbd3d`, branch `arena/01a10260-autonoc-project`  
**Scope:** architecture, simulation, AI, API, dashboard, evaluation, tests, deployment, and safe change boundaries.

> This is an independent review of the implementation, not a restatement of the README. No application code, tests, model artifacts, or committed results were changed. This document is the only tracked addition.

## 1. Executive assessment

AutoNOC is a substantial **simulation-backed telecom operations demo**: 300 synthetic LTE sites around Sulaymaniyah, weather and fault generation, maintenance crews, root-cause correlation, ML diagnosis/prediction, automated decisions, and an animated operations dashboard.

The strongest foundation is the separation of a standard-library-only engine from ML, HTTP, and rendering. The engine can run headlessly, the model artifacts are included, and the existing regression suite passes with dependencies installed. Those are good foundations for incremental changes; a wholesale rewrite is not necessary.

However, **passing tests do not currently guarantee correct live telemetry or scientifically clean AI evaluation**. Additional probes found significant gaps:

1. Most normal telemetry changes never reach delta clients.
2. Warning updates are globally consumed by the first reader; same-tick controls can disappear from the stream.
3. The optimized random helper is not uniform and suppresses configured grid dropout/restoration events.
4. Oracle operating thresholds are selected using test labels, and live decisions use a different threshold on uncalibrated scores.
5. Simulator ground truth suppresses false-positive tier-1 actions, making the autonomous policy more favorable than a telemetry-only policy.
6. The advertised live rules fallback is not actually connected to the inference scoring path.
7. The public controls have no authorization, and user-supplied cut descriptions reach an HTML rendering sink.
8. CI deploys without running tests, including on pull-request events.

**Readiness:** suitable for controlled demonstrations and further development. It needs correctness, evaluation, and deployment hardening before being described as an operational NOC platform or used to support strong production ROI claims.

---

## 2. What exists today

### Product and scope

- **World:** 300 nodes, ten aggregation districts, ten maintenance teams, and ten rings under the current configuration.
- **Clock:** one tick represents five simulated minutes; the API aims for approximately one tick per wall-clock second at 1×.
- **Fault classes:** healthy, congestion, overheat, RF/antenna, power, backhaul.
- **Exogenous schedules:** node faults, weather, and fiber cuts generated at initialization from a seed.
- **Operations:** fault progression, remote resets, self-healing, prioritized dispatch, skill-sensitive repairs, pre-positioned crews, and a fault ledger.
- **AI:** XGBoost Doctor, GRU Oracle, deterministic expected-value Commander.
- **User interface:** map, animated KPIs, fault feed, district list, node inspector, AI panel, command palette, injection and simulation controls.
- **Evaluation:** four-arm, seed-paired offline experiments with committed CSV/JSON summaries.

### What it is not

There is no real network ingestion, database, authentication system, durable incident store, tenant isolation, or actual O-RAN A1 integration. The O-RAN/rApp terminology is architectural framing rather than protocol interoperability. The 3GPP-style values include approximations and relabeled synthetic telemetry, not measurements from a standards-compliant LTE stack.

All users of one server process control the same in-memory simulation. Restarting the process resets it. Multiple Uvicorn workers or multiple independent machines would each own a different world unless state ownership is redesigned.

### Technology

| Area | Current implementation |
|---|---|
| Backend | Python, FastAPI, Uvicorn, Pydantic |
| Simulation | Python standard library, mutable dataclasses |
| ML | NumPy, pandas, scikit-learn, XGBoost, PyTorch |
| Frontend | Vanilla JavaScript, HTML, CSS, bundled Leaflet |
| Transport | HTTP polling with a simulation-tick cursor |
| Testing | pytest, seven test modules, 87 collected tests |
| Deployment | Multi-stage Docker image, Fly.io, GitHub Actions |
| Packaging | Run from repository root; no `pyproject.toml` or dependency lock |

React, Vite, TypeScript, Framer Motion, and deck.gl are **planned**, not installed parts of this application. Several sidebar entries are placeholders for that future phase.

---

## 3. Architecture and execution flow

```text
config + placement + topology + seeded schedules
                       |
                       v
             NOCEngine.step()
                       |
        mutable node/team state + history + ledger
                  /                 \
                 v                   v
      feature/window snapshot     API readouts
                 |                   |
        Doctor + Oracle              |
                 |                   |
        verdicts written back        |
                 |                   |
        Commander on next step       |
                                     v
                         config / snapshot / delta
                                     |
                                     v
                         browser state maps + UI
```

### Runtime ownership

`autonoc/api/main.py` constructs a module-global engine. Its lifespan starts:

1. An asyncio simulation loop, which sends engine stepping to a worker thread.
2. A separate `InferenceWorker`, which snapshots engine inputs under a shared lock, scores outside the lock, and publishes verdicts under the lock.

A manual step endpoint also advances the engine through the same locked stepping helper. GET routes do not advance time, which is a good separation. But the GET implementation does mutate warning-delivery bookkeeping; that compromises its claimed idempotence.

### Tick ordering

`NOCEngine.step()` performs:

1. Tick increment and weather lookup.
2. Commander actions, if enabled.
3. Mitigation decay.
4. Scheduled node faults and fiber cuts.
5. Gradual degradation advancement.
6. Per-node traffic, CPU, dust, thermal, radio, power, self-heal, and history capture.
7. Neighbor ripple effects.
8. Reactive dispatch and remote resets.
9. Crew movement, standby, repair, and return.
10. Watchdog recovery.

**Important change boundary:** history capture happens before ripple, dispatch, and repairs. Sequence training reads state after the entire step, while live Oracle inference reads history captured earlier. These are not always the same samples.

### Main source map

| File/module | Responsibility | Change impact |
|---|---|---|
| `engine/config.py` | Constants, fault/status definitions, display metadata, costs | Broad: simulation, AI, schemas, UI, reports |
| `engine/models.py` | Node, crew, ring, cut, incident types; history and serialization | Broad data contract |
| `engine/engine.py` | Tick orchestration, fault lifecycle, ledger, repairs, Commander hooks | Highest behavioral coupling |
| `engine/placement.py` | Coverage grid, roads, district morphology | Geography, distances, training distribution |
| `engine/network.py` | Network assembly, neighbor graph, ring construction | Correlation, routing geometry, crews |
| `engine/physics.py` | Radio, load, thermal, dust, power calculations | Telemetry and learned distributions |
| `engine/faults.py` | Schedule generation and degradation curves | Labels, predictability, evaluation |
| `engine/noise.py` | Precomputed random/noise source | Nearly every physical trajectory |
| `engine/dispatch.py` | Correlation, incident priority, crew selection | Downtime and fleet utilization |
| `engine/commander.py` | Decision economics and reversible actions | Policy and experiment outcomes |
| `ai/features.py` | Shared Doctor feature contract | Must match saved model/scaler |
| `ai/dataset.py`, `ai/train.py` | Doctor data generation and training | Dataset/metric provenance |
| `ai/seqdata.py`, `ai/oracle.py` | Oracle windows and benchmark | Forecasting validity |
| `ai/serve.py` | Artifact loading, batch scoring, worker lifecycle | Live AI reliability |
| `api/main.py`, `api/schemas.py` | Control/data endpoints and validation | Client contract and concurrency |
| `web/app.js` | Client cache, polling, map, controls, animation | UI behavior and derived displays |
| `web/index.html`, `web/styles.css` | Layout and presentation | Mostly low-risk visual changes |
| `scripts/counterfactual.py` | A/B/C/D study runner | Published benefit claims |
| `scripts/cast_seed.py` | Demo seed search and verification | Demo narrative |
| `scripts/sanity_check.py` | Headless telemetry/performance report | Fast physics sanity check |
| `scripts/export_sites.py` | Geographic exports | Export metadata correctness |

The current UI is concentrated in one approximately 766-line JavaScript file. The engine orchestration is approximately 788 lines. Both are still tractable, but new features should favor small extracted components/functions rather than growing these files indefinitely.

---

## 4. Simulation and operations study

### Geography and network

Placement combines a coverage grid, road corridors, and district-specific character. Sites have generations, grid tiers, elevations, criticality, neighboring sites, and ring membership. Faruk-area critical sites influence reactive dispatch priority. Topology construction is done once, avoiding repeated spatial work per tick.

The configuration's district counts act as weights/nominal quotas, not actual enforced counts. At seed 42, examples include Goizha **22 actual vs 18 configured**, Salim Street **47 vs 42**, and Rizgari **44 vs 38**. Runtime aggregation uses actual membership, but config/export documentation can show the nominal counts.

Ring construction has a more substantial issue: after closing the initial ring paths, leftover nodes are appended to `node_ids` without rebuilding segments. At seed 42, ring 0 has **31 members but only 12 segments**, and ring 1 has **48 members but only 29 segments**. Cut impact membership and displayed geometry therefore describe different topology.

### Physics

The code models COST-231-style path loss, radio quality, offered load, thermal dynamics, dust accumulation, batteries, generators, and grid events. It clamps many readings and derives VSWR/CQI/PRB values for display.

Important qualifications:

- Site power types A/B/C are labels derived from grid tiers, not separate equipment architectures. Type C sites still start grid-connected, and the same solar branch is available to all sites.
- `rain_fade_db()` and microwave link-margin constants exist, but no runtime call connects them to core failover or service availability. The dual-core story is not a complete working failover model.
- A backhaul-isolated node is set to zero throughput when the cut occurs, but the next radio update increases its throughput again while its status remains isolated. A probe observed **0 → 34.39** after one tick.
- A forced depleted-battery/daylight edge produces a negative battery percentage in the solar branch. This is an edge-state defect, not something observed during the two normal 1,000-tick schema sweeps.

### Randomness and determinism

Seeded initialization and separate schedule generation are sound design choices. Same-seed engine tests pass.

But deterministic is not the same as distributionally correct. `NoisePool.random()` maps a normal draw through a bounded squash:

```python
0.5 + 0.5 * (v / (1.0 + abs(v)))
```

That is **not uniform on [0,1)**. For seed 42, the full 65,521-value pool ranged from approximately **0.09745 to 0.90432**. Consequently, none of its draws could satisfy even the largest configured grid dropout probability, **0.0045**, or grid restoration probability, **0.06**.

This helper is passed to `update_power()`. Scheduled power faults can still change power conditions, but the configured spontaneous grid process is not behaving as documented. Fixing it will change the learned telemetry distribution and requires regenerated data, models, and experiments.

Also, some named independent RNG objects are not used by the hot path: traffic and power consume the same noise cursor, and operational events and remote repairs share `rng_ops`. Exogenous fault/weather/cut schedules remain matched between arms, but that does not imply identical unscheduled randomness after policies change state and conditional draw counts.

### Dispatch and accounting

The dispatcher retries outstanding work every tick and uses skill-sensitive expected completion time. That addresses a real class of fleet starvation problems. Crews move through `IDLE → EN_ROUTE → STANDBY/REPAIRING → RETURNING`.

Accounting limitations:

- A double cut creates one incident **per cut**; the current implementation can produce two fiber incidents, not necessarily the advertised one incident.
- Scheduled fiber cuts receive ledger entries but repairs do not resolve those entries. At seed 131/tick 600, the cut from tick 125 was physically repaired while its ledger entry still said `injected`.
- MTTR samples are dispatch-to-completion mission durations for crew missions, not a comprehensive fault-onset-to-restoration measure over every fault.
- The AI panel's `precision` is `pre_empted / (pre_empted + false_dispatches)`: it mixes soft-fault pre-emption counts with crew false dispatches. It is not conventional prediction precision, and successful crew pre-positioning is not represented as an equivalent true positive.
- `crew_hours_saved` sums configured repair times for pre-empted episodes; it is an estimate, not a measured difference from a matched no-AI run.

### Horizon

The API pre-generates 30 simulated days. After the horizon, the engine continues ticking, weather is clamped to the final scheduled weather, and no new scheduled node/fiber events exist. At 1×, the schedule lasts roughly **2.4 wall-clock hours**, or roughly **14.4 minutes at 10×**, excluding stepping overhead.

A long-running demo therefore needs explicit horizon completion, reset, or deterministic schedule extension.

---

## 5. AI pipeline and scientific validity

### Doctor

- Input contract: **71 features**, shared between training and serving.
- Inputs include current metrics, one-hour statistics, deltas/slopes, engineered margins, and static site attributes.
- Data plans: train seed 42/60 days, validation seed 90/12 days, test seed 99/20 days.
- Healthy rows are subsampled at generation; evaluation weights restore their frequency.
- Scaling is fitted on training data; episode disjointness is checked.
- The validation set is loaded and checked but is not used for model selection/calibration in the current training code.

The committed Doctor artifact contains **five classes**, rather than all six possible status codes. Its metrics omit backhaul. Backhaul diagnosis currently depends principally on topology/engine state, not evidence of a trained six-class classifier.

### Oracle

- Input: **12 contiguous samples × 12 raw channels**.
- Target: a scheduled node failure within the next 12 ticks/60 simulated minutes, for currently healthy nodes.
- Model: one-layer GRU, 64 hidden units, small dense head, 17,089 parameters.
- Baselines: always negative, trend rules, logistic regression, XGBoost.
- Generation plans: train seed 42/45 days, test seed 99/18 days; there is no Oracle validation split in the current pipeline.
- Negative windows are retained at 6%, and metrics use inverse retention weights.

#### Evaluation concerns

**Test-set threshold selection.** `oracle.py` calls `best_threshold(yte, scores, wte)` for learned baselines and the GRU. Threshold-dependent precision, recall, and economic benefit are therefore optimized on test labels. A separate validation/calibration set is needed. AUC-PR itself is threshold-independent, but model choice is also based on the same test benchmark.

**Serving threshold mismatch.** The committed GRU metrics use a threshold of approximately **0.95**. The live Commander acts using the cost-derived **0.4375** threshold. Those are not the same operating point, so the recorded precision/recall does not describe live policy decisions.

**Calibration.** Training uses subsampling and positive weighting; the sigmoid output is not automatically a calibrated natural-prevalence failure probability. The committed GRU Brier score is approximately **0.1032**. Using the committed weighted prevalence, even a constant-prevalence predictor would have Brier around **0.0174**. The model can rank risk usefully while providing poor probabilities for direct economic decisions.

**Train/serve mismatch.** `seqdata.py` reads final node attributes after `step()`, whereas serving reads `hist_fine`, captured before ripple/repair operations. At seed 5/tick 300, **11 healthy nodes** had a different final training-style row from the live-history row. Training also attempts to reset windows around faults; serving does not impose the same health-window policy.

**Target interpretation.** Labels come from scheduled onsets, not solely observed activations. Masked events and non-scheduled power/fiber conditions need explicit handling. The published recall is a window-level metric over generated labels; it is not a measured event-level recall specifically on gradual failures. The README wording about catching a proportion of the predictable 75% is not established by this metric.

**Seasonal claims.** The default runs start at day 220 and span 12–60 days, not an entire year. Statements that training sweeps all seasons overstate the default generation plan.

### Live serving

Good design choices:

- Models load once.
- Inference is batched rather than called 300 times independently.
- Input snapshotting and output publication are separated from the expensive score computation.
- The shared feature builder reduces Doctor schema drift.

Reliability issues:

- `rules_verdicts()` exists, but `_score_batch()` and `score_engine()` do not call it when models are missing. With both models absent, scores are zero, despite the displayed rules mode. A seed-5 probe produced **42 direct rule warnings versus zero above-threshold live-path scores**.
- Inference exceptions are caught and converted to missing scores without necessarily changing an already-selected `ml` mode, hiding degraded operation.
- `models_dir` changes a serving-module global; Oracle loading has its own separate model-directory global. Custom model directories do not cleanly select one coherent bundle.
- The saved feature order/channel metadata is not fully enforced at inference, especially if a future change preserves dimensions but reorders channels.
- `self._stop` shadows `threading.Thread._stop()`. Starting/stopping the worker and then calling `join()` reproduced `TypeError: 'Event' object is not callable`. Current shutdown does not join the worker, which avoids that call but leaves lifecycle cleanup incomplete.
- The worker wakes every 0.25 seconds and only scores on exactly divisible ticks. Fast simulation speeds can skip intended inference ticks.
- Auto-approval checking only runs on those scoring cycles, not as an independent wall-clock timer; pausing/stalls can delay it.
- No verdict timestamp/expiry or robust recheck prevents an in-flight inference result from being published after AI is disabled.

### Commander and experiment interpretation

The economic threshold calculation is understandable:

```text
act if p × (90 − 45) > (1 − p) × 35
therefore p > 35 / 80 = 0.4375
```

That is correct arithmetic **if p is a suitable calibrated probability and the costs represent actual policy consequences**.

The implementation uses hidden simulator state beyond telemetry:

- `_commander_hook()` checks the actual episode kind before applying a tier-1 action. False-positive soft-fault predictions on genuinely healthy nodes produce no throttle at all.
- A successfully applied tier-1 action immediately marks an actual gradual soft episode pre-empted and cancels it; success is not established by a physical trajectory under mitigation.
- `_standby_horizon()` uses the exact hidden `onset_tick` to set crew waiting duration.

Ground truth is appropriate for scoring and simulating physical outcomes. It should not silently decide whether an imperfect controller incurs the consequences of its chosen action. As written, false-positive tier-1 harm is suppressed, biasing the autonomous comparison favorably.

The study's arms also differ in more than human latency:

| Arm | Actual policy |
|---|---|
| A | Reactive dispatch, no AI |
| B | No automatic tier-1 mitigation; tier-2 approval after 2 ticks |
| C | Automatic tier-1 mitigation; tier-2 approval after 1 tick |
| D | Perfect knowledge of pending gradual faults with a dispatch heuristic and immediate approvals |

Thus, B≈A versus C>A does **not isolate human approval delay** as the explanation. It changes the available action policy too. D is a useful perfect-information reference policy, not a mathematically proven optimal planner/upper bound.

The reported cost is a synthetic **tower-minute cost proxy**, not measured monetary OPEX. A future study should include paired confidence intervals for A–C differences, not just separate per-arm intervals, and record model/code/config provenance.

---

## 6. API and client consistency

### API surface

| Purpose | Routes |
|---|---|
| Dashboard/assets | `/`, `/static/*` |
| Config | `GET /api/config` |
| Full snapshot | `GET /api/data` |
| Delta | `GET /api/delta?since=...` |
| Health | `GET /api/health` |
| Clock controls | pause, resume, step, speed |
| Demo events | inject, cut-fiber |
| AI controls | enable/disable, approve, veto |

Pydantic response models provide a useful boundary for physical ranges and event severity vocabulary. `/api/data` exists but is omitted from the README API table.

### Confirmed delta defects

**1. Normal telemetry does not advance the change marker.**

`ENodeB.snapshot()` records history but does not update `last_changed_tick`. Most physical updates likewise do not mark nodes changed. `_node_dicts()` filters using this marker.

Reproduction with seed 42:

- Read a full snapshot at tick 1.
- Advance one tick.
- Compare full snapshots: all **300** node payloads changed.
- Request delta since tick 1: only **1** node is returned.
- **299 changed nodes are omitted.**

The UI can continue to show stale readings while the server clock and network KPIs move. Ordinary timely polling never triggers the lag-based full resync, so the omitted telemetry is not repaired merely by waiting.

**2. Warning state is a global dirty flag.**

`_warn_sent` records the last warning sent by any request. Two clients with the same cursor do not independently receive the transition. A repeated same-cursor probe returned **one node, then zero** without an intervening step.

**3. Simulation tick is not a sufficient mutation cursor.**

Injecting a fault at a tick the client has already seen sets the node's change tick to that same value. Delta filtering uses `>`; the injected node and its log are omitted. This is especially visible while paused.

**4. Restart detection is absent.**

If a client cursor is ahead of the new process's tick, the server does not immediately force a reset. Add a run/session identifier as well as a monotonic state revision.

**Recommended contract:** a server-owned state revision independent of simulation time, plus a run identifier and per-entity revisions. Logs need their own monotonic sequence or explicit truncation/resync behavior. Tick remains useful as simulated time, not as the only delivery cursor.

### Concurrency and scaling

The engine remains a process-local singleton. Async GET handlers acquire a blocking `threading.Lock`; if stepping/inference snapshotting holds it, HTTP event-loop work can wait. This is tolerable at the measured scale, but moving the step off the loop does not eliminate all blocking paths.

Use a single state owner for this demo. Do not increase web worker count or horizontally scale it as if it were a stateless API.

---

## 7. Frontend study

### What works structurally

- Relative API URLs are appropriate for same-origin hosting and proxied previews.
- Config-driven labels, node colors, and inspector gauges reduce backend/UI drift.
- The master animation loop, spring interpolation, and animated paths are separate from polling.
- Browser state is organized with maps keyed by node/team/ring IDs.
- Poll errors update connection status; major boot errors are visible.

### Gaps and defects

- **Weakest-district command crashes:** `worst` stores an ID, but the comparison reads `worst.h.v`. Reproduced with the exact loop in Node.js.
- **Not purely render-only:** `absorb()` computes a custom power-risk score using hardcoded weights, district bands use hardcoded thresholds, and map center/zoom are hardcoded instead of using config. These contradict the strongest I5/I6 claims.
- **Risk is partly cumulative:** lifetime ATS/theft counters feed the risk gauge, so old resolved incidents can permanently raise current-looking risk.
- **Controls are optimistic:** pause/speed state changes locally without checking response success, and other users' control changes are not synchronized into these UI variables.
- **Full refresh does not clear all entity maps:** future network resizing/reset behavior needs explicit deletion and reconstruction handling.
- **Cut marker geometry:** the marker is placed at the path midpoint rather than the supplied cut coordinate.
- **Pending-action ETA units:** backend values are wall-clock seconds; UI appends `t` as if they were ticks.
- **Placeholders:** power, crews, counterfactual, and policy sidebar entries insert a phase-2 message rather than opening implemented views.
- **Offline limitations:** Leaflet code is bundled, but map tiles use Carto and fonts use Google; the full visual experience is not offline.
- **Accessibility/mobile:** no reduced-motion path was found; the layout has only a limited desktop-width media query, and several navigation elements are clickable divs. A browser/accessibility pass is still needed.
- **Motion implementation drift:** the animation hot path writes `innerHTML` for some counters despite the design document's prohibition. This is smaller than the data correctness issues, but worth cleaning up when componentizing.

A React migration can improve maintainability, but it will not correct the stale telemetry protocol or backend policy/evaluation issues. Fix the contract first.

---

## 8. Security and deployment

### Security posture

**Unauthenticated shared controls.** Anyone with network access can pause the simulation, change speed, inject faults, cut rings, enable AI, and approve actions. Wildcard CORS also permits cross-origin access. This may be intentional for a private demo, but it is not an operator authorization model.

**HTML injection path.** The cut endpoint accepts an arbitrary `cause` string, the engine inserts it into log text, and `feedItem()` inserts that log message with `innerHTML`. An inert `<b>AUDIT-MARKER</b>` probe passed unchanged into the API log. This establishes the unsafe source-to-sink path; no executable payload was needed. Use text nodes/escaping and validate cause values. Add a suitable content security policy as defense in depth, not as the only fix.

**Docker context hygiene.** `.dockerignore` excludes `.envrc` but not `.env`/`.env.*`, `venv/`, generated data, or ordinary runtime logs. `COPY . .` can package local files that Git ignores. No actual secret exposure was observed; this is a build-context risk.

### CI/CD

The active `.github/workflows/ci.yml` has only a deploy job, triggered on both pushes to main and pull requests targeting main. It does not run pytest before deployment. For same-repository PRs with secrets available, PR code may be deployed; fork PRs can instead fail for lack of secrets.

`docs/ci-proposed.yml` adds tests and a dependency on the test job, but it still needs an explicit deploy condition restricting deployment to the intended main-branch push event. Copying it unchanged does not fully resolve PR deployment behavior.

### Reproducible environment

Dependencies are unpinned. Model compatibility, test behavior, image size, and performance can change with each installation. The Torch requirement is not a reliable CPU-only installation strategy; the project itself documents the large default download risk.

The Docker image targets Python 3.12.14 and runs as the default root user. Fly configuration is one shared CPU/1 GB RAM with automatic stopping. CPU-only, version-pinned ML dependencies and explicit health/readiness behavior would make deployments more predictable.

Paths for static files, models, data, and reports are mostly relative to the working directory. Launching outside the repository root is not supported reliably. `.env.example` is documentation: the app reads process environment variables and does not automatically load an arbitrary `.env` file in the normal documented Uvicorn command.

The Windows launcher refers users to `Stop-Demo.ps1`, which is absent; `Stop-Demo.bat` exists. Start/stop scripts also operate on whichever process owns port 8000, so they are demo conveniences rather than safe general service management.

---

## 9. Verification performed

### Environment and limits

- Sandbox Python: **3.11.2**. A Python 3.12 download was attempted but blocked by external TLS/download failures. Therefore this review does not certify the target Docker/Python 3.12 build.
- An ignored `.venv` was created for verification.
- Successful ML verification used Torch **2.2.2**, NumPy **1.26.4**, and XGBoost **3.2.0**. The CPU-wheel host was unreachable, so Torch was installed from PyPI; inference ran on CPU.
- Test/replay commands used `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1` to avoid unnecessary numerical-library thread oversubscription.
- No full model retraining, full dataset regeneration, full 30-seed replay, production deploy, or visual browser/accessibility test was performed.

### Existing suite

```text
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python -m pytest tests/ -q -ra --durations=10

82 passed, 5 skipped in 85.09 seconds
```

The five skips require ignored generated datasets:

- train/test seed separation check;
- episode separation check;
- geography-memorization diagnostic;
- sequence contiguity check;
- raw sequence channel check.

An earlier dependency-incomplete run had two model-loading failures because Torch was unavailable. Those passed after Torch was installed; they are not unresolved repository test failures.

### Additional checks

| Check | Result |
|---|---|
| JavaScript syntax | `node --check autonoc/web/app.js` passed |
| HTTP smoke, in-process TestClient | `/`, JS asset, config, full snapshot, health returned 200 |
| Normal node schema sweeps | All node payloads validated through 1,000 ticks for seeds 42 and 131 |
| Headless seven-day sanity | 2,016 ticks; ~1.77 ms/tick; sampled mean availability 98.81% |
| Model loading | Committed Doctor and Oracle loaded successfully |
| Delta completeness | 299/300 changed nodes omitted in a one-tick probe |
| Same-cursor warning replay | One warning row on first read, zero on second |
| Same-tick injection | Control succeeded; node and log absent from delta |
| Random helper distribution | No seed-42 pool draw below maximum grid dropout/restore thresholds |
| Live rules path | Direct rules produced 42 warnings; missing-model scoring produced none |
| Oracle sample alignment | 11 healthy final-state/history mismatches at seed 5/tick 300 |
| Worker lifecycle | `join()` raised an Event-not-callable TypeError |
| Ring topology | Seed-42 membership/segment counts disagree |
| Fiber ledger | Repaired scheduled cut remained `injected` |
| Isolated throughput | Rose from zero while status stayed isolated |
| Daytime empty-battery edge | Negative battery value rejected by response schema |
| Command palette logic | Weakest-district comparison raised a TypeError |
| HTML source-to-sink | Inert markup accepted into log text rendered by an HTML sink |

### Partial counterfactual replay

A fresh **seed 1 × 10 days × four arms** replay used the committed models and current code. It ran in about 63 seconds and did not overwrite committed reports.

| Arm | Committed downtime tower-min | Current replay | Committed pre-emptions | Current replay |
|---|---:|---:|---:|---:|
| A | 52,085 | 51,920 | 0 | 0 |
| B | 52,110 | 51,920 | 0 | 0 |
| C | 45,790 | 45,655 | 472 | 473 |
| D | 42,720 | 42,725 | 514 | 514 |

The qualitative C-over-A improvement remains in this sample. Exact results do not reproduce under this review environment. Code/config drift and dependency/platform differences need recorded provenance before assigning the cause. This one-seed replay does not replace or validate the full published 30-seed headline.

### Documentation/artifact differences

| Metric | README | Committed artifact |
|---|---:|---:|
| Doctor precision | 0.993 | 0.98723 |
| Doctor recall | 1.000 | 0.99935 |
| Oracle GRU AUC-PR | 0.547 | 0.54643 |
| Oracle GRU recall | 0.450 | 0.44185 |
| GRU lift over XGBoost | 9.2% | approximately 8.9% |

Other drift includes the quickstart's old “64 passed” comment, stale coarse-history comments, Linux/Windows CI language despite the deploy-only workflow, completed roadmap items still unchecked, nominal district sizes, and claims of full-year training or implemented microwave failover.

The existing `docs/PROJECT_NOTES.md` is a useful orientation document, but its statements that new power alarms leave dynamics/model validity untouched are too strong: those alarms change state and consume an RNG also used for operational repairs.

---

## 10. Prioritized findings and recommended order

**Priority meanings:** P1 = address before trusting public operation/live results; P2 = address before substantive modeling/feature expansion; P3 = polish and maintainability.

| Priority | Finding | Primary source locations | Suggested direction |
|---|---|---|---|
| P1 | Normal telemetry omitted by deltas | `engine/models.py:94`, `api/main.py:183` | Per-entity state revisions or complete node snapshots at this scale |
| P1 | Global warning state, same-tick updates, restart ambiguity | `api/main.py:183,258,313` | Independent revision cursor, run ID, replay-safe logs |
| P1 | Non-uniform “random” helper breaks grid probabilities | `engine/noise.py:32`, `engine/physics.py:136` | Correct uniform stream; regenerate downstream artifacts |
| P1 | Oracle test-label threshold optimization and uncalibrated live cutoff | `ai/oracle.py:141,167`, `engine/commander.py:57` | Separate train/validation/test, probability calibration, live-policy evaluation |
| P1 | Hidden truth gates tier-1 actions | `engine/engine.py:548,684` | Separate controller observables from world truth; charge false actions |
| P1 | HTML injection and unauthenticated shared controls | `api/main.py:333`, `web/app.js:188` | Render untrusted text safely; restrict access/origins |
| P1 | Deployment without tests; deploy on PR events | `.github/workflows/ci.yml` | Test gate plus main-push-only deployment |
| P2 | Live rules fallback not wired; hidden scoring failures | `ai/serve.py:235,267,279,335` | Explicit tested ML/partial/rules/off states |
| P2 | Train/live sequence mismatch | `engine/engine.py:118`, `ai/seqdata.py:58`, `ai/serve.py:248` | One shared observation/window pipeline |
| P2 | Incomplete ring geometry and fiber accounting | `engine/network.py:97`, `engine/engine.py:493` | Rebuild topology after allocation; link repairs to episode IDs |
| P2 | Isolated throughput recovers; solar battery edge underflows | `engine/physics.py:54,136` | Enforce fault constraints through time; clamp/test boundary states |
| P2 | Worker shutdown, scheduling, timer, stale-result behavior | `ai/serve.py:158–245` | Safe stop event, join, elapsed-tick cadence, independent deadlines, generation tokens |
| P2 | Finite schedule silently expires | `engine/engine.py:118`, `api/main.py:41` | Explicit completed state/reset or deterministic extension |
| P2 | Unpinned runtime/artifact provenance | `requirements.txt`, `models/`, `reports/` | Locked environments and machine-readable run manifests |
| P2 | UI risk/health semantics and control synchronization | `web/app.js:124,545` | Backend-derived operational metrics; server-authoritative controls |
| P3 | Weakest-district command, marker location, ETA units | `web/app.js` | Targeted UI regression tests and fixes |
| P3 | Packaging, script/docs drift, accessibility | root scripts, README, styles | Package paths, truthful docs, keyboard/reduced-motion pass |

### Suggested work sequence

1. **Freeze the baseline:** preserve current artifacts and attach hashes/config/environment provenance.
2. **Repair the live contract:** delta completeness, warning replay, same-tick writes, run resets, UI error handling.
3. **Harden exposure:** HTML text rendering, controls/access policy, CORS, Docker exclusions, CI gates.
4. **Correct the simulation:** uniform probabilities, ring paths, sustained isolation, battery edge states, ledger resolution, horizon handling.
5. **Rebuild evaluation honestly:** shared observations, validation/calibration split, controller/world separation, corrected metrics and paired experiments.
6. **Regenerate data/models/results:** only after simulation semantics stabilize; update headline claims from the new artifacts.
7. **Then expand the product:** real sidebar views, history, richer policy controls, or a React migration if maintainability warrants it.

These are recommendations, not changes applied during this review.

---

## 11. Safe-change guide for the next iteration

| Desired change | Likely files | Required checks |
|---|---|---|
| Colors/layout/typography | `web/index.html`, `web/styles.css`, some `app.js` | Syntax, desktop/mobile/browser smoke, accessibility |
| Inspector field/display metric | `models.py`, `schemas.py`, `api/main.py`, `app.js` | Full and delta payloads, config contract |
| Simulation speed/pause/reset | `api/main.py`, worker, client controls | Multi-client, same-tick controls, run/cursor reset |
| Districts/node count/placement | config, placement, network, schemas, UI | Bounds, membership, topology, performance, retraining |
| New fault class | config, faults, engine, dispatch, schemas, ML, UI | Lifecycle/repair, feature labels, retraining, study |
| New power/weather physics | physics, faults, engine | Distribution tests, deterministic tests, retraining, report regeneration |
| New model/features | features/seqdata, training, serving, artifacts | Exact feature/channel order, calibration, holdout, fallback |
| Different Commander costs/actions | config, commander, engine, counterfactual | Threshold and UI consistency, policy cost accounting, paired study |
| Crew workflow changes | models, dispatch, engine, schemas, UI | Fleet release, standby/approval, starvation, crew-time accounting |
| React frontend migration | new frontend build plus Docker/CI | Preserve/fix API contract first; do not port stale-data behavior |
| Real network integration | new ingestion and observation boundary | Separate simulated truth from telemetry; auth, persistence, auditability |

### Contracts worth protecting

- Keep I/O, wall clock, web frameworks, and ML execution out of the pure engine.
- Keep reactive dispatch retrying all outstanding work, not only new faults.
- Preserve matched exogenous schedules and explicit masked-event accounting for comparisons.
- Treat the Doctor's 71-feature order and Oracle's 12-channel order as versioned artifact contracts.
- Keep simulation time separate from wall-clock timers and client-delivery revisions.
- Do not claim a model/report remains valid merely because its input dimensions are unchanged after physics changes.

### Highest-value new tests

1. Full snapshot reconstructed from deltas equals the actual full snapshot.
2. Two clients reading the same revision both receive the same warning changes.
3. Paused same-tick controls and process resets are delivered correctly.
4. Random event frequencies match configured probabilities within statistical tolerances.
5. Model-absent live scoring actually calls the rules policy.
6. Shared train/live sequence extraction is identical on fault/ripple/repair boundaries.
7. False-positive tier-1 predictions execute/consume modeled costs without consulting hidden truth.
8. Every ring member has consistent path geometry and each cut episode resolves.
9. Isolated nodes remain without service until restoration; battery remains in bounds under edge inputs.
10. Worker stop/join, in-flight disable, high-speed cadence, and approval deadlines work.
11. Frontend command palette and untrusted log rendering have browser-level tests.
12. CI runs meaningful data-generation checks rather than permanently skipping the five data-dependent guards.

## Final conclusion

The project has a useful, understandable architecture and enough existing tests to support careful evolution. The biggest risks are not framework choice or visual polish: they are **state-delivery correctness, stochastic-model correctness, separation of controller knowledge from simulator truth, and validation of the actual deployed AI policy**.

Preserve the layered design. Correct those foundations in small tested steps. Then build the requested new features on a baseline whose live behavior and published evidence agree.
