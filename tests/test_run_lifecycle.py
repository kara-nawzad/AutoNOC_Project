"""Thirty-day reset, run-bound controls, and summary durability guards."""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from autonoc.ai.serve import InferenceWorker
from autonoc.api import main as M
from autonoc.api import presentation as P
from autonoc.api.run_history import RunSummaryStore
from autonoc.engine import config as C
from autonoc.engine.engine import NOCEngine


@pytest.fixture
def small_world(monkeypatch, tmp_path):
    engine = NOCEngine(seed=42, horizon=4)
    monkeypatch.setattr(M, "engine", engine)
    monkeypatch.setattr(M, "worker", None)
    monkeypatch.setattr(M, "_history", P.History())
    monkeypatch.setattr(M, "_summary_store", RunSummaryStore(tmp_path))
    monkeypatch.setattr(M, "_run_id", "run-before-reset")
    monkeypatch.setattr(M, "_reset_notice", False)
    monkeypatch.setattr(M, "_run_error", None)
    monkeypatch.setattr(M, "_speed", 1.0)
    return engine


class WorkerStub:
    def __init__(self, seconds=12.5):
        self.auto_approve_seconds = seconds
        self.engine = None
        self.run_id = None

    def replace_engine(self, engine, run_id):
        self.engine = engine
        self.run_id = run_id

    def eta_for(self, action_id):
        return 0.0

    def set_auto_approve(self, seconds):
        self.auto_approve_seconds = seconds


def test_exact_day_30_boundary_resets_without_exposing_day_31(monkeypatch, tmp_path):
    engine = NOCEngine(seed=42, ai_enabled=True, horizon=M.RUN_TICKS)
    engine.tick = M.RUN_TICKS - 1
    monkeypatch.setattr(M, "engine", engine)
    monkeypatch.setattr(M, "worker", None)
    monkeypatch.setattr(M, "_history", P.History())
    monkeypatch.setattr(M, "_summary_store", RunSummaryStore(tmp_path))
    monkeypatch.setattr(M, "_run_id", "day-thirty-run")
    monkeypatch.setattr(M, "_run_error", None)

    assert M.RUN_TICKS == 30 * C.TICKS_PER_DAY == 8640
    assert engine.sim_time == "D30 23:55"
    result = M._step_locked(automatic=True)

    assert result["reset"] is True
    assert M.engine is not engine
    assert M.engine.tick == 0
    assert M.engine.sim_time == "D1 00:00"
    assert M._run_id != "day-thirty-run"
    assert M._summary_store.recent()[0]["completed_sim_time"] == "D30 23:55"
    history = TestClient(M.app).get("/api/history")
    assert history.status_code == 200
    assert history.json()["summaries"][0]["simulated_days"] == 30
    assert M._reset_notice is True


def test_manual_step_can_cross_boundary_but_stays_paused(small_world):
    small_world.tick = small_world.horizon - 1
    small_world.paused = True
    before_id = M._run_id

    automatic = M._step_locked(automatic=True)
    assert automatic["advanced"] is False
    assert M.engine is small_world
    assert M._run_id == before_id
    assert M._summary_store.recent() == []

    manual = M._step_locked(automatic=False, expected_run_id=before_id)
    assert manual["reset"] is True
    assert M.engine.tick == 0
    assert M.engine.paused is True
    assert M._run_id != before_id
    assert len(M._summary_store.recent()) == 1


def test_reset_reinitializes_world_and_preserves_operator_preferences(small_world, monkeypatch):
    old = small_world
    old.horizon = 4
    old.tick = old.horizon - 1
    old.paused = False
    old.ai_enabled = True
    old.ai_policy = "advisory"
    old.ai_mode = "ml"
    old.ai_verdicts = {old.nodes[0].node_id: {"p_fail": 0.9, "cls": C.STATUS_RF}}
    old.pending_actions = [{"action_id": 99, "node_id": old.nodes[0].node_id,
                            "state": "pending"}]
    old._next_action_id = 100
    old.stats["injected"] = 9
    old.stats["repairs"] = 4
    old.stats["ats_failures"] = 2
    old.nodes[0].status = C.STATUS_RF
    old.nodes[0].grid_available = False
    old.nodes[0].power_source = "Generator"
    old.nodes[0].ats_failed = True
    old.teams[0].state = "EN_ROUTE"
    old.teams[0].target_id = old.nodes[0].node_id
    old.cut_fiber(0, isolate=False)

    worker = WorkerStub(seconds=37.0)
    monkeypatch.setattr(M, "worker", worker)
    monkeypatch.setattr(M, "_speed", 4.0)
    old_layout = [(n.node_id, n.lat, n.lon) for n in old.nodes]
    old_run_id = M._run_id

    result = M._step_locked(automatic=True)
    fresh = M.engine

    assert result["reset"] is True
    assert fresh.seed == old.seed == 42
    assert fresh.ai_enabled is True
    assert fresh.ai_policy == "advisory"
    assert fresh.ai_mode == "ml"
    assert M._speed == 4.0
    assert worker.auto_approve_seconds == 37.0
    assert worker.engine is fresh and worker.run_id == M._run_id
    assert M._run_id != old_run_id
    assert [(n.node_id, n.lat, n.lon) for n in fresh.nodes] == old_layout
    assert fresh.tick == 0
    assert fresh.ai_verdicts == {}
    assert fresh.pending_actions == []
    assert fresh.stats["injected"] == fresh.stats["repairs"] == 0
    assert fresh.stats["ats_failures"] == 0
    assert fresh.nodes[0].status == C.STATUS_HEALTHY
    assert fresh.nodes[0].ats_failed is False
    assert all(not ring.cuts for ring in fresh.net.rings)
    assert all(team.available and team.state == "IDLE" for team in fresh.teams)
    assert M._history.owner is fresh
    assert len(P.dashboard(fresh, M._history)["history"]) == 1
    summary = M._summary_store.recent()[0]
    assert summary["injected"] == 9
    assert summary["repairs"] == 4
    assert summary["ats_failures"] == 2
    assert "run_id" not in summary


