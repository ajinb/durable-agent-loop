"""A durable step journal for agent loops, in one file, on SQLite.

Every model call and tool call is a step. The first time a step runs, its output is recorded.
After a crash the process runs the same code again from the top, and recorded steps return their
stored output instead of executing. Execution continues live from the first unrecorded step.

Recording happens after the effect, so a crash between the two re-executes the step. That window
cannot be closed from this side. The idempotency key handed to each step is how the system on the
other side closes it.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sqlite3
from collections.abc import Callable
from typing import Any

SCHEMA = """CREATE TABLE IF NOT EXISTS steps(
    run_id TEXT, seq INTEGER, name TEXT, input_hash TEXT, output TEXT,
    PRIMARY KEY (run_id, seq))"""


class NonDeterminism(RuntimeError):
    """The code no longer matches the recorded history for this run."""


def _maybe_crash(seq: int, window: str) -> None:
    # Test hook: CRASH_AT="3:effect" kills the process in that window with a real SIGKILL.
    if os.environ.get("CRASH_AT") == f"{seq}:{window}":
        os.kill(os.getpid(), signal.SIGKILL)


class Journal:
    """`commit` is "step" (durable), "turn" (checkpoint at turn end) or "never" (no persistence)."""

    def __init__(self, path: str, run_id: str, commit: str = "step", keys: bool = True):
        if commit not in ("step", "turn", "never"):
            raise ValueError(f"unknown commit policy {commit!r}")
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA fullfsync=ON")  # plain fsync on macOS stops at the drive cache
        self.db.execute(SCHEMA)
        self.run_id, self.commit, self.keys = run_id, commit, keys
        self.seq, self.replayed, self.buffer = 0, 0, []

    def step(self, name: str, fn: Callable[..., Any], *args: Any) -> Any:
        seq, self.seq = self.seq, self.seq + 1
        digest = hashlib.sha256(json.dumps([name, args], sort_keys=True).encode()).hexdigest()
        row = self.db.execute(
            "SELECT name, input_hash, output FROM steps WHERE run_id=? AND seq=?",
            (self.run_id, seq),
        ).fetchone()
        if row:
            if (row[0], row[1]) != (name, digest):
                raise NonDeterminism(f"step {seq}: history has {row[0]!r}, code asked for {name!r}")
            self.replayed += 1
            return json.loads(row[2])

        _maybe_crash(seq, "before")
        key = f"{self.run_id}:{seq}" if self.keys else None
        output = fn(*args, key)
        _maybe_crash(seq, "effect")
        record = (self.run_id, seq, name, digest, json.dumps(output))
        if self.commit == "step":
            self._write([record])
        elif self.commit == "turn":
            self.buffer.append(record)
        _maybe_crash(seq, "recorded")
        return output

    def end_turn(self) -> None:
        if self.commit == "turn" and self.buffer:
            self._write(self.buffer)
            self.buffer = []

    def _write(self, records: list[tuple]) -> None:
        with self.db:
            self.db.executemany("INSERT INTO steps VALUES (?,?,?,?,?)", records)
