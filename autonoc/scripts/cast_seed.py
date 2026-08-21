"""
M8 — seed casting for the "Storm over Goizha" demo.

Search a range of seeds for one whose EMERGENT world contains the beats of
the 5-minute demo — nothing scripted. Every beat comes from the exogenous
schedules (I10):

  Act 0  a calm opening — few faults in the first hours
  Act 1  a Salim Street node degrades gradually; the Oracle flags it early
  Act 2  the Commander pre-dispatches; a crew is on site before failure
  Act 3  a storm rages over Goizha and a fiber cut darkens a ring
         (click CUT FIBER during the storm for the double-cut isolation
         spectacle — a natural double cut is ~2x/year, far too rare to
         wait for on camera)
  Act 4  an instant fault strikes during the storm — no warning, by design
  Act 5  the counterfactual table for the same seed (M7)

Scoring never steps the engine: the fault schedule, fiber schedule and
weather timeline are all decided at init, so a seed's whole demo potential
is visible the instant the engine is constructed.

Wall-clock mapping: the live server runs BASE_TICK_SECONDS = 1.0, so at 1x
speed one tick is about one second of demo time. The demo's 0:45 / 1:30 /
2:30 / 3:45 / 4:30 beats fall at roughly ticks 45 / 90 / 150 / 225 / 270.

Usage:
    python -m autonoc.scripts.cast_seed --seeds 5000 --workers 8
    python -m autonoc.scripts.cast_seed --report 1234
    python -m autonoc.scripts.cast_seed --verify 1234   # needs trained models
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import pathlib

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine

REPORTS = pathlib.Path("reports")

# Scoring windows in ticks (1 tick = 5 sim minutes, ~1 s demo time at 1x).
W_ACT1 = (20, 100)      # Salim Street degradation (Oracle flags it)
W_ACT3 = (120, 210)     # storm + fiber cut over Goizha
W_ACT4 = (200, 260)     # instant strike during the storm
CALM_TICKS = 36         # Act 0: first 3 simulated hours
CALM_MAX_FAULTS = 25    # ~15 expected; 25 keeps the opening visibly calm

# How many simulated days of horizon we need to score. The demo beats all
# fall inside the first ~1.1 days, so a short horizon keeps casting fast.
DEMO_DAYS = 2


# ------------------------------------------------------------------ profile
def _sim_time(tick: int) -> str:
    tod = tick % C.TICKS_PER_DAY
    day = tick // C.TICKS_PER_DAY + 1
    return f"D{day} {tod * 5 // 60:02d}:{tod * 5 % 60:02d}"


def storm_periods(engine, site: int = 0, ticks: int | None = None):
    """Contiguous [start, end] tick runs where the site sees a storm."""
    if ticks is None:
        ticks = DEMO_DAYS * C.TICKS_PER_DAY
    periods = []
    cur = None
    for t in range(1, ticks + 1):
        if engine.weather_timeline[t][site]["type"] == "Storm":
            if cur is None:
                cur = [t, t]
            else:
                cur[1] = t
        elif cur is not None:
            periods.append((cur[0], cur[1]))
            cur = None
    if cur is not None:
        periods.append((cur[0], cur[1]))
    return periods


def profile(seed: int, days: int = DEMO_DAYS) -> dict:
    """Inspect one seed's exogenous world. No engine stepping."""
    horizon = days * C.TICKS_PER_DAY + C.TICKS_PER_DAY
    e = NOCEngine(seed=seed, horizon=horizon)
    ticks = days * C.TICKS_PER_DAY

    goizha_storms = [t for t in range(1, ticks + 1)
                     if e.weather_timeline[t][0]["type"] == "Storm"]
    storm_set = set(goizha_storms)
    storm_w2 = [t for t in goizha_storms if W_ACT3[0] <= t <= W_ACT3[1]]

    cuts = [ev for ev in e.fiber_schedule if ev.tick <= ticks]
    storm_cuts = [ev for ev in cuts if ev.cause == "storm"]
    cuts_w2 = [ev for ev in cuts if W_ACT3[0] <= ev.tick <= W_ACT3[1]]
    storm_cuts_w2 = [ev for ev in storm_cuts if W_ACT3[0] <= ev.tick <= W_ACT3[1]]

    salim = []
    for ev in e.schedule:
        if ev.tick > ticks:
            break                     # schedule is emitted in tick order
        node = e.net.by_id[ev.node_id]
        if (node.agg_id == 2 and ev.is_gradual and ev.onset_offset >= 8):
            salim.append(ev)
    salim_congestion = [ev for ev in salim if ev.kind == C.STATUS_CONGESTION]
    salim_w1 = [ev for ev in salim if W_ACT1[0] <= ev.tick <= W_ACT1[1]]

    instant_in_storm = [ev for ev in e.schedule
                        if not ev.is_gradual and ev.tick in storm_set]
    instant_w3 = [ev for ev in instant_in_storm if W_ACT4[0] <= ev.tick <= W_ACT4[1]]

    early_faults = sum(1 for ev in e.schedule if 0 < ev.tick <= CALM_TICKS)
    calm = early_faults <= CALM_MAX_FAULTS

    score = 0.0
    if goizha_storms:
        score += 2.0
    if storm_w2:
        score += 1.0
    if cuts:
        score += 2.0
    if storm_cuts:
        score += 1.5
    if cuts_w2:
        score += 1.0
    if storm_cuts_w2:
        score += 1.0
    if salim:
        score += 2.0
    if salim_congestion:
        score += 0.5
    if salim_w1:
        score += 1.5
    if instant_in_storm:
        score += 1.0
    if instant_w3:
        score += 1.0
    if calm:
        score += 0.5

    def _ev(ev):
        return {
            "tick": ev.tick, "node": ev.node_id, "kind": int(ev.kind),
            "onset": int(ev.onset_offset),
            "activation": ev.tick + ev.onset_offset,
            "episode": int(ev.episode_id),
        }

    def _cut_ev(ev):
        return {
            "tick": ev.tick, "ring": int(ev.ring_id),
            "segment": int(ev.segment_idx), "cause": ev.cause,
            "episode": int(ev.episode_id),
        }

    return {
        "seed": seed, "score": round(score, 1),
        "n_storms": len(goizha_storms),
        "first_storm_tick": goizha_storms[0] if goizha_storms else None,
        "storm_act3": bool(storm_w2),
        "n_fiber_cuts": len(cuts),
        "n_storm_cuts": len(storm_cuts),
        "first_cut": _cut_ev(cuts[0]) if cuts else None,
        "first_storm_cut": _cut_ev(storm_cuts[0]) if storm_cuts else None,
        "cut_act3": bool(cuts_w2),
        "storm_cut_act3": bool(storm_cuts_w2),
        "n_salim_gradual": len(salim),
        "n_salim_congestion": len(salim_congestion),
        "best_salim": _ev(salim_w1[0]) if salim_w1
                      else (_ev(salim[0]) if salim else None),
        "salim_act1": bool(salim_w1),
        "n_instant_in_storm": len(instant_in_storm),
        "first_instant_in_storm": _ev(instant_in_storm[0])
                                   if instant_in_storm else None,
        "instant_act4": bool(instant_w3),
        "early_faults": early_faults,
        "calm_start": calm,
    }


