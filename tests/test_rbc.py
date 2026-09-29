"""Hand-built cases and properties for app/detector/rbc.py (decisions 64, 65).

RBC for tag directions Ξ is the drop in the combined index phi = zᵀMz when those tags are
rebuilt from the others. The closed form is zᵀMΞ(ΞᵀMΞ)⁻¹ΞᵀMz. The property tests also
check it against that definition directly: phi(z) minus the smallest phi(z − Ξf) over f,
found by least squares. So they don't depend on the closed form being right.

Until Raj implements the stubs, the tests fail with NotImplementedError. The groups
loader's tests are in tests/test_groups.py.
"""

import numpy as np
import pytest

from app.detector import pca, rbc
from app.detector.pca import PCAModel
from tests.test_pca import FOUR, SCALE, TWO_TAGS, random_data, tags

# --- models ---------------------------------------------------------------------------

# The 2-tag model from test_pca: correlation 0.9, k = 1, P = (1, 1)/√2, λ1 = 1.9,
# mean 0, scale √(40/3). So z = x / SCALE.
TWO = pca.fit(FOUR, TWO_TAGS, 1)


def hand_three():
    """3 tags, mean 0 and scale 1 (so z = x), k = 1 with loading p = (0.8, 0.6, 0) and
    λ1 = 2 (the others 0.5 and 0.5, summing to 3)."""
    p = np.array([[0.8], [0.6], [0.0]])
    return PCAModel(tags=("TG-000", "TG-001", "TG-002"), mean=np.zeros(3), scale=np.ones(3),
                    loadings=p, eigenvalues=np.array([2.0]),
                    all_eigenvalues=np.array([2.0, 0.5, 0.5]))


def random_model(m=6, k=2, seed=0):
    return pca.fit(random_data(n=500, m=m, seed=seed), tags(m), k)


T2_LIM, SPE_LIM = 9.0, 3.0


def samples(model, n=40, seed=1, size=3.0):
    """Raw samples whose standardised values are random, some of them large."""
    z = np.random.default_rng(seed).normal(size=(n, len(model.tags))) * size
    return model.mean + z * model.scale


def standardised(model, X):
    return (np.asarray(X, dtype=np.float64) - model.mean) / model.scale


def rebuild_drop(M, z, cols):
    """RBC from its definition: phi(z) − min over f of phi(z − Ξf). Uses M = L Lᵀ
    (Cholesky), so phi(v) = |Lᵀ v|², and the minimum is a least-squares fit."""
    L = np.linalg.cholesky(M)
    Xi = np.eye(len(z))[:, list(cols)]
    f, *_ = np.linalg.lstsq(L.T @ Xi, L.T @ z, rcond=None)
    rest = z - Xi @ f
    return z @ M @ z - rest @ M @ rest


# --- index_matrix -----------------------------------------------------------------------

@pytest.mark.parametrize("t2_lim, spe_lim", [(1.0, 1.0), (2.0, 4.0)])
def test_index_matrix_two_tag_example(t2_lim, spe_lim):
    # PPᵀ = ½[[1, 1], [1, 1]], so PΛ⁻¹Pᵀ / T²lim = a·[[1, 1], [1, 1]] with a = 0.5 / (1.9·T²lim).
    # I − PPᵀ = ½[[1, −1], [−1, 1]], so (I − PPᵀ) / SPElim = b·[[1, −1], [−1, 1]] with b = 0.5 / SPElim.
    # M = [[a + b, a − b], [a − b, a + b]], in standardised units.
    a, b = 0.5 / (1.9 * t2_lim), 0.5 / spe_lim
    M = rbc.index_matrix(TWO, t2_lim, spe_lim)
    assert M == pytest.approx(np.array([[a + b, a - b], [a - b, a + b]]), rel=1e-12)


def test_index_matrix_three_tag_example():
    # With T²lim = SPElim = 1 and λ1 = 2: M = ppᵀ/2 + (I − ppᵀ) = I − ½ppᵀ.
    # ppᵀ = [[.64, .48, 0], [.48, .36, 0], [0, 0, 0]].
    M = rbc.index_matrix(hand_three(), 1.0, 1.0)
    assert M == pytest.approx(np.array([[0.68, -0.24, 0.0], [-0.24, 0.82, 0.0], [0.0, 0.0, 1.0]]), abs=1e-12)


