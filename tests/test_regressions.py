"""
Regression tests. Every one encodes a bug that actually cost days in v1.
These are not hypothetical. Each has a measured failure behind it.
"""
from __future__ import annotations

import pytest

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine


@pytest.fixture(scope="module")
def run_7_days():
    """~7 simulated days. Long enough for steady state to emerge."""
    e = NOCEngine(seed=42, horizon=C.TICKS_PER_DAY * 8)
    for _ in range(2000):
        e.step()
    return e


# ------------------------------------------------------------------ v1 bug 1
def test_no_stuck_faults(run_7_days):
    """v1: 34 nodes (11.3%) broken for 7.6 simulated days while the fleet had
    1.8x the required capacity. Dispatch fired only on the tick a fault
    appeared, so anything arriving while all teams were busy was orphaned.
    """
    e = run_7_days
    stuck = [
        n for n in e.nodes
        if n.needs_technician
        and n.fault_started_tick >= 0
        and (e.tick - n.fault_started_tick) > C.STUCK_WATCHDOG_TICKS * 2
    ]
    assert not stuck, (
        f"{len(stuck)} nodes unrepaired beyond the watchdog window: "
        f"{[n.node_id for n in stuck[:5]]}"
    )


def test_availability_does_not_decay(run_7_days):
    """If repairs cannot keep pace, availability drifts down forever.
    v1 reached 88.3% and falling.
    """
    avail = run_7_days.kpis()["availability"]
    assert 93.0 <= avail <= 100.0, f"availability {avail}% outside healthy band"


# ------------------------------------------------------------------ v1 bug 2
def test_teams_always_released(run_7_days):
    """v1 leaked teams: a mission could start and never reset its state,
    permanently removing that crew from the fleet.
    """
    e = run_7_days
    for t in e.teams:
        if t.state == "IDLE":
            assert t.target_id is None
            assert t.incident is None
            assert t.repair_ticks_left == 0
    # over 2000 ticks every team should have completed real work
    idle_forever = [t for t in e.teams if t.dispatch_count == 0]
    assert len(idle_forever) < len(e.teams), "no team ever dispatched"


def test_fleet_not_permanently_saturated(run_7_days):
    """A fleet stuck at 100% busy is the signature of a leak."""
    e = run_7_days
    busy_streak = 0
    for _ in range(60):
        e.step()
        if all(not t.available for t in e.teams):
            busy_streak += 1
        else:
            busy_streak = 0
        assert busy_streak < 50, "fleet saturated for 50 consecutive ticks"


# ------------------------------------------------------------------ v1 bug 3
def test_vehicle_speed_is_correct():
    """v1: 0.0048 deg/tick was intended as 40 km/h but was actually 6.4 km/h,
    and moving in raw degrees made east-west travel 23% faster than
    north-south (1 deg lon = 90.6 km vs 1 deg lat = 111.3 km at 35.56 N).
    """
    from autonoc.engine.geo import haversine_m, step_toward
    start = (35.5500, 45.4200)
    # north-south leg
    ns_lat, ns_lon, _ = step_toward(*start, 35.6100, 45.4200, C.TEAM_STEP_M)
    ns = haversine_m(*start, ns_lat, ns_lon)
    # east-west leg of equal metric distance
    ew_lat, ew_lon, _ = step_toward(*start, 35.5500, 45.5200, C.TEAM_STEP_M)
    ew = haversine_m(*start, ew_lat, ew_lon)
    assert abs(ns - ew) < 1.0, f"anisotropic movement: NS {ns:.1f} m vs EW {ew:.1f} m"
    assert abs(ns - C.TEAM_STEP_M) < 1.0
    kmh = C.TEAM_STEP_M / 1000.0 / (C.TICK_MINUTES / 60.0)
    assert abs(kmh - C.TEAM_SPEED_KMH) < 0.1


def test_team_arrival_uses_threshold_not_equality():
    """Float equality is never true and strands the mover forever."""
    from autonoc.engine.geo import step_toward
    lat, lon = 35.5500, 45.4200
    tgt = (35.5510, 45.4210)          # ~140 m, well inside one step
    lat, lon, arrived = step_toward(lat, lon, *tgt, C.TEAM_STEP_M)
    assert arrived
    assert (lat, lon) == tgt          # snapped exactly


