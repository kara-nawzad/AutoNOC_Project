"""
M6 — Commander tests.

The acceptance criteria from the brief, each pinned to a test:

  - the decision rule is DERIVED from the cost model, never hard-coded
  - tier-1 actions are cheap, reversible, applied automatically
  - tier-2 actions surface an approve/veto control
  - pre-emption is recorded per-episode and keeps the schedule denominator
    consistent across counterfactual arms
  - false dispatches are counted honestly
  - the AI panel computes live numbers, including precision vs break-even
  - missing model files degrade to rules mode without crashing
"""
from __future__ import annotations

import pathlib
import threading

import pytest

from autonoc.engine import config as C
from autonoc.engine import commander as CM
from autonoc.engine.engine import NOCEngine


# ------------------------------------------------------------------ rule
def test_decision_rule_reduces_exactly_to_break_even():
    """Act iff expected saving exceeds expected waste.

    ev_act  = p * (COST_FAILURE - COST_PREEMPT)
    ev_wait = (1 - p) * COST_FALSE_DISPATCH
    acting is right exactly when p > BREAK_EVEN_PRECISION — and that number
    is derived from the costs, not hard-coded anywhere.
    """
    derived = (C.COST_FALSE_DISPATCH_MIN
               / ((C.COST_FAILURE_MIN - C.COST_PREEMPT_MIN)
                  + C.COST_FALSE_DISPATCH_MIN))
    assert abs(derived - C.BREAK_EVEN_PRECISION) < 1e-9
    for p in (0.0, 0.1, 0.3, 0.4374, 0.4375):
        assert not CM.decision(p), f"should NOT act at p={p}"
    for p in (0.4376, 0.5, 0.7, 0.94, 1.0):
        assert CM.decision(p), f"should act at p={p}"


def test_decision_respects_crew_availability():
    """No crew, no action — even at p=1.0."""
    assert not CM.decision(1.0, crew_available=False)
    assert CM.decision(1.0, crew_available=True)


def test_tier_classification():
    """Crew-consuming actions need approval; cheap ones do not."""
    assert CM.tier_for("pre_dispatch") == CM.TIER_APPROVE
    for action in ("throttle", "shed", "reboot", "switch_power"):
        assert CM.tier_for(action) == CM.TIER_AUTO


def test_default_action_matches_fault_class():
    """Doctor class drives the mitigation; crew-worthy classes pre-dispatch."""
    assert CM.default_action_for(C.STATUS_CONGESTION, False, 0.9) == "throttle"
    assert CM.default_action_for(C.STATUS_OVERHEAT, False, 0.9) == "throttle"
    assert CM.default_action_for(C.STATUS_RF, False, 0.9) == "pre_dispatch"
    assert CM.default_action_for(C.STATUS_POWER, False, 0.9) == "pre_dispatch"
    # criticality never changes the action type: a critical overheat is still
    # pre-empted by the cheap tier-1 action, not by burning a crew
    assert CM.default_action_for(C.STATUS_CONGESTION, True, 0.9) == "throttle"
    assert CM.default_action_for(C.STATUS_OVERHEAT, True, 0.9) == "throttle"
    assert CM.default_action_for(C.STATUS_RF, True, 0.9) == "pre_dispatch"
    # below break-even, even a crew-worthy node gets the cheap tier-1 hedge
    assert CM.default_action_for(C.STATUS_RF, True, 0.1) == "reboot"


# ------------------------------------------------------------------ pre-emption
def _find_pending_node(e: NOCEngine, soft: bool = True):
    """A node partway through a gradual fault that has not activated yet.

    With `soft=True` (default) the fault must be congestion/overheat — the
    class a tier-1 action is allowed to pre-empt. The other tests cover
    crew-worthy faults explicitly.
    """
    for n in e.nodes:
        if n.is_gradual and n.episode_id >= 0 and not n.is_faulty \
                and n.onset_tick > e.tick:
            if soft:
                kind = e.ledger.get(n.episode_id, {}).get("kind")
                if kind not in (C.STATUS_CONGESTION, C.STATUS_OVERHEAT):
                    continue
            return n
    return None


def test_tier1_never_preempts_crew_worthy_fault():
    """Physical guard (M7): a cheap tier-1 action cannot cancel an RF/power
    fault. If the Doctor misclassifies a crew-worthy pending fault as
    congestion, throttling must NOT pre-empt it — the fault activates and
    needs a real crew. Without this, misclassification would make the
    autonomous arm superhuman."""
    e = NOCEngine(seed=42, ai_enabled=True, horizon=C.TICKS_PER_DAY * 8)
    for _ in range(300):
        e.step()
    # a pending crew-worthy (RF) fault, with the Doctor WRONGLY saying
    # congestion so the Commander would throttle it
    node = next((n for n in e.nodes
                 if n.is_gradual and n.episode_id >= 0 and not n.is_faulty
                 and e.ledger.get(n.episode_id, {}).get("kind") == C.STATUS_RF),
                None)
    if node is None:
        pytest.skip("no pending RF fault in window — test setup")
    episode = node.episode_id
    e.ai_verdicts[node.node_id] = {
        "p_fail": 0.94, "cls": C.STATUS_CONGESTION,  # deliberate misclassification
        "action": "throttle", "tier": 1,
    }
    for _ in range(node.onset_tick - e.tick + 2):
        e.step()
    assert e.ledger.get(episode, {}).get("state") != "pre_empted", \
        "tier-1 must never pre-empt a crew-worthy fault"


