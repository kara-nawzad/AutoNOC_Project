"""React command center contracts. No browser request may advance the engine."""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonoc.api import main as M, presentation as P
from autonoc.api.schemas import DeltaResponse
from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine


@pytest.fixture
def world(monkeypatch, tmp_path):
    from autonoc.api.run_history import RunSummaryStore

    engine = NOCEngine(seed=42, horizon=600)
    monkeypatch.setattr(M, "engine", engine)
    monkeypatch.setattr(M, "worker", None)
    monkeypatch.setattr(M, "_history", P.History())
    monkeypatch.setattr(M, "_speed", 1.0)
    monkeypatch.setattr(M, "_run_id", "test-run")
    monkeypatch.setattr(M, "_reset_notice", False)
    monkeypatch.setattr(M, "_run_error", None)
    monkeypatch.setattr(M, "_summary_store", RunSummaryStore(tmp_path))
    return engine


def get_delta(since):
    return asyncio.run(M.get_delta(since))


def test_delta_delivers_every_current_node(world):
    M._step_locked()
    before = get_delta(0)
    M._step_locked()
    after = get_delta(before["tick"])
    assert len(after["nodes"]) == C.NUM_NODES
    assert after["nodes"] == asyncio.run(M.get_full())["nodes"]
    DeltaResponse(**after)


def test_multiple_readers_receive_the_same_warning(world):
    M._step_locked()
    world.ai_enabled = True
    world.ai_verdicts = {world.nodes[0].node_id: {"p_fail": .99, "cls": C.STATUS_RF}}
    first, second = get_delta(world.tick), get_delta(world.tick)
    assert first == second
    assert first["nodes"][0]["warn"]
    assert world.tick == 1


def test_same_tick_controls_arrive_while_paused(world):
    M._step_locked()
    world.paused = True
    client = TestClient(M.app)
    before = client.get('/api/delta?since=1').json()
    nid = world.nodes[0].node_id
    assert client.post('/api/control/inject', params={"node_id": nid, "kind": 3, "run_id": M._run_id}).status_code == 200
    after = client.get('/api/delta?since=1').json()
    assert before['tick'] == after['tick'] == 1
    assert after['nodes'][0]['status'] == C.STATUS_RF
    assert any('MANUAL' in row['message'] for row in after['logs'])
    assert any(inc['node_id'] == nid for inc in after['dashboard']['incidents'])


def test_pause_resume_and_single_step(world):
    client = TestClient(M.app)
    params = {"run_id": M._run_id}
    client.post('/api/control/pause', params=params)
    assert get_delta(0)['control']['paused']
    client.post('/api/control/step', params=params)
    assert world.tick == 1 and world.paused
    client.post('/api/control/resume', params=params)
    assert not get_delta(1)['control']['paused']


def test_history_is_bounded_and_reads_do_not_mutate(world):
    for _ in range(40):
        M._step_locked()
    before = list(M._history.rows)
    get_delta(0); get_delta(0)
    assert list(M._history.rows) == before
    rows = get_delta(40)['dashboard']['history']
    assert len(rows) == 30
    assert [r['tick'] for r in rows] == list(range(11, 41))


def test_history_reset_starts_with_the_day_one_sample():
    engine = NOCEngine(seed=7, horizon=600)
    history = P.History()
    history.reset(engine)
    rows = history.read_window(engine, P.sample(engine), 7)
    assert len(rows) == 1
    assert rows[0]["tick"] == 0
    assert rows[0]["sim_time"] == engine.sim_time


def test_timeframe_history_uses_current_run_samples_and_exact_sim_window(world):
    for _ in range(40):
        M._step_locked()

    client = TestClient(M.app)
    params = {"run_id": M._run_id}
    recent = client.get("/api/telemetry/history", params={**params, "timeframe": "30m"})
    assert recent.status_code == 200
    recent_body = recent.json()
    assert recent_body["tick_minutes"] == C.TICK_MINUTES
    assert [row["tick"] for row in recent_body["samples"]] == list(range(34, 41))

    day = client.get("/api/telemetry/history", params={**params, "timeframe": "24h"})
    week = client.get("/api/telemetry/history", params={**params, "timeframe": "7d"})
    assert len(day.json()["samples"]) == len(week.json()["samples"]) == 40
    assert day.json()["samples"][-1]["tick"] == week.json()["samples"][-1]["tick"] == 40
    assert client.get(
        "/api/telemetry/history", params={"timeframe": "7d", "run_id": "stale-run"}
    ).status_code == 409
    assert client.get(
        "/api/telemetry/history", params={"timeframe": "5y", "run_id": M._run_id}
    ).status_code == 422


