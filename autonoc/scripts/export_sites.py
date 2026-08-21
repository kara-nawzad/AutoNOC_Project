"""
Export the 300 eNodeB positions as JSON and CSV.

Usage:  python -m autonoc.scripts.export_sites
Writes: sites_300.json, sites_300.csv
"""
from __future__ import annotations

import csv
import json
import pathlib
import statistics

from autonoc.engine import config as C
from autonoc.engine.geo import haversine_km
from autonoc.engine.placement import (CLUTTER_CELL_SCALE, GRID_TIERS,
                                       MORPHOLOGY, ROADS, place_all)


def main(seed: int = 42) -> None:
    sites = place_all(seed)
    by_agg: dict[int, list] = {}
    for s in sites:
        by_agg.setdefault(s["agg_id"], []).append(s)

    districts = []
    for agg_id, name, alat, alon, count, clutter_c, color in C.AGG_SITES:
        g = by_agg[agg_id]
        pattern, bearing, clutter_class = MORPHOLOGY[agg_id]
        nn = [min(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
                  for b in g if b is not a) for a in g] if len(g) > 1 else [0.0]
        span = max(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
                   for a in g for b in g)
        districts.append({
            "parent_agg": f"AGG-{agg_id}",
            "name": name,
            "hub_lat": alat, "hub_lon": alon,
            "site_count": count,
            "pattern": pattern,
            "clutter_class": clutter_class,
            "cost231_clutter_c_db": clutter_c,
            "axis_bearing_deg": bearing,
            "cell_scale": CLUTTER_CELL_SCALE[clutter_class],
            "mean_spacing_m": round(statistics.mean(nn) * 1000),
            "span_km": round(span, 2),
            "color": color,
        })

    doc = {
        "project": "AutoNOC v2 — Sulaymaniyah",
        "seed": seed,
        "generated_from": "autonoc/engine/placement.py",
        "crs": "EPSG:4326",
        "bounds": {"lat_min": C.LAT_MIN, "lat_max": C.LAT_MAX,
                   "lon_min": C.LON_MIN, "lon_max": C.LON_MAX},
        "total_sites": len(sites),
        "placement": {
            "method": "clutter-scaled variable grid + roads + character",
            "grid_tiers_km": [list(t) for t in GRID_TIERS],
            "clutter_cell_scale": CLUTTER_CELL_SCALE,
            "roads": list(ROADS),
            "served_radius_km": 3.5,
        },
        "districts": districts,
        "sites": [
            {
                "site_id": s["site_id"],
                "lat": s["lat"],
                "lon": s["lon"],
                "parent_agg": s["parent_agg"],
                "clutter_class": s["clutter_class"],
                "role": s["role"],
            }
            for s in sites
        ],
    }

    out_json = pathlib.Path("sites_300.json")
    out_json.write_text(json.dumps(doc, indent=2))
    out_csv = pathlib.Path("sites_300.csv")
    with out_csv.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["site_id", "lat", "lon", "parent_agg",
                    "clutter_class", "role"])
        for s in sites:
            w.writerow([s["site_id"], s["lat"], s["lon"],
                        s["parent_agg"], s["clutter_class"], s["role"]])
    print(f"wrote {out_json} ({out_json.stat().st_size/1024:.0f} KB)")
    print(f"wrote {out_csv} ({out_csv.stat().st_size/1024:.0f} KB)\n")
    print(f"{'AGG':6} {'district':18} {'n':>3} {'pattern':13} "
          f"{'clutter':14} {'spacing':>8} {'span':>7}")
    for d in districts:
        print(f"{d['parent_agg']:6} {d['name']:18} {d['site_count']:3} "
              f"{d['pattern']:13} {d['clutter_class']:14} "
              f"{d['mean_spacing_m']:6} m {d['span_km']:5.1f} km")


if __name__ == "__main__":
    main()
