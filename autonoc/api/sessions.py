"""In-memory browser session registry for the single Fly machine."""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

COOKIE_NAME = "autonoc_session"

@dataclass
class Session:
    token: str
    engine: object
    lock: threading.Lock
    speed: float
    history: object
    run_id: str
    reset_notice: bool = False
    run_error: str | None = None
    worker: object | None = None
    summary_store: object | None = None
    slow_ticks: int = 0
    last_seen: float = field(default_factory=time.monotonic)

class SessionCapacityError(Exception):
    pass

class InMemorySummaryStore:
    """Per-session completed-run summaries; never shared between cookies."""
    def __init__(self, max_entries: int = 20):
        self.rows = []
        self.max_entries = max_entries
    def save(self, run_id, summary):
        self.rows.insert(0, dict(summary))
        del self.rows[self.max_entries:]
    def recent(self, limit=20):
        return list(self.rows[:limit])

class SessionRegistry:
    def __init__(self, factory: Callable[[str], Session], max_sessions: int = 8,
                 idle_timeout: float = 1800):
        self.factory = factory
        self.max_sessions = max(1, int(max_sessions))
        self.idle_timeout = max(1.0, float(idle_timeout))
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def _purge(self, now: float) -> None:
        for token, session in list(self._sessions.items()):
            if now - session.last_seen > self.idle_timeout:
                if session.worker is not None:
                    session.worker.stop()
                del self._sessions[token]

    def get(self, token: str | None) -> tuple[Session, bool]:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            if token and token in self._sessions:
                session = self._sessions[token]
                session.last_seen = now
                return session, False
            if len(self._sessions) >= self.max_sessions:
                raise SessionCapacityError(
                    f"AutoNOC is at capacity ({self.max_sessions} active browser sessions). "
                    "Close an idle dashboard and try again."
                )
            token = secrets.token_urlsafe(32)
            session = self.factory(token)
            self._sessions[token] = session
            return session, True

    def count(self) -> int:
        with self._lock:
            self._purge(time.monotonic())
            return len(self._sessions)

    def clear(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                if session.worker is not None:
                    session.worker.stop()
            self._sessions.clear()
