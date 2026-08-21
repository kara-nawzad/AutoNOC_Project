"""
Invariant guards. These run before any feature test.

An invariant that is not tested is a preference. v1 died because its
architecture existed only in conversation; every one of these encodes a
decision that must not be silently negotiated away.
"""
from __future__ import annotations

import ast
import hashlib
import math
import pathlib
import time
import pytest

ENGINE_DIR = pathlib.Path(__file__).parent.parent / "autonoc" / "engine"

# ---------------------------------------------------------------- I2
BANNED_IN_ENGINE = {
    # frameworks and I/O
    "fastapi", "starlette", "uvicorn", "requests", "httpx", "flask",
    # heavyweight data / ML
    "pandas", "sklearn", "torch", "tensorflow", "keras", "joblib", "xgboost",
    # non-determinism sources
    "time", "datetime", "uuid", "secrets", "asyncio", "threading",
    # filesystem
    "os", "pathlib", "shutil", "pickle", "json", "csv",
}


def _iter_engine_files():
    return sorted(ENGINE_DIR.rglob("*.py"))


def test_I2_engine_is_pure():
    """The engine imports nothing that breaks purity or determinism.

    This single test would have prevented v1's 177 ms/tick pandas call,
    which two rounds of manual profiling failed to locate.
    """
    files = _iter_engine_files()
    assert files, "no engine files found — did the path change?"
    violations = []
    for f in files:
        tree = ast.parse(f.read_text(), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # level > 0 means a relative import — always allowed
                if node.level:
                    continue
                mods = [(node.module or "").split(".")[0]]
            else:
                continue
            for m in mods:
                if m in BANNED_IN_ENGINE:
                    violations.append(f"{f.name}:{node.lineno} imports '{m}'")
    assert not violations, "engine purity violated:\n  " + "\n  ".join(violations)


def test_I2_engine_has_no_wallclock_calls():
    """Belt and braces: catch time access even via an allowed module."""
    bad = ("time.time", "time.perf_counter", "datetime.now", "datetime.utcnow")
    violations = []
    for f in _iter_engine_files():
        src = f.read_text()
        for token in bad:
            if token in src:
                violations.append(f"{f.name}: contains '{token}'")
    assert not violations, "wall-clock access in engine:\n  " + "\n  ".join(violations)


# ---------------------------------------------------------------- I3
def _state_hash(engine) -> str:
    """Order-independent, FP-noise-tolerant fingerprint of engine state.

    Floats are rounded before hashing: without this the test measures
    floating-point noise rather than logic. 6 dp is far tighter than any
    physical meaning in this model.
    """
    rows = sorted(
        (
            n.node_id,
            round(n.rsrp, 6),
            round(n.temperature, 6),
            round(n.voltage, 6),
            n.status,
        )
        for n in engine.nodes
    )
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def _run(seed: int, ticks: int):
    from autonoc.engine.engine import NOCEngine
    e = NOCEngine(seed=seed)
    for _ in range(ticks):
        e.step()
    return e


def test_I3_determinism_short():
    assert _state_hash(_run(42, 100)) == _state_hash(_run(42, 100))


@pytest.mark.slow
def test_I3_determinism_long():
    """5000 ticks ≈ 17 simulated days. Catches slow-accumulating divergence."""
    assert _state_hash(_run(42, 5000)) == _state_hash(_run(42, 5000))


def test_I3_different_seeds_diverge():
    """Sanity check on the determinism test itself: it must be able to fail."""
    assert _state_hash(_run(42, 100)) != _state_hash(_run(43, 100))


def test_I3_no_set_iteration_in_engine():
    """Set iteration order depends on string hashing and varies BETWEEN
    PROCESSES when PYTHONHASHSEED is unset. Verified as a real hazard.
    """
    violations = []
    for f in _iter_engine_files():
        tree = ast.parse(f.read_text(), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Set):
                violations.append(f"{f.name}:{node.lineno} iterates a set literal")
    assert not violations, "\n  ".join(violations)


# ---------------------------------------------------------------- I4
def _machine_speed_index() -> float:
    """Cost of a fixed unit of work on THIS machine, in milliseconds.

    An absolute wall-clock budget measures the hardware, not the code. The
    same engine measured 3.4 ms on a bare Linux box and 21.6 ms on Windows
    under VS Code — a 6x spread that says nothing about efficiency. So we
    calibrate against a reference workload first and assert on the ratio.
    """
    t0 = time.perf_counter()
    acc = 0.0
    for i in range(200_000):
        acc += math.log10(i + 1.5) * 1.0000001
    return (time.perf_counter() - t0) * 1000.0


# Reference: on the machine where the budget was set, _machine_speed_index()
# returned ~REF_INDEX_MS and step() ran at ~REF_STEP_MS for 300 nodes.
REF_INDEX_MS = 38.0
REF_STEP_MS = 3.5
MAX_RATIO = 3.0        # allow 3x worse than reference before failing


@pytest.mark.slow
def test_I4_step_within_budget_for_this_machine():
    """step() must stay efficient RELATIVE to the machine it runs on.

    The engine budget exists so the simulation never blocks the event loop.
    In the live app one tick has 1000 ms of wall clock available, so even a
    slow machine has orders of magnitude of headroom. What this test really
    guards against is an algorithmic regression — an accidental O(n^2) scan
    or a pandas call sneaking into the tick.
    """
    from autonoc.engine.engine import NOCEngine

    index = _machine_speed_index()
    scale = index / REF_INDEX_MS          # >1 means slower than reference
    allowed = REF_STEP_MS * scale * MAX_RATIO

    e = NOCEngine(seed=1)
    for _ in range(50):                   # warm up
        e.step()
    n = 300
    t0 = time.perf_counter()
    for _ in range(n):
        e.step()
    avg_ms = (time.perf_counter() - t0) / n * 1000

    print(f"\n  machine index {index:.1f} ms (ref {REF_INDEX_MS})"
          f" -> {scale:.2f}x reference speed"
          f"\n  step() {avg_ms:.2f} ms, allowed {allowed:.2f} ms"
          f"\n  live tick budget is 1000 ms -> using {avg_ms / 10:.2f}%")
    assert avg_ms < allowed, (
        f"step() averaged {avg_ms:.2f} ms; this machine's scaled budget is "
        f"{allowed:.2f} ms. That gap suggests an algorithmic regression "
        f"rather than slow hardware."
    )


@pytest.mark.slow
def test_I4_step_fits_live_tick_with_margin():
    """Absolute floor: one tick must fit comfortably inside a live tick.
    Even the slowest supported machine needs an order of magnitude of room,
    so the async loop is never starved.
    """
    from autonoc.engine.engine import NOCEngine

    e = NOCEngine(seed=1)
    for _ in range(50):
        e.step()
    t0 = time.perf_counter()
    for _ in range(200):
        e.step()
    avg_ms = (time.perf_counter() - t0) / 200 * 1000
    assert avg_ms < 100.0, (
        f"step() averaged {avg_ms:.2f} ms — under 10x margin against the "
        f"1000 ms live tick. Investigate before shipping."
    )


# ---------------------------------------------------------------- I9 / I10
def test_I9_rng_streams_are_independent():
    """Faults, weather, physics, traffic and ops draw from separate streams.
    Without this the counterfactual study is invalid: AI actions would
    perturb the fault sequence itself, so the two arms would inhabit
    different worlds rather than testing two policies.
    """
    from autonoc.engine.engine import NOCEngine

    e = NOCEngine(seed=7)
    streams = {
        id(e.rng_faults), id(e.rng_weather), id(e.rng_physics),
        id(e.rng_traffic), id(e.rng_ops),
    }
    assert len(streams) == 5, "RNG streams are not distinct objects"


def test_I10_schedule_is_exogenous_and_immutable():
    """The fault schedule depends only on the seed, never on engine state."""
    from autonoc.engine.faults import generate_schedule

    a = generate_schedule(seed=42, horizon=576, nodes=_dummy_nodes())
    b = generate_schedule(seed=42, horizon=576, nodes=_dummy_nodes())
    assert [ev.as_tuple() for ev in a] == [ev.as_tuple() for ev in b]
    c = generate_schedule(seed=43, horizon=576, nodes=_dummy_nodes())
    assert [ev.as_tuple() for ev in a] != [ev.as_tuple() for ev in c]


def test_I10_schedule_identical_across_ai_arms():
    """Arm A (no AI) and Arm C (autonomous) must see the same schedule."""
    from autonoc.engine.engine import NOCEngine

    a = NOCEngine(seed=99, ai_enabled=False)
    c = NOCEngine(seed=99, ai_enabled=True)
    assert [ev.as_tuple() for ev in a.schedule] == \
        [ev.as_tuple() for ev in c.schedule]


def _dummy_nodes():
    from autonoc.engine.network import build_network
    net = build_network(seed=0)
    return net.nodes
