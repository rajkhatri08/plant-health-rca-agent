"""eval/dev_table.py on synthetic runs (never data/): calibrate with the driver first, then
build the dev table. The run-level tests need Raj's first_divergence and
before_divergence_share; until then they fail with NotImplementedError."""

import json

import numpy as np
import pytest

import dataset.loader as loader_mod
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import calibrate_driver as drv
from eval import dev_table as dt
from eval import metrics, run_record
from ingest import tags as tagmap
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)
from tests.test_fit_pca import FAST, two_factor_runs

DEV = range(101, 111)
SAMPLES = 120
N_BOOT = 50


def faulty_dev(normal, fault, first_changed=21):
    """A copy of each normal dev run (its twin) with a step on every fast tag from
    sample first_changed on, larger per fault. Faults 3, 9 and 15 get no step, so those
    runs stay identical to their twins and any detection there is luck."""
    cols = tagmap.column_indices(VARIABLES, FAST)
    runs = {k: v.copy() for k, v in normal.runs.items()}
    if fault not in dt.EXCLUDED:
        for k in runs:
            runs[k][first_changed - 1:, cols] += np.float32(0.4 * fault)
    return Runs(name="faulty_training", fault=fault, pool="dev", columns=VARIABLES, runs=runs)


@pytest.fixture
def calibrated(setup, monkeypatch, tmp_path):
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    normal = two_factor_runs(numbers=DEV, samples=SAMPLES, seed=11)
    calls = []

    def load_normal(pool):
        calls.append(("normal", pool))
        if pool != "dev":
            pytest.fail(f"dev table loaded normal pool {pool}")
        return normal

    def load_faulty(fault, pool):
        calls.append(("faulty", fault, pool))
        if pool != "dev" or fault not in range(1, 16):
            pytest.fail(f"dev table loaded fault {fault} from {pool}")
        return faulty_dev(normal, fault)

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    return {**setup, "normal": normal, "calls": calls, "tables": tmp_path / "tables"}


def build(c, **kw):
    return dt.run(c["out"], c["model_path"], repo_root=c["repo"], tables_dir=c["tables"],
                  n_boot=N_BOOT, **kw)


def direct_tracks(c, runs):
    lim = json.loads(c["out"].read_text())
    scored = drv.score_runs(c["model"], runs)
    return drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], lim["warmup"]), lim


def the_record(c):
    (path,) = (c["repo"] / "eval" / "runs").glob("*_dev_table_*.json")
    return path, json.loads(path.read_text())


# --- Pure pieces: these don't need Raj's stubs. ---

def test_faults_are_the_open_ones_and_the_summary_excludes_3_9_15():
    assert dt.FAULTS == tuple(range(1, 16))
    assert dt.SUMMARY_FAULTS == (1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14)
    assert set(dt.FAMILIES) == set(dt.SUMMARY_FAULTS)


def test_mean_rate_weights_faults_equally():
    # Fault 1: 3 of 4 runs detected (0.75); fault 2: 1 of 4 (0.25). Mean 0.5.
    hit = {(1, 1): True, (1, 2): True, (1, 3): True, (1, 4): False,
           (2, 1): True, (2, 2): False, (2, 3): False, (2, 4): False}
    out = dt.mean_rate(hit, (1, 2), n_boot=N_BOOT)
    assert out["rate"] == pytest.approx(0.5)
    assert out["faults"] == [1, 2]
    low, high = out["rate_ci95"]
    assert 0 <= low <= high <= 1


def test_mean_rate_refuses_different_run_numbers_per_fault():
    # The joint bootstrap draws one set of numbers for every fault (rule 3).
    hit = {(1, 1): True, (1, 2): True, (2, 1): True, (2, 3): False}
    with pytest.raises(ValueError):
        dt.mean_rate(hit, (1, 2), n_boot=N_BOOT)


def test_mean_rate_refuses_a_missing_fault():
    with pytest.raises(ValueError):
        dt.mean_rate({(1, 1): True}, (1, 2), n_boot=N_BOOT)


