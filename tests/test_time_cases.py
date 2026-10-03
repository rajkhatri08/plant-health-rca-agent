"""eval/time_cases.py on synthetic runs (never data/): the cost check scores a small
forest_ceiling batch through cases.score_pool and writes nothing."""

import pytest

import dataset.loader as loader_mod
from dataset.loader import Runs
from eval import cases, time_cases
from tests.test_authoring import NUMBERS, authoring_runs, ready  # noqa: F401
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)


@pytest.fixture
def ctx(ready, monkeypatch):
    calls = []

    def load_faulty(fault, pool):
        calls.append((fault, pool))
        r = authoring_runs(fault)
        return Runs(r.name, fault, pool, r.columns, r.runs)

    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    return {**ready, "calls": calls}


def timed(c, **kw):
    return time_cases.run(model_path=c["model_path"], limits_path=c["out"], watch_path=c["watch"],
                          normals_path=c["normals"], repo_root=c["repo"], **kw)


def test_projection_arithmetic():
    est = time_cases.project(t_inputs=10, t_load=30, t_score=40, n_scored=20)
    assert est["per_run_s"] == 2.0
    assert est["per_fault_s"] == 30 + 445 * 2.0
    assert est["total_s"] == 10 + 12 * (30 + 445 * 2.0)


def test_scores_only_the_batch_of_one_forest_ceiling_fault(ctx, monkeypatch):
    seen = []
    real = cases.score_pool
    monkeypatch.setattr(cases, "score_pool", lambda inp, runs: seen.append(sorted(runs.runs)) or real(inp, runs))
    timed(ctx, fault=4, n_runs=2)
    assert ctx["calls"] == [(4, "forest_ceiling")]
    assert seen == [NUMBERS[:2]]


def test_writes_nothing(ctx, capsys):
    before = sorted(p.relative_to(ctx["repo"]) for p in ctx["repo"].rglob("*") if ".git" not in p.parts)
    timed(ctx, fault=1, n_runs=3)
    after = sorted(p.relative_to(ctx["repo"]) for p in ctx["repo"].rglob("*") if ".git" not in p.parts)
    assert after == before
    out = capsys.readouterr().out
    assert "s per run" in out and "projected 12 x 445 runs" in out


def test_uses_the_clock_for_each_phase(ctx):
    ticks = iter([0.0, 5.0, 25.0, 31.0])          # inputs 5 s, load 20 s, scoring 6 s for 3 runs
    est = timed(ctx, fault=1, n_runs=3, clock=lambda: next(ticks))
    assert est == time_cases.project(5.0, 20.0, 6.0, 3)


@pytest.mark.parametrize("fault, n", [(3, 5), (16, 5), (1, 0)])
def test_refuses_before_loading(ctx, fault, n):
    with pytest.raises(cases.CasesError):
        timed(ctx, fault=fault, n_runs=n)
    assert ctx["calls"] == []