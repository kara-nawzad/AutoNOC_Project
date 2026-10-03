"""Read-only presentation projections for the command center.

All operational aggregation stays on the server (I6). No schedule, hidden onset
or future state is exposed. History is sampled by the API clock, never a GET.
The engine's physics, RNG streams and model feature contracts are untouched.
"""
from collections import Counter, deque

from autonoc.engine import config as C
from autonoc.engine.placement import ROADS

# Semantic presentation tokens are served exclusively via /api/config (I5).
PALETTE = {
    "healthy": "#10b981", "warning": "#f59e0b", "critical": "#f43f5e",
    "fiber": "#06b6d4", "prediction": "#8b5cf6", "crew": "#38bdf8",
    "muted": "#64748b",
}
SEVERITY_COLORS = {
    "CRITICAL": PALETTE["critical"], "MAJOR": "#fb923c",
    "MINOR": PALETTE["warning"], "WARNING": PALETTE["warning"],
    "CLEARED": PALETTE["healthy"], "INFO": PALETTE["crew"],
}
POWER_COLORS = {
    "Grid": PALETTE["healthy"], "Battery": PALETTE["warning"],
    "Generator": PALETTE["prediction"], "Solar": PALETTE["fiber"],
}


def config_payload():
    return {
        "roads": [{"name": name, "path": path} for name, path in ROADS.items()],
        "network_name": "Sulaymaniyah", "region_label": "IRAQ / SUL",
        "palette": PALETTE, "severity_colors": SEVERITY_COLORS,
        "power_colors": POWER_COLORS, "healthy_status": C.STATUS_HEALTHY,
        "offline_statuses": [C.STATUS_POWER, C.STATUS_BACKHAUL],
        "poll_ms": 1000, "history_ticks": 30,
        "prediction_horizon_min": C.HISTORY_FINE * C.TICK_MINUTES,
        "speed_min": 0.25, "speed_max": 10.0,
        "fault_options": [{"value": k, "label": v}
                          for k, v in C.STATUS_NAMES.items() if k != C.STATUS_HEALTHY],
        "generation_names": {C.GEN_LEGACY: "Legacy", C.GEN_STANDARD: "Standard",
                             C.GEN_MODERN: "Modernised"},
    }


def incidents(engine):
    """Operator alarm view, including work already dispatched to a crew.

    Group backhaul symptoms by ring. This is a display correlation, not a
    change to dispatch.py's per-cut work orders. ATS latches are separate
    active facility alarms; fuel theft is reported as a cumulative event.
    """
    result, claimed = [], set()
    for ring in engine.net.rings:
        if not ring.cuts:
            continue
        affected = [nid for nid in ring.node_ids
                    if engine.net.by_id[nid].status == C.STATUS_BACKHAUL]
        claimed.update(affected)
        result.append({
            "id": f"ring-{ring.ring_id}", "node_id": None,
            "title": "Fiber ring isolated" if ring.is_isolated else "Fiber protection lost",
            "detail": f"Ring {ring.ring_id:02d} · {len(ring.cuts)} open cut(s)",
            "severity": "CRITICAL" if ring.is_isolated else "MINOR",
            "affected": len(affected), "since_tick": min(c.started_tick for c in ring.cuts),
            "dispatched": any(c.dispatched for c in ring.cuts),
        })
    for node in engine.nodes:
        if node.is_faulty and node.node_id not in claimed:
            result.append({
                "id": f"node-{node.node_id}-{node.fault_started_tick}",
                "node_id": node.node_id, "title": C.STATUS_NAMES[node.status],
                "detail": engine.net.agg_sites[node.agg_id].name,
                "severity": C.X733_SEVERITY[node.status], "affected": 1,
                "since_tick": max(0, node.fault_started_tick),
                "dispatched": node.tech_dispatched,
            })
        if node.ats_failed:
            result.append({
                "id": f"ats-{node.node_id}", "node_id": node.node_id,
                "title": "ATS failure to crank", "detail": "Generator transfer switch",
                "severity": "CRITICAL", "affected": 1, "since_tick": engine.tick,
                "dispatched": node.tech_dispatched,
            })
    order = {"CRITICAL": 0, "MAJOR": 1, "MINOR": 2, "WARNING": 3}
    return sorted(result, key=lambda a: (order[a["severity"]], a["since_tick"], a["id"]))


