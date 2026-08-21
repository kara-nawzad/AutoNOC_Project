"""
Every tunable constant. No other module in engine/ may define a magic number.

Anything the frontend needs is served by GET /api/config — never hard-coded
in JavaScript. That duplication is what caused v1's SLY-032 desync, where the
map said "Critical" and the sidebar said "Normal" because the same threshold
existed in two places and drifted.
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------- geography
# Bounds derived from real landmark positions, not chosen arbitrarily.
# The city stretches east-west along a valley, so the envelope is wider
# than it is tall.
LAT_MIN: Final = 35.509
LAT_MAX: Final = 35.630
LON_MIN: Final = 45.292
LON_MAX: Final = 45.485

EARTH_RADIUS_M: Final = 6_371_000.0

# Dual core: metro-redundant, 1.70 km apart. NOT geo-redundant (30-100 km) —
# an operator in a city this size would not build a core 50 km away.
EPC_PRIMARY: Final = ("SPU University", 35.5500, 45.4200, "fiber")
EPC_BACKUP: Final = ("Grand Millennium", 35.5602, 45.4340, "microwave")
DEPOT_LAT: Final = 35.5500
DEPOT_LON: Final = 45.4200

# ---------------------------------------------------------------- time
TICK_MINUTES: Final = 5
TICKS_PER_HOUR: Final = 12
TICKS_PER_DAY: Final = 288
TICKS_PER_YEAR: Final = TICKS_PER_DAY * 365
# Simulation start day-of-year. 220 = early August: peak heat and dust season,
# the conditions the demo narrative is built around. Training data sweeps the
# full year regardless.
START_DAY_OF_YEAR: Final = 220

# ---------------------------------------------------------------- network
NUM_NODES: Final = 300
NUM_TEAMS: Final = 10

# id, name, lat, lon, node_count, clutter_C, colour
# clutter_C is the COST-231 correction term — a parameter with real physical
# meaning, unlike v1's hand-tuned path-loss exponents.
AGG_SITES: Final = (
    (0, "Goizha Mountain",  35.6100, 45.4600, 18,  -8.0, "#FF6B6B"),
    (1, "Grand Millennium", 35.5602, 45.4340, 34,  +3.0, "#7F00FF"),
    (2, "Salim Street",     35.5565, 45.4295, 42,  +3.0, "#00F2FE"),
    (3, "University",       35.5790, 45.3550, 36,  +1.0, "#00F5A0"),
    (4, "Sarchinar",        35.5830, 45.3760, 28,  -2.0, "#FF9600"),
    (5, "Bakrajo",          35.5290, 45.3590, 32,  -2.0, "#9D4EDD"),
    (6, "Tasluja Road",     35.5700, 45.3300, 24,  -5.0, "#F8B500"),
    (7, "Hawara Barza",     35.5748, 45.4496, 26,  -1.0, "#FFD700"),
    (8, "Airport",          35.5617, 45.3167, 22,  -6.0, "#4FACFE"),
    (9, "Rizgari",          35.5450, 45.4520, 38,   0.0, "#77E4C8"),
)
assert sum(s[4] for s in AGG_SITES) == NUM_NODES

# Faruk Medical City sits inside AGG-9 Rizgari as a priority cluster, not as
# its own aggregation site — it is 1.14 km from Rizgari, and two aggregation
# nodes 1 km apart is poor network design.
FARUK_LAT: Final = 35.5552
FARUK_LON: Final = 45.4531
FARUK_RADIUS_KM: Final = 0.8
CRITICAL_PRIORITY_MULT: Final = 3.0

NODE_SPREAD_DEG: Final = 0.012

TEAM_NAMES: Final = (
    "Alpha Response", "Bravo Unit", "Charlie Squad", "Delta Force", "Echo Team",
    "Fox Patrol", "Golf Crew", "Hawk Unit", "Iris Response", "Jade Squad",
)
# Soft constraint: a mismatched team is slower, never blocked. A hard
# constraint would starve RF faults whenever all three RF techs were busy —
# structurally identical to v1's dispatch bug.
TEAM_SKILLS: Final = ("RF", "RF", "RF", "POWER", "POWER", "POWER",
                      "GENERAL", "GENERAL", "GENERAL", "GENERAL")
SKILL_MULT_MATCHED: Final = 1.0
SKILL_MULT_GENERAL: Final = 1.2
SKILL_MULT_MISMATCH: Final = 1.5

# ---------------------------------------------------------------- generations
# Gives the Doctor a real latent variable to learn, and makes remote reset
# meaningful: modernised sites cost zero team-time to fix for soft faults.
GEN_LEGACY: Final = 0
GEN_STANDARD: Final = 1
GEN_MODERN: Final = 2
GEN_WEIGHTS: Final = (0.15, 0.70, 0.15)
GEN_FAULT_MULT: Final = {GEN_LEGACY: 1.6, GEN_STANDARD: 1.0, GEN_MODERN: 0.6}
GEN_TEMP_OFFSET: Final = {GEN_LEGACY: 3.0, GEN_STANDARD: 0.0, GEN_MODERN: -2.0}
GEN_REMOTE_RESET: Final = {GEN_LEGACY: 0.0, GEN_STANDARD: 0.12, GEN_MODERN: 0.35}

# ---------------------------------------------------------------- radio
# COST-231 Hata. NOT Friis: free-space is ~27 dB optimistic at 1 km, which
# made the RSRP < -100 dBm threshold unreachable anywhere inside the map and
# left that entire branch of v1's physics as dead code.
#
# Caveat: COST-231 is specified for 1500-2000 MHz; we run at 2100 MHz.
# Measured cost of that extrapolation is 0.72 dB — roughly 10x smaller than
# the 6-8 dB shadow fading we deliberately inject, so it is statistically
# irrelevant. Documented rather than hidden.
FREQ_MHZ: Final = 2100.0
TX_POWER_DBM: Final = 43.0
ANTENNA_GAIN_DB: Final = 15.0
BS_HEIGHT_M: Final = 30.0
MS_HEIGHT_M: Final = 1.5
SHADOW_SIGMA_DB: Final = 6.0

RSRP_CONVERGENCE: Final = 0.30
ELEVATION_BONUS_MAX_DB: Final = 6.0
LOAD_PENALTY_MAX_DB: Final = 5.0

RSRP_FLOOR: Final = -130.0
RSRP_CEIL: Final = -50.0
SINR_FLOOR: Final = -5.0

# Hard physical ceilings. Degradation compounds across ticks, so every
# fault effect must clamp or metrics drift into impossible territory.
MAX_TEMP_C: Final = 95.0
MAX_LATENCY_MS: Final = 500.0
MAX_JITTER_MS: Final = 50.0
MAX_S11_DB: Final = -1.0        # above 0 dB the antenna would amplify
MIN_VOLTAGE: Final = 8.0
SINR_CEIL: Final = 35.0

# ---------------------------------------------------------------- microwave
# 23 GHz: degrades visibly in a storm without failing constantly.
# 15 GHz is too robust to be interesting; 38 GHz fails too often.
MW_FREQ_GHZ: Final = 23.0
MW_PATH_KM: Final = 1.70
MW_LINK_MARGIN_DB: Final = 38.0
MW_ITU_K: Final = 0.128       # ITU-R P.838 coefficients at 23 GHz
MW_ITU_ALPHA: Final = 1.0214

# ---------------------------------------------------------------- traffic
# Peaks at tick 168 = 14:00. v1 documented "2 PM (tick 204)"; tick 204 is 17:00.
TRAFFIC_BASE: Final = 0.30
TRAFFIC_AMPLITUDE: Final = 0.35
TRAFFIC_PEAK_TICK: Final = 168

# per agg site: (amplitude_mult, peak_shift_ticks, base_mult)
TRAFFIC_PROFILE: Final = {
    0: (0.6, 0, 0.7),     # Goizha — low, steady
    1: (1.3, 0, 1.1),     # Grand Millennium — very high
    2: (1.4, 0, 1.2),     # Salim Street — highest daytime
    3: (1.2, -12, 0.9),   # University — bursty, earlier peak
    4: (0.9, +36, 0.8),   # Sarchinar — evening/weekend leisure
    5: (0.9, +24, 0.9),   # Bakrajo — residential evening
    6: (0.4, 0, 1.0),     # Tasluja — flat 24 h industrial
    7: (0.7, +30, 0.9),   # Hawara Barza — high throughput, low density
    8: (1.0, 0, 0.8),     # Airport — flight-schedule spikes
    9: (1.1, +24, 1.0),   # Rizgari — dense residential, evening
}

# ---------------------------------------------------------------- thermal
AMBIENT_BASE_C: Final = 21.0        # annual mean
AMBIENT_SEASONAL_AMP: Final = 13.0  # Jan ~8C, Jul ~34C
AMBIENT_DAILY_AMP: Final = 9.0
AMBIENT_PEAK_TICK: Final = 180      # ~15:00
TEMP_PER_CPU_PCT: Final = 0.22
TEMP_CONVERGENCE: Final = 0.25
TEMP_NOISE_SIGMA: Final = 0.6

# ---------------------------------------------------------------- power
BATTERY_TICKS: Final = 72           # 6 h at full capacity
GENERATOR_TICKS: Final = 288        # 24 h fuel
SOLAR_START_TICK: Final = 48        # 04:00
SOLAR_END_TICK: Final = 240         # 20:00
SOLAR_CHARGE_PCT: Final = 0.5
GRID_CHARGE_PCT: Final = 0.5
GEN_START_BATTERY_PCT: Final = 10.0

VOLTAGE_GRID: Final = 12.0
VOLTAGE_BATT_FULL: Final = 12.5
VOLTAGE_BATT_EMPTY: Final = 11.0
VOLTAGE_NOISE: Final = 0.05

# Two distinct weak-grid mechanisms, deliberately:
#   Bakrajo — mains instability, repeated cycling, capacity fade -> PREDICTABLE
#   Goizha  — lightning/wind snaps the line                      -> UNPREDICTABLE
# Same symptom class, opposite precursors. This is where the 75/25
# gradual/instant split comes from physically rather than by decree.
GRID_TIER: Final = {
    0: "EXPOSED", 1: "STRONG", 2: "STRONGEST", 3: "STRONG", 4: "MEDIUM",
    5: "UNSTABLE", 6: "MEDIUM", 7: "MEDIUM", 8: "STRONG", 9: "MEDIUM",
}
GRID_DROPOUT_CHANCE: Final = {
    "STRONGEST": 0.0002, "STRONG": 0.0005, "MEDIUM": 0.0010,
    "UNSTABLE": 0.0045, "EXPOSED": 0.0018,
}
GRID_RESTORE_CHANCE: Final = {
    "STRONGEST": 0.060, "STRONG": 0.040, "MEDIUM": 0.025,
    "UNSTABLE": 0.020, "EXPOSED": 0.008,
}

# Verified stable over a simulated year: Bakrajo fades to 82.7% (6.0 h -> 4.96 h
# backup), Salim Street to 97.1%. Bounded by a floor so it cannot run away.
BATTERY_FADE_PER_CYCLE: Final = 0.04
BATTERY_CAPACITY_FLOOR: Final = 40.0

# ---------------------------------------------------------------- weather
# name: (prob, fault_mult, wind_min, wind_max, temp_delta, rain_mm_h)
WEATHER_TYPES: Final = {
    "Clear":    (0.50, 1.0, 10.0,  25.0,  0.0,   0.0),
    "Wind":     (0.18, 1.8, 50.0,  80.0,  0.0,   0.0),
    "Storm":    (0.10, 2.5, 70.0, 100.0, -2.0,  60.0),
    "Heatwave": (0.12, 2.0,  5.0,  20.0,  5.0,   0.0),
    "Dust":     (0.10, 1.4, 30.0,  60.0,  2.0,   0.0),
}
WEATHER_MIN_TICKS: Final = 12
WEATHER_MAX_TICKS: Final = 48
DUST_MIN_TICKS: Final = 24
DUST_MAX_TICKS: Final = 72
HIGH_WIND_KMH: Final = 60.0

# Dust does NOT attenuate 2.1 GHz (<0.01 dB/km — it only matters above
# ~10 GHz). Modelling it as propagation loss would be an error an RF-literate
# reviewer catches instantly. The real mechanisms are mechanical, and they
# create the only multi-day degradation signature in the model — which is
# precisely what justifies the Oracle's coarse branch.
DUST_ACCUM_PER_TICK: Final = 0.004
DUST_COOLING_PENALTY: Final = 8.0     # deg C at full accumulation
DUST_SOLAR_PENALTY: Final = 0.30
DUST_S11_DRIFT: Final = 3.0
RAIN_WASH_THRESHOLD: Final = 10.0     # mm/h that cleans panels and dishes

# Seasonal weather bias (month -> multipliers). Dust season Mar-Jun,
# thermal stress Jul-Aug, rain Dec-Feb.
SEASON_DUST_MULT: Final = {1: 0.3, 2: 0.5, 3: 1.8, 4: 2.2, 5: 2.0, 6: 1.6,
                           7: 1.2, 8: 1.3, 9: 0.9, 10: 0.6, 11: 0.4, 12: 0.3}
SEASON_STORM_MULT: Final = {1: 1.8, 2: 1.7, 3: 1.3, 4: 1.0, 5: 0.5, 6: 0.2,
                            7: 0.1, 8: 0.1, 9: 0.4, 10: 0.9, 11: 1.4, 12: 1.8}

# ---------------------------------------------------------------- faults
# ~130/day across 300 nodes. This is ~100x a real network's rate — deliberate,
# because a static green map is a useless demo. Documented as an accelerated
# rate rather than left as an unexamined constant.
FAULT_CHANCE_PER_TICK: Final = 0.0010

STATUS_HEALTHY: Final = 0
STATUS_CONGESTION: Final = 1
STATUS_OVERHEAT: Final = 2
STATUS_RF: Final = 3
STATUS_POWER: Final = 4
STATUS_BACKHAUL: Final = 5

STATUS_NAMES: Final = {
    0: "Healthy", 1: "Congestion", 2: "Overheat",
    3: "RF / Antenna", 4: "Power", 5: "Backhaul Isolated",
}
STATUS_COLORS: Final = {
    0: "#00F5A0", 1: "#00F2FE", 2: "#FF9600",
    3: "#FF2A6D", 4: "#FF6B00", 5: "#6B7280",
}

# per-node fault mix (backhaul is an independent process, see below)
FAULT_MIX: Final = {
    0: (0.10, 0.10, 0.55, 0.25),   # Goizha — hardware/exposure heavy
    1: (0.45, 0.20, 0.25, 0.10),   # Grand Millennium — congestion
    2: (0.50, 0.18, 0.24, 0.08),   # Salim Street — congestion
    5: (0.28, 0.35, 0.20, 0.17),   # Bakrajo — overheat + power
    6: (0.20, 0.20, 0.45, 0.15),   # Tasluja — dust-driven RF
}
FAULT_MIX_DEFAULT: Final = (0.32, 0.24, 0.27, 0.17)

# 75% develop gradually (predictable), 25% strike instantly (impossible to
# forecast). This sets an HONEST ceiling on AI recall — a feature, not a
# limitation. It means a good result reads "caught 82% of what was catchable"
# rather than a suspicious 99%.
GRADUAL_FRACTION: Final = 0.75

# Curves assigned by physics. A single shape would let a trivial trend
# detector match the GRU, undermining the deep-learning benchmark.
FAULT_CURVE: Final = {
    STATUS_CONGESTION: ("linear", 4, 12),
    STATUS_OVERHEAT: ("exponential", 6, 18),
    STATUS_RF: ("sigmoid", 12, 24),
    STATUS_POWER: ("linear", 24, 288),
}

AMBIGUOUS_FRACTION: Final = 0.08
AMBIGUOUS_SEVERITY: Final = 0.35

SELF_HEAL_TICKS: Final = {STATUS_CONGESTION: 4, STATUS_OVERHEAT: 5}
REPAIR_TICKS: Final = {
    STATUS_CONGESTION: 4, STATUS_OVERHEAT: 5,
    STATUS_RF: 12, STATUS_POWER: 24, STATUS_BACKHAUL: 18,
}
REPAIR_SKILL: Final = {
    STATUS_CONGESTION: "GENERAL", STATUS_OVERHEAT: "GENERAL",
    STATUS_RF: "RF", STATUS_POWER: "POWER", STATUS_BACKHAUL: "GENERAL",
}

STUCK_WATCHDOG_TICKS: Final = 120

# ---------------------------------------------------------------- fiber
# Cuts are an INDEPENDENT process, not a share of the node fault rate.
# Treating backhaul as 8% of per-node faults gave 10.4 cuts/day against a
# real-world 0.03-0.1/day — roughly 300x too many. The demo gets its cut from
# a cast seed instead.
NUM_RINGS: Final = 10
FIBER_CUT_CHANCE_PER_TICK: Final = 0.08 / TICKS_PER_DAY
RING_MAX_CIRCUMFERENCE_KM: Final = 12.0
RING_MAX_MEMBER_SEPARATION_KM: Final = 6.0
MIN_CORRELATED_ALARMS: Final = 3

# ---------------------------------------------------------------- GNN ripple
NEIGHBOUR_RADIUS_KM: Final = 2.0
RIPPLE_PACKET_LOSS: Final = (0.2, 0.8)
RIPPLE_CPU_LOAD: Final = (2.0, 5.0)

# ---------------------------------------------------------------- teams
# 28 km/h, not 40. Sulaymaniyah is compact: at 40 km/h most trips finished in
# 1-3 real seconds and the vehicle animation was effectively invisible. 28 km/h
# is the honest door-to-door urban average including traffic and junctions —
# the realistic number is also the better-looking one.
TEAM_SPEED_KMH: Final = 28.0
TEAM_STEP_M: Final = TEAM_SPEED_KMH * (TICK_MINUTES / 60.0) * 1000.0

# ---------------------------------------------------------------- detection
# The ONLY place these exist. Served to the frontend via /api/config.
THRESH_RSRP: Final = -100.0
THRESH_S11: Final = -10.0
THRESH_S11_HIGH_WIND: Final = -13.0
THRESH_TEMP: Final = 72.0
THRESH_PACKET_LOSS: Final = 15.0
THRESH_CPU: Final = 90.0

# ---------------------------------------------------------------- history
# Two branches. The fine branch alone cannot see dust: measured SNR 0.08 over
# a 12-tick window. The coarse branch gives SNR 6.93, both from longer
# coverage and from averaging 12 samples per bucket (noise / sqrt(12)).
# The 92% slow-fault recall target depends entirely on this.
HISTORY_FINE: Final = 12        # 1 h at full resolution
HISTORY_COARSE: Final = 24      # 24 h of hourly aggregates
MAX_LOG_ENTRIES: Final = 500
MAX_DELTA_LAG: Final = 60

# ---------------------------------------------------------------- economics
COST_FAILURE_MIN: Final = 90.0
COST_PREEMPT_MIN: Final = 45.0
COST_FALSE_DISPATCH_MIN: Final = 35.0

BREAK_EVEN_PRECISION: Final = (
    COST_FALSE_DISPATCH_MIN
    / ((COST_FAILURE_MIN - COST_PREEMPT_MIN) + COST_FALSE_DISPATCH_MIN)
)  # = 0.438

# ---------------------------------------------------------------- evaluation
# From review #2: evaluating on a rebalanced sample overstated precision by
# 50.1 pp (91.2% vs 41.1% true), which would have flipped the project's
# conclusion from "autonomy justified" to "the AI makes the network worse".
TRUE_PREVALENCE: Final = 0.022
TRAIN_SUBSAMPLE_RATIO: Final = 3.0    # TRAINING ONLY. Never the test set.
EMBARGO_TICKS: Final = HISTORY_FINE + 12   # input window + max horizon

# ---------------------------------------------------------------- commander
# M6 — the Commander. Expected-value dispatch from the Oracle's probabilities.
#
# The decision rule is NOT a hard-coded threshold. It is derived every time
# from the cost model (see engine/commander.py), so a sensitivity analysis on
# the costs (M7) is a one-line change and the break-even moves with it.

# How often (in ticks) the inference worker runs a fresh batch over all nodes.
# 6 ticks = 30 simulated minutes of movement between model refreshes.
AI_INFERENCE_EVERY_TICKS: Final = 6

# Auto-approve tier-2 actions after N WALL-CLOCK seconds. 0 = off. The timer
# lives in the API layer, never in the engine: the engine stays deterministic
# (I3), and a demo can flip this on without touching the sim.
AUTO_APPROVE_SECONDS: Final = 0

# After a tier-2 action is approved or vetoed, do not re-propose the same node
# for this many ticks (2 h). Without this, a persistent verdict re-queues the
# same pre-dispatch every inference cycle.
TIER2_REQUEUE_COOLDOWN_TICKS: Final = 24

# How long a pre-dispatched crew holds on site (STANDBY) before declaring the
# prediction a false dispatch. 12 ticks = 60 min = the Oracle's horizon: if
# the predicted failure has not landed within the window it predicts, the
# crew goes home. Real crews hold on site; counting them false the instant
# they arrive would make pre-positioning physically impossible.
STANDBY_HORIZON_TICKS: Final = 12

# Tier-1 mitigation magnitudes (documented sim effects, all reversible):
#   throttle  — cut offered traffic by THROTTLE_PCT for THROTTLE_TICKS
#   shed      — throttle this node and push SHED_BOOST onto 2 neighbours
#   reboot    — clears soft-state faults (congestion/overheat) instantly
#   switch    — force the generator on before the battery exhausts
THROTTLE_TICKS: Final = 12
THROTTLE_PCT: Final = 0.5
SHED_PCT: Final = 0.4
SHED_BOOST: Final = 0.15
SWITCH_GEN_MIN_BATTERY: Final = 40.0   # start the generator above this %