# ------------------------------------------------------------------ v1 bug 4
def test_rsrp_threshold_is_reachable():
    """v1 used Friis (free-space), ~27 dB optimistic at 1 km. RSRP < -100 dBm
    was unreachable anywhere inside the map, so that entire fault branch was
    dead code.
    """
    e = NOCEngine(seed=3)
    for _ in range(200):
        e.step()
    healthy = [n.rsrp for n in e.nodes if n.status == C.STATUS_HEALTHY]
    assert healthy
    worst = min(healthy)
    best = max(healthy)
    assert -120.0 < worst < -85.0, f"worst healthy RSRP {worst:.1f} implausible"
    assert -95.0 < best < -50.0, f"best healthy RSRP {best:.1f} implausible"


# ------------------------------------------------------------------ topology
def test_rings_are_geographically_coherent():
    """A ring spanning Bakrajo to Goizha is 12.8 km across. Twelve alarms
    scattered over that distance read as noise rather than a pattern, which
    would visually contradict the very correlation claim Act 3 exists to make.
    """
    from autonoc.engine.geo import haversine_km
    e = NOCEngine(seed=42)
    for ring in e.net.rings:
        if len(ring.node_ids) < 2:
            continue
        pts = [(e.net.by_id[n].lat, e.net.by_id[n].lon) for n in ring.node_ids]
        spread = max(
            haversine_km(*a, *b) for i, a in enumerate(pts) for b in pts[i + 1:]
        )
        assert spread <= C.RING_MAX_MEMBER_SEPARATION_KM * 2, (
            f"ring {ring.ring_id} spans {spread:.1f} km — alarms would not "
            f"read as a cluster"
        )


def test_every_node_belongs_to_exactly_one_ring():
    e = NOCEngine(seed=42)
    seen: dict[str, int] = {}
    for ring in e.net.rings:
        for nid in ring.node_ids:
            assert nid not in seen, f"{nid} in rings {seen[nid]} and {ring.ring_id}"
            seen[nid] = ring.ring_id
    assert len(seen) == len(e.nodes)


# ------------------------------------------------------------------ ledger
def test_ledger_denominator_is_consistent_across_arms():
    """Masked events must be counted identically in every arm, or the recall
    denominator silently drifts and the counterfactual comparison is invalid.
    """
    a = NOCEngine(seed=77, ai_enabled=False)
    c = NOCEngine(seed=77, ai_enabled=True)
    for _ in range(400):
        a.step()
        c.step()
    assert a.stats["injected"] == c.stats["injected"]


def test_backhaul_node_looks_healthy_except_throughput():
    """A backhaul-isolated node is FINE but unreachable: normal RF, normal
    temperature, normal power. Distinguishing that from a genuinely broken
    node demands the opposite action, and is the diagnostic subtlety that
    makes correlation non-trivial.
    """
    from autonoc.engine.faults import apply_degradation
    e = NOCEngine(seed=5)
    for _ in range(30):
        e.step()
    node = e.nodes[0]
    rsrp_before, temp_before = node.rsrp, node.temperature
    apply_degradation(node, C.STATUS_BACKHAUL, 1.0, 1.0, e.noise)
    assert node.throughput == 0.0
    assert node.packet_loss == 100.0
    assert node.rsrp == rsrp_before, "backhaul isolation must not alter RF"
    assert node.temperature == temp_before, "backhaul isolation must not alter thermal"


# ------------------------------------------------------------------ physics bounds
def test_metrics_stay_physically_possible():
    """Degradation compounds across ticks, so every fault effect must clamp.
    An early build produced 118 C, +8.5 dB S11 and 1194 ms latency because
    the multipliers had no ceiling. The Pydantic response layer caught it at
    the API boundary — exactly the job that layer exists to do — but the
    engine should never generate impossible values in the first place.
    """
    e = NOCEngine(seed=11)
    for _ in range(1500):
        e.step()
        for n in e.nodes:
            assert -20.0 <= n.temperature <= 100.0, f"{n.node_id} temp {n.temperature}"
            assert 0.0 <= n.latency <= 1000.0, f"{n.node_id} latency {n.latency}"
            assert -40.0 <= n.s11 <= 5.0, f"{n.node_id} s11 {n.s11}"
            assert -140.0 <= n.rsrp <= -40.0, f"{n.node_id} rsrp {n.rsrp}"
            assert 0.0 <= n.voltage <= 20.0, f"{n.node_id} voltage {n.voltage}"
            assert 0.0 <= n.jitter <= 50.0, f"{n.node_id} jitter {n.jitter}"
            assert 0.0 <= n.packet_loss <= 100.0, f"{n.node_id} loss {n.packet_loss}"
            assert 0.0 <= n.throughput <= 400.0, f"{n.node_id} thr {n.throughput}"


