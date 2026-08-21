"""
Exogenous fault scheduling and causal degradation.

TWO principles, both learned the hard way from v1.

1. Faults are a CAUSE, not a threshold. Pick the fault first, then degrade
   metrics through it. v1 thresholded metrics to create labels and then asked
   a model to predict those labels from the same metrics — circular, and worth
   a meaningless 99.6% accuracy.

2. The schedule is EXOGENOUS. It is generated before any run begins and
   depends only on the seed, never on simulation state. Without this the
   counterfactual study is invalid: an AI that repairs a node early makes it
   eligible for a fault the no-AI arm never saw, so the two arms drift into
   different worlds even with separate RNG streams.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from . import config as C


@dataclass(slots=True)
class FaultEvent:

    tick: int                # when the fault becomes active
    node_id: str
    kind: int                # STATUS_*
    is_gradual: bool
    onset_offset: int        # ticks of degradation before it lands
    severity: float          # 1.0 normal, 0.35 ambiguous
    curve: str               # linear | exponential | sigmoid | step
    episode_id: int

    def as_tuple(self) -> tuple:
        return (self.tick, self.node_id, self.kind, self.is_gradual,
                self.onset_offset, round(self.severity, 6), self.curve,
                self.episode_id)


@dataclass(slots=True)
class FiberCutEvent:

    tick: int
    ring_id: int
    segment_idx: int
    position: float
    cause: str
    episode_id: int

    def as_tuple(self) -> tuple:
        return (self.tick, self.ring_id, self.segment_idx,
                round(self.position, 6), self.cause, self.episode_id)


# ------------------------------------------------------------------ weather
def generate_weather_timeline(seed: int, horizon: int, num_sites: int) -> list[dict]:
    """Per-tick weather for every aggregation site. Exogenous."""
    rng = random.Random(seed * 7919 + 2)
    timeline: list[dict] = []
    state = {i: _roll_weather(rng, 0) for i in range(num_sites)}
    remaining = {i: state[i]["ticks"] for i in range(num_sites)}
    for tick in range(horizon):
        day = (C.START_DAY_OF_YEAR + tick // C.TICKS_PER_DAY) % 365
        month = min(12, max(1, int(day / 30.4) + 1))
        snap = {}
        for site in range(num_sites):
            remaining[site] -= 1
            if remaining[site] <= 0:
                state[site] = _roll_weather(rng, month)
                remaining[site] = state[site]["ticks"]
            snap[site] = state[site]
        timeline.append(snap)
    return timeline


def _roll_weather(rng: random.Random, month: int) -> dict:
    names = list(C.WEATHER_TYPES)
    probs = []
    for n in names:
        p = C.WEATHER_TYPES[n][0]
        if n == "Dust":
            p *= C.SEASON_DUST_MULT.get(month, 1.0)
        elif n == "Storm":
            p *= C.SEASON_STORM_MULT.get(month, 1.0)
        probs.append(p)
    name = rng.choices(names, weights=probs, k=1)[0]
    _, mult, wmin, wmax, tdelta, rain = C.WEATHER_TYPES[name]
    lo, hi = ((C.DUST_MIN_TICKS, C.DUST_MAX_TICKS) if name == "Dust"
              else (C.WEATHER_MIN_TICKS, C.WEATHER_MAX_TICKS))
    return {
        "type": name, "mult": mult, "temp_delta": tdelta, "rain": rain,
        "wind": rng.uniform(wmin, wmax), "ticks": rng.randint(lo, hi),
    }


# ------------------------------------------------------------------ schedule
def generate_schedule(seed: int, horizon: int, nodes,
                      weather_timeline=None) -> list[FaultEvent]:
    """Pre-generate every node fault. Depends only on the seed.

    Note what is deliberately absent: any reference to node.status. Eligibility
    is NOT checked here. A scheduled fault landing on an already-broken node is
    handled at replay time as 'masked', and counted identically in every arm so
    the recall denominator cannot drift between them.
    """
    rng = random.Random(seed * 7919 + 1)
    events: list[FaultEvent] = []
    episode = 0
    for tick in range(horizon):
        for node in nodes:
            weather_mult = 1.0
            if weather_timeline is not None:
                weather_mult = weather_timeline[tick][node.agg_id]["mult"]
            rate = (C.FAULT_CHANCE_PER_TICK
                    * weather_mult
                    * C.GEN_FAULT_MULT[node.generation])
            if rng.random() >= rate:
                continue
            mix = C.FAULT_MIX.get(node.agg_id, C.FAULT_MIX_DEFAULT)
            kind = rng.choices(
                [C.STATUS_CONGESTION, C.STATUS_OVERHEAT,
                 C.STATUS_RF, C.STATUS_POWER],
                weights=mix, k=1)[0]
            gradual = rng.random() < C.GRADUAL_FRACTION
            if gradual and kind in C.FAULT_CURVE:
                curve, lo, hi = C.FAULT_CURVE[kind]
                offset = rng.randint(lo, hi)
            else:
                curve, offset, gradual = "step", 0, False
            severity = (C.AMBIGUOUS_SEVERITY
                        if rng.random() < C.AMBIGUOUS_FRACTION else 1.0)
            events.append(FaultEvent(
                tick=tick, node_id=node.node_id, kind=kind,
                is_gradual=gradual, onset_offset=offset,
                severity=severity, curve=curve, episode_id=episode))
            episode += 1
    return events


def generate_fiber_schedule(seed: int, horizon: int, rings,
                            weather_timeline=None) -> list[FiberCutEvent]:
    """Fiber cuts as an independent process.

    Treating backhaul as a share of the node fault rate gave 10.4 cuts/day
    against a real-world 0.03-0.1/day — about 300x too many. The demo obtains
    its cut from a cast seed instead of an inflated rate.
    """
    rng = random.Random(seed * 7919 + 6)
    events: list[FiberCutEvent] = []
    episode = 1_000_000                    # separate id space from node faults
    for tick in range(horizon):
        for ring in rings:
            rate = C.FIBER_CUT_CHANCE_PER_TICK
            cause = "construction"
            if weather_timeline is not None:
                first = ring.node_ids[0] if ring.node_ids else None
                if first is not None:
                    w = weather_timeline[tick]
                    # storms raise the odds and change the attributed cause
                    any_storm = any(v["type"] == "Storm" for v in w.values())
                    if any_storm:
                        rate *= 3.0
                        cause = "storm"
            if rng.random() >= rate or not ring.segments:
                continue
            events.append(FiberCutEvent(
                tick=tick, ring_id=ring.ring_id,
                segment_idx=rng.randrange(len(ring.segments)),
                position=rng.random(), cause=cause, episode_id=episode))
            episode += 1
    return events


# ------------------------------------------------------------------ curves
def curve_progress(curve: str, p: float) -> float:
    """Fraction of full severity reached at progress p in [0, 1].

    Shapes are assigned per fault type in config. A single shape would let a
    trivial trend detector match the GRU and hollow out the deep-learning
    benchmark before it was run.
    """
    p = 0.0 if p < 0.0 else 1.0 if p > 1.0 else p
    if curve == "linear":
        return p
    if curve == "exponential":
        return (math.exp(3.0 * p) - 1.0) / (math.exp(3.0) - 1.0)
    if curve == "sigmoid":
        return 1.0 / (1.0 + math.exp(-10.0 * (p - 0.5)))
    return 1.0 if p >= 1.0 else 0.0        # step


def apply_degradation(node, kind: int, frac: float, severity: float, rng) -> None:
    """Move metrics toward the fully-degraded state.

    `frac` is how far along the curve we are; `severity` scales the endpoint
    so ambiguous faults sit genuinely near the decision boundary rather than
    being trivially separable.
    """
    k = frac * severity

    # Every metric is clamped to a physically possible range. Degradation is
    # applied repeatedly as a fault progresses, so unclamped multipliers
    # compound: an early build produced 118 C, +8.5 dB S11 and 1194 ms
    # latency. The Pydantic response layer caught it at the API boundary,
    # which is precisely why that layer exists.
    if kind == C.STATUS_CONGESTION:
        node.cpu_load = min(99.0, node.cpu_load + 35.0 * k)
        node.latency = min(C.MAX_LATENCY_MS, node.latency * (1.0 + 2.0 * k))
        node.jitter = min(C.MAX_JITTER_MS, node.jitter * (1.0 + 1.8 * k))
        node.packet_loss = min(100.0, node.packet_loss + 5.0 * k)
        node.throughput = max(0.0, node.throughput * (1.0 - 0.45 * k))
    elif kind == C.STATUS_OVERHEAT:
        node.temperature = min(C.MAX_TEMP_C, node.temperature + 25.0 * k)
        node.cpu_load = min(99.0, node.cpu_load + 17.0 * k)
        node.throughput = max(0.0, node.throughput * (1.0 - 0.35 * k))
    elif kind == C.STATUS_RF:
        # return loss collapses toward -8 dB. S11 above 0 dB would mean the
        # antenna reflects more power than it receives, which is impossible.
        node.s11 = min(C.MAX_S11_DB, node.s11 + 11.0 * k)
        node.rsrp = max(C.RSRP_FLOOR, node.rsrp - 10.0 * k)
        node.sinr = max(C.SINR_FLOOR, node.sinr - 7.0 * k)
        node.throughput = max(0.0, node.throughput * (1.0 - 0.6 * k))
        node.packet_loss = min(100.0, node.packet_loss + 7.0 * k)
    elif kind == C.STATUS_POWER:
        node.voltage = max(C.MIN_VOLTAGE, node.voltage - 1.2 * k)
        node.battery_pct = max(0.0, node.battery_pct - 30.0 * k)
    elif kind == C.STATUS_BACKHAUL:
        # A backhaul-isolated node is FINE but unreachable: normal RF, normal
        # temperature, normal power. Telling that apart from a genuinely
        # broken node demands the opposite action, and is what makes the
        # correlation problem a real diagnostic subtlety.
        node.throughput = 0.0
        node.packet_loss = 100.0
        node.latency = C.MAX_LATENCY_MS
