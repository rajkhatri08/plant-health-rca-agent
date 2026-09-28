"""Hand-built cases for app/detector/dpca.py: lagged data and the lag rule.

The lag rule is the new-relations rule of Ku, Storer and Georgakis (1995), "Disturbance
detection and isolation by dynamic principal component analysis", with k from our parallel
analysis and L_max = 4 (Raj, week 3 session 1). Stop reading (Raj, week 3 session 7): at the
first l* >= 1 with r_new(l*) <= 0, L = l* - 1; no stop by L_max gives L = L_max, capped.
"""

import numpy as np
import pytest

from app.detector import dpca, pca
from app.detector.dpca import LagChoice

# 4 samples, 2 tags. Sample t (1-based) is (t, 10t), so every value shows where it came from.
X4 = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0], [4.0, 40.0]])


def tags(m):
    return tuple(f"TG-{i:03d}" for i in range(m))


# --- lagged: one run -----------------------------------------------------------------

def test_lagged_zero_lags_is_the_data():
    assert np.array_equal(dpca.lagged(X4, 0), X4)


def test_lagged_one_lag():
    # Rows are samples 2..4, laid out [x_t | x_{t-1}].
    expected = np.array([[2, 20, 1, 10],
                         [3, 30, 2, 20],
                         [4, 40, 3, 30]], dtype=float)
    assert np.array_equal(dpca.lagged(X4, 1), expected)


def test_lagged_two_lags():
    # Rows are samples 3..4, laid out [x_t | x_{t-1} | x_{t-2}].
    expected = np.array([[3, 30, 2, 20, 1, 10],
                         [4, 40, 3, 30, 2, 20]], dtype=float)
    assert np.array_equal(dpca.lagged(X4, 2), expected)


def test_lagged_has_no_look_ahead():
    # With 2 lags, row i covers samples i..i+2 (0-based). Changing sample 6 may change
    # rows 4, 5 and 6 only; rows 0..3 end before it.
    X = np.random.default_rng(0).normal(size=(10, 3))
    before = dpca.lagged(X, 2)
    Y = X.copy()
    Y[6] += 100.0
    after = dpca.lagged(Y, 2)
    assert np.array_equal(after[:4], before[:4])
    assert not np.array_equal(after[4:7], before[4:7])


def test_lagged_computes_in_float64():
    assert dpca.lagged(X4.astype(np.float32), 1).dtype == np.float64


@pytest.mark.parametrize("X, lags", [
    (X4, -1),                            # negative lags
    (X4[:, 0], 1),                       # not 2-D
    (X4[:2], 2),                         # 2 samples, 2 lags: no complete row
    (X4[:2], 3),
])
def test_lagged_refusals(X, lags):
    with pytest.raises(ValueError):
        dpca.lagged(X, lags)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_lagged_refuses_non_finite(bad):
    X = X4.copy()
    X[1, 1] = bad
    with pytest.raises(ValueError):
        dpca.lagged(X, 1)


# --- lagged_tags ---------------------------------------------------------------------

def test_lagged_tags():
    assert dpca.lagged_tags(("A", "B"), 0) == ("A", "B")
    assert dpca.lagged_tags(("A", "B"), 2) == ("A", "B", "A@t-1", "B@t-1", "A@t-2", "B@t-2")


def test_lagged_tags_match_lagged_columns():
    assert len(dpca.lagged_tags(tags(2), 2)) == dpca.lagged(X4, 2).shape[1]


def test_lagged_tags_refuse_negative_lags():
    with pytest.raises(ValueError):
        dpca.lagged_tags(("A",), -1)


# --- stack_lagged: many runs ---------------------------------------------------------

# Run 1 is all positive (6 samples), run 2 all negative (5 samples), so a row that mixed
# runs would hold both signs.
RUN1 = np.arange(1.0, 13.0).reshape(6, 2)
RUN2 = -np.arange(1.0, 11.0).reshape(5, 2)


