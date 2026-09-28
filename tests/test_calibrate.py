"""eval/calibrate.py on hand-built cases (decision 54).

Index 0 is sample 1. A 480-sample scored stretch is 24 h (3-min samples), so the
budget there is at most 1 notification. These fail with NotImplementedError until Raj
implements eval/calibrate.py (and app/detector/alerting.py, which it uses).
"""

import numpy as np
import pytest

from eval import calibrate as cal

DAY = 480                                 # scored samples in 24 h


def ratio_with(above_samples, length):
    """Ratio 2.0 at the given 1-based samples, 0.5 elsewhere."""
    r = np.full(length, 0.5)
    for s in above_samples:
        r[s - 1] = 2.0
    return r


def table(per_q):
    """ratio_runs_at from {q: {run number: ratio}}, recording the q values asked for."""
    asked = []

    def ratio_runs_at(q):
        asked.append(q)
        return per_q[q]
    return ratio_runs_at, asked


ZERO = {1: ratio_with([], DAY)}
ONE = {1: ratio_with([100], DAY)}
TWO = {1: ratio_with([100, 200], DAY)}


# ---------- constants ----------

def test_grid_and_ranges():
    assert len(cal.Q_GRID) == 500
    assert cal.Q_GRID[0] == 95.0 and cal.Q_GRID[-1] == 99.99 and 99.0 in cal.Q_GRID
    assert all(a < b for a, b in zip(cal.Q_GRID, cal.Q_GRID[1:]))
    assert list(cal.GAP_RANGE) == list(range(0, 21))
    assert cal.SELECTION_FAULTS == (1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14)
    assert cal.BUDGET_PER_24H == 1.0


@pytest.mark.parametrize("lags, expected", [(0, range(1, 11)), (2, range(1, 9)),
                                            (9, range(1, 2))])
def test_n_range_follows_the_memory_bound(lags, expected):
    assert cal.n_range(lags, 9) == expected


def test_n_range_refuses_lags_beyond_warmup():
    with pytest.raises(ValueError):
        cal.n_range(10, 9)


# ---------- limits_at ----------

T2 = [np.array([100.0, 1, 2, 3]), np.array([100.0, 4, 5, 6])]
SPE = [np.array([-1.0, 10, 20, 30]), np.array([-1.0, 40, 50, 60])]


def test_limits_pool_scored_samples_only():
    # warm-up 1 drops the 100s and -1s. Pooled T² = 1..6: median (linear) = 3.5, max = 6.
    # Pooled SPE = 10..60: median 35.
    assert cal.limits_at(T2, SPE, 50, 1) == pytest.approx((3.5, 35.0))
    assert cal.limits_at(T2, SPE, 100, 1) == pytest.approx((6.0, 60.0))


def test_limits_linear_percentile():
    # 1..6 at q = 90: position 0.9 * 5 = 4.5 -> 5 + 0.5 * (6 - 5) = 5.5.
    assert cal.limits_at(T2, SPE, 90, 1)[0] == pytest.approx(5.5)


@pytest.mark.parametrize("t2, spe, q, warmup", [
    (T2, SPE, 0, 1),                      # q must be in (0, 100]
    (T2, SPE, 100.5, 1),
    ([], [], 50, 1),                      # no runs
    (T2, SPE[:1], 50, 1),                 # different run counts
    ([T2[0], T2[1][:3]], SPE, 50, 1),     # a run's T² and SPE lengths differ
    (T2, SPE, 50, 4),                     # warm-up doesn't end inside the runs
])
def test_limits_refusals(t2, spe, q, warmup):
    with pytest.raises(ValueError):
        cal.limits_at(t2, spe, q, warmup)


# ---------- lowest_stable_q ----------

def test_stable_q_skips_a_lucky_pass_below_a_failure():
    # q=1: 2 notifications (fails), q=2: 1 (passes), q=3: 2 (fails), q=4: 0 (passes).
    # Plain "lowest passing" would give 2; the stable answer from the top is 4.
    f, asked = table({1: TWO, 2: ONE, 3: TWO, 4: ZERO})
    assert cal.lowest_stable_q(f, 1, 0, 0, q_grid=(1, 2, 3, 4)) == 4
    assert asked == [4, 3]                # scans down from the top, stops at the failure


