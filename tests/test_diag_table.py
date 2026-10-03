"""eval/diag_table.py: the dev diagnosis table, on synthetic runs (never data/) with patched
loaders, against a throwaway repo holding a copy of the real library and entry key.

The synthetic faults all look alike, so the numbers mean nothing here: these tests check
the rules (thresholds, top-k, per-entry counts), which pools are read, leave-one-out, the
record and the table."""

import json
import shutil
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path

import numpy as np
import pytest

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import cases, diag_table as dt, run_record
from eval import diag_metrics as dm
from ingest import tags as tagmap
from tests.test_approve_entry import commit
from tests.test_authoring import ANALYZERS, INTERVAL, NUMBERS, QUIET, authoring_runs, hold, ready  # noqa: F401
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)
from tests.test_fit_pca import FAST, two_factor_runs

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)      # after every committed approval
SPIKED = NUMBERS[1]                                          # the normal run with a false alert


def normal_runs():
    runs = two_factor_runs(numbers=NUMBERS, samples=120, seed=99)
    fast = tagmap.column_indices(VARIABLES, FAST)
    an = dict(zip(ANALYZERS, tagmap.column_indices(VARIABLES, ANALYZERS)))
    for k, x in runs.runs.items():
        if k == SPIKED:
            x[50:62, fast] += np.float32(3.0)                # one excursion, no onset: a false alert
        for t, c in an.items():
            x[:, c] = hold(x[:, c], INTERVAL[t])
    return Runs("fault_free_training", 0, "dev", VARIABLES, runs.runs)


@pytest.fixture
def ctx(ready, monkeypatch, tmp_path):
    repo = ready["repo"]
    shutil.copytree(REPO / "library", repo / "library")
    (repo / "eval").mkdir(exist_ok=True)
    shutil.copyfile(REPO / "eval" / "entry_provenance.yaml", repo / "eval" / "entry_provenance.yaml")
    shutil.copytree(REPO / "eval" / "provenance", repo / "eval" / "provenance")
    commit(repo)
    calls = []

    def load_faulty(fault, pool):
        calls.append((fault, pool))
        r = authoring_runs(fault)
        return Runs(r.name, fault, pool, r.columns, r.runs)

    def load_normal(pool):
        calls.append((0, pool))
        return normal_runs()

    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    return {**ready, "calls": calls, "tables": tmp_path / "tables"}


def table(c, **kw):
    return dt.run(c["model_path"], c["out"], c["watch"], c["normals"], tables_dir=c["tables"],
                  repo_root=c["repo"], now=kw.pop("now", NOW), n_boot=kw.pop("n_boot", 50), **kw)


# ---------- the 95% decline threshold ----------

def test_threshold_accepts_at_least_95_percent():
    values = [F(i, 20) for i in range(20, 0, -1)]            # 1, 19/20, ..., 1/20
    t, acc, short = dt.threshold_95(values, [True] * 20)
    assert (t, acc, short) == (F(2, 20), F(19, 20), False)   # the 19th largest


def test_threshold_ties_at_the_threshold_are_all_accepted():
    values = [F(1)] * 10 + [F(1, 2)] * 10
    t, acc, short = dt.threshold_95(values, [True] * 20)
    assert t == F(1, 2) and acc == 1


def test_threshold_ineligible_cases_count_as_not_accepted():
    # 3 of 20 have a required contradiction everywhere: 85% is the most that can be accepted
    values = [F(1)] * 20
    eligible = [True] * 17 + [False] * 3
    t, acc, short = dt.threshold_95(values, eligible)
    assert (t, acc, short) == (F(1), F(17, 20), True)


def test_threshold_works_for_forest_probabilities():
    t, acc, short = dt.threshold_95([0.9, 0.8, 0.5, 0.4], [True] * 4)
    assert t == 0.4 and acc == 1 and not short               # ceil(0.95 x 4) = 4


def test_threshold_refusals():
    with pytest.raises(dt.DiagTableError):
        dt.threshold_95([], [])
    with pytest.raises(dt.DiagTableError):
        dt.threshold_95([F(1)], [False])


# ---------- top-k ----------

def case(right, ranking):
    return dm.Case(run=1, fault=1, family="F", right=right, ranking=ranking, declined=False)


def test_choose_k_is_the_smallest_reaching_95_percent():
    cases_ = [case("a", (("a",), ("b",), ("c",)))] * 18 + [case("a", (("b",), ("c",), ("a",)))] * 2
    assert dt.choose_k(cases_, 3) == 3                       # top-2 recall is 90%
    assert dt.choose_k(cases_[:18] + cases_[:1], 3) == 1


