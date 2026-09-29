"""eval/calibrate.py's Watch calibration on hand-built cases (decision 66).

Two columns (think of them as two groups' RBC), 100 scored samples split over two runs
of 50, each run starting with one warm-up sample holding 1e6. That value would move every
percentile if the warm-up were counted. Column 0 takes the values 1..100.

numpy's linear percentile of 1..100 at p is 1 + 0.99p:
  p = 90 -> 90.1  (91..100 above: 10)
  p = 95 -> 95.05 (96..100 above: 5)
  p = 98 -> 98.02 (99, 100 above: 2)
  p = 99 -> 99.01 (100 above: 1)
Column 1 is either "aligned" (col0 + 100, so both columns are high on the same samples)
or "reversed" (201 - col0, so they're high on different samples). The any-group share is
the col0 share when aligned and twice it when reversed.

These fail with NotImplementedError until Raj implements the three functions.
"""

import numpy as np
import pytest

from eval import calibrate as cal

WARMUP = 1
GRID = (90.0, 95.0, 98.0, 99.0)


def runs(col1_of):
    col0 = np.arange(1.0, 101.0)
    both = np.column_stack([col0, col1_of(col0)])
    warm = np.full((1, 2), 1e6)
    return [np.vstack([warm, both[:50]]), np.vstack([warm, both[50:]])]


ALIGNED = runs(lambda c: c + 100)
REVERSED = runs(lambda c: 201 - c)


# ---------- watch_limits_at ----------

def test_limits_are_pooled_percentiles_of_scored_samples():
    got = cal.watch_limits_at(ALIGNED, 98.0, WARMUP)
    assert got.shape == (2,) and got.dtype == np.float64
    assert got == pytest.approx([98.02, 198.02], rel=1e-12)
    assert cal.watch_limits_at(REVERSED, 50.0, WARMUP) == pytest.approx([50.5, 150.5], rel=1e-12)


def test_limits_skip_the_warmup():
    # Counting the 1e6 warm-up samples would make the 100th percentile 1e6.
    assert cal.watch_limits_at(ALIGNED, 100.0, WARMUP) == pytest.approx([100.0, 200.0])


@pytest.mark.parametrize("p", [0.0, -1.0, 100.5])
def test_limits_refuse_p_outside_0_100(p):
    with pytest.raises(ValueError):
        cal.watch_limits_at(ALIGNED, p, WARMUP)


def test_limits_refusals():
    with pytest.raises(ValueError):
        cal.watch_limits_at([], 98.0, WARMUP)                             # no runs
    with pytest.raises(ValueError):
        cal.watch_limits_at([ALIGNED[0], ALIGNED[1][:, :1]], 98.0, WARMUP)   # column counts differ
    with pytest.raises(ValueError):
        cal.watch_limits_at(ALIGNED, 98.0, 51)                            # warm-up past a run's end
    bad = [ALIGNED[0].copy(), ALIGNED[1]]
    bad[0][5, 1] = np.nan
    with pytest.raises(ValueError):
        cal.watch_limits_at(bad, 98.0, WARMUP)


# ---------- watch_shares ----------

def test_shares_by_hand():
    # Limits (98.5, 150.5) on aligned columns: col0 above on 99, 100 (2 of 100);
    # col1 above where col0 > 50.5, 50 samples. Any: the same 50 samples (col0's are
    # among them), so 0.5.
    any_share, per = cal.watch_shares(ALIGNED, np.array([98.5, 150.5]), WARMUP)
    assert any_share == pytest.approx(0.5) and per == pytest.approx([0.02, 0.5])


def test_shares_count_different_samples_once_each():
    # Reversed, limits (98.5, 198.5): col0 above on col0 = 99, 100; col1 above where
    # 201 - col0 > 198.5, i.e. col0 = 1, 2. Four different samples: any = 0.04.
    any_share, per = cal.watch_shares(REVERSED, np.array([98.5, 198.5]), WARMUP)
    assert any_share == pytest.approx(0.04) and per == pytest.approx([0.02, 0.02])


def test_a_value_equal_to_its_limit_is_not_in_watch():
    any_share, per = cal.watch_shares(ALIGNED, np.array([100.0, 200.0]), WARMUP)
    assert any_share == 0.0 and list(per) == [0.0, 0.0]


def test_shares_skip_the_warmup():
    # The 1e6 warm-up samples are above any limit here, but they aren't scored.
    any_share, _ = cal.watch_shares(ALIGNED, np.array([1000.0, 1000.0]), WARMUP)
    assert any_share == 0.0


@pytest.mark.parametrize("limits", [np.array([98.5]), np.array([98.5, 0.0]),
                                    np.array([98.5, -1.0]), np.array([98.5, np.nan])])
def test_shares_refuse_bad_limits(limits):
    with pytest.raises(ValueError):
        cal.watch_shares(ALIGNED, limits, WARMUP)


# ---------- watch_limit ----------

def test_aligned_columns_share_their_exceedances():
    # Any share at p: 98 -> 2 of 100 (at the cap, passes); 95 -> 5 (fails). So p = 98.
    assert cal.watch_limit(ALIGNED, WARMUP, q_grid=GRID) == 98.0


def test_reversed_columns_add_up():
    # Any share: 99 -> 1 + 1 = 2 (passes); 98 -> 2 + 2 = 4 (fails). So p = 99.
    # The cap is on the plant (any group), so two groups each at 2% don't pass together.
    assert cal.watch_limit(REVERSED, WARMUP, q_grid=GRID) == 99.0


def test_bottom_of_the_grid_when_everything_passes():
    assert cal.watch_limit(ALIGNED, WARMUP, cap=0.2, q_grid=GRID) == 90.0


def test_none_when_the_top_already_fails():
    # Reversed at 99: 2 of 100 > 0.5%.
    assert cal.watch_limit(REVERSED, WARMUP, cap=0.005, q_grid=GRID) is None


def test_default_cap_and_grid():
    assert cal.WATCH_CAP == 0.02
    # On the real grid the aligned case lands exactly where a 2% share first holds: the
    # lowest p with 1 + 0.99p >= 98, i.e. p >= 97.98 (share 2 of 100 at 97.98, 3 below it).
    assert cal.watch_limit(ALIGNED, WARMUP) == 97.98


@pytest.mark.parametrize("grid", [(), (99.0, 98.0), (98.0, 98.0)])
def test_refuses_a_bad_grid(grid):
    with pytest.raises(ValueError):
        cal.watch_limit(ALIGNED, WARMUP, q_grid=grid)


@pytest.mark.parametrize("cap", [-0.01, 1.0, 1.5])
def test_refuses_a_bad_cap(cap):
    with pytest.raises(ValueError):
        cal.watch_limit(ALIGNED, WARMUP, cap=cap, q_grid=GRID)