def test_mean_rate_every_fault_detected_gives_a_point_interval():
    hit = {(f, k): True for f in (1, 2) for k in range(1, 6)}
    assert dt.mean_rate(hit, (1, 2), n_boot=N_BOOT)["rate_ci95"] == [1.0, 1.0]


def test_normal_row_matches_direct_metric_calls():
    # 120 samples, warm-up 9: 111 scored samples (5.55 h) per run.
    # Run 1: switches on at 12 (before the fake-onset window 21..100) and at 105 (after
    # it): 2 notifications, no chance "detection".
    # Run 2: on at 21..22, inside the window: 1 notification, a chance "detection".
    # So 3 notifications in 11.1 h, and a chance rate of 1 of 2.
    t1 = np.zeros(120, dtype=int); t1[11:13] = 1; t1[104] = 1
    t2 = np.zeros(120, dtype=int); t2[20:22] = 1
    row = dt.normal_row({1: t1, 2: t2}, warmup=9, n_boot=N_BOOT)
    runs = [metrics.ScoredRun(0, 1, t1), metrics.ScoredRun(0, 2, t2)]
    assert (row["notifications"], row["hours"], row["per_24h"]) == pytest.approx(
        metrics.false_alerts_per_24h(runs, 9))
    assert row["notifications"] == 3 and row["hours"] == pytest.approx(11.1)
    assert row["chance_rate"] == 0.5
    assert row["runs"] == 2


def test_render_marks_unbuilt_columns_and_infinite_delays():
    r = {"family": dt.PENDING, "runs": 2, "detected": 0, "rate": 0.0, "rate_ci95": [0.0, 0.0],
         "before_divergence": 0, "before_divergence_of": 0, "delay_median_min": "inf",
         "delay_q1_min": "inf", "delay_q3_min": "inf", "delay_median_ci95": ["inf", "inf"],
         "share_still_flagged": None, "share_still_flagged_runs": 0}
    stored = {"commit": "a" * 40, "dirty": False,
              "config": {"detector": "pca_static", "n": 3, "gap": 15, "q": 95.57, "warmup": 9,
                         "bootstrap": {"resamples": 2000}},
              "seeds": {"bootstrap": dt.BOOTSTRAP_SEED},
              "metrics": {"faults": {f"fault_{f:02d}": r for f in dt.FAULTS},
                          "summary": {"rate": 0.0, "rate_ci95": [0.0, 0.0]},
                          "excluded": {"rate": 0.0, "rate_ci95": [0.0, 0.0]},
                          "normal": {"runs": 2, "notifications": 1, "hours": 9.1, "per_24h": 2.637,
                                     "per_24h_ci95": [0.0, 5.0], "chance_rate": 0.5,
                                     "chance_rate_ci95": [0.0, 1.0]}}}
    text = dt.render(stored, "eval/runs/x_dev_table_pca_static.json")
    rows = [line for line in text.splitlines() if line.startswith("| 1 |")]
    assert len(rows) == 1
    assert "∞ (∞–∞)" in rows[0] and rows[0].count(dt.PENDING) >= 4
    assert "eval/runs/x_dev_table_pca_static.json" in text


# --- The whole run: needs Raj's first_divergence and before_divergence_share. ---

def test_loads_only_dev_each_fault_once(calibrated):
    build(calibrated)
    assert calibrated["calls"] == [("normal", "dev")] + [("faulty", f, "dev") for f in range(1, 16)]