# ------------------------------------------------------------------ coverage
def test_network_has_no_coverage_holes():
    """Towers must cover the SERVED AREA without holes.

    Coverage is measured only within 3.5 km of an aggregation hub. The map
    bounds are a bounding box around the ten hubs plus padding, but the city
    is a valley running east-west — the corners of that box are mountain and
    empty land, and 78% of apparent "holes" fall there. A real operator does
    not build towers over uninhabited terrain, so measuring the whole box
    would penalise correct behaviour.
    """
    from autonoc.engine.geo import haversine_km
    from autonoc.engine.network import build_network

    net = build_network(42)
    hubs = [(s[2], s[3]) for s in C.AGG_SITES]
    worst = 0.0
    over = 0
    samples = 0
    for i in range(30):
        for j in range(45):
            la = C.LAT_MIN + (C.LAT_MAX - C.LAT_MIN) * i / 29
            lo = C.LON_MIN + (C.LON_MAX - C.LON_MIN) * j / 44
            if min(haversine_km(la, lo, h[0], h[1]) for h in hubs) > 3.5:
                continue                      # outside the served area
            d = min(haversine_km(la, lo, n.lat, n.lon) for n in net.nodes)
            worst = max(worst, d)
            samples += 1
            if d > 2.0:
                over += 1
    pct = over / samples * 100
    assert pct < 8.0, f"{pct:.1f}% of the served area is >2 km from a tower"
    assert worst < 3.5, f"worst gap inside the served area is {worst:.1f} km"


def test_districts_have_distinct_morphology():
    """Salim Street micro-cells must be visibly tighter than the Goizha ridge.
    An even scatter across the whole city is not what a real deployment looks
    like: dense commercial streets need a site every other corner because of
    building shadows, while a ridge site with 5 km line of sight covers the
    work of three.
    """
    import statistics
    from autonoc.engine.geo import haversine_km
    from autonoc.engine.network import build_network

    net = build_network(42)

    def spacing(agg_id: int) -> float:
        g = [n for n in net.nodes if n.agg_id == agg_id]
        return statistics.mean(
            min(haversine_km(a.lat, a.lon, b.lat, b.lon)
                for b in g if b is not a) for a in g)

    salim = spacing(2)
    goizha = spacing(0)
    assert salim < goizha, (
        f"Salim Street ({salim*1000:.0f} m) should be denser than "
        f"Goizha ({goizha*1000:.0f} m)"
    )
    assert salim * 1000 < 400, f"Salim micro-cells at {salim*1000:.0f} m, expected <400"


def test_tower_spacing_is_realistic():
    """Spacing must be plausible PER DISTRICT, not uniform across the city.
    An earlier version asserted a single city-wide mean, which is the wrong
    shape of test: it would only pass if every district were placed
    identically, which is exactly the even-scatter look we are trying to
    avoid. Real deployments span roughly 150 m micro-cells to 1.5 km rural
    macro sites.
    """
    import statistics
    from autonoc.engine.geo import haversine_km
    from autonoc.engine.network import build_network

    net = build_network(42)
    for agg_id, name, *_ in [(s[0], s[1]) for s in C.AGG_SITES]:
        g = [n for n in net.nodes if n.agg_id == agg_id]
        if len(g) < 2:
            continue
        nn = [min(haversine_km(a.lat, a.lon, b.lat, b.lon)
                  for b in g if b is not a) for a in g]
        mean_m = statistics.mean(nn) * 1000
        assert 120.0 < mean_m < 2000.0, (
            f"{name}: mean spacing {mean_m:.0f} m is outside the plausible "
            f"120-2000 m range for any real deployment"
        )
    # and the city as a whole should sit in the dense-urban band
    all_nn = [min(haversine_km(a.lat, a.lon, b.lat, b.lon)
                  for b in net.nodes if b is not a) for a in net.nodes]
    city_mean = statistics.mean(all_nn) * 1000
    assert 200.0 < city_mean < 1200.0, (
        f"city-wide mean spacing {city_mean:.0f} m implausible for "
        f"300 sites over 235 km2"
    )


# ------------------------------------------------------------------ continuity
def test_corridors_between_hubs_are_continuous():
    """No dead zones between districts.
    Per-district morphology alone produced ten well-formed islands with
    unserved gaps between them — a real operator covers the roads people
    travel on, not just the neighbourhoods. 30% of each district's sites are
    outriders strung along corridors toward neighbouring hubs.
    """
    from autonoc.engine.geo import haversine_km
    from autonoc.engine.network import build_network

    net = build_network(42)
    pairs = [(0, 4), (0, 7), (2, 4), (3, 5), (4, 5),
             (2, 5), (6, 3), (8, 6), (8, 5), (9, 7)]
    for a, b in pairs:
        A, B = C.AGG_SITES[a], C.AGG_SITES[b]
        worst = 0.0
        for f in (0.3, 0.4, 0.5, 0.6, 0.7):
            la = A[2] + (B[2] - A[2]) * f
            lo = A[3] + (B[3] - A[3]) * f
            worst = max(worst, min(
                haversine_km(la, lo, n.lat, n.lon) for n in net.nodes))
        assert worst < 1.5, (
            f"corridor {A[1]} <-> {B[1]} has a {worst:.2f} km hole"
        )


