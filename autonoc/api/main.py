"""
FastAPI layer.

THREE v1 bugs are structurally impossible here:

1. GET no longer mutates state. v1's `/api/delta` advanced the simulation as a
   side effect, so two browser tabs ran the sim at 2x speed and closing the
   browser stopped time entirely.

2. Time is owned by a server clock in a lifespan task, not by the request
   path. v1 moved the tick into the handler and called it an optimisation;
   the work did not disappear, it just landed on the client's latency path.

3. Deltas use a tick cursor, not dirty flags. With flags, one dropped poll
   loses that update forever and the client silently desyncs.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine

from . import schemas as S

BASE_TICK_SECONDS = 1.0

# M8 — demo support. The "Storm over Goizha" demo runs a cast seed:
#   $env:AUTONOC_SEED=131; python -m uvicorn autonoc.api.main:app
# AUTONOC_AI=1 auto-enables the Commander at boot for a hands-free demo.
_DEFAULT_SEED = int(os.environ.get("AUTONOC_SEED", "42"))
_DEFAULT_AI = os.environ.get("AUTONOC_AI", "0") == "1"
_DEFAULT_AUTO_APPROVE = float(os.environ.get("AUTONOC_AUTO_APPROVE", "0"))

engine = NOCEngine(seed=_DEFAULT_SEED, ai_enabled=_DEFAULT_AI,
                   horizon=C.TICKS_PER_DAY * 30)
_lock = threading.Lock()
_speed = 1.0
_slow_ticks = 0

# M6 — live inference worker. Created in lifespan (needs the engine + lock);
# None until then so module import never starts threads.
worker = None


def _step_locked() -> None:
    """Runs off the event loop thread; holds the lock while mutating."""
    global _slow_ticks
    t0 = time.perf_counter()
    with _lock:
        engine.step()
    dt = (time.perf_counter() - t0) * 1000
    if dt > 100.0:
        _slow_ticks += 1


async def simulation_loop() -> None:
    """The ONLY place engine.step() is called during normal operation."""
    while True:
        try:
            if not engine.paused:
                # off the event loop so a slow tick never stalls HTTP
                await asyncio.to_thread(_step_locked)
        except asyncio.CancelledError:
            raise
        except Exception:                      # never let the clock die
            import traceback
            traceback.print_exc()
        await asyncio.sleep(BASE_TICK_SECONDS / max(_speed, 0.1))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker
    task = asyncio.create_task(simulation_loop())
    from autonoc.ai.serve import InferenceWorker
    worker = InferenceWorker(engine, _lock,
                             auto_approve_seconds=_DEFAULT_AUTO_APPROVE)
    worker.start()
    yield
    worker.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="AutoNOC", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


@app.middleware("http")
async def no_cache_dashboard(request, call_next):
    """The dashboard must NEVER be cached.

    A stale cached index.html/app.js was the root cause of the long-running
    "page loads but everything is empty" bug: the browser kept resurrecting
    an old frontend even after the backend was fixed. HTML and API responses
    are served with Cache-Control: no-store; static assets with no-cache so
    the browser always revalidates.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/"):
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
                    "nodes": s[4], "clutter": s[5], "color": s[6]}
                   for s in C.AGG_SITES],
        num_nodes=C.NUM_NODES,
        num_teams=C.NUM_TEAMS,
        tick_minutes=C.TICK_MINUTES,
        break_even_precision=round(C.BREAK_EVEN_PRECISION, 4),
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
        })
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
                    "cut": cut})
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
        "agg": _agg_payload(),
        "nodes": [n.to_dict() for n in engine.nodes],
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
    """READ ONLY. Never advances the simulation.

    Idempotent: calling twice with the same cursor returns the same data.
    """
    with _lock:
        if since <= 0 or engine.tick - since > C.MAX_DELTA_LAG:
            return _snapshot(resync=True)
        return {
            "tick": engine.tick, "resync": False, "kpis": engine.kpis(),
            "agg": _agg_payload(),
            "nodes": [n.to_dict() for n in engine.nodes
                      if n.last_changed_tick > since],
            "teams": [t.to_dict() for t in engine.teams
                      if t.last_changed_tick > since],
            "logs": [l for l in engine.logs if l["tick"] > since][-60:],
            "rings": _ring_payload(),
            "ai": _ai_payload(),
        }


@app.get("/api/health")
async def health():
    return {"status": "ok", "tick": engine.tick, "paused": engine.paused,
            "speed": _speed, "slow_ticks": _slow_ticks,
            "seed": engine.seed, "ai_enabled": engine.ai_enabled,
            "ai_policy": engine.ai_policy}


# ------------------------------------------------------------------ control
@app.post("/api/control/pause")
async def pause():
    engine.paused = True
    return {"paused": True}


@app.post("/api/control/resume")
async def resume():
    engine.paused = False
    return {"paused": False}


@app.post("/api/control/step")
async def step_once():
    await asyncio.to_thread(_step_locked)
    return {"tick": engine.tick}


@app.post("/api/control/speed")
async def set_speed(value: float = Query(1.0, ge=0.25, le=10.0)):
    global _speed
    _speed = value
    return {"speed": _speed}


@app.post("/api/control/inject")
async def inject(node_id: str, kind: int = Query(3, ge=1, le=5)):
    from autonoc.engine import faults as F
    with _lock:
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
        engine.log(f"MANUAL: {node_id} — {C.STATUS_NAMES[kind]} injected",
                   "CRITICAL", node_id)
    return {"ok": True, "node": node_id, "status": kind}


@app.post("/api/control/cut-fiber")
async def cut_fiber(ring_id: int = Query(0, ge=0, le=20),
                    isolate: bool = Query(True),
                    cause: str = Query("construction")):
    """Trigger the Act 3 scenario: a double cut isolates a whole ring."""
    with _lock:
        return engine.cut_fiber(ring_id, isolate=isolate, cause=cause)


# ------------------------------------------------------------------ commander (M6)
@app.post("/api/control/ai")
async def set_ai(enabled: bool = Query(True),
                 auto_approve_seconds: float = Query(C.AUTO_APPROVE_SECONDS,
                                                     ge=0, le=600)):
    """Toggle the Commander and (for demos) auto-approve-after-N-seconds."""
    global worker
    with _lock:
        engine.ai_enabled = enabled
        if not enabled:
            engine.ai_verdicts = {}
            engine.ai_mode = "off"
    if worker is not None:
        worker.set_auto_approve(auto_approve_seconds)
    return {"ai_enabled": enabled, "auto_approve_seconds": auto_approve_seconds}


@app.post("/api/control/approve/{action_id}")
async def approve(action_id: int):
    with _lock:
        return engine.approve_action(action_id)


@app.post("/api/control/veto/{action_id}")
async def veto(action_id: int):
    with _lock:
        return engine.veto_action(action_id)


# ------------------------------------------------------------------ static
app.mount("/static", StaticFiles(directory="autonoc/web"), name="static")


@app.get("/")
async def index():
    return FileResponse("autonoc/web/index.html")
