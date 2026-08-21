"""
Site placement: guaranteed coverage blanket + density character.

FIVE iterations, each fixing the last one's failure:

  1. Disc around each hub      -> 6.3 km holes, 30% of the city uncovered
  2. Farthest-point sampling   -> coverage fixed, every district identical
  3. Per-district morphology   -> character restored, districts became islands
  4. + corridor outriders      -> islands joined, but pockets still unserved
  5. THIS: guaranteed grid     -> every 800 m cell in the served area holds at
                                  least one site, BEFORE any character is added

The ordering is the whole point. Earlier versions placed towers by character
and hoped coverage emerged; it never fully did. This version reserves one
tower per grid cell first — coverage becomes a guarantee rather than an
outcome — then spends what remains on density and road-following.

A NOTE ON THE ARITHMETIC

    The bounding box holds 374 cells of 800 m; we have 300 towers. Covering
    the full box is therefore impossible, and would be wrong anyway: the box
    corners are mountain and empty valley. Restricted to the inhabited area
    (within 3.5 km of an aggregation hub) there are 290 cells, which 300
    towers CAN cover — with 10 to spare.

    That leaves no room for the requested 10-15 tower cores at every hub
    (that alone would be 100-150 towers). Coverage was chosen over core
    density, because a black hole in a neighbourhood is a worse defect than a
    hub that looks less dramatic. Cores still form naturally: dense districts
    get more grid cells, so Salim Street ends up tightly packed regardless.
"""
from __future__ import annotations

import math
import random

from . import config as C
from .geo import haversine_km

# --------------------------------------------------------------------------
# VARIABLE grid. A uniform 800 m lattice consumed 290 of 300 towers and
# flattened every district to the same 620 m spacing — Salim Street ended up
# with fewer sites than Bakrajo, which is backwards. Real networks vary cell
# size with demand, so the guarantee adapts to where people actually are.
#
#   (max_distance_from_hub_km, cell_size_km)
GRID_TIERS = (
    (1.2, 0.58),    # dense core  — metropolitan, micro-cell territory
    (2.2, 0.85),    # inner ring  — urban
    (3.5, 1.15),    # outer ring  — suburban / open
)

# Cell-size multiplier by clutter class. Metropolitan districts pack tighter
# because tall buildings cast signal shadows; open terrain needs far fewer
# sites for the same coverage.
CLUTTER_CELL_SCALE = {
    "Metropolitan": 0.68,
    "Urban": 0.88,
    "Suburban": 1.12,
    "Open": 1.30,
}

GRID_KM = 0.8               # nominal, used by tests as the coverage target
SERVED_RADIUS_KM = 3.5      # distance from a hub that counts as inhabited

_KM_LAT = 111.32
_KM_LON = 111.32 * math.cos(math.radians(35.56))

# Per-district character. Applied to whatever towers remain after the
# coverage grid is satisfied.
#   agg_id: (pattern, axis_bearing_deg, clutter_class)
MORPHOLOGY = {
    0: ("LINEAR_RIDGE", 118.0, "Open"),          # Goizha — NE ridge
    1: ("URBAN_CORE",     0.0, "Metropolitan"),  # Grand Millennium
    2: ("DENSE_GRID",    72.0, "Metropolitan"),  # Salim Street
    3: ("CORRIDOR",      95.0, "Urban"),         # University / Raparin
    4: ("RESIDENTIAL",    0.0, "Suburban"),      # Sarchinar
    5: ("GROWTH",       200.0, "Suburban"),      # Bakrajo
    6: ("CORRIDOR",     105.0, "Open"),          # Tasluja road
    7: ("RESIDENTIAL",    0.0, "Suburban"),      # Hawara Barza
    8: ("OPEN_PLAIN",   225.0, "Open"),          # Airport flats
    9: ("URBAN_CORE",     0.0, "Urban"),         # Rizgari
}

# Main roads that must show linear connectivity. Each is a polyline of
# (lat, lon) waypoints traced along the real route.
ROADS = {
    "60m Road": [
        (35.5790, 45.3550), (35.5735, 45.3800), (35.5680, 45.4050),
        (35.5620, 45.4230), (35.5602, 45.4340),
    ],
    "Salim Street": [
        (35.5510, 45.4180), (35.5545, 45.4250), (35.5565, 45.4295),
        (35.5590, 45.4360), (35.5615, 45.4430),
    ],
    "Tasluja Highway": [
        (35.5700, 45.3300), (35.5660, 45.3480), (35.5617, 45.3167),
    ],
    "Airport Link": [
        (35.5617, 45.3167), (35.5590, 45.3400), (35.5540, 45.3620),
        (35.5480, 45.3850),
    ],
    "Ring South": [
        (35.5290, 45.3590), (35.5340, 45.3900), (35.5400, 45.4180),
        (35.5450, 45.4520),
    ],
}


def _offset(lat, lon, north_km, east_km):
    return lat + north_km / _KM_LAT, lon + east_km / _KM_LON


def _along(bearing_deg, dist_km):
    b = math.radians(bearing_deg)
    return dist_km * math.cos(b), dist_km * math.sin(b)


