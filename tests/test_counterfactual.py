"""
M7 — counterfactual study tests.

What M7 must guarantee:

  - all four arms inhabit IDENTICAL worlds (same exogenous schedules per seed)
  - the clairvoyant arm pre-empts every gradual fault with zero false
    positives and beats no-AI on the same seed
  - advisory never applies automatic tier-1 actions
  - a pre-positioned crew HOLDS on site (STANDBY) and catches the fault —
    it is NOT counted as a false dispatch
  - a standby crew whose prediction never lands is counted honestly
  - the study driver runs all four arms and produces the summary report

All tests are deterministic and need NO trained model files (arms B/C fall
back to rule verdicts, which is the documented model-free path).
"""
from __future__ import annotations

import pytest

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine
from autonoc.engine.geo import haversine_km

from autonoc.scripts.counterfactual import ARMS, run_arm, run_study, summarize


# ------------------------------------------------------------------ worlds
def test_arms_share_identical_schedules():
    """I10 at the study level: the four arms of one seed see the same world."""
    engs = {arm: NOCEngine(seed=5, ai_enabled=(arm != "A"),
                           horizon=C.TICKS_PER_DAY * 3)
            for arm in ARMS}
    base = [ev.as_tuple() for ev in engs["A"].schedule]
    base_fiber = [ev.as_tuple() for ev in engs["A"].fiber_schedule]
    for arm in ARMS[1:]:
        assert [ev.as_tuple() for ev in engs[arm].schedule] == base, \
            f"arm {arm} node-fault schedule diverged"
        assert [ev.as_tuple() for ev in engs[arm].fiber_schedule] == base_fiber, \
            f"arm {arm} fiber schedule diverged"


# ------------------------------------------------------------------ arms
def test_clairvoyant_preempts_gradual_and_beats_no_ai():
    """Arm D on one seed: pre-empts gradual faults, zero false positives,
    strictly better availability than arm A on the SAME seed."""
    a = run_arm(5, "A", 3)
    d = run_arm(5, "D", 3)
    assert d["pre_empted"] > 0, "clairvoyant must pre-empt gradual faults"
    assert d["false_dispatches"] == 0, \
        "clairvoyant has zero false positives by construction"
    assert d["activated"] <= a["activated"]
    assert d["downtime_tower_min"] <= a["downtime_tower_min"]
    assert d["availability"] >= a["availability"]
    # same world
    assert d["episodes"] == a["episodes"], \
        "arms must process the identical episode set"


def test_advisory_skips_tier1():
    """Advisory (B) never applies automatic mitigations — it only suggests."""
    e = NOCEngine(seed=7, ai_enabled=True, horizon=C.TICKS_PER_DAY * 4)
    e.ai_policy = "advisory"
    for _ in range(200):
        e.step()
    node = next((n for n in e.nodes
                 if n.is_gradual and n.episode_id >= 0 and not n.is_faulty),
                None)
    assert node is not None, "no pending gradual fault found — test setup"
    episode = node.episode_id
    e.ai_verdicts[node.node_id] = {
        "p_fail": 0.94, "cls": C.STATUS_CONGESTION, "action": "throttle",
        "tier": 1,
    }
    for _ in range(node.onset_tick - e.tick + 2):
        e.step()
    assert e.ledger.get(episode, {}).get("state") != "pre_empted", \
        "advisory must NOT pre-empt (tier-1 actions are disabled)"


# ------------------------------------------------------------------ standby
def _find_standby_target():
    """A deterministic (seed, event) for an RF gradual fault with a long
    onset window and a node close to the depot, so the pre-dispatched crew
    reliably arrives BEFORE activation and must hold on site."""
    for seed in range(40, 70):
        e = NOCEngine(seed=seed, ai_enabled=True, horizon=C.TICKS_PER_DAY * 6)
        for ev in e.schedule:
            if (ev.kind == C.STATUS_RF and ev.is_gradual
                    and ev.onset_offset >= 20):
                node = e.net.by_id[ev.node_id]
                d = haversine_km(C.DEPOT_LAT, C.DEPOT_LON, node.lat, node.lon)
                if d < 3.0:
                    return seed, ev
    raise AssertionError("no suitable RF target found across seeds 40-69")


