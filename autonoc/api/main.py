"""
FastAPI layer.

THREE v1 bugs are structurally impossible here:

1. GET no longer mutates state. v1's `/api/delta` advanced the simulation as a
   side effect, so two browser tabs ran the sim at 2x speed and closing the
   browser stopped time entirely.

2. Time is owned by a server clock in a lifespan task, not by the request
   path. v1 moved the tick into the handler and called it an optimisation;
   the work did not disappear, it just landed on the client's latency path.

3. The legacy tick-cursor endpoint sends bounded full snapshots (resync=True).
   Physical changes, same-tick controls and warning flips reach every reader;
   no global dirty flags are consumed by GET requests.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine

from . import presentation as P
from . import schemas as S
from .run_history import RunSummaryStore

BASE_TICK_SECONDS = 1.0
RUN_DAYS = 30
RUN_TICKS = C.TICKS_PER_DAY * RUN_DAYS

# M8 — demo support. The "Storm over Goizha" demo runs a cast seed:
#   $env:AUTONOC_SEED=131; python -m uvicorn autonoc.api.main:app
# AUTONOC_AI=1 auto-enables the Commander at boot for a hands-free demo.
_DEFAULT_SEED = int(os.environ.get("AUTONOC_SEED", "42"))
_DEFAULT_AI = os.environ.get("AUTONOC_AI", "0") == "1"
_DEFAULT_AUTO_APPROVE = float(os.environ.get("AUTONOC_AUTO_APPROVE", "0"))

engine = NOCEngine(seed=_DEFAULT_SEED, ai_enabled=_DEFAULT_AI,
                   horizon=RUN_TICKS)
_lock = threading.Lock()
_speed = 1.0
_slow_ticks = 0

# M6 — live inference worker. Created in lifespan (needs the engine + lock);
# None until then so module import never starts threads.
worker = None

# The identifier changes on every successful Day 30 reset and on process
# start. Every browser control is bound to the identifier it was rendered for.
_run_id = uuid.uuid4().hex
_reset_notice = False
_run_error: str | None = None
_history = P.History()
_history.reset(engine)
_summary_store = RunSummaryStore()


def _assert_current_run(run_id: str) -> None:
    """Reject commands created against a world that has already been reset."""
    if run_id != _run_id:
        raise HTTPException(
            status_code=409,
            detail="This control belongs to an earlier demo. Refresh the dashboard and try again.",
        )


def _run_summary(source) -> dict:
    """Capture aggregate results only; no simulation state is checkpointed."""
    kpis = source.kpis()
    ai = source.ai_payload()
    return {
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "simulated_days": RUN_DAYS,
        "completed_sim_time": source.sim_time,
        "seed": source.seed,
        "availability": kpis["availability"],
        "injected": kpis["injected"],
        "masked": kpis["masked"],
        "repairs": kpis["repairs"],
        "mttr_min": kpis["mttr_min"],
        "ats_failures": kpis["ats_failures"],
        "fuel_thefts": kpis["fuel_thefts"],
        "active_incidents": len(P.incidents(source)),
        "ai_enabled": bool(source.ai_enabled),
        "ai_mode": source.ai_mode,
        "pre_empted": int(ai["pre_empted"]),
        "acted_upon": int(ai["acted_upon"]),
        "false_dispatches": int(ai["false_dispatches"]),
        "crew_hours_saved": float(ai["crew_hours_saved"]),
        "precision": ai["precision"],
    }


def _new_engine_like(source, paused: bool):
    """Build the next deterministic world without mutating the current one."""
    fresh = NOCEngine(
        seed=source.seed,
        ai_enabled=source.ai_enabled,
        horizon=source.horizon,
    )
    fresh.ai_policy = source.ai_policy
    fresh.ai_mode = source.ai_mode
    fresh.paused = paused
    return fresh


def _reset_completed_run_locked() -> bool:
    """Atomically persist the summary and replace a completed world.

    The caller owns `_lock`. Candidate initialization and durable summary save
    both happen before publishing the candidate. Any exception leaves the
    completed world untouched except that it is paused and reports the error.
    """
    global engine, _run_id, _reset_notice, _run_error
    previous = engine
    previous_run_id = _run_id
    keep_paused = previous.paused
    try:
        summary = _run_summary(previous)
        candidate = _new_engine_like(previous, paused=keep_paused)
        candidate_initial_sample = P.sample(candidate)
        _summary_store.save(previous_run_id, summary)
        next_run_id = uuid.uuid4().hex
    except Exception as exc:
        previous.paused = True
        detail = str(exc).strip() or type(exc).__name__
        _run_error = (
            "Demo restart failed. The completed world was preserved and paused. "
            f"{detail[:300]}"
        )
        return False

    # The worker snapshots the engine and run id together under the same lock;
    # results produced from the previous world are rejected when it resumes.
    if worker is not None:
        worker.replace_engine(candidate, next_run_id)
    engine = candidate
    _run_id = next_run_id
    _history.reset(candidate, candidate_initial_sample)
    _reset_notice = True
    _run_error = None
    return True


def _step_locked(automatic: bool = True, expected_run_id: str | None = None) -> dict:
    """Advance one server tick, or safely complete/reset at the run boundary."""
    global _slow_ticks
    t0 = time.perf_counter()
    with _lock:
        if expected_run_id is not None:
            _assert_current_run(expected_run_id)
        if automatic and engine.paused:
            return {"advanced": False, "tick": engine.tick, "run_id": _run_id}
        if not automatic and not engine.paused:
            raise HTTPException(status_code=409, detail="Pause the simulation before stepping.")

        # tick 8639 is D30 23:55. The next 5-minute transition would display
        # Day 31, so complete the 30-day summary and reset instead of exposing
        # a Day 31 frame. A paused/manual step takes this same path and stays
        # paused in the new world.
        if engine.tick >= engine.horizon - 1:
            reset = _reset_completed_run_locked()
            result = {
                "advanced": False,
                "reset": reset,
                "tick": engine.tick,
                "run_id": _run_id,
                "paused": engine.paused,
                "error": _run_error,
            }
        else:
            engine.step()
            _history.record(engine)
            result = {"advanced": True, "tick": engine.tick, "run_id": _run_id}

    dt = (time.perf_counter() - t0) * 1000
    if dt > 100.0:
        _slow_ticks += 1
    return result


async def simulation_loop() -> None:
    """The ONLY place engine.step() is called during normal operation."""
    while True:
        try:
            # `_step_locked` rechecks Pause after acquiring the engine lock, so
            # a racing pause cannot permit a boundary reset behind the user.
            await asyncio.to_thread(_step_locked, True)
        except asyncio.CancelledError:
            raise
        except Exception:                      # never let the clock die
            import traceback
            traceback.print_exc()
        with _lock:
            interval = BASE_TICK_SECONDS / max(_speed, 0.1)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker
    task = asyncio.create_task(simulation_loop())
    from autonoc.ai.serve import InferenceWorker
    worker = InferenceWorker(engine, _lock,
                             auto_approve_seconds=_DEFAULT_AUTO_APPROVE,
                             run_id=_run_id)
    worker.start()
    yield
    worker.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="AutoNOC", version="3.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


@app.middleware("http")
async def no_cache_dashboard(request, call_next):
    """The dashboard must NEVER be cached.

    A stale cached index.html/app.js was the root cause of the long-running
    "page loads but everything is empty" bug: the browser kept resurrecting
    an old frontend even after the backend was fixed. HTML and API responses
    are served with Cache-Control: no-store. Legacy assets revalidate; the
    Vite assets have content hashes and can safely be cached immutably.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    else:
        response.headers["Cache-Control"] = "no-store"
    return response


