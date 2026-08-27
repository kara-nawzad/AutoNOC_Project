# AutoNOC — Complete Project Notes

> A detailed reference for the AutoNOC project: what it is, how every part works,
> why it is built the way it is, what the published numbers actually mean, how to
> run it and deploy it, and what is known to be incomplete or inconsistent.
>
> Companion to `README.md` — the README is the pitch, this file is the manual.

---

## Part I — The General Picture

### 1. What this project is

AutoNOC is a **predictive Network Operations Center (NOC) for a simulated LTE
network**. It is a digital twin of a 300-tower network in Sulaymaniyah, Iraq,
with an AI layer that:

- **diagnoses** faults that are already happening (the *Doctor*),
- **predicts** failures 60 minutes before they land (the *Oracle*),
- **acts** on those predictions with an explicit, cost-based decision rule (the
  *Commander*), and
- **proves the value** of acting with a four-arm counterfactual study (the
  *Study*).

It is a **portfolio / learning project**, deliberately scoped to be:

- **Deterministic** — the same seed produces the same world, bit for bit
  (within a machine).
- **Honest** — every published metric is reported against an honest baseline
  (often "always do nothing"), and the limitations are written down in the
  README, not hidden in a footnote.
- **Test-guarded** — the architectural decisions are enforced by tests
  ("invariants"), not by conversation.

**What it is not:** it is not a real network. The fault rate is ~100× a real
network (deliberate — a static green map is a useless demo), the physics is
COST-231 plus documented approximations, and the AI learns from its own
simulation. Nothing here claims to transfer to a real LTE network.

### 2. The world being simulated

**City:** Sulaymaniyah, a compact valley city in Iraqi Kurdistan. The map
envelope is derived from real landmark positions:

```
lat 35.509 … 35.630   lon 45.292 … 45.485
```

**Ten aggregation sites (districts)** anchor the 300 eNodeBs. Each district has
a real name, a real position, a node count, and a COST-231 clutter term `C`
(a genuine physics parameter, not a hand-tuned knob):

| # | District | Nodes | Clutter C | Character |
|---|----------|-------|-----------|-----------|
| 0 | Goizha Mountain | 18 | −8.0 | Ridge macro sites, elevation 950–1250 m, exposed grid |
| 1 | Grand Millennium | 34 | +3.0 | Very high daytime traffic, backup core site |
| 2 | Salim Street | 42 | +3.0 | Densest district, highest daytime traffic |
| 3 | University | 36 | +1.0 | Bursty, earlier peak |
| 4 | Sarchinar | 28 | −2.0 | Evening/weekend leisure |
| 5 | Bakrajo | 32 | −2.0 | Residential evening; **unstable mains** |
| 6 | Tasluja Road | 24 | −5.0 | Flat 24 h industrial; dust-driven RF |
| 7 | Hawara Barza | 26 | −1.0 | High throughput, low density |
| 8 | Airport | 22 | −6.0 | Flight-schedule traffic spikes |
| 9 | Rizgari | 38 | 0.0 | Dense residential; contains the Faruk cluster |

**Priority cluster:** Faruk Medical City sits inside Rizgari (0.8 km radius
around 35.5552, 45.4531). Nodes inside it get a **3× dispatch priority
multiplier**. It is a cluster inside an agg site, not its own site — two
aggregation nodes 1 km apart is poor network design.