def test_tier1_action_preempts_scheduled_fault():
    """The core M6 claim: act on the Oracle's probability and the scheduled
    fault never materialises. Ledger records injected -> pre_empted."""
    e = NOCEngine(seed=42, ai_enabled=True, horizon=C.TICKS_PER_DAY * 8)
    for _ in range(300):
        e.step()

    node = _find_pending_node(e, soft=True)
    assert node is not None, "no pending soft fault found — test setup"
    activation = node.onset_tick
    episode = node.episode_id
    assert e.ledger[episode]["state"] == "injected"
    assert e.ledger[episode]["kind"] in (C.STATUS_CONGESTION, C.STATUS_OVERHEAT)

    # the Oracle says this node fails within 60 min; the Commander throttles
    e.ai_verdicts[node.node_id] = {
        "p_fail": 0.94, "cls": C.STATUS_CONGESTION, "action": "throttle",
        "tier": 1,
    }

    for _ in range(activation - e.tick + 2):
        e.step()

    assert node.status == C.STATUS_HEALTHY, "pre-empted node must stay healthy"
    assert node.pre_empted_episode == episode
    assert e.ledger[episode]["state"] == "pre_empted"
    assert e.stats["pre_empted"] == 1
    assert e.stats["acted_upon"] == 1
    assert e.ai_payload()["pre_empted"] == 1


def test_ledger_denominator_consistent_across_arms_with_ai():
    """Arm A (no AI) and Arm C (AI) see the SAME schedule and record the SAME
    number of episodes — only the outcome differs (resolved vs pre_empted).
    This is the guarantee the M7 counterfactual study rests on."""
    a = NOCEngine(seed=1234, ai_enabled=False, horizon=C.TICKS_PER_DAY * 6)
    c = NOCEngine(seed=1234, ai_enabled=True, horizon=C.TICKS_PER_DAY * 6)

    for _ in range(200):
        a.step()
        c.step()

    # identical schedules (I10 guard, re-checked here at the ledger level)
    assert [ev.as_tuple() for ev in a.schedule] == \
        [ev.as_tuple() for ev in c.schedule]

    # pre-empt every pending gradual fault in arm C for 400 ticks
    for _ in range(400):
        c.step()
        node = _find_pending_node(c)
        if node is not None:
            c.ai_verdicts[node.node_id] = {
                "p_fail": 0.94, "cls": C.STATUS_CONGESTION,
                "action": "throttle", "tier": 1,
            }
        a.step()

    # both arms processed EXACTLY the same episode set. An episode can be
    # masked in one arm and pre-empted in the other (pre-emption changes the
    # node's eligibility for later events) — that is the intervention working.
    # What must never happen is an episode existing in one ledger and not the
    # other: the recall denominator would drift and the comparison break.
    assert set(a.ledger) == set(c.ledger), (
        "episode sets diverged between arms: "
        f"{len(set(a.ledger) - set(c.ledger))} only in A, "
        f"{len(set(c.ledger) - set(a.ledger))} only in C")
    pre_episodes = {ep for ep, s in c.ledger.items()
                    if s.get("state") == "pre_empted"}
    assert pre_episodes, "AI arm pre-empted nothing — test is not exercising M6"
    for ep in pre_episodes:
        assert a.ledger[ep]["state"] != "pre_empted", \
            "arm A must never pre-empt (AI is off there)"


# ------------------------------------------------------------------ tier 2
def _node_with_no_scheduled_fault(e: NOCEngine, horizon_ticks: int = 60):
    for n in e.nodes:
        if n.is_faulty or n.is_gradual:
            continue
        if any(ev.node_id == n.node_id
               and 0 <= ev.tick - e.tick <= horizon_ticks
               for ev in e.schedule):
            continue
        return n
    return None


def test_approved_predispatch_counts_false_dispatch_when_healthy():
    """A crew pre-dispatched to a node that never fails is a FALSE DISPATCH,
    counted honestly in the panel."""
    e = NOCEngine(seed=7, ai_enabled=True, horizon=C.TICKS_PER_DAY * 6)
    for _ in range(120):
        e.step()

    node = _node_with_no_scheduled_fault(e)
    assert node is not None, "no clean node found — test setup"
    e.ai_verdicts[node.node_id] = {
        "p_fail": 0.94, "cls": C.STATUS_POWER, "action": "pre_dispatch",
        "tier": 2,
    }
    e.step()
    assert len(e.pending_actions) == 1, "tier-2 action should await approval"

    r = e.approve_action(e.pending_actions[0]["action_id"])
    assert r["ok"] and not r.get("late", False)
    assert e.stats["acted_upon"] == 1

    # crew travels (~10 ticks), finds a healthy node, comes home
    for _ in range(60):
        e.step()
    assert e.stats["false_dispatch"] == 1
    assert node.status == C.STATUS_HEALTHY
    assert e.ai_payload()["false_dispatches"] == 1


