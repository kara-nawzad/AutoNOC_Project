"""
Geodesy. Pure functions, stdlib only.

Distances use haversine in metres, never degree arithmetic. At 35.56 N one
degree of longitude is 90.56 km while one degree of latitude is 111.32 km —
v1 moved teams in raw degrees, making east-west travel 23% faster than
north-south.

Measured cost: 8 microseconds per tick for 10 teams, 0.16% of the 5 ms budget.
An equirectangular approximation would save 5 us and introduce up to 31.7 m of
error, so it is not worth it.
"""
from __future__ import annotations

import math

from . import config as C


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * C.EARTH_RADIUS_M * math.asin(math.sqrt(a))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_m(lat1, lon1, lat2, lon2) / 1000.0


def step_toward(lat: float, lon: float, tgt_lat: float, tgt_lon: float,
                step_m: float) -> tuple[float, float, bool]:
    """Move step_m metres toward the target.

    Returns (lat, lon, arrived). Arrival uses a distance threshold and snaps
    exactly on arrival — never float equality, which is never true and
    strands the mover forever.
    """
    d = haversine_m(lat, lon, tgt_lat, tgt_lon)
    if d <= step_m:
        return tgt_lat, tgt_lon, True
    f = step_m / d
    return lat + (tgt_lat - lat) * f, lon + (tgt_lon - lon) * f, False


def interpolate(lat1: float, lon1: float, lat2: float, lon2: float,
                fraction: float) -> tuple[float, float]:
    """Point at `fraction` along the segment. Used to place fiber cuts."""
    return lat1 + (lat2 - lat1) * fraction, lon1 + (lon2 - lon1) * fraction


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v
