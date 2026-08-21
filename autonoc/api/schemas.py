"""
Pydantic validation. Restored — v1 deleted this layer as "simplification"
and lost its only guard against the engine shipping nonsense to the browser.

At ~300 records per tick the cost is negligible, and it catches engine bugs
at the boundary rather than as a blank screen.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from autonoc.engine import config as C


class NodeModel(BaseModel):
    id: str
    lat: float = Field(ge=C.LAT_MIN - 0.01, le=C.LAT_MAX + 0.01)
    lon: float = Field(ge=C.LON_MIN - 0.01, le=C.LON_MAX + 0.01)
    agg: int = Field(ge=0, le=9)
    ring: int = Field(ge=-1, le=C.NUM_RINGS)
    gen: int = Field(ge=0, le=2)
    critical: bool
    status: int = Field(ge=0, le=5)

    rsrp: float = Field(ge=-140.0, le=-40.0)
    sinr: float = Field(ge=-10.0, le=40.0)
    s11: float = Field(ge=-40.0, le=5.0)
    latency: float = Field(ge=0.0, le=1000.0)
    jitter: float = Field(ge=0.0, le=50.0)
    loss: float = Field(ge=0.0, le=100.0)
    throughput: float = Field(ge=0.0, le=400.0)
    temp: float = Field(ge=-20.0, le=100.0)
    cpu: float = Field(ge=0.0, le=100.0)

    power: Literal["Grid", "Solar", "Battery", "Generator"]
    voltage: float = Field(ge=0.0, le=20.0)
    battery: float = Field(ge=0.0, le=100.0)
    dust: float = Field(ge=0.0, le=1.0)

    dispatched: bool
    repairing: bool


class TeamModel(BaseModel):
    id: int = Field(ge=1, le=C.NUM_TEAMS)
    name: str
    skill: Literal["RF", "POWER", "GENERAL"]
    lat: float
    lon: float
    state: Literal["IDLE", "EN_ROUTE", "STANDBY", "REPAIRING", "RETURNING"]
    available: bool
    target: Optional[str] = None
    target_lat: Optional[float] = None
    target_lon: Optional[float] = None
    eta: int = Field(ge=0)
    missions: int = Field(ge=0)


class KPIModel(BaseModel):
    tick: int = Field(ge=0)
    sim_time: str
    availability: float = Field(ge=0.0, le=100.0)
    healthy: int = Field(ge=0)
    congestion: int = Field(ge=0)
    overheat: int = Field(ge=0)
    rf: int = Field(ge=0)
    power: int = Field(ge=0)
    backhaul: int = Field(ge=0)
    active_teams: int = Field(ge=0, le=C.NUM_TEAMS)
    grid_failures: int = Field(ge=0)
    mttr_min: float = Field(ge=0.0)
    injected: int = Field(ge=0)
    masked: int = Field(ge=0)
    repairs: int = Field(ge=0)


class AggModel(BaseModel):
    id: int
    name: str
    lat: float
    lon: float
    color: str
    node_count: int
    health: float = Field(ge=0.0, le=100.0)
    weather: str
    wind: float
    clutter: float


class LogModel(BaseModel):
    tick: int
    time: str
    severity: Literal["INFO", "SUCCESS", "HIGH", "CRITICAL"]
    message: str
    node_id: Optional[str] = None


class RingModel(BaseModel):
    id: int
    nodes: list[str]
    path: list[list[float]]
    circumference_km: float
    cut: Optional[dict] = None


class DeltaResponse(BaseModel):
    """Cursor-based delta. Read-only and idempotent.

    v1 used dirty flags cleared after each response, so a single dropped poll
    lost that update permanently and the client silently desynced. A tick
    cursor lets the client re-sync instead of drifting.
    """
    tick: int
    resync: bool
    kpis: KPIModel
    agg: list[AggModel]
    nodes: list[NodeModel]
    teams: list[TeamModel]
    logs: list[LogModel]
    rings: list[RingModel] = []
    ai: Optional[dict] = None        # M6 — Commander panel payload


class ConfigResponse(BaseModel):
    """Single source of truth for anything the frontend renders.

    v1 defined STATUS_COLORS, thresholds and region metadata in BOTH the
    backend and the JavaScript. They drifted, which is how SLY-032 ended up
    showing "Critical Fault" on the map and "Normal" in the sidebar.
    The frontend now hard-codes none of this.
    """
    status_names: dict[int, str]
    status_colors: dict[int, str]
    thresholds: dict[str, float]
    map_center: list[float]
    map_zoom: int
    bounds: dict[str, float]
    epc_primary: dict
    epc_backup: dict
    depot: dict
    agg_sites: list[dict]
    num_nodes: int
    num_teams: int
    tick_minutes: int
    break_even_precision: float