def test_choose_k_counts_ties_fractionally():
    cases_ = [case("a", (("a", "b"), ("c",)))] * 20          # recall 1/2 at k = 1, 1 at k = 2
    assert dt.choose_k(cases_, 3) == 2


# ---------- per-entry results ----------

def test_per_entry_counts_ties_fractionally_and_skips_declines():
    cs = [case("a", (("a",), ("b",))), case("a", (("a", "b"),)), case("b", (("a",), ("b",))),
          dm.Case(run=2, fault=1, family="F", right="b", ranking=(("a",),), declined=True)]
    got = dt.per_entry(cs, ["a", "b"])
    assert got["a"] == {"cases": 2, "picked_right": F(3, 2), "picked_wrong": F(1)}
    assert got["b"] == {"cases": 2, "picked_right": F(0), "picked_wrong": F(1, 2)}


# ---------- the whole table ----------

def test_reads_only_dev_authoring_ceiling_of_known_faults_and_normal_dev(ctx):
    table(ctx)
    faulty = [(f, p) for f, p in ctx["calls"] if f]
    assert sorted({p for _, p in faulty}) == ["authoring", "dev", "forest_ceiling"]
    assert {f for f, _ in faulty} == set(cases.KNOWN_FAULTS)
    assert [c for c in ctx["calls"] if c[0] == 0] == [(0, "dev")]


def test_record_and_table(ctx):
    results, record = table(ctx)
    rec = json.loads(record.read_text())
    assert rec["name"] == "diag_table" and rec["dirty"] is False
    assert rec["seeds"] == {"bootstrap": dt.BOOTSTRAP_SEED, "forest": 20261002}
    assert len(rec["config"]["library"]) == 12 and rec["config"]["headline"] == "provisional"
    path = Path(rec["outputs"]["table"]["path"])
    path = path if path.is_absolute() else ctx["repo"] / path
    assert rec["outputs"]["table"]["sha256"] == run_record.sha256(path)
    text = path.read_text()
    assert "## Provisional (headline)" in text and "## Revised" in text and "Leave-one-out" in text
    for at in dt.TIMES:
        m = rec["metrics"][at]
        assert set(m["methods"]) == set(dt.METHODS)
        assert m["counts"]["known"] >= 12 * 4                     # the stepped runs are detected
        assert m["counts"]["false_alerts"] >= 1
        assert 1 <= m["k"] <= 12
        for name in ("matcher", "forest5", "ceiling"):
            th = m["thresholds"][name]
            assert th["accepted"] >= 0.95 or th["short"] is True
        assert m["methods"]["random"]["top1"] == pytest.approx(1 / 12)
        assert m["methods"]["random"]["false_alert_declined"] == 0
        assert set(m["paired"]) == {"matcher_vs_forest5", "matcher_vs_ceiling"}
        assert sum(v["cases"] for v in m["methods"]["matcher"]["per_entry"].values()) == m["counts"]["known"]


def test_leave_one_out(ctx):
    results, _ = table(ctx)
    for at in dt.TIMES:
        loo = results[at]["loo"]
        assert loo["left_out"] == {"2": "mixed-feed-inert-rise", "11": "reactor-cooling-water-temperature-wander"}
        per_entry = results[at]["methods"]["matcher"]["per_entry"]
        own = per_entry["mixed-feed-inert-rise"]["cases"] + per_entry["reactor-cooling-water-temperature-wander"]["cases"]
        assert loo["matcher"]["cases"] == loo["forest5"]["cases"] == own >= 8      # those faults' dev cases
        assert loo["forest5"]["classes"] == 10 and loo["ceiling"]["classes"] == 10
        assert loo["random"]["declined"] == 0
        assert results[at]["thresholds"]["forest5"]["classes"] == 12


def test_false_alerts_come_from_the_spiked_normal_run(ctx, monkeypatch):
    seen = []
    real = cases.score_normal
    monkeypatch.setattr(cases, "score_normal", lambda inp, runs: seen.append(real(inp, runs)) or seen[-1])
    table(ctx)
    (rows,) = seen
    assert [r["run"] for r in rows if r["notifications"]] == [SPIKED]


def test_refuses_a_dirty_tree_before_loading(ctx):
    (ctx["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        table(ctx)
    assert ctx["calls"] == []


def test_refuses_a_known_fault_without_an_entry_in_force(ctx):
    # before the approvals were made, nothing is in force
    with pytest.raises(dt.DiagTableError, match="without an entry in force"):
        table(ctx, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert ctx["calls"] == []


def test_never_overwrites_the_table(ctx):
    ctx["tables"].mkdir(parents=True)
    (ctx["tables"] / f"{NOW.strftime('%Y%m%dT%H%M%SZ')}_diag_table.md").write_text("kept")
    with pytest.raises(FileExistsError):
        table(ctx)
    assert ctx["calls"] == []