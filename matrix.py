#!/usr/bin/env python3
"""Kill the agent with SIGKILL at every step boundary, under every policy, and count the damage."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agent import PLAN, POLICIES
from durable import Journal

STEPS = len(PLAN) * 2
WINDOWS = ("before", "effect", "recorded")


def execute(work_dir: str, mode: str, crash_at: str | None) -> tuple[int, int]:
    """Run until the agent exits cleanly. Returns (tokens spent, duplicate side effects)."""
    env = {**os.environ}
    env.pop("CRASH_AT", None)
    if crash_at:
        env["CRASH_AT"] = crash_at
    for _ in range(3):
        result = subprocess.run([sys.executable, "agent.py", work_dir, mode], env=env, check=False)
        if result.returncode == 0:
            break
        if result.returncode != -signal.SIGKILL:
            raise RuntimeError(f"agent failed with {result.returncode}")
        env.pop("CRASH_AT", None)  # the restart runs clean
    else:
        raise RuntimeError("agent never completed")
    db = sqlite3.connect(f"{work_dir}/world.db")
    tokens = db.execute("SELECT SUM(tokens) FROM spend").fetchone()[0]
    writes = db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    expected = sum(1 for _, kind in PLAN if kind == "write")
    return tokens, writes - expected


def trial(mode: str, crash_at: str | None) -> tuple[int, int]:
    with tempfile.TemporaryDirectory() as work_dir:
        return execute(work_dir, mode, crash_at)


def run_matrix() -> dict:
    baseline, _ = trial("journal+keys", None)
    report: dict = {"baseline_tokens": baseline, "crash_points": STEPS * len(WINDOWS), "modes": {}}
    for mode in POLICIES:
        extra, dupes = [], []
        for seq in range(STEPS):
            for window in WINDOWS:
                tokens, duplicates = trial(mode, f"{seq}:{window}")
                extra.append(tokens - baseline)
                dupes.append(duplicates)
        report["modes"][mode] = {
            "crashes_causing_duplicate_side_effects": sum(d > 0 for d in dupes),
            "max_duplicate_side_effects": max(dupes),
            "mean_extra_tokens": round(statistics.mean(extra)),
            "max_extra_tokens": max(extra),
            "max_extra_tokens_pct": round(100 * max(extra) / baseline, 1),
        }
    return report


def journal_write_cost(writes: int = 2000) -> dict:
    with tempfile.TemporaryDirectory() as work_dir:
        journal = Journal(f"{work_dir}/j.db", "bench")
        samples = []
        for i in range(writes):
            start = time.perf_counter()
            journal.step("noop", lambda n, key: {"n": n}, i)
            samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {
        "writes": writes,
        "p50_ms": round(samples[writes // 2], 2),
        "p99_ms": round(samples[int(writes * 0.99)], 2),
    }


if __name__ == "__main__":
    output = run_matrix()
    output["journal_write_cost"] = journal_write_cost()
    Path("results").mkdir(exist_ok=True)
    Path("results/matrix.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
