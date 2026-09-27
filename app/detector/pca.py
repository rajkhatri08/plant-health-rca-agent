"""Static PCA monitoring: fit, component count, T² and SPE (eval/PROTOCOL.md, Detection).

Runtime code: pure numpy, plant tag names only, no imports from dataset/, eval/ or ingest/.

Conventions:
- X is samples x tags (any float dtype). All arithmetic is float64 (decision 47).
- Standardisation uses the fit data's mean and standard deviation (ddof=1), stored in
  the model and reused on every later sample. Scored data never re-estimates them.
- Eigenvalues are those of the fit data's correlation matrix (the covariance of the
  standardised data, ddof=1), in descending order. They sum to the number of tags.
- Sign rule: in each loading column, the entry with the largest absolute value is
  positive; on a tie, the first such entry.
- T² = sum over kept components of t_i² / λ_i, where t = Pᵀ z.
- SPE = squared length of z - P t.
- Scoring is row by row: a sample's scores never depend on other samples.
- Saved as .npz with no object arrays (no pickles); loaded with allow_pickle=False.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PCAModel:
    tags: tuple               # plant tag names, the column order of X
    mean: np.ndarray          # (m,) fit-pool mean per tag
    scale: np.ndarray         # (m,) fit-pool standard deviation per tag (ddof=1)
    loadings: np.ndarray      # (m, k) kept directions, unit length, sign rule applied
    eigenvalues: np.ndarray   # (k,) kept eigenvalues, descending
    all_eigenvalues: np.ndarray  # (m,) every eigenvalue, descending

    @property
    def k(self):
        return self.loadings.shape[1]


def _checked(X, tags):
    """X as a float64 samples x tags array, refusing a wrong shape and NaN or inf."""
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or X.shape[1] != len(tags):
        raise ValueError(f"X must be samples x {len(tags)} tags, got shape {X.shape}")
    if not np.isfinite(X).all():
        raise ValueError("X contains NaN or inf")
    return X


def standardisation(X, tags) -> tuple[np.ndarray, np.ndarray]:
    """(mean, scale) per tag, float64, scale with ddof=1. Raises ValueError naming the
    tag if a tag has zero variance, and on NaN/inf or a column count that doesn't
    match tags."""
    X = _checked(X, tags)
    mean = X.mean(axis=0)
    scale = X.std(axis=0, ddof=1)
    for tag, s in zip(tags, scale):
        if not s > 0:
            raise ValueError(f"tag {tag} has zero variance in the fit data")
    return mean, scale


def _eigen(Z):
    """Eigenvalues (largest first) and unit eigenvectors of the correlation matrix of
    standardised data Z, with the sign rule applied to every eigenvector."""
    R = Z.T @ Z / (len(Z) - 1)                # covariance of standardised data = correlation matrix
    values, vectors = np.linalg.eigh(R)       # eigh is for symmetric matrices; ascending order
    order = np.argsort(values)[::-1]          # reorder: largest eigenvalue first
    values, vectors = values[order], vectors[:, order]
    for j in range(vectors.shape[1]):
        size = np.abs(vectors[:, j])
        i = np.flatnonzero(size >= size.max() - 1e-12)[0]   # largest entry; first one on a tie
        if vectors[i, j] < 0:
            vectors[:, j] = -vectors[:, j]    # flip so that entry is positive
    return values, vectors


def fit(X, tags, k) -> PCAModel:
    """Fit on X (the fit pool after warm-up) keeping k components. Raises ValueError
    if k isn't in 1..number of tags, plus everything standardisation raises."""
    tags = tuple(tags)
    if not 1 <= k <= len(tags):
        raise ValueError(f"k must be between 1 and {len(tags)}, got {k}")
    X = _checked(X, tags)
    mean, scale = standardisation(X, tags)
    values, vectors = _eigen((X - mean) / scale)
    return PCAModel(tags=tags, mean=mean, scale=scale,
                    loadings=vectors[:, :k].copy(), eigenvalues=values[:k].copy(),
                    all_eigenvalues=values)


def parallel_analysis(X, tags, rng, n_shuffles=20, percentile=95) -> int:
    """The number of leading components whose correlation-matrix eigenvalue exceeds the
    `percentile` of the eigenvalues at the same rank from n_shuffles copies of the
    standardised X, each column shuffled independently with rng. Counting stops at the
    first component that doesn't exceed it."""
    X = _checked(X, tags)
    mean, scale = standardisation(X, tags)
    Z = (X - mean) / scale
    real, _ = _eigen(Z)
    chance = np.empty((n_shuffles, Z.shape[1]))
    for s in range(n_shuffles):
        # Shuffling each column separately keeps every tag's spread but destroys the
        # links between tags, so these eigenvalues show what pure chance looks like.
        shuffled = np.column_stack([rng.permutation(Z[:, j]) for j in range(Z.shape[1])])
        chance[s], _ = _eigen(shuffled)
    threshold = np.percentile(chance, percentile, axis=0)    # one threshold per rank
    k = 0
    while k < len(real) and real[k] > threshold[k]:
        k += 1                                               # stop at the first failure
    return k


def cumulative_explained(model) -> float:
    """Share of total variance in the kept components: sum(eigenvalues) / sum(all_eigenvalues)."""
    return float(model.eigenvalues.sum() / model.all_eigenvalues.sum())


def scores(model, X) -> tuple[np.ndarray, np.ndarray]:
    """(T², SPE), each shape (samples,), float64. X columns are in model.tags order.
    Raises ValueError on a column count that doesn't match the model, and on NaN or inf:
    a NaN score would compare as below the limit and read as normal."""
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or X.shape[1] != len(model.tags):
        raise ValueError(f"X must be samples x {len(model.tags)} tags, got shape {X.shape}")
    if not np.isfinite(X).all():
        raise ValueError("X contains NaN or inf; handle gaps before scoring, because a NaN "
                         "score would compare as below the limit and read as normal")
    Z = (X - model.mean) / model.scale        # the fit pool's mean and spread, never the batch's
    T = Z @ model.loadings                    # t: each sample's position along the kept directions
    t2 = np.sum(T ** 2 / model.eigenvalues, axis=1)
    residual = Z - T @ model.loadings.T       # the part the kept directions can't explain
    spe = np.sum(residual ** 2, axis=1)
    return t2, spe


def save(model, path) -> None:
    """Write the model's arrays and tags to an .npz file (no object arrays). The path must
    end in .npz: np.savez would otherwise add it, and the caller's path would be wrong."""
    if not str(path).endswith(".npz"):
        raise ValueError(f"model path must end in .npz, got {path}")
    np.savez(path, tags=np.array(model.tags, dtype=str), mean=model.mean, scale=model.scale,
             loadings=model.loadings, eigenvalues=model.eigenvalues,
             all_eigenvalues=model.all_eigenvalues)


def load(path) -> PCAModel:
    """Read a model written by save, with allow_pickle=False."""
    with np.load(path, allow_pickle=False) as f:
        return PCAModel(tags=tuple(str(t) for t in f["tags"]), mean=f["mean"],
                        scale=f["scale"], loadings=f["loadings"],
                        eigenvalues=f["eigenvalues"], all_eigenvalues=f["all_eigenvalues"])