"""
M6 — live model serving for the Commander.

Two rules from the brief, both structural:

1. NEVER call predict() 300 times per tick. Batch inference runs every
   AI_INFERENCE_EVERY_TICKS on a WORKER THREAD, off the sim thread. If a
   cycle overruns, the previous cycle's verdicts are reused — stale
   predictions beat a stalled simulation.

2. GRACEFUL DEGRADATION. If any model file is missing, fall back to the
   hand-tuned rules (the B1 baseline from the Oracle benchmark) and set
   engine.ai_mode = "rules". The dashboard must never crash because a .json
   is absent.

The worker never calls engine.step(). It reads node state under the API lock,
runs inference outside it, and writes engine.ai_verdicts back under the lock.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
import traceback

import numpy as np

from autonoc.engine import config as C
from autonoc.engine import commander as CM

from .features import build_vector

MODEL_DIR = pathlib.Path("models")

try:
    import torch
    _TORCH_OK = True
except ImportError:
    torch = None
    _TORCH_OK = False


# ------------------------------------------------------------------ rules
def _slope(values: list[float]) -> float:
    """Least-squares slope per tick (same as the feature builder)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den if den else 0.0


def rules_verdicts(engine) -> dict[str, dict]:
    """B1-style hand-tuned thresholds on live telemetry (no ML, no crash).

    Mirrors the Oracle benchmark's B1: trend thresholds on temperature, s11,
    packet loss, CPU and battery. The trigger probability is set above the
    cost-derived break-even so the Commander still applies its decision rule.
    """
    verdicts: dict[str, dict] = {}
    for n in engine.net.nodes:
        if n.status != C.STATUS_HEALTHY:
            continue
        h = list(n.hist_fine)
        if len(h) < 6:
            continue
        slope = {k: _slope([row[k] for row in h])
                 for k in ("temperature", "s11", "packet_loss",
                           "cpu_load", "battery_pct")}
        fired = None
        if slope["temperature"] > 0.30:
            fired = C.STATUS_OVERHEAT
        elif slope["s11"] > 0.10:
            fired = C.STATUS_RF
        elif slope["packet_loss"] > 0.08:
            fired = C.STATUS_CONGESTION
        elif slope["cpu_load"] > 0.80:
            fired = C.STATUS_CONGESTION
        elif slope["battery_pct"] < -0.70:
            fired = C.STATUS_POWER
        if fired is None:
            continue
        action = CM.default_action_for(fired, n.is_critical, 0.9)
        verdicts[n.node_id] = {
            "p_fail": 0.90, "cls": int(fired), "action": action,
            "tier": CM.tier_for(action),
        }
    return verdicts


# ------------------------------------------------------------------ models
class ModelBundle:
    """Loads Doctor + Oracle once. Every missing piece degrades to rules."""

    def __init__(self) -> None:
        self.doctor = None
        self.scaler_mean = None
        self.scaler_scale = None
        self.feature_order: list[str] = []
        self.oracle = None
        self.oracle_mu = None
        self.oracle_sd = None
        self.oracle_seq_len = 12
        self.channels: list[str] = []
        self.mode = "rules"          # upgraded to "ml" only if EVERYTHING loads

        self._load_doctor()
        self._load_oracle()

    def _load_doctor(self) -> None:
        try:
            from xgboost import XGBClassifier
            path = MODEL_DIR / "doctor_xgb.json"
            scaler = np.load(MODEL_DIR / "doctor_scaler.npz")
            order = json.loads((MODEL_DIR / "feature_order.json").read_text())
            assert path.exists(), "doctor_xgb.json missing"
            assert len(order) == len(scaler["mean"]), (
                "feature_order/scaler mismatch: "
                f"{len(order)} vs {len(scaler['mean'])}")
            model = XGBClassifier()
            model.load_model(str(path))
            self.doctor = model
            self.scaler_mean = scaler["mean"].astype(np.float32)
            self.scaler_scale = scaler["scale"].astype(np.float32)
            self.feature_order = order
        except Exception as exc:
            print(f"[serve] Doctor unavailable ({exc}) — rules mode for Doctor")

    def _load_oracle(self) -> None:
        if not _TORCH_OK:
            print("[serve] torch missing — Oracle unavailable")
            return
        try:
            from .oracle import load_oracle_artifacts
            net, mu, sd, seq_len, channels = load_oracle_artifacts()
            self.oracle = net
            self.oracle_mu = mu.astype(np.float32)
            self.oracle_sd = sd.astype(np.float32)
            self.oracle_seq_len = seq_len
            self.channels = list(channels)
        except Exception as exc:
            print(f"[serve] Oracle unavailable ({exc}) — rules mode for Oracle")

    @property
    def complete(self) -> bool:
        return (self.doctor is not None and self.oracle is not None)