def test_stable_q_is_the_bottom_of_the_grid_when_all_pass():
    f, asked = table({1: ONE, 2: ONE, 3: ZERO})
    assert cal.lowest_stable_q(f, 1, 0, 0, q_grid=(1, 2, 3)) == 1
    assert asked == [3, 2, 1]


def test_stable_q_is_none_when_the_top_fails():
    f, _ = table({1: ZERO, 2: TWO})
    assert cal.lowest_stable_q(f, 1, 0, 0, q_grid=(1, 2)) is None


def test_exactly_the_budget_passes():
    # 1 notification in 24 h is 1.0 per 24 h: at most 1, so it passes.
    f, _ = table({5: ONE})
    assert cal.lowest_stable_q(f, 1, 0, 0, q_grid=(5,)) == 5


def test_budget_is_pooled_over_runs():
    # Two 24-h runs: 2 notifications in 48 h passes; 3 fails.
    two_days_ok = {1: ratio_with([100], DAY), 2: ratio_with([300], DAY)}
    two_days_bad = {1: ratio_with([100, 300], DAY), 2: ratio_with([50], DAY)}
    f, _ = table({1: two_days_bad, 2: two_days_ok})
    assert cal.lowest_stable_q(f, 1, 0, 0, q_grid=(1, 2)) == 2


def test_gap_is_applied():
    # Above at 100 and 102, with a 1-sample dip at 101: gap 1 merges them (1 notification),
    # gap 0 doesn't (2).
    f, _ = table({1: {1: ratio_with([100, 102], DAY)}})
    assert cal.lowest_stable_q(f, 1, 1, 0, q_grid=(1,)) == 1
    assert cal.lowest_stable_q(f, 1, 0, 0, q_grid=(1,)) is None


def test_persistence_is_applied():
    # Two single-sample blips: n = 1 counts 2 (fails); n = 2 counts 0 (passes).
    # Warm-up 1 so that n = 2 fits (decision 52); 481 samples keep 24 h scored.
    f, _ = table({1: {1: ratio_with([100, 200], DAY + 1)}})
    assert cal.lowest_stable_q(f, 1, 0, 1, q_grid=(1,)) is None
    assert cal.lowest_stable_q(f, 2, 0, 1, q_grid=(1,)) == 1


def test_warmup_is_not_counted():
    # warm-up 5, 485 samples = 24 h scored. The blip at sample 3 is in the warm-up; only
    # the one at 100 counts, so 1 notification passes.
    f, _ = table({1: {1: ratio_with([3, 100], DAY + 5)}})
    assert cal.lowest_stable_q(f, 1, 0, 5, q_grid=(1,)) == 1


def test_memory_bound_is_enforced_through_alert_track():
    f, _ = table({1: ZERO})
    with pytest.raises(ValueError):
        cal.lowest_stable_q(f, 2, 0, 0, q_grid=(1,))      # 0 + 2 - 1 > 0


@pytest.mark.parametrize("grid", [(), (2, 1), (1, 1)])
def test_grid_must_be_strictly_increasing_and_non_empty(grid):
    f, _ = table({1: ZERO, 2: ZERO})
    with pytest.raises(ValueError):
        cal.lowest_stable_q(f, 1, 0, 0, q_grid=grid)


# ---------- selection_score ----------

LEN = 120
HIT = np.array([0] * 24 + [1] * 6 + [0] * 90)        # notification at 25: in 21..100
MISS = np.zeros(LEN, dtype=int)
ON_BEFORE = np.array([0] * 14 + [1] * 106)            # on from 15: active at onset, a miss


def all_faults(tracks):
    return {f: list(tracks) for f in cal.SELECTION_FAULTS}


def test_selection_score_is_the_mean_rate():
    assert cal.selection_score(all_faults([HIT, MISS]), 9) == pytest.approx(0.5)


def test_alert_active_at_onset_is_not_a_detection():
    assert cal.selection_score(all_faults([ON_BEFORE]), 9) == 0.0


def test_faults_are_weighted_equally():
    # Fault 1: 4 runs, 3 hits (0.75). The other 11: 0.5 each. Mean = (0.75 + 5.5) / 12.
    tracks = all_faults([HIT, MISS])
    tracks[1] = [HIT, HIT, HIT, MISS]
    assert cal.selection_score(tracks, 9) == pytest.approx(6.25 / 12)