def test_rows_match_direct_metric_calls(calibrated):
    results = build(calibrated)
    for f in (5, 9):
        tracks, lim = direct_tracks(calibrated, faulty_dev(calibrated["normal"], f))
        dets = [metrics.detection(tracks[k], dt.ONSET, warmup=lim["warmup"]) for k in sorted(tracks)]
        row = results["faults"][f"fault_{f:02d}"]
        assert row["runs"] == len(DEV)
        assert row["detected"] == sum(d.detected for d in dets)
        assert row["rate"] == pytest.approx(row["detected"] / len(DEV))
        median, q1, q3 = metrics.delay_summary([d.delay_min for d in dets])
        assert (row["delay_median_min"], row["delay_q1_min"], row["delay_q3_min"]) == (median, q1, q3)
        # Fault 5's runs diverge at sample 21; fault 9's never do.
        before_expected = sum(d.detected and (f == 9 or d.sample < 21) for d in dets)
        assert (row["before_divergence"], row["before_divergence_of"]) == (before_expected, row["detected"])
    tracks, lim = direct_tracks(calibrated, calibrated["normal"])
    runs = [metrics.ScoredRun(0, k, a) for k, a in tracks.items()]
    assert results["normal"]["per_24h"] == pytest.approx(metrics.false_alerts_per_24h(runs, lim["warmup"])[2])
    assert results["normal"]["chance_rate"] == metrics.chance_rate(runs, dt.ONSET, warmup=lim["warmup"])


def test_a_detection_before_divergence_is_counted(calibrated, monkeypatch):
    # Fault 5's runs diverge only from sample 60, so any detection in 21..59 is luck.
    normal = calibrated["normal"]
    monkeypatch.setattr(loader_mod, "load_faulty",
                        lambda fault, pool: faulty_dev(normal, fault, first_changed=60))
    results = build(calibrated)
    tracks, lim = direct_tracks(calibrated, faulty_dev(normal, 5, first_changed=60))
    dets = [metrics.detection(tracks[k], dt.ONSET, warmup=lim["warmup"]) for k in sorted(tracks)]
    row = results["faults"]["fault_05"]
    assert row["before_divergence"] == sum(d.detected and d.sample < 60 for d in dets)


def test_refuses_runs_that_differ_from_their_twins_before_onset(calibrated, monkeypatch):
    normal = calibrated["normal"]
    monkeypatch.setattr(loader_mod, "load_faulty",
                        lambda fault, pool: faulty_dev(normal, fault, first_changed=15))
    with pytest.raises(dt.DevTableError):
        build(calibrated)


def test_record_holds_every_fault_and_no_sealed_ones(calibrated):
    build(calibrated)
    _, rec = the_record(calibrated)
    assert sorted(rec["metrics"]["faults"]) == [f"fault_{f:02d}" for f in range(1, 16)]
    assert rec["config"]["pool"] == "dev" and rec["seeds"] == {"bootstrap": dt.BOOTSTRAP_SEED}
    assert rec["config"]["calibration_record"].endswith("_calibrate_pca.json")
    assert rec["metrics"]["summary"]["faults"] == list(dt.SUMMARY_FAULTS)
    text = json.dumps(rec)
    assert not any(f"fault_{f}" in text for f in range(16, 21))


def test_table_is_rendered_from_the_saved_record(calibrated):
    build(calibrated)
    path, rec = the_record(calibrated)
    (table,) = calibrated["tables"].glob("*_dev_table_*.md")
    assert rec["outputs"]["table"]["sha256"] == run_record.sha256(table)
    rel = path.relative_to(calibrated["repo"]).as_posix()
    assert table.read_text() == dt.render(rec, rel)


def test_same_seed_same_numbers(calibrated):
    first = build(calibrated)
    # Records and tables are never overwritten, and two runs in one second share a name.
    for p in [*(calibrated["repo"] / "eval" / "runs").glob("*_dev_table_*.json"),
              *calibrated["tables"].glob("*.md")]:
        p.unlink()
    assert build(calibrated) == first


def test_refuses_dirty_tree_before_loading(calibrated):
    (calibrated["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        build(calibrated)
    assert calibrated["calls"] == []


def test_refuses_limits_without_a_calibration_record(calibrated):
    lim = json.loads(calibrated["out"].read_text())
    lim["q"] = 50.0
    calibrated["out"].write_text(json.dumps(lim))
    with pytest.raises(drv.CalibrationError):
        build(calibrated)
    assert calibrated["calls"] == []
