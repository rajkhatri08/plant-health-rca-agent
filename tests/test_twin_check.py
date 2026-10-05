"""eval/twin_check.py (decision 57; S0 answer 9; S1 Q3), on synthetic runs.

load_testing is replaced by a fake, so nothing here reads data or sets EVAL_MODE.
"""

import json

import numpy as np
import pytest

from dataset import loader as loader_mod
from dataset.convert import VARIABLES
from eval import twin_check as tc
from ingest import tags as tagmap

RUNS, SAMPLES, ONSET = 4, 170, 160


def normal_runs():
    rng = np.random.default_rng(0)
    return {k: rng.normal(size=(SAMPLES, len(VARIABLES))).astype(np.float32) for k in range(1, RUNS + 1)}


@pytest.fixture
def fake(monkeypatch):
    """faults[f] = a function (k, twin array) -> faulty array; default: a copy, changed after 160."""
    normal, faults, calls = normal_runs(), {}, []

    def after_onset(k, twin):
        a = twin.copy()
        a[ONSET:] += 1.0
        return a

    def load_testing(fault, *, purpose):
        calls.append((fault, purpose))
        if fault == 0:
            return loader_mod.Runs("fault_free_testing", 0, "test", VARIABLES, normal)
        make = faults.get(fault, after_onset)
        return loader_mod.Runs("faulty_testing", fault, "test", VARIABLES,
                               {k: make(k, a) for k, a in normal.items()})

    monkeypatch.setattr(loader_mod, "load_testing", load_testing)
    return {"faults": faults, "calls": calls, "normal": normal}


def test_all_twins_shared(fake, git_repo):
    m, record = tc.run(repo_root=git_repo, out=lambda s: None)
    assert m["verdict"] == "shared"
    assert m["faults"] == {str(f): {"runs": RUNS, "match": RUNS} for f in range(1, 21)}
    assert fake["calls"] == [(f, "twin_check") for f in range(0, 21)]
    rec = json.loads(record.read_text())
    assert rec["config"]["samples"] == [1, ONSET] and rec["config"]["n_tags"] == 33


def test_one_run_differing_before_the_onset_makes_it_not_shared(fake, git_repo):
    def early(k, twin):
        a = twin.copy()
        if k == 2:
            a[ONSET - 1, tagmap.column_indices(VARIABLES, tagmap.fast_tags())[0]] += 1.0   # sample 160
        return a

    fake["faults"][7] = early
    m, _ = tc.run(repo_root=git_repo, out=lambda s: None)
    assert m["verdict"] == "not shared"
    assert m["faults"]["7"] == {"runs": RUNS, "match": RUNS - 1}
    assert all(v["match"] == RUNS for f, v in m["faults"].items() if f != "7")


def test_a_difference_outside_the_fast_tags_doesnt_count(fake, git_repo):
    fast = set(tagmap.column_indices(VARIABLES, tagmap.fast_tags()))
    other = next(i for i in range(len(VARIABLES)) if i not in fast)

    def slow_only(k, twin):
        a = twin.copy()
        a[:ONSET, other] += 1.0
        return a

    fake["faults"][3] = slow_only
    assert tc.run(repo_root=git_repo, out=lambda s: None)[0]["verdict"] == "shared"


def test_the_record_holds_counts_only(fake, git_repo):
    _, record = tc.run(repo_root=git_repo, out=lambda s: None)
    rec = json.loads(record.read_text())
    assert rec["outputs"] == {} and rec["config"]["split"] == "test"
    for v in rec["metrics"]["faults"].values():
        assert set(v) == {"runs", "match"}


def test_mismatched_run_numbers_refused(fake, git_repo, monkeypatch):
    real = loader_mod.load_testing

    def fewer(fault, *, purpose):
        runs = real(fault, purpose=purpose)
        if fault == 1:
            runs.runs.pop(1)
        return runs

    monkeypatch.setattr(loader_mod, "load_testing", fewer)
    with pytest.raises(ValueError, match="aren't the normal test run numbers"):
        tc.run(repo_root=git_repo, out=lambda s: None)


def test_dirty_tree_refused_before_any_load(fake, git_repo):
    (git_repo / "code.py").write_text("x = 2\n")
    with pytest.raises(Exception, match="dirty"):
        tc.run(repo_root=git_repo, out=lambda s: None)
    assert fake["calls"] == []