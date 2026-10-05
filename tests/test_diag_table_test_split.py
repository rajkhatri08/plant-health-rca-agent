"""eval/diag_table.py, week 7 S1c: the diag_fingerprint record (dev) and --split test, on
synthetic runs only.

The dev loaders serve test_diag_table's synthetic runs; load_testing is replaced by a fake
serving synthetic "testing" runs (onset after sample 160, faults 1-20), and the sealed
folder is a tmp_path. Nothing here reads data, opens the real sealed folder or sets
EVAL_MODE. The synthetic faults look alike, so the numbers mean nothing: these tests check
the order (fingerprint before any test load), the rules (set on dev, never on test), the
cases, the scopes and where every output goes.
"""

import json
from datetime import datetime, timezone

import numpy as np
import pytest

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import diag_table as dt
from eval import split as split_mod
from ingest import tags as tagmap
from tests.test_authoring import ANALYZERS, INTERVAL, hold, ready  # noqa: F401 (fixture)
from tests.test_calibrate_driver import setup  # noqa: F401 (fixture)
from tests.test_diag_table import NOW, ctx, table  # noqa: F401 (fixture)
from tests.test_fit_pca import FAST, two_factor_runs

LATER = datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc)      # the test run's own clock
AS_OF = NOW                                                 # the pinned library clock
SAMPLES = 300
DRAW = split_mod.test_draw()
TEST_NUMBERS = DRAW[:3] + [n for n in range(1, 501) if n not in DRAW][:2]
SPIKED = DRAW[0]                                            # a normal testing run with a false alert


def _held(x):
    an = dict(zip(ANALYZERS, tagmap.column_indices(VARIABLES, ANALYZERS)))
    for t, c in an.items():
        x[:, c] = hold(x[:, c], INTERVAL[t])
    return x


def synthetic_testing_runs(fault):
    runs = two_factor_runs(numbers=TEST_NUMBERS, samples=SAMPLES, seed=500 + fault)
    fast = tagmap.column_indices(VARIABLES, FAST)
    for k, x in runs.runs.items():
        if fault:
            x[160:, fast] += np.float32(1.5 + 0.3 * fault)
        elif k == SPIKED:
            x[50:62, fast] += np.float32(3.0)
        _held(x)
    name = "faulty_testing" if fault else "fault_free_testing"
    return Runs(name, fault, "test", VARIABLES, runs.runs)


@pytest.fixture
def tc(ctx, monkeypatch, tmp_path):
    sealed = tmp_path / "sealed"
    monkeypatch.setattr(loader_mod, "SEALED_ROOT", sealed)
    test_calls = []

    def load_testing(fault, *, purpose):
        test_calls.append((fault, purpose))
        return synthetic_testing_runs(fault)

    monkeypatch.setattr(loader_mod, "load_testing", load_testing)
    return {**ctx, "test_calls": test_calls, "sealed": sealed}


def make_fingerprint(c):
    table(c, library_as_of=AS_OF, fingerprint_out=True)
    (fp,) = (c["repo"] / "eval" / "runs").glob("*_diag_fingerprint.json")
    return fp


def run_test(c, fp, **kw):
    return table(c, split="test", library_as_of=AS_OF, fingerprint_record=fp, now=LATER, **kw)


# ---------- the draw and the leave-one-out refs ----------

def test_the_test_draw_is_ten_sorted_distinct_numbers_from_its_seed():
    assert len(DRAW) == 10 and DRAW == sorted(set(DRAW)) and all(1 <= n <= 500 for n in DRAW)
    expected = sorted(int(x) for x in np.random.default_rng(20261006).choice(list(range(1, 501)), 10, replace=False))
    assert DRAW == expected and split_mod.TEST_SEED == 20261006


def test_loo_refs_are_s0_answer_16():
    assert dt.LOO_TEST == {1: "mixed-feed-reactant-ratio-shift", 4: "reactor-cooling-water-warm-supply",
                           5: "condenser-cooling-water-warm-supply", 13: "reaction-rate-drift"}


def test_loo_refs_checked_against_the_library():
    class Rev:
        def __init__(self, revision):
            self.revision = revision
    revs = {e: Rev(1) for e in dt.LOO_TEST.values()}
    right_of = {f: e for f, e in dt.LOO_TEST.items()}
    dt.check_loo_refs(revs, right_of)
    with pytest.raises(dt.DiagTableError, match="should remove"):
        dt.check_loo_refs({**revs, "reaction-rate-drift": Rev(2)}, right_of)
    with pytest.raises(dt.DiagTableError, match="should remove"):
        dt.check_loo_refs(revs, {**right_of, 13: "something-else"})