# ------------------------------------------------------------------ config
@app.get("/api/config", response_model=S.ConfigResponse)
async def get_config():
    """Everything the frontend needs to render. It hard-codes none of it."""
    return S.ConfigResponse(
        status_names=C.STATUS_NAMES,
        status_colors=C.STATUS_COLORS,
        thresholds={
            "rsrp": C.THRESH_RSRP, "s11": C.THRESH_S11,
            "s11_high_wind": C.THRESH_S11_HIGH_WIND, "temp": C.THRESH_TEMP,
            "packet_loss": C.THRESH_PACKET_LOSS, "cpu": C.THRESH_CPU,
        },
        metric_labels=dict(C.METRIC_LABELS),
        gauges={k: dict(v) for k, v in C.GAUGE_SPECS.items()},
        x733_severity=dict(C.X733_SEVERITY),
        power_configs=dict(C.POWER_CONFIG_NAMES),
        vswr_alarm=C.VSWR_ALARM_THRESHOLD,
        rapp_roles=dict(C.RAPP_ROLES),
        map_center=[(C.LAT_MIN + C.LAT_MAX) / 2, (C.LON_MIN + C.LON_MAX) / 2],
        map_zoom=12,
        bounds={"lat_min": C.LAT_MIN, "lat_max": C.LAT_MAX,
                "lon_min": C.LON_MIN, "lon_max": C.LON_MAX},
        epc_primary={"name": C.EPC_PRIMARY[0], "lat": C.EPC_PRIMARY[1],
                     "lon": C.EPC_PRIMARY[2], "backhaul": C.EPC_PRIMARY[3]},
        epc_backup={"name": C.EPC_BACKUP[0], "lat": C.EPC_BACKUP[1],
                    "lon": C.EPC_BACKUP[2], "backhaul": C.EPC_BACKUP[3]},
        depot={"lat": C.DEPOT_LAT, "lon": C.DEPOT_LON},
        agg_sites=[{"id": s[0], "name": s[1], "lat": s[2], "lon": s[3],
                    "nodes": len(engine.net.agg_sites[s[0]].node_ids), "clutter": s[5], "color": s[6]}
                   for s in C.AGG_SITES],
        num_nodes=C.NUM_NODES,
        num_teams=C.NUM_TEAMS,
        tick_minutes=C.TICK_MINUTES,
        break_even_precision=round(C.BREAK_EVEN_PRECISION, 4),
        presentation=P.config_payload(),
    )


