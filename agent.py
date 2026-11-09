#!/usr/bin/env python3
"""An incident-response agent, scripted so that every run makes the same decisions.

The model and the ticketing, paging and status systems are stand-ins. They live in world.db so
their state survives the agent being killed, exactly like the real systems would.
usage: agent.py WORK_DIR {naive,checkpoint,journal,journal+keys}
"""

from __future__ import annotations

import sqlite3
import sys

from durable import Journal

POLICIES = {
    "naive": ("never", False),
    "checkpoint": ("turn", False),
    "journal": ("step", False),
    "journal+keys": ("step", True),
}
# Context grows each turn, the way a real agent's message history does.
PLAN = [
    ("search_logs", "read"),
    ("open_ticket", "write"),
    ("page_oncall", "write"),
    ("post_status", "write"),
    ("close_out", "read"),
]
INPUT_TOKENS, GROWTH, OUTPUT_TOKENS = 4000, 1500, 400


class World:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS spend(tokens INTEGER)")
        self.db.execute("CREATE TABLE IF NOT EXISTS effects(kind TEXT, key TEXT UNIQUE)")

    def model(self, turn: int, key: str | None) -> dict:
        self.db.execute(
            "INSERT INTO spend VALUES (?)", (INPUT_TOKENS + GROWTH * turn + OUTPUT_TOKENS,)
        )
        return {"tool": PLAN[turn][0]}

    def tool(self, kind: str, key: str | None) -> dict:
        if dict(PLAN)[kind] == "write":
            # The remote system deduplicates on the key when the caller sends one.
            self.db.execute("INSERT OR IGNORE INTO effects VALUES (?,?)", (kind, key))
        return {"ok": kind}


def run(work_dir: str, mode: str) -> None:
    commit, keys = POLICIES[mode]
    world = World(f"{work_dir}/world.db")
    journal = Journal(f"{work_dir}/journal.db", "incident-42", commit=commit, keys=keys)
    for turn in range(len(PLAN)):
        decision = journal.step("model", world.model, turn)
        journal.step(decision["tool"], world.tool, decision["tool"])
        journal.end_turn()


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
