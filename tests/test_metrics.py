"""Hand-built cases for eval/metrics.py (PROTOCOL, Detection metrics; decision 49).

Every expected value is worked out in a comment. Samples are 1-based; 3 min per
sample; training onset after sample 20 (window 21..100), testing onset after 160
(window 161..240).

Confirmed by Raj and written into PROTOCOL.md (Detection metrics):
- quantiles: linear interpolation, and an interpolation touching +inf gives +inf
- bootstrap: B = 2000, percentile interval
- share still flagged: first detection to end of run, both ends included
The onset-to-divergence window is still open and deliberately not tested.
"""

import math
from collections import Counter

import numpy as np
import pytest

from eval import metrics as m
from eval.metrics import INF, ScoredRun

W = 5  # warm-up used in most cases: scoring starts at sample 6


def track(length, *on):
    """0/1 track; each (a, b) switches samples a..b on (1-based, inclusive)."""
    t = np.zeros(length, dtype=np.int8)
    for a, b in on:
        t[a - 1:b] = 1
    return t


# The worked example from session 3.
RUN_A = track(500, (3, 8), (15, 25), (41, 60))
N1 = ScoredRun(0, 1, track(500, (50, 52), (300, 310)))
N2 = ScoredRun(0, 2, track(500, (6, 8)))
N3 = ScoredRun(0, 3, track(500))


# --- notifications ---------------------------------------------------------------

@pytest.mark.parametrize("alert, warmup, expected", [
    (track(30), W, []),                            # never on
    (track(30, (10, 12), (15, 16)), W, [10, 15]),  # two rising edges
    (track(30, (3, 8)), W, [6]),                   # on at first scored sample 6: counts
    (track(30, (3, 5)), W, []),                    # on only inside warm-up
    (track(30, (5, 8)), W, [6]),                   # on from 5: still first scored sample 6
    (track(30, (6, 8)), W, [6]),                   # plain rising edge at 6
    (track(30, (1, 30)), 0, [1]),                  # no warm-up, on from sample 1
    (track(30, (1, 30)), W, [6]),                  # on all along: one notification only
    (RUN_A, W, [6, 15, 41]),                       # worked example
])
def test_notifications(alert, warmup, expected):
    assert m.notifications(alert, warmup) == expected


def test_notifications_accept_bool():
    assert m.notifications(track(30, (10, 12)).astype(bool), W) == [10]


# --- detection and delay -----------------------------------------------------------

def test_worked_example_run_a():
    # Rises at 6 and 15 are before onset; on at 20 and still on at 21-25 is no new
    # notification; rise at 41 is in the window: delay (41 - 20) * 3 = 63 min.
    assert m.detection(RUN_A, onset=20, warmup=W) == (True, 41, 63.0)


@pytest.mark.parametrize("on, expected", [
    ([(21, 30)], (True, 21, 3.0)),              # first window sample: 1 * 3
    ([(100, 110)], (True, 100, 240.0)),         # last window sample: 80 * 3
    ([(101, 110)], (False, None, INF)),         # one sample past the window
    ([(20, 120)], (False, None, INF)),          # already on at onset, stays on
    ([(18, 30), (40, 45)], (True, 40, 60.0)),   # on at onset, off, new rise at 40
    ([(10, 12)], (False, None, INF)),           # pre-onset alerts only
    ([(21, 22), (50, 55)], (True, 21, 3.0)),    # first rise in the window counts
])
def test_detection_training(on, expected):
    assert m.detection(track(500, *on), onset=m.TRAIN_ONSET, warmup=W) == expected


@pytest.mark.parametrize("on, expected", [
    ([(161, 170)], (True, 161, 3.0)),
    ([(240, 250)], (True, 240, 240.0)),
    ([(241, 250)], (False, None, INF)),
])
def test_detection_testing(on, expected):
    assert m.detection(track(960, *on), onset=m.TEST_ONSET, warmup=W) == expected


@pytest.mark.parametrize("warmup", [20, 25])
def test_warmup_must_end_before_onset(warmup):
    with pytest.raises(ValueError):
        m.detection(track(500, (30, 40)), onset=20, warmup=warmup)


