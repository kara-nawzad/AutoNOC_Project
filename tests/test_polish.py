"""
M8 — polish: seed casting, docs, demo support.

The cast seed (131) is deterministic: its exogenous schedules always produce
the same world, so these assertions are stable across machines.
"""
from __future__ import annotations

import pathlib

import pytest

from autonoc.engine import config as C

# The seed the M8 cast found (score 14/15): storm over Goizha + a natural
# storm-caused fiber cut + a Salim Street gradual fault in the Act-1 window
# + an instant fault during the storm + a calm opening.
DEMO_SEED = 131

ROOT = pathlib.Path(__file__).parent.parent


def test_cast_seed_131_is_demo_worthy():
    """The cast seed's exogenous world contains every demo beat."""
    from autonoc.scripts.cast_seed import profile

    p = profile(DEMO_SEED, days=2)
    assert p["score"] >= 13.0, f"seed {DEMO_SEED} scored {p['score']}"
    assert p["n_storms"] > 0, "no storm over Goizha"
    assert p["n_fiber_cuts"] > 0, "no natural fiber cut"
    assert p["storm_cut_act3"], "no storm-caused cut in the Act-3 window"
    assert p["salim_act1"], "no Salim Street gradual fault in the Act-1 window"
    assert p["best_salim"]["kind"] == C.STATUS_CONGESTION, \
        "Act 1 should be a congestion degrade (reads best on camera)"
    assert p["n_instant_in_storm"] > 0, "no instant fault during the storm"
    assert p["calm_start"], "opening should be calm"


def test_search_returns_sorted_profiles():
    """The search driver returns profiles sorted best-first with the keys
    the demo plan and tests rely on."""
    from autonoc.scripts.cast_seed import search

    results = search(range(1, 9), days=2, workers=1)
    assert len(results) == 8
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), "not sorted best-first"
    keys = {"seed", "score", "n_storms", "n_fiber_cuts", "best_salim",
            "first_storm_cut", "n_instant_in_storm", "calm_start"}
    assert keys <= set(results[0].keys())


def test_demo_plan_contains_all_acts():
    """The demo plan narrates every act for the cast seed."""
    from autonoc.scripts.cast_seed import demo_plan

    plan = "\n".join(demo_plan(DEMO_SEED, days=2))
    for beat in ("Act 0", "Act 1", "Act 3", "Act 4", "Act 5",
                 "STORM over Goizha", "SLY-eNB-080", "CUT FIBER"):
        assert beat in plan, f"demo plan missing '{beat}'"


def test_cast_seed_is_verified_by_models():
    """The demo fault must actually be caught by the trained Commander —
    this is what --verify checks, and it must hold in CI with models."""
    from autonoc.scripts.cast_seed import verify

    models = ROOT / "models"
    if not (models / "oracle_gru.pt").exists():
        pytest.skip("run autonoc.ai.oracle first")
    r = verify(DEMO_SEED, days=3)
    assert r["ai_mode"] == "ml", f"models not loaded: {r['ai_mode']}"
    assert r["demo_salim_pre_empted"] is True, \
        "the demo Salim episode was not pre-empted by the Commander"


def test_docs_and_dependencies_exist():
    """M8 deliverables: README with honest limitations + requirements.txt."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "honest limitations" in readme.lower()
    assert "fastapi" in reqs
    assert "xgboost" in reqs
    assert "torch" in reqs
    assert "pytest" in reqs


def test_main_respects_autonoc_seed_env(monkeypatch):
    """AUTONOC_SEED lets the demo pin a cast seed without code changes."""
    import importlib
    monkeypatch.setenv("AUTONOC_SEED", "131")
    monkeypatch.setenv("AUTONOC_AI", "0")
    import autonoc.api.main as M
    M = importlib.reload(M)
    assert M.engine.seed == 131
    assert M.engine.ai_enabled is False
    monkeypatch.delenv("AUTONOC_SEED", raising=False)
    monkeypatch.delenv("AUTONOC_AI", raising=False)
    importlib.reload(M)