def _clamp(lat, lon):
    return (min(C.LAT_MAX - 0.001, max(C.LAT_MIN + 0.001, lat)),
            min(C.LON_MAX - 0.001, max(C.LON_MIN + 0.001, lon)))


def _nearest_hub(lat, lon):
    return min(C.AGG_SITES, key=lambda s: haversine_km(lat, lon, s[2], s[3]))


def _hub_distance(lat, lon):
    return min(haversine_km(lat, lon, s[2], s[3]) for s in C.AGG_SITES)


# --------------------------------------------------------------------------
# stage 1 — the guaranteed coverage blanket
# --------------------------------------------------------------------------
def _coverage_grid(rng) -> list[tuple[float, float]]:
    """One site per cell, cell size set by district clutter AND hub distance.

    Coverage is reserved BEFORE any character is applied, so no neighbourhood
    can be left unserved. Each district lays its own lattice at its own
    resolution: a metropolitan cell is ~0.68x the base size because tall
    buildings cast signal shadows, while open terrain needs ~1.30x fewer
    sites for the same reach.

    Keying only on distance-from-hub was not enough — Salim Street and
    Sarchinar both sit ~1 km from a hub and were getting identical cells, so
    metropolitan density never emerged.
    """
    pts = []
    for agg_id, name, alat, alon, cnt, c, col in C.AGG_SITES:
        scale = CLUTTER_CELL_SCALE[MORPHOLOGY[agg_id][2]]
        prev = 0.0
        for limit, base_cell in GRID_TIERS:
            cell = base_cell * scale
            cols = math.ceil((C.LON_MAX - C.LON_MIN) * _KM_LON / cell)
            rows = math.ceil((C.LAT_MAX - C.LAT_MIN) * _KM_LAT / cell)
            for r in range(rows):
                for c in range(cols):
                    lat = C.LAT_MIN + (r + 0.5) * cell / _KM_LAT
                    lon = C.LON_MIN + (c + 0.5) * cell / _KM_LON
                    if lat > C.LAT_MAX or lon > C.LON_MAX:
                        continue
                    if _nearest_hub(lat, lon)[0] != agg_id:
                        continue              # belongs to another district
                    d = _hub_distance(lat, lon)
                    if not (prev < d <= limit):
                        continue
                    j = cell * 0.26
                    pts.append(_offset(lat, lon,
                                       rng.uniform(-j, j), rng.uniform(-j, j)))
            prev = limit
    return pts


# --------------------------------------------------------------------------
# stage 2 — road following
# --------------------------------------------------------------------------
def _road_sites(rng, budget: int) -> list[tuple[float, float]]:
    """Strung along the main roads to show linear connectivity."""
    if budget <= 0:
        return []
    # total road length, so budget is shared in proportion
    lengths = {}
    for name, pts in ROADS.items():
        lengths[name] = sum(haversine_km(*pts[i], *pts[i + 1])
                            for i in range(len(pts) - 1))
    total = sum(lengths.values())
    out = []
    for name, pts in ROADS.items():
        share = max(1, round(budget * lengths[name] / total))
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        seg_len = [haversine_km(*a, *b) for a, b in segs]
        cum = sum(seg_len)
        for k in range(share):
            if len(out) >= budget:
                break
            t = (k + 0.5) / share * cum
            acc = 0.0
            for (a, b), L in zip(segs, seg_len):
                if acc + L >= t:
                    f = (t - acc) / L if L else 0.0
                    lat = a[0] + (b[0] - a[0]) * f
                    lon = a[1] + (b[1] - a[1]) * f
                    out.append(_offset(lat, lon, rng.gauss(0, 0.13),
                                       rng.gauss(0, 0.13)))
                    break
                acc += L
    return out[:budget]


