"""eval/curves.py (week 7 S1e): the cumulative detection curve, Raj's AMOC sweep, the amoc
driver and the plots, on synthetic numbers only (never data/, never the sealed folder).

The amoc_sweep tests fail with NotImplementedError until Raj implements the sweep. The
driver and plot tests use a stand-in sweep, so they pass now.
"""

import json
import math

import numpy as np
import pytest

import dataset.loader as loader_mod
from eval import calibrate as cal
from eval import calibrate_driver as drv
from eval import curves
from eval import dev_table as dt
from eval import metrics
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)
from tests.test_dev_table import N_BOOT, SAMPLES, calibrated, faulty_dev  # noqa: F401 (fixture)
from tests.test_fit_pca import two_factor_runs

INF = math.inf


# ---------- the cumulative detection curve ----------

def test_horizons_are_every_6_minutes_to_the_4_hour_window():
    assert curves.HORIZONS_MIN[0] == 6 and curves.HORIZONS_MIN[-1] == 240 and len(curves.HORIZONS_MIN) == 40


def test_cumulative_detection_by_hand():
    # 4 runs: detected at 3, 6 and 30 minutes, one miss. Horizons 3, 6, 29, 30, 240.
    shares = curves.cumulative_detection([3.0, 6.0, 30.0, INF], (3, 6, 29, 30, 240))
    assert shares == [0.25, 0.5, 0.5, 0.75, 0.75]                   # the miss never counts


@pytest.mark.parametrize("bad", [[], [float("nan")], [-3.0]])
def test_cumulative_detection_refusals(bad):
    with pytest.raises(ValueError):
        curves.cumulative_detection(bad)


def test_cumulative_block_summary_is_the_equal_weight_mean():
    block = curves.cumulative_block({1: [6.0, INF], 2: [6.0, 6.0, 6.0, INF], 3: [INF]}, (1, 2), (6,))
    assert block["faults"] == {"fault_01": [0.5], "fault_02": [0.75], "fault_03": [0.0]}
    assert block["summary"] == [pytest.approx(0.625)] and block["summary_faults"] == [1, 2]


def test_the_detection_table_records_the_curve_from_its_own_detections(calibrated):
    results = dt.run(calibrated["out"], calibrated["model_path"], repo_root=calibrated["repo"],
                     tables_dir=calibrated["tables"], n_boot=N_BOOT)
    cum = results["cumulative"]
    tracks, lim = _direct_tracks(calibrated, faulty_dev(calibrated["normal"], 5))
    delays = [metrics.detection(tracks[k], dt.ONSET, warmup=lim["warmup"]).delay_min for k in sorted(tracks)]
    assert cum["faults"]["fault_05"] == curves.cumulative_detection(delays)
    assert cum["summary_faults"] == list(dt.SUMMARY_FAULTS) and len(cum["summary"]) == 40


