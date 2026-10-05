"""eval/dev_table.py --split test (week 7 S1b), on synthetic runs only.

load_testing is replaced by a fake that serves synthetic "testing" runs (onset after
sample 160, faults 1-20), and the dev loaders fail if touched, so nothing here reads data,
opens the sealed folder or sets EVAL_MODE. The metric functions are Raj's, unchanged; these
tests check that the driver feeds them the test split's onset, faults and twins.
"""

import json

import numpy as np
import pytest

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import dev_table as dt
from eval import metrics, run_record
from ingest import tags as tagmap
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)
from tests.test_dev_table import N_BOOT, calibrated, direct_alarm, direct_tracks, with_alarms  # noqa: F401
from tests.test_dev_table_attribution import WGRID
from tests.test_fit_pca import FAST, two_factor_runs
from tests import test_calibrate_alarms as tca

TEST_RUNS = range(1, 9)
TEST_SAMPLES = 250                    # onset 160 + the 80-sample useful window, and a little more
ONSET = metrics.TEST_ONSET
FAULTS = tuple(range(1, 21))


def faulty_test(normal, fault, first_changed=ONSET + 1):
    """Each normal testing run (its twin) with a step on every fast tag from first_changed,
    larger per fault. Faults 3, 9 and 15 get no step."""
    cols = tagmap.column_indices(VARIABLES, FAST)
    runs = {k: v.copy() for k, v in normal.runs.items()}
    if fault not in dt.EXCLUDED:
        for k in runs:
            runs[k][first_changed - 1:, cols] += np.float32(0.3 * fault)
    return Runs(name="faulty_testing", fault=fault, pool="test", columns=VARIABLES, runs=runs)


def serve_test(monkeypatch, normal, make_faulty=faulty_test):
    """Patch load_testing to serve synthetic testing runs; any dev load fails the test."""
    calls = []

    def load_testing(fault, *, purpose):
        calls.append((fault, purpose))
        return normal if fault == 0 else make_faulty(normal, fault)

    monkeypatch.setattr(loader_mod, "load_testing", load_testing)
    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail(f"loaded normal {pool}"))
    monkeypatch.setattr(loader_mod, "load_faulty", lambda f, pool: pytest.fail(f"loaded fault {f} from {pool}"))
    return calls


def write_twin(repo, verdict="shared", name="20261006T000000Z_twin_check.json", split="test"):
    path = repo / "eval" / "runs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"config": {"split": split}, "metrics": {"verdict": verdict, "faults": {}}}))
    return path


@pytest.fixture
def tested(setup, monkeypatch):
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    normal = two_factor_runs(numbers=TEST_RUNS, samples=TEST_SAMPLES, seed=11)
    calls = serve_test(monkeypatch, normal)
    tables = setup["repo"] / "data" / "tables"          # inside the repo, as data/tables is
    return {**setup, "normal": normal, "calls": calls, "tables": tables}


def build(c, verdict="shared", **kw):
    if "twin_check" not in kw:
        kw["twin_check"] = write_twin(c["repo"], verdict)
    return dt.run(c["out"], c["model_path"], repo_root=c["repo"], tables_dir=c["tables"], n_boot=N_BOOT,
                  split="test", **kw)


def the_record(c):
    (path,) = (c["repo"] / "eval" / "runs").glob("*_test_table_*.json")
    return path, json.loads(path.read_text())


# ---------- what is loaded ----------

def test_loads_only_the_testing_files_each_once_with_the_purpose(tested):
    build(tested)
    assert tested["calls"] == [(f, "test_table_pca_static") for f in (0, *FAULTS)]


def test_needs_a_twin_check_record_and_refuses_one_on_dev(tested):
    with pytest.raises(dt.DevTableError, match="needs --twin-check"):
        build(tested, twin_check=None)
    with pytest.raises(dt.DevTableError, match="only for --split test"):
        dt.run(tested["out"], tested["model_path"], repo_root=tested["repo"], tables_dir=tested["tables"],
               n_boot=N_BOOT, twin_check=write_twin(tested["repo"]))
    assert tested["calls"] == []


@pytest.mark.parametrize("kw", [{"name": "20261006T000000Z_other.json"}, {"split": "dev"},
                                {"verdict": "maybe"}])
def test_bad_twin_records_refused_before_loading(tested, kw):
    with pytest.raises(dt.DevTableError):
        build(tested, twin_check=write_twin(tested["repo"], **kw))
    assert tested["calls"] == []


