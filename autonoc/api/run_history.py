"""Persistent summaries for completed demo runs.

Only aggregate summaries are retained here. Live engine state is intentionally
never serialized: a process restart starts a fresh simulation at Day 1.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


class RunSummaryStore:
    """Small SQLite-backed, bounded history of completed simulations."""

    def __init__(
        self,
        data_dir: str | os.PathLike[str] | None = None,
        *,
        max_entries: int = 50,
    ) -> None:
        root = Path(
            data_dir
            or os.environ.get("AUTONOC_DATA_DIR")
            or (Path.cwd() / "data")
        )
        self.path = root if root.suffix == ".sqlite3" else root / "run_summaries.sqlite3"
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS completed_runs (
                       run_id TEXT PRIMARY KEY,
                       completed_at TEXT NOT NULL,
                       payload TEXT NOT NULL
                   )"""
            )
            return connection
        except Exception:
            connection.close()
            raise

    def save(self, run_id: str, summary: dict[str, Any]) -> None:
        """Persist before the caller swaps out the completed world.

        `run_id` is an internal idempotency key only; it is not returned as a
        dashboard label. Retrying a failed reset cannot duplicate a summary.
        """
        payload = json.dumps(summary, separators=(",", ":"), allow_nan=False)
        with self._lock:
            connection = self._open()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO completed_runs "
                    "(run_id, completed_at, payload) VALUES (?, ?, ?)",
                    (run_id, summary["completed_at"], payload),
                )
                connection.execute(
                    """DELETE FROM completed_runs
                       WHERE run_id NOT IN (
                           SELECT run_id FROM completed_runs
                           ORDER BY completed_at DESC, rowid DESC
                           LIMIT ?
                       )""",
                    (self.max_entries,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the newest summaries, labeled by their completion time."""
        limit = max(1, min(int(limit), self.max_entries))
        with self._lock:
            connection = self._open()
            try:
                rows = connection.execute(
                    """SELECT payload FROM completed_runs
                       ORDER BY completed_at DESC, rowid DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            finally:
                connection.close()
        return [json.loads(row[0]) for row in rows]
