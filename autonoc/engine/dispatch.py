"""
Alarm correlation and state-driven dispatch.

v1's dispatch bug: auto-dispatch fired only on the tick a fault appeared. If
all ten teams happened to be busy that instant, the node was orphaned
permanently — 34 nodes sat broken for 7.6 simulated days while the fleet had
1.8x the required capacity. Dispatch here runs EVERY tick over ALL pending
work.
"""
from __future__ import annotations

from . import config as C
from .geo import haversine_km
from .models import Incident


def correlate_alarms(net, tick: int) -> list[Incident]:
    """Collapse symptoms into root-cause incidents.

    Twelve backhaul-isolated nodes on one fiber segment are ONE incident.
    Dispatching twelve teams to twelve 'failures' consumes the whole fleet,
    and none of those repairs fix anything — the nodes were never broken.
    Measured: the naive reading restores 0 of 12 nodes while occupying all 10
    teams for 2.7 simulated hours.
    """
    incidents: list[Incident] = []
    claimed: set[str] = set()

    # 1. fiber cuts -> ONE incident at the cut coordinate.
    #
    # This is the case a naive NOC gets catastrophically wrong. Twelve
    # backhaul-isolated nodes look like twelve failures; dispatching twelve
    # crews consumes the whole fleet and repairs nothing, because none of
    # those nodes are actually broken. They are fine but unreachable.
    for ring in net.rings:
        for cut in ring.cuts:
            if cut.repaired or cut.dispatched:
                continue
            affected = [nid for nid in ring.node_ids
                        if net.by_id[nid].status == C.STATUS_BACKHAUL]
            claimed.update(affected)
            isolated = len(affected) >= C.MIN_CORRELATED_ALARMS
            incidents.append(Incident(
                kind="FIBER_CUT",
                target_id=cut.segment.seg_id,
                target_lat=cut.lat, target_lon=cut.lon,
                affected=affected,
                status=C.STATUS_BACKHAUL,
                required_skill=C.REPAIR_SKILL[C.STATUS_BACKHAUL],
                repair_ticks=C.REPAIR_TICKS[C.STATUS_BACKHAUL],
                root_cause=(
                    f"Fiber cut {cut.segment.seg_id} ({cut.cause}) — "
                    + (f"{len(affected)} nodes isolated"
                       if isolated else
                       f"ring {ring.ring_id} unprotected, rerouting")),
            ))

    # 2. everything else -> individual incidents
    for node in net.nodes:
        if not node.needs_technician or node.tech_dispatched:
            continue
        if node.node_id in claimed:
            continue
        incidents.append(Incident(
            kind="NODE_FAULT",
            target_id=node.node_id,
            target_lat=node.lat, target_lon=node.lon,
            affected=[node.node_id],
            status=node.status,
            required_skill=C.REPAIR_SKILL[node.status],
            repair_ticks=C.REPAIR_TICKS[node.status],
            root_cause=C.STATUS_NAMES[node.status],
        ))
    return incidents


def priority_score(inc: Incident, net, tick: int) -> float:
    """Priority-weighted triage, not nearest-first.

    Wait-time ageing is essential: without it low-priority nodes starve
    indefinitely, which is v1's orphaning bug wearing a different hat.
    """
    severity = {"FIBER_CUT": 100.0}.get(inc.kind, 40.0)
    if inc.status == C.STATUS_POWER:
        severity = 60.0
    crit = max((net.by_id[n].priority_mult for n in inc.affected
                if n in net.by_id), default=1.0)
    waits = [tick - net.by_id[n].fault_started_tick
             for n in inc.affected
             if n in net.by_id and net.by_id[n].fault_started_tick >= 0]
    wait = max(waits) if waits else 0
    travel = haversine_km(C.DEPOT_LAT, C.DEPOT_LON,
                          inc.target_lat, inc.target_lon) / \
        (C.TEAM_SPEED_KMH / C.TICKS_PER_HOUR)
    return (severity * len(inc.affected) * crit
            * (1.0 + wait / 50.0) / (1.0 + travel / 10.0))


def best_team(inc: Incident, free: list, tick: int):
    """Choose by expected completion time, not distance.

    nearby generalist : 2 travel + 12 x 1.2 = 16.4 ticks
    distant RF tech   : 5 travel + 12 x 1.0 = 17.0 ticks   -> send the generalist
    """
    def completion(team):
        d_km = haversine_km(team.lat, team.lon, inc.target_lat, inc.target_lon)
        travel = d_km / (C.TEAM_SPEED_KMH / C.TICKS_PER_HOUR)
        return travel + inc.repair_ticks * team.skill_mult(inc.required_skill)

    return min(free, key=completion)