def test_index_matrix_is_symmetric_positive_definite_float64():
    M = rbc.index_matrix(random_model(), T2_LIM, SPE_LIM)
    assert M.shape == (6, 6) and M.dtype == np.float64
    assert M == pytest.approx(M.T, abs=1e-14)
    assert np.linalg.eigvalsh(M).min() > 0


@pytest.mark.parametrize("t2_lim, spe_lim", [(0.0, 1.0), (1.0, 0.0), (-1.0, 1.0), (np.nan, 1.0),
                                             (1.0, np.inf)])
def test_index_matrix_refuses_bad_limits(t2_lim, spe_lim):
    with pytest.raises(ValueError):
        rbc.index_matrix(TWO, t2_lim, spe_lim)


# --- combined_index ---------------------------------------------------------------------

def test_combined_index_equals_t2_and_spe_over_their_limits():
    model = random_model()
    X = samples(model)
    t2, spe = pca.scores(model, X)
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    phi = rbc.combined_index(model, M, X)
    assert phi.shape == (len(X),) and phi.dtype == np.float64
    assert phi == pytest.approx(t2 / T2_LIM + spe / SPE_LIM, rel=1e-10)


def test_combined_index_is_not_the_plant_ratio():
    # r = max(T²/T²lim, SPE/SPElim) and phi is their sum, so r <= phi <= 2r, and phi > r
    # whenever both parts are non-zero. The alert uses r; attribution uses phi (decision 64).
    model = random_model()
    X = samples(model)
    t2, spe = pca.scores(model, X)
    r = np.maximum(t2 / T2_LIM, spe / SPE_LIM)
    phi = rbc.combined_index(model, rbc.index_matrix(model, T2_LIM, SPE_LIM), X)
    assert np.all(phi >= r * (1 - 1e-12)) and np.all(phi <= 2 * r * (1 + 1e-12))
    assert np.all(phi > r)


# --- tag_rbc: hand values ---------------------------------------------------------------

def test_tag_rbc_two_tag_example():
    # z = (1, 0), limits 1 and 1: a = 0.5/1.9, b = 0.5. Mz = (a + b, a − b), phi = a + b.
    # RBC_1 = (a + b)² / (a + b) = a + b = phi: rebuilding tag 1 removes everything.
    # RBC_2 = (a − b)² / (a + b).
    a, b = 0.5 / 1.9, 0.5
    X = np.array([[SCALE, 0.0]])                       # z = (1, 0)
    M = rbc.index_matrix(TWO, 1.0, 1.0)
    got = rbc.tag_rbc(TWO, M, X)
    assert got.shape == (1, 2)
    assert got[0] == pytest.approx([a + b, (a - b) ** 2 / (a + b)], rel=1e-12)
    assert rbc.combined_index(TWO, M, X)[0] == pytest.approx(a + b, rel=1e-12)


def test_tag_rbc_three_tag_example():
    # z = e1, M = [[.68, −.24, 0], [−.24, .82, 0], [0, 0, 1]]: Mz = (.68, −.24, 0), phi = .68.
    # RBC = (.68²/.68, .24²/.82, 0) = (.68, .0702439..., 0).
    model = hand_three()
    got = rbc.tag_rbc(model, rbc.index_matrix(model, 1.0, 1.0), np.array([[1.0, 0.0, 0.0]]))
    assert got[0] == pytest.approx([0.68, 0.0576 / 0.82, 0.0], abs=1e-12)


