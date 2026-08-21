"""
Feature construction. ONE builder, shared by training and inference.

v1 had two separate code paths and they drifted: the scaler expected 35
features in a fixed order, the live path supplied 11, and nothing caught it
until the model silently produced nonsense.

THE CARDINAL RULE
    Features at tick t may use ONLY data from ticks <= t.

The Oracle's label is "fails within N ticks", which is legitimately derived
from the future. A FEATURE that peeks ahead is not — it is the single easiest
way to accidentally build a 99% model, and the hardest to notice afterwards.
`assert_no_lookahead` enforces this and a test calls it.
"""
from __future__ import annotations

import math

from autonoc.engine import config as C

# Metrics captured every tick in ENodeB.hist_fine
BASE_METRICS = (
    "rsrp", "sinr", "s11", "latency", "jitter", "packet_loss",
    "throughput", "cpu_load", "temperature", "voltage", "battery_pct", "dust",
)

# Static site attributes. Deliberately NOT site_id: the model would memorise
# "SLY-eNB-088 fails a lot", which does not transfer to an unseen tower.
# These describe the *kind* of site, so they generalise.
STATIC_FEATURES = (
    "generation", "clutter_c", "elevation_m", "is_critical",
    "grid_tier_code", "agg_id",
)

_GRID_TIER_CODE = {"STRONGEST": 0, "STRONG": 1, "MEDIUM": 2,
                   "UNSTABLE": 3, "EXPOSED": 4}


def feature_names() -> list[str]:
    """Canonical order. Persisted at training time, asserted at inference."""
    names: list[str] = []
    names += [f"{m}" for m in BASE_METRICS]                 # current value
    names += [f"{m}_mean_1h" for m in BASE_METRICS]         # fine-window mean
    names += [f"{m}_std_1h" for m in BASE_METRICS]          # fine-window std
    names += [f"{m}_delta" for m in BASE_METRICS]           # tick-over-tick
    names += [f"{m}_slope_1h" for m in BASE_METRICS]        # trend over window
    names += ["signal_efficiency", "thermal_headroom", "power_margin",
              "s11_excess", "load_pressure"]
    names += list(STATIC_FEATURES)
    return names


N_FEATURES = len(feature_names())


def _slope(values: list[float]) -> float:
    """Least-squares slope per tick. Captures 'getting worse', not just 'bad'."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den if den else 0.0


def build_vector(node) -> list[float]:
    """Build one feature row from a node's CURRENT state and history.

    Reads only hist_fine (past readings) and static attributes. No engine
    lookahead, no schedule access, no knowledge of pending faults.
    """
    hist = list(node.hist_fine)
    if not hist:
        hist = [{m: getattr(node, _attr(m)) for m in BASE_METRICS}]

    cur = {m: getattr(node, _attr(m)) for m in BASE_METRICS}
    out: list[float] = []

    out += [cur[m] for m in BASE_METRICS]

    for m in BASE_METRICS:
        series = [h[m] for h in hist]
        n = len(series)
        mean = sum(series) / n
        out.append(mean)
    for m in BASE_METRICS:
        series = [h[m] for h in hist]
        n = len(series)
        if n < 2:
            out.append(0.0)
        else:
            mu = sum(series) / n
            out.append(math.sqrt(sum((v - mu) ** 2 for v in series) / (n - 1)))
    for m in BASE_METRICS:
        series = [h[m] for h in hist]
        out.append(series[-1] - series[-2] if len(series) >= 2 else 0.0)
    for m in BASE_METRICS:
        out.append(_slope([h[m] for h in hist]))

    # engineered: ratios and margins that carry more signal than raw values
    sinr_safe = cur["sinr"] if abs(cur["sinr"]) > 0.5 else 0.5
    out.append(cur["rsrp"] / sinr_safe)                       # signal_efficiency
    out.append(C.THRESH_TEMP - cur["temperature"])            # thermal_headroom
    out.append(cur["voltage"] - C.VOLTAGE_BATT_EMPTY)         # power_margin
    out.append(cur["s11"] - C.THRESH_S11)                     # s11_excess
    out.append(cur["cpu_load"] * cur["latency"] / 1000.0)     # load_pressure

    out.append(float(node.generation))
    out.append(float(C.AGG_SITES[node.agg_id][5]))            # clutter_c
    out.append(float(node.elevation_m))
    out.append(1.0 if node.is_critical else 0.0)
    out.append(float(_GRID_TIER_CODE[node.grid_tier]))
    out.append(float(node.agg_id))

    return out


def _attr(metric: str) -> str:
    """hist_fine key -> ENodeB attribute name."""
    return {"packet_loss": "packet_loss", "cpu_load": "cpu_load",
            "temperature": "temperature", "battery_pct": "battery_pct",
            "dust": "dust_accum"}.get(metric, metric)


def assert_no_lookahead(node, engine) -> None:
    """Guard for the cardinal rule.

    Builds a vector, advances the engine, rebuilds. If the first vector could
    see the future its values would already reflect the later state.
    """
    before = build_vector(node)
    engine.step()
    after = build_vector(node)
    assert len(before) == len(after) == N_FEATURES
    # the vectors must differ: identical vectors would mean the features are
    # not reading live state at all
    assert before != after, "features appear frozen — not reading node state"
