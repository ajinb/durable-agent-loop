import pytest

import matrix
from durable import Journal, NonDeterminism


def run_steps(journal, calls):
    def fn(name, key):
        calls.append(name)
        return {"done": name}

    return [journal.step(name, fn, name) for name in ("a", "b")]


def test_recorded_steps_replay_without_executing(tmp_path):
    db, calls = str(tmp_path / "j.db"), []
    first = run_steps(Journal(db, "r1"), calls)
    again = Journal(db, "r1")
    assert run_steps(again, calls) == first
    assert calls == ["a", "b"]
    assert again.replayed == 2


def test_runs_are_isolated(tmp_path):
    db, calls = str(tmp_path / "j.db"), []
    run_steps(Journal(db, "r1"), calls)
    run_steps(Journal(db, "r2"), calls)
    assert calls == ["a", "b", "a", "b"]


def test_changed_code_is_refused_not_replayed(tmp_path):
    db = str(tmp_path / "j.db")
    Journal(db, "r1").step("charge_card", lambda amount, key: amount, 10)
    with pytest.raises(NonDeterminism, match="charge_card"):
        Journal(db, "r1").step("refund_card", lambda amount, key: amount, 10)


def test_changed_input_is_refused(tmp_path):
    db = str(tmp_path / "j.db")
    Journal(db, "r1").step("charge_card", lambda amount, key: amount, 10)
    with pytest.raises(NonDeterminism):
        Journal(db, "r1").step("charge_card", lambda amount, key: amount, 99)


def test_each_step_gets_a_stable_key(tmp_path):
    seen = []
    journal = Journal(str(tmp_path / "j.db"), "r1")
    journal.step("x", lambda key: seen.append(key) or 1)
    journal.step("y", lambda key: seen.append(key) or 2)
    assert seen == ["r1:0", "r1:1"]


@pytest.mark.parametrize("mode", ["journal+keys"])
@pytest.mark.parametrize("seq", range(matrix.STEPS))
@pytest.mark.parametrize("window", matrix.WINDOWS)
def test_journal_with_keys_never_duplicates_under_sigkill(mode, seq, window):
    assert matrix.trial(mode, f"{seq}:{window}")[1] == 0


def test_journal_without_keys_duplicates_in_the_effect_window():
    # step 3 is open_ticket: the ticket exists, the record of it does not
    assert matrix.trial("journal", "3:effect")[1] == 1


def test_journal_without_keys_is_safe_after_recording():
    assert matrix.trial("journal", "3:recorded")[1] == 0


def test_no_persistence_repeats_everything():
    # die on the last step: every write before it happens again
    assert matrix.trial("naive", f"{matrix.STEPS - 1}:before")[1] == 3
