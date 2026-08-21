"""
M7 — Counterfactual study.

Four arms on IDENTICAL exogenous schedules per seed (I10):

    A  no AI       reactive dispatch only — the status quo
    B  advisory    the Oracle suggests; a human approves crew pre-dispatches
                   after a realistic latency (6 ticks = 30 min). NO automatic
                   tier-1 actions.
    C  autonomous  the Commander acts: tier-1 mitigations applied instantly,
                   tier-2 pre-dispatches approved fast (1 tick — a
                   high-trust operator)
    D  clairvoyant perfect prediction of every GRADUAL fault, zero false
                   positives, instant approvals — the upper bound under the
                   SAME fleet, travel and repair constraints

Instant (unpredictable) faults are not pre-empted in ANY arm, including D:
a lightning strike is an exogenous shock. D therefore bounds the value of
PREDICTIVE maintenance, not omniscience — which is the honest claim, and it
is why the headline reads "X% of the improvement available to a clairvoyant
planner" rather than 100%.

Metrics per run (tower-minutes throughout):

    availability            mean % over the run
    downtime_tower_min      faulty-node-ticks x 5 min
    activated / pre_empted / masked / unresolved   from the ledger
    false_dispatches        crews sent to nodes that never failed
    crew_hours              fleet occupation (en route + repair + standby)
    mttr_min                mean time to repair
    cost_tower_min          flat cost model: 90 per activated episode,
                            45 per pre-emption, 35 per false dispatch

The headline comparison (autonomous vs clairvoyant) uses downtime saved,
the physical outcome, not the flat cost model.

Usage:
    python -m autonoc.scripts.counterfactual --seeds 30 --days 10 --workers 8
    python -m autonoc.scripts.counterfactual --quick      # 3 seeds, 2 days

Writes reports/counterfactual.csv and reports/counterfactual_summary.json
and prints the mean +/- 95% CI table.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import pathlib
import statistics

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine
from autonoc.engine.geo import haversine_km

ARMS = ("A", "B", "C", "D")

REPORTS = pathlib.Path("reports")

# Approve latency per arm, in ticks (1 tick = 5 sim minutes).
#   B: 10 min  — an operator reviewing suggestions
#   C:  5 min  — high-trust operator rubber-stamping the Commander
#   D:  0      — a perfect planner needs no approval delay
APPROVE_LATENCY = {"A": None, "B": 2, "C": 1, "D": 0}

# Student-t 97.5th percentile for a few degrees of freedom (95% CI).
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
        7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131,
        20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}

_DAYS = 10
_BUNDLE = None            # ModelBundle, loaded once per worker


def _t95(n: int) -> float:
    df = n - 1
    if df <= 0:
        return 0.0
    for k in sorted(_T95):
        if df <= k:
            return _T95[k]
    return 1.96


# ------------------------------------------------------------------ arms
def run_arm(seed: int, arm: str, days: int, bundle=None) -> dict:
    """Run one arm for one seed. Deterministic: same (seed, arm) -> same dict.

    `bundle` is the shared ModelBundle for arms B/C. If None, the rule-based
    fallback verdicts are used (model-free, for tests and --rules mode).
    Arm D needs no bundle: it reads the engine's own pending schedule.
    """
    horizon = days * C.TICKS_PER_DAY + C.TICKS_PER_DAY
    e = NOCEngine(seed=seed, ai_enabled=(arm != "A"), horizon=horizon)
    if arm == "B":
        e.ai_policy = "advisory"

    ticks = days * C.TICKS_PER_DAY
    down_ticks = 0
    crew_ticks = 0

    for tick in range(1, ticks + 1):
        e.step()

        down_ticks += sum(1 for n in e.nodes if n.status != C.STATUS_HEALTHY)
        crew_ticks += sum(1 for t in e.teams
                          if t.state in ("EN_ROUTE", "REPAIRING", "STANDBY"))

        # ---- verdicts (set after the step, consumed by the next step's hook)
        if arm in ("B", "C"):
            if tick % C.AI_INFERENCE_EVERY_TICKS == 0:
                if bundle is not None:
                    from autonoc.ai.serve import score_engine
                    e.ai_verdicts = score_engine(e, bundle)
                else:
                    from autonoc.ai.serve import rules_verdicts
                    e.ai_verdicts = rules_verdicts(e)
        elif arm == "D":
            # Clairvoyant: perfect knowledge of every pending gradual fault,
            # acted on optimally:
            #   - tier-1 classes (congestion/overheat): pre-empt the moment
            #     the episode is known — the action is free and reversible,
            #     so there is no reason to wait.
            #   - crew classes (RF/power): dispatch so the crew is ON SITE at
            #     activation — send it just early enough to cover travel from
            #     the depot (worst case). Never park a crew for hours, which
            #     would saturate the fleet and is not what a perfect planner
            #     would do.
            # D is the upper bound on PREDICTION, not on foresight.
            v: dict[str, dict] = {}
            for ev, node, _start in list(e.pending):
                if node.pre_empted_episode == ev.episode_id:
                    continue
                remaining = ev.tick + ev.onset_offset - e.tick
                if remaining <= 0:
                    continue
                if ev.kind in (C.STATUS_CONGESTION, C.STATUS_OVERHEAT):
                    v[node.node_id] = {"p_fail": 1.0, "cls": ev.kind,
                                       "action": None}
                else:
                    d_km = haversine_km(C.DEPOT_LAT, C.DEPOT_LON,
                                        node.lat, node.lon)
                    travel = max(1, math.ceil(d_km * 1000.0 / C.TEAM_STEP_M))
                    if remaining <= travel + 2:
                        v[node.node_id] = {"p_fail": 1.0, "cls": ev.kind,
                                           "action": None}
            e.ai_verdicts = v

        # ---- approvals
        if arm in ("B", "C", "D"):
            lat = APPROVE_LATENCY[arm]
            for a in [a for a in e.pending_actions if a["state"] == "pending"]:
                if tick - a["created_tick"] >= lat:
                    e.approve_action(a["action_id"])

    # ---- metrics
    k = e.kpis()
    states = [s.get("state") for s in e.ledger.values()]
    activated = states.count("resolved") + states.count("injected")
    pre_empted = states.count("pre_empted")
    masked = states.count("masked")
    unresolved = states.count("injected")
    false = e.stats["false_dispatch"]
    cost = (activated * C.COST_FAILURE_MIN
            + pre_empted * C.COST_PREEMPT_MIN
            + false * C.COST_FALSE_DISPATCH_MIN)
    return {
        "seed": seed, "arm": arm,
        "availability": round(100.0 * (1.0 - down_ticks / (len(e.nodes) * ticks)), 3),
        "downtime_tower_min": round(down_ticks * C.TICK_MINUTES, 1),
        "episodes": len(e.ledger),
        "activated": activated,
        "pre_empted": pre_empted,
        "masked": masked,
        "unresolved": unresolved,
        "false_dispatches": false,
        "crew_hours": round(crew_ticks / C.TICKS_PER_HOUR, 1),
        "repairs": e.stats["repairs"],
        "mttr_min": k["mttr_min"],
        "cost_tower_min": round(cost, 1),
    }


# ------------------------------------------------------------------ parallel
def _init_worker(days: int, use_models: bool) -> None:
    global _DAYS, _BUNDLE
    _DAYS = days
    _BUNDLE = None
    if use_models:
        from autonoc.ai.serve import ModelBundle
        _BUNDLE = ModelBundle()


def _work(params) -> dict:
    seed, arm = params
    return run_arm(seed, arm, _DAYS, _BUNDLE)


def run_study(seeds, days: int, workers: int = 1, use_models: bool = True):
    """Run every (seed, arm) combination. Returns a list of result dicts."""
    tasks = [(s, a) for s in seeds for a in ARMS]
    if workers <= 1:
        bundle = None
        if use_models:
            from autonoc.ai.serve import ModelBundle
            bundle = ModelBundle()
        return [run_arm(s, a, days, bundle) for (s, a) in tasks]
    with mp.Pool(workers, initializer=_init_worker,
                 initargs=(days, use_models)) as pool:
        return pool.map(_work, tasks, chunksize=1)


# ------------------------------------------------------------------ summary
_METRIC_KEYS = ("availability", "downtime_tower_min", "episodes", "activated",
                "pre_empted", "masked", "unresolved", "false_dispatches",
                "crew_hours", "repairs", "mttr_min", "cost_tower_min")


def summarize(results, days: int, seeds) -> dict:
    out: dict = {"meta": {"days": days, "seeds": sorted(seeds),
                          "n_seeds": len(seeds)}, "arms": {}, "headline": {}}
    for arm in ARMS:
        rows = [r for r in results if r["arm"] == arm]
        n = len(rows)
        summary = {}
        for key in _METRIC_KEYS:
            vals = [r[key] for r in rows]
            mean = statistics.mean(vals)
            sd = statistics.stdev(vals) if n > 1 else 0.0
            ci = _t95(n) * sd / math.sqrt(n) if n > 1 else 0.0
            summary[key] = {"mean": round(float(mean), 2),
                            "ci95": round(float(ci), 2)}
        out["arms"][arm] = summary

    def m(arm, key):
        return out["arms"][arm][key]["mean"]

    cost_a, down_a = m("A", "cost_tower_min"), m("A", "downtime_tower_min")
    saved = {}
    for arm in ("B", "C", "D"):
        saved[arm] = {
            "cost_saved_tower_min": round(cost_a - m(arm, "cost_tower_min"), 1),
            "downtime_saved_tower_min": round(down_a - m(arm, "downtime_tower_min"), 1),
        }
    down_d = saved["D"]["downtime_saved_tower_min"]
    down_c = saved["C"]["downtime_saved_tower_min"]
    out["headline"] = {
        "saved_vs_A": saved,
        "pct_of_clairvoyant_downtime_reduction": (
            round(down_c / down_d * 100.0, 1)
            if down_d > 0 and down_c > 0 else None),
        "autonomous_worse_than_no_ai": down_c <= 0,
    }
    return out


def print_table(results, days: int, seeds) -> None:
    s = summarize(results, days, seeds)
    print("\n" + "=" * 92)
    print(f"  M7 COUNTERFACTUAL STUDY — {s['meta']['n_seeds']} seeds x "
          f"{days} days ({days * C.TICKS_PER_DAY} ticks per run)")
    print("  mean +/- 95% CI")
    print("=" * 92)
    hdr = (f"  {'arm':<4} {'availability':>12} {'downtime min':>14} "
           f"{'activated':>10} {'pre-empted':>10} {'false':>7} "
           f"{'crew-h':>8} {'mttr min':>9} {'cost':>12}")
    print(hdr)
    print("  " + "-" * 90)
    for arm in ARMS:
        a = s["arms"][arm]
        print(f"  {arm:<4} "
              f"{a['availability']['mean']:>7.2f} +/-{a['availability']['ci95']:<5.2f} "
              f"{a['downtime_tower_min']['mean']:>9,.0f} +/-{a['downtime_tower_min']['ci95']:<6,.0f} "
              f"{a['activated']['mean']:>10,.0f} "
              f"{a['pre_empted']['mean']:>10,.0f} "
              f"{a['false_dispatches']['mean']:>7,.1f} "
              f"{a['crew_hours']['mean']:>8,.1f} "
              f"{a['mttr_min']['mean']:>9,.0f} "
              f"{a['cost_tower_min']['mean']:>10,.0f}")
    print("  " + "-" * 90)
    h = s["headline"]
    for arm in ("B", "C", "D"):
        sv = h["saved_vs_A"][arm]
        print(f"  {arm} vs A:  cost saved {sv['cost_saved_tower_min']:>10,.0f} "
              f"tower-min | downtime saved {sv['downtime_saved_tower_min']:>10,.0f} "
              f"tower-min")
    pct = h["pct_of_clairvoyant_downtime_reduction"]
    if pct is not None:
        print(f"\n  AUTONOMOUS (C) achieved {pct}% of the clairvoyant (D) "
              f"downtime reduction under identical fleet constraints.")
    elif h.get("autonomous_worse_than_no_ai"):
        print("\n  AUTONOMOUS (C) was WORSE than no-AI with this predictor — "
              "its false-alarm cost exceeded its benefit.")
        print("  This is expected with the rule-based fallback (B1 baseline: "
              "precision ~0.04). Run with the trained models for the real study.")
    else:
        print("\n  (clairvoyant arm reduced zero downtime — nothing to compare)")
    print("=" * 92)


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description="M7 counterfactual study")
    ap.add_argument("--seeds", type=int, default=30, help="number of seeds")
    ap.add_argument("--days", type=int, default=10, help="sim days per run")
    ap.add_argument("--workers", type=int, default=1, help="parallel workers")
    ap.add_argument("--quick", action="store_true",
                    help="3 seeds, 2 days, 1 worker (sanity)")
    ap.add_argument("--rules", action="store_true",
                    help="use rule verdicts instead of the trained models")
    args = ap.parse_args()

    if args.quick:
        seeds, days, workers = list(range(1, 4)), 2, 1
    else:
        seeds = list(range(1, args.seeds + 1))
        days, workers = args.days, args.workers
    use_models = not args.rules

    print(f"M7 counterfactual study — {len(seeds)} seeds x {days} days "
          f"x {len(ARMS)} arms, {workers} worker(s), "
          f"models={'on' if use_models else 'off (rules)'}")

    t0 = __import__("time").perf_counter()
    results = run_study(seeds, days, workers, use_models)
    elapsed = __import__("time").perf_counter() - t0
    print(f"  ran {len(results)} runs in {elapsed:.1f} s")

    REPORTS.mkdir(exist_ok=True)
    csv_path = REPORTS / "counterfactual.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        w.writeheader()
        for r in results:
            w.writerow(r)

    summary = summarize(results, days, seeds)
    json_path = REPORTS / "counterfactual_summary.json"
    json_path.write_text(json.dumps(summary, indent=2))

    print_table(results, days, seeds)
    print(f"\n  wrote {csv_path}")
    print(f"  wrote {json_path}")


if __name__ == "__main__":
    main()
