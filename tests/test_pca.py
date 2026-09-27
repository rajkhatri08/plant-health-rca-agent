"""Hand-built cases for app/detector/pca.py (PROTOCOL, Detection: PCA components).

Expected values are worked out in comments. The 4-point data set below has sample
correlation exactly 0.9, which is the 2-tag example from session 4.
"""

import numpy as np
import pytest

from app.detector import pca
from app.detector.pca import PCAModel

A, B = np.sqrt(19.0), 1.0
# Points (a, a), (-a, -a), (b, -b), (-b, b): mean (0, 0). Each column's variance
# (ddof=1) = (19 + 19 + 1 + 1) / 3 = 40/3. Covariance = (19 + 19 - 1 - 1) / 3 = 12.
# Correlation = 12 / (40/3) = 0.9. Correlation eigenvalues: 1.9 along (1, 1)/√2 and
# 0.1 along (1, -1)/√2 (sign rule: tie, so the first entry is positive).
FOUR = np.array([[A, A], [-A, -A], [B, -B], [-B, B]])
TWO_TAGS = ("RX-TI-204", "RX-PI-202")
SCALE = np.sqrt(40 / 3)
R2 = 1 / np.sqrt(2)


def random_data(n=300, m=5, seed=0):
    rng = np.random.default_rng(seed)
    mix = rng.normal(size=(m, m))
    return rng.normal(size=(n, m)) @ mix + rng.normal(size=m) * 10


def tags(m):
    return tuple(f"TG-{i:03d}" for i in range(m))


# --- hand-checked values -------------------------------------------------------------

def test_known_model_values():
    # One kept direction e1 with λ1 = 2; x = (1, 1) is already standardised.
    # t = 1, T² = 1² / 2 = 0.5; residual (0, 1), SPE = 1.
    model = PCAModel(tags=("A", "B"), mean=np.zeros(2), scale=np.ones(2),
                     loadings=np.array([[1.0], [0.0]]), eigenvalues=np.array([2.0]),
                     all_eigenvalues=np.array([2.0, 0.5]))
    t2, spe = pca.scores(model, np.array([[1.0, 1.0]]))
    assert t2 == pytest.approx([0.5]) and spe == pytest.approx([1.0])


def test_fit_on_correlation_09_example():
    model = pca.fit(FOUR, TWO_TAGS, k=1)
    assert model.tags == TWO_TAGS and model.k == 1
    assert model.mean == pytest.approx([0.0, 0.0], abs=1e-12)
    assert model.scale == pytest.approx([SCALE, SCALE])
    assert model.all_eigenvalues == pytest.approx([1.9, 0.1])
    assert model.eigenvalues == pytest.approx([1.9])
    assert model.loadings[:, 0] == pytest.approx([R2, R2])


@pytest.mark.parametrize("z, t2, spe", [
    ((1, 1), 2 / 1.9, 0.0),   # t = 2/√2; T² = 2/1.9 ≈ 1.05; on the model line, SPE 0
    ((1, -1), 0.0, 2.0),      # t = 0; residual (1, -1), SPE = 2 (20x its normal 0.1)
])
def test_worked_example_scores(z, t2, spe):
    model = pca.fit(FOUR, TWO_TAGS, k=1)
    x = np.array([z], dtype=float) * SCALE  # raw values that standardise to z
    got_t2, got_spe = pca.scores(model, x)
    assert got_t2 == pytest.approx([t2]) and got_spe == pytest.approx([spe], abs=1e-12)


def test_cumulative_explained_example():
    assert pca.cumulative_explained(pca.fit(FOUR, TWO_TAGS, k=1)) == pytest.approx(0.95)  # 1.9 / 2


def test_all_components_kept_gives_mahalanobis():
    # With every component kept, SPE = 0 and T² = zᵀ R⁻¹ z (R = correlation matrix).
    X = random_data()
    model = pca.fit(X, tags(5), k=5)
    z = (X - X.mean(axis=0)) / X.std(axis=0, ddof=1)
    expected = np.einsum("ij,jk,ik->i", z, np.linalg.inv(np.corrcoef(X, rowvar=False)), z)
    t2, spe = pca.scores(model, X)
    assert t2 == pytest.approx(expected, rel=1e-8)
    assert spe == pytest.approx(np.zeros(len(X)), abs=1e-9)


