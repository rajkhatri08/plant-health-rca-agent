"""Hand-built cases for eval/baselines/alarms.py (decision 58).

Index 0 is sample 1. Every expected value is worked out in a comment. These fail with
NotImplementedError until Raj implements the stubs.

Details proposed by Claude and still to be confirmed by Raj (docs/log.md, week 3
session 3): the strict/inclusive edges of the hysteresis, σ as the pooled ddof-0
standard deviation, and the analyzer on-delay as the first reading past the limit.
"""

import numpy as np
import pytest

from app.detector import alerting
from eval.baselines import alarms as al


def col(*values):
    """A one-column run (samples x 1), float64."""
    return np.array(values, dtype=float)[:, None]


def bits(a):
    return np.asarray(a).astype(int).ravel().tolist()


# ---------- constants (decision 58) ----------

def test_constants():
    assert al.DEADBAND_SIGMA == {"temperature": 0.25, "pressure": 0.25, "flow": 0.5,
                                 "level": 0.5, "composition": 0.5}
    assert (al.VALVE_LOW, al.VALVE_HIGH) == (2.0, 98.0)
    assert al.ANALYZER_ON_DELAY == 1


# ---------- tag_limits and tag_spread ----------

# Warm-up 1 drops the 100 and -100. Pooled scored values in column 0: 1..10.
# Column 1 is ten times column 0.
RUN_A = np.column_stack([[100.0, 1, 2, 3, 4, 5], [1000.0, 10, 20, 30, 40, 50]])
RUN_B = np.column_stack([[-100.0, 6, 7, 8, 9, 10], [-1000.0, 60, 70, 80, 90, 100]])


def test_limits_two_sided_at_the_same_q():
    # q = 80: lo is the 10th percentile, hi the 90th, of 1..10 (linear).
    # 10th: position 0.1 * 9 = 0.9 -> 1 + 0.9 * (2 - 1) = 1.9
    # 90th: position 0.9 * 9 = 8.1 -> 9 + 0.1 * (10 - 9) = 9.1
    lo, hi = al.tag_limits([RUN_A, RUN_B], 80, 1)
    assert lo == pytest.approx([1.9, 19.0])
    assert hi == pytest.approx([9.1, 91.0])


def test_limits_at_q_50():
    # 25th: position 2.25 -> 3.25; 75th: position 6.75 -> 7.75.
    lo, hi = al.tag_limits([RUN_A, RUN_B], 50, 1)
    assert lo == pytest.approx([3.25, 32.5]) and hi == pytest.approx([7.75, 77.5])


def test_limits_ignore_the_warmup():
    # Warm-up 0 keeps the 100 and -100: sorted pooled values are -100, 1, 2, ..., 10, 100
    # (12 values). The 10th percentile sits at position 0.1 * 11 = 1.1, between 1 and 2:
    # 1.1, not 1.9.
    lo, _ = al.tag_limits([RUN_A, RUN_B], 80, 0)
    assert lo[0] == pytest.approx(1.1)


def test_spread_is_pooled_ddof0():
    # Variance of 1..10 (ddof 0) is 8.25, so σ = 2.87228...; column 1 is ten times that.
    assert al.tag_spread([RUN_A, RUN_B], 1) == pytest.approx([np.sqrt(8.25), 10 * np.sqrt(8.25)])


@pytest.mark.parametrize("runs, q, warmup", [
    ([], 80, 1),                                          # no runs
    ([RUN_A, RUN_B[:, :1]], 80, 1),                       # column counts differ
    ([RUN_A[:, 0]], 80, 1),                               # not 2-D
    ([RUN_A, RUN_B], 80, 6),                              # warm-up doesn't end inside
    ([RUN_A, RUN_B], 0, 1),                               # q must be in (0, 100)
    ([RUN_A, RUN_B], 100, 1),
    ([np.where(RUN_A == 3, np.nan, RUN_A), RUN_B], 80, 1),  # NaN
    ([np.where(RUN_A == 3, np.inf, RUN_A), RUN_B], 80, 1),  # inf
])
def test_limits_refusals(runs, q, warmup):
    with pytest.raises(ValueError):
        al.tag_limits(runs, q, warmup)


@pytest.mark.parametrize("runs, warmup", [
    ([], 1), ([RUN_A[:, 0]], 1), ([RUN_A, RUN_B], 6),
    ([np.where(RUN_A == 3, np.nan, RUN_A), RUN_B], 1),
])
def test_spread_refusals(runs, warmup):
    with pytest.raises(ValueError):
        al.tag_spread(runs, warmup)


# ---------- hysteresis ----------

