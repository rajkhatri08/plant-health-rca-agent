"""eval/calibrate_alarms.py on synthetic runs (never data/), with a small grid for speed."""

import json

import numpy as np
import pytest

import dataset.loader as loader_mod
from app.detector import alerting
from dataset import selection
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import calibrate as cal
from eval import calibrate_alarms as ca
from eval import metrics, run_record
from eval.baselines import alarms as al
from ingest import tags as tagmap
from tests.test_fit_pca import two_factor_runs

WARMUP = 3                                   # small, so n_range is 1..4
GRID = (90.0, 99.0, 99.9, 99.99)
GAPS = range(0, 3)
SELECTION = [2, 4, 6, 8, 10]
VALVES = [r["tag"] for r in tagmap.register() if r["kind"] == "valve"]
MEASUREMENTS = [r["tag"] for r in tagmap.register() if r["kind"] == "measurement"]
ANALYZERS = [r["tag"] for r in tagmap.register() if r["kind"] == "analyzer"]
HOLD = 5                                     # analyzer update, in samples (as the product analyzer)


def plant_runs(numbers, samples=120, seed=7, step=0.0, fault=0, pool="calibration"):
    """Two-factor runs with valves near 50% open (so valve-at-limit stays quiet), analyzer
    values held for HOLD samples like real analyzer updates, and an optional step on every
    measurement from sample 21."""
    runs = two_factor_runs(numbers=numbers, samples=samples, seed=seed)
    v_cols = tagmap.column_indices(VARIABLES, VALVES)
    m_cols = tagmap.column_indices(VARIABLES, MEASUREMENTS)
    a_cols = tagmap.column_indices(VARIABLES, ANALYZERS)
    rng = np.random.default_rng(seed + 1000)
    held = np.arange(samples) // HOLD * HOLD                  # index of each sample's last update
    for k in runs.runs:
        runs.runs[k][:, v_cols] = (50 + 5 * rng.normal(size=(samples, len(v_cols)))).astype(np.float32)
        runs.runs[k][:, a_cols] = runs.runs[k][held][:, a_cols]
        runs.runs[k][20:, m_cols] += np.float32(step)
    name = "fault_free_training" if fault == 0 else "faulty_training"
    return Runs(name=name, fault=fault, pool=pool, columns=VARIABLES, runs=runs.runs)


@pytest.fixture
def setup(tmp_path, monkeypatch, git_repo):
    calls = []
    calib = plant_runs(range(1, 21))

    def load_normal(pool):
        calls.append(("normal", pool))
        if pool != "calibration":
            pytest.fail(f"alarm calibration loaded normal pool {pool}")
        return calib

    def load_faulty(fault, pool):
        calls.append(("faulty", fault, pool))
        if pool != "forest_ceiling" or fault not in cal.SELECTION_FAULTS:
            pytest.fail(f"alarm calibration loaded fault {fault} from {pool}")
        return plant_runs(range(1, 13), seed=100 + fault, step=1.0 + 0.3 * fault, fault=fault,
                          pool="forest_ceiling")

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    monkeypatch.setattr(selection, "load", lambda repo_root=None: {"seed": 7, "numbers": SELECTION})
    return {"calib": calib, "calls": calls, "repo": git_repo, "models": tmp_path / "models"}


def calibrate(s, name="realistic", **kw):
    return ca.run(name, s["models"] / f"alarms_{name}_limits.json", repo_root=s["repo"],
                  warmup=WARMUP, q_grid=GRID, gap_range=GAPS, **kw)


def the_record(s, name="realistic"):
    (path,) = (s["repo"] / "eval" / "runs").glob(f"*_calibrate_alarms_{name}.json")
    return json.loads(path.read_text())


def direct_points(runs, alist, lo, hi, band):
    """Points built straight from alarms.py, without the driver's cache."""
    hl_cols = tagmap.column_indices(runs.columns, alist.hl_tags)
    v_cols = tagmap.column_indices(runs.columns, alist.valve_tags) if alist.valve_tags else []
    out = {}
    for k, x in runs.runs.items():
        high, low = al.hysteresis(x[:, hl_cols], lo, hi, band)
        parts = [high, low] + ([al.at_limit(x[:, v_cols])] if v_cols else [])
        out[k] = np.hstack(parts)
    return out


def calibration_inputs(s, alist):
    hl_cols = tagmap.column_indices(VARIABLES, alist.hl_tags)
    runs = [s["calib"].runs[k][:, hl_cols] for k in sorted(s["calib"].runs)]
    sigma = al.tag_spread(runs, WARMUP)
    band = np.array([al.DEADBAND_SIGMA[t] for t in alist.hl_types]) * sigma
    return runs, band


# ---------- alarm lists (decision 58) ----------

def test_realistic_list():
    a = ca.alarm_list("realistic")
    assert len(a.hl_tags) == 41 and sum(a.hl_analyzer) == 19          # 22 measurements + 19 analyzers
    assert a.valve_tags == tuple(VALVES) and len(VALVES) == 11
    assert not set(a.hl_tags) & set(VALVES)
    ns = a.on_delays(3)
    assert len(ns) == 2 * 41 + 11
    assert ns.count(al.ANALYZER_ON_DELAY) == 2 * 19 and ns.count(3) == 2 * 22 + 11


def test_every_tag_list():
    a = ca.alarm_list("every")
    assert len(a.hl_tags) == 52 and a.valve_tags == ()
    assert set(VALVES) <= set(a.hl_tags)
    assert {"valve", "power"} <= set(a.hl_types) <= set(al.DEADBAND_SIGMA)


