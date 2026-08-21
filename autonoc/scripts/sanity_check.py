"""
Physical sanity check. Runs the engine headless and prints distributions
that should be checked against real-world expectations.

Usage:  python3 -m autonoc.scripts.sanity_check
"""
from __future__ import annotations

import statistics
import time

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine


def main(seed: int = 42, days: int = 7) -> None:
    ticks = days * C.TICKS_PER_DAY
    print(f"AutoNOC engine sanity check — seed {seed}, {days} simulated days\n")

    e = NOCEngine(seed=seed, horizon=ticks + C.TICKS_PER_DAY)
    t0 = time.perf_counter()
    avail_series = []
    for i in range(ticks):
        e.step()
        if i % C.TICKS_PER_HOUR == 0:
            avail_series.append(e.kpis()["availability"])
    elapsed = time.perf_counter() - t0

    print(f"runtime      {elapsed:.1f} s for {ticks} ticks "
          f"({elapsed / ticks * 1000:.2f} ms/tick)")
    k = e.kpis()
    print(f"\n--- final state ({k['sim_time']}) ---")
    for key in ("availability", "healthy", "congestion", "overheat",
                "rf", "power", "backhaul", "active_teams", "mttr_min"):
        print(f"  {key:14} {k[key]}")
    print(f"\n--- availability over {days} days ---")
    print(f"  mean {statistics.mean(avail_series):.2f}%  "
          f"min {min(avail_series):.2f}%  max {max(avail_series):.2f}%")

    healthy = [n for n in e.nodes if n.status == C.STATUS_HEALTHY]
    rsrp = sorted(n.rsrp for n in healthy)
    print(f"\n--- RSRP across {len(healthy)} healthy nodes (expect -70..-110) ---")
    for pct in (0, 10, 50, 90, 100):
        idx = min(len(rsrp) - 1, pct * len(rsrp) // 100)
        print(f"  p{pct:<3} {rsrp[idx]:7.1f} dBm")

    print("\n--- RSRP by district (clutter correction working?) ---")
    for site in e.net.agg_sites:
        vals = [e.net.by_id[i].rsrp for i in site.node_ids
                if e.net.by_id[i].status == C.STATUS_HEALTHY]
        if vals:
            print(f"  {site.name:18} {statistics.mean(vals):7.1f} dBm  "
                  f"(C={site.clutter_c:+.0f})")

    temps = [n.temperature for n in healthy]
    print(f"\n--- temperature ---")
    print(f"  mean {statistics.mean(temps):.1f} C  "
          f"min {min(temps):.1f}  max {max(temps):.1f}")

    print("\n--- fault ledger ---")
    print(f"  injected      {e.stats['injected']}")
    print(f"  masked        {e.stats['masked']} "
          f"({e.stats['masked'] / max(1, e.stats['injected'] + e.stats['masked']) * 100:.1f}%)")
    print(f"  self-healed   {e.stats['self_healed']}")
    print(f"  remote resets {e.stats['remote_resets']}")
    print(f"  team repairs  {e.stats['repairs']}")
    print(f"  faults/day    {e.stats['injected'] / days:.0f}")

    print("\n--- fiber rings ---")
    for r in e.net.rings:
        print(f"  ring {r.ring_id}: {len(r.node_ids):3} nodes, "
              f"{r.circumference_km:5.1f} km circumference")

    print("\n--- teams ---")
    for t in e.teams:
        print(f"  {t.name:16} {t.skill:8} {t.state:10} missions={t.dispatch_count}")

    dust = [n.dust_accum for n in e.nodes]
    print(f"\n--- dust accumulation (drives the slow signature) ---")
    print(f"  mean {statistics.mean(dust):.3f}  max {max(dust):.3f}")

    print("\n--- last 8 log lines ---")
    for entry in list(e.logs)[-8:]:
        print(f"  [{entry['time']}] {entry['severity']:8} {entry['message'][:78]}")


if __name__ == "__main__":
    main()