def test_dirty_tree_refused_before_loading(tested):
    (tested["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        build(tested)
    assert tested["calls"] == []


# ---------- the numbers: Raj's metrics at onset 160 ----------

def test_rows_match_direct_metric_calls_at_onset_160(tested):
    results = build(tested)
    for f in (5, 9, 17):
        tracks, lim = direct_tracks(tested, faulty_test(tested["normal"], f))
        dets = [metrics.detection(tracks[k], ONSET, warmup=lim["warmup"]) for k in sorted(tracks)]
        row = results["faults"][f"fault_{f:02d}"]
        assert row["runs"] == len(TEST_RUNS) and row["detected"] == sum(d.detected for d in dets)
        assert (row["delay_median_min"], row["delay_q1_min"], row["delay_q3_min"]) == \
            metrics.delay_summary([d.delay_min for d in dets])
        # Shared twins: fault 9's runs never diverge, so every detection there is luck;
        # the stepped faults diverge at 161, so none of theirs is.
        expected = sum(d.detected for d in dets) if f == 9 else 0
        assert (row["before_divergence"], row["before_divergence_of"]) == (expected, row["detected"])
    assert any(results["faults"][f"fault_{f:02d}"]["detected"] for f in (16, 17, 18, 19, 20))
    tracks, lim = direct_tracks(tested, tested["normal"])
    runs = [metrics.ScoredRun(0, k, a) for k, a in tracks.items()]
    assert results["normal"]["chance_rate"] == metrics.chance_rate(runs, ONSET, warmup=lim["warmup"])
    assert results["normal"]["per_24h"] == pytest.approx(metrics.false_alerts_per_24h(runs, lim["warmup"])[2])
    # Whole runs after the warm-up: 241 scored samples of 3 minutes per run.
    assert results["normal"]["hours"] == pytest.approx(len(TEST_RUNS) * (TEST_SAMPLES - lim["warmup"]) * 3 / 60)


def test_operator_load_uses_the_test_notification_window(tested):
    results = build(tested)
    tracks, lim = direct_tracks(tested, faulty_test(tested["normal"], 5))
    expected = dt.operator_load({k: [metrics.notifications(t, lim["warmup"])] for k, t in tracks.items()},
                                onset=ONSET)
    assert results["faults"]["fault_05"]["load"] == pytest.approx(expected)


def test_summary_is_faults_1_to_20_except_3_9_15(tested):
    results = build(tested)
    assert results["summary"]["faults"] == [f for f in FAULTS if f not in (3, 9, 15)]
    assert results["excluded"]["faults"] == [3, 9, 15]


def test_not_shared_twins_mean_the_column_is_not_reported(tested):
    results = build(tested, verdict="not shared")
    assert all(r["before_divergence"] == dt.NOT_REPORTED and r["before_divergence_of"] == dt.NOT_REPORTED
               for r in results["faults"].values())
    table = next(tested["tables"].glob("*_test_table_*.md")).read_text()
    assert "| not reported |" in table and "(not shared)" in table


def test_shared_twins_that_differ_before_onset_are_refused(setup, monkeypatch):
    # A "shared" verdict is checked again run by run, as on dev.
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    normal = two_factor_runs(numbers=TEST_RUNS, samples=TEST_SAMPLES, seed=11)
    serve_test(monkeypatch, normal, lambda n, f: faulty_test(n, f, first_changed=100))
    with pytest.raises(dt.DevTableError, match="at or before sample 160"):
        dt.run(setup["out"], setup["model_path"], repo_root=setup["repo"], tables_dir=setup["repo"] / "t",
               n_boot=N_BOOT, split="test", twin_check=write_twin(setup["repo"]))


# ---------- the record and the table ----------

def test_record_is_a_test_table_with_the_split_in_its_config(tested):
    build(tested)
    path, rec = the_record(tested)
    cfg = rec["config"]
    assert rec["name"] == "test_table_pca_static"
    assert (cfg["pool"], cfg["split"], cfg["onset"]) == ("test", "test", 160)
    assert cfg["notification_window"] == [161, 200] and cfg["faults"] == list(FAULTS)
    assert cfg["right_place_faults"] == list(dt.SUMMARY_FAULTS)
    assert cfg["twin_check"] == {"record": "eval/runs/20261006T000000Z_twin_check.json", "verdict": "shared"}
    assert sorted(rec["metrics"]["faults"]) == [f"fault_{f:02d}" for f in FAULTS]
    assert rec["outputs"]["table"]["path"].startswith("data/tables/")


def test_record_holds_aggregates_only_and_no_absolute_paths(tested, tmp_path):
    build(tested)
    _, rec = the_record(tested)
    text = json.dumps(rec)
    assert str(tmp_path) not in text
    for row in rec["metrics"]["faults"].values():
        assert not any(isinstance(v, list) and len(v) > 2 for v in row.values())   # intervals only


def test_table_names_the_test_split_and_unlabelled_faults(tested):
    build(tested)
    path, rec = the_record(tested)
    (table,) = tested["tables"].glob("*_test_table_*.md")
    assert table.read_text() == dt.render(rec, path.relative_to(tested["repo"]).as_posix())
    text = table.read_text()
    assert text.startswith("# Test detection table: pca_static")
    assert "Test split, 8 run numbers" in text and "Mean, faults 1–20 except 3, 9, 15" in text
    row17 = next(line for line in text.splitlines() if line.startswith("| 17 |"))
    assert row17.startswith("| 17 | n/a |") and "/ n/a |" in row17


def test_masked_column_reads_not_labelled_for_16_to_20(tested):
    from tests.test_dev_table import write_masked
    results = build(tested, masked=write_masked(tested))
    assert results["faults"]["fault_05"]["masked"] == {"masked": True, "valves": "CD-FV-302"}
    assert all(results["faults"][f"fault_{f}"]["masked"] == dt.NOT_LABELLED for f in range(16, 21))
    text = next(tested["tables"].glob("*.md")).read_text()
    assert "| 18 | n/a | not labelled |" in text


def test_main_passes_the_split_and_twin_check(monkeypatch):
    seen = []
    monkeypatch.setattr(dt, "run", lambda limits, model, **kw: seen.append((kw["split"], kw["twin_check"])))
    assert dt.main([]) == 0
    assert dt.main(["--split", "test", "--twin-check", "t.json"]) == 0
    assert seen == [("dev", None), ("test", dt.Path("t.json"))]


# ---------- lead time and attribution on test ----------

def test_lead_time_uses_onset_160(with_alarms, monkeypatch):
    c = with_alarms
    normal = tca.plant_runs(TEST_RUNS, samples=TEST_SAMPLES, seed=11, pool="test")
    serve_test(monkeypatch, normal)
    results = dt.run(c["out"], c["model_path"], repo_root=c["repo"], tables_dir=c["tables"], n_boot=N_BOOT,
                     lead_vs=c["alarms"]["realistic"], split="test", twin_check=write_twin(c["repo"]))
    for f in (5, 18):
        runs = faulty_test(normal, f)
        app_tracks, lim = direct_tracks(c, runs)
        base = direct_alarm(c["alarms"]["realistic"], "grouped", runs)
        ks = sorted(app_tracks)
        lt = metrics.lead_time([metrics.detection(app_tracks[k], ONSET, warmup=lim["warmup"]) for k in ks],
                               [metrics.detection(base[k][0], ONSET, warmup=lim["warmup"]) for k in ks])
        lead = results["faults"][f"fault_{f:02d}"]["lead"]
        assert (lead["median_min"], lead["both"], lead["only_app"], lead["only_base"], lead["neither"]) == tuple(lt)


def test_attribution_on_test_summarises_the_12_family_faults(setup, monkeypatch):
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    watch = setup["repo"].parent / "models" / "watch.json"
    cw.run(setup["model_path"], setup["out"], watch, repo_root=setup["repo"], q_grid=WGRID)
    normal = two_factor_runs(numbers=TEST_RUNS, samples=TEST_SAMPLES, seed=11)
    serve_test(monkeypatch, normal)
    results = dt.run(setup["out"], setup["model_path"], watch=watch, repo_root=setup["repo"],
                     tables_dir=setup["repo"].parent / "tables", n_boot=N_BOOT, split="test",
                     twin_check=write_twin(setup["repo"]))
    assert results["right_place"]["summary"]["faults"] == list(dt.SUMMARY_FAULTS)
    for f in range(16, 21):
        a = results["faults"][f"fault_{f}"]["attribution"]
        assert "right_place" not in a and "allowed_groups" not in a
    text = next((setup["repo"].parent / "tables").glob("*.md")).read_text()
    assert "Mean, the 12 family faults, at the notification" in text
    row = next(line for line in text.splitlines() if line.startswith("| 19 | n/a | n/a | n/a |"))
    assert row
