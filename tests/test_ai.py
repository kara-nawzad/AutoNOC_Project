"""
Guards for the ML pipeline. Every one encodes a leak found in the v1 audit.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine

DATA = pathlib.Path("data")
MODELS = pathlib.Path("models")

needs_data = pytest.mark.skipif(
    not (DATA / "test.csv").exists(), reason="run autonoc.ai.dataset first")
needs_model = pytest.mark.skipif(
    not (MODELS / "doctor_xgb.json").exists(), reason="run autonoc.ai.train first")


def test_feature_contract_is_stable():
    """Feature count and order must be fixed.

    v1's scaler expected 35 features and the live path supplied 11. Nothing
    caught it; the model just produced nonsense.
    """
    from autonoc.ai.features import N_FEATURES, build_vector, feature_names

    names = feature_names()
    assert len(names) == N_FEATURES
    assert len(set(names)) == len(names), "duplicate feature names"

    e = NOCEngine(seed=3)
    for _ in range(20):
        e.step()
    for node in e.nodes[:5]:
        assert len(build_vector(node)) == N_FEATURES


def test_features_never_look_ahead():
    """L8: the single easiest way to build a fake 99% model.
    A feature at tick t may use only data from ticks <= t. The label may be
    future-derived; a feature may not.
    """
    from autonoc.ai.features import assert_no_lookahead

    e = NOCEngine(seed=5)
    for _ in range(30):
        e.step()
    assert_no_lookahead(e.nodes[0], e)


def test_site_id_is_not_a_feature():
    """L9: node identity would let the model memorise which towers fail,
    which does not transfer to an unseen site."""
    from autonoc.ai.features import feature_names

    for n in feature_names():
        assert "site" not in n.lower()
        assert "node_id" not in n.lower()


@needs_data
def test_splits_use_different_seeds():
    """L7: a shared seed means the test set is a re-run of training data."""
    import pandas as pd

    seeds = {s: pd.read_csv(DATA / f"{s}.csv", usecols=["seed"]).seed.iloc[0]
             for s in ("train", "val", "test")}
    assert len(set(seeds.values())) == 3, f"seeds not distinct: {seeds}"


@needs_data
def test_episodes_are_disjoint_across_splits():
    """One 18-tick fault yields ~30 windows sharing 92% of their timesteps.
    Splitting by node and time alone puts near-duplicates on both sides."""
    import pandas as pd

    def eps(split):
        d = pd.read_csv(DATA / f"{split}.csv", usecols=["episode_id"])
        return set(d.loc[d.episode_id >= 0, "episode_id"])

    tr, te, va = eps("train"), eps("test"), eps("val")
    assert not (tr & te), f"{len(tr & te)} episodes shared train/test"
    assert not (tr & va), f"{len(tr & va)} episodes shared train/val"


@needs_model
def test_metrics_reported_at_true_prevalence():
    """The critical one.

    Healthy rows are subsampled 10x. Reporting precision on that rebalanced
    sample overstates it by ~50 points — 91.2% versus 41.1% measured — which
    flips the conclusion from 'autonomy justified' to 'the AI makes the
    network worse'.
    """
    m = json.loads((MODELS / "doctor_metrics.json").read_text())
    prev = m["true_prevalence"]
    assert prev < 0.05, (
        f"reported prevalence {prev:.1%} looks like the subsampled rate, "
        f"not the natural one"
    )
    assert "false_positive_rate" in m["fault_level"], (
        "FPR must be reported: at this prevalence it dominates precision"
    )


@needs_model
def test_baseline_b0_is_reported():
    """B0 'always healthy' scores higher than any honest model. Publishing it
    is the cleanest demonstration that accuracy is a vanity metric here."""
    m = json.loads((MODELS / "doctor_metrics.json").read_text())
    assert m["baselines"]["B0_accuracy"] > 0.95


@needs_model
def test_model_is_not_memorising_geography():
    """Static site attributes alone must be near-useless.
    If elevation, clutter class and grid tier could identify a node, the model
    would be learning geography rather than fault physics. Measured: 0.014
    precision from static features alone.
    """
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier
    from autonoc.ai.dataset import HEALTHY_KEEP

    static = ["generation", "clutter_c", "elevation_m", "is_critical",
              "grid_tier_code", "agg_id"]
    tr = pd.read_csv(DATA / "train.csv", usecols=static + ["label"])
    te = pd.read_csv(DATA / "test.csv", usecols=static + ["label"])

    clf = XGBClassifier(n_estimators=60, max_depth=4, tree_method="hist",
                        num_class=5, objective="multi:softprob",
                        eval_metric="mlogloss", n_jobs=-1, random_state=0)
    sc = StandardScaler().fit(tr[static])
    clf.fit(sc.transform(tr[static]), tr.label)
    pred = clf.predict(sc.transform(te[static]))

    w = np.where(te.label == 0, 1 / HEALTHY_KEEP, 1.0)
    yb = (te.label != 0).astype(int).to_numpy()
    pb = (pred != 0).astype(int)
    tp = float(((yb == 1) & (pb == 1)) @ w)
    fp = float(((yb == 0) & (pb == 1)) @ w)
    prec = tp / (tp + fp) if tp + fp else 0.0
    assert prec < 0.15, (
        f"static-only precision {prec:.3f} — the model can identify nodes "
        f"from their attributes, so it may be memorising geography"
    )


# ------------------------------------------------------------------ Oracle
needs_seq = pytest.mark.skipif(
    not (DATA / "seq_test.npz").exists(),
    reason="run autonoc.ai.seqdata first")
needs_oracle = pytest.mark.skipif(
    not (MODELS / "oracle_metrics.json").exists(),
    reason="run autonoc.ai.oracle first")


@needs_seq
def test_sequence_windows_are_contiguous():
    """The Oracle's windows must span exactly 60 simulated minutes.
    An earlier version built sequences from the 10x-subsampled tabular data,
    where a 12-step window spanned 12-50 HOURS while the degradation it must
    detect unfolds over 1-2 hours. The GRU scored AUC-PR 0.035 and looked
    decisively beaten — but that was a broken pipeline, not a finding about
    deep learning. Contiguity is the whole comparison.
    """
    from autonoc.ai.seqdata import CHANNELS, SEQ_LEN

    d = np.load(DATA / "seq_test.npz", allow_pickle=True)
    X = d["X"]
    assert X.ndim == 3
    assert X.shape[1] == SEQ_LEN, f"window is {X.shape[1]} steps, want {SEQ_LEN}"
    assert X.shape[2] == len(CHANNELS)
    assert SEQ_LEN * C.TICK_MINUTES == 60


@needs_seq
def test_sequence_channels_are_raw_telemetry():
    """The GRU must not be handed engine-computed rolling features.
    The question is whether a recurrent model can learn temporal structure by
    itself. Feeding it *_slope_1h would answer a different question.
    """
    d = np.load(DATA / "seq_test.npz", allow_pickle=True)
    for ch in d["channels"]:
        name = str(ch)
        assert not name.endswith(("_slope_1h", "_std_1h", "_mean_1h", "_delta"))


@needs_oracle
def test_oracle_benchmark_includes_all_baselines():
    """A deep model reported without baselines is not evidence."""
    m = json.loads((MODELS / "oracle_metrics.json").read_text())
    r = m["results"]
    for key in ("B0", "B1", "B2", "B3"):
        assert key in r, f"baseline {key} missing from the benchmark"
    assert r["B0"]["accuracy"] > 0.95, "B0 should expose the accuracy trap"


@needs_oracle
def test_oracle_precision_clears_break_even():
    """Below 43.8% precision the Commander acting on these predictions would
    make the network worse, not better."""
    m = json.loads((MODELS / "oracle_metrics.json").read_text())
    best = max((v for k, v in m["results"].items() if "precision" in v),
               key=lambda v: v.get("auc_pr", 0))
    assert best["precision"] > C.BREAK_EVEN_PRECISION, (
        f"precision {best['precision']:.3f} is below break-even "
        f"{C.BREAK_EVEN_PRECISION:.3f}"
    )