@pytest.mark.parametrize("lags", [0, 1, 2])
def test_stack_lagged_rows_are_the_same_samples_at_every_lag(lags):
    # Warm-up 2: samples 3..6 of run 1 (4 rows) and 3..5 of run 2 (3 rows), 7 in all,
    # whatever the lag count. Only the number of columns changes: 2 (lags + 1).
    S = dpca.stack_lagged([RUN1, RUN2], lags, warmup=2)
    assert S.shape == (7, 2 * (lags + 1))
    assert np.array_equal(S[:, :2], np.vstack([RUN1[2:], RUN2[2:]]))   # lag-0 block


def test_stack_lagged_never_mixes_runs():
    S = dpca.stack_lagged([RUN1, RUN2], 2, warmup=2)
    assert (S[:4] > 0).all() and (S[4:] < 0).all()


def test_stack_lagged_reads_warm_up_samples():
    # Run 1's first row is sample 3 with 2 lags: [x3 | x2 | x1], and x1, x2 are warm-up.
    S = dpca.stack_lagged([RUN1, RUN2], 2, warmup=2)
    assert np.array_equal(S[0], [5, 6, 3, 4, 1, 2])
    assert np.array_equal(S[4], [-5, -6, -3, -4, -1, -2])              # run 2 starts fresh


def test_stack_lagged_keeps_run_order():
    S = dpca.stack_lagged([RUN2, RUN1], 1, warmup=2)
    assert (S[:3] < 0).all() and (S[3:] > 0).all()


@pytest.mark.parametrize("lags, warmup", [(3, 2), (-1, 2), (0, -1)])
def test_stack_lagged_refusals(lags, warmup):
    with pytest.raises(ValueError):
        dpca.stack_lagged([RUN1, RUN2], lags, warmup)


# --- new_relations -------------------------------------------------------------------

@pytest.mark.parametrize("r, expected", [
    # 3 static relations. Each appears once per time block: r(l) = 3(l+1).
    # r_new(1) = 6 - 2*3 = 0; r_new(2) = 9 - (3*3 + 2*0) = 0.
    ((3, 6, 9), (3, 0, 0)),
    # One relation first seen at lag 1 (x2_t = x1_{t-1}, say). At l = 2 it appears twice
    # (at t and at t-1): r_new(2) = 2 - (3*0 + 2*1) = 0; r_new(3) = 3 - (4*0 + 3*1 + 2*0) = 0.
    ((0, 1, 2, 3), (0, 1, 0, 0)),
    # 2 static plus 1 at lag 1: r(1) = 2*2 + 1 = 5, r(2) = 3*2 + 2*1 = 8.
    # r_new(1) = 5 - 2*2 = 1; r_new(2) = 8 - (3*2 + 2*1) = 0.
    ((2, 5, 8), (2, 1, 0)),
    # A count one short at l = 1 (the parallel-analysis edge): r_new(1) = 5 - 2*3 = -1.
    ((3, 5), (3, -1)),
    # Every lag adds one new relation: r(l) = sum of (l - i + 1) for i = 0..l.
    ((1, 3, 6, 10, 15), (1, 1, 1, 1, 1)),
])
def test_new_relations_by_hand(r, expected):
    got = dpca.new_relations(r)
    assert got == expected
    assert all(isinstance(v, int) for v in got)


# --- choose_lags with fake relation counts -------------------------------------------

def fake_count(r, m=4):
    """count(l) -> (k, r) from a list of r(l), with k = m(l+1) - r(l); records each call."""
    calls = []

    def count(l):
        calls.append(l)
        return m * (l + 1) - r[l], r[l]
    return count, calls


def test_static_process_gives_zero_lags():
    # r_new = (3, 0): lag 1 adds nothing, so L = 0 and DPCA equals static PCA.
    count, calls = fake_count((3, 6, 9, 12, 15))
    assert dpca.choose_lags(count) == LagChoice(lags=0, k=(1, 2), r=(3, 6), r_new=(3, 0),
                                                capped=False)
    assert calls == [0, 1]                       # nothing computed past the stop


