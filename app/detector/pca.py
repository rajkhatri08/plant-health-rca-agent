"""Static PCA monitoring: fit, component count, T² and SPE (eval/PROTOCOL.md, Detection).

Stubs only: Raj implements these against tests/test_pca.py.

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


def standardisation(X, tags) -> tuple[np.ndarray, np.ndarray]:
    """(mean, scale) per tag, float64, scale with ddof=1. Raises ValueError naming the
    tag if a tag has zero variance, and on NaN/inf or a column count that doesn't
    match tags."""
    raise NotImplementedError


def fit(X, tags, k) -> PCAModel:
    """Fit on X (the fit pool after warm-up) keeping k components. Raises ValueError
    if k isn't in 1..number of tags, plus everything standardisation raises."""
    raise NotImplementedError


def parallel_analysis(X, tags, rng, n_shuffles=20, percentile=95) -> int:
    """The number of leading components whose correlation-matrix eigenvalue exceeds the
    `percentile` of the eigenvalues at the same rank from n_shuffles copies of the
    standardised X, each column shuffled independently with rng. Counting stops at the
    first component that doesn't exceed it."""
    raise NotImplementedError


def cumulative_explained(model) -> float:
    """Share of total variance in the kept components: sum(eigenvalues) / sum(all_eigenvalues)."""
    raise NotImplementedError


def scores(model, X) -> tuple[np.ndarray, np.ndarray]:
    """(T², SPE), each shape (samples,), float64. X columns are in model.tags order.
    Raises ValueError on a column count that doesn't match the model."""
    raise NotImplementedError


def save(model, path) -> None:
    """Write the model's arrays and tags to an .npz file (no object arrays)."""
    raise NotImplementedError


def load(path) -> PCAModel:
    """Read a model written by save, with allow_pickle=False."""
    raise NotImplementedError
