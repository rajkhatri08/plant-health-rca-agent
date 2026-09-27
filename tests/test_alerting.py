"""app/detector/alerting.py on hand-built tracks (decisions 52, 53, 54).

Index 0 is sample 1. Expected values are worked out in the comments. These fail with
NotImplementedError until Raj implements alerting.py.
"""

import numpy as np
import pytest

from app.detector import alerting as al
from eval.metrics import notifications

W = 9                                     # the protocol's warm-up (decision 52)


def track(on_samples, length):
    """0/1 array with 1 at the given 1-based samples."""
    a = np.zeros(length, dtype=int)
    for s in on_samples:
        a[s - 1] = 1
    return a


def ratio_with(above_samples, length):
    """Ratio 2.0 at the given 1-based samples, 0.5 elsewhere."""
    return np.where(track(above_samples, length) == 1, 2.0, 0.5)


# ---------- plant_ratio (decision 53) ----------

def test_plant_ratio_is_the_larger_ratio():
    # Sample 1: 1/2 = 0.5 vs 3/2 = 1.5 -> 1.5.  Sample 2: 4/2 = 2.0 vs 1/2 = 0.5 -> 2.0.
    r = al.plant_ratio(np.array([1.0, 4.0]), np.array([3.0, 1.0]), 2.0, 2.0)
    assert r.dtype == np.float64
    assert r.tolist() == [1.5, 2.0]


def test_plant_ratio_uses_each_limit_for_its_own_statistic():
    # T²/10 = 0.5, SPE/1 = 0.5 -> 0.5; swapping the limits would give 5.0.
    assert al.plant_ratio(np.array([5.0]), np.array([0.5]), 10.0, 1.0).tolist() == [0.5]


@pytest.mark.parametrize("t2, spe, t2_lim, spe_lim", [
    ([1.0], [1.0], 0.0, 1.0),               # limit must be > 0
    ([1.0], [1.0], 1.0, -1.0),
    ([1.0], [1.0], np.nan, 1.0),
    ([1.0], [1.0], 1.0, np.inf),
    ([np.nan], [1.0], 1.0, 1.0),            # a gap must never read as normal (decision 51)
    ([1.0], [np.inf], 1.0, 1.0),
    ([1.0, 2.0], [1.0], 1.0, 1.0),          # lengths differ
    ([[1.0]], [[1.0]], 1.0, 1.0),           # not 1-D
])
def test_plant_ratio_refusals(t2, spe, t2_lim, spe_lim):
    with pytest.raises(ValueError):
        al.plant_ratio(np.array(t2), np.array(spe), t2_lim, spe_lim)


# ---------- persist (on-delay) ----------

def test_persist_n1_is_identity():
    e = np.array([0, 1, 1, 0, 1])
    assert al.persist(e, 1).tolist() == [False, True, True, False, True]


def test_persist_needs_n_consecutive():
    # n = 3. Runs of exceedance: samples 2-3 (too short), samples 5-8 (on from 7).
    e = track([2, 3, 5, 6, 7, 8], 9)
    assert al.persist(e, 3).astype(int).tolist() == [0, 0, 0, 0, 0, 0, 1, 1, 0]


def test_persist_window_never_reaches_before_sample_1():
    # Samples 1-2 can't have 3 samples behind them, so they're off even when exceeding.
    assert al.persist(np.array([1, 1, 1]), 3).astype(int).tolist() == [0, 0, 1]
    assert al.persist(np.array([1, 1]), 3).astype(int).tolist() == [0, 0]


@pytest.mark.parametrize("bad", [np.array([0, 2]), np.array([0.5, 1]), np.array([np.nan, 1])])
def test_persist_refuses_non_binary(bad):
    with pytest.raises(ValueError):
        al.persist(bad, 1)


def test_persist_refuses_n_below_1():
    with pytest.raises(ValueError):
        al.persist(np.array([1, 1]), 0)


# ---------- group (off-delay) ----------

def test_group_gap0_only_masks_warmup():
    held = np.array([1, 1, 0, 1, 0])
    assert al.group(held, 0, 2).astype(int).tolist() == [0, 0, 0, 1, 0]


def test_group_holds_gap_samples_after_clearing():
    # warm-up 0, gap 2. Held at 4 -> on 4, 5, 6. Held at 8 -> on 8, 9, 10.
    held = track([4, 8], 12)
    assert al.group(held, 2, 0).astype(int).tolist() == [0, 0, 0, 1, 1, 1, 0, 1, 1, 1, 0, 0]


def test_group_ignores_held_samples_in_the_warmup():
    # Held only at sample 2, inside a warm-up of 3; gap 5 would reach samples 4-7, but
    # the grouping state starts at the first scored sample (4).
    held = track([2], 8)
    assert al.group(held, 5, 3).astype(int).tolist() == [0] * 8