# ------------------------------------------------------------------ search
def search(seeds, days: int = DEMO_DAYS, workers: int = 1) -> list[dict]:
    """Profile every seed, return sorted best-first."""
    if workers <= 1:
        profs = [profile(s, days) for s in seeds]
    else:
        with mp.Pool(workers) as pool:
            profs = pool.map(_profile_worker, [(s, days) for s in seeds])
    return sorted(profs, key=lambda p: -p["score"])


def _profile_worker(params) -> dict:
    seed, days = params
    return profile(seed, days)


# ------------------------------------------------------------------ demo plan
def demo_plan(seed: int, days: int = DEMO_DAYS) -> list[str]:
    p = profile(seed, days)
    e = NOCEngine(seed=seed, horizon=days * C.TICKS_PER_DAY + C.TICKS_PER_DAY)
    ticks = days * C.TICKS_PER_DAY

    lines = []
    lines.append(f"DEMO PLAN — seed {seed}  (score {p['score']:.1f} / 15)")
    lines.append(f"  run: $env:AUTONOC_SEED={seed}; python -m uvicorn "
                 f"autonoc.api.main:app --port 8000")
    lines.append("  (1 tick = ~1 s of demo time at 1x; timings below are "
                 "sim time, not wall clock)")
    lines.append("")
    lines.append(f"  Act 0  {_sim_time(0)}  calm opening — "
                 f"{p['early_faults']} faults in the first 3 sim hours "
                 f"({'calm' if p['calm_start'] else 'busy'})")
    if p["best_salim"]:
        s = p["best_salim"]
        lines.append(f"  Act 1  {_sim_time(s['tick'])}  {s['node']} "
                     f"(Salim St) starts degrading — "
                     f"{C.STATUS_NAMES[s['kind']]}, onset {s['onset']}t, "
                     f"activates {_sim_time(s['activation'])}")
        lines.append("         ENABLE AI in the dashboard; the Oracle should "
                     "flag it inside its 60-min window and the Commander acts")
    else:
        lines.append("  Act 1  (no Salim gradual fault in the window — "
                     "weak seed for the opening)")
    for (a, b) in storm_periods(e, 0, ticks)[:2]:
        wind = e.weather_timeline[a][0]["wind"]
        lines.append(f"  Act 3  {_sim_time(a)}  STORM over Goizha "
                     f"({wind:.0f} km/h), {b - a + 1}t")
    if p["first_storm_cut"]:
        c = p["first_storm_cut"]
        lines.append(f"         natural storm-caused fiber cut: ring "
                     f"{c['ring']} at {_sim_time(c['tick'])} (cause storm)")
        lines.append("         that cut is a SINGLE cut (reroute) — click "
                     "CUT FIBER during the storm for the ISOLATION demo "
                     "(34 alarms -> 1 incident)")
    elif p["first_cut"]:
        c = p["first_cut"]
        lines.append(f"         natural fiber cut: ring {c['ring']} at "
                     f"{_sim_time(c['tick'])}")
        lines.append("         for the ISOLATION demo click CUT FIBER while "
                     "the storm is up (a natural double cut is ~2x/year)")
    else:
        lines.append("         no natural fiber cut — click CUT FIBER "
                     "during the storm")
    if p["first_instant_in_storm"]:
        k = p["first_instant_in_storm"]
        lines.append(f"  Act 4  {_sim_time(k['tick'])}  instant "
                     f"{C.STATUS_NAMES[k['kind']]} during the storm — "
                     f"no warning, by design (25% of faults)")
    else:
        lines.append("  Act 4  (no instant fault inside the storm window — "
                     "the AI can still admit it cannot predict the next one)")
    lines.append("  Act 5  counterfactual table: run")
    lines.append(f"         python -m autonoc.scripts.counterfactual "
                 f"--seeds 30 --days 10 --workers 8")
    return lines


