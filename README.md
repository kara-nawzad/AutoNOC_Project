# AutoNOC — a predictive NOC for a simulated LTE network in Sulaymaniyah

A digital-twin simulation of a 300-tower LTE network in Sulaymaniyah, Iraq,
with an AI layer that **diagnoses** faults (the Doctor), **predicts** failures
(the Oracle), **acts** on them (the Commander), and **proves** the acting is
worth it (the counterfactual study).

Built as a portfolio / learning project. Python 3.12+, FastAPI + Leaflet,
XGBoost, PyTorch. Deterministic: the same seed produces the same world.

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

---

## Quickstart

```powershell
python install_autonoc.py                 # unpack the codebase
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

---

## What's inside

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
```

---

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
A no-AI, B advisory, C autonomous, D clairvoyant. 8 seeds × 5 days:

```
arm   availability   downtime min   pre-empted   false
A     98.77 ± 0.03    26,581 ± 707      0          0
B     98.77 ± 0.03    26,580 ± 708      0          0
C     98.90 ± 0.03    23,706 ± 669     224         0
D     98.98 ± 0.03    22,014 ± 623     244         0
```

**Autonomous achieves ~63% of the clairvoyant downtime reduction.** Advisory
is indistinguishable from no-AI: human approval latency eats the entire
predictive advantage — the argument for autonomy. D bounds *predictive*
maintenance, not omniscience: instant faults are excluded by construction.

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
