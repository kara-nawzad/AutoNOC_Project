"""
Commander — decision theory, not machine learning.

The Oracle produces P(failure within 60 min) for every node. Turning that
probability into an action is NOT a learning problem: it is expected-value
arithmetic over the cost model. Deterministic, inspectable, and far easier to
defend than a learned policy.

    ev_act  = p_fail * (COST_FAILURE_MIN - COST_PREEMPT_MIN)
    ev_wait = (1 - p_fail) * COST_FALSE_DISPATCH_MIN
    act  <=>  ev_act > ev_wait

which reduces exactly to p_fail > BREAK_EVEN_PRECISION — but the threshold is
NEVER hard-coded here. It falls out of the costs, so an M7 sensitivity study
on the costs re-derives it for free.

TIERED AUTONOMY (config-anchored, never re-designed mid-project)

    Auto    throttle, shed load, switch power source, remote reboot
            cheap + reversible -> applied immediately
    Approve pre-dispatch a crew, force a maintenance window, shut a site
            consumes a scarce crew for ~1 h -> operator confirms
    Never   permanent config changes, disabling alarms
            out of scope by construction

This module is pure engine logic: stdlib only, no ML, no file I/O, no wall
clock. Invariant I2 scans engine/ and would reject anything else.
"""
from __future__ import annotations

from . import config as C

# ------------------------------------------------------------------ tiers
TIER_AUTO = 1
TIER_APPROVE = 2
TIER_NEVER = 3

# The only action that consumes a crew and therefore needs approval.
TIER2_ACTIONS = frozenset({"pre_dispatch"})

# Doctor fault class -> tier-1 mitigation. Cheap, reversible, no crew.
AUTO_ACTION_FOR_CLASS = {
    C.STATUS_CONGESTION: "throttle",
    C.STATUS_OVERHEAT: "throttle",
    C.STATUS_RF: "reboot",
    C.STATUS_POWER: "switch_power",
    C.STATUS_BACKHAUL: "pre_dispatch",   # no cheap fix for isolation
}


# ------------------------------------------------------------------ rule
def decision(p_fail: float, crew_available: bool = True) -> bool:
    """Act only when the expected saving exceeds the expected waste.

    ev_act  = p * (COST_FAILURE - COST_PREEMPT)     # the failure we avoid
    ev_wait = (1 - p) * COST_FALSE_DISPATCH         # the waste when wrong

    With the config costs this reduces exactly to p > 0.4375 — derived, not
    hard-coded. A sensitivity study (M7) changes the costs, not this rule.
    """
    if not crew_available:
        return False
    ev_act = p_fail * (C.COST_FAILURE_MIN - C.COST_PREEMPT_MIN)
    ev_wait = (1.0 - p_fail) * C.COST_FALSE_DISPATCH_MIN
    return ev_act > ev_wait


def tier_for(action: str) -> int:
    """Which autonomy tier does an action belong to?"""
    if action in TIER2_ACTIONS:
        return TIER_APPROVE
    return TIER_AUTO


def default_action_for(cls: int, is_critical: bool, p_fail: float) -> str:
    """Pick the Commander's action for a verdict.

    A crew is offered (tier-2 pre-dispatch) only for faults that physically
    NEED a crew: RF, Power, Backhaul. Congestion and overheat are pre-empted
    by a cheap reversible tier-1 action even on critical sites — sending a
    crew to an overheat that remote-reset can clear in the same hour just
    burns fleet time and can end as a false dispatch. Criticality scales the
    decision, never the action type.
    """
    if (cls in (C.STATUS_RF, C.STATUS_POWER, C.STATUS_BACKHAUL)
            and p_fail > C.BREAK_EVEN_PRECISION):
        return "pre_dispatch"
    return AUTO_ACTION_FOR_CLASS.get(cls, "throttle")


