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


def _standardised(model, M, X):
    """(Z, M) as float64 after the checks every scoring function shares: X is samples x m
    in model.tags order, M is m x m, and X holds no NaN or inf. Z = (X - mean) / scale,
    row by row, exactly as in pca.scores."""
    m = len(model.tags)
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or X.shape[1] != m:
        raise ValueError(f"X must be a 2-D array of samples x {m} tags, got shape {X.shape}")
    M = np.asarray(M, dtype=np.float64)
    if M.shape != (m, m):
        raise ValueError(f"M must be {m} x {m}, got {M.shape}")
    if not np.isfinite(X).all():
        raise ValueError("X holds NaN or inf; a gap must never read as normal")
    return (X - model.mean) / model.scale, M


def index_matrix(model, t2_lim, spe_lim) -> np.ndarray:
    """M for the combined index, shape (m, m), float64, with m = len(model.tags).
    Raises ValueError if either limit isn't a finite number > 0."""
    for name, v in (("T²lim", t2_lim), ("SPElim", spe_lim)):
        if not (np.isfinite(v) and v > 0):
            raise ValueError(f"{name} must be a finite number > 0, got {v}")
    P = np.asarray(model.loadings, dtype=np.float64)          # m x k, the kept loadings
    lam = np.asarray(model.eigenvalues, dtype=np.float64)     # k kept eigenvalues
    t2_part = (P / lam) @ P.T                                 # P Λ⁻¹ Pᵀ: each column over its λ
    spe_part = np.eye(len(P)) - P @ P.T                       # I − P Pᵀ: the residual space
    M = t2_part / t2_lim + spe_part / spe_lim
    return (M + M.T) / 2                                      # exactly symmetric


def combined_index(model, M, X) -> np.ndarray:
    """phi = zᵀMz per sample, shape (samples,), float64. Equals T²/T²lim + SPE/SPElim from
    pca.scores when M = index_matrix(model, T²lim, SPElim). Raises ValueError on a column
    count that doesn't match the model, an M of the wrong shape, and NaN or inf."""
    Z, M = _standardised(model, M, X)
    return np.einsum("ij,ij->i", Z @ M, Z)                    # zᵀMz, row by row


def tag_rbc(model, M, X) -> np.ndarray:
    """RBC of every tag, shape (samples, m), float64: column i is (Mz)_i² / M_ii.
    Same refusals as combined_index."""
    Z, M = _standardised(model, M, X)
    MZ = Z @ M                                                # row s is (M z_s)ᵀ (M is symmetric)
    return MZ ** 2 / np.diag(M)                               # (Mz)_i² / M_ii for every tag i


def group_rbc(model, M, X, groups) -> np.ndarray:
    """Joint RBC of each group, shape (samples, len(groups)), float64, in the given group
    order. groups is a sequence of column-index tuples (groups.load gives them by name).
    Column j is vᵀ A⁻¹ v with v = (Mz)[g] and A = M[g][:, g] for group g = groups[j].
    Raises ValueError on an empty group, a column index outside 0..m-1 or repeated within
    a group, plus combined_index's refusals. Groups may overlap; the tests don't rely on it."""
    Z, M = _standardised(model, M, X)
    m = len(model.tags)
    cols = []
    for g in groups:
        g = tuple(g)
        if not g:
            raise ValueError("a group is empty")
        if len(set(g)) != len(g):
            raise ValueError(f"a column repeats within group {g}")
        if any(not 0 <= i < m for i in g):
            raise ValueError(f"group {g} has a column outside 0..{m - 1}")
        cols.append(list(g))
    MZ = Z @ M                                                # row s is (M z_s)ᵀ
    out = np.empty((len(Z), len(cols)))
    for j, g in enumerate(cols):
        A = M[np.ix_(g, g)]                                   # ΞᵀMΞ, the group's block of M
        V = MZ[:, g]                                          # ΞᵀMz for every row
        out[:, j] = np.einsum("ij,ij->i", V, np.linalg.solve(A, V.T).T)   # vᵀ A⁻¹ v per row
    return out


def rank_at(ratios, t, n) -> tuple[np.ndarray, np.ndarray]:
    """Attribution as of a notification at 1-based sample t (decision 65).
    ratios is a whole-run array, samples x columns (RBC / W per group, or per tag),
    index 0 = sample 1. Returns (means, order): means[j] is the mean of column j over
    samples t - n + 1 .. t; order lists the column indices from the highest mean to the
    lowest, ties kept in column order. Reads no sample after t.
    Raises ValueError if n < 1, t - n + 1 < 1, t > the number of samples, or the window
    holds NaN or inf."""
    R = np.asarray(ratios, dtype=np.float64)
    if R.ndim != 2:
        raise ValueError("ratios must be a 2-D array (samples x columns)")
    if n < 1:
        raise ValueError(f"the window needs at least one sample, got n = {n}")
    if t - n + 1 < 1 or t > len(R):
        raise ValueError(f"samples {t - n + 1}..{t} aren't all inside a run of {len(R)} samples")
    window = R[t - n:t]                                       # samples t-n+1 .. t (1-based)
    if not np.isfinite(window).all():
        raise ValueError("the window holds NaN or inf")
    means = window.mean(axis=0)
    order = np.argsort(-means, kind="stable")                 # highest first; ties keep column order
    return means, order