def sample(engine):
    nodes = engine.nodes
    size = max(1, len(nodes))
    healthy = sum(n.status == C.STATUS_HEALTHY for n in nodes)
    offline = sum(n.status in (C.STATUS_POWER, C.STATUS_BACKHAUL) for n in nodes)
    return {
        "tick": engine.tick, "sim_time": engine.sim_time,
        "availability": round(healthy / size * 100, 2),
        "incidents": len(incidents(engine)),
        "power_events": engine.stats["ats_failures"] + engine.stats["fuel_thefts"],
        "throughput_gbps": round(sum(n.throughput for n in nodes) / 1000, 3),
        # Synthetic simulator KPI, not a measured bearer-level ratio.
        "drop_rate": round(sum(n.packet_loss for n in nodes) / size, 3),
        "prb": round(sum(n.prb_util for n in nodes) / size, 2),
        "online": healthy, "degraded": len(nodes) - healthy - offline,
        "offline": offline,
    }


class History:
    """Bounded server-tick history; record only under the API engine lock."""
    def __init__(self):
        self.rows = deque(maxlen=30)
        self.owner = None

    def record(self, engine):
        if self.owner is not engine:
            self.rows.clear()
            self.owner = engine
        row = sample(engine)
        if self.rows and self.rows[-1]["tick"] == engine.tick:
            self.rows[-1] = row
        else:
            self.rows.append(row)

    def read(self, engine, current):
        rows = list(self.rows) if self.owner is engine else []
        # Same-tick manual actions must appear immediately without GET mutation.
        return [r for r in rows if r["tick"] < engine.tick][-29:] + [current]


def dashboard(engine, history):
    current = sample(engine)
    rows = history.read(engine, current)
    previous = next((r for r in reversed(rows)
                     if r["tick"] <= engine.tick - C.TICKS_PER_HOUR), None)
    change = None
    if previous and previous["throughput_gbps"] > 0:
        change = round((current["throughput_gbps"] / previous["throughput_gbps"] - 1) * 100, 1)
    top = sorted(engine.nodes, key=lambda n: (-n.prb_util, n.cqi, n.node_id))[:4]
    forecasts = []
    if engine.ai_enabled:
        for nid, v in engine.ai_verdicts.items():
            node = engine.net.by_id.get(nid)
            if node is None or node.is_faulty:
                continue
            forecasts.append({"node_id": nid, "probability": float(v["p_fail"]),
                              "label": C.STATUS_NAMES.get(v["cls"], "Unclassified"),
                              "actionable": float(v["p_fail"]) > C.BREAK_EVEN_PRECISION})
    forecasts.sort(key=lambda v: (-v["probability"], v["node_id"]))
    power = Counter(n.power_source for n in engine.nodes)
    fleet = Counter(t.state for t in engine.teams)
    return {
        "current": current, "history": rows, "traffic_change_pct": change,
        "operational_pct": current["availability"], "incidents": incidents(engine),
        "top_cells": [{"node_id": n.node_id, "district": engine.net.agg_sites[n.agg_id].name,
                       "prb": round(n.prb_util, 1), "cqi": n.cqi, "status": n.status}
                      for n in top],
        "forecast": forecasts[0] if forecasts else None,
        "actionable_predictions": sum(f["actionable"] for f in forecasts),
        "power": [{"name": name, "count": power[name],
                   "fraction": power[name] / max(1, len(engine.nodes))}
                  for name in POWER_COLORS],
        "active_ats": sum(n.ats_failed for n in engine.nodes),
        "fuel_thefts": engine.stats["fuel_thefts"],
        "fleet": {s: fleet[s] for s in ("IDLE", "EN_ROUTE", "STANDBY", "REPAIRING", "RETURNING")},
    }
