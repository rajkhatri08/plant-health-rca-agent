"""Reconstruction-based contributions (decisions 9, 64, 65; eval/PROTOCOL.md, Detection).

Runtime code: pure numpy, plant tag names only, no imports from dataset/, eval/ or ingest/.

Conventions:
- X is samples x tags in model.tags order, any float dtype; all arithmetic is float64.
  Each row is standardised with the model's fit-pool mean and scale, z = (x - mean) / scale,
  exactly as in pca.scores. Scoring is row by row.
- The index is the combined index phi = T²/T²lim + SPE/SPElim = zᵀMz, with
      M = P Λ⁻¹ Pᵀ / T²lim + (I − P Pᵀ) / SPElim
  (P the kept loadings, Λ their eigenvalues). M is symmetric and positive definite.
- RBC for tag directions Ξ (columns of the identity) is the drop in phi when those tags are
  rebuilt from the others:
      RBC_Ξ = zᵀMΞ (ΞᵀMΞ)⁻¹ ΞᵀMz
  For one tag i this is (Mz)_i² / M_ii. For a group, Ξ holds all of the group's columns, so
  the group is rebuilt jointly.
- Whole-run arrays use index 0 = sample 1, the convention of alerting.py and metrics.py.
- NaN or inf input is refused, as in pca.scores: a NaN would compare as below any limit.
"""

import numpy as np


def index_matrix(model, t2_lim, spe_lim) -> np.ndarray:
    """M for the combined index, shape (m, m), float64, with m = len(model.tags).
    Raises ValueError if either limit isn't a finite number > 0."""
    raise NotImplementedError("Raj: week 4 session 2")


def combined_index(model, M, X) -> np.ndarray:
    """phi = zᵀMz per sample, shape (samples,), float64. Equals T²/T²lim + SPE/SPElim from
    pca.scores when M = index_matrix(model, T²lim, SPElim). Raises ValueError on a column
    count that doesn't match the model, an M of the wrong shape, and NaN or inf."""
    raise NotImplementedError("Raj: week 4 session 2")


def tag_rbc(model, M, X) -> np.ndarray:
    """RBC of every tag, shape (samples, m), float64: column i is (Mz)_i² / M_ii.
    Same refusals as combined_index."""
    raise NotImplementedError("Raj: week 4 session 2")


def group_rbc(model, M, X, groups) -> np.ndarray:
    """Joint RBC of each group, shape (samples, len(groups)), float64, in the given group
    order. groups is a sequence of column-index tuples (groups.load gives them by name).
    Column j is vᵀ A⁻¹ v with v = (Mz)[g] and A = M[g][:, g] for group g = groups[j].
    Raises ValueError on an empty group, a column index outside 0..m-1 or repeated within
    a group, plus combined_index's refusals. Groups may overlap; the tests don't rely on it."""
    raise NotImplementedError("Raj: week 4 session 2")


def rank_at(ratios, t, n) -> tuple[np.ndarray, np.ndarray]:
    """Attribution as of a notification at 1-based sample t (decision 65).
    ratios is a whole-run array, samples x columns (RBC / W per group, or per tag),
    index 0 = sample 1. Returns (means, order): means[j] is the mean of column j over
    samples t - n + 1 .. t; order lists the column indices from the highest mean to the
    lowest, ties kept in column order. Reads no sample after t.
    Raises ValueError if n < 1, t - n + 1 < 1, t > the number of samples, or the window
    holds NaN or inf."""
    raise NotImplementedError("Raj: week 4 session 2")