# ------------------------------------------------------------------ data
def _agg_payload() -> list[dict]:
    out = []
    w_now = engine.weather_timeline[min(engine.tick, engine.horizon - 1)]
    for site in engine.net.agg_sites:
        nodes = [engine.net.by_id[i] for i in site.node_ids]
        ok = sum(1 for n in nodes if n.status == C.STATUS_HEALTHY)
        w = w_now[site.agg_id]
        out.append({
            "id": site.agg_id, "name": site.name, "lat": site.lat,
            "lon": site.lon, "color": site.color, "node_count": len(nodes),
            "health": round(ok / len(nodes) * 100.0, 1) if nodes else 100.0,
            "weather": w["type"], "wind": round(w["wind"], 1),
            "clutter": site.clutter_c,
            # every node in a district shares its grid tier, so the site
            # power architecture (A/B/C) is a district-level label
            "pwr": C.POWER_CONFIG_BY_TIER[C.GRID_TIER[site.agg_id]],
        })
    return out


def _node_dicts(only_changed_since: int | None = None) -> list[dict]:
    """Complete current node readouts, independent of who polled before us.

    Physical telemetry changes each tick without last_changed_tick updates.
    For 300 nodes, bounded snapshots are safer than a lossy dirty-flag delta.
    This also delivers warning flips and controls performed while paused.
    """
    out = []
    for n in engine.nodes:
        v = engine.ai_verdicts.get(n.node_id) if engine.ai_enabled else None
        warn = bool(v and n.status == C.STATUS_HEALTHY
                    and float(v.get("p_fail", 0.0)) > C.BREAK_EVEN_PRECISION)
        out.append({**n.to_dict(), "warn": warn})
    return out


