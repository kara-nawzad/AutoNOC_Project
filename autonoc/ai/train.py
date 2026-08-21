"""
Train the Doctor (XGBoost) and report honestly.

THE CRITICAL CORRECTION
    Healthy rows are subsampled 10x at generation time to keep files
    manageable. Reporting precision on that rebalanced sample would overstate
    it by ~50 percentage points — measured: 91.2% on the subsample versus
    41.1% at true prevalence, which flips the project's conclusion from
    "autonomy justified" to "the AI makes the network worse".

    Every metric here is therefore computed with SAMPLE WEIGHTS that restore
    the natural 2.2% fault prevalence.

BASELINES ARE MANDATORY
    B0 "always predict healthy" is the important one. At 43:1 imbalance it
    scores ~97.8% accuracy — higher than any honest model will reach. Showing
    that number explicitly is the cleanest demonstration of why accuracy is a
    vanity metric here.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd
from sklearn.metrics import (brier_score_loss, classification_report,
                             confusion_matrix, precision_recall_fscore_support)
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from autonoc.engine import config as C

from .dataset import HEALTHY_KEEP
from .features import feature_names

MODEL_DIR = pathlib.Path("models")
DATA_DIR = pathlib.Path("data")


def _load(split: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{split}.csv")
    # restore natural prevalence: healthy rows were kept at HEALTHY_KEEP
    df["weight"] = np.where(df["label"] == C.STATUS_HEALTHY,
                            1.0 / HEALTHY_KEEP, 1.0)
    return df


def _check_episode_disjoint(train: pd.DataFrame, test: pd.DataFrame) -> None:
    """No fault episode may appear in both splits.

    One 18-tick fault yields ~30 overlapping windows sharing 92% of their
    timesteps. Splitting by node and time alone puts near-duplicates on both
    sides, and the model is then tested on what it memorised.
    """
    a = set(train.loc[train.episode_id >= 0, "episode_id"])
    b = set(test.loc[test.episode_id >= 0, "episode_id"])
    overlap = a & b
    assert not overlap, f"{len(overlap)} episodes appear in both splits"


def _weighted_report(y, pred, w, title: str) -> dict:
    print(f"\n  {title}")
    print(f"  {'class':22} {'precision':>10} {'recall':>8} {'f1':>8} {'support':>10}")
    p, r, f, s = precision_recall_fscore_support(
        y, pred, labels=sorted(set(y)), sample_weight=w, zero_division=0)
    out = {}
    for i, lbl in enumerate(sorted(set(y))):
        name = C.STATUS_NAMES.get(lbl, str(lbl))
        print(f"  {name:22} {p[i]:10.3f} {r[i]:8.3f} {f[i]:8.3f} {s[i]:10,.0f}")
        out[name] = {"precision": float(p[i]), "recall": float(r[i]),
                     "f1": float(f[i]), "support": float(s[i])}
    return out


def _fault_level_metrics(y, pred, w) -> dict:
    """Binary view: any fault vs healthy. This is what the Commander acts on."""
    yb = (y != C.STATUS_HEALTHY).astype(int)
    pb = (pred != C.STATUS_HEALTHY).astype(int)
    tp = float(((yb == 1) & (pb == 1)) @ w)
    fp = float(((yb == 0) & (pb == 1)) @ w)
    fn = float(((yb == 1) & (pb == 0)) @ w)
    tn = float(((yb == 0) & (pb == 0)) @ w)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {"precision": prec, "recall": rec, "false_positive_rate": fpr,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def main() -> None:
    MODEL_DIR.mkdir(exist_ok=True)
    names = feature_names()

    print("=" * 66)
    print("  THE DOCTOR — XGBoost fault diagnosis")
    print("=" * 66)

    train = _load("train")
    val = _load("val")
    test = _load("test")
    _check_episode_disjoint(train, test)
    _check_episode_disjoint(train, val)

    print(f"\n  train {len(train):>8,} rows   seed {train.seed.iloc[0]}")
    print(f"  val   {len(val):>8,} rows   seed {val.seed.iloc[0]}")
    print(f"  test  {len(test):>8,} rows   seed {test.seed.iloc[0]}")
    print(f"  episodes disjoint across all splits: yes")

    tw = test["weight"].to_numpy()
    true_prev = float((test.label != C.STATUS_HEALTHY) @ tw / tw.sum())
    print(f"\n  test prevalence at natural rate: {true_prev:.3%}")
    print(f"  (raw file shows {(test.label != C.STATUS_HEALTHY).mean():.1%} "
          f"— healthy rows were subsampled {1/HEALTHY_KEEP:.0f}x)")

    Xtr, ytr = train[names].to_numpy(np.float32), train.label.to_numpy()
    Xte, yte = test[names].to_numpy(np.float32), test.label.to_numpy()

    # scaler fit on TRAIN ONLY — v1 fit it on everything and leaked test
    # mean/variance into training
    scaler = StandardScaler().fit(Xtr)
    Xtr_s, Xte_s = scaler.transform(Xtr), scaler.transform(Xte)

    # ---------------------------------------------------------- baselines
    print("\n" + "-" * 66)
    print("  BASELINES")
    print("-" * 66)

    b0 = np.full_like(yte, C.STATUS_HEALTHY)
    acc_b0 = float((b0 == yte) @ tw / tw.sum())
    print(f"\n  B0  always predict healthy")
    print(f"      accuracy {acc_b0:.4f}  <-- higher than any honest model")
    print(f"      recall on faults: 0.000")
    print(f"      This is why accuracy is a vanity metric at {true_prev:.1%} "
          f"prevalence.")

    # B1: the threshold rules v1 actually used
    b1 = np.full_like(yte, C.STATUS_HEALTHY)
    b1[test.temperature.to_numpy() > C.THRESH_TEMP] = C.STATUS_OVERHEAT
    b1[test.s11.to_numpy() > C.THRESH_S11] = C.STATUS_RF
    b1[test.voltage.to_numpy() < 11.0] = C.STATUS_POWER
    b1[test.cpu_load.to_numpy() > C.THRESH_CPU] = C.STATUS_CONGESTION
    m_b1 = _fault_level_metrics(yte, b1, tw)
    print(f"\n  B1  simple thresholds (v1's actual behaviour)")
    print(f"      precision {m_b1['precision']:.3f}  recall {m_b1['recall']:.3f}"
          f"  FPR {m_b1['false_positive_rate']:.4f}")

    # ---------------------------------------------------------- model
    print("\n" + "-" * 66)
    print("  TRAINING")
    print("-" * 66)

    classes, counts = np.unique(ytr, return_counts=True)
    cw = {int(c): float(len(ytr) / (len(classes) * n))
          for c, n in zip(classes, counts)}
    w_tr = np.array([cw[int(v)] for v in ytr], dtype=np.float32)
    print(f"\n  class weights (no SMOTE — interpolating telemetry would")
    print(f"  produce physically impossible half-overheated nodes):")
    for c in sorted(cw):
        print(f"    {C.STATUS_NAMES[c]:22} {cw[c]:7.2f}")

    model = XGBClassifier(
        n_estimators=400, max_depth=6, learning_rate=0.08,
        subsample=0.85, colsample_bytree=0.85,
        objective="multi:softprob", num_class=len(classes),
        eval_metric="mlogloss", tree_method="hist",
        random_state=42, n_jobs=-1,
    )
    model.fit(Xtr_s, ytr, sample_weight=w_tr, verbose=False)

    pred = model.predict(Xte_s)
    proba = model.predict_proba(Xte_s)

    # ---------------------------------------------------------- results
    print("\n" + "=" * 66)
    print("  RESULTS — fully held out (unseen nodes, unseen seed, unseen time)")
    print("  All metrics weighted to natural prevalence.")
    print("=" * 66)

    per_class = _weighted_report(yte, pred, tw, "per class")
    m = _fault_level_metrics(yte, pred, tw)

    print(f"\n  fault vs healthy (what the Commander acts on)")
    print(f"    precision            {m['precision']:.3f}")
    print(f"    recall               {m['recall']:.3f}")
    print(f"    false positive rate  {m['false_positive_rate']:.4f}"
          f"   <-- dominates precision at this prevalence")
    print(f"    break-even precision {C.BREAK_EVEN_PRECISION:.3f}")
    verdict = ("ABOVE break-even — autonomy is justified"
               if m["precision"] > C.BREAK_EVEN_PRECISION
               else "BELOW break-even — acting would make the network WORSE")
    print(f"    -> {verdict}")

    # calibration: the Commander consumes probabilities directly, so a
    # miscalibrated 0.8 corrupts the entire decision layer
    p_fault = 1.0 - proba[:, 0]
    y_fault = (yte != C.STATUS_HEALTHY).astype(int)
    brier = brier_score_loss(y_fault, p_fault, sample_weight=tw)
    print(f"\n  calibration (Brier, lower is better): {brier:.4f}")
    print(f"  {'confidence band':>18} {'predicted':>10} {'actual':>8} {'n':>9}")
    for lo, hi in ((0.0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
        sel = (p_fault >= lo) & (p_fault < hi)
        if sel.sum() < 20:
            continue
        exp = float(p_fault[sel] @ tw[sel] / tw[sel].sum())
        act = float(y_fault[sel] @ tw[sel] / tw[sel].sum())
        print(f"  {lo:.1f}-{hi:.1f}{'':>10} {exp:10.3f} {act:8.3f} "
              f"{tw[sel].sum():9,.0f}")

    print("\n  confusion matrix (rows true, cols predicted, weighted)")
    cm = confusion_matrix(yte, pred, sample_weight=tw)
    hdr = "".join(f"{C.STATUS_NAMES[c][:9]:>11}" for c in sorted(set(yte)))
    print(f"  {'':22}{hdr}")
    for i, c in enumerate(sorted(set(yte))):
        row = "".join(f"{v:11,.0f}" for v in cm[i])
        print(f"  {C.STATUS_NAMES[c]:22}{row}")

    print("\n  top 15 features by gain")
    imp = sorted(zip(names, model.feature_importances_),
                 key=lambda x: -x[1])[:15]
    for n, v in imp:
        print(f"    {n:28} {v:.4f}")

    # ---------------------------------------------------------- save
    model.save_model(MODEL_DIR / "doctor_xgb.json")
    np.savez(MODEL_DIR / "doctor_scaler.npz",
             mean=scaler.mean_, scale=scaler.scale_)
    (MODEL_DIR / "feature_order.json").write_text(json.dumps(names, indent=1))
    (MODEL_DIR / "doctor_metrics.json").write_text(json.dumps({
        "per_class": per_class,
        "fault_level": m,
        "baselines": {"B0_accuracy": acc_b0, "B1": m_b1},
        "brier": float(brier),
        "true_prevalence": true_prev,
        "break_even_precision": C.BREAK_EVEN_PRECISION,
        "n_features": len(names),
        "seeds": {"train": int(train.seed.iloc[0]),
                  "test": int(test.seed.iloc[0])},
    }, indent=2))

    print(f"\n  saved -> {MODEL_DIR}/doctor_xgb.json")
    print(f"           {MODEL_DIR}/feature_order.json ({len(names)} features)")
    print(f"           {MODEL_DIR}/doctor_metrics.json")


if __name__ == "__main__":
    main()
