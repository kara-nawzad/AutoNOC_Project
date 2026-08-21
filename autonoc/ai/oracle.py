"""
The Oracle — will this node fail within 60 minutes?

THE POINT IS THE BENCHMARK, NOT THE MODEL.

Deep learning is only worth shipping if it beats simpler alternatives on the
same held-out data:

    B0   always predict "no failure"      the majority-class trap
    B1   hand-tuned trend thresholds      what a competent engineer writes
    B2   logistic regression on lag feats linear baseline
    B3   XGBoost on lag features          strong tabular baseline
    M    GRU on the raw sequence          deep learning

If the GRU wins we can prove deep learning was necessary. If it loses we
report that and ship XGBoost. Both are defensible results; "I used an LSTM
because it sounded advanced" is not.

A FALSE RESULT WE ALMOST PUBLISHED
    The first run had the GRU at AUC-PR 0.035 against XGBoost's 0.484, which
    looks like a decisive answer. It was a bug in the data pipeline. Healthy
    rows are subsampled 10x in the tabular set, so a 12-step window spanned
    12-50 HOURS while the degradation it must detect unfolds over 1-2 hours.
    The GRU was shown snapshots taken days apart and asked to spot an
    hour-long trend.

    Both models now read the same contiguous 60-minute windows from
    seqdata.py, so the comparison actually measures what it claims to.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from autonoc.engine import config as C

from .seqdata import CHANNELS, SEQ_LEN

MODEL_DIR = pathlib.Path("models")
DATA_DIR = pathlib.Path("data")

try:                          # module-level so serve.py can import GRUNet
    import torch
    import torch.nn as nn
    _TORCH_OK = True
except ImportError:
    torch = None              # type: ignore[assignment]
    nn = None                 # type: ignore[assignment]
    _TORCH_OK = False


if _TORCH_OK:
    class GRUNet(nn.Module):
        """Small on purpose. ~64k positive windows will not support a large
        network without memorising. Defined at module level so the live
        serving layer (ai/serve.py) can re-instantiate it from the saved
        state_dict."""

        def __init__(self, n_ch: int, hidden: int = 64):
            super().__init__()
            self.gru = nn.GRU(n_ch, hidden, num_layers=1, batch_first=True)
            self.drop = nn.Dropout(0.2)
            self.head = nn.Sequential(nn.Linear(hidden, 32), nn.ReLU(),
                                      nn.Linear(32, 1))

        def forward(self, x):
            out, _ = self.gru(x)
            return self.head(self.drop(out[:, -1])).squeeze(-1)
else:
    GRUNet = None             # type: ignore[assignment,misc]


def load_oracle_artifacts() -> tuple:
    """Return (model, mu, sd, seq_len, channels) for live inference.

    Raises FileNotFoundError if anything is missing; the serving layer turns
    that into rules-mode fallback.
    """
    import numpy as np
    import torch

    stats = np.load(MODEL_DIR / "oracle_stats.npz")
    mu = stats["mu"]
    sd = stats["sd"]
    net = GRUNet(len(CHANNELS))
    net.load_state_dict(torch.load(MODEL_DIR / "oracle_gru.pt",
                                   map_location="cpu", weights_only=True))
    net.eval()
    return net, mu, sd, SEQ_LEN, CHANNELS


# --------------------------------------------------------------------------
def load(split: str):
    d = np.load(DATA_DIR / f"seq_{split}.npz", allow_pickle=True)
    return d["X"], d["y"].astype(np.int64), float(d["neg_keep"])


def weights_for(y: np.ndarray, neg_keep: float) -> np.ndarray:
    """Restore natural prevalence.

    Negative windows were kept at NEG_KEEP during generation. Reporting
    precision on the subsampled mix would overstate it badly — the same trap
    that would have inverted the Doctor's conclusion.
    """
    return np.where(y == 0, 1.0 / neg_keep, 1.0).astype(np.float64)


def flatten_lags(X: np.ndarray) -> np.ndarray:
    """Turn a sequence into the lag features a tabular model would be given:
    last value, mean, std, slope and total delta per channel."""
    last = X[:, -1, :]
    mean = X.mean(axis=1)
    std = X.std(axis=1)
    delta = X[:, -1, :] - X[:, 0, :]
    t = np.arange(SEQ_LEN, dtype=np.float32)
    t = (t - t.mean())
    slope = (X * t[None, :, None]).sum(axis=1) / (t ** 2).sum()
    return np.concatenate([last, mean, std, delta, slope], axis=1)


def metrics_at(y, score, w, threshold: float) -> dict:
    pred = (score >= threshold).astype(int)
    tp = float(((y == 1) & (pred == 1)) @ w)
    fp = float(((y == 0) & (pred == 1)) @ w)
    fn = float(((y == 1) & (pred == 0)) @ w)
    tn = float(((y == 0) & (pred == 0)) @ w)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"threshold": threshold, "precision": prec, "recall": rec,
            "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
            "fpr": fp / (fp + tn) if fp + tn else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def best_threshold(y, score, w) -> dict:
    """Choose the operating point by NET BENEFIT, not F1.

    A missed failure costs 90 tower-minutes, a pre-emption 45, a false
    dispatch 35 minutes of crew time. F1 would ignore that asymmetry.
    """
    best = None
    for t in np.arange(0.05, 0.96, 0.01):
        m = metrics_at(y, score, w, float(t))
        m["net_benefit_min"] = (
            m["tp"] * (C.COST_FAILURE_MIN - C.COST_PREEMPT_MIN)
            - m["fp"] * C.COST_FALSE_DISPATCH_MIN)
        if best is None or m["net_benefit_min"] > best["net_benefit_min"]:
            best = m
    return best


def report(name: str, m: dict, auc: float) -> None:
    print(f"\n  {name}")
    print(f"      AUC-PR {auc:.3f}   precision {m['precision']:.3f}   "
          f"recall {m['recall']:.3f}   F1 {m['f1']:.3f}")
    print(f"      threshold {m['threshold']:.2f}   "
          f"net benefit {m['net_benefit_min']:,.0f} tower-min")


# --------------------------------------------------------------------------
def main() -> None:
    MODEL_DIR.mkdir(exist_ok=True)
    print("=" * 70)
    print("  THE ORACLE — will this node fail within 60 minutes?")
    print("=" * 70)

    Xtr, ytr, nk_tr = load("train")
    Xte, yte, nk_te = load("test")
    wte = weights_for(yte, nk_te)

    prev = float((yte == 1) @ wte / wte.sum())
    print(f"\n  train {len(Xtr):>7,} windows, {ytr.sum():>6,} positive")
    print(f"  test  {len(Xte):>7,} windows, {yte.sum():>6,} positive")
    print(f"  window: {SEQ_LEN} contiguous ticks = "
          f"{SEQ_LEN * C.TICK_MINUTES} simulated minutes")
    print(f"  channels: {len(CHANNELS)} raw telemetry, no engine features")
    print(f"  seeds: train 42, test 99")
    print(f"  natural prevalence after reweighting: {prev:.3%}")

    Ftr, Fte = flatten_lags(Xtr), flatten_lags(Xte)
    sc = StandardScaler().fit(Ftr)
    Ftr_s, Fte_s = sc.transform(Ftr), sc.transform(Fte)

    results: dict = {}

    # ---------------------------------------------------------- B0
    print("\n" + "-" * 70)
    print("  BASELINES")
    print("-" * 70)
    acc0 = float(((yte == 0) @ wte) / wte.sum())
    print(f"\n  B0  always predict 'no failure'")
    print(f"      accuracy {acc0:.4f}   recall 0.000")
    print(f"      Beats every honest model on accuracy. That is the point.")
    results["B0"] = {"accuracy": acc0, "recall": 0.0}

    # ---------------------------------------------------------- B1
    ci = {c: i for i, c in enumerate(CHANNELS)}
    t = np.arange(SEQ_LEN, dtype=np.float32)
    t -= t.mean()
    sl = lambda c: (Xte[:, :, ci[c]] * t[None, :]).sum(1) / (t ** 2).sum()
    rule = ((sl("temperature") > 0.30) | (sl("s11") > 0.10)
            | (sl("packet_loss") > 0.08) | (sl("cpu_load") > 0.80)
            | (sl("battery_pct") < -0.70)).astype(float)
    m1 = metrics_at(yte, rule, wte, 0.5)
    m1["net_benefit_min"] = (m1["tp"] * (C.COST_FAILURE_MIN - C.COST_PREEMPT_MIN)
                             - m1["fp"] * C.COST_FALSE_DISPATCH_MIN)
    auc1 = float(average_precision_score(yte, rule, sample_weight=wte))
    report("B1  hand-tuned trend thresholds", m1, auc1)
    results["B1"] = {**m1, "auc_pr": auc1}

    # ---------------------------------------------------------- B2
    lr = LogisticRegression(max_iter=1500, class_weight="balanced")
    lr.fit(Ftr_s, ytr)
    s2 = lr.predict_proba(Fte_s)[:, 1]
    m2 = best_threshold(yte, s2, wte)
    auc2 = float(average_precision_score(yte, s2, sample_weight=wte))
    report("B2  logistic regression on lag features", m2, auc2)
    results["B2"] = {**m2, "auc_pr": auc2}

    # ---------------------------------------------------------- B3
    pw = float((ytr == 0).sum() / max((ytr == 1).sum(), 1))
    xgb = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.06,
                        subsample=0.8, colsample_bytree=0.8,
                        scale_pos_weight=pw, objective="binary:logistic",
                        eval_metric="aucpr", tree_method="hist",
                        random_state=42, n_jobs=-1)
    xgb.fit(Ftr_s, ytr, verbose=False)
    s3 = xgb.predict_proba(Fte_s)[:, 1]
    m3 = best_threshold(yte, s3, wte)
    auc3 = float(average_precision_score(yte, s3, sample_weight=wte))
    report("B3  XGBoost on lag features  <-- the one to beat", m3, auc3)
    results["B3"] = {**m3, "auc_pr": auc3,
                     "brier": float(brier_score_loss(yte, s3, sample_weight=wte))}

    # ---------------------------------------------------------- GRU
    print("\n" + "-" * 70)
    print("  DEEP LEARNING")
    print("-" * 70)
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        print("\n  PyTorch not installed. pip install torch, then re-run.")
        _save(results, None)
        return

    torch.manual_seed(42)
    np.random.seed(42)

    # normalise per channel using TRAIN statistics only
    mu = Xtr.reshape(-1, Xtr.shape[2]).mean(0)
    sd = Xtr.reshape(-1, Xtr.shape[2]).std(0) + 1e-6
    Xtr_n = ((Xtr - mu) / sd).astype(np.float32)
    Xte_n = ((Xte - mu) / sd).astype(np.float32)

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = GRUNet(len(CHANNELS)).to(dev)
    npar = sum(p.numel() for p in net.parameters())
    print(f"\n  GRU: 1 layer, 64 hidden, {npar:,} parameters, {dev}")

    yt = torch.tensor(ytr, dtype=torch.float32)
    lossf = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([pw], dtype=torch.float32, device=dev))
    opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-5)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=12)

    idx = np.arange(len(Xtr_n))
    bs = 1024
    for epoch in range(12):
        net.train()
        np.random.shuffle(idx)
        tot = 0.0
        for k in range(0, len(idx), bs):
            b = idx[k:k + bs]
            xb = torch.from_numpy(Xtr_n[b]).to(dev)
            yb = yt[b].to(dev)
            opt.zero_grad()
            loss = lossf(net(xb), yb)
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            tot += float(loss.detach()) * len(b)
        sched.step()
        if epoch % 3 == 0 or epoch == 11:
            print(f"    epoch {epoch:2}  loss {tot / len(idx):.4f}")

    net.eval()
    outs = []
    with torch.no_grad():
        for k in range(0, len(Xte_n), 8192):
            xb = torch.from_numpy(Xte_n[k:k + 8192]).to(dev)
            outs.append(torch.sigmoid(net(xb)).cpu().numpy())
    sg = np.concatenate(outs)

    mg = best_threshold(yte, sg, wte)
    aucg = float(average_precision_score(yte, sg, sample_weight=wte))
    report("M   GRU on raw contiguous sequences", mg, aucg)
    results["M_gru"] = {**mg, "auc_pr": aucg, "parameters": npar,
                        "brier": float(brier_score_loss(yte, sg, sample_weight=wte))}

    _verdict(results["B3"], results["M_gru"])
    _save(results, net if aucg > auc3 else None, mu, sd)


def _verdict(b3: dict, gru: dict) -> None:
    print("\n" + "=" * 70)
    print("  VERDICT — was deep learning worth it?")
    print("=" * 70)
    print(f"\n  {'model':32} {'AUC-PR':>8} {'prec':>7} {'recall':>8} {'F1':>7}")
    print(f"  {'B3 XGBoost on lag features':32} {b3['auc_pr']:8.3f} "
          f"{b3['precision']:7.3f} {b3['recall']:8.3f} {b3['f1']:7.3f}")
    print(f"  {'M  GRU on raw sequence':32} {gru['auc_pr']:8.3f} "
          f"{gru['precision']:7.3f} {gru['recall']:8.3f} {gru['f1']:7.3f}")

    lift = (gru["auc_pr"] - b3["auc_pr"]) / max(b3["auc_pr"], 1e-9)
    print(f"\n  AUC-PR lift from deep learning: {lift:+.1%}")
    print(f"  parameters: GRU {gru['parameters']:,} vs XGBoost ~400 trees")
    if lift > 0.05:
        print("\n  -> The GRU earns its place. Raw sequence carries structure")
        print("     that hand-crafted lag features do not capture.")
    elif lift > -0.05:
        print("\n  -> Statistically indistinguishable. SHIP XGBOOST: equal")
        print("     accuracy, far fewer parameters, no torch dependency,")
        print("     and it is interpretable. Choosing the simpler model when")
        print("     it ties is the engineering answer.")
    else:
        print("\n  -> XGBoost wins outright. Deep learning is NOT justified")
        print("     for this problem. Reporting that is a result, not a")
        print("     failure — and it is the honest one.")


def _save(results: dict, net, mu=None, sd=None) -> None:
    (MODEL_DIR / "oracle_metrics.json").write_text(
        json.dumps({"horizon_min": 60, "seq_len": SEQ_LEN,
                    "channels": list(CHANNELS),
                    "break_even_precision": C.BREAK_EVEN_PRECISION,
                    "results": results}, indent=2, default=float))
    if net is not None:
        import torch
        torch.save(net.state_dict(), MODEL_DIR / "oracle_gru.pt")
        # per-channel normalisation statistics from TRAIN ONLY — the live
        # serving layer needs exactly the same transform the model saw
        np.savez(MODEL_DIR / "oracle_stats.npz", mu=mu, sd=sd)
        print(f"\n  saved -> {MODEL_DIR}/oracle_gru.pt")
        print(f"  saved -> {MODEL_DIR}/oracle_stats.npz (train mu/sd)")
    print(f"  saved -> {MODEL_DIR}/oracle_metrics.json")


if __name__ == "__main__":
    main()
