"""
Domain models. Pure dataclasses — stdlib only.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

from . import config as C
from .geo import haversine_m, step_toward


# ------------------------------------------------------------------ eNodeB
@dataclass(slots=True)
class ENodeB:

    node_id: str
    lat: float
    lon: float
    agg_id: int
    elevation_m: float
    dist_to_agg_m: float
    generation: int
    grid_tier: str
    is_critical: bool = False          # Faruk Medical cluster
    ring_id: int = -1

    # log10(distance_km) never changes: nodes do not move. Precomputing it
    # removes a log10 per node per tick from the hottest path in the engine.
    log_dist_km: float = 0.0

    # radio
    rsrp: float = -85.0
    sinr: float = 20.0
    s11: float = -22.0
    latency: float = 25.0
    jitter: float = 2.5
    packet_loss: float = 0.3
    throughput: float = 150.0

    # hardware / environment
    temperature: float = 30.0
    cpu_load: float = 45.0
    traffic_load: float = 0.4
    dust_accum: float = 0.0            # 0..1, cumulative, reset on service

    # power
    power_source: str = "Grid"
    voltage: float = 12.0
    battery_pct: float = 100.0
    battery_capacity: float = 100.0    # fades with cycling
    battery_cycles: float = 0.0
    generator_fuel_pct: float = 100.0
    grid_available: bool = True

    # state
    status: int = C.STATUS_HEALTHY
    status_timer: int = 0
    episode_id: int = -1               # groups all windows from one fault
    fault_progress: float = 0.0        # 0..1 through the degradation curve
    fault_severity: float = 1.0        # 1.0 normal, 0.35 ambiguous
    is_gradual: bool = False
    onset_tick: int = -1               # when it will actually break
    tech_dispatched: bool = False
    under_repair: bool = False
    assigned_team: Optional[int] = None
    last_changed_tick: int = 0
    fault_started_tick: int = -1

    # Two-branch history. The fine branch alone cannot see dust degradation
    # (measured SNR 0.08); the coarse branch gives SNR 6.93.
    hist_fine: Deque[dict] = field(
        default_factory=lambda: deque(maxlen=C.HISTORY_FINE))
    hist_coarse: Deque[dict] = field(
        default_factory=lambda: deque(maxlen=C.HISTORY_COARSE))
    _hour_buffer: list = field(default_factory=list)

    # M6 — Commander state. Defaults are inert: with ai_enabled=False (and
    # therefore no verdicts and no actions) these never change, so determinism
    # (I3) is untouched.
    throttle_pct: float = 0.0          # fraction of traffic withheld (0..1)
    traffic_boost: float = 0.0         # extra load pushed here by a shed
    pre_empted_episode: int = -1       # episode stopped before activation

    # -------------------------------------------------- history
    def snapshot(self, tick: int) -> None:
        """Append to the fine buffer; roll up hourly into the coarse buffer."""
        row = {
            "rsrp": self.rsrp, "sinr": self.sinr, "s11": self.s11,
            "latency": self.latency, "jitter": self.jitter,
            "packet_loss": self.packet_loss, "throughput": self.throughput,
            "cpu_load": self.cpu_load, "temperature": self.temperature,
            "voltage": self.voltage, "battery_pct": self.battery_pct,
            "dust": self.dust_accum,
        }
        self.hist_fine.append(row)
        self._hour_buffer.append(row)
        if len(self._hour_buffer) >= C.TICKS_PER_HOUR:
            # Single pass computing sum and sum-of-squares per key.
            # The naive two-pass version was the #2 cost in the tick profile
            # (1.17M generator calls); this keeps the same result with one
            # traversal and no intermediate lists.
            buf = self._hour_buffer
            n = len(buf)
            totals: dict[str, float] = {}
            sqsums: dict[str, float] = {}
            for r in buf:
                for k, v in r.items():
                    totals[k] = totals.get(k, 0.0) + v
                    sqsums[k] = sqsums.get(k, 0.0) + v * v
            agg = {}
            inv_n = 1.0 / n
            for k, tot in totals.items():
                m = tot * inv_n
                agg[f"{k}_mean"] = m
                # aggregation divides noise by sqrt(n) — this is what makes
                # slow dust degradation visible to the Oracle
                var = (sqsums[k] - tot * m) / (n - 1) if n > 1 else 0.0
                agg[f"{k}_std"] = math.sqrt(var) if var > 0.0 else 0.0
            self.hist_coarse.append(agg)
            buf.clear()

    def roll_mean(self, key: str) -> float:
        if not self.hist_fine:
            return 0.0
        return sum(h[key] for h in self.hist_fine) / len(self.hist_fine)

    def roll_std(self, key: str) -> float:
        n = len(self.hist_fine)
        if n < 2:
            return 0.0
        m = self.roll_mean(key)
        return math.sqrt(sum((h[key] - m) ** 2 for h in self.hist_fine) / (n - 1))

    def delta(self, key: str) -> float:
        if len(self.hist_fine) < 2:
            return 0.0
        return self.hist_fine[-1][key] - self.hist_fine[-2][key]

    # -------------------------------------------------- state
    @property
    def is_faulty(self) -> bool:
        return self.status != C.STATUS_HEALTHY

    @property
    def needs_technician(self) -> bool:
        return self.status in (C.STATUS_RF, C.STATUS_POWER, C.STATUS_BACKHAUL)

    @property
    def can_remote_reset(self) -> bool:
        return (self.status in (C.STATUS_CONGESTION, C.STATUS_OVERHEAT)
                and C.GEN_REMOTE_RESET[self.generation] > 0.0)

    @property
    def priority_mult(self) -> float:
        return C.CRITICAL_PRIORITY_MULT if self.is_critical else 1.0

    def to_dict(self) -> dict:
        return {
            "id": self.node_id, "lat": round(self.lat, 6), "lon": round(self.lon, 6),
            "agg": self.agg_id, "ring": self.ring_id, "gen": self.generation,
            "critical": self.is_critical, "status": self.status,
            "rsrp": round(self.rsrp, 1), "sinr": round(self.sinr, 1),
            "s11": round(self.s11, 1), "latency": round(self.latency, 1),
            "jitter": round(self.jitter, 2), "loss": round(self.packet_loss, 2),
            "throughput": round(self.throughput, 1),
            "temp": round(self.temperature, 1), "cpu": round(self.cpu_load, 1),
            "power": self.power_source, "voltage": round(self.voltage, 2),
            "battery": round(self.battery_pct, 1),
            "dust": round(self.dust_accum, 3),
            "dispatched": self.tech_dispatched, "repairing": self.under_repair,
        }


# ------------------------------------------------------------------ agg site
@dataclass(slots=True)
class AggSite:

    agg_id: int
    name: str
    lat: float
    lon: float
    clutter_c: float
    color: str
    node_ids: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ fiber
@dataclass(slots=True)
class FiberSegment:
    """A span between two points on a ring.

    Carries real path vertices so a cut has an actual coordinate — the
    technician needs somewhere to drive, and the UI needs a point to animate
    toward. A graph edge alone is not dispatchable.
    """

    seg_id: str
    ring_id: int
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    length_km: float


@dataclass(slots=True)
class FiberRing:

    ring_id: int
    node_ids: list[str] = field(default_factory=list)
    segments: list[FiberSegment] = field(default_factory=list)
    circumference_km: float = 0.0
    cuts: list = field(default_factory=list)     # list[FiberCut]

    @property
    def is_isolated(self) -> bool:
        """One cut reroutes the long way; two isolate everything between."""
        return len(self.cuts) >= 2


@dataclass(slots=True)
class FiberCut:

    segment: FiberSegment
    position: float          # 0..1 along the segment
    lat: float               # dispatch target
    lon: float
    cause: str               # construction | storm | equipment
    started_tick: int
    repaired: bool = False
    dispatched: bool = False


# ------------------------------------------------------------------ team
@dataclass(slots=True)
class Team:

    team_id: int
    name: str
    skill: str
    lat: float = C.DEPOT_LAT
    lon: float = C.DEPOT_LON
    state: str = "IDLE"      # IDLE -> EN_ROUTE -> (STANDBY) -> REPAIRING -> RETURNING
    target_id: Optional[str] = None
    target_lat: Optional[float] = None
    target_lon: Optional[float] = None
    repair_ticks_left: int = 0
    standby_ticks_left: int = 0    # M7: how long a pre-positioned crew holds
    mission_start_tick: int = -1
    dispatch_count: int = 0
    last_changed_tick: int = 0
    incident: Optional["Incident"] = None    # the mission currently assigned

    @property
    def available(self) -> bool:
        return self.state == "IDLE"

    def skill_mult(self, required: str) -> float:
        if self.skill == required:
            return C.SKILL_MULT_MATCHED
        if self.skill == "GENERAL":
            return C.SKILL_MULT_GENERAL
        return C.SKILL_MULT_MISMATCH

    def dispatch_to(self, target_id: str, lat: float, lon: float, tick: int) -> None:
        self.state = "EN_ROUTE"
        self.target_id = target_id
        self.target_lat = lat
        self.target_lon = lon
        self.mission_start_tick = tick
        self.last_changed_tick = tick

    def advance(self, tick: int) -> bool:
        if self.target_lat is None:
            return False
        self.lat, self.lon, arrived = step_toward(
            self.lat, self.lon, self.target_lat, self.target_lon, C.TEAM_STEP_M)
        self.last_changed_tick = tick
        return arrived

    def eta_ticks(self) -> int:
        if self.state == "REPAIRING":
            return self.repair_ticks_left
        if self.state == "STANDBY":
            return self.standby_ticks_left
        if self.target_lat is None:
            return 0
        d = haversine_m(self.lat, self.lon, self.target_lat, self.target_lon)
        return math.ceil(d / C.TEAM_STEP_M)

    def send_home(self, tick: int) -> None:
        self.state = "RETURNING"
        self.target_id = None
        self.target_lat = C.DEPOT_LAT
        self.target_lon = C.DEPOT_LON
        self.repair_ticks_left = 0
        self.last_changed_tick = tick

    def go_idle(self, tick: int) -> None:
        self.state = "IDLE"
        self.target_id = None
        self.target_lat = None
        self.target_lon = None
        self.repair_ticks_left = 0
        self.incident = None
        self.last_changed_tick = tick

    def to_dict(self) -> dict:
        return {
            "id": self.team_id, "name": self.name, "skill": self.skill,
            "lat": round(self.lat, 6), "lon": round(self.lon, 6),
            "state": self.state, "available": self.available,
            "target": self.target_id,
            "target_lat": self.target_lat, "target_lon": self.target_lon,
            "eta": self.eta_ticks(), "missions": self.dispatch_count,
        }


# ------------------------------------------------------------------ incident
@dataclass(slots=True)
class Incident:
    """A root cause, not a symptom.

    Twelve backhaul-isolated nodes on one segment are ONE incident. Dispatching
    twelve teams to twelve 'failures' consumes the fleet, and none of the
    repairs fix anything — the nodes were never broken.
    """

    kind: str                # NODE_FAULT | FIBER_CUT
    target_id: str
    target_lat: float
    target_lon: float
    affected: list[str]
    status: int
    required_skill: str
    repair_ticks: int
    priority: float = 0.0
    root_cause: str = ""
