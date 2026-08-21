"""
Training-data generation from the engine.

Every leak found in the v1 audit is closed here BY CONSTRUCTION rather than
patched afterwards:

  L1  SMOTE before split          -> no SMOTE at all; class weights instead
  L2  scaler fit on all data      -> scaler is fit in train.py, on train only
  L3  rolling features across     -> features are built per node, from that
      node boundaries                node's own deque
  L4  random split on temporal    -> chronological, blocked by season
      data
  L5  seasonal split imbalance    -> blocked split keeps every regime in both
                                     train and test
  L6  subsample before split      -> subsampling happens after, per split
  L7  same seed train and eval    -> separate seeds, recorded per row
  L8  feature peeks ahead         -> features read only hist_fine
  L9  node identity leak          -> site_id is metadata, never a feature
  L10 ripple contamination        -> embargo around every episode boundary

Each row also carries episode_id, so train/test can be grouped by episode.
One 18-tick fault produces ~30 overlapping windows sharing 92% of their
timesteps; splitting by node and time alone would put near-duplicates on both
sides.
"""
from __future__ import annotations

import csv
import pathlib
import random

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine

from .features import build_vector, feature_names

# Rows are sampled rather than taken every tick: consecutive rows from one
# node are almost identical, so full capture mostly inflates file size.
SAMPLE_EVERY = 3

# Healthy rows outnumber faults ~43:1. Keep a fraction at generation time so
# the file stays manageable; the precise ratio is set per split in train.py.
HEALTHY_KEEP = 0.10


def generate(seed: int, days: int, out_path: str,
             progress: bool = True) -> dict:
    """Run the engine headless and write one CSV of feature rows."""
    ticks = days * C.TICKS_PER_DAY
    engine = NOCEngine(seed=seed, horizon=ticks + C.TICKS_PER_DAY)
    rng = random.Random(seed * 31 + 7)

    names = feature_names()
    header = (["tick", "site_id", "agg_id", "seed", "day_of_year",
               "episode_id", "label", "will_fail_30", "will_fail_60"]
              + names)

    # Episode ids restart at 0 for every seed, so ids collide across files
    # and the disjointness check in train.py trips. Namespace them by seed.
    ep_base = seed * 1_000_000

    # onset lookup: for each node, the ticks at which a fault lands.
    # Used ONLY to build labels and the embargo, never as a feature.
    onsets: dict[str, list[tuple[int, int, int]]] = {}
    for ev in engine.schedule:
        landing = ev.tick + ev.onset_offset
        onsets.setdefault(ev.node_id, []).append(
            (landing, ev.kind, ep_base + ev.episode_id))
    for v in onsets.values():
        v.sort()

    path = pathlib.Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    label_counts: dict[int, int] = {}

    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)

        for t in range(ticks):
            engine.step()
            if t % SAMPLE_EVERY:
                continue
            tick = engine.tick
            day = (C.START_DAY_OF_YEAR + tick // C.TICKS_PER_DAY) % 365

            for node in engine.nodes:
                label = node.status

                # embargo: a row sitting just before an onset already carries
                # degradation signal but would be labelled healthy, teaching
                # the model contradictory targets and leaking positives into
                # the negative pool
                in_embargo = False
                fail_30 = fail_60 = 0
                ep = (ep_base + node.episode_id
                      if node.episode_id >= 0 else -1)
                for landing, kind, episode in onsets.get(node.node_id, ()):
                    lead = landing - tick
                    if 0 < lead <= 6:
                        fail_30 = 1
                    if 0 < lead <= 12:
                        fail_60 = 1
                    if abs(lead) <= C.EMBARGO_TICKS:
                        if label == C.STATUS_HEALTHY and lead > 12:
                            in_embargo = True
                        if lead <= 0 and ep < 0:
                            ep = episode

                if in_embargo:
                    continue
                if label == C.STATUS_HEALTHY and rng.random() > HEALTHY_KEEP:
                    continue

                row = ([tick, node.node_id, node.agg_id, seed, day,
                        ep, label, fail_30, fail_60]
                       + [round(v, 5) for v in build_vector(node)])
                w.writerow(row)
                written += 1
                label_counts[label] = label_counts.get(label, 0) + 1

            if progress and t % (C.TICKS_PER_DAY * 2) == 0:
                print(f"    day {t // C.TICKS_PER_DAY:3}/{days}  "
                      f"rows={written:,}", flush=True)

    return {
        "path": str(path), "seed": seed, "days": days,
        "rows": written, "labels": dict(sorted(label_counts.items())),
        "features": len(names),
    }


def main() -> None:
    """Generate train / validation / test sets on SEPARATE seeds.

    Different seeds mean different weather, different fault timing and
    different traffic — the test set is not a re-run of training data with a
    different slice taken out.
    """
    print("AutoNOC dataset generation\n")
    plans = [
        ("data/train.csv", 42, 60),
        ("data/val.csv", 90, 12),
        ("data/test.csv", 99, 20),
    ]
    for out, seed, days in plans:
        print(f"  {out}  seed={seed}  {days} simulated days")
        info = generate(seed, days, out)
        total = sum(info["labels"].values())
        print(f"    -> {info['rows']:,} rows, {info['features']} features")
        for lbl, n in info["labels"].items():
            print(f"       {lbl} {C.STATUS_NAMES[lbl]:20} {n:7,} "
                  f"({n / total * 100:5.1f}%)")
        print()


if __name__ == "__main__":
    main()