**Dual core (EPC):** metro-redundant, **1.70 km apart**, not geo-redundant
(a city this size wouldn't put its core 50 km away):

- Primary: **SPU University** (35.5500, 45.4200), fiber backhaul. The
  maintenance depot is co-located here.
- Backup: **Grand Millennium** (35.5602, 45.4340), **23 GHz microwave**
  backhaul.

The dual design is physically real in the sim: storms threaten the microwave
path (ITU-R P.530 rain fade at 23 GHz) while leaving fiber alone;
construction threatens fiber while microwave is fine.

**Season:** the demo world starts on day-of-year **220 (early August)** —
peak heat and dust season, the conditions the narrative is built around.
Training data sweeps the full year regardless. Weather is seasonal: dust
multipliers peak Mar–Jun (×2.2 in April), storm multipliers peak Dec–Feb
(×1.8 in January).

### 3. The four personas

| Persona | Technology | Job | Key published result |
|---------|-----------|-----|----------------------|
| **Doctor** | XGBoost, 71 features, 5 classes | Say what's *wrong now* from degraded telemetry | fault precision 0.995 / recall 1.000 / FPR 7e−5 (on already-broken nodes — easy) |
| **Oracle** | GRU, 12×12 raw-telemetry windows | Say what will break **within 60 min** | AUC-PR 0.547 vs 0.501 for the best tabular baseline; recall 0.450, and that is the ceiling story |
| **Commander** | Decision theory (no ML) | Turn probabilities into actions when expected value is positive | Act iff p > 0.4375 — *derived* from the cost model, never hard-coded |
| **Study (M7)** | Counterfactual simulation | Prove the AI is worth it under identical exogenous schedules | Autonomous achieves ~62–63% of the clairvoyant planner's downtime reduction |

### 4. Design philosophy

The project's culture, distilled from the code comments:

1. **Determinism is the foundation.** Same seed ⇒ same world. The counterfactual
   study is only valid because of it.
2. **Honest numbers.** If "always predict healthy" scores 98.7% accuracy,
   that number is published next to the model's, not buried. If the deep
   learning baseline wins, the project ships the simpler model and says so.
3. **Invariants are tested, not conversational.** Every architectural rule has
   a test. "An invariant that is not tested is a preference."
4. **No subsystem deleted to improve a number** (invariant I12).
5. **Headless first.** Every feature is testable without a browser.
6. **Learn from v1 the hard way.** Nearly every module documents a v1 bug it
   was built to make structurally impossible (see §7).

### 5. The demo — "Storm over Goizha"

A 5-minute, one-seed demo. Seed **131** was found by `cast_seed.py` (M8) from
hundreds of candidates: its **exogenous schedules** (generated at init, before
any stepping) naturally contain every beat. Nothing in the demo is scripted in
the engine.

| Beat | What happens | Sim time (seed 131) |
|------|--------------|---------------------|
| Act 0 | Calm opening — crews idle, ~99% availability | D1 00:00 |
| Act 1 | **SLY-eNB-080 (Salim St)** degrades gradually (congestion); Oracle flags it; Commander pre-dispatches | D1 05:55 |
| Act 2 | Crew on site before the failure | — |
| Act 3 | **Storm over Goizha (81 km/h) + a natural storm-caused fiber cut** | D1 10:15 |
| Act 4 | Instant power fault during the storm — no warning, by design (25% of faults) | D1 11:20 |
| Act 5 | Counterfactual table: same seed, AI on vs off | — |

The single manual beat: when the storm hits, the presenter clicks **CUT FIBER**
to force the double-cut isolation spectacle (a whole ring goes dark, 34 alarms
correlate to 1 incident, one crew fixes it). A natural *double* cut happens
roughly twice per simulated year — far too rare to wait for on camera.

At 1× speed one tick ≈ 1 wall-clock second, so the acts fall at roughly
0:00 / 1:00 / 2:00 / 2:30 of the demo.

---

## Part II — Architecture

### 6. Layered architecture

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
                    └──────────┬──────────
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

- **engine/** — pure Python stdlib. No I/O, no framework, no wall clock, no
  ML libraries. An AST test (`test_I2_engine_is_pure`) scans every file and
  fails on banned imports (`fastapi`, `pandas`, `torch`, `time`, `os`,
  `json`, …). This is what keeps the sim deterministic and fast, and what
  keeps AI actions from perturbing the world.
- **ai/** — data generation, training, and batched inference. May use numpy /
  torch / xgboost / sklearn / pandas. Never calls `engine.step()`.
- **api/** — FastAPI. Owns the production clock (a lifespan task), the
  process lock, the cursor-delta protocol, and the control surface.
- **web/** — a single-page Leaflet dashboard (bundled, offline-capable). It
  renders whatever the API sends and computes nothing: no status names, no
  colours, no thresholds in JavaScript — all of it comes from
  `GET /api/config` (invariant I5).

### 7. The twelve invariants

From `tests/test_invariants.py` and `engine/engine.py`:

| # | Guard | What it prevents (the v1 bug it kills) |
|---|-------|----------------------------------------|
| I1 | The engine owns time — no `engine.step()` in route handlers | v1 advanced the tick inside `GET /api/delta`; two browser tabs ran the sim at 2× speed, closing the browser stopped time |
| I2 | The engine is pure — banned imports enforced by an AST test | v1's 177 ms/tick `pandas` call, which two rounds of manual profiling failed to locate |
| I3 | Determinism — seed 42 twice ⇒ identical state at tick 5000 | silent non-determinism corrupting the counterfactual comparison |
| I4 | `step()` is fast — hardware-calibrated, asserts a ratio (target < 5 ms for 300 nodes) | slow ticks stalling the HTTP server / demo |
| I5 | One source of truth — no colours/thresholds in `web/` | v1's SLY-032 desync: map said "Critical", sidebar said "Normal", because the same threshold lived in two places and drifted |
| I6 | Frontend renders, never computes | client-side re-implementation of engine logic |
| I7 | Headless first — every feature testable without a browser | features that only exist in the browser |
| I8 | No metric without a holdout | in-sample numbers presented as results |
| I9 | Five independent RNG streams (faults, weather, physics, traffic, ops) + a pre-drawn noise pool | shared RNG letting AI actions perturb the fault sequence, so counterfactual arms inhabit different worlds instead of testing two policies |
| I10 | Exogenous event schedule, generated pre-run, immutable | state-dependent fault scheduling invalidating the counterfactual study |
| I11 | Features never peek ahead | the single easiest way to accidentally build a 99% model |
| I12 | No subsystem deleted to improve a number | metric-chasing that quietly deletes capabilities |

### 8. Time and determinism

- **Tick = 5 simulated minutes.** 288 ticks/day, 365 days/year.
- **The clock lives in one place:** `NOCEngine.step()`, called from exactly
  one production site — `simulation_loop()` in the API lifespan, run via
  `asyncio.to_thread` so a slow tick never stalls HTTP responses.
- **Five independent `random.Random` streams**, each seeded as
  `seed * 7919 + {1,2,3,4,5}` for faults, weather, physics, traffic, ops —
  plus a `NoisePool` (stream `+33`) of pre-drawn gaussians: the hot path does
  ~10 `gauss()` draws per node per tick, and pre-drawing from a seeded pool
  removed the dominant tick cost while staying deterministic.
- **No wall clock in the engine.** Wall-clock time exists only in the API
  layer (auto-approve timers, tick pacing) and in the inference worker's
  staleness logic.
- **Determinism is within a machine** (honest limitation): float reduction
  order and library versions can differ across platforms. Tests assert
  within-machine determinism and machine-relative performance.

### 9. Threading and concurrency model

- **Sim thread ≠ HTTP thread.** The tick runs in a worker thread under a
  `threading.Lock`; every HTTP read takes the same lock for a snapshot.
  `GET` never mutates state (I1 + the v1 two-tabs bug).
- **Inference worker** (M6): a daemon thread that every 0.25 s checks the
  tick; every 6 ticks (30 sim minutes) it snapshots node state **under the
  lock**, runs Doctor+Oracle inference **outside the lock**, and writes
  verdicts back **under the lock**. If a cycle overruns, the previous
  cycle's verdicts are reused — stale predictions beat a stalled simulation.
  The worker **never** calls `engine.step()`.
- **Approve/veto** and manual controls take the lock too; the auto-approve
  timer (demo mode) lives in the worker, not the engine, so the engine stays
  deterministic.

---

## Part III — The Engine

### 10. Geography and topology

**Placement** (`engine/placement.py`): morphology-driven, per-district
patterns, not a uniform grid. Two earlier attempts failed differently:
disc-scatter left 6.3 km coverage holes; farthest-point sampling fixed
coverage but made every district look identical. Real networks are
heterogeneous — micro-cells ~200 m apart on Salim Street, macro sites ~1.5 km
apart along the Goizha ridge. Node coordinates are jittered around a
clutter-scaled variable grid (`NODE_SPREAD_DEG = 0.012`).

**Elevation:** 750–840 m for city nodes; the Goizha ridge 950–1250 m.
Elevation feeds a real physics term: up to +6 dB RSRP bonus
(`(elev − 780)/90`, clamped).

**Neighbour graph:** pairs within 2 km, built **once at init** (O(n²) once —
v1 rebuilt it every tick at a measured 35.8 ms). Used for the GNN-style
ripple: an RF fault adds 0.2–0.8% packet loss and 2–5% CPU to healthy
neighbours (a neighbour ripple, not inter-cell interference).

**Fiber rings:** 10 protected rings, grown geographically from each agg site
by nearest-unassigned nodes, with hard locality guards: max member
separation 6 km from the ring seed, max circumference 12 km. A ring spanning
Bakrajo to Goizha would scatter its alarms into visual noise and defeat the
correlation story Act 3 exists to demonstrate.

**Protected ring semantics** (the heart of M3):

- **1 cut** → traffic reroutes the long way. Service survives, latency rises
  ×1.6 for ring members, the ring is now UNPROTECTED, and a crew is
  dispatched immediately.
- **2 cuts** → the span between them is isolated: every healthy ring node
  goes `Backhaul Isolated` — fine but unreachable.

> An earlier build raised no incident for a single cut, so nothing was ever
> repaired: cuts accumulated silently until a ring randomly reached two and
> 33 nodes went dark at once. Fixed, and now guarded by tests.

### 11. Physics (`engine/physics.py`)

**Radio — COST-231 Hata, not Friis.** Free-space (Friis) is ~27 dB optimistic
at 1 km, which made the `RSRP < −100 dBm` threshold unreachable anywhere on
the map and left an entire v1 physics branch as dead code. COST-231 at
2100 MHz:

- TX 43 dBm, antenna gain 15 dBi, BS 30 m, MS 1.5 m, log-normal shadow
  fading σ = 6 dB (deliberately injected — it is the dominant noise floor).
- `log10(distance_km)` is precomputed per node (nodes don't move) — one less
  log per node per tick in the hottest path.
- **Documented caveat:** COST-231 is specified for 1500–2000 MHz; running it
  at 2100 MHz costs **0.72 dB** — roughly 10× smaller than the 6–8 dB shadow
  fading. Documented rather than hidden.

Then per tick, converged toward targets:

- `RSRP = TX + gain − pathloss + elev_bonus − 5·load − weather_penalty`,
  converged at 30%, clamped to [−130, −50] dBm. Weather penalty: 3 dB in a
  storm, 1.5 dB in wind.
- `SINR ≈ 26 − 12·load + 0.25·(RSRP + 85)`, clamped [−5, 35] dB.
- `throughput ∝ log2(1 + 10^(SINR/10))` (Shannon) × 22 × (1 − 0.45·load),
  clamped [0.5, 300].
- Healthy latency ≈ 18 + 22·load ms; jitter 1.2 + 3·load; packet loss relaxes
  to ~0.25% baseline. Faults override these (the fault "owns" the metric).

**Thermal:** ambient = 21 °C annual mean ± 13 °C seasonal (Jan ~8, Jul ~34)
± 9 °C daily (peak ~15:00) + weather Δ. Node temperature targets
`ambient + 0.22·CPU% + dust_penalty + generation_offset` (legacy +3, modern
−2 °C), converged at 25%.

**Dust — mechanical damage, not RF.** Dust does **not** attenuate 2.1 GHz
(<0.01 dB/km; it only matters above ~10 GHz) — modelling it as propagation
loss would be an error an RF-literate reviewer catches instantly. The real
mechanisms: filter clogging (−8 °C cooling capacity at full accumulation),
solar panel soiling (−30% charge), connector drift (+3 dB S11 over days).
Accumulation: +0.004/tick during dust weather (dust events last 24–72 ticks);
rain ≥ 10 mm/h washes panels (−0.05/tick). This creates the **only
multi-day degradation signature** in the model — the slow trend the Oracle's
coarse branch is designed to see.

**Power** (`Grid → Solar → Battery → Generator`):

- Battery: 72 ticks (6 h) at full capacity. Generator: 288 ticks (24 h) of
  fuel. Solar window 04:00–20:00, charging 0.5%/tick (reduced by soiling).
- **Two distinct weak-grid mechanisms, deliberately** (same symptom class,
  opposite precursors — this is where the 75/25 gradual/instant split comes
  from *physically* rather than by decree):
  - **Bakrajo (UNSTABLE):** mains instability, repeated cycling, capacity
    fade → **predictable** degradation.
  - **Goizha (EXPOSED):** lightning/wind snaps the line → **unpredictable**.
- Grid dropout/restore chances per tier (per tick): STRONGEST 0.0002/0.060,
  STRONG 0.0005/0.040, MEDIUM 0.0010/0.025, UNSTABLE 0.0045/0.020,
  EXPOSED 0.0018/0.008.
- **Battery capacity fades** 4% per cycle (floor 40%): verified over a
  simulated year, Bakrajo fades 6.0 h → 4.96 h backup, Salim Street barely
  moves (97.1% of capacity).
- Total power loss (no grid, battery ≤ 0.5%, fuel 0%) → `Power` fault,
  logged CRITICAL.

**Microwave core link:** 23 GHz over 1.70 km, 38 dB link margin, ITU-R
P.530 rain fade with K=0.128, α=1.0214 (ITU-R P.838 coefficients at 23 GHz).
23 GHz was chosen because it degrades visibly in a storm without failing
constantly (15 GHz too robust to be interesting; 38 GHz fails too often).

**Traffic:** 24-h cosine peaking at tick 168 = 14:00, base 0.30 ± amplitude
0.35, with a per-district profile (amplitude multiplier, peak shift, base
multiplier) — Goizha low/steady, Salim Street highest daytime, Tasluja flat
industrial, etc.

### 12. The fault model (`engine/faults.py`)

**Two principles, both learned from v1:**

1. **Faults are a CAUSE, not a threshold.** Pick the fault first, then degrade
   metrics through it. v1 thresholded metrics to create labels and then asked
   a model to predict those labels from the same metrics — circular, worth a
   meaningless 99.6% accuracy.
2. **The schedule is EXOGENOUS (I10).** Generated before any run begins,
   depending only on the seed, never on simulation state. Eligibility is
   *not* checked at generation: a scheduled fault landing on an
   already-broken node is handled at replay time as **masked** and counted
   identically in every counterfactual arm, so the recall denominator cannot
   drift between arms.

**Rates and mix:**

- Base node fault rate: 0.001/tick/node ≈ ~100× real (deliberate, documented
  as accelerated). Multiplied by weather fault multiplier (storm ×2.5,
  heatwave ×2.0, wind ×1.8, dust ×1.4) and generation multiplier (legacy
  ×1.6, standard ×1.0, modern ×0.6).
- Per-district fault mix (congestion/overheat/RF/power), e.g. Goizha
  (0.10/0.10/0.55/0.25) hardware-heavy, Salim Street (0.50/0.18/0.24/0.08)
  congestion, Bakrajo (0.28/0.35/0.20/0.17) overheat+power; default
  (0.32/0.24/0.27/0.17).
- **75% gradual (predictable), 25% instant (impossible to forecast)** — this
  sets an honest ceiling on AI recall: a good result reads "caught 82% of
  what was catchable" rather than a suspicious 99%.
- 8% of faults are **ambiguous** (severity 0.35): they sit genuinely near the
  decision boundary.

**Degradation curves** (assigned per fault *type* by physics — a single shape
would let a trivial trend detector match the GRU and hollow out the
benchmark):

| Fault | Curve | Onset offset (ticks) |
|-------|-------|----------------------|
| Congestion | linear | 4–12 (20–60 min) |
| Overheat | exponential | 6–18 (30–90 min) |
| RF / Antenna | sigmoid | 12–24 (60–120 min) |
| Power | linear | 24–288 (2 h – 24 h) |

**Causal degradation per kind** (all clamped to physically possible ranges —
an early build produced 118 °C, +8.5 dB S11 and 1194 ms latency; the Pydantic
response layer is what caught it):

- Congestion: CPU +35·k, latency ×(1+2k), jitter ×(1+1.8k), loss +5k,
  throughput ×(1−0.45k).
- Overheat: temp +25·k, CPU +17·k, throughput ×(1−0.35k).
- RF: S11 +11·k (max −1 dB — above 0 dB the antenna would amplify), RSRP
  −10·k, SINR −7·k, throughput ×(1−0.6k), loss +7k.
- Power: voltage −1.2·k (min 8 V), battery −30·k.
- Backhaul: **fine but unreachable** — normal RF/temp/power, throughput 0,
  loss 100%, max latency. Telling that apart from a genuinely broken node
  demands the *opposite* action — the core diagnostic subtlety.

**Fiber cuts are an independent process** (not a share of node faults —
treating backhaul as 8% of node faults gave 10.4 cuts/day against a
real-world 0.03–0.1/day, ~300× too many). Rate: 0.08/day/ring; storms triple
the rate and re-attribute the cause to `storm`.

**Recovery:**

- **Self-heal:** congestion (4 ticks) and overheat (5 ticks) can
  auto-resolve.
- **Remote reset:** free repairs on modernised hardware — per-tick chance
  legacy 0.0 / standard 0.12 / modern 0.35. Gives the Doctor a real latent
  variable (generation) and makes reboot meaningful.
- **Repair times:** congestion 4t, overheat 5t, RF 12t, power 24t, backhaul
  18t (× skill multiplier).
- **Watchdog:** nothing stays broken and unattended — after 120 ticks
  (10 h) unrepaired with a dispatched tech, the node is re-queued (clears
  `tech_dispatched` so dispatch can retry).

**The ledger.** Every scheduled event gets a ledger entry with an immutable
episode id and a state that only moves forward:

```
injected → resolved        (fault activated, then healed/repaired)
injected → pre_empted      (Commander stopped it before activation — M6)
injected → masked          (fired on an already-broken node — counted, not dropped)
```

The ledger is the denominator for every AI claim, and it is identical in
shape across all counterfactual arms.

### 13. Dispatch and crews (`engine/dispatch.py`)

**v1's dispatch bug:** auto-dispatch fired only on the tick a fault appeared.
If all ten teams were busy that instant, the node was orphaned *permanently*
— 34 nodes sat broken for 7.6 simulated days while the fleet had 1.8× the
required capacity. **Fix:** dispatch runs every tick over all pending work.

**Alarm correlation — root causes, not symptoms.** Twelve backhaul-isolated
nodes on one fiber segment are **ONE incident** at the cut coordinate.
Dispatching twelve crews to twelve "failures" consumes the whole fleet and
repairs nothing — the nodes were never broken. Measured: the naive reading
restores 0 of 12 nodes while occupying all 10 teams for 2.7 simulated hours;
the correlated reading restores all of them. (≥3 correlated alarms to treat a
ring as isolated.)

**Priority** (triage with wait-time ageing — without it, low-priority nodes
starve indefinitely, v1's orphaning bug in a different hat):

```
priority = severity · #affected · critical_mult · (1 + wait/50) / (1 + travel/10)
severity: FIBER_CUT 100, POWER 60, other node faults 40
```

**Best team** — by *expected completion time*, not distance:

```
completion = travel + repair_ticks × skill_mult
nearby generalist : 2 travel + 12 × 1.2 = 16.4 ticks
distant RF tech   : 5 travel + 12 × 1.0 = 17.0 ticks  → send the generalist
```

Skills are a **soft** constraint (a mismatched team is slower, never blocked):
10 teams = 3 RF, 3 POWER, 4 GENERAL; multipliers 1.0 / 1.2 / 1.5. A hard
constraint would starve RF faults whenever all three RF techs were busy —
structurally identical to v1's dispatch bug.

**Crew movement:** 28 km/h (2333 m/tick) — the honest door-to-door urban
average including traffic; at 40 km/h most trips finished in 1–3 real
seconds and the vehicle animation was invisible.

**Team state machine:**

```
IDLE → EN_ROUTE → REPAIRING → RETURNING → IDLE
                 ↘ STANDBY ↗   (M6 pre-dispatch: crew holds on site for the
                                prediction window; fault lands → instant
                                repair; window expires → false dispatch)
```

Every completed mission resets **all** state (v1 leaked state — "every
mission must reset ALL state or teams leak").

---

## Part IV — The AI

### 14. Feature engineering and the cardinal rule

**The cardinal rule:** features at tick t may use **only** data from ticks
≤ t. The Oracle's label is "fails within N ticks", which is legitimately
derived from the future. A *feature* that peeks ahead is not — it is the
single easiest way to accidentally build a 99% model, and the hardest to
notice afterwards. `assert_no_lookahead` enforces it; a test calls it (I11).

**One builder, shared by training and inference.** v1 had two code paths that
drifted: the scaler expected 35 features in a fixed order, the live path
supplied 11, and nothing caught it until the model silently produced
nonsense. Now `features.build_vector()` is the single source, with the
canonical order persisted at training time (`feature_order.json`) and asserted
at inference.

**The 71 Doctor features:**

| Group | Count | Content |
|-------|-------|---------|
| current | 12 | rsrp, sinr, s11, latency, jitter, packet_loss, throughput, cpu_load, temperature, voltage, battery_pct, dust |
| `*_mean_1h` | 12 | fine-window (12 ticks) means |
| `*_std_1h` | 12 | fine-window stds |
| `*_delta` | 12 | tick-over-tick changes |
| `*_slope_1h` | 12 | least-squares slope per tick ("getting worse", not just "bad") |
| engineered | 5 | signal_efficiency (RSRP/SINR), thermal_headroom, power_margin, s11_excess, load_pressure (CPU·latency/1000) |
| static | 6 | generation, clutter_C, elevation, is_critical, grid_tier_code, agg_id |

**Deliberately NOT a feature: `site_id`.** The model would memorise "this
tower fails a lot", which does not transfer to an unseen tower. Static
attributes describe the *kind* of site, so they generalise.

**Two-branch history** on every node: `hist_fine` (12 ticks, 1 h, full
resolution) and `hist_coarse` (24 hourly aggregates of mean+std). The fine
branch alone cannot see dust (measured SNR 0.08 over a 12-tick window); the
coarse branch gives SNR 6.93 — from longer coverage and averaging 12 samples
per bucket (noise/√12). *Note (audit, §29): the coarse branch is collected
but no current model consumes it yet.*

### 15. Data pipeline and the leak audit

Ten leaks found in the v1 audit, each closed **by construction**:

| # | Leak | Fix |
|---|------|-----|
| L1 | SMOTE before split | no SMOTE at all; class weights instead (interpolating telemetry produces physically impossible half-overheated nodes) |
| L2 | scaler fit on all data | scaler fit in `train.py`, on **train only** |
| L3 | rolling features across node boundaries | features built per node from that node's own deque |
| L4 | random split on temporal data | chronological, blocked by season |
| L5 | seasonal split imbalance | blocked split keeps every regime in both train and test |
| L6 | subsample before split | subsampling happens after, per split |
| L7 | same seed train and eval | separate seeds (42/90/99), recorded per row |
| L8 | feature peeks ahead | features read only `hist_fine`; asserted |
| L9 | node identity leak | `site_id` is metadata, never a feature |
| L10 | ripple contamination | embargo (24 ticks) around every episode boundary |

**Tabular dataset (Doctor):** `dataset.py` rolls the engine headless and
writes one CSV per split — train seed 42 / 60 days, val seed 90 / 12 days,
test seed 99 / 20 days. Rows sampled every 3 ticks; **healthy rows kept at
10%** (HEALTHY_KEEP) so files stay manageable — the *precise* ratio is
restored with sample weights at training time. Episodes are namespaced by
seed (`seed × 10⁶ + id`) so `train.py` can assert **episode disjointness**
across splits: one 18-tick fault yields ~30 overlapping windows sharing 92%
of their timesteps; splitting by node and time alone would put
near-duplicates on both sides. Rows within the 24-tick **embargo** before an
onset are dropped: they already carry degradation signal but would be labelled
healthy, teaching the model contradictory targets.

**Sequence dataset (Oracle):** `seqdata.py` records genuinely **contiguous**
12-tick windows (12 × 12 raw channels, no engine features) from the engine —
train seed 42 / 45 days, test seed 99 / 18 days, negative windows kept at
6%.

> **A FALSE RESULT THE PROJECT ALMOST PUBLISHED.** The first GRU run had
> AUC-PR 0.035 against XGBoost's 0.484 — a "decisive" anti-deep-learning
> answer. It was a pipeline bug: healthy rows are subsampled 10× in the
> tabular set, so a 12-step window spanned **min 12.5 h, median 30.8 h, max
> 51.8 h**, while the degradation to detect unfolds over 1–2 h. The GRU was
> shown snapshots taken days apart and asked to spot an hour-long trend. Both
> models now read the same contiguous 60-minute windows, so the comparison
> measures what it claims to.

### 16. The Doctor (XGBoost)

**Setup:** 400 trees, depth 6, lr 0.08, subsample/colsample 0.85,
`multi:softprob` over 5 classes, class weights (no SMOTE), standard scaler
fit on train only, `tree_method="hist"`.

**The critical correction (rebalancing):** healthy rows are subsampled 10×,
so ~43:1 imbalance. Reporting precision on the rebalanced sample overstates it
by ~50 points — measured **91.2% vs 41.1%** at true prevalence, which would
have flipped the project's conclusion from "autonomy justified" to "the AI
makes the network worse". Every metric is computed with **sample weights that
restore the natural prevalence**.

**Held-out results** (unseen seed 99, unseen time; weighted):

| Metric | Value |
|--------|-------|
| Fault-level precision | **0.995** |
| Fault-level recall | **1.000** |
| False positive rate | **7.1 × 10⁻⁵** |
| Brier (calibration of P(fault)) | 5.7 × 10⁻⁵ |
| True test prevalence | 1.32% |
| **B0 "always healthy" accuracy** | **98.68%** ← published deliberately |
| B1 v1 thresholds (precision/recall) | 0.623 / 0.535 |

The B0 line is the cleanest demonstration that accuracy is a vanity metric at
1–2% prevalence. **Honest caveat:** diagnosing an *already-broken* node is
easy — degradation has already moved the metrics. The hard number to defend
is the Oracle's recall (§17).

### 17. The Oracle (GRU)

**The point is the benchmark, not the model.** Deep learning is only worth
shipping if it beats simpler alternatives on the same held-out data:

| Model | What it is | AUC-PR | Precision | Recall | Net benefit |
|-------|-----------|--------|-----------|--------|-------------|
| B0 | always "no failure" | — | 0 | 0 | — (98.24% accuracy!) |
| B1 | hand-tuned trend thresholds (what a competent engineer writes) | 0.030 | 0.040 | 0.550 | **−11.5 M tower-min** |
| B2 | logistic regression on lag features | 0.487 | 0.899 | 0.373 | +400,025 |
| B3 | XGBoost on lag features — the one to beat | 0.500 | 0.963 | 0.394 | +448,645 |
| **M** | **GRU on raw contiguous sequences** | **0.547** | **0.974** | **0.450** | **+517,982** |

- **GRU:** 1 layer, 64 hidden, dropout 0.2, ~17,089 parameters. Trained 12
  epochs, Adam lr 2e−3, cosine schedule, batch 1024, gradient clip 1.0,
  pos-weight for imbalance, per-channel normalisation from **train
  statistics only**.
- **AUC-PR lift from deep learning: +9.2%** over B3 → "the GRU earns its
  place: raw sequence carries structure that hand-crafted lag features do not
  capture." (The script also encodes the honest opposite verdicts: if the
  lift were within ±5%, ship XGBoost; if negative, report that deep learning
  is not justified. Both are defensible results.)
- **Operating point chosen by net benefit, not F1** — a missed failure costs
  90 tower-minutes, a pre-emption 45, a false dispatch 35 crew-minutes. The
  GRU's best net-benefit threshold is 0.94.
- **Recall 0.450 is the ceiling story:** with 25% of faults instant by
  construction, the honest claim is "caught 45% of the 75% that were
  physically predictable."
- **B1's net benefit is MINUS 11.5 million tower-minutes:** the
  hand-tuned-engineer baseline catches half of all failures and is *still
  worse than doing nothing*. That row is the whole argument for the
  Commander's cost-derived rule — a threshold picked by feel can make the
  network worse.

### 18. The Commander (`engine/commander.py`)

**Decision theory, not machine learning.** The Oracle produces
P(failure within 60 min) for every node. Turning that probability into an
action is expected-value arithmetic over the cost model — deterministic,
inspectable, and far easier to defend than a learned policy:

```
ev_act  = p · (COST_FAILURE − COST_PREEMPT) = p · (90 − 45)
ev_wait = (1 − p) · COST_FALSE_DISPATCH    = (1 − p) · 35
act  ⟺  ev_act > ev_wait
        ⟺  p > 35 / (45 + 35) = 0.4375
```

The threshold is **never hard-coded** — it falls out of the costs
(`BREAK_EVEN_PRECISION`), so a sensitivity study on the costs re-derives it
for free.

**Tiered autonomy** (config-anchored, never re-designed mid-project):

| Tier | Actions | Rationale |
|------|---------|-----------|
| **Auto (1)** | throttle, shed load, switch power source, remote reboot | cheap + reversible → applied immediately |
| **Approve (2)** | pre-dispatch a crew | consumes a scarce crew for ~1 h → operator confirms |
| **Never (3)** | permanent config changes, disabling alarms | out of scope by construction |

**Action selection** (`default_action_for`): a crew is offered only for
faults that physically *need* a crew (RF, Power, Backhaul), and only when
p > break-even. Congestion and overheat are pre-empted by a cheap reversible
tier-1 action even on critical sites — sending a crew to an overheat that
remote-reset can clear in the same hour just burns fleet time. Criticality
scales the decision, never the action type.

**The pre-emption gate (a subtle correctness point):** a cheap tier-1
mitigation can only pre-empt a **soft** fault (congestion/overheat). If the
Doctor misclassified a crew-worthy pending fault (RF/power) as congestion,
throttling must **not** cancel it — the antenna is still broken. Pre-emption
is therefore gated on the **actual fault kind from the exogenous ledger**,
never on the classifier's guess.

**Tier-1 effects** (all documented sim effects, all reversible, all decay on
a fixed deterministic schedule):

- `throttle` — withhold 50% of offered traffic for 12 ticks (linear decay).
- `shed` — throttle this node 40% and push +15% load onto 2 healthy
  neighbours.
- `reboot` — clear soft-state metrics toward baseline (CPU 45, latency ≤ 40
  ms, jitter 2.5, loss 0.3%, temp ≤ 45 °C).
- `switch_power` — force the generator on before the battery exhausts (only
  when grid is already down and fuel ≥ 20%).

**Bookkeeping:**

- Successful tier-1 pre-emption moves the ledger entry
  `injected → pre_empted` and resets the node to a clean baseline. The
  schedule event still exists (I10) — it just never became a real fault in
  this arm. Both arms keep the same episode set.
- **Standby horizon:** a pre-dispatched crew that arrives before any fault
  materialises **holds on site** for the rest of the prediction window (up to
  12 ticks = 60 min = the Oracle's horizon). If the fault lands while they
  wait, repair starts immediately (downtime ~1 tick, not ~1 hour) — that is
  the entire point of pre-positioning. Only if nothing happens by expiry is
  it a **false dispatch**. Real crews hold on site; counting them false the
  instant they arrive would make pre-positioning physically impossible.
- **Tier-2 re-queue cooldown:** 24 ticks (2 h) after an approve/veto, so a
  persistent verdict cannot spam the approval queue. Cooldown is set only
  when the action actually dispatched or the fault landed meanwhile — a busy
  fleet can still retry.
- **Live panel** (`ai_payload`): computed from the ledger every request —
  pre-empted count, false dispatches, precision, crew-hours saved, pending
  actions with auto-approve countdowns. The panel shows what *this* run
  actually did, never static numbers.

### 19. Live model serving (`ai/serve.py`)

Two structural rules from the brief:

1. **Never call `predict()` 300 times per tick.** Batch inference runs every
   `AI_INFERENCE_EVERY_TICKS` (6 ticks = 30 sim minutes) on a worker thread,
   off the sim thread. Snapshot under the lock → infer outside it → write
   verdicts back under the lock. If a cycle overruns, the previous cycle's
   verdicts are reused.
2. **Graceful degradation.** `ModelBundle` loads Doctor + Oracle once; every
   missing piece degrades that model to the hand-tuned **rules mode** (the
   B1 baseline: slope thresholds on temperature > 0.30/t, s11 > 0.10/t,
   packet loss > 0.08/t, CPU > 0.80/t, battery < −0.70/t, with a fixed
   p = 0.90 so the Commander's decision rule still applies). The dashboard
   must never crash because a `.json` is absent.

Verdict assembly per healthy node: class = Doctor argmax; p_fail = Oracle
score (falls back to 1 − Doctor P(healthy) if the Oracle is unavailable);
action = `default_action_for(cls, critical, p)`; tier follows the action.
The same pure `score_engine()` function is shared by the live worker and the
M7 study.

---

## Part V — Evaluation

### 20. The counterfactual study (M7)

**Design:** four arms on **identical exogenous schedules per seed** (I10),
same fleet, travel, and repair constraints:

| Arm | Policy | Approval latency |
|-----|--------|------------------|
| **A** | no AI — reactive dispatch only (status quo) | — |
| **B** | advisory — Oracle suggests; a human approves pre-dispatches; **no automatic tier-1** | 2 ticks (10 min) |
| **C** | autonomous — Commander acts: tier-1 instant, tier-2 approved fast (high-trust operator) | 1 tick (5 min) |
| **D** | clairvoyant — perfect knowledge of every *gradual* fault, zero false positives, dispatch timed so crews are on site at activation (travel-aware, never parking crews for hours) | 0 |

**The honest bound:** instant (unpredictable) faults are not pre-empted in
*any* arm, including D — a lightning strike is an exogenous shock. D
therefore bounds the value of **predictive maintenance, not omniscience** —
which is why the headline reads "X% of the improvement available to a
clairvoyant planner" rather than 100%.

**Metrics per run (tower-minutes throughout):** availability, downtime
(faulty-node-ticks × 5 min), episodes / activated / pre-empted / masked /
unresolved (from the ledger), false dispatches, crew-hours, MTTR, and a flat
cost model (90 per activated episode, 45 per pre-emption, 35 per false
dispatch). The headline comparison (autonomous vs clairvoyant) uses **downtime
saved** — the physical outcome — not the flat cost model.

**Results, 30 seeds × 10 days** (from `reports/counterfactual_summary.json`,
the most recent committed run):

| Arm | Availability | Downtime (tower-min) | Activated | Pre-empted | False | Crew-h | MTTR (min) | Cost |
|-----|-------------|----------------------|-----------|------------|-------|--------|------------|------|
| A no-AI | 98.75 ± 0.02 | 54,033 ± 775 | 1,158 | 0 | 0.0 | 773 | 92.8 | 104,229 |
| B advisory | 98.75 ± 0.02 | 54,070 ± 773 | 1,158 | 0 | 4.4 | 779 | 92.9 | 104,385 |
| **C autonomous** | **98.88 ± 0.03** | **48,369 ± 766** | **717** | **448** | 3.8 | 782 | 92.9 | **84,811** |
| D clairvoyant | 98.96 ± 0.03 | 44,857 ± 741 | 678 | 491 | 0.0 | 813 | 100.4 | 83,121 |

**Headline: autonomous (C) achieves 61.7% of the clairvoyant (D) downtime
reduction** (5,664 of 9,177 tower-minutes saved) under identical fleet
constraints.

**Findings:**

- **Advisory is not better than no-AI** — in this run it is marginally
  *worse* (−37 tower-minutes of downtime, −156 of cost: approval latency plus
  4.4 false dispatches eat the entire predictive advantage). An earlier
  8-seed × 5-day run (quoted in the README) showed it as statistically
  indistinguishable. Either way, the argument is for autonomy, not
  suggestion.
- Autonomous saves ~19,400 tower-minutes of cost per seed-run while using
  about the same crew-hours — the value comes from **fewer, shorter
  outages**, not more crew work.
- Even D's MTTR *rises* (92.8 → 100.4): pre-positioned crews occasionally
  wait, and the mix of repairs shifts. Availability still improves — the
  physical outcome is what the headline uses.

**Reproduce:**

```
python -m autonoc.scripts.counterfactual --seeds 30 --days 10 --workers 8
python -m autonoc.scripts.counterfactual --quick    # 3 seeds, 2 days
python -m autonoc.scripts.counterfactual --rules    # rules verdicts, no models
```

### 21. Testing

**70 test functions** across 6 files (the README's "64" and its per-file
breakdown are stale — audit §29):

| File | Tests | What they guard |
|------|-------|-----------------|
| `test_invariants.py` | 11 | I1–I12 as far as they are machine-checkable: pure engine (AST banned imports), single clock, determinism (seed 42 twice ⇒ identical state at tick 5000), step() speed ratio, no colours/thresholds in `web/`, no-preview leakage, 5 RNG streams |
| `test_regressions.py` | 20 | availability, ring reroute, team arrival, fault repair, realistic tower spacing, … |
| `test_ai.py` | 12 | no test-set information in features, episode disjointness, the leak audit |
| `test_commander.py` | 14 | decision-theory behaviour, break-even derivation, tier routing, pre-emption gating on the ledger |
| `test_counterfactual.py` | 7 | identical episode denominators across arms, arm determinism, summary math |
| `test_polish.py` | 6 | seed 131 is demo-worthy (score ≥ 13/15), demo plan narrates every act, **the demo fault is actually pre-empted by the trained models** (skipped when model artifacts are absent), docs/requirements deliverables |

`test_docs_and_dependencies_exist` currently **fails** on the committed
`requirements.txt`: it asserts `"xgboost" in reqs`, and the committed file
does not list xgboost (audit §29).

**CI reality (audit):** the GitHub Actions workflow "CI & Deploy" runs
`flyctl deploy --remote-only` on push/PR to main — it **deploys, but does not
run the test suite**, on ubuntu only. The README's claim that the suite runs
"on both Linux and Windows" does not match the committed workflow.

---

## Part VI — The Product

### 22. The API

Base URL `http://localhost:8000` (8080 in the Docker/fly image). Three v1
bugs are structurally impossible here: GET never mutates state; time is owned
by a server clock in a lifespan task, not the request path; deltas use a tick
cursor, not dirty flags (with flags, one dropped poll loses that update
forever and the client silently desyncs).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serves the Leaflet dashboard |
| GET | `/api/config` | Single source of truth (status names/colours, thresholds, map, EPC, depot, agg sites, break-even) |
| GET | `/api/data` | Full resync snapshot |
| GET | `/api/delta?since=<tick>` | Cursor-based state deltas — read-only, idempotent; resyncs if lag > 60 ticks |
| GET | `/api/health` | tick, seed, ai_enabled, ai_policy, paused, speed, slow_ticks |
| POST | `/api/control/pause` / `resume` | pause / resume the sim |
| POST | `/api/control/step` | advance one tick |
| POST | `/api/control/speed?value=1.0` | 0.25–10× |
| POST | `/api/control/inject?node_id&kind` | inject a fault (1–5) — for demos |
| POST | `/api/control/cut-fiber?ring_id&isolate` | the Act 3 double-cut scenario |
| POST | `/api/control/ai?enabled&auto_approve_seconds` | toggle the Commander (0–600 s auto-approve) |
| POST | `/api/control/approve/{action_id}` / `veto/{action_id}` | operator decisions on tier-2 actions |

Interactive OpenAPI docs at `/docs`.

**Environment variables:**

| Var | Default | Purpose |
|-----|---------|---------|
| `AUTONOC_SEED` | `42` | simulation seed (the demo uses `131`) |
| `AUTONOC_AI` | `0` | `1` auto-enables the Commander at boot |
| `AUTONOC_AUTO_APPROVE` | `0` | auto-approve Commander actions after N wall-clock seconds (demo mode) |

**Caching:** the dashboard must never be cached. A stale cached
`index.html`/`app.js` was the root cause of the long-running "page loads but
everything is empty" bug — the browser kept resurrecting an old frontend even
after the backend was fixed. HTML/API: `Cache-Control: no-store`; static
assets: `no-cache`.

**Pydantic schemas** (`api/schemas.py`) are the API boundary: every response
model validates the engine's output. (This is the layer that caught the
early build's 118 °C / +8.5 dB S11 / 1194 ms latency drift at the boundary.)

### 23. The dashboard

Single page, vanilla JS + Leaflet (bundled offline, `leaflet.js`/`leaflet.css`
in `web/`), 670 lines of `app.js`. It **renders, never computes** (I6): every
name, colour, and threshold arrives from `/api/config`.

Layout: map centre (node markers by status, agg-site markers, fiber rings
with cut points, animated crew vehicles, storm overlays), left rail (district
health list, team list), right rail (inspector, incident panel), bottom
(status bars — availability / healthy / faults / active teams / MTTR / sim
time — and the event log), and the **AI panel**: live pre-empted /
false-dispatch / precision / break-even / crew-hours-saved, pending tier-2
actions with approve/veto buttons and auto-approve countdowns, and the mode
indicator (`ml` vs `rules` vs `off`). Controls: pause/resume, speed, **CUT
FIBER**, ENABLE AI.

Polling: `/api/data` once on load, then `/api/delta?since=<last tick>` every
second at 1× speed (the client scales polling with the sim speed).

---

## Part VII — Operations

### 24. Local quickstart (honest version)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu   # slimmer CPU build (optional)

python -m autonoc.scripts.sanity_check    # headless physics report
python -m autonoc.ai.dataset              # ~3 min -> data/*.csv
python -m autonoc.ai.train                # ~40 s  -> Doctor
python -m autonoc.ai.seqdata              # ~2 min -> data/seq_*.npz
python -m autonoc.ai.oracle               # ~2 min -> Oracle
python -m pytest tests/ -q
python -m uvicorn autonoc.api.main:app --port 8000
```

Run everything **from the repo root** — `models/` and `data/` are resolved
relative to the working directory. If `RULES MODE` appears in the AI panel,
the model artifacts are missing (see §29) — re-run the pipeline.

One-line note on `requirements.txt`: the `torch` line's trailing
`--index-url https://pytorch.org` is **ignored by pip's requirements-file
parser** (file options must be on their own line); torch is installed from
PyPI — which is the CUDA build, so expect a large download even on CPU-only
machines. The separate `pip install torch --index-url
https://download.pytorch.org/whl/cpu` line above is the slimmer path.

### 25. The model pipeline and its artifacts

| Stage | Command | Runtime | Output |
|-------|---------|---------|--------|
| Tabular data | `python -m autonoc.ai.dataset` | ~3 min | `data/train.csv` (seed 42, 60 d), `data/val.csv` (90, 12 d), `data/test.csv` (99, 20 d) |
| Doctor | `python -m autonoc.ai.train` | ~40 s | `models/doctor_xgb.json`, `models/doctor_scaler.npz`, `models/feature_order.json`, `models/doctor_metrics.json` |
| Sequence data | `python -m autonoc.ai.seqdata` | ~2 min | `data/seq_train.npz` (42, 45 d), `data/seq_test.npz` (99, 18 d) |
| Oracle | `python -m autonoc.ai.oracle` | ~2–10 min CPU | `models/oracle_gru.pt`, `models/oracle_stats.npz` (train μ/σ), `models/oracle_metrics.json` |

`data/` is **regenerable and gitignored** (too large for GitHub, and the
engine is deterministic). The model artifacts under `models/` are the ones
the live server needs — see the audit note on which are and aren't committed
(§29).

### 26. Deployment (fly.io)

- `Dockerfile`: two-stage build on `python:3.12.14` → slim, venv,
  `pip install -r requirements.txt`, `COPY . .`, CMD uvicorn on
  `0.0.0.0:8080`.
- `fly.toml`: app `autonoc-project`, region `ams`, 1 shared CPU, 1024 MB,
  force HTTPS, machines auto-start/stop (scale to zero).
- **Auto-deploy:** the CI workflow runs `flyctl deploy --remote-only` on
  every push/PR to `main`. A fresh build from the GitHub source therefore
  contains exactly what is committed — including, once committed, the model
  artifacts. `.dockerignore` excludes only `fly.toml`, `.git/`,
  `__pycache__/`, `.envrc`, `.venv/` — note it does **not** exclude
  `models/`, so a *local* `fly deploy` also bakes in untracked local model
  files.

### 27. The demo, step by step

```powershell
$env:AUTONOC_SEED = 131
$env:AUTONOC_AI = 1
python -m uvicorn autonoc.api.main:app --port 8000
```

or `Start-Demo.ps1` / `Start-Demo.bat` (background server, AI auto-on,
relative paths — work from any clone).

1. Open `http://localhost:8000`. At 1× speed one tick ≈ 1 s of demo time.
2. ~1:00 (Act 1): SLY-eNB-080 (Salim St) starts degrading. The AI panel
   should flag it inside its 60-min window; the Commander pre-dispatches.
3. ~2:00 (Act 3): storm over Goizha. **Click CUT FIBER** for the isolation
   spectacle (34 alarms → 1 incident → 1 crew → ring restored in 21 ticks).
4. ~2:30 (Act 4): instant fault during the storm — the AI cannot warn; the
   dashboard shows the honest limit.
5. Act 5: show the counterfactual table for the same seed.

**Tooling:**

- `python -m autonoc.scripts.cast_seed --seeds 5000 --workers 8` — search
  seeds for one whose emergent world contains all demo beats. Scoring never
  steps the engine: the whole demo potential is visible from the exogenous
  schedules at init. Score is out of 15 (storm over Goizha, storm in the
  Act-3 window, cuts, storm-caused cuts, a Salim Street gradual fault in the
  Act-1 window, an instant fault inside a storm, a calm first 3 hours ≤ 25
  faults, …). Seed **131** scored **14/15** and is locked in by a test.
- `python -m autonoc.scripts.cast_seed --report 131` — print the demo plan.
- `python -m autonoc.scripts.cast_seed --verify 131` — step an autonomous
  run with the trained models and confirm the demo fault is actually
  pre-empted live.
- `python -m autonoc.scripts.sanity_check` — headless physics report.
- `python -m autonoc.scripts.export_sites` — `sites_300.json` / `.csv` for
  GIS/analysis.

---

## Part VIII — Audit

### 28. Honest limitations (carried from the README)

- **It is a simulation, not a network.** Fault rate ~100× real, deliberately.
  Nothing claims to transfer to a real LTE network.
- **The AI learns from its own simulation.** Internally consistent by
  construction; real-world generalisation unproven — say so in interviews.
- **COST-231 extrapolated** 2000 → 2100 MHz costs 0.72 dB, ~10× smaller than
  the injected 6–8 dB shadow fading.
- **Dust is mechanical damage**, not RF attenuation.
- **75/25 gradual/instant** sets an honest recall ceiling.
- **The Doctor's ~99% is on already-broken nodes** — the hard part is the
  Oracle's 0.45 recall.
- **The rules fallback is catastrophically bad** (B1: precision ~0.04). It
  exists as a robustness demo, not a feature.
- **Determinism is within a machine** — float reduction and library versions
  can differ across platforms.
- **One city, one operator, no user mobility** — no handover, no inter-cell
  interference beyond the neighbour ripple, no demand shocks beyond traffic
  curves.

### 29. Known issues and inconsistencies (audited against the code, 2026-08)

1. **`requirements.txt` — verified behaviour.**
   - The file installs fine: pip's requirements-file parser silently drops
     the trailing `--index-url https://pytorch.org` from the `torch` line
     (options must be on their own line), so torch comes from PyPI (CUDA
     build, large). A live `pip install --dry-run -r requirements.txt`
     resolves successfully.
   - **Genuinely missing:** `pandas`, `scikit-learn`, `xgboost` — imported by
     `ai/train.py` and `ai/oracle.py`. The server itself degrades gracefully
     without them (rules mode), but the **training pipeline cannot run** from
     a fresh clone, and the project's own test
     `test_docs_and_dependencies_exist` asserts `"xgboost" in reqs` — so the
     committed test suite currently fails on that file. (Fix in progress:
     the three packages are added to `requirements.txt` in this branch —
     purely additive; the working `torch` line is untouched.)
2. **Model artifacts split between committed and gitignored.**
   `models/doctor_xgb.json` + `feature_order.json` are committed, but
   `.gitignore` excludes `models/*.npz` and `models/*.pt`, so
   `doctor_scaler.npz`, `oracle_gru.pt`, `oracle_stats.npz` are **not on
   GitHub**. Consequence: a fresh clone boots in **RULES MODE** until the
   full pipeline is re-run. The running fly.io app "works perfectly" because
   either (a) it was deployed from a local directory whose untracked model
   files were baked in by `COPY . .` (`.dockerignore` does not exclude
   `models/`), or (b) the presenter has simply not noticed rules mode.
   Remedy in this branch: regenerate the three artifacts and commit them,
   so any build — including the CI auto-deploy from `main` — ships in ML
   mode. (This also activates
   `test_cast_seed_is_verified_by_models`, which is skipped while
   `oracle_gru.pt` is absent.)
3. **README test count is stale.** README: "64 tests (11 + 24 + 8 + 13 + 8)".
   Actual: **70 test functions** — invariants 11, regressions 20, AI 12,
   commander 14, counterfactual 7, polish 6.
4. **README CI claim does not match the workflow.** README: "runs
   automatically on every push/PR via GitHub Actions on both Linux and
   Windows". The committed `ci.yml` is deploy-only (`flyctl deploy
   --remote-only`, ubuntu), with no test job and no Windows runner.
5. **README M7 table is from an older run.** README quotes 8 seeds × 5 days
   (98.77 / 98.90 / 98.98 availability); `reports/counterfactual_summary.json`
   is a 30 seeds × 10 days run (98.75 / 98.88 / 98.96; headline 61.7% vs the
   README's ~63%). Both are valid; the committed report is the more recent.
6. **`TRUE_PREVALENCE` config vs measured.** `config.py` documents
   `TRUE_PREVALENCE = 0.022` (from review #2), while the committed Doctor
   test-set measure is 1.32% prevalence. The constant is documentation-grade
   (the pipeline re-weights from the data itself).
7. **`hist_coarse` is collected but unused.** The 24 h coarse history (the
   branch that makes dust visible, SNR 6.93 vs 0.08) is maintained on every
   node by `snapshot()`, but no current feature set, model, or script reads
   it. The config comment ("the 92% slow-fault recall target depends
   entirely on this") describes intent, not the current model.
8. **Packaging.** No `pyproject.toml` yet (roadmap) — the project is
   run-in-place from the repo root, not pip-installed.
9. **Python version.** Target is 3.12+ (badge, Dockerfile 3.12.14). The code
   runs on 3.11 as well; nothing 3.12-specific was found.

### 30. File map

```
autonoc/
  engine/            PURE. stdlib only. no I/O, no framework, no wall clock.
    config.py        every tunable constant (single source of truth)
    models.py        ENodeB, AggSite, FiberRing, FiberCut, Team, Incident
    engine.py        NOCEngine.step(), ledger, KPIs, commander hooks, cut_fiber()
    placement.py     tower positions (morphology-driven, clutter-scaled)
    faults.py        exogenous schedule, causal degradation, curves
    physics.py       COST-231, thermal, power, dust, rain fade, traffic
    network.py       topology, neighbour graph, fiber rings
    dispatch.py      correlate_alarms(), priority_score(), best_team()
    commander.py     M6: expected-value decision layer (NOT machine learning)
    geo.py           haversine, interpolate, clamp, step_toward
    noise.py         seeded pre-drawn gaussian pool (hot path)
  ai/
    features.py      71-feature builder, shared train + inference
    dataset.py       engine -> train/val/test.csv (tabular, Doctor)
    train.py         Doctor: XGBoost + baselines B0/B1, honest reweighting
    seqdata.py       engine -> contiguous 60-min windows (Oracle)
    oracle.py        Oracle: B0/B1/B2/B3 vs GRU benchmark
    serve.py         M6: batched live inference, rules-mode fallback
  api/
    main.py          FastAPI: lifespan clock, cursor deltas, control endpoints
    schemas.py       Pydantic response models (the API validation boundary)
  web/
    index.html       single page (72 lines)
    app.js           dashboard logic (670 lines) — renders, never computes
    styles.css, leaflet.js, leaflet.css
  scripts/
    sanity_check.py  headless physics report
    export_sites.py  sites_300.json / .csv
    counterfactual.py M7: the four-arm study
    cast_seed.py     M8: search seeds for the demo world
tests/               70 tests (see §21)
models/              committed: doctor_xgb.json, feature_order.json,
                     doctor_metrics.json, oracle_metrics.json
                     (gitignored until this branch: doctor_scaler.npz,
                     oracle_gru.pt, oracle_stats.npz)
data/                gitignored, regenerable (CSVs + sequence npz)
reports/             counterfactual.csv, counterfactual_summary.json
docs/                this file
```

### 31. Glossary

| Term | Meaning here |
|------|--------------|
| NOC | Network Operations Center — the monitoring/control room this project simulates |
| eNodeB | LTE base station; the 300 simulated towers |
| EPC | Evolved Packet Core — the two (fiber + microwave) central sites |
| RSRP | Reference Signal Received Power (dBm) |
| SINR | Signal-to-Interference-plus-Noise Ratio (dB) |
| S11 | Return loss (dB); drifting toward 0 means the antenna is reflecting power — VSWR problem |
| COST-231 | Classic urban macro-cell path-loss model (Hata variant), valid 1500–2000 MHz |
| Shadow fading | Log-normal large-scale variation (σ = 6 dB injected here) |
| ITU-R P.530 / P.838 | Rain attenuation / rainfall-rate models used for the 23 GHz microwave link |
| MTTR | Mean Time To Repair |
| AUC-PR | Area under the precision-recall curve — the honest ranking metric at 1–2% prevalence |
| Brier score | Calibration of predicted probabilities (lower is better) |
| GRU | Gated Recurrent Unit — the small recurrent network used by the Oracle |
| XGBoost | Gradient-boosted trees — the Doctor and the B3 baseline |
| Exogenous schedule | The fault/weather/cut timeline, generated from the seed before the run and never mutated |
| Episode | One fault instance (with a unique id); all its windows/ledger entries share it |
| Masked | A scheduled fault that fired on an already-broken node — recorded, not dropped |
| Pre-empted | A gradual fault stopped by a tier-1 mitigation before activation |
| Tier 1 / Tier 2 | Auto (cheap, reversible) / Approve (consumes a crew) actions |
| Break-even precision | p* = C_false / (ΔC + C_false) = 0.4375 — the cost-derived acting threshold |
| Tower-minutes | downtime or cost unit: one faulty tower for one 5-min tick = 5 tower-min |
| Clairvoyant arm | The M7 upper bound: perfect knowledge of gradual faults only |
| Seed casting (M8) | Searching seeds for one whose emergent world contains the demo beats |

### 32. Key numbers cheat-sheet

| Constant | Value | Where it matters |
|----------|-------|------------------|
| Tick | 5 min (288/day) | the whole sim |
| Nodes / teams / rings | 300 / 10 / 10 | fleet sizing |
| Start day-of-year | 220 (early August) | demo season |
| Fault base rate | 0.001/tick/node (~100× real) | demo legibility |
| Gradual / instant | 75% / 25% | recall ceiling |
| Fiber cut rate | 0.08/day/ring (×3 in storms) | backhaul process |
| Crew speed | 28 km/h (2333 m/tick) | travel time, animation |
| Break-even precision | 0.4375 (from 90/45/35) | Commander |
| AI inference cadence | every 6 ticks (30 sim min) | serving |
| Standby horizon | 12 ticks (60 min) = Oracle horizon | pre-dispatch |
| Tier-2 cooldown | 24 ticks (2 h) | approval queue |
| Throttle / shed | 50% × 12t / 40% + 15% boost | tier-1 actions |
| Oracle window | 12 ticks × 12 channels | M model input |
| Doctor features | 71 | M model input |
| Doctor subsample | healthy × 0.10 (reweighted at train) | data pipeline |
| Oracle neg keep | × 0.06 | data pipeline |
| Embargo | 24 ticks | data pipeline |
| Watchdog | 120 ticks (10 h) | no orphaned faults |
| M7 approval latencies | B 10 min / C 5 min / D 0 | counterfactual arms |
| Demo seed | 131 (score 14/15) | the story |

---

*These notes were generated from the code at branch `arena/01a04463-autonoc-project`
(2026-08-27). Where the README and the committed artifacts disagree, the code
and the artifacts win and the discrepancy is listed in §29.*