def test_group_continues_an_alert_already_on_at_the_first_scored_sample():
    # warm-up 2: held at samples 1-4 -> off in the warm-up, on at 3 and 4, hold 1 -> 5.
    held = track([1, 2, 3, 4], 6)
    assert al.group(held, 1, 2).astype(int).tolist() == [0, 0, 1, 1, 1, 0]


@pytest.mark.parametrize("gap, warmup", [(-1, 0), (0, -1)])
def test_group_refusals(gap, warmup):
    with pytest.raises(ValueError):
        al.group(np.array([0, 1]), gap, warmup)


def test_group_refuses_non_binary():
    with pytest.raises(ValueError):
        al.group(np.array([0, 3]), 0, 0)


# ---------- alert_track: the whole pipeline ----------

def test_ratio_exactly_1_is_not_an_exceedance():
    r = np.array([1.0] * 12)
    assert al.alert_track(r, 1, 0, W).tolist() == [0] * 12


def test_track_is_integer_0_1():
    t = al.alert_track(ratio_with([10, 11], 12), 1, 0, W)
    assert t.dtype.kind in "iu" and t.tolist() == [0] * 9 + [1, 1, 0]


def test_window_may_use_warmup_samples():
    # n = 3, gap 2. Ratio > 1 at samples 8, 9, 10: the window at sample 10 is 8-10, two of
    # them in the warm-up. That's what the warm-up is for, so the alert is on at 10
    # (a notification, per PROTOCOL), then holds 2 more samples: on at 10, 11, 12.
    t = al.alert_track(ratio_with([8, 9, 10], 15), 3, 2, W)
    assert t.tolist() == [0] * 9 + [1, 1, 1, 0, 0, 0]
    assert notifications(t, W) == [10]


def test_n10_window_reaches_exactly_sample_1():
    # n = 10, warm-up 9: at sample 10 the window is samples 1-10, the whole run so far.
    full = al.alert_track(ratio_with(range(1, 11), 12), 10, 0, W)
    assert full.tolist() == [0] * 9 + [1, 0, 0]
    # Missing sample 1: only 9 exceedances by sample 10, so off.
    short = al.alert_track(ratio_with(range(2, 11), 12), 10, 0, W)
    assert short.tolist() == [0] * 12


def test_nothing_is_on_in_the_warmup():
    t = al.alert_track(ratio_with(range(1, 13), 12), 1, 5, W)
    assert t[:W].tolist() == [0] * W and t[W:].tolist() == [1, 1, 1]


@pytest.mark.parametrize("gap, expected", [(0, [12, 17]), (1, [12, 17]), (2, [12])])
def test_grouping_merges_notifications_across_a_short_dip(gap, expected):
    # n = 1. Above at 12-14 and 17-18; the dip is samples 15-16 (2 samples).
    # gap 2 holds through 15 and 16, so the second burst is the same episode.
    t = al.alert_track(ratio_with([12, 13, 14, 17, 18], 25), 1, gap, W)
    assert notifications(t, W) == expected


def test_persistence_suppresses_a_short_blip():
    # One sample above at 15; n = 2 needs two in a row.
    t = al.alert_track(ratio_with([15], 20), 2, 0, W)
    assert notifications(t, W) == []


@pytest.mark.parametrize("n, lags, ok", [(10, 0, True), (11, 0, False), (8, 2, True),
                                         (9, 2, False), (1, 9, True), (1, 10, False)])
def test_memory_bound_lags_plus_n_minus_1_le_warmup(n, lags, ok):
    r = ratio_with([], 20)
    if ok:
        al.alert_track(r, n, 0, W, lags=lags)
    else:
        with pytest.raises(ValueError):
            al.alert_track(r, n, 0, W, lags=lags)


@pytest.mark.parametrize("kwargs", [dict(n=0, gap=0), dict(n=1, gap=-1),
                                    dict(n=1, gap=0, lags=-1)])
def test_alert_track_refusals(kwargs):
    with pytest.raises(ValueError):
        al.alert_track(ratio_with([], 20), warmup=W, **kwargs)


@pytest.mark.parametrize("bad", [np.array([0.5, np.nan] + [0.5] * 10),
                                 np.array([0.5, np.inf] + [0.5] * 10),
                                 np.full((12, 1), 0.5)])
def test_alert_track_refuses_nan_inf_and_2d(bad):
    with pytest.raises(ValueError):
        al.alert_track(bad, 1, 0, W)


def test_no_look_ahead():
    # Causal: the track up to sample t is the same whether or not later samples exist,
    # and changing later samples never changes earlier decisions.
    rng = np.random.default_rng(1)
    r = rng.uniform(0.0, 2.0, 120)
    full = al.alert_track(r, 3, 4, W)
    for t in range(W + 1, len(r) + 1):
        assert al.alert_track(r[:t], 3, 4, W).tolist() == full[:t].tolist()
    changed = r.copy()
    changed[60:] = rng.uniform(0.0, 2.0, 60)
    assert al.alert_track(changed, 3, 4, W)[:60].tolist() == full[:60].tolist()
