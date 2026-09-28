"""eval/masked.py (decision 62, amended): hand-built cases for the plant-level label and
the per-loop evidence, then the driver on synthetic runs (never data/)."""

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


# ---------- plant_masked (the label) and absorbing_valves ----------

PB = {c: (-1.0, 1.0) for c in range(4)}     # columns 0, 1 held (measurement, analyzer); 2, 3 valves


def plant_run(out_cols_samples, samples=120):
    """Zeros, with column c at 5 on the given 1-based samples: {col: samples}."""
    r = np.zeros((samples, 4))
    for c, ss in out_cols_samples.items():
        for s in ss:
            r[s - 1, c] = 5.0
    return r


@pytest.mark.parametrize("outs, expected", [
    ({2: (70, 71, 72)}, (True, [2])),                        # one valve out, nothing held is out
    ({2: (70, 71, 72), 3: (90, 91, 92)}, (True, [2, 3])),    # two valves out
    ({}, (False, [])),                                       # nothing out: normal, not masked
    ({2: (70, 71, 72), 1: (80, 81, 82)}, (False, [])),       # an analyzer is out too: visible
    ({2: (70, 71, 72), 0: (80, 81)}, (True, [2])),           # a 2-sample blip doesn't count
    ({2: (70, 71, 72), 0: (21, 22, 23, 24)}, (True, [2])),   # an onset transient before 61 doesn't count
    ({2: (30, 31, 32)}, (False, [])),                        # a valve out only in the first 2 h
])
def test_plant_masked(outs, expected):
    assert mk.plant_masked(plant_run(outs), [0, 1], [2, 3], PB, onset=20, window=80, n=3) == expected


def test_plant_masked_checks_the_window():
    with pytest.raises(ValueError):
        mk.plant_masked(np.zeros((99, 4)), [0, 1], [2, 3], PB, onset=20, window=80)
    with pytest.raises(ValueError):
        mk.plant_masked(plant_run({}), [0, 1], [2, 3], PB, onset=20, window=80, settle=80)


def test_absorbing_valves():
    names = {2: "V-A", 3: "V-B", 4: "V-C"}
    # 4 masked runs: V-A out in 3 (0.75), V-B in 2 (0.5, counts), V-C in 1 (0.25).
    valves, share = mk.absorbing_valves([[2, 3], [2], [2, 3], [4]], names)
    assert valves == ["V-A", "V-B"] and share == {"V-A": 0.75, "V-B": 0.5, "V-C": 0.25}


def test_absorbing_valves_fallback_and_empty():
    names = {2: "V-A", 3: "V-B", 4: "V-C", 5: "V-D"}
    # 3 masked runs, each a different valve (1/3 each, none at 0.5): all tied, all named.
    assert mk.absorbing_valves([[2], [3], [4]], names)[0] == ["V-A", "V-B", "V-C"]
    # V-A in 2 of 5 (0.4), the others 1 of 5 (0.2): below 0.5, so the most frequent is named.
    valves, share = mk.absorbing_valves([[2], [2], [3], [4], [5]], names)
    assert valves == ["V-A"] and share["V-A"] == 0.4
    assert mk.absorbing_valves([], names) == ([], {})


def test_plant_columns_split_the_register():
    held, valves = mk.plant_columns(VARIABLES)
    assert len(held) == 41 and len(valves) == 11                 # 22 measurements + 19 analyzers
    assert set(valves.values()) == {r["tag"] for r in tagmap.register() if r["kind"] == "valve"}
    assert not set(held) & set(valves)


def test_constants():
    assert (mk.BAND, mk.PERSIST, mk.MASKED_SHARE, mk.WARMUP) == ((0.5, 99.5), 3, 0.5, 9)
    assert mk.WINDOW == 80 and mk.SETTLE == 40 and mk.ONSET == 20 and mk.FAULTS == tuple(range(1, 16))
    assert mk.RULE == "plant"


# ---------- the driver ----------

def plant_runs(numbers, seed, masked_valve=None, shift_meas=False, shift_tag=None, samples=120):
    """Independent noise on every column; optionally a fault from sample 25 that pushes
    one valve far out, every loop measurement out, or one other tag out."""
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
        if shift_tag:
            (c,) = tagmap.column_indices(VARIABLES, [shift_tag])
            x[24:, c] += 10
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
        # 5: a valve absorbs and the plant looks normal (masked).
        # 6: the same valve absorbs, but reactor pressure (in no loop) shows the fault:
        #    the production-rate loop still absorbs it, the plant-level label says visible.
        # 7: every loop measurement moves too (not masked, nothing absorbs).
        spec = {5: {"masked_valve": "CD-FV-302"},
                6: {"masked_valve": "CD-FV-302", "shift_tag": "RX-PI-202"},
                7: {"shift_meas": True}}.get(fault, {})
        return Runs("faulty_training", fault, pool, VARIABLES, plant_runs(range(1, 13), seed=100 + fault, **spec))

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    monkeypatch.setattr(selection, "load", lambda repo_root=None: {"seed": 7, "numbers": SELECTION})
    return {"calls": calls, "repo": git_repo}


def the_record(s):
    (path,) = (s["repo"] / "eval" / "runs").glob("*_masked_faults.json")
    return json.loads(path.read_text())


def test_driver_plant_label_and_loop_evidence(setup):
    per_fault = mk.run(repo_root=setup["repo"])
    f5, f6, f7 = per_fault["fault_05"], per_fault["fault_06"], per_fault["fault_07"]
    # Fault 5: only the condenser cooling water valve moves: masked, absorbed by that
    # valve, and the production-rate loop is the evidence.
    assert f5["masked"] and f5["masked_share"] == 1.0
    assert f5["absorbing_valves"] == "CD-FV-302" and f5["valve_shares"] == {"CD-FV-302": 1.0}
    assert f5["absorbing_loops"] == "ST-FIC-603" and f5["loop_shares"]["ST-FIC-603"] == 1.0
    # Fault 6: the same loop absorbs, but a measurement in no loop shows the fault, so the
    # plant-level label says visible (the superseded any-loop rule said masked).
    assert not f6["masked"] and f6["masked_share"] == 0.0 and f6["absorbing_valves"] is None
    assert f6["absorbing_loops"] == "ST-FIC-603"
    # Fault 7: every loop measurement moves: neither masked nor absorbed by any loop.
    assert not f7["masked"] and f7["absorbing_loops"] is None
    rec = the_record(setup)
    assert rec["metrics"]["masked_faults"] == [5]
    assert rec["config"]["rule"] == "plant" and rec["config"]["held_tags"] == 41 and rec["config"]["valves"] == 11
    assert rec["config"]["selection_runs"] == len(SELECTION) and rec["config"]["persist"] == 3
    assert rec["config"]["judged_samples"] == [61, 100]
    normal = rec["metrics"]["normal_calibration"]
    assert 0.0 <= normal["plant"] <= 1.0 and set(normal["loop_shares"]) == set(loop_map.load())


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