# ------------------------------------------------------------------ verify
def verify(seed: int, days: int = 10) -> dict:
    """Step an autonomous (arm-C) run with the trained models and report
    whether the demo's Salim episode was actually pre-empted live."""
    from autonoc.ai.serve import ModelBundle, score_engine

    bundle = ModelBundle()
    prof = profile(seed, days)
    salim = prof.get("best_salim")

    e = NOCEngine(seed=seed, ai_enabled=True,
                  horizon=days * C.TICKS_PER_DAY + C.TICKS_PER_DAY)
    e.ai_mode = "ml" if bundle.complete else "rules"
    ticks = days * C.TICKS_PER_DAY
    for tick in range(1, ticks + 1):
        e.step()
        if tick % C.AI_INFERENCE_EVERY_TICKS == 0:
            e.ai_verdicts = score_engine(e, bundle)
        for a in [a for a in e.pending_actions if a["state"] == "pending"]:
            if tick - a["created_tick"] >= 1:
                e.approve_action(a["action_id"])

    states = [s.get("state") for s in e.ledger.values()]
    report = {
        "seed": seed,
        "pre_empted": states.count("pre_empted"),
        "activated": states.count("resolved") + states.count("injected"),
        "masked": states.count("masked"),
        "false_dispatches": e.stats["false_dispatch"],
        "ai_mode": e.ai_mode,
        "demo_salim_pre_empted": None,
    }
    if salim is not None:
        ep = salim["episode"]
        report["demo_salim_pre_empted"] = (
            e.ledger.get(ep, {}).get("state") == "pre_empted")
    return report


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description="M8 seed casting")
    ap.add_argument("--seeds", type=int, default=5000,
                    help="number of seeds to search (1..N)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--days", type=int, default=DEMO_DAYS,
                    help="scoring horizon in sim days")
    ap.add_argument("--report", type=int, metavar="SEED",
                    help="print the demo plan for one seed")
    ap.add_argument("--verify", type=int, metavar="SEED",
                    help="step arm C with models; did the demo fault get caught?")
    args = ap.parse_args()

    if args.report is not None:
        for line in demo_plan(args.report, args.days):
            print(line)
        return
    if args.verify is not None:
        r = verify(args.verify)
        print(json.dumps(r, indent=2))
        if r.get("demo_salim_pre_empted") is False:
            print("\n  The demo Salim episode was NOT pre-empted by the "
                  "trained models on this seed.")
            print("  Try the next seed in the ranking, or run --verify on "
                  "another candidate.")
        return

    print(f"M8 seed casting — searching seeds 1..{args.seeds} "
          f"({args.workers} worker(s), {args.days}-day horizon)")
    t0 = __import__("time").perf_counter()
    results = search(range(1, args.seeds + 1), args.days, args.workers)
    print(f"  profiled {len(results)} seeds in "
          f"{__import__('time').perf_counter() - t0:.1f} s\n")

    print("  top 5 demo-worthy seeds:")
    print(f"  {'seed':>6} {'score':>6} {'storm':>6} {'cut':>6} "
          f"{'salim':>6} {'salimA1':>7} {'instSt':>7} {'calm':>5}")
    for p in results[:5]:
        print(f"  {p['seed']:>6} {p['score']:>6.1f} "
              f"{'yes' if p['n_storms'] else '-':>6} "
              f"{'yes' if p['n_fiber_cuts'] else '-':>6} "
              f"{'yes' if p['n_salim_gradual'] else '-':>6} "
              f"{'yes' if p['salim_act1'] else '-':>7} "
              f"{'yes' if p['n_instant_in_storm'] else '-':>7} "
              f"{'yes' if p['calm_start'] else '-':>5}")

    best = results[0]
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "cast_seed.json").write_text(json.dumps(best, indent=2))
    print(f"\n  best seed -> {best['seed']} (score {best['score']}/15)")
    print(f"  wrote reports/cast_seed.json\n")
    for line in demo_plan(best["seed"], args.days):
        print(line)
    print("\n  Next: --verify <seed> with the trained models to confirm the "
          "Oracle catches the demo fault live.")


if __name__ == "__main__":
    main()