def test_smearing_plain_spe_contribution_blames_a_healthy_tag_rbc_does_not():
    # The textbook plain contribution to SPE is c_i = ((I − PPᵀ) z)_i². For a fault on tag 1
    # alone (z = e1) with p = (0.8, 0.6, 0): (I − ppᵀ) e1 = (0.36, −0.48, 0), so
    # c = (0.1296, 0.2304, 0). The healthy tag 2 gets more blame than the faulty tag 1.
    # RBC puts tag 1 first, with all of phi (a single-tag fault is fully removed by
    # rebuilding that tag).
    model = hand_three()
    z = np.array([1.0, 0.0, 0.0])
    P = model.loadings
    plain = ((np.eye(3) - P @ P.T) @ z) ** 2
    assert plain == pytest.approx([0.1296, 0.2304, 0.0], abs=1e-12)
    assert plain.argmax() == 1                         # the wrong tag
    got = rbc.tag_rbc(model, rbc.index_matrix(model, 1.0, 1.0), z[None, :])[0]
    assert got.argmax() == 0
    assert got[0] == pytest.approx(rbc.combined_index(model, rbc.index_matrix(model, 1.0, 1.0), z[None, :])[0])


# --- tag_rbc and group_rbc: properties ---------------------------------------------------

def test_single_tag_fault_is_fully_removed_and_ranked_first():
    # For z = f·e_j, RBC_j = phi exactly, and no other tag can exceed it.
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    for j in range(len(model.tags)):
        z = np.zeros(len(model.tags))
        z[j] = 4.0
        X = (model.mean + z * model.scale)[None, :]
        got = rbc.tag_rbc(model, M, X)[0]
        phi = rbc.combined_index(model, M, X)[0]
        assert got[j] == pytest.approx(phi, rel=1e-10)
        assert np.all(got <= got[j] * (1 + 1e-12))


def test_tag_rbc_matches_the_rebuild_definition():
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model, n=10)
    got = rbc.tag_rbc(model, M, X)
    for s, z in enumerate(standardised(model, X)):
        for i in range(len(model.tags)):
            assert got[s, i] == pytest.approx(rebuild_drop(M, z, [i]), rel=1e-8, abs=1e-12)


GROUPS = ((0, 1), (2,), (3, 4, 5))


def test_group_rbc_matches_the_rebuild_definition():
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model, n=10)
    got = rbc.group_rbc(model, M, X, GROUPS)
    assert got.shape == (10, 3) and got.dtype == np.float64
    for s, z in enumerate(standardised(model, X)):
        for j, g in enumerate(GROUPS):
            assert got[s, j] == pytest.approx(rebuild_drop(M, z, g), rel=1e-8, abs=1e-12)


def test_rbc_is_between_zero_and_phi():
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model)
    phi = rbc.combined_index(model, M, X)[:, None]
    for got in (rbc.tag_rbc(model, M, X), rbc.group_rbc(model, M, X, GROUPS)):
        assert np.all(got >= -1e-12) and np.all(got <= phi * (1 + 1e-12))


def test_one_tag_group_equals_tag_rbc():
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model)
    singles = tuple((i,) for i in range(len(model.tags)))
    assert rbc.group_rbc(model, M, X, singles) == pytest.approx(rbc.tag_rbc(model, M, X), rel=1e-12)


def test_group_rbc_at_least_every_members_rbc():
    # Rebuilding a set of tags can remove at least as much as rebuilding any one of them.
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model)
    tag = rbc.tag_rbc(model, M, X)
    grp = rbc.group_rbc(model, M, X, GROUPS)
    for j, g in enumerate(GROUPS):
        assert np.all(grp[:, j][:, None] >= tag[:, list(g)] * (1 - 1e-10) - 1e-12)


def test_all_tags_group_removes_the_whole_index():
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model)
    everything = (tuple(range(len(model.tags))),)
    assert rbc.group_rbc(model, M, X, everything)[:, 0] == pytest.approx(
        rbc.combined_index(model, M, X), rel=1e-10)


def test_fault_inside_a_group_is_fully_removed_by_that_group():
    # z = Ξ f for group (3, 4, 5): rebuilding that group removes all of phi.
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    z = np.zeros(6)
    z[[3, 4, 5]] = [2.0, -3.0, 1.5]
    X = (model.mean + z * model.scale)[None, :]
    got = rbc.group_rbc(model, M, X, GROUPS)[0]
    assert got[2] == pytest.approx(rbc.combined_index(model, M, X)[0], rel=1e-10)
    assert got.argmax() == 2


# --- scoring conventions ------------------------------------------------------------------