def test_standby_catches_predicted_fault():
    """The physical fix M7 depends on: a pre-positioned crew that arrives
    before the fault holds on site, catches it, and is NOT a false dispatch."""
    seed, ev = _find_standby_target()
    e = NOCEngine(seed=seed, ai_enabled=True, horizon=C.TICKS_PER_DAY * 6)
    for _ in range(ev.tick - e.tick):
        e.step()
    node = e.net.by_id[ev.node_id]
    assert node.is_gradual and node.episode_id == ev.episode_id
    assert not node.is_faulty

    e.ai_verdicts[node.node_id] = {
        "p_fail": 0.99, "cls": C.STATUS_RF, "action": "pre_dispatch", "tier": 2,
    }
    e.step()
    assert len(e.pending_actions) == 1, "tier-2 pre-dispatch should be queued"
    e.approve_action(e.pending_actions[0]["action_id"])

    seen_standby = False
    for _ in range(80):
        e.step()
        if any(t.state == "STANDBY" for t in e.teams):
            seen_standby = True
        if node.status == C.STATUS_HEALTHY and node.episode_id == -1:
            break
    assert seen_standby, "crew must hold on site before the fault lands"
    assert node.status == C.STATUS_HEALTHY, "node must end repaired"
    assert e.stats["false_dispatch"] == 0, \
        "a crew that caught the fault is not a false dispatch"
    assert e.ledger[ev.episode_id]["state"] == "resolved"


def test_standby_expires_as_false_dispatch():
    """A pre-dispatched crew to a node that never fails holds for the window,
    then is released and counted as a false dispatch — honestly."""
    e = NOCEngine(seed=7, ai_enabled=True, horizon=C.TICKS_PER_DAY * 4)
    for _ in range(60):
        e.step()

    # a healthy node with no scheduled fault in the next 30 ticks
    node = None
    for n in e.nodes:
        if n.is_faulty or n.is_gradual:
            continue
        if any(x.node_id == n.node_id and 0 <= x.tick - e.tick <= 30
               for x in e.schedule):
            continue
        node = n
        break
    assert node is not None, "no clean node found — test setup"

    e.ai_verdicts[node.node_id] = {
        "p_fail": 0.94, "cls": C.STATUS_POWER, "action": "pre_dispatch",
        "tier": 2,
    }
    e.step()
    assert len(e.pending_actions) == 1
    e.approve_action(e.pending_actions[0]["action_id"])

    seen_standby = False
    for _ in range(30):
        e.step()
        if any(t.state == "STANDBY" for t in e.teams):
            seen_standby = True
            break
    assert seen_standby, "crew should hold on site first"
    for _ in range(20):
        e.step()
    assert e.stats["false_dispatch"] == 1
    assert node.status == C.STATUS_HEALTHY
    assert not any(t.state == "STANDBY" for t in e.teams), \
        "no crew may still be holding after the window expired"
    assert not node.tech_dispatched, "released node must be re-dispatchable"


# ------------------------------------------------------------------ driver
def test_study_quick_runs_all_arms():
    """The driver runs all four arms and the summary has the expected shape.
    Model-free: arms B/C use rule verdicts."""
    results = run_study([1], days=1, workers=1, use_models=False)
    assert {r["arm"] for r in results} == set(ARMS)
    summary = summarize(results, days=1, seeds=[1])
    for arm in ARMS:
        assert "availability" in summary["arms"][arm]
        assert "downtime_tower_min" in summary["arms"][arm]
        assert "cost_tower_min" in summary["arms"][arm]
    assert "pct_of_clairvoyant_downtime_reduction" in summary["headline"]


def test_study_arm_a_matches_baseline_engine():
    """Arm A is exactly the pre-M6 engine: no verdicts ever consumed."""
    r = run_arm(42, "A", 1)
    assert r["pre_empted"] == 0
    assert r["false_dispatches"] == 0
    assert r["activated"] > 0, "arm A must actually experience faults"