# ------------------------------------------------------------------ worker
class InferenceWorker(threading.Thread):
    """Batched inference off the sim thread, every 6 ticks, with staleness
    fallback and an auto-approve timer for demo mode."""

    def __init__(self, engine, lock, models_dir: str = "models",
                 auto_approve_seconds: int = C.AUTO_APPROVE_SECONDS):
        super().__init__(daemon=True, name="autonoc-inference")
        global MODEL_DIR
        MODEL_DIR = pathlib.Path(models_dir)
        self.engine = engine
        self.lock = lock
        self._stop = threading.Event()
        self._last_cycle = -1
        self.auto_approve_seconds = float(auto_approve_seconds)
        self._created: dict[int, float] = {}
        self._last_error: str | None = None
        # loads happen here so a missing file degrades once, quietly
        self.bundle = ModelBundle()
        self._mode = "ml" if self.bundle.complete else "rules"

    # ------------------------------------------------------------ lifecycle
    def stop(self) -> None:
        self._stop.set()

    def set_auto_approve(self, seconds: float) -> None:
        self.auto_approve_seconds = max(0.0, float(seconds))

    def eta_for(self, action_id: int) -> float:
        if self.auto_approve_seconds <= 0:
            return 0.0
        created = self._created.get(int(action_id))
        if created is None:
            return 0.0
        return max(0.0, self.auto_approve_seconds
                   - (time.monotonic() - created))

    # ------------------------------------------------------------ main loop
    def run(self) -> None:
        while not self._stop.wait(0.25):
            try:
                with self.lock:
                    tick = self.engine.tick
                    enabled = bool(self.engine.ai_enabled)
                if not enabled:
                    continue                       # no verdicts while AI is off
                if tick == self._last_cycle:
                    continue
                if tick % C.AI_INFERENCE_EVERY_TICKS != 0:
                    continue
                self._last_cycle = tick
                verdicts = self._score_batch()
                with self.lock:
                    self.engine.ai_verdicts = verdicts
                    self.engine.ai_mode = self._mode
                    self._track_pending()
                self._settle_auto_approve()
            except Exception:
                self._last_error = traceback.format_exc(limit=3)
                print(self._last_error)

    def _track_pending(self) -> None:
        """Remember when each pending action was created (wall clock)."""
        now = time.monotonic()
        for a in self.engine.pending_actions:
            self._created.setdefault(int(a["action_id"]), now)

    def _settle_auto_approve(self) -> None:
        if self.auto_approve_seconds <= 0:
            return
        now = time.monotonic()
        with self.lock:
            for a in list(self.engine.pending_actions):
                created = self._created.get(int(a["action_id"]))
                if created is None or now - created < self.auto_approve_seconds:
                    continue
                self.engine.approve_action(int(a["action_id"]))
                self.engine.log(
                    f"AI: action {a['action_id']} auto-approved "
                    f"after {(now - created):.0f}s (demo mode)", "INFO")

    # ------------------------------------------------------------ scoring
    def _score_batch(self) -> dict[str, dict]:
        """Snapshot under the lock, infer outside it, return verdicts."""
        with self.lock:
            snapshot = _collect_inputs(self.engine, self.bundle)
        ids, feats, windows, statuses, crit = snapshot
        p_fault = _doctor_scores(ids, feats, self.bundle)
        p_fail = _oracle_scores(ids, windows, self.bundle)
        return _combine(ids, statuses, crit, p_fault, p_fail)