def test_named_infill_areas_are_served():
    """Raparin, Zargata and Tuwi Malik must reach suburban density.
    These were the visible gaps in the rendered map before outriders existed.
    """
    from autonoc.engine.geo import haversine_km
    from autonoc.engine.network import build_network

    net = build_network(42)
    areas = [("Raparin", 35.5745, 45.3720),
             ("Zargata", 35.5480, 45.3880),
             ("Tuwi Malik", 35.5340, 45.4180)]
    for name, la, lo in areas:
        nearest = min(haversine_km(la, lo, n.lat, n.lon) for n in net.nodes)
        assert nearest < 1.2, f"{name} nearest tower is {nearest:.2f} km away"


# ------------------------------------------------------------------ Act 3
def test_single_cut_reroutes_and_gets_repaired():
    """A protected ring survives one cut, but must still dispatch a crew.
    An earlier build raised no incident for a single cut, so nothing was ever
    repaired. Cuts accumulated silently until a ring randomly reached two and
    33 nodes went dark at once — the opposite of how ring protection works.
    """
    e = NOCEngine(seed=42, horizon=C.TICKS_PER_DAY * 6)
    for _ in range(200):
        e.step()
    res = e.cut_fiber(3, isolate=False)
    assert res["ok"] and not res["isolated"]
    assert res["nodes_dark"] == 0, "a single cut must not darken nodes"
    for _ in range(90):
        e.step()
    open_cuts = sum(len(r.cuts) for r in e.net.rings)
    assert open_cuts == 0, f"{open_cuts} cuts left unrepaired — no crew sent"


def test_double_cut_isolates_and_correlates_to_one_incident():
    """The Act 3 centrepiece.
    Thirty-plus nodes go dark from a single physical cause. A naive NOC reads
    that as thirty-plus independent failures, dispatches the entire fleet, and
    every technician arrives to find nothing wrong — the nodes are healthy,
    they simply have no backhaul. Correlation collapses the alarm storm onto
    the shared segments.
    """
    from autonoc.engine.dispatch import correlate_alarms

    e = NOCEngine(seed=42, horizon=C.TICKS_PER_DAY * 6)
    for _ in range(200):
        e.step()
    before = e.kpis()["availability"]
    res = e.cut_fiber(5, isolate=True)
    assert res["isolated"], "two cuts on one ring must isolate it"
    dark = res["nodes_dark"]
    assert dark >= 10, f"only {dark} nodes dark — ring too small to demo"
    incidents = correlate_alarms(e.net, e.tick)
    fiber = [i for i in incidents if i.kind == "FIBER_CUT"]
    assert len(fiber) <= 2, (
        f"{dark} alarms collapsed to {len(fiber)} incidents; correlation failed"
    )
    assert all(len(i.affected) >= 10 for i in fiber)
    # and the network must actually recover
    for _ in range(80):
        e.step()
    still_dark = sum(1 for n in e.nodes if n.status == C.STATUS_BACKHAUL)
    assert still_dark == 0, f"{still_dark} nodes still isolated after 80 ticks"
    assert e.kpis()["availability"] > before - 3.0


def test_isolated_node_is_not_locally_broken():
    """Backhaul isolation must leave RF, thermal and power untouched.
    This is the diagnostic subtlety that makes correlation non-trivial: an
    isolated node reports healthy hardware, so a per-node classifier sees
    nothing wrong with it.
    """
    e = NOCEngine(seed=9, horizon=C.TICKS_PER_DAY * 4)
    for _ in range(120):
        e.step()
    ring = max(e.net.rings, key=lambda r: len(r.node_ids))
    sample = e.net.by_id[ring.node_ids[0]]
    rsrp, temp, volts = sample.rsrp, sample.temperature, sample.voltage
    e.cut_fiber(ring.ring_id, isolate=True)
    assert sample.status == C.STATUS_BACKHAUL
    assert sample.throughput == 0.0
    assert sample.rsrp == rsrp, "isolation must not change RF"
    assert sample.temperature == temp, "isolation must not change thermal"
    assert sample.voltage == volts, "isolation must not change power"