def test_stale_controls_and_approvals_are_rejected(small_world):
    client = TestClient(M.app)
    node = small_world.nodes[0]
    small_world.pending_actions = [{"action_id": 1, "node_id": node.node_id,
                                    "state": "pending"}]

    stale = client.post("/api/control/pause", params={"run_id": "older-run"})
    assert stale.status_code == 409
    assert small_world.paused is False
    stale_approval = client.post(
        "/api/control/approve/1", params={"run_id": "older-run"}
    )
    assert stale_approval.status_code == 409
    assert len(small_world.pending_actions) == 1

    current = client.post(
        "/api/control/pause", params={"run_id": M._run_id}
    )
    assert current.status_code == 200
    assert small_world.paused is True


def test_manual_step_endpoint_requires_pause_and_keeps_pause(small_world):
    client = TestClient(M.app)
    run_id = M._run_id
    assert client.post("/api/control/step", params={"run_id": run_id}).status_code == 409
    client.post("/api/control/pause", params={"run_id": run_id})
    small_world.tick = small_world.horizon - 1
    response = client.post("/api/control/step", params={"run_id": run_id})
    assert response.status_code == 200
    assert response.json()["reset"] is True
    assert M.engine.tick == 0 and M.engine.paused


def test_summary_save_failure_preserves_old_world_and_pauses(small_world, monkeypatch):
    small_world.tick = small_world.horizon - 1
    before_run_id = M._run_id

    class FailedStore:
        def save(self, run_id, summary):
            raise OSError("simulated disk full")

        def recent(self):
            return []

    monkeypatch.setattr(M, "_summary_store", FailedStore())
    result = M._step_locked(automatic=True)

    assert result["reset"] is False
    assert M.engine is small_world
    assert M.engine.tick == small_world.horizon - 1
    assert M.engine.paused is True
    assert M._run_id == before_run_id
    assert "simulated disk full" in M._run_error
    snapshot = M._snapshot(resync=True)
    assert snapshot["run_error"] == M._run_error


def test_initialization_failure_preserves_old_world_and_does_not_save(small_world, monkeypatch):
    small_world.tick = small_world.horizon - 1
    before_run_id = M._run_id
    store = M._summary_store

    def fail_initialization(source, paused):
        raise RuntimeError("simulated initialization failure")

    monkeypatch.setattr(M, "_new_engine_like", fail_initialization)
    result = M._step_locked(automatic=True)

    assert result["reset"] is False
    assert M.engine is small_world
    assert M.engine.tick == small_world.horizon - 1
    assert M.engine.paused is True
    assert M._run_id == before_run_id
    assert store.recent() == []
    assert "simulated initialization failure" in M._run_error


def test_worker_discards_in_flight_verdicts_from_previous_run(tmp_path):
    old = NOCEngine(seed=42, ai_enabled=True, horizon=4)
    new = NOCEngine(seed=42, ai_enabled=True, horizon=4)
    lock = threading.Lock()
    worker = InferenceWorker(old, lock, models_dir=str(tmp_path), run_id="old")
    entered = threading.Event()
    release = threading.Event()

    def slow_score(source=None):
        entered.set()
        assert release.wait(5)
        return {"old-world-node": {"p_fail": 0.9}}

    worker._score_batch = slow_score
    result = []
    thread = threading.Thread(target=lambda: result.append(worker._process_cycle()))
    try:
        thread.start()
        assert entered.wait(5)
        with lock:
            worker.replace_engine(new, "new")
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        assert result == [False]
        assert new.ai_verdicts == {}
        assert old.ai_verdicts == {}
    finally:
        release.set()
        worker.stop()


def test_history_store_persists_recent_summaries(tmp_path):
    first = RunSummaryStore(tmp_path, max_entries=2)
    for index in range(3):
        first.save(
            f"internal-{index}",
            {"completed_at": f"2026-10-0{index + 1}T00:00:00Z", "seed": 42},
        )
    reopened = RunSummaryStore(tmp_path, max_entries=2)
    assert [row["completed_at"] for row in reopened.recent()] == [
        "2026-10-03T00:00:00Z",
        "2026-10-02T00:00:00Z",
    ]