# --- structure of the fitted model ---------------------------------------------------

def test_model_structure():
    X = random_data()
    model = pca.fit(X, tags(5), k=3)
    P = model.loadings
    assert P.shape == (5, 3) and model.eigenvalues.shape == (3,)
    assert P.T @ P == pytest.approx(np.eye(3), abs=1e-10)               # orthonormal
    assert np.all(np.diff(model.all_eigenvalues) <= 0)                   # descending
    assert model.all_eigenvalues.sum() == pytest.approx(5.0)             # correlation matrix
    assert model.eigenvalues == pytest.approx(model.all_eigenvalues[:3])
    assert model.mean == pytest.approx(X.mean(axis=0))
    assert model.scale == pytest.approx(X.std(axis=0, ddof=1))


def test_sign_rule_makes_loadings_reproducible():
    X = random_data()
    model = pca.fit(X, tags(5), k=3)
    for j in range(3):
        col = model.loadings[:, j]
        assert col[np.argmax(np.abs(col))] > 0
    perm = np.random.default_rng(1).permutation(len(X))
    assert pca.fit(X[perm], tags(5), k=3).loadings == pytest.approx(model.loadings, abs=1e-10)


# --- no look-ahead -------------------------------------------------------------------

def test_scoring_uses_fit_statistics_not_the_batch():
    # A per-batch normalisation would score X + 10 exactly like X. The model must not.
    X = random_data()
    model = pca.fit(X, tags(5), k=2)
    t2, spe = pca.scores(model, X)
    t2_shift, spe_shift = pca.scores(model, X + 10.0)
    assert not np.allclose(t2, t2_shift) and not np.allclose(spe, spe_shift)
    # The fit mean itself scores exactly zero on both statistics.
    t2_mean, spe_mean = pca.scores(model, model.mean[None, :])
    assert t2_mean == pytest.approx([0.0], abs=1e-12) and spe_mean == pytest.approx([0.0], abs=1e-12)


def test_scoring_is_row_by_row():
    X = random_data()
    model = pca.fit(X, tags(5), k=2)
    t2, spe = pca.scores(model, X)
    for i in (0, 17, 299):
        one_t2, one_spe = pca.scores(model, X[i:i + 1])
        assert one_t2[0] == pytest.approx(t2[i]) and one_spe[0] == pytest.approx(spe[i])


# --- types ---------------------------------------------------------------------------

def test_float32_input_computes_in_float64():
    X = random_data()
    m64 = pca.fit(X, tags(5), k=2)
    m32 = pca.fit(X.astype(np.float32), tags(5), k=2)
    for arr in (m32.mean, m32.scale, m32.loadings, m32.eigenvalues, m32.all_eigenvalues):
        assert arr.dtype == np.float64
    t2, spe = pca.scores(m32, X.astype(np.float32))
    assert t2.dtype == np.float64 and spe.dtype == np.float64
    assert m32.eigenvalues == pytest.approx(m64.eigenvalues, rel=1e-4)


# --- guards --------------------------------------------------------------------------

def test_zero_variance_tag_is_named():
    X = random_data(m=3)
    X[:, 1] = 7.0
    names = ("RX-TI-204", "SP-LI-402", "CD-TI-301")
    with pytest.raises(ValueError, match="SP-LI-402"):
        pca.standardisation(X, names)
    with pytest.raises(ValueError, match="SP-LI-402"):
        pca.fit(X, names, k=1)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_input_refused(bad):
    X = random_data()
    X[3, 2] = bad
    with pytest.raises(ValueError):
        pca.fit(X, tags(5), k=2)


def test_tag_count_must_match_columns():
    with pytest.raises(ValueError):
        pca.fit(random_data(), tags(4), k=2)