def test_veto_discards_tier2_action():
    """A vetoed action dispatches nothing and costs nothing."""
    e = NOCEngine(seed=11, ai_enabled=True, horizon=C.TICKS_PER_DAY * 6)
    for _ in range(120):
        e.step()
    node = _node_with_no_scheduled_fault(e)
    assert node is not None
    e.ai_verdicts[node.node_id] = {
        "p_fail": 0.94, "cls": C.STATUS_RF, "action": "pre_dispatch", "tier": 2,
    }
    e.step()
    assert len(e.pending_actions) == 1
    missions_before = sum(t.dispatch_count for t in e.teams)
    r = e.veto_action(e.pending_actions[0]["action_id"])
    assert r["ok"]
    assert e.pending_actions == []
    assert sum(t.dispatch_count for t in e.teams) == missions_before
    assert e.stats["acted_upon"] == 0
    assert not node.tech_dispatched


def test_ai_panel_precision_vs_break_even():
    """Precision is computed live as pre-empted / (pre-empted + false), and
    compared against the cost-derived break-even."""
    e = NOCEngine(seed=3, ai_enabled=True, horizon=C.TICKS_PER_DAY * 6)
    for _ in range(200):
        e.step()
    node = _find_pending_node(e)
    assert node is not None
    e.ai_verdicts[node.node_id] = {
        "p_fail": 0.94, "cls": C.STATUS_CONGESTION, "action": "throttle", "tier": 1,
    }
    for _ in range(20):
        e.step()

    p = e.ai_payload()
    assert p["pre_empted"] == 1
    assert p["false_dispatches"] == 0
    assert p["precision"] == 1.0
    assert abs(p["break_even_precision"] - C.BREAK_EVEN_PRECISION) < 1e-9
    assert p["crew_hours_saved"] > 0.0
    assert p["unpredictable_pct"] == 25.0
    assert p["ai_enabled"] is True


# ------------------------------------------------------------------ serving
def test_rules_verdicts_need_no_models():
    """The fallback path produces verdicts with no model files at all."""
    from autonoc.ai import serve
    e = NOCEngine(seed=5)
    for _ in range(300):
        e.step()
    v = serve.rules_verdicts(e)
    assert isinstance(v, dict)
    for entry in v.values():
        assert entry["p_fail"] > C.BREAK_EVEN_PRECISION
        assert entry["tier"] in (CM.TIER_AUTO, CM.TIER_APPROVE)


def test_missing_models_degrade_to_rules(tmp_path, monkeypatch):
    """ModelBundle with an empty models dir must not raise; mode = rules."""
    from autonoc.ai import serve
    monkeypatch.setattr(serve, "MODEL_DIR", pathlib.Path(tmp_path))
    b = serve.ModelBundle()
    assert b.complete is False
    assert b.mode == "rules"


def test_worker_scores_batch_with_real_models():
    """End-to-end: the inference worker produces ~300 verdicts with real
    trained artifacts loaded, on healthy nodes only."""
    e = NOCEngine(seed=2, ai_enabled=True, horizon=C.TICKS_PER_DAY * 4)
    for _ in range(60):                # fill hist_fine windows
        e.step()
    from autonoc.ai.serve import InferenceWorker
    w = InferenceWorker(e, threading.Lock())
    try:
        assert w.bundle.complete, "trained artifacts should load in CI"
        verdicts = w._score_batch()
        assert len(verdicts) <= len(e.nodes)
        for v in verdicts.values():
            assert 0.0 <= v["p_fail"] <= 1.0
            assert v["cls"] in C.STATUS_NAMES
    finally:
        w.stop()


def test_step_stays_in_budget_with_verdicts():
    """I4 extension: a full verdict map must not blow the tick budget."""
    from autonoc.engine.engine import NOCEngine
    e = NOCEngine(seed=1, ai_enabled=True)
    for _ in range(50):
        e.step()
    e.ai_verdicts = {n.node_id: {"p_fail": 0.94, "cls": C.STATUS_CONGESTION,
                                 "action": "throttle", "tier": 1}
                     for n in e.nodes}
    t0 = __import__("time").perf_counter()
    for _ in range(120):
        e.step()
    avg_ms = (__import__("time").perf_counter() - t0) / 120 * 1000
    assert avg_ms < 100.0, f"step() {avg_ms:.2f} ms with verdicts — too slow"
