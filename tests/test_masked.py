"""eval/masked.py (decision 62): hand-built cases for the rule, then the driver on
synthetic runs (never data/)."""

import json

import numpy as np
import pytest

import dataset.loader as loader_mod
from app.detector import loops as loop_map
from dataset import selection
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import masked as mk
from eval import run_record
from ingest import tags as tagmap

SELECTION = [2, 4, 6, 8, 10]


# ---------- bands ----------

def test_bands_are_pooled_scored_percentiles():
    # Warm-up 1 drops 100 and -100; pooled values 1..10 (and 10..100 in column 1).
    # 0.5th percentile: position 0.005 * 9 = 0.045 -> 1.045; 99.5th: 8.955 -> 9.955.
    a = np.column_stack([[100.0, 1, 2, 3, 4, 5], [1000.0, 10, 20, 30, 40, 50]])
    b = np.column_stack([[-100.0, 6, 7, 8, 9, 10], [-1000.0, 60, 70, 80, 90, 100]])
    bands = mk.normal_bands([a, b], [0, 1], warmup=1)
    assert bands[0] == pytest.approx((1.045, 9.955))
    assert bands[1] == pytest.approx((10.45, 99.55))


@pytest.mark.parametrize("runs, warmup", [([], 1), ([np.zeros((3, 1))], 3), ([np.full((5, 1), np.nan)], 1)])
def test_bands_refusals(runs, warmup):
    with pytest.raises(ValueError):
        mk.normal_bands(runs, [0], warmup=warmup)


# ---------- outside_for ----------

@pytest.mark.parametrize("x, expected", [
    ([0, 5, 5, 5, 0], True),          # 3 in a row above hi = 1
    ([0, 5, 5, 0, 5, 5], False),      # never 3 in a row
    ([0, -5, 5, -5, 0], True),        # below, above, below: all outside, 3 in a row
    ([1, 1, 1, 1], False),            # exactly at hi: the edge is inside
    ([-1, -1, -1], False),            # exactly at lo
    ([], False),
])
def test_outside_for_three_consecutive(x, expected):
    assert mk.outside_for(np.array(x, dtype=float), -1.0, 1.0, 3) is expected


def test_outside_for_n():
    assert mk.outside_for(np.array([5.0]), -1.0, 1.0, 1) is True
    with pytest.raises(ValueError):
        mk.outside_for(np.array([5.0]), -1.0, 1.0, 0)


# ---------- run_masked ----------

BANDS = {0: (-1.0, 1.0), 1: (-1.0, 1.0)}      # column 0 measurement, column 1 valve


def run_with(meas_out=(), valve_out=(), samples=120):
    """Zeros, with the measurement (col 0) or the valve (col 1) at 5 on the given
    1-based samples."""
    r = np.zeros((samples, 2))
    for s in meas_out:
        r[s - 1, 0] = 5.0
    for s in valve_out:
        r[s - 1, 1] = 5.0
    return r


# Onset 20, window 80: the rule judges the settled half, samples 61..100 (decision 62).
@pytest.mark.parametrize("meas_out, valve_out, expected", [
    ((), (70, 71, 72), True),                  # valve out 3 in a row, measurement held
    ((), (70, 71), False),                     # valve out only 2 in a row
    ((80, 81, 82), (70, 71, 72), False),       # the measurement left too: not held
    ((80, 81), (70, 71, 72), True),            # a 2-sample blip still counts as held
    ((21, 22, 23, 24, 25), (70, 71, 72), True),  # an onset transient before 61 doesn't disqualify
    ((), (30, 31, 32), False),                 # a valve excursion only in the first 2 h isn't absorption
    ((), (58, 59, 60), False),                 # ends just before the judged half
    ((), (59, 60, 61), False),                 # only 61 is inside: 1 sample
    ((), (61, 62, 63), True),                  # the first 3 judged samples
    ((), (99, 100, 101), False),               # only 2 of them inside the window
    ((), (98, 99, 100), True),                 # the last 3 samples of the window
    ((59, 60, 61), (70, 71, 72), True),        # the measurement's excursion starts before 61
])
def test_run_masked_on_the_settled_half(meas_out, valve_out, expected):
    assert mk.run_masked(run_with(meas_out, valve_out), 0, 1, BANDS, onset=20, window=80, n=3) is expected


def test_run_masked_whole_window_when_settle_is_0():
    # settle = 0 judges samples 21..100: an onset transient in the measurement disqualifies.
    r = run_with((21, 22, 23), (70, 71, 72))
    assert mk.run_masked(r, 0, 1, BANDS, onset=20, window=80, n=3, settle=0) is False
    assert mk.run_masked(r, 0, 1, BANDS, onset=20, window=80, n=3) is True


@pytest.mark.parametrize("settle", [-1, 80, 81])
def test_run_masked_refuses_a_settle_outside_the_window(settle):
    with pytest.raises(ValueError):
        mk.run_masked(run_with(), 0, 1, BANDS, onset=20, window=80, settle=settle)