def test_high_alarm_holds_until_it_clears_the_band():
    # hi 10, band 2, so it clears at x <= 8.
    # s1 5 off; s2 11 on (> 10); s3 9 on (9 > 8); s4 8.5 on; s5 8 off (8 <= 8);
    # s6 7.9 off; s7 12 on; s8 10 on (10 > 8, still latched); s9 10.1 on.
    x = col(5, 11, 9, 8.5, 8, 7.9, 12, 10, 10.1)
    high, low = al.hysteresis(x, [0.0], [10.0], [2.0])
    assert bits(high) == [0, 1, 1, 1, 0, 0, 1, 1, 1]
    assert bits(low) == [0] * 9


def test_low_alarm_mirrors_the_high_one():
    # lo 0, band 1, so it clears at x >= 1.
    # s1 1 off; s2 -0.5 on (< 0); s3 0.5 on (0.5 < 1); s4 1 off (1 >= 1); s5 -2 on; s6 0 on.
    x = col(1, -0.5, 0.5, 1, -2, 0)
    high, low = al.hysteresis(x, [0.0], [10.0], [1.0])
    assert bits(low) == [0, 1, 1, 0, 1, 1]
    assert bits(high) == [0] * 6


def test_band_zero_is_a_plain_comparison_and_the_limit_itself_is_not_an_alarm():
    # Band 0: high = x > 10 exactly. x = 10 is not above the limit.
    x = col(5, 11, 10, 10.5, 9.99)
    high, _ = al.hysteresis(x, [0.0], [10.0], [0.0])
    assert bits(high) == [0, 1, 0, 1, 0]


def test_starts_off_and_can_turn_on_at_sample_1():
    # Nothing before sample 1: the state starts off, and 11 > 10 turns it on at once.
    high, _ = al.hysteresis(col(11, 9, 7), [0.0], [10.0], [2.0])
    assert bits(high) == [1, 1, 0]                 # 9 > 8 holds; 7 <= 8 clears


def test_columns_are_independent():
    # Column 0 as in the first case; column 1 has its own limits (lo -5, hi 5, band 1).
    # Column 1: s1 6 on; s2 4.5 on (4.5 > 4); s3 4 off (4 <= 4); s4 -6 low on.
    x = np.column_stack([[5.0, 11, 9, 8], [6.0, 4.5, 4, -6]])
    high, low = al.hysteresis(x, [0.0, -5.0], [10.0, 5.0], [2.0, 1.0])
    assert high[:, 0].astype(int).tolist() == [0, 1, 1, 0]
    assert high[:, 1].astype(int).tolist() == [1, 1, 0, 0]
    assert low[:, 1].astype(int).tolist() == [0, 0, 0, 1]
    assert not low[:, 0].any()


def test_hysteresis_has_no_look_ahead():
    rng = np.random.default_rng(3)
    x = rng.normal(size=(200, 4))
    lo, hi, band = [-1.0] * 4, [1.0] * 4, [0.5] * 4
    full_high, full_low = al.hysteresis(x, lo, hi, band)
    for t in (1, 17, 100, 199):
        cut_high, cut_low = al.hysteresis(x[:t], lo, hi, band)
        assert (cut_high == full_high[:t]).all() and (cut_low == full_low[:t]).all()
    changed = x.copy()
    changed[150:] = 50.0                           # a different future
    ch_high, ch_low = al.hysteresis(changed, lo, hi, band)
    assert (ch_high[:150] == full_high[:150]).all() and (ch_low[:150] == full_low[:150]).all()


@pytest.mark.parametrize("x, lo, hi, band", [
    (np.zeros(5), [0.0], [1.0], [0.0]),                   # not 2-D
    (np.zeros((5, 2)), [0.0], [1.0], [0.0]),              # one limit for two columns
    (np.zeros((5, 1)), [2.0], [1.0], [0.0]),              # lo > hi
    (np.zeros((5, 1)), [0.0], [1.0], [-0.1]),             # negative band
    (col(0, np.nan, 0), [0.0], [1.0], [0.0]),             # NaN
    (col(0, np.inf, 0), [0.0], [1.0], [0.0]),             # inf
    (np.zeros((5, 1)), [0.0], [np.nan], [0.0]),           # NaN limit
])
def test_hysteresis_refusals(x, lo, hi, band):
    with pytest.raises(ValueError):
        al.hysteresis(x, lo, hi, band)


# ---------- at_limit ----------

def test_valve_at_limit_is_inclusive_at_2_and_98():
    # <= 2 or >= 98: 1 on, 2 on, 2.1 off, 50 off, 97.9 off, 98 on, 100 on.
    assert bits(al.at_limit(col(1, 2, 2.1, 50, 97.9, 98, 100))) == [1, 1, 0, 0, 0, 1, 1]


def test_valve_at_limit_per_column():
    v = np.column_stack([[50.0, 99.0], [1.0, 50.0]])
    assert al.at_limit(v).astype(int).tolist() == [[0, 1], [1, 0]]