# ------------------------------------------------------------------ actions
def apply_tier1(engine, node, action: str) -> bool:
    """Apply a cheap, reversible mitigation. Returns True if it ran.

    All four are documented simulation effects:

      throttle     withhold THROTTLE_PCT of offered traffic for a window
      shed         throttle this node and push a little load onto neighbours
      reboot       clear soft-state faults (congestion/overheat) instantly
      switch_power force the generator on before the battery exhausts
    """
    if action == "throttle":
        node.throttle_pct = max(node.throttle_pct, C.THROTTLE_PCT)
        return True
    if action == "shed":
        node.throttle_pct = max(node.throttle_pct, C.SHED_PCT)
        nbrs = [n for n in sorted(engine.net.neighbours.get(node.node_id, ()))
                if not engine.net.by_id[n].is_faulty]
        for nid in nbrs[:2]:
            n = engine.net.by_id[nid]
            n.traffic_boost = min(0.5, n.traffic_boost + C.SHED_BOOST)
        return True
    if action == "reboot":
        _reset_soft_state(node)
        return True
    if action == "switch_power":
        if node.grid_available or node.generator_fuel_pct < 20.0:
            return False
        # force the generator on so the battery stops draining
        node.generator_fuel_pct = 100.0
        node.grid_available = False
        node.power_source = "Generator"
        return True
    return False


def _reset_soft_state(node) -> None:
    """Reboot: clear soft-state metrics toward baseline (no crew, no repair)."""
    node.cpu_load = 45.0
    node.latency = min(node.latency, 40.0)
    node.jitter = 2.5
    node.packet_loss = 0.3
    node.throughput = max(node.throughput, 150.0)
    node.temperature = min(node.temperature, 45.0)


# ------------------------------------------------------------------ bookkeeping
def mark_preempted(engine, node) -> bool:
    """Record that node's pending episode was stopped before it activated.

    The ledger transition is injected -> pre_empted: the schedule event still
    exists (I10), it just never became a real fault in this arm. Both
    counterfactual arms share the same schedule, so the denominator stays
    consistent — the existing guard test proves it.
    """
    if node.episode_id < 0:
        return False
    entry = engine.ledger.get(node.episode_id)
    if entry is None or entry.get("state") != "injected":
        return False
    entry["state"] = "pre_empted"
    entry["pre_empted_at"] = engine.tick
    node.pre_empted_episode = node.episode_id
    engine.stats["pre_empted"] += 1
    engine.stats["acted_upon"] += 1
    engine.log(f"PRE-EMPTED {node.node_id} — "
               f"{C.STATUS_NAMES.get(entry.get('kind', 0), 'fault')} "
               f"stopped before activation", "SUCCESS", node.node_id)
    return True


def reset_preempted_node(engine, node) -> None:
    """Clear the node back to a clean baseline after a successful pre-emption."""
    node.status = C.STATUS_HEALTHY
    node.status_timer = 0
    node.fault_progress = 0.0
    node.fault_severity = 1.0
    node.is_gradual = False
    node.onset_tick = -1
    node.episode_id = -1
    node.tech_dispatched = False
    node.under_repair = False
    node.assigned_team = None
    node.fault_started_tick = -1
    node.last_changed_tick = engine.tick
    _reset_soft_state(node)


# ------------------------------------------------------------------ panel
def ai_panel(engine) -> dict:
    """Live AI-performance numbers, computed from the ledger — never static.

    The §8.4 table in the project brief was illustrative; the panel must show
    what THIS run actually did.
    """
    pre_empted = sum(1 for s in engine.ledger.values()
                     if s.get("state") == "pre_empted")
    false_disp = engine.stats["false_dispatch"]
    denom = pre_empted + false_disp
    hours = 0.0
    for s in engine.ledger.values():
        if s.get("state") == "pre_empted":
            kind = s.get("kind", C.STATUS_CONGESTION)
            hours += C.REPAIR_TICKS.get(kind, 4) * C.TICK_MINUTES / 60.0
    return {
        "ai_enabled": bool(engine.ai_enabled),
        "ai_mode": engine.ai_mode,
        "ai_policy": engine.ai_policy,
        "pre_empted": pre_empted,
        "acted_upon": engine.stats["acted_upon"],
        "false_dispatches": false_disp,
        "precision": (pre_empted / denom) if denom else None,
        "break_even_precision": C.BREAK_EVEN_PRECISION,
        "crew_hours_saved": round(hours, 1),
        "unpredictable_pct": round((1.0 - C.GRADUAL_FRACTION) * 100.0, 0),
        "pending": list(engine.pending_actions),
    }