def test_lag_one_relation_gives_one_lag():
    # r_new = (0, 1, 0). r_new(0) = 0 isn't a stop; lag 2 adds nothing, so L = 1.
    count, calls = fake_count((0, 1, 2, 3, 4))
    choice = dpca.choose_lags(count)
    assert choice.lags == 1 and choice.r_new == (0, 1, 0) and not choice.capped
    assert calls == [0, 1, 2]


def test_negative_new_relations_stop():
    # r_new(1) = -1 <= 0: stop at l* = 1, L = 0.
    count, calls = fake_count((3, 5, 9))
    choice = dpca.choose_lags(count)
    assert choice.lags == 0 and choice.r_new == (3, -1) and calls == [0, 1]


def test_stop_at_l_max_is_not_capped():
    # r_new = (1, 1, 1, 1, 0): r(4) = 5 + 4 + 3 + 2 + 0 = 14. The stop comes at l* = 4,
    # so L = 3, not capped.
    count, calls = fake_count((1, 3, 6, 10, 14))
    choice = dpca.choose_lags(count)
    assert choice.lags == 3 and not choice.capped and calls == [0, 1, 2, 3, 4]


def test_no_stop_is_capped_at_l_max():
    # r_new = 1 at every l: no stop by l = 4, so L = 4 and capped. l = 5 is never computed.
    count, calls = fake_count((1, 3, 6, 10, 15, 21), m=5)
    choice = dpca.choose_lags(count)
    assert choice == LagChoice(lags=4, k=(4, 7, 9, 10, 10), r=(1, 3, 6, 10, 15),
                               r_new=(1, 1, 1, 1, 1), capped=True)
    assert calls == [0, 1, 2, 3, 4]


def test_smaller_l_max_caps_earlier():
    count, calls = fake_count((1, 3, 6, 10, 15))
    choice = dpca.choose_lags(count, l_max=2)
    assert choice.lags == 2 and choice.capped and calls == [0, 1, 2]


def test_rule_misses_a_relation_that_skips_lags():
    # A known property of the rule, pinned here so it isn't a surprise: it stops at the
    # first lag with nothing new. A relation first seen at lag 3, with none at lags 1-2,
    # is never reached: r_new(1) = 0, so L = 0.
    count, calls = fake_count((0, 0, 0, 1, 2))
    assert dpca.choose_lags(count).lags == 0 and calls == [0, 1]


@pytest.mark.parametrize("l_max", [0, -1])
def test_l_max_below_one_refused(l_max):
    count, calls = fake_count((1, 3, 6))
    with pytest.raises(ValueError):
        dpca.choose_lags(count, l_max=l_max)
    assert calls == []                           # refused before any count


def test_default_l_max_is_four():
    assert dpca.L_MAX == 4


# --- relation_count on synthetic plants ----------------------------------------------