def test_dashboard_is_derived_from_engine(world):
    for _ in range(12):
        M._step_locked()
    d = get_delta(0)['dashboard']
    assert d['current']['availability'] == world.kpis()['availability']
    assert d['current']['throughput_gbps'] == round(sum(n.throughput for n in world.nodes) / 1000, 3)
    assert sum(p['count'] for p in d['power']) == len(world.nodes)
    assert sum(p['fraction'] for p in d['power']) == pytest.approx(1)
    assert sum(d['fleet'].values()) == C.NUM_TEAMS
    assert d['traffic_change_pct'] is None  # no full hour of earlier samples yet


def test_correlated_display_includes_dispatched_ring(world):
    world.cut_fiber(0)
    M._step_locked()
    alarms = P.incidents(world)
    ring = next(i for i in alarms if i['id'] == 'ring-0')
    assert ring['severity'] == 'CRITICAL'
    assert ring['dispatched']
    assert not any(i['node_id'] in world.net.rings[0].node_ids and i['title'] == C.STATUS_NAMES[5] for i in alarms)


def test_forecast_does_not_leak_future_onset(world):
    world.ai_enabled = True
    n = world.nodes[0]
    n.onset_tick = 8888
    world.ai_verdicts = {n.node_id: {'p_fail': .8, 'cls': C.STATUS_RF}}
    forecast = get_delta(0)['dashboard']['forecast']
    assert forecast['probability'] == .8 and forecast['actionable']
    assert 'onset_tick' not in forecast
    assert '8888' not in str(forecast)


def test_config_has_all_semantics_and_supported_faults(world):
    cfg = asyncio.run(M.get_config())
    ui = cfg.presentation
    assert len(ui['roads']) > 0
    assert {f['value'] for f in ui['fault_options']} == set(C.STATUS_NAMES) - {C.STATUS_HEALTHY}
    assert set(ui['power_colors']) == {'Grid', 'Battery', 'Solar', 'Generator'}
    assert set(ui['severity_colors']) >= set(C.X733_CLASSES)
    assert cfg.break_even_precision == C.BREAK_EVEN_PRECISION


def test_control_errors_are_actionable(world):
    client = TestClient(M.app)
    run_id = M._run_id
    assert client.post('/api/control/inject', params={'node_id': 'unknown', 'kind': 3, 'run_id': run_id}).status_code == 404
    assert client.post(f'/api/control/speed?value=100&run_id={run_id}').status_code == 422
    assert client.post(f'/api/control/cut-fiber?cause=%3Cb%3Eunsafe%3C/b%3E&run_id={run_id}').status_code == 422
    assert client.post(f'/api/control/approve/999?run_id={run_id}').json()['ok'] is False


def test_complete_snapshot_resets_legacy_consumers(world):
    M._step_locked()
    assert get_delta(999)['resync']
    assert get_delta(1)['resync']  # complete logs must be replaced, not appended


def test_history_resets_for_a_new_engine(world):
    M._step_locked()
    other = NOCEngine(seed=5, horizon=10)
    assert P.dashboard(other, M._history)['history'][0]['tick'] == 0
    assert len(P.dashboard(other, M._history)['history']) == 1


def test_react_build_is_served_when_available(world):
    path = Path(M._DIST / 'index.html')
    if not path.exists():
        pytest.skip('npm run build --prefix frontend first')
    client = TestClient(M.app)
    response = client.get('/')
    assert response.status_code == 200
    assert '/assets/' in response.text and 'root' in response.text
    assert response.headers['cache-control'] == 'no-store'
