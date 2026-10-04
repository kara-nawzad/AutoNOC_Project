"""Anonymous browser sessions are isolated and bounded."""
import time
from types import SimpleNamespace

from autonoc.api.sessions import Session, SessionRegistry


def test_two_browser_clients_have_independent_controls():
    from fastapi.testclient import TestClient
    from autonoc.api import main as M

    with TestClient(M.app) as first:
        second = TestClient(M.app)
        a = first.get("/api/data"); b = second.get("/api/data")
        assert a.status_code == b.status_code == 200
        da, db = a.json(), b.json()
        assert da["run_id"] != db["run_id"]
        run_a, run_b = da["run_id"], db["run_id"]
        node = da["nodes"][0]["id"]
        assert first.post("/api/control/speed", params={"value": 4, "run_id": run_a}).status_code == 200
        assert first.post("/api/control/pause", params={"run_id": run_a}).status_code == 200
        assert first.post("/api/control/ai", params={"enabled": "true", "run_id": run_a}).status_code == 200
        assert first.post("/api/control/inject", params={"node_id": node, "kind": 3, "run_id": run_a}).status_code == 200
        a2, b2 = first.get("/api/data").json(), second.get("/api/data").json()
        assert a2["control"]["speed"] == 4 and a2["control"]["paused"]
        assert a2["ai"]["ai_enabled"] is True
        assert b2["control"]["speed"] == 1 and not b2["control"]["paused"]
        assert b2["ai"]["ai_enabled"] is False
        assert next(n for n in a2["nodes"] if n["id"] == node)["status"] == 3
        assert next(n for n in b2["nodes"] if n["id"] == node)["status"] != 3
        assert second.post("/api/control/pause", params={"run_id": run_a}).status_code == 409


def test_registry_expires_idle_sessions_and_reports_capacity():
    created = []
    def factory(token):
        session = Session(token, object(), object(), 1.0, object(), token)
        created.append(session)
        return session

    registry = SessionRegistry(factory, max_sessions=1, idle_timeout=1)
    first, is_new = registry.get(None)
    assert is_new and registry.count() == 1
    try:
        registry.get(None)
    except Exception as exc:
        assert "capacity" in str(exc)
    else:
        raise AssertionError("capacity must reject a second active session")
    first.last_seen = time.monotonic() - 2
    second, is_new = registry.get(None)
    assert is_new and second.token != first.token


def test_cookie_tokens_are_not_client_selected_ids():
    def factory(token):
        return Session(token, object(), object(), 1.0, object(), "run")
    registry = SessionRegistry(factory, max_sessions=3, idle_timeout=60)
    a, _ = registry.get(None)
    b, _ = registry.get(None)
    assert a.token != b.token
    # A token resolves only to its own record; an arbitrary client value does not.
    c, new = registry.get("not-a-real-token")
    assert new and c.token not in {a.token, b.token}
