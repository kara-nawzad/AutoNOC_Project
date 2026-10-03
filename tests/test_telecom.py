"""
Telecom-standards alignment (3GPP / ITU-T / O-RAN).

Guards for the v2.1 reframing: the dashboard and API speak operator language
(VSWR, PRB, CQI, E-RAB drops, X.733 severities, site-power types A/B/C, ATS
and fuel-theft alarms) while the ENGINE DYNAMICS the trained models depend on
stay untouched:

  - derived 3GPP KPIs are pure readouts of existing state (no new RNG draws
    in physics, no change to the 71-feature contract)
  - X.733 severities come from the config map, never hard-coded per call site
  - site power events (ATS failure to crank, fuel theft) are deterministic,
    counted in stats/KPIs, and raise CRITICAL notifications
"""
from __future__ import annotations

import pytest

from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine
from autonoc.engine.faults import FaultEvent

ALLOWED_SEVERITIES = {"INFO", "WARNING", "MINOR", "MAJOR", "CRITICAL", "CLEARED"}


# ------------------------------------------------------------------ language
def test_status_names_speak_3gpp():
    """The FM vocabulary is what a RAN engineer reads: VSWR alarms and PRB
    congestion, not "RF/Antenna" and "Congestion"."""
    names = " ".join(C.STATUS_NAMES.values())
    assert "VSWR" in names, "antenna faults must read as VSWR alarms"
    assert "PRB" in names, "congestion must read as PRB utilisation"
    assert C.STATUS_NAMES[C.STATUS_HEALTHY] == "In Service"
    assert C.STATUS_NAMES[C.STATUS_BACKHAUL] == "Backhaul Isolated"


def test_metric_labels_use_operator_terms():
    """E-RAB Drop Rate, not "packet loss"; QCI-9 user throughput."""
    assert C.METRIC_LABELS["loss"] == "E-RAB Drop Rate"
    assert "QCI 9" in C.METRIC_LABELS["throughput"]
    assert C.METRIC_LABELS["vswr"] == "VSWR"
    assert C.METRIC_LABELS["prb"] == "PRB Utilisation"
    assert C.METRIC_LABELS["fuel"] == "DG Fuel"
    # every gauge key has a label
    for key in C.GAUGE_SPECS:
        assert key in C.METRIC_LABELS, f"gauge '{key}' has no served label"


# ------------------------------------------------------------------ X.733
def test_x733_map_covers_every_fault_class():
    """ITU-T X.733 perceived severity for all five alarm kinds; power and
    backhaul (site-down / unreachable) are CRITICAL, the rest MAJOR."""
    for status in (C.STATUS_CONGESTION, C.STATUS_OVERHEAT, C.STATUS_RF,
                   C.STATUS_POWER, C.STATUS_BACKHAUL):
        assert status in C.X733_SEVERITY
        assert C.X733_SEVERITY[status] in C.X733_CLASSES
    assert C.X733_SEVERITY[C.STATUS_POWER] == "CRITICAL"
    assert C.X733_SEVERITY[C.STATUS_BACKHAUL] == "CRITICAL"
    assert C.X733_SEVERITY[C.STATUS_RF] == "MAJOR"


def test_logs_only_emit_x733_classes():
    """A run emits only X.733 severities (+INFO) — the ad-hoc v2 classes
    HIGH/SUCCESS are gone from the FM log."""
    e = NOCEngine(seed=42, horizon=C.TICKS_PER_DAY * 4)
    for _ in range(600):
        e.step()
    e.cut_fiber(3, isolate=False)      # MINOR (protection lost)
    e.cut_fiber(3, isolate=True)       # CRITICAL (isolation)
    for _ in range(60):
        e.step()
    severities = {l["severity"] for l in e.logs}
    assert severities, "no logs emitted — test not exercising the FM path"
    assert severities <= ALLOWED_SEVERITIES, f"non-X.733 severities: {severities}"
    assert "CRITICAL" in severities and "CLEARED" in severities


def test_activation_and_heal_use_the_x733_map():
    """Fault activation logs the mapped class; restoration logs CLEARED."""
    e = NOCEngine(seed=5)
    for _ in range(30):
        e.step()
    node = next(n for n in e.nodes if n.status == C.STATUS_HEALTHY)

    ev = FaultEvent(tick=e.tick, node_id=node.node_id, kind=C.STATUS_POWER,
                    is_gradual=False, onset_offset=0, severity=1.0,
                    curve="step", episode_id=987_654)
    e._activate(ev, node)
    assert e.logs[-1]["severity"] == "CRITICAL"

    ev2 = FaultEvent(tick=e.tick, node_id=node.node_id, kind=C.STATUS_RF,
                     is_gradual=False, onset_offset=0, severity=1.0,
                     curve="step", episode_id=987_655)
    e._activate(ev2, node)
    assert e.logs[-1]["severity"] == "MAJOR"

    e._heal(node, "test")
    assert e.logs[-1]["severity"] == "CLEARED"