def test_unknown_list_is_refused():
    with pytest.raises(ca.AlarmCalibrationError):
        ca.alarm_list("some")


# ---------- the cache is exact ----------

@pytest.mark.parametrize("name", ["realistic", "every"])
def test_cached_tracks_equal_plant_track(setup, name):
    alist = ca.alarm_list(name)
    runs, band = calibration_inputs(setup, alist)
    limits = lambda q: al.tag_limits(runs, q, WARMUP)                  # noqa: E731
    pool = ca.Pool(setup["calib"], alist, limits, band, WARMUP, all_n=(1, 2, 3, 4))
    for q in (90.0, 99.0):
        pts = direct_points(setup["calib"], alist, *limits(q), band)
        for n in (1, 3, 4):
            for gap in (0, 2):
                for k in (1, 7, 20):
                    expected = al.plant_track(pts[k], alist.on_delays(n), gap, WARMUP)
                    assert pool.track(q, k, n, gap).tolist() == expected.tolist()


def test_pool_refuses_missing_run_numbers(setup):
    alist = ca.alarm_list("realistic")
    runs, band = calibration_inputs(setup, alist)
    with pytest.raises(ca.AlarmCalibrationError):
        ca.Pool(setup["calib"], alist, lambda q: al.tag_limits(runs, q, WARMUP), band, WARMUP,
                numbers=[1, 99])


# ---------- the whole run ----------

def test_limits_file_and_record(setup):
    doc = calibrate(setup)
    rec = the_record(setup)
    alist = ca.alarm_list("realistic")
    runs, band = calibration_inputs(setup, alist)
    assert doc["hl_tags"] == list(alist.hl_tags) and doc["valve_tags"] == VALVES
    assert doc["band"] == pytest.approx(band.tolist())
    for label in ("grouped", "ungrouped"):
        lo, hi = al.tag_limits(runs, doc[label]["q"], WARMUP)
        assert doc[label]["lo"] == pytest.approx(lo.tolist()) and doc[label]["hi"] == pytest.approx(hi.tolist())
        assert rec["metrics"][label]["q"] == doc[label]["q"]
    assert doc["ungrouped"]["gap"] == 0
    assert len(rec["metrics"]["settings"]) == 4 * 3        # n 1..4 x G 0..2
    assert rec["config"]["list"] == "realistic" and rec["config"]["valve_at_limit"] == 11
    assert rec["outputs"]["limits"]["sha256"] == run_record.sha256(setup["models"] / "alarms_realistic_limits.json")


def test_chosen_settings_follow_choose_on_the_recorded_table(setup):
    calibrate(setup)
    rec = the_record(setup)
    cands = {}
    for key, row in rec["metrics"]["settings"].items():
        n, g = (int(x) for x in key[1:].split("_g"))
        cands[(n, g)] = (row["q"], row["score"] if row["score"] is not None else 0.0)
    n, g, q = cal.choose(cands)
    assert (rec["metrics"]["grouped"]["n"], rec["metrics"]["grouped"]["gap"], rec["metrics"]["grouped"]["q"]) == (n, g, q)
    n, g, q = cal.choose({s: v for s, v in cands.items() if s[1] == 0})
    assert (rec["metrics"]["ungrouped"]["n"], rec["metrics"]["ungrouped"]["gap"], rec["metrics"]["ungrouped"]["q"]) == (n, 0, q)


def test_every_eligible_setting_meets_the_budget_by_direct_count(setup):
    calibrate(setup)
    rec = the_record(setup)
    alist = ca.alarm_list("realistic")
    runs, band = calibration_inputs(setup, alist)
    eligible = [(k, r) for k, r in rec["metrics"]["settings"].items() if r["q"] is not None]
    assert eligible
    for key, row in eligible:
        n, g = (int(x) for x in key[1:].split("_g"))
        pts = direct_points(setup["calib"], alist, *al.tag_limits(runs, row["q"], WARMUP), band)
        tracks = [metrics.ScoredRun(0, k, al.plant_track(p, alist.on_delays(n), g, WARMUP))
                  for k, p in pts.items()]
        per_24h = metrics.false_alerts_per_24h(tracks, WARMUP)[2]
        assert per_24h <= cal.BUDGET_PER_24H
        assert row["budget_share"] == pytest.approx(per_24h / cal.BUDGET_PER_24H)


def test_loads_only_calibration_and_selection(setup):
    calibrate(setup)
    assert setup["calls"] == [("normal", "calibration")] + [
        ("faulty", f, "forest_ceiling") for f in cal.SELECTION_FAULTS]


def test_every_tag_list_runs(setup):
    doc = calibrate(setup, "every")
    assert doc["valve_tags"] == [] and len(doc["hl_tags"]) == 52
    assert the_record(setup, "every")["config"]["valve_at_limit"] == 0


def test_refuses_existing_output_before_loading(setup):
    out = setup["models"] / "alarms_realistic_limits.json"
    out.parent.mkdir(parents=True)
    out.write_text("{}")
    with pytest.raises(FileExistsError):
        calibrate(setup)
    assert setup["calls"] == []


def test_refuses_dirty_tree_before_loading(setup):
    (setup["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        calibrate(setup)
    assert setup["calls"] == []


def test_group_after_the_cache_is_the_same_as_group_on_the_raw_or():
    # The driver groups a base track whose warm-up is already off; alerting.group turns
    # the warm-up off itself, so grouping before or after that gives the same track.
    rng = np.random.default_rng(1)
    held = rng.random(80) < 0.3
    base = alerting.group(held, 0, 5)
    for gap in range(0, 6):
        assert alerting.group(base, gap, 5).tolist() == alerting.group(held, gap, 5).tolist()