# ---------- the fingerprint record (dev) ----------

def test_fingerprint_record_holds_hashes_and_exact_rules(tc):
    fp = json.loads(make_fingerprint(tc).read_text())
    assert fp["name"] == "diag_fingerprint" and fp["config"]["as_of"] == AS_OF.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert "scikit-learn" in fp["library_versions"]
    for at in dt.TIMES:
        m = fp["metrics"][at]
        assert set(m) == {"k", "matcher", "cases", "forest5", "ceiling"}
        assert "/" in m["matcher"]["threshold"] or m["matcher"]["threshold"].isdigit()     # an exact Fraction
        assert len(m["matcher"]["rankings_sha256"]) == 64
        for name in ("forest5", "ceiling"):
            assert len(m[name]["proba_sha256"]) == 64 and float(m[name]["threshold"]) == float(m[name]["threshold"])
    assert tc["test_calls"] == []                                  # dev only


def test_fingerprint_is_reproducible(tc):
    first = json.loads(make_fingerprint(tc).read_text())["metrics"]
    for p in (tc["repo"] / "eval" / "runs").glob("*_diag_*.json"):
        p.unlink()
    for p in tc["tables"].glob("*.md"):
        p.unlink()
    assert json.loads(make_fingerprint(tc).read_text())["metrics"] == first


def test_a_different_forest_changes_the_fingerprint(tc, monkeypatch):
    first = json.loads(make_fingerprint(tc).read_text())["metrics"]
    for p in (tc["repo"] / "eval" / "runs").glob("*_diag_*.json"):
        p.unlink()
    for p in tc["tables"].glob("*.md"):
        p.unlink()
    monkeypatch.setitem(dt.forest.HYPERPARAMS, "random_state", 1)
    second = json.loads(make_fingerprint(tc).read_text())["metrics"]
    assert any(second[at][f]["proba_sha256"] != first[at][f]["proba_sha256"]
               for at in dt.TIMES for f in ("forest5", "ceiling"))


@pytest.mark.parametrize("kw, match", [
    ({"fingerprint_out": True}, "needs --library-as-of"),
    ({"split": "test", "library_as_of": AS_OF}, "needs --fingerprint-record"),
    ({"split": "test", "fingerprint_record": "x"}, "needs --fingerprint-record and --library-as-of"),
    ({"fingerprint_record": "x"}, "only for --split test"),
    ({"library_as_of": datetime(2026, 10, 5)}, "time zone"),
])
def test_argument_refusals_before_anything_is_loaded(tc, kw, match):
    with pytest.raises(dt.DiagTableError, match=match):
        table(tc, **kw)
    assert tc["calls"] == [] and tc["test_calls"] == []


# ---------- the test run: the fingerprint first, then the test loads ----------

def test_dev_rules_are_checked_before_the_first_test_load(tc):
    fp = make_fingerprint(tc)
    tc["calls"].clear()
    run_test(tc, fp)
    assert tc["calls"] and all(pool != "test" for _, pool in tc["calls"])        # dev and training first
    faults = [f for f, _ in tc["test_calls"]]
    assert faults == [1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 16, 17, 18, 19, 20, 0]
    assert {p for _, p in tc["test_calls"]} == {"test_diag_table"}


def test_a_fingerprint_mismatch_stops_before_any_test_load(tc):
    fp = make_fingerprint(tc)
    doc = json.loads(fp.read_text())
    doc["metrics"]["provisional"]["forest5"]["proba_sha256"] = "0" * 64
    fp.write_text(json.dumps(doc))
    with pytest.raises(dt.DiagTableError, match="provisional.forest5"):
        run_test(tc, fp)
    assert tc["test_calls"] == []


@pytest.mark.parametrize("change", ["as_of", "library", "dirty", "name"])
def test_a_fingerprint_for_something_else_is_refused_before_any_load(tc, change):
    fp = make_fingerprint(tc)
    doc = json.loads(fp.read_text())
    if change == "as_of":
        doc["config"]["as_of"] = "2026-10-01T00:00:00Z"
    elif change == "library":
        doc["config"]["library"]["reaction-rate-drift"] = "reaction-rate-drift@r9"
    elif change == "dirty":
        doc["dirty"] = True
    fp.write_text(json.dumps(doc))
    if change == "name":
        fp = fp.rename(fp.with_name("20261005T000000Z_other.json"))
    tc["calls"].clear()
    with pytest.raises(dt.DiagTableError):
        run_test(tc, fp)
    assert tc["calls"] == [] and tc["test_calls"] == []


# ---------- the test results ----------