def _ring_payload() -> list[dict]:
    out = []
    for ring in engine.net.rings:
        path = [[s.from_lat, s.from_lon] for s in ring.segments]
        if ring.segments:
            path.append([ring.segments[-1].to_lat, ring.segments[-1].to_lon])
        cut = None
        if ring.cuts:
            c = ring.cuts[0]
            cut = {"lat": c.lat, "lon": c.lon, "seg": c.segment.seg_id,
                   "cause": c.cause}
        out.append({"id": ring.ring_id, "nodes": ring.node_ids, "path": path,
                    "circumference_km": round(ring.circumference_km, 2),
                    "cut": cut, "isolated": ring.is_isolated,
                    "cuts": [{"lat": c.lat, "lon": c.lon,
                              "seg": c.segment.seg_id, "cause": c.cause,
                              "path": [[c.segment.from_lat, c.segment.from_lon],
                                       [c.segment.to_lat, c.segment.to_lon]]}
                             for c in ring.cuts]})
    return out


def _ai_payload() -> dict:
    """M6 — Commander panel, enriched with live auto-approve countdowns."""
    p = engine.ai_payload()
    if worker is not None:
        p["pending"] = [{**a, "eta": worker.eta_for(a["action_id"])}
                        for a in p["pending"]]
    return p


def _snapshot(resync: bool) -> dict:
    return {
        "tick": engine.tick, "resync": resync, "kpis": engine.kpis(),
        "run_id": _run_id, "reset_notice": _reset_notice,
        "run_error": _run_error,
        "control": {"paused": engine.paused, "speed": _speed, "seed": engine.seed,
                    "auto_approve_seconds": worker.auto_approve_seconds if worker else 0},
        "dashboard": P.dashboard(engine, _history),
        "agg": _agg_payload(),
        "nodes": _node_dicts(),
        "teams": [t.to_dict() for t in engine.teams],
        "logs": list(engine.logs)[-60:],
        "rings": _ring_payload(),
        "ai": _ai_payload(),
    }


@app.get("/api/data", response_model=S.DeltaResponse)
async def get_full():
    with _lock:
        return _snapshot(resync=True)


@app.get("/api/delta", response_model=S.DeltaResponse)
async def get_delta(since: int = Query(0, ge=0)):
    """Read-only, replay-safe bounded snapshot at the existing delta endpoint.

    The legacy tick cursor is retained. Nodes/teams/logs are complete bounded
    readouts, so paused same-tick mutations and dropped polls are never lost.
    No request changes delivery state for another client.
    """
    with _lock:
        # Always mark complete snapshots so legacy consumers replace logs too.
        return _snapshot(resync=True)


@app.get("/api/telemetry/history", response_model=S.TelemetryHistoryResponse)
async def telemetry_history(
    timeframe: Literal["30m", "24h", "7d"] = Query("30m"),
    run_id: str = Query(..., min_length=1),
):
    """Read actual samples from the current simulation run, never a forecast.

    30m/24h/7d refer to simulated network time. Samples are emitted at the
    engine's five-minute tick resolution; a newly reset world therefore fills
    longer windows as simulated time elapses.
    """
    minutes = {"30m": 30, "24h": 24 * 60, "7d": 7 * 24 * 60}[timeframe]
    sample_count = minutes // C.TICK_MINUTES + 1
    with _lock:
        _assert_current_run(run_id)
        current = P.sample(engine)
        return {
            "run_id": _run_id,
            "timeframe": timeframe,
            "tick_minutes": C.TICK_MINUTES,
            "samples": _history.read_window(engine, current, sample_count),
        }


@app.get("/api/history", response_model=S.RunHistoryResponse)
async def run_history():
    """Recent durable completion summaries, not resumable simulation state."""
    try:
        return {"summaries": _summary_store.recent()}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Run history is unavailable: {str(exc).strip() or type(exc).__name__}",
        ) from exc


@app.get("/api/health")
async def health():
    with _lock:
        return {"status": "ok", "tick": engine.tick, "paused": engine.paused,
                "speed": _speed, "slow_ticks": _slow_ticks,
                "seed": engine.seed, "run_id": _run_id,
                "run_error": _run_error, "ai_enabled": engine.ai_enabled,
                "ai_policy": engine.ai_policy}


# ------------------------------------------------------------------ control
@app.post("/api/control/pause")
async def pause(run_id: str = Query(..., min_length=1)):
    with _lock:
        _assert_current_run(run_id)
        engine.paused = True
    return {"paused": True, "run_id": run_id}