@pytest.mark.parametrize("v, low, high", [
    (np.zeros(3), 2.0, 98.0),                             # not 2-D
    (col(50, np.nan), 2.0, 98.0),                         # NaN
    (col(50, 50), 98.0, 2.0),                             # low >= high
])
def test_at_limit_refusals(v, low, high):
    with pytest.raises(ValueError):
        al.at_limit(v, low, high)


# ---------- plant_track ----------

def points(*columns):
    return np.column_stack([np.array(c, dtype=bool) for c in columns])


def test_on_delay_is_per_point_not_on_the_or():
    # Two points that take turns: the OR is on from sample 2 to 8 without a break, but
    # neither point is on for 2 samples in a row, so with n = 2 per point nothing fires.
    # (A plant-level on-delay on the OR would fire from sample 3.)
    p = points([0, 1, 0, 1, 0, 1, 0, 1], [0, 0, 1, 0, 1, 0, 1, 0])
    assert bits(al.plant_track(p, [2, 2], gap=0, warmup=2)) == [0] * 8


def test_different_on_delays_then_or():
    # Point 0, n = 2: [0,1,1,0,1,1,1,0] -> on at 3, 6, 7 -> [0,0,1,0,0,1,1,0]
    # Point 1, n = 1: on at 8 only.
    # OR: [0,0,1,0,0,1,1,1]; warm-up 2 is already off there.
    p = points([0, 1, 1, 0, 1, 1, 1, 0], [0, 0, 0, 0, 0, 0, 0, 1])
    assert bits(al.plant_track(p, [2, 1], gap=0, warmup=2)) == [0, 0, 1, 0, 0, 1, 1, 1]


def test_off_delay_groups_the_stream():
    # As above, then gap 2: on at t when the OR was on anywhere in t-2..t.
    # s4: s3 on -> 1; s5: s3 on -> 1; s6..s8 on. So [0,0,1,1,1,1,1,1].
    p = points([0, 1, 1, 0, 1, 1, 1, 0], [0, 0, 0, 0, 0, 0, 0, 1])
    assert bits(al.plant_track(p, [2, 1], gap=2, warmup=2)) == [0, 0, 1, 1, 1, 1, 1, 1]


def test_warmup_is_off_but_the_on_delay_may_use_it():
    # Warm-up 3. Point on from sample 2; n = 3 is met at sample 4 (samples 2, 3, 4),
    # the first scored sample.
    p = points([0, 1, 1, 1, 0])
    assert bits(al.plant_track(p, [3], gap=0, warmup=3)) == [0, 0, 0, 1, 0]
    # On through the warm-up with n = 1: off in the warm-up, on at sample 4.
    assert bits(al.plant_track(points([1, 1, 1, 1, 0]), [1], gap=0, warmup=3)) == [0, 0, 0, 1, 0]


def test_matches_persist_or_group_on_random_points():
    rng = np.random.default_rng(5)
    p = rng.random((300, 6)) < 0.3
    ns = [1, 2, 3, 4, 1, 2]
    expected = alerting.group(
        np.column_stack([alerting.persist(p[:, j], n) for j, n in enumerate(ns)]).any(axis=1),
        4, 9)
    out = al.plant_track(p, ns, gap=4, warmup=9)
    assert out.dtype.kind == "i" and set(np.unique(out)) <= {0, 1}
    assert bits(out) == bits(expected)


def test_plant_track_has_no_look_ahead():
    rng = np.random.default_rng(6)
    p = rng.random((200, 3)) < 0.4
    full = al.plant_track(p, [2, 3, 1], gap=3, warmup=9)
    for t in (10, 50, 199):
        assert bits(al.plant_track(p[:t], [2, 3, 1], gap=3, warmup=9)) == bits(full[:t])


def test_memory_bound_edge_is_allowed():
    # n - 1 = 3 = warm-up: allowed.
    al.plant_track(points([1, 1, 1, 1, 1]), [4], gap=0, warmup=3)


@pytest.mark.parametrize("p, ns, gap, warmup", [
    (points([1, 1, 1, 1, 1]), [5], 0, 3),                 # n - 1 = 4 > warm-up 3
    (points([1, 1, 1]), [0], 0, 0),                       # n < 1
    (points([1, 1, 1]), [1, 1], 0, 0),                    # one n per point
    (np.array([1, 0, 1]), [1], 0, 0),                     # not 2-D
    (np.array([[1.0], [np.nan]]), [1], 0, 0),             # not 0/1
    (np.array([[1], [2]]), [1], 0, 0),
    (points([1, 1, 1]), [1], -1, 0),                      # negative gap
    (points([1, 1, 1]), [1], 0, -1),                      # negative warm-up
])
def test_plant_track_refusals(p, ns, gap, warmup):
    with pytest.raises(ValueError):
        al.plant_track(p, ns, gap, warmup)