# --- delay summary -----------------------------------------------------------------

@pytest.mark.parametrize("delays, expected", [
    # Worked example: sorted [3, 63, 240, inf]; median = (63 + 240) / 2 = 151.5;
    # q1 at position 0.75 = 3 + 0.75 * 60 = 48; q3 at 2.25 is between 240 and inf.
    ([63, INF, 3, 240], (151.5, 48.0, INF)),
    # [3, 6, 9]: positions 0.5, 1, 1.5 -> q1 4.5, median 6, q3 7.5.
    ([9, 3, 6], (6.0, 4.5, 7.5)),
    # More than half missed: median at position 1 is inf; q1 at 0.5 is between 3 and inf.
    ([3, INF, INF], (INF, INF, INF)),
    # Interpolating between two infinities must give inf, not NaN (median position 1.5).
    ([3, INF, INF, INF], (INF, INF, INF)),
    ([INF, INF], (INF, INF, INF)),
    ([12], (12.0, 12.0, 12.0)),
])
def test_delay_summary(delays, expected):
    median, q1, q3 = m.delay_summary(delays)
    assert not any(math.isnan(v) for v in (median, q1, q3))
    assert (median, q1, q3) == pytest.approx(expected)


def test_delay_summary_empty():
    with pytest.raises(ValueError):
        m.delay_summary([])


# --- false alerts per 24 h (rule 4: normal runs only) -------------------------------

def test_false_alerts_worked_example():
    # N1: 2 notifications, N2: 1 (on at first scored sample 6), N3: 0 -> 3.
    # Hours: 3 runs * (500 - 5) samples * 0.05 h = 74.25 h. Rate 3 / 74.25 * 24.
    count, hours, rate = m.false_alerts_per_24h([N1, N2, N3], warmup=W)
    assert count == 3
    assert hours == pytest.approx(74.25)
    assert rate == pytest.approx(3 / 74.25 * 24)  # about 0.97


def test_false_alerts_hours_follow_each_run_length():
    # (500 - 5 + 960 - 5) * 0.05 = 72.5 h; no alerts.
    runs = [ScoredRun(0, 1, track(500)), ScoredRun(0, 2, track(960))]
    assert m.false_alerts_per_24h(runs, warmup=W) == pytest.approx((0, 72.5, 0.0))


def test_long_alert_is_one_false_alert():
    # On from sample 1 to the end: one notification at sample 6. 1 / 24.75 h * 24.
    count, hours, rate = m.false_alerts_per_24h([ScoredRun(0, 1, track(500, (1, 500)))], warmup=W)
    assert (count, hours) == (1, pytest.approx(24.75))
    assert rate == pytest.approx(24 / 24.75)


def test_false_alerts_refuse_fault_runs():
    with pytest.raises(ValueError):
        m.false_alerts_per_24h([N1, ScoredRun(1, 4, track(500, (50, 60)))], warmup=W)


# --- chance rate (rule 4: normal runs only) -----------------------------------------

def test_chance_rate_worked_example():
    # Fake onset after 20: N1 rises at 50 (in 21..100) yes; N2 rises at 6, no; N3 no.
    assert m.chance_rate([N1, N2, N3], fake_onset=20, warmup=W) == pytest.approx(1 / 3)


def test_chance_rate_refuses_fault_runs():
    with pytest.raises(ValueError):
        m.chance_rate([N1, ScoredRun(2, 1, track(500, (50, 60)))], fake_onset=20, warmup=W)


def test_chance_rate_empty():
    with pytest.raises(ValueError):
        m.chance_rate([], fake_onset=20, warmup=W)


# --- share still flagged ------------------------------------------------------------

@pytest.mark.parametrize("alert, first, expected", [
    (RUN_A, 41, 20 / 460),                 # 41-60 on, of samples 41..500
    (track(500, (41, 500)), 41, 1.0),      # on to the end
    (track(500, (500, 500)), 500, 1.0),    # detected at the last sample: 1 of 1
    (track(100, (21, 30), (61, 70)), 21, 20 / 80),  # 21-30 and 61-70, of 21..100
])
def test_share_still_flagged(alert, first, expected):
    assert m.share_still_flagged(alert, first) == pytest.approx(expected)