def test_float32_input_computes_in_float64():
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X32 = samples(model).astype(np.float32)
    for f in (lambda X: rbc.tag_rbc(model, M, X), lambda X: rbc.group_rbc(model, M, X, GROUPS),
              lambda X: rbc.combined_index(model, M, X)):
        out = f(X32)
        assert out.dtype == np.float64
        assert np.array_equal(out, f(X32.astype(np.float64)))


def test_scoring_is_row_by_row():
    # A row's RBC doesn't depend on the other rows (BLAS order can move the last bits).
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model)
    whole_t, whole_g = rbc.tag_rbc(model, M, X), rbc.group_rbc(model, M, X, GROUPS)
    for i in (0, 17, len(X) - 1):
        assert rbc.tag_rbc(model, M, X[i:i + 1])[0] == pytest.approx(whole_t[i], rel=1e-12)
        assert rbc.group_rbc(model, M, X[i:i + 1], GROUPS)[0] == pytest.approx(whole_g[i], rel=1e-12)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_input_refused(bad):
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model)
    X[3, 2] = bad
    for f in (rbc.combined_index, rbc.tag_rbc):
        with pytest.raises(ValueError):
            f(model, M, X)
    with pytest.raises(ValueError):
        rbc.group_rbc(model, M, X, GROUPS)


def test_wrong_column_count_or_matrix_shape_refused():
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    X = samples(model)
    for f in (rbc.combined_index, rbc.tag_rbc):
        with pytest.raises(ValueError):
            f(model, M, X[:, :5])
        with pytest.raises(ValueError):
            f(model, M[:5, :5], X)
    with pytest.raises(ValueError):
        rbc.group_rbc(model, M, X[:, :5], GROUPS)


@pytest.mark.parametrize("groups", [((),), ((0, 6),), ((-1,),), ((1, 1),), ((0,), ())])
def test_bad_groups_refused(groups):
    model = random_model()
    M = rbc.index_matrix(model, T2_LIM, SPE_LIM)
    with pytest.raises(ValueError):
        rbc.group_rbc(model, M, samples(model), groups)


# --- rank_at --------------------------------------------------------------------------------

RATIOS = np.array([[0.1, 0.2, 0.3],     # sample 1
                   [0.5, 2.0, 1.0],     # sample 2
                   [0.9, 1.0, 1.1],     # sample 3
                   [1.3, 0.6, 1.1],     # sample 4
                   [9.0, 9.0, 9.0]])    # sample 5


def test_rank_at_triggering_window():
    # t = 4, n = 3: samples 2..4. Means: (0.5+0.9+1.3)/3 = 0.9, (2+1+0.6)/3 = 1.2,
    # (1+1.1+1.1)/3 = 1.0666... Order: column 1, column 2, column 0.
    means, order = rbc.rank_at(RATIOS, 4, 3)
    assert means == pytest.approx([0.9, 1.2, 3.2 / 3], rel=1e-12)
    assert list(order) == [1, 2, 0]


def test_rank_at_one_sample_and_ties_in_column_order():
    means, order = rbc.rank_at(RATIOS, 5, 1)
    assert means == pytest.approx([9.0, 9.0, 9.0]) and list(order) == [0, 1, 2]


def test_rank_at_reads_nothing_after_t():
    later = RATIOS.copy()
    later[4] = np.nan                                 # sample 5 is after t = 4
    assert rbc.rank_at(later, 4, 3)[0] == pytest.approx(rbc.rank_at(RATIOS, 4, 3)[0], rel=1e-15)
    extended = np.vstack([RATIOS[:4], [[100.0, 0.0, 0.0]]])
    assert list(rbc.rank_at(extended, 4, 3)[1]) == [1, 2, 0]


@pytest.mark.parametrize("t, n", [(4, 0), (2, 3), (6, 1), (0, 1)])
def test_rank_at_refuses_windows_outside_the_run(t, n):
    with pytest.raises(ValueError):
        rbc.rank_at(RATIOS, t, n)


def test_rank_at_refuses_non_finite_window():
    bad = RATIOS.copy()
    bad[2, 1] = np.nan                                # sample 3, inside samples 2..4
    with pytest.raises(ValueError):
        rbc.rank_at(bad, 4, 3)