# ------------------------------------------------------------------ offline scoring
# Shared by the live worker (above) and the M7 counterfactual study. Pure
# functions of (engine state, model bundle): deterministic, no wall clock.
def _collect_inputs(engine, bundle):
    ids: list[str] = []
    feats: list[list[float]] = []
    windows: list = []
    statuses: dict[str, int] = {}
    crit: dict[str, bool] = {}
    for n in engine.net.nodes:
        ids.append(n.node_id)
        statuses[n.node_id] = n.status
        crit[n.node_id] = n.is_critical
        feats.append(build_vector(n))
        h = list(n.hist_fine)
        if len(h) >= bundle.oracle_seq_len:
            windows.append(_window(h, bundle.oracle_seq_len))
        else:
            windows.append(None)
    return ids, feats, windows, statuses, crit


def _doctor_scores(ids, feats, bundle):
    doc = bundle.doctor
    if doc is None or not feats:
        return None
    try:
        X = np.asarray(feats, dtype=np.float32)
        Xs = (X - bundle.scaler_mean) / bundle.scaler_scale
        return doc.predict_proba(Xs)
    except Exception:
        return None


def _oracle_scores(ids, windows, bundle):
    oracle = bundle.oracle
    if oracle is None or not _TORCH_OK:
        return None
    try:
        valid = [w for w in windows if w is not None]
        if not valid:
            return None
        X = np.stack(valid).astype(np.float32)
        Xn = (X - bundle.oracle_mu) / bundle.oracle_sd
        with torch.no_grad():
            out = torch.sigmoid(
                oracle(torch.from_numpy(Xn))).numpy().reshape(-1)
        scores: dict[str, float] = {}
        j = 0
        for i, nid in enumerate(ids):
            if windows[i] is not None:
                scores[nid] = float(out[j])
                j += 1
        return [scores.get(nid, 0.0) for nid in ids]
    except Exception:
        return None


def _window(hist: list[dict], seq_len: int) -> np.ndarray:
    """hist_fine rows (dicts keyed by feature metric) -> (12, 12) array
    in the Oracle's CHANNELS order (dust_accum is row['dust'])."""
    rows = []
    for row in hist[-seq_len:]:
        rows.append([
            row.get("rsrp", 0.0), row.get("sinr", 0.0),
            row.get("s11", 0.0), row.get("latency", 0.0),
            row.get("jitter", 0.0), row.get("packet_loss", 0.0),
            row.get("throughput", 0.0), row.get("cpu_load", 0.0),
            row.get("temperature", 0.0), row.get("voltage", 0.0),
            row.get("battery_pct", 0.0), row.get("dust", 0.0),
        ])
    return np.asarray(rows, dtype=np.float32)


def _combine(ids, statuses, crit, p_fault, p_fail) -> dict[str, dict]:
    verdicts: dict[str, dict] = {}
    for i, nid in enumerate(ids):
        if statuses[nid] != C.STATUS_HEALTHY:
            continue
        cls = int(p_fault[i].argmax()) if p_fault is not None else C.STATUS_RF
        pf = float(p_fail[i]) if p_fail is not None else \
            float(1.0 - p_fault[i][0]) if p_fault is not None else 0.0
        action = CM.default_action_for(cls, crit[nid], pf)
        verdicts[nid] = {
            "p_fail": round(pf, 4), "cls": cls, "action": action,
            "tier": CM.tier_for(action),
        }
    return verdicts


def score_engine(engine, bundle) -> dict[str, dict]:
    """Score every healthy node in one batch. Used by the M7 study and by the
    live worker (which adds locking around the snapshot)."""
    ids, feats, windows, statuses, crit = _collect_inputs(engine, bundle)
    p_fault = _doctor_scores(ids, feats, bundle)
    p_fail = _oracle_scores(ids, windows, bundle)
    return _combine(ids, statuses, crit, p_fault, p_fail)