@pytest.mark.parametrize("first", [None, 30])  # a miss; a sample where the track is off
def test_share_still_flagged_rejects_bad_first_detection(first):
    with pytest.raises(ValueError):
        m.share_still_flagged(RUN_A, first)


# --- bootstrap over run numbers (rule 3) --------------------------------------------

def _mean_run_minus_one(runs):
    return float(np.mean([r.run - 1 for r in runs]))


def test_bootstrap_two_numbers_by_hand():
    # Runs 1 and 2, stat = mean of (run - 1). A resample of 2 numbers gives mean 0
    # (prob 1/4), 0.5 (1/2) or 1 (1/4). With 2000 resamples the 2.5th percentile is 0
    # and the 97.5th is 1.
    runs = [ScoredRun(0, 1, track(10)), ScoredRun(0, 2, track(10))]
    assert m.bootstrap_ci(runs, _mean_run_minus_one, np.random.default_rng(0)) == (0.0, 1.0)


def test_bootstrap_constant_stat():
    runs = [ScoredRun(0, k, track(10)) for k in range(1, 6)]
    assert m.bootstrap_ci(runs, lambda rs: 7.0, np.random.default_rng(0), n=200) == (7.0, 7.0)


def _grouped_runs(numbers, faults=(0, 1, 2), seed=0):
    rng = np.random.default_rng(seed)
    runs = []
    for k in numbers:
        t = (rng.random(50) < rng.random()).astype(np.int8)
        runs += [ScoredRun(f, k, t.copy()) for f in faults]  # twins: identical tracks
    return runs


def test_bootstrap_draws_whole_run_number_groups():
    # Every resample must hold, for each file, the same multiset of run numbers, with
    # as many draws as there are distinct numbers (5).
    runs = _grouped_runs(range(1, 6))
    seen = []

    def stat(resample):
        per_file = {f: Counter(r.run for r in resample if r.fault == f) for f in (0, 1, 2)}
        assert per_file[0] == per_file[1] == per_file[2]
        assert sum(per_file[0].values()) == 5
        seen.append(per_file[0])
        return 0.0

    m.bootstrap_ci(runs, stat, np.random.default_rng(1), n=300)
    assert len(seen) == 300
    assert any(max(c.values()) > 1 for c in seen)  # it really resamples with replacement


def test_bootstrap_keeps_twins_together():
    # Normal run k and fault run k have identical tracks. Drawn together, the share
    # flagged among normal runs always equals the share among fault runs, so the
    # difference is exactly 0 in every resample. Drawn separately, it wouldn't be.
    runs = _grouped_runs(range(1, 11), faults=(0, 1))

    def diff(resample):
        flagged = {f: [r.alert.max() for r in resample if r.fault == f] for f in (0, 1)}
        return float(np.mean(flagged[0]) - np.mean(flagged[1]))

    assert m.bootstrap_ci(runs, diff, np.random.default_rng(2), n=500) == (0.0, 0.0)


def test_bootstrap_is_seeded():
    runs = _grouped_runs(range(1, 11))
    a = m.bootstrap_ci(runs, _mean_run_minus_one, np.random.default_rng(3), n=500)
    b = m.bootstrap_ci(runs, _mean_run_minus_one, np.random.default_rng(3), n=500)
    assert a == b


# --- paired bootstrap ---------------------------------------------------------------

def _total_on(runs):
    return float(np.mean([r.alert.sum() for r in runs]))


def test_paired_identical_detectors_differ_by_zero():
    runs = _grouped_runs(range(1, 11), faults=(0,))
    assert m.paired_bootstrap_ci(runs, runs, _total_on, np.random.default_rng(4), n=500) == (0.0, 0.0)