@pytest.mark.parametrize("k", [0, 6, -1])
def test_k_out_of_range_refused(k):
    with pytest.raises(ValueError):
        pca.fit(random_data(), tags(5), k=k)


def test_scores_refuse_wrong_column_count():
    model = pca.fit(random_data(), tags(5), k=2)
    with pytest.raises(ValueError):
        pca.scores(model, random_data(m=4))


# --- parallel analysis ---------------------------------------------------------------

def factor_data(n_factors, n=4000, per_factor=2, noise=0.3, seed=0):
    # Each factor drives `per_factor` tags plus small noise. With noise 0.3 each pair's
    # correlation eigenvalue is about 1.9 and the rest are about 0.08, far from the
    # shuffled eigenvalues (all close to 1). So parallel analysis should keep n_factors.
    rng = np.random.default_rng(seed)
    f = rng.normal(size=(n, n_factors))
    cols = [f[:, i] + noise * rng.normal(size=n) for i in range(n_factors) for _ in range(per_factor)]
    return np.column_stack(cols)


@pytest.mark.parametrize("n_factors", [1, 2, 3])
def test_parallel_analysis_finds_the_factors(n_factors):
    X = factor_data(n_factors)
    assert pca.parallel_analysis(X, tags(X.shape[1]), np.random.default_rng(20260927)) == n_factors


def test_parallel_analysis_one_factor_many_tags():
    # 4 tags on one factor: eigenvalues about 3.7, 0.08, 0.08, 0.08 -> k = 1.
    X = factor_data(1, per_factor=4)
    assert pca.parallel_analysis(X, tags(4), np.random.default_rng(20260927)) == 1


def test_parallel_analysis_ignores_units():
    # It works on the correlation matrix, so rescaling a tag changes nothing.
    X = factor_data(2)
    Y = X.copy()
    Y[:, 0] *= 1000.0
    k_x = pca.parallel_analysis(X, tags(4), np.random.default_rng(5))
    k_y = pca.parallel_analysis(Y, tags(4), np.random.default_rng(5))
    assert k_x == k_y == 2


def test_parallel_analysis_is_seeded():
    X = random_data(n=500, m=6)
    a = pca.parallel_analysis(X, tags(6), np.random.default_rng(11))
    b = pca.parallel_analysis(X, tags(6), np.random.default_rng(11))
    assert a == b


def test_parallel_analysis_names_zero_variance_tag():
    X = factor_data(2)
    X[:, 3] = 1.0
    with pytest.raises(ValueError, match="TG-003"):
        pca.parallel_analysis(X, tags(4), np.random.default_rng(0))


# --- save and load (no pickles) ------------------------------------------------------

def test_save_load_round_trip(tmp_path):
    model = pca.fit(random_data(), tags(5), k=2)
    path = tmp_path / "pca.npz"
    pca.save(model, path)
    with np.load(path, allow_pickle=False) as f:
        assert all(f[key].dtype != object for key in f.files)
    back = pca.load(path)
    assert back.tags == model.tags and back.k == model.k
    for name in ("mean", "scale", "loadings", "eigenvalues", "all_eigenvalues"):
        assert np.array_equal(getattr(back, name), getattr(model, name))

# --- session 4 review decisions (ValueError only) ------------------------------------

# (1) Scoring refuses NaN or inf, so a gap can never read as normal (decision 51).

@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_scores_refuse_non_finite(bad):
    model = pca.fit(random_data(), tags(5), k=2)
    X = random_data(n=4)
    X[2, 1] = bad
    with pytest.raises(ValueError):
        pca.scores(model, X)


# (2) save() refuses a path that doesn't end in .npz, and writes nothing.

@pytest.mark.parametrize("name", ["pca", "pca.txt", "pca.npz.bak"])
def test_save_refuses_non_npz_path(tmp_path, name):
    model = pca.fit(random_data(), tags(5), k=2)
    with pytest.raises(ValueError):
        pca.save(model, tmp_path / name)
    assert list(tmp_path.iterdir()) == []