def test_run_masked_needs_the_whole_window():
    with pytest.raises(ValueError):
        mk.run_masked(np.zeros((99, 2)), 0, 1, BANDS, onset=20, window=80)


def test_shares_and_verdict():
    # Loop A masked on 2 of 4 runs (0.5, which counts), loop B on 1 of 4.
    runs = [run_with((), (70, 71, 72)), run_with((), (70, 71, 72)), run_with(), run_with()]
    runs = [np.column_stack([r, r[:, 1] if i == 0 else np.zeros(len(r))]) for i, r in enumerate(runs)]
    bands = {0: (-1.0, 1.0), 1: (-1.0, 1.0), 2: (-1.0, 1.0)}
    s = mk.shares(runs, {"A": (0, 1), "B": (0, 2)}, bands, onset=20)
    assert s == {"A": 0.5, "B": 0.25}
    assert mk.verdict(s) == ["A"] and mk.verdict({"A": 0.49}) == []


def test_constants():
    assert (mk.BAND, mk.PERSIST, mk.MASKED_SHARE, mk.WARMUP) == ((0.5, 99.5), 3, 0.5, 9)
    assert mk.WINDOW == 80 and mk.SETTLE == 40 and mk.ONSET == 20 and mk.FAULTS == tuple(range(1, 16))


# ---------- the driver ----------

def plant_runs(numbers, seed, masked_valve=None, shift_meas=False, samples=120):
    """Independent noise on every column; optionally a fault from sample 25 that pushes
    one valve far out (masked) or pushes every loop measurement out too (not masked)."""
    rng = np.random.default_rng(seed)
    loops = loop_map.load()
    meas_cols = tagmap.column_indices(VARIABLES, [lp.controlled for lp in loops.values()])
    runs = {}
    for k in numbers:
        x = rng.normal(size=(samples, len(VARIABLES))).astype(np.float32)
        if masked_valve:
            (c,) = tagmap.column_indices(VARIABLES, [masked_valve])
            x[24:, c] += 10
        if shift_meas:
            x[24:, meas_cols] += 10
        runs[k] = x
    return runs


@pytest.fixture
def setup(monkeypatch, git_repo):
    calls = []
    calib = Runs("fault_free_training", 0, "calibration", VARIABLES, plant_runs(range(1, 31), seed=1))

    def load_normal(pool):
        calls.append(("normal", pool))
        if pool != "calibration":
            pytest.fail(f"masked rule loaded normal pool {pool}")
        return calib

    def load_faulty(fault, pool):
        calls.append(("faulty", fault, pool))
        if pool != "forest_ceiling":
            pytest.fail(f"masked rule loaded fault {fault} from {pool}")
        spec = {5: {"masked_valve": "CD-FV-302"}, 7: {"shift_meas": True}}.get(fault, {})
        return Runs("faulty_training", fault, pool, VARIABLES, plant_runs(range(1, 13), seed=100 + fault, **spec))

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    monkeypatch.setattr(selection, "load", lambda repo_root=None: {"seed": 7, "numbers": SELECTION})
    return {"calls": calls, "repo": git_repo}


def the_record(s):
    (path,) = (s["repo"] / "eval" / "runs").glob("*_masked_faults.json")
    return json.loads(path.read_text())


def test_driver_finds_the_masked_fault_and_its_loop(setup):
    per_fault = mk.run(repo_root=setup["repo"])
    # Fault 5: the condenser cooling water valve (production-rate loop ST-FIC-603) is
    # pushed out while its measurement is untouched: masked by that loop in every run.
    assert per_fault["fault_05"]["masked"] and per_fault["fault_05"]["by"] == "ST-FIC-603"
    assert per_fault["fault_05"]["shares"]["ST-FIC-603"] == 1.0
    # Fault 7: every loop measurement is pushed out too, so nothing is held.
    assert not per_fault["fault_07"]["masked"] and per_fault["fault_07"]["max_share"] == 0.0
    rec = the_record(setup)
    assert rec["metrics"]["masked_faults"] == [5]
    assert rec["config"]["selection_runs"] == len(SELECTION) and rec["config"]["persist"] == 3
    assert rec["config"]["judged_samples"] == [61, 100]
    assert 0.0 <= rec["metrics"]["normal_calibration"]["any_loop"] <= 1.0


def test_driver_loads_only_calibration_and_selection_pools(setup):
    mk.run(repo_root=setup["repo"])
    assert setup["calls"] == [("normal", "calibration")] + [("faulty", f, "forest_ceiling") for f in range(1, 16)]


def test_driver_refuses_dirty_tree_before_loading(setup):
    (setup["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        mk.run(repo_root=setup["repo"])
    assert setup["calls"] == []


def test_driver_refuses_missing_selection_runs(setup, monkeypatch):
    monkeypatch.setattr(selection, "load", lambda repo_root=None: {"seed": 7, "numbers": [2, 99]})
    with pytest.raises(mk.MaskedError):
        mk.run(repo_root=setup["repo"])