@app.post("/api/control/resume")
async def resume(run_id: str = Query(..., min_length=1)):
    with _lock:
        _assert_current_run(run_id)
        engine.paused = False
    return {"paused": False, "run_id": run_id}


@app.post("/api/control/step")
async def step_once(run_id: str = Query(..., min_length=1)):
    return await asyncio.to_thread(_step_locked, False, run_id)


@app.post("/api/control/speed")
async def set_speed(
    value: float = Query(1.0, ge=0.25, le=10.0),
    run_id: str = Query(..., min_length=1),
):
    global _speed
    with _lock:
        _assert_current_run(run_id)
        _speed = value
        return {"speed": _speed, "run_id": run_id}


@app.post("/api/control/inject")
async def inject(
    node_id: str,
    kind: int = Query(3, ge=1, le=5),
    run_id: str = Query(..., min_length=1),
):
    from autonoc.engine import faults as F
    with _lock:
        _assert_current_run(run_id)
        node = engine.net.by_id.get(node_id)
        if node is None:
            raise HTTPException(404, f"unknown node {node_id}")
        if node.is_faulty:
            raise HTTPException(409, f"{node_id} already faulty")
        node.status = kind
        node.status_timer = 0
        node.fault_started_tick = engine.tick
        node.last_changed_tick = engine.tick
        F.apply_degradation(node, kind, 1.0, 1.0, engine.noise)
        # ITU-T X.733 perceived severity for the injected fault class
        engine.log(f"MANUAL: {node_id} — {C.STATUS_NAMES[kind]} injected",
                   C.X733_SEVERITY.get(kind, "MAJOR"), node_id)
    return {"ok": True, "node": node_id, "status": kind}


@app.post("/api/control/cut-fiber")
async def cut_fiber(
    ring_id: int = Query(0, ge=0, le=20),
    isolate: bool = Query(True),
    cause: str = Query("construction", pattern="^(construction|storm|equipment)$"),
    run_id: str = Query(..., min_length=1),
):
    """Trigger the Act 3 scenario: a double cut isolates a whole ring."""
    with _lock:
        _assert_current_run(run_id)
        return engine.cut_fiber(ring_id, isolate=isolate, cause=cause)


# ------------------------------------------------------------------ commander (M6)
@app.post("/api/control/ai")
async def set_ai(
    enabled: bool = Query(True),
    auto_approve_seconds: float = Query(C.AUTO_APPROVE_SECONDS, ge=0, le=600),
    run_id: str = Query(..., min_length=1),
):
    """Toggle the Commander and (for demos) auto-approve-after-N-seconds."""
    with _lock:
        _assert_current_run(run_id)
        engine.ai_enabled = enabled
        if not enabled:
            engine.ai_verdicts = {}
            engine.ai_mode = "off"
        if worker is not None:
            worker.set_auto_approve(auto_approve_seconds)
    return {"ai_enabled": enabled, "auto_approve_seconds": auto_approve_seconds}


@app.post("/api/control/approve/{action_id}")
async def approve(action_id: int, run_id: str = Query(..., min_length=1)):
    with _lock:
        _assert_current_run(run_id)
        return engine.approve_action(action_id)


@app.post("/api/control/veto/{action_id}")
async def veto(action_id: int, run_id: str = Query(..., min_length=1)):
    with _lock:
        _assert_current_run(run_id)
        return engine.veto_action(action_id)


# ------------------------------------------------------------------ static
# Absolute paths work under both Uvicorn and the multi-stage Docker image.
_WEB = Path(__file__).resolve().parents[1] / "web"
_DIST = _WEB / "dist"
app.mount("/static", StaticFiles(directory=str(_WEB)), name="static")
app.mount("/assets", StaticFiles(directory=str(_DIST / "assets"), check_dir=False), name="assets")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    path = _DIST / "favicon.svg"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/")
async def index():
    built = _DIST / "index.html"
    return FileResponse(built if built.exists() else _WEB / "index.html")