def _direct_tracks(c, runs):
    lim = json.loads(c["out"].read_text())
    return drv.tracks(drv.score_runs(c["model"], runs), (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"],
                      lim["warmup"]), lim


# ---------- Raj's sweep (fails until it's implemented) ----------
# A hand-checked case: warm-up 1, n = 1, G = 0, onset 2, T² = SPE everywhere, so the ratio is
# value / limit. Calibration run [0, 1, 2, 3, 4]: scored samples 1..4, so the limit is 2.5 at
# q = 50 and 4.0 at q = 100. Every other run has 21 samples (20 scored = 1 h).

def _spike(sample, value, length=21):
    x = np.zeros(length)
    x[sample - 1] = value
    return x


def _from(sample, value, length=21, before=None):
    x = np.zeros(length)
    x[sample - 1:] = value
    if before:
        s, v = before
        x[s - 1] = v
    return x


HAND = dict(
    cal_scored={1: (np.arange(5.0), np.arange(5.0))},
    normal_scored={1: (_spike(3, 3.0), _spike(3, 3.0))},           # one excursion: 3.0 at sample 3
    fault_scored={
        4: {7: (_from(5, 5.0, before=(4, 3.0)), _from(5, 5.0, before=(4, 3.0)))},   # 3.0 at 4, then 5.0
        6: {8: (np.zeros(21), np.zeros(21)),                                          # never: a miss
            9: (_from(6, 5.0), _from(6, 5.0))}},                                      # 5.0 from 6
    n=1, gap=0, warmup=1, onset=2, q_grid=(50.0, 100.0))


def test_amoc_sweep_by_hand():
    points = curves.amoc_sweep(**HAND)
    assert [p["q"] for p in points] == [50.0, 100.0]
    low, high = points
    # q = 50, limit 2.5: the normal excursion is 1 notification in 1 h; delays 6, 12 and a miss
    assert low["per_24h"] == pytest.approx(24.0)
    assert low["delay_min"] == 12.0 and low["detection_rate"] == pytest.approx(2 / 3)
    # q = 100, limit 4: no false alert; delays 9, 12 and a miss
    assert high["per_24h"] == 0.0
    assert high["delay_min"] == 12.0 and high["detection_rate"] == pytest.approx(2 / 3)


def test_amoc_sweep_pools_runs_across_faults_and_a_majority_of_misses_is_infinite():
    hand = {**HAND, "fault_scored": {4: HAND["fault_scored"][4], 6: {8: HAND["fault_scored"][6][8]}}}
    for p in curves.amoc_sweep(**hand):                             # pooled [6 or 9, miss]: median +inf
        assert p["delay_min"] == INF and p["detection_rate"] == pytest.approx(0.5)


def test_amoc_sweep_equals_its_pieces_on_scored_runs(setup):
    # The definition, piece by piece, on calibrated synthetic runs (two_factor_runs).
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    lim = json.loads(setup["out"].read_text())
    model = setup["model"]
    cal_s = drv.score_runs(model, two_factor_runs(numbers=range(1, 9), samples=120, seed=3))
    nrm_s = drv.score_runs(model, two_factor_runs(numbers=range(101, 105), samples=120, seed=4))
    normal = two_factor_runs(numbers=range(201, 205), samples=120, seed=5)
    flt_s = {f: drv.score_runs(model, faulty_dev(normal, f)) for f in (2, 5)}
    grid = tuple(sorted({GRID[0], lim["q"], GRID[-1]}))
    points = curves.amoc_sweep(cal_s, nrm_s, flt_s, lim["n"], lim["gap"], lim["warmup"], 20, grid)
    t2, spe = [cal_s[k][0] for k in sorted(cal_s)], [cal_s[k][1] for k in sorted(cal_s)]
    for p, q in zip(points, grid):
        limits = cal.limits_at(t2, spe, q, lim["warmup"])
        nt = drv.tracks(nrm_s, limits, lim["n"], lim["gap"], lim["warmup"])
        per_24h = metrics.false_alerts_per_24h([metrics.ScoredRun(0, k, t) for k, t in nt.items()], lim["warmup"])[2]
        dets = [metrics.detection(t, 20, warmup=lim["warmup"])
                for s in flt_s.values() for t in drv.tracks(s, limits, lim["n"], lim["gap"], lim["warmup"]).values()]
        assert p["q"] == q and p["per_24h"] == pytest.approx(per_24h)
        assert p["delay_min"] == metrics.delay_summary([d.delay_min for d in dets])[0]
        assert p["detection_rate"] == pytest.approx(sum(d.detected for d in dets) / len(dets))


@pytest.mark.parametrize("change", [{"q_grid": ()}, {"q_grid": (100.0, 50.0)}, {"q_grid": (50.0, 50.0)},
                                    {"normal_scored": {}}, {"fault_scored": {}}])
def test_amoc_sweep_refusals(change):
    with pytest.raises(ValueError):
        curves.amoc_sweep(**{**HAND, **change})


# ---------- the amoc driver (a stand-in sweep) ----------

def stand_in(points_for=None):
    def sweep(cal_scored, normal_scored, fault_scored, n, gap, warmup, onset, q_grid, lags=0):
        sweep.args = dict(cal=len(cal_scored), normal=len(normal_scored), faults=sorted(fault_scored), n=n, gap=gap,
                          warmup=warmup, onset=onset)
        return points_for(q_grid) if points_for else [
            {"q": q, "per_24h": 10.0 / (i + 1), "delay_min": INF if i == 0 else 30.0 - i, "detection_rate": 0.5}
            for i, q in enumerate(q_grid)]
    return sweep


@pytest.fixture
def amoc_env(calibrated, monkeypatch):
    calib = two_factor_runs(numbers=range(1, 9), samples=SAMPLES, seed=21)

    def load_normal(pool):
        calibrated["calls"].append(("normal", pool))
        return calib if pool == "calibration" else calibrated["normal"]

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    return calibrated


def test_amoc_record_on_dev(amoc_env, monkeypatch):
    sweep = stand_in()
    monkeypatch.setattr(curves, "amoc_sweep", sweep)
    lim = json.loads(amoc_env["out"].read_text())
    grid = tuple(sorted({GRID[0], lim["q"], GRID[-1]}))
    m, record = curves.run_amoc(amoc_env["out"], amoc_env["model_path"], repo_root=amoc_env["repo"], q_grid=grid,
                                out=lambda s: None)
    rec = json.loads(record.read_text())
    assert rec["name"] == "amoc" and rec["config"]["split"] == "dev" and rec["config"]["onset"] == 20
    assert rec["config"]["summary_faults"] == list(dt.SUMMARY_FAULTS)
    assert sweep.args["faults"] == list(dt.SUMMARY_FAULTS) and sweep.args["onset"] == 20
    assert (sweep.args["n"], sweep.args["gap"]) == (lim["n"], lim["gap"])
    assert len(rec["metrics"]["points"]) == len(grid) and rec["metrics"]["operating_point"]["q"] == lim["q"]
    assert rec["metrics"]["infinite_delay_points"] == 1
    assert rec["metrics"]["points"][repr(grid[0])]["delay_min"] == "inf"
    assert ("normal", "calibration") in amoc_env["calls"] and ("normal", "dev") in amoc_env["calls"]


def test_amoc_on_test_loads_the_testing_files_through_the_split(amoc_env, monkeypatch):
    monkeypatch.setattr(curves, "amoc_sweep", stand_in())
    test_calls = []

    def load_testing(fault, *, purpose):
        test_calls.append((fault, purpose))
        return amoc_env["normal"] if fault == 0 else faulty_dev(amoc_env["normal"], min(fault, 15))

    monkeypatch.setattr(loader_mod, "load_testing", load_testing)
    lim = json.loads(amoc_env["out"].read_text())
    _, record = curves.run_amoc(amoc_env["out"], amoc_env["model_path"], split="test", repo_root=amoc_env["repo"],
                                q_grid=(lim["q"],), out=lambda s: None)
    rec = json.loads(record.read_text())
    assert rec["name"] == "test_amoc" and rec["config"]["onset"] == 160
    assert [f for f, _ in test_calls] == [0] + [f for f in range(1, 21) if f not in (3, 9, 15)]
    assert {p for _, p in test_calls} == {"test_amoc"}


def test_amoc_refusals(amoc_env, monkeypatch):
    lim = json.loads(amoc_env["out"].read_text())
    monkeypatch.setattr(curves, "amoc_sweep", stand_in())
    with pytest.raises(curves.CurvesError, match="isn't on the grid"):
        curves.run_amoc(amoc_env["out"], amoc_env["model_path"], repo_root=amoc_env["repo"],
                        q_grid=tuple(q for q in GRID if q != lim["q"]), out=lambda s: None)
    monkeypatch.setattr(curves, "amoc_sweep", stand_in(lambda grid: [{"q": q, "per_24h": 0.0, "delay_min": 3.0,
                                                                      "detection_rate": 1.0} for q in reversed(grid)]))
    with pytest.raises(curves.CurvesError, match="grid order"):
        curves.run_amoc(amoc_env["out"], amoc_env["model_path"], repo_root=amoc_env["repo"],
                        q_grid=(GRID[0], lim["q"]) if GRID[0] != lim["q"] else (lim["q"], GRID[-1]), out=lambda s: None)


def test_main_routes_and_reports_errors(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(curves, "run_amoc", lambda limits, model, **kw: seen.append(kw["split"]))
    monkeypatch.setattr(curves, "plot", lambda record, plots: seen.append(str(record)))
    assert curves.main(["amoc", "--split", "test"]) == 0 and curves.main(["plot", "r.json"]) == 0
    assert seen == ["test", "r.json"]

    def boom(*a, **kw):
        raise curves.CurvesError("boom")
    monkeypatch.setattr(curves, "run_amoc", boom)
    assert curves.main(["amoc"]) == 1 and "boom" in capsys.readouterr().err


# ---------- the plots (from records only) ----------

def test_cumulative_plot_from_a_detection_table_record(calibrated, tmp_path):
    dt.run(calibrated["out"], calibrated["model_path"], repo_root=calibrated["repo"],
           tables_dir=calibrated["tables"], n_boot=N_BOOT)
    (record,) = (calibrated["repo"] / "eval" / "runs").glob("*_dev_table_*.json")
    png = curves.plot(record, tmp_path / "plots", out=lambda s: None)
    assert png.name.endswith("_cumulative.png") and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_amoc_plot_from_an_amoc_record(tmp_path):
    rec = {"name": "amoc", "config": {"detector": "pca_static", "split": "dev"},
           "metrics": {"points": {"95.0": {"per_24h": 30.0, "delay_min": 6.0, "detection_rate": 0.9},
                                  "99.0": {"per_24h": 1.0, "delay_min": 12.0, "detection_rate": 0.8},
                                  "99.9": {"per_24h": 0.0, "delay_min": "inf", "detection_rate": 0.4}},
                       "operating_point": {"q": 99.0, "per_24h": 1.0, "delay_min": 12.0, "detection_rate": 0.8},
                       "infinite_delay_points": 1}}
    path = tmp_path / "20261006T000000Z_amoc.json"
    path.write_text(json.dumps(rec))
    png = curves.plot(path, tmp_path / "plots", out=lambda s: None)
    assert png.name == "20261006T000000Z_amoc_amoc.png" and png.stat().st_size > 0


def test_plot_refusals(tmp_path):
    old = tmp_path / "x_dev_table_pca_static.json"
    old.write_text(json.dumps({"name": "dev_table_pca_static", "config": {}, "metrics": {}}))
    with pytest.raises(curves.CurvesError, match="no cumulative"):
        curves.plot(old, tmp_path, out=lambda s: None)
    other = tmp_path / "x_fit_pca.json"
    other.write_text(json.dumps({"name": "fit_pca", "config": {}, "metrics": {}}))
    with pytest.raises(curves.CurvesError, match="neither"):
        curves.plot(other, tmp_path, out=lambda s: None)