def plant(lagged_pair, runs=4, T=1000, noise=0.3, seed=0):
    """4 tags per run. Tags 0 and 1 follow factor f_t; tags 2 and 3 follow f_{t-1} if
    lagged_pair, else a second factor g_t. f and g are white noise, each tag gets its own
    small noise. Each factor pair has a correlation eigenvalue near 1.9, and the noise
    directions sit near 0.08, far from the shuffled eigenvalues near 1."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(runs):
        f = rng.normal(size=T + 1)                         # f[1:] is f_t, f[:-1] is f_{t-1}
        second = f[:-1] if lagged_pair else rng.normal(size=T)
        cols = [f[1:], f[1:], second, second]
        out.append(np.column_stack([c + noise * rng.normal(size=T) for c in cols]))
    return out


PA_SEED = 20260927


def counter(runs, warmup=9):
    return lambda l: dpca.relation_count(runs, tags(4), l, warmup, np.random.default_rng(PA_SEED))


def test_relation_count_is_parallel_analysis_on_the_stacked_matrix():
    runs = plant(lagged_pair=True)
    for lags in (0, 2):
        X = dpca.stack_lagged(runs, lags, 9)
        k = pca.parallel_analysis(X, dpca.lagged_tags(tags(4), lags), np.random.default_rng(PA_SEED))
        assert dpca.relation_count(runs, tags(4), lags, 9, np.random.default_rng(PA_SEED)) \
            == (k, 4 * (lags + 1) - k)


def test_static_plant_end_to_end():
    # Two independent factors at time t. l = 0: k = 2, r = 4 - 2 = 2.
    # l = 1: the lagged matrix holds f_t, g_t, f_{t-1}, g_{t-1}: k = 4, r = 8 - 4 = 4.
    # r_new(1) = 4 - 2*2 = 0: stop, L = 0.
    choice = dpca.choose_lags(counter(plant(lagged_pair=False)))
    assert choice == LagChoice(lags=0, k=(2, 4), r=(2, 4), r_new=(2, 0), capped=False)


def test_lagged_plant_end_to_end():
    # Tags 2-3 follow f_{t-1}, so at l lags the matrix holds f_t .. f_{t-l-1}: k = l + 2.
    # r = (4-2, 8-3, 12-4) = (2, 5, 8); r_new = (2, 5 - 4, 8 - (6 + 2)) = (2, 1, 0).
    # Lag 1 brings one new relation (tags 2-3 at t against tags 0-1 at t-1); lag 2 nothing.
    choice = dpca.choose_lags(counter(plant(lagged_pair=True)))
    assert choice == LagChoice(lags=1, k=(2, 3, 4), r=(2, 5, 8), r_new=(2, 1, 0), capped=False)

# --- scores: one whole run (week 3 session 8) ----------------------------------------

from app.detector import alerting                                   # noqa: E402
from app.detector.pca import PCAModel                               # noqa: E402
from eval import calibrate as cal                                   # noqa: E402

WARMUP = 9


def dpca_model(lags, runs=None):
    """PCA fitted on the lagged synthetic plant. At L lags it holds f_t .. f_{t-L-1}, so
    k = L + 2 (the end-to-end test above checks this for L = 0..2)."""
    runs = plant(lagged_pair=True) if runs is None else runs
    X = dpca.stack_lagged(runs, lags, WARMUP)
    return pca.fit(X, dpca.lagged_tags(tags(4), lags), lags + 2)


def test_scores_without_lags_are_static_pca():
    model = dpca_model(0)
    X = plant(lagged_pair=True, runs=1, seed=5)[0]
    t2, spe = dpca.scores(model, X, 0)
    s_t2, s_spe = pca.scores(model, X)
    assert np.array_equal(t2, s_t2) and np.array_equal(spe, s_spe)


def test_scores_known_model_by_hand():
    # One base tag, one lag. Kept direction e1 (the current sample) with λ = 2.
    # X = 1, 2, 3 gives lagged rows (2, 1) and (3, 2) for samples 2 and 3.
    # T² = t²/2 with t = the current value: 4/2 = 2, 9/2 = 4.5. SPE = the lag value²: 1, 4.
    # Sample 1 has no complete row: 0.0.
    model = PCAModel(tags=("A", "A@t-1"), mean=np.zeros(2), scale=np.ones(2),
                     loadings=np.array([[1.0], [0.0]]), eigenvalues=np.array([2.0]),
                     all_eigenvalues=np.array([2.0, 0.5]))
    t2, spe = dpca.scores(model, np.array([[1.0], [2.0], [3.0]]), 1)
    assert t2 == pytest.approx([0.0, 2.0, 4.5]) and spe == pytest.approx([0.0, 1.0, 4.0])


def test_scores_place_lagged_rows_at_their_samples():
    model = dpca_model(2)
    X = plant(lagged_pair=True, runs=1, seed=5)[0]
    t2, spe = dpca.scores(model, X, 2)
    e_t2, e_spe = pca.scores(model, dpca.lagged(X, 2))
    assert len(t2) == len(spe) == len(X)                          # whole run, index 0 = sample 1
    assert t2.dtype == np.float64 and spe.dtype == np.float64
    assert np.array_equal(t2[2:], e_t2) and np.array_equal(spe[2:], e_spe)
    assert np.array_equal(t2[:2], [0.0, 0.0]) and np.array_equal(spe[:2], [0.0, 0.0])


def test_scores_accept_float32_and_compute_in_float64():
    model = dpca_model(1)
    X = plant(lagged_pair=True, runs=1, seed=5)[0]
    t2, _ = dpca.scores(model, X.astype(np.float32), 1)
    assert t2.dtype == np.float64
    assert t2 == pytest.approx(dpca.scores(model, X, 1)[0], rel=1e-4)


@pytest.mark.parametrize("t", [3, 10, 500])
def test_scores_are_causal(t):
    # Cutting the run at sample t never changes a score up to t (no look-ahead). Equal to
    # rounding, not bit for bit: BLAS sums a matrix product in an order that depends on the
    # row count, as in test_pca.test_scoring_is_row_by_row.
    model = dpca_model(2)
    X = plant(lagged_pair=True, runs=1, seed=5)[0]
    full_t2, full_spe = dpca.scores(model, X, 2)
    cut_t2, cut_spe = dpca.scores(model, X[:t], 2)
    assert cut_t2 == pytest.approx(full_t2[:t], rel=1e-12, abs=1e-12)
    assert cut_spe == pytest.approx(full_spe[:t], rel=1e-12, abs=1e-12)


def test_the_pad_is_never_read():
    # With warm-up 9 and L = 4, decision 52 allows n <= 6. Setting the 4 pad entries to 1e9
    # changes neither the limits (which read samples 10 onwards) nor any alert track.
    model = dpca_model(4)
    runs = plant(lagged_pair=True, runs=6, T=300, seed=8)
    for r in runs[3:]:
        r[30:, 0] += 3.0                                            # a step, so some tracks alert
    scored = [dpca.scores(model, r, 4) for r in runs]
    padded = []
    for t2, spe in scored:
        t2, spe = t2.copy(), spe.copy()
        t2[:4], spe[:4] = 1e9, 1e9
        padded.append((t2, spe))
    limits = cal.limits_at([s[0] for s in scored], [s[1] for s in scored], 99.0, WARMUP)
    assert cal.limits_at([p[0] for p in padded], [p[1] for p in padded], 99.0, WARMUP) == limits
    alerted = 0
    for (t2, spe), (p_t2, p_spe) in zip(scored, padded):
        for n, gap in ((1, 0), (6, 0), (6, 5), (3, 20)):
            a = alerting.alert_track(alerting.plant_ratio(t2, spe, *limits), n, gap, WARMUP, 4)
            b = alerting.alert_track(alerting.plant_ratio(p_t2, p_spe, *limits), n, gap, WARMUP, 4)
            assert np.array_equal(a, b)
            alerted += int(a.any())
    assert alerted > 0                                              # the check isn't vacuous


def test_scores_refuse_a_model_fitted_with_other_lags():
    model = dpca_model(2)                                           # 12 tags = 4 x (2 + 1)
    X = plant(lagged_pair=True, runs=1, seed=5)[0]
    with pytest.raises(ValueError):
        dpca.scores(model, X, 1)                                    # 4 x 2 = 8 != 12
    with pytest.raises(ValueError):
        dpca.scores(model, X[:, :3], 2)                             # 3 x 3 = 9 != 12


@pytest.mark.parametrize("lags, n", [(-1, 50), (2, 2)])            # negative; no complete row
def test_scores_refusals(lags, n):
    model = dpca_model(2)
    X = plant(lagged_pair=True, runs=1, seed=5)[0][:n]
    with pytest.raises(ValueError):
        dpca.scores(model, X, lags)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_scores_refuse_non_finite(bad):
    model = dpca_model(2)
    X = plant(lagged_pair=True, runs=1, seed=5)[0].copy()
    X[7, 1] = bad
    with pytest.raises(ValueError):
        dpca.scores(model, X, 2)