def test_log_schema_rejects_legacy_severities():
    """The Pydantic boundary accepts X.733 and rejects the old classes."""
    from autonoc.api.schemas import LogModel
    for sev in ("INFO", "WARNING", "MINOR", "MAJOR", "CRITICAL", "CLEARED"):
        LogModel(tick=1, time="D1 00:00", severity=sev, message="x")
    with pytest.raises(Exception):
        LogModel(tick=1, time="D1 00:00", severity="HIGH", message="x")


# ------------------------------------------------------------------ VSWR
def test_vswr_is_the_exact_s11_identity():
    """VSWR = (1+|Gamma|)/(1-|Gamma|), |Gamma| = 10^(S11/20). The field
    alarm threshold 1.5 corresponds to S11 = -14 dB."""
    from autonoc.engine.network import build_network
    n = build_network(0).nodes[0]

    n.s11 = -22.0
    assert abs(n.vswr - 1.17) < 0.01          # healthy feed line
    n.s11 = -14.0
    assert abs(n.vswr - C.VSWR_ALARM_THRESHOLD) < 0.01
    n.s11 = -10.0
    assert abs(n.vswr - 1.93) < 0.01          # THRESH_S11 = damage territory

    # monotonic: worse return loss -> worse VSWR
    seq = []
    for s11 in (-30.0, -22.0, -14.0, -10.0, -6.0, -1.0):
        n.s11 = s11
        seq.append(n.vswr)
    assert seq == sorted(seq)
    assert all(v >= 1.0 for v in seq)


# ------------------------------------------------------------------ CQI / PRB
def test_cqi_maps_sinr_to_0_15():
    """CQI approximates the TS 36.213 SINR mapping and collapses with SINR."""
    from autonoc.engine.network import build_network
    n = build_network(0).nodes[0]
    seq = []
    for sinr in (-5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 35.0):
        n.sinr = sinr
        seq.append(n.cqi)
    assert seq == sorted(seq), "CQI must rise with SINR"
    assert all(0 <= c <= 15 for c in seq)
    assert seq[0] == 0 and seq[-1] == 15


def test_prb_saturates_during_congestion_alarm():
    """A cell under a PRB-congestion alarm reads >= the 85% saturation floor,
    exactly like a real PM counter pinned by unschedulable demand."""
    from autonoc.engine.network import build_network
    n = build_network(0).nodes[0]
    n.traffic_load = 0.5
    n.status = C.STATUS_HEALTHY
    assert abs(n.prb_util - 50.0) < 0.01      # offered load, in service

    n.status = C.STATUS_CONGESTION
    n.fault_progress = 0.0
    assert n.prb_util >= C.PRB_CONGESTION_FLOOR
    n.fault_progress = 1.0
    assert n.prb_util >= 99.0                 # fully developed congestion
    assert n.prb_util <= 100.0


# ------------------------------------------------------------------ site power
def test_power_config_types_a_b_c():
    """District grid tier -> site power architecture: Bakrajo (UNSTABLE) is
    Type B hybrid, Goizha (EXPOSED) is Type C off-grid solar, strong-grid
    districts are Type A."""
    assert C.POWER_CONFIG_BY_TIER["UNSTABLE"] == "B"
    assert C.POWER_CONFIG_BY_TIER["EXPOSED"] == "C"
    for tier in ("STRONGEST", "STRONG", "MEDIUM"):
        assert C.POWER_CONFIG_BY_TIER[tier] == "A"
    assert set(C.POWER_CONFIG_NAMES) == {"A", "B", "C"}

    e = NOCEngine(seed=1)
    for n in e.nodes:
        d = n.to_dict()
        assert d["pwr"] == C.POWER_CONFIG_BY_TIER[n.grid_tier]
        if n.agg_id == 5:                     # Bakrajo
            assert d["pwr"] == "B"
        if n.agg_id == 0:                     # Goizha
            assert d["pwr"] == "C"


def test_ats_failure_to_crank(monkeypatch):
    """ATS FAILURE TO CRANK: mains down, battery at the generator-start
    level, fuel in the tank — and the DG does NOT start. X.733 CRITICAL,
    counted in stats, and cleared when the mains returns."""
    e = NOCEngine(seed=5)
    for _ in range(20):
        e.step()
    node = next(n for n in e.nodes if n.status == C.STATUS_HEALTHY)
    node.grid_available = False
    node.battery_pct = C.GEN_START_BATTERY_PCT   # crank requested NOW
    node.generator_fuel_pct = 80.0
    node.ats_failed = False

    monkeypatch.setattr(C, "ATS_CRANK_FAIL_CHANCE", 1.0)
    e._power_events(node)
    assert node.ats_failed
    assert e.stats["ats_failures"] == 1
    log = e.logs[-1]
    assert "ATS FAILURE TO CRANK" in log["message"]
    assert log["severity"] == "CRITICAL"

    # with the switch jammed the plant must NOT run the generator
    from autonoc.engine import physics as P
    node.battery_pct = 5.0
    P.update_power(node, e.tick, e.noise)
    assert node.power_source != "Generator"

    # mains back -> ATS resets with the plant
    monkeypatch.setattr(C, "ATS_CRANK_FAIL_CHANCE", 0.0)
    node.grid_available = True
    e._power_events(node)
    assert not node.ats_failed