def test_paired_uses_the_same_draw_for_both():
    # Detector A flags exactly one more sample than B on every run, and B varies a lot
    # between runs. With the same draw, stat(A) - stat(B) is exactly 1 every time.
    # With different draws it would swing with B's run-to-run spread.
    rng = np.random.default_rng(5)
    runs_b, runs_a = [], []
    for k in range(1, 11):
        n_on = int(rng.integers(0, 40))
        runs_b.append(ScoredRun(0, k, track(50, (1, n_on)) if n_on else track(50)))
        runs_a.append(ScoredRun(0, k, track(50, (1, n_on + 1))))
    lo, hi = m.paired_bootstrap_ci(runs_a, runs_b, _total_on, np.random.default_rng(6), n=500)
    assert (lo, hi) == (pytest.approx(1.0), pytest.approx(1.0))


# --- review findings 1-4 and untested error paths 5-6 (ValueError only) ---------------

# 1. Bootstrap intervals never return NaN.

def test_bootstrap_always_infinite_stat_gives_inf_inf():
    runs = [ScoredRun(1, k, track(10)) for k in range(1, 5)]
    lo, hi = m.bootstrap_ci(runs, lambda rs: INF, np.random.default_rng(0), n=200)
    assert (lo, hi) == (INF, INF)


def test_bootstrap_sometimes_infinite_stat_gives_finite_inf():
    # Runs 1 and 2; the stat is 5.0 when run 2 isn't drawn (prob 1/4), else +inf
    # (prob 3/4). So the 2.5th percentile is 5.0 and the 97.5th is +inf.
    runs = [ScoredRun(1, 1, track(10)), ScoredRun(1, 2, track(10))]

    def stat(rs):
        return INF if any(r.run == 2 for r in rs) else 5.0

    lo, hi = m.bootstrap_ci(runs, stat, np.random.default_rng(0))
    assert not math.isnan(lo) and not math.isnan(hi)
    assert math.isfinite(lo) and hi == INF


def test_paired_bootstrap_refuses_inf_minus_inf():
    runs = [ScoredRun(1, k, track(10)) for k in range(1, 5)]
    with pytest.raises(ValueError):
        m.paired_bootstrap_ci(runs, runs, lambda rs: INF, np.random.default_rng(0), n=50)


# 2. NaN delays are refused.

def test_delay_summary_refuses_nan():
    with pytest.raises(ValueError):
        m.delay_summary([3.0, math.nan, 6.0])


# 3. Tracks must be 0/1, and warm-up can't be negative.

@pytest.mark.parametrize("bad", [math.nan, 2, 0.5])
def test_notifications_refuse_non_binary_values(bad):
    alert = np.array([0, bad, 0], dtype=float)
    with pytest.raises(ValueError):
        m.notifications(alert, 0)


def test_notifications_refuse_negative_warmup():
    with pytest.raises(ValueError):
        m.notifications(track(10, (3, 4)), -1)


# 4. The warm-up must end inside every run (at least one scored sample).

@pytest.mark.parametrize("lengths", [[3], [5], [500, 3]])  # warm-up 5
def test_false_alerts_refuse_warmup_not_ending_inside_a_run(lengths):
    runs = [ScoredRun(0, k, track(n)) for k, n in enumerate(lengths, start=1)]
    with pytest.raises(ValueError):
        m.false_alerts_per_24h(runs, warmup=W)


# 5. Paired bootstrap needs the same run numbers for both detectors.

def test_paired_bootstrap_refuses_different_run_numbers():
    a = [ScoredRun(0, k, track(10)) for k in (1, 2, 3)]
    b = [ScoredRun(0, k, track(10)) for k in (1, 2, 4)]
    with pytest.raises(ValueError):
        m.paired_bootstrap_ci(a, b, _total_on, np.random.default_rng(0), n=50)


# 6. Empty input is refused.

def test_bootstrap_refuses_empty():
    with pytest.raises(ValueError):
        m.bootstrap_ci([], _total_on, np.random.default_rng(0), n=50)


def test_paired_bootstrap_refuses_empty():
    with pytest.raises(ValueError):
        m.paired_bootstrap_ci([], [], _total_on, np.random.default_rng(0), n=50)