def test_rules_on_test_are_the_fingerprints(tc):
    path = make_fingerprint(tc)
    fp = json.loads(path.read_text())
    results, _ = run_test(tc, path)
    for at in dt.TIMES:
        r, f = results[at]["rules"], fp["metrics"][at]
        assert r["k"] == f["k"] and r["matcher"] == f["matcher"]["threshold"]
        assert r["forest5"] == f["forest5"]["threshold"] and r["ceiling"] == f["ceiling"]["threshold"]


def test_cases_scopes_unknowns_and_leave_one_out(tc):
    results, _ = run_test(tc, make_fingerprint(tc))
    for at in dt.TIMES:
        full, sub = results[at]["full"], results[at]["subsample"]
        assert full["counts"]["known_fault_runs"] == 12 * len(TEST_NUMBERS)
        assert sub["counts"]["known_fault_runs"] == 12 * 10
        assert 0 < sub["counts"]["known"] <= full["counts"]["known"]
        assert 0 < full["counts"]["unknown"] and sub["counts"]["unknown"] <= full["counts"]["unknown"]
        assert full["counts"]["false_alerts"] >= sub["counts"]["false_alerts"] >= 1      # the spiked run is drawn
        for scope in (full, sub):
            assert set(scope["methods"]) == {"matcher", "forest5", "ceiling", "random"}
            assert set(scope["unknown"]["matcher"]["by_fault"]) == {"16", "17", "18", "19", "20"}
            assert scope["unknown"]["random"]["declined"] == 0
            assert set(scope["loo"]) == {"1", "4", "5", "13"}
            for f, row in scope["loo"].items():
                assert row["left_out"] == dt.LOO_TEST[int(f)]
                assert row["forest5"]["classes"] == 11 and row["ceiling"]["classes"] == 11
        assert "paired" in sub and "paired" not in full
        assert set(sub["paired"]) == {"matcher_vs_forest5", "matcher_vs_ceiling"}


def test_per_case_rows_go_to_the_sealed_folder_and_the_record_holds_aggregates(tc):
    _, record = run_test(tc, make_fingerprint(tc))
    rec = json.loads(record.read_text())
    text = record.read_text()
    out = rec["outputs"]["cases"]["path"]
    assert out.startswith("sealed:test_outputs/") and out.endswith("_test_diag_table/cases.jsonl")
    assert str(tc["sealed"]) not in text
    rows = [json.loads(line) for line in
            (tc["sealed"] / out.removeprefix("sealed:")).read_text().splitlines()]
    kinds = {r["kind"] for r in rows}
    assert {"known", "unknown", "false", "loo_1", "loo_4", "loo_5", "loo_13"} <= kinds
    assert {r["method"] for r in rows} == {"matcher", "forest5", "ceiling"}
    assert any(r["in_draw"] for r in rows) and any(not r["in_draw"] for r in rows)
    # The committed record: no run number of any test case appears as a value.
    assert rec["config"]["split"] == "test" and rec["config"]["subsample"] == {"seed": 20261006, "runs": 10}
    assert rec["config"]["llm_only"].startswith("not run")
    assert rec["seeds"] == {"bootstrap": dt.BOOTSTRAP_SEED, "forest": dt.forest.SEED, "subsample": 20261006}


def test_the_test_table_is_aggregates_from_the_results(tc):
    run_test(tc, make_fingerprint(tc))
    (md,) = tc["tables"].glob("*_test_diag_table.md")
    text = md.read_text()
    assert text.startswith("# Test diagnosis table")
    assert "### All detected test runs" in text and "### The subsample" in text
    assert "Unknown faults declined, by fault" in text and "| 13 | reaction-rate-drift | matcher |" in text
    assert "_diag_fingerprint.json" in text


def test_a_dirty_tree_is_refused_before_anything(tc):
    fp = make_fingerprint(tc)
    (tc["repo"] / "code.py").write_text("x = 3\n")
    tc["calls"].clear()
    with pytest.raises(Exception, match="dirty"):
        run_test(tc, fp)
    assert tc["calls"] == [] and tc["test_calls"] == []


def test_main_passes_the_new_flags(monkeypatch):
    seen = []
    monkeypatch.setattr(dt, "run", lambda *a, **kw: seen.append(kw))
    assert dt.main(["--split", "test", "--library-as-of", "2026-10-05T00:00:00+00:00",
                    "--fingerprint-record", "f.json"]) == 0
    assert dt.main(["--library-as-of", "2026-10-05T00:00:00+00:00", "--fingerprint"]) == 0
    assert seen[0]["split"] == "test" and seen[0]["fingerprint_record"] == dt.Path("f.json")
    assert seen[0]["library_as_of"] == datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert seen[1]["fingerprint_out"] is True and seen[1]["split"] == "dev"
