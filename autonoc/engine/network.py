"""
Network construction: nodes, aggregation sites, fiber rings, neighbour graph.

Everything here is built ONCE. Node positions never change, so the neighbour
graph and ring topology are computed at init — v1 rebuilt the neighbour graph
every tick at a measured cost of 35.8 ms, most of its remaining budget.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from . import config as C
from .geo import haversine_km, haversine_m
from .models import AggSite, ENodeB, FiberRing, FiberSegment, Team


@dataclass
class Network:

    nodes: list[ENodeB] = field(default_factory=list)
    by_id: dict[str, ENodeB] = field(default_factory=dict)
    agg_sites: list[AggSite] = field(default_factory=list)
    rings: list[FiberRing] = field(default_factory=list)
    teams: list[Team] = field(default_factory=list)
    neighbours: dict[str, list[str]] = field(default_factory=dict)


def build_network(seed: int) -> Network:
    rng = random.Random(seed * 7919 + 11)
    net = Network()

    # Morphology-driven placement (see engine/placement.py).
    #
    # Two earlier attempts failed differently: scattering nodes in a disc
    # around each hub left 6.3 km holes, and farthest-point sampling fixed
    # coverage but made every district look identical. Real networks are
    # heterogeneous — micro-cells 200 m apart on Salim Street, macro sites
    # 1.5 km apart along the Goizha ridge. Each district now uses a placement
    # pattern derived from its physical character.
    from .placement import place_all

    site_by_id = {}
    for agg_id, name, alat, alon, count, clutter, color in C.AGG_SITES:
        site_by_id[agg_id] = AggSite(agg_id, name, alat, alon, clutter, color)

    for rec in place_all(seed):
        agg_id = rec["agg_id"]
        site = site_by_id[agg_id]
        lat, lon = rec["lat"], rec["lon"]
        elev = 780.0 + rng.uniform(-30, 60)
        if agg_id == 0:                          # Goizha ridge
            elev = 950.0 + rng.uniform(0, 300)
        gen = rng.choices((C.GEN_LEGACY, C.GEN_STANDARD, C.GEN_MODERN),
                          weights=C.GEN_WEIGHTS, k=1)[0]
        critical = (agg_id == 9 and
                    haversine_km(lat, lon, C.FARUK_LAT, C.FARUK_LON)
                    <= C.FARUK_RADIUS_KM)
        node = ENodeB(
            node_id=rec["site_id"], lat=lat, lon=lon, agg_id=agg_id,
            elevation_m=elev,
            dist_to_agg_m=max(haversine_m(lat, lon, site.lat, site.lon), 80.0),
            generation=gen,
            grid_tier=C.GRID_TIER[agg_id],
            is_critical=critical,
        )
        node.log_dist_km = math.log10(max(node.dist_to_agg_m / 1000.0, 0.02))
        net.nodes.append(node)
        net.by_id[node.node_id] = node
        site.node_ids.append(node.node_id)

    for agg_id in sorted(site_by_id):
        net.agg_sites.append(site_by_id[agg_id])

    net.teams = [Team(i + 1, n, C.TEAM_SKILLS[i])
                 for i, n in enumerate(C.TEAM_NAMES)]

    _build_neighbours(net)
    _build_rings(net, rng)
    return net


def _build_neighbours(net: Network) -> None:
    """O(n^2) once at init, never per tick."""
    net.neighbours = {n.node_id: [] for n in net.nodes}
    nodes = net.nodes
    for i in range(len(nodes)):
        a = nodes[i]
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            if haversine_km(a.lat, a.lon, b.lat, b.lon) <= C.NEIGHBOUR_RADIUS_KM:
                net.neighbours[a.node_id].append(b.node_id)
                net.neighbours[b.node_id].append(a.node_id)


def _build_rings(net: Network, rng: random.Random) -> None:
    """Geographically coherent fiber rings.

    Rings must be local. A ring spanning Bakrajo to Goizha is 12.8 km across;
    twelve alarms scattered over that distance read as random noise rather
    than a pattern, which would visually contradict the correlation claim
    that Act 3 exists to demonstrate.

    Real operators build rings along street topology, which is inherently
    local, so this is the realistic construction as well as the legible one.
    """
    # seed each ring at an aggregation site, then grow by nearest-unassigned
    unassigned = {n.node_id for n in net.nodes}
    ring_seeds = [(s.agg_id, s.lat, s.lon) for s in net.agg_sites]
    for ring_id, (_agg, slat, slon) in enumerate(ring_seeds):
        if not unassigned:
            break
        target = max(1, len(net.nodes) // C.NUM_RINGS)
        members: list[ENodeB] = []
        cx, cy = slat, slon
        for _ in range(target):
            if not unassigned:
                break
            # sorted() over a list keeps this deterministic; never iterate a set
            best = min(sorted(unassigned),
                       key=lambda nid: haversine_km(
                           cx, cy, net.by_id[nid].lat, net.by_id[nid].lon))
            node = net.by_id[best]
            if members and haversine_km(slat, slon, node.lat, node.lon) > \
                    C.RING_MAX_MEMBER_SEPARATION_KM:
                break
            # hard circumference guard: an over-large ring scatters its alarms
            # across the map and the correlation animation stops reading as a
            # cluster, which defeats the purpose of Act 3
            if len(members) >= 3:
                trial = _close_ring(ring_id, members + [node])
                if trial.circumference_km > C.RING_MAX_CIRCUMFERENCE_KM:
                    break
            members.append(node)
            unassigned.discard(best)
            node.ring_id = ring_id
            cx = sum(m.lat for m in members) / len(members)
            cy = sum(m.lon for m in members) / len(members)
        if members:
            net.rings.append(_close_ring(ring_id, members))

    # anything left over joins its geographically nearest ring
    for nid in sorted(unassigned):
        node = net.by_id[nid]
        ring = min(net.rings, key=lambda r: haversine_km(
            node.lat, node.lon,
            net.by_id[r.node_ids[0]].lat, net.by_id[r.node_ids[0]].lon))
        ring.node_ids.append(nid)
        node.ring_id = ring.ring_id


def _close_ring(ring_id: int, members: list[ENodeB]) -> FiberRing:
    """Order members into a loop by angle about their centroid, then close it."""
    cx = sum(m.lat for m in members) / len(members)
    cy = sum(m.lon for m in members) / len(members)
    ordered = sorted(members, key=lambda m: math.atan2(m.lat - cx, m.lon - cy))
    segs: list[FiberSegment] = []
    total = 0.0
    for i, a in enumerate(ordered):
        b = ordered[(i + 1) % len(ordered)]
        d = haversine_km(a.lat, a.lon, b.lat, b.lon)
        total += d
        segs.append(FiberSegment(
            seg_id=f"R{ring_id}-S{i}", ring_id=ring_id,
            from_lat=a.lat, from_lon=a.lon, to_lat=b.lat, to_lon=b.lon,
            length_km=d))
    return FiberRing(ring_id=ring_id,
                     node_ids=[m.node_id for m in ordered],
                     segments=segs,
                     circumference_km=total)
