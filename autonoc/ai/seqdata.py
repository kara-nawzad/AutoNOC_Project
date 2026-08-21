"""
Contiguous sequence dataset for the Oracle.

WHY THIS EXISTS

The tabular dataset subsamples healthy rows 10x to keep file sizes sane. That
is fine for XGBoost, which receives pre-computed `*_slope_1h` and `*_std_1h`
features calculated inside the engine from contiguous ticks.

It is fatal for a recurrent model. Measured on the tabular data, a 12-step
window spanned:

    min 12.5 h   median 30.8 h   max 51.8 h

while the degradation it must detect unfolds over:

    congestion  0.3-1.0 h
    overheat    0.5-1.5 h
    RF/antenna  1.0-2.0 h

The GRU was being shown twelve snapshots taken days apart and asked to spot an
hour-long trend. It scored AUC-PR 0.035 against XGBoost's 0.484 — but that was
a broken comparison, not evidence about deep learning.

This module records genuinely contiguous windows straight from the engine, so
both models see the same 1-hour horizon and the benchmark means something.
"""
from __future__ import annotations

import pathlib

import numpy as np

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine

# 12 contiguous ticks = 60 simulated minutes, matching the degradation window
SEQ_LEN = 12

# Channels sampled every tick. Raw telemetry only — no engine-computed
# rolling features, because the whole point is to test whether the network
# can learn temporal structure for itself.
CHANNELS = (
    "rsrp", "sinr", "s11", "latency", "jitter", "packet_loss",
    "throughput", "cpu_load", "temperature", "voltage", "battery_pct",
    "dust_accum",
)

# Keep this fraction of negative windows. The natural rate is ~57:1, which
# wastes almost every gradient step on trivially-negative examples.
NEG_KEEP = 0.06


def _read(node) -> list[float]:
    return [float(getattr(node, c)) for c in CHANNELS]


def generate(seed: int, days: int, out_path: str,
             progress: bool = True) -> dict:
    """Roll a contiguous window per node and snapshot it every tick."""
    ticks = days * C.TICKS_PER_DAY
    engine = NOCEngine(seed=seed, horizon=ticks + C.TICKS_PER_DAY)
    rng = np.random.RandomState(seed * 13 + 5)

    # onset lookup drives the label; never used as an input
    onsets: dict[str, list[int]] = {}
    for ev in engine.schedule:
        onsets.setdefault(ev.node_id, []).append(ev.tick + ev.onset_offset)
    for v in onsets.values():
        v.sort()

    buffers: dict[str, list] = {n.node_id: [] for n in engine.nodes}
    X: list = []
    y: list = []
    meta: list = []

    for _ in range(ticks):
        engine.step()
        tick = engine.tick

        for node in engine.nodes:
            buf = buffers[node.node_id]
            buf.append(_read(node))
            if len(buf) > SEQ_LEN:
                buf.pop(0)

            if len(buf) < SEQ_LEN:
                continue
            # only predict for nodes that currently look healthy
            if node.status != C.STATUS_HEALTHY:
                buf.clear()          # a fault breaks window continuity
                continue

            label = 0
            embargo = False
            for landing in onsets.get(node.node_id, ()):
                lead = landing - tick
                if 0 < lead <= 12:               # fails within 60 min
                    label = 1
                elif 12 < lead <= C.EMBARGO_TICKS:
                    embargo = True               # ambiguous, exclude
            if embargo and label == 0:
                continue
            if label == 0 and rng.rand() > NEG_KEEP:
                continue

            X.append(np.asarray(buf, dtype=np.float32))
            y.append(label)
            meta.append((tick, node.agg_id))

        if progress and tick % (C.TICKS_PER_DAY * 3) == 0:
            print(f"    day {tick // C.TICKS_PER_DAY:3}/{days}  "
                  f"windows={len(X):,}", flush=True)

    Xa = np.asarray(X, dtype=np.float32)
    ya = np.asarray(y, dtype=np.int8)
    ma = np.asarray(meta, dtype=np.int32)

    path = pathlib.Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, X=Xa, y=ya, meta=ma,
                        channels=np.array(CHANNELS), seed=seed,
                        neg_keep=NEG_KEEP)

    return {"path": str(path), "windows": len(Xa), "positive": int(ya.sum()),
            "shape": Xa.shape, "seed": seed}


def main() -> None:
    print("Contiguous sequence generation for the Oracle\n")
    print(f"  {SEQ_LEN} consecutive ticks = "
          f"{SEQ_LEN * C.TICK_MINUTES} simulated minutes")
    print(f"  {len(CHANNELS)} raw channels, no engine-computed features\n")
    for out, seed, days in (("data/seq_train.npz", 42, 45),
                            ("data/seq_test.npz", 99, 18)):
        print(f"  {out}  seed={seed}  {days} days")
        info = generate(seed, days, out)
        pos = info["positive"]
        n = info["windows"]
        print(f"    -> {n:,} windows, {pos:,} positive ({pos / n:.2%}), "
              f"shape {info['shape']}\n")


if __name__ == "__main__":
    main()