def test_faults_3_9_15_are_ignored():
    tracks = all_faults([HIT, MISS])
    for f in (3, 9, 15):
        tracks[f] = [HIT, HIT]
    assert cal.selection_score(tracks, 9) == pytest.approx(0.5)


@pytest.mark.parametrize("change", ["missing", "empty", "sealed", "normal"])
def test_selection_score_refusals(change):
    tracks = all_faults([HIT])
    if change == "missing":
        del tracks[2]
    elif change == "empty":
        tracks[2] = []
    elif change == "sealed":
        tracks[16] = [HIT]
    else:
        tracks[0] = [HIT]
    with pytest.raises(ValueError):
        cal.selection_score(tracks, 9)


# ---------- choose ----------

def test_choose_highest_score_among_eligible():
    # (3, 5) has the best score but no q, so it isn't eligible.
    c = {(1, 0): (99.0, 0.5), (2, 0): (98.0, 0.7), (3, 5): (None, 0.9)}
    assert cal.choose(c) == (2, 0, 98.0)


def test_choose_ties_smaller_n_then_smaller_gap():
    # All three are within 1e-12: smallest n is 2; between (2, 5) and (2, 1), gap 1.
    c = {(3, 0): (99.0, 0.7), (2, 5): (98.5, 0.7), (2, 1): (99.5, 0.7 + 1e-13)}
    assert cal.choose(c) == (2, 1, 99.5)


def test_choose_a_real_difference_is_not_a_tie():
    c = {(1, 0): (99.0, 0.7), (5, 5): (99.0, 0.7 + 1e-9)}
    assert cal.choose(c) == (5, 5, 99.0)


@pytest.mark.parametrize("c", [{}, {(1, 0): (None, 0.5)}])
def test_choose_refuses_no_eligible_setting(c):
    with pytest.raises(ValueError):
        cal.choose(c)


# ---------- lowest_stable_q with a track builder (decision 58) ----------
# Raj adds an optional `track` argument: track(x, n, gap, warmup, lags) -> 0/1 alert
# array, called on each run's value from ratio_runs_at(q). The default is
# alerting.alert_track, so every case above is unchanged. These fail with TypeError
# until the argument exists.

def alert_with(on_samples, length=DAY):
    """0/1 track with single-sample notifications at the given 1-based samples."""
    a = np.zeros(length, dtype=int)
    for s in on_samples:
        a[s - 1] = 1
    return a


def test_track_builder_is_used_instead_of_alert_track(monkeypatch):
    # ratio_runs_at returns labels, not ratios; the builder turns each label into a track.
    # q = 1: 2 notifications in 24 h (fails); q = 2: 1 (passes). Stable lowest: 2.
    from app.detector import alerting
    monkeypatch.setattr(alerting, "alert_track",
                        lambda *a, **k: pytest.fail("alert_track used despite a track builder"))
    tracks = {"two": alert_with([100, 200]), "one": alert_with([100])}
    calls = []

    def track(x, n, gap, warmup, lags):
        calls.append((x, n, gap, warmup, lags))
        return tracks[x]

    f, asked = table({1: {1: "two"}, 2: {1: "one"}})
    assert cal.lowest_stable_q(f, 3, 4, 0, lags=0, q_grid=(1, 2), track=track) == 2
    assert asked == [2, 1]
    assert calls == [("one", 3, 4, 0, 0), ("two", 3, 4, 0, 0)]   # n, gap, warm-up, lags passed on


def test_track_builder_budget_is_pooled_over_runs():
    # Two 24-h runs: 1 + 1 notifications in 48 h passes (1.0 per 24 h); 2 + 1 fails.
    tracks = {"a": alert_with([100]), "b": alert_with([100, 300])}
    f, _ = table({1: {1: "b", 2: "a"}, 2: {1: "a", 2: "a"}})
    assert cal.lowest_stable_q(f, 1, 0, 0, q_grid=(1, 2),
                               track=lambda x, n, gap, warmup, lags: tracks[x]) == 2


def test_default_track_is_alert_track():
    # Passing alert_track explicitly gives the same answer as leaving it out.
    from app.detector import alerting
    f, _ = table({1: TWO, 2: ONE, 3: TWO, 4: ZERO})
    assert (cal.lowest_stable_q(f, 1, 0, 0, q_grid=(1, 2, 3, 4), track=alerting.alert_track)
            == cal.lowest_stable_q(f, 1, 0, 0, q_grid=(1, 2, 3, 4)) == 4)
