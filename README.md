# durable-agent-loop

A durable agent loop in one SQLite-backed file, tested by `SIGKILL`ing it at every step boundary.

Companion to [I Killed an Agent 120 Times to See What Durable Execution Actually Buys You](https://cloudandsre.com/blog/durable-execution-for-agents-sigkill-test/).

## The result

Thirty kill points per policy: ten steps, three windows each (before the effect, after the effect, after recording it).

| Policy | Kills causing duplicate writes | Worst duplicates | Mean extra tokens |
|---|---:|---:|---:|
| No persistence | 20 / 30 | 3 | 17,967 |
| Checkpoint per turn | 6 / 30 | 1 | 6,167 |
| Step journal | 3 / 30 | 1 | 1,233 |
| Journal + idempotency keys | **0 / 30** | 0 | 1,233 |

Durable execution gets you progress that survives a crash. Avoiding duplicate effects needs an idempotency key that the receiving system honours, because a crash between "it happened" and "we recorded it" can't be closed from the caller's side.

A durable journal write took 3.02 ms at the median with `PRAGMA fullfsync=ON` on an Apple M3.

## Run it

Standard library only.

```bash
python matrix.py        # about 15 seconds
pip install -r requirements-ci.txt && pytest -q
```

## Use it

```python
from durable import Journal

journal = Journal("runs.db", run_id="incident-42")

def open_ticket(title, key):
    return ticketing.create(title=title, idempotency_key=key)

ticket = journal.step("open_ticket", open_ticket, "checkout is down")
```

Every step function receives a stable idempotency key as its last argument. After a crash, run the same code again. Recorded steps return their stored output and execution continues at the first unrecorded step. If the code no longer matches the recorded history, it raises `NonDeterminism` instead of guessing.

## Not included

Multiple workers, durable timers, compensation, workflow versioning and visibility. If you need those, use Temporal, Restate, DBOS or similar. The agent, model and tools here are scripted, the token numbers come from a cost model, and `SIGKILL` tests process death rather than power loss.

## License

Apache-2.0