def test_ats_jam_can_take_the_site_down(monkeypatch):
    """The nightmare path: a jammed ATS with the battery empty is site-down,
    exactly like a dry tank."""
    e = NOCEngine(seed=5)
    for _ in range(20):
        e.step()
    node = next(n for n in e.nodes if n.status == C.STATUS_HEALTHY)
    node.grid_available = False
    node.battery_pct = 0.2
    node.generator_fuel_pct = 70.0
    node.ats_failed = True
    monkeypatch.setattr(C, "ATS_RECOVER_CHANCE", 0.0)
    e._power_events(node)
    e._check_power_failure(node)
    assert node.status == C.STATUS_POWER
    assert "ATS" in e.logs[-1]["message"]


def test_fuel_theft_alarm(monkeypatch):
    """FUEL THEFT / ABNORMAL FUEL DROP: the DG is OFF yet the tank loses
    15-25% in one telemetry interval. X.733 CRITICAL, counted in stats."""
    e = NOCEngine(seed=5)
    for _ in range(20):
        e.step()
    node = next(n for n in e.nodes if n.status == C.STATUS_HEALTHY)
    node.grid_available = True
    node.power_source = "Grid"
    node.generator_fuel_pct = 80.0

    monkeypatch.setattr(C, "FUEL_THEFT_CHANCE", 1.0)
    e._power_events(node)
    drop = 80.0 - node.generator_fuel_pct
    assert C.FUEL_THEFT_DROP_PCT[0] - 1e-9 <= drop <= C.FUEL_THEFT_DROP_PCT[1] + 1e-9
    assert e.stats["fuel_thefts"] == 1
    log = e.logs[-1]
    assert "FUEL THEFT" in log["message"]
    assert log["severity"] == "CRITICAL"


def test_fuel_theft_never_fires_while_dg_runs(monkeypatch):
    """Consumption is not theft: a RUNNING generator may not raise the
    abnormal-drop alarm, and an (almost) empty tank is not worth stealing."""
    e = NOCEngine(seed=5)
    for _ in range(20):
        e.step()
    node = next(n for n in e.nodes if n.status == C.STATUS_HEALTHY)
    monkeypatch.setattr(C, "FUEL_THEFT_CHANCE", 1.0)
    node.power_source = "Generator"
    node.generator_fuel_pct = 80.0
    e._power_events(node)
    assert node.generator_fuel_pct == 80.0
    node.power_source = "Battery"
    node.generator_fuel_pct = C.FUEL_THEFT_MIN_FUEL_PCT - 1.0
    e._power_events(node)
    assert e.stats["fuel_thefts"] == 0


# ------------------------------------------------------------------ payloads
def test_node_payload_carries_telecom_kpis():
    """to_dict exposes the derived 3GPP readouts + site-power telemetry, and
    the Pydantic boundary validates them."""
    from autonoc.api.schemas import NodeModel
    e = NOCEngine(seed=3)
    for _ in range(30):
        e.step()
    d = e.nodes[0].to_dict()
    for key in ("vswr", "cqi", "prb", "pwr", "fuel", "ats"):
        assert key in d, f"payload missing '{key}'"
    NodeModel(**{**d, "warn": False})
    k = e.kpis()
    assert "ats_failures" in k and "fuel_thefts" in k


def test_config_serves_the_telecom_layer():
    """/api/config remains the single source of truth (I5): labels, gauge
    specs, X.733 map, power configurations, rApp roles, VSWR alarm point.
    Gauge specs must be internally consistent for the frontend renderer."""
    import asyncio
    import autonoc.api.main as M

    cfg = asyncio.run(M.get_config())
    assert cfg.metric_labels["loss"] == "E-RAB Drop Rate"
    assert cfg.vswr_alarm == C.VSWR_ALARM_THRESHOLD
    assert set(cfg.x733_severity.values()) <= set(C.X733_CLASSES)
    assert set(cfg.power_configs) == {"A", "B", "C"}
    assert len(cfg.rapp_roles) == 3
    for key, g in cfg.gauges.items():
        assert g["lo"] < g["hi"], f"gauge {key}: empty window"
        for t in ("good", "warn", "bad"):
            assert g["lo"] <= g[t] <= g["hi"], f"gauge {key}: {t} outside window"
        if g["lower_bad"]:
            assert g["good"] > g["warn"] > g["bad"], f"gauge {key}: bad order"
        else:
            assert g["good"] < g["warn"] < g["bad"], f"gauge {key}: bad order"


# ------------------------------------------------------------------ purity
def test_power_events_preserve_determinism():
    """The new site-power events live inside step() and are seed-deterministic
    (I3): fuel levels and ATS latches match across identical runs."""
    def run():
        e = NOCEngine(seed=17, horizon=C.TICKS_PER_DAY * 3)
        for _ in range(700):
            e.step()
        return [(n.node_id, round(n.generator_fuel_pct, 9), n.ats_failed,
                 n.battery_pct, n.status) for n in e.nodes]

    assert run() == run()