# --------------------------------------------------------------------------
# stage 3 — district character
# --------------------------------------------------------------------------
def _character_sites(rng, agg_id, n) -> list[tuple[float, float]]:
    """Extra density expressing each district's physical character."""
    if n <= 0:
        return []
    _, name, alat, alon, cnt, c, col = C.AGG_SITES[agg_id]
    pattern, bearing, _clutter = MORPHOLOGY[agg_id]
    pts = []
    if pattern == "DENSE_GRID":
        # micro-cells on the street axis: tall buildings cast signal shadows,
        # so Salim Street needs a site every other corner
        for i in range(n):
            r, c = divmod(i, 5)
            dn, de = _along(bearing, (c - 2) * 0.24 + rng.gauss(0, .05))
            pn, pe = _along(bearing + 90, (r - 1.5) * 0.30 + rng.gauss(0, .05))
            pts.append(_offset(alat, alon, dn + pn, de + pe))
    elif pattern == "LINEAR_RIDGE":
        # spread evenly along the full 5 km ridge so the mountain reads as a
        # border of signal rather than a single cluster
        for i in range(n):
            t = (i / max(1, n - 1) - 0.5) * 5.0
            dn, de = _along(bearing, t)
            wn, we = _along(bearing + 90, rng.gauss(0, 0.25))
            pts.append(_offset(alat, alon, dn + wn, de + we))
    elif pattern == "URBAN_CORE":
        for i in range(n):
            r = 0.35 + 0.45 * math.sqrt(rng.random())
            th = rng.uniform(0, 2 * math.pi)
            pts.append(_offset(alat, alon, r * math.cos(th), r * math.sin(th)))
    elif pattern == "GROWTH":
        for i in range(n):
            reach = 0.5 + 1.6 * (i / max(1, n - 1))
            gn, ge = _along(bearing + rng.gauss(0, 30), reach)
            pts.append(_offset(alat, alon, gn, ge))
    elif pattern == "CORRIDOR":
        for i in range(n):
            t = (i / max(1, n - 1) - 0.5) * 3.4
            dn, de = _along(bearing, t)
            wn, we = _along(bearing + 90, rng.gauss(0, 0.30))
            pts.append(_offset(alat, alon, dn + wn, de + we))
    elif pattern == "OPEN_PLAIN":
        for i in range(n):
            r = 0.6 + 1.8 * math.sqrt(rng.random())
            th = math.radians(bearing) + rng.gauss(0, 1.1)
            pts.append(_offset(alat, alon, r * math.cos(th), r * math.sin(th)))
    else:                                     # RESIDENTIAL
        side = math.ceil(math.sqrt(max(n, 1)))
        for i in range(n):
            r, c = divmod(i, side)
            step = 2.6 / side
            pts.append(_offset(alat, alon,
                               (r - side / 2) * step + rng.gauss(0, .08),
                               (c - side / 2) * step + rng.gauss(0, .08)))
    return pts


# --------------------------------------------------------------------------
def place_all(seed: int) -> list[dict]:
    """Generate all 300 sites. Deterministic for a given seed.

    Order matters: coverage is reserved first, so it is a guarantee. Whatever
    remains is spent on roads and district character.
    """
    rng = random.Random(seed * 7919 + 11)
    grid = _coverage_grid(rng)
    remaining = C.NUM_NODES - len(grid)
    road_budget = min(max(remaining // 3, 0), remaining)
    roads = _road_sites(rng, road_budget)
    remaining -= len(roads)

    # spend what is left on character, weighted by each district's tower quota
    weights = {s[0]: s[4] for s in C.AGG_SITES}
    total_w = sum(weights.values())
    character = []
    for agg_id in sorted(weights):
        share = round(remaining * weights[agg_id] / total_w)
        character += [(p, agg_id) for p in _character_sites(rng, agg_id, share)]

    candidates = [(p, None) for p in grid] + [(p, None) for p in roads] + character

    # Close any residual >800 m pocket. The variable grid leaves a handful of
    # cells whose nearest tower sits just across a boundary; a few of those
    # genuinely exceed 800 m. Patch them before spending anything on character.
    def _worst_pockets(pts, k):
        have = [q for q, _ in pts]
        out = []
        step = 0.35
        lat = C.LAT_MIN
        while lat <= C.LAT_MAX:
            lon = C.LON_MIN
            while lon <= C.LON_MAX:
                if _hub_distance(lat, lon) <= SERVED_RADIUS_KM:
                    d = min(haversine_km(lat, lon, q[0], q[1]) for q in have)
                    if d > 0.8:
                        out.append((d, lat, lon))
                lon += step / _KM_LON
            lat += step / _KM_LAT
        out.sort(reverse=True)
        picked = []
        for d, la, lo in out:
            if len(picked) >= k:
                break
            if all(haversine_km(la, lo, q[0], q[1]) > 0.7 for q in picked):
                picked.append((la, lo))
        return picked

    for la, lo in _worst_pockets(candidates, 14):
        candidates.append(((la, lo), None))

    # trim or pad to exactly NUM_NODES, never dropping a grid point
    if len(candidates) > C.NUM_NODES:
        keep = candidates[:len(grid) + len(roads)]
        extra = candidates[len(grid) + len(roads):]
        rng.shuffle(extra)
        candidates = keep + extra[:C.NUM_NODES - len(keep)]
    while len(candidates) < C.NUM_NODES:
        base = rng.choice(grid)
        candidates.append((_offset(base[0], base[1],
                                   rng.gauss(0, .25), rng.gauss(0, .25)), None))

    out = []
    for idx, (pt, forced_agg) in enumerate(candidates[:C.NUM_NODES], start=1):
        lat, lon = _clamp(*pt)
        hub = C.AGG_SITES[forced_agg] if forced_agg is not None else _nearest_hub(lat, lon)
        agg_id = hub[0]
        out.append({
            "site_id": f"SLY-eNB-{idx:03d}",
            "lat": round(lat, 4), "lon": round(lon, 4),
            "parent_agg": f"AGG-{agg_id}", "agg_id": agg_id,
            "agg_name": hub[1],
            "clutter_class": MORPHOLOGY[agg_id][2],
            "clutter_c": hub[5],
            "pattern": MORPHOLOGY[agg_id][0],
            "role": ("grid" if idx <= len(grid)
                     else "road" if idx <= len(grid) + len(roads)
                     else "character"),
        })
    assert len(out) == C.NUM_NODES, f"placed {len(out)}"
    return out
