"""Dynamic PCA: lagged data and the lag-count rule (eval/PROTOCOL.md, Detection).

Runtime code: pure numpy, plant tag names only, no imports from dataset/, eval/ or ingest/.
The fit itself reuses app/detector/pca.py on the lagged matrix.

Conventions:
- L lags means the L past samples are appended to the current one; the current sample
  isn't a lag (decision 52). A lagged row for sample t is [x_t | x_{t-1} | ... | x_{t-L}],
  so the lag-0 block comes first and each block is in tag order.
- Past samples only: a row never uses a sample after t, and never crosses a run boundary.
- Lag rule (the new-relations rule; reference in docs/log.md, week 3 session 1), with
  L_max = 4. At each l, k(l) comes from pca.parallel_analysis on the l-lagged matrix and
  the relation count is r(l) = m(l+1) - k(l). A relation found first at lag i appears
  (l - i + 1) times in the l-lagged matrix, so the new relations at l are
      r_new(l) = r(l) - sum over i < l of (l - i + 1) * r_new(i).
  The search runs l = 0, 1, ... . At the first l* >= 1 with r_new(l*) <= 0, lag l* adds
  nothing, and L = l* - 1. r_new(0) is never a stop. If no stop comes by l = L_max,
  L = L_max and the choice is marked capped (Raj, week 3 session 7).
"""

from dataclasses import dataclass

import numpy as np

from app.detector import pca

L_MAX = 4


@dataclass(frozen=True)
class LagChoice:
    lags: int          # the chosen L
    k: tuple           # k(l) for every l evaluated, starting at l = 0
    r: tuple           # r(l) = m(l+1) - k(l), same l's
    r_new: tuple       # new relations at each evaluated l
    capped: bool       # True when no stop came by l = l_max, so L = l_max


def lagged(X, lags) -> np.ndarray:
    """Lagged rows for one run. X is samples x m. Returns (T - lags) x m(lags+1), float64:
    row i is sample t = i + lags (0-based), laid out [x_t | x_{t-1} | ... | x_{t-lags}].
    lags = 0 returns X as float64. Raises ValueError on lags < 0, X that isn't 2-D,
    T <= lags (no complete row), and NaN or inf."""
    if lags < 0:
        raise ValueError(f"lags can't be negative, got {lags}")
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2:
        raise ValueError("X must be a 2-D array (samples x tags)")
    T = len(X)
    if T <= lags:
        raise ValueError(f"{T} samples can't hold one complete row with {lags} lags")
    if not np.isfinite(X).all():
        raise ValueError("X holds NaN or inf")
    # Block j holds x_{t-j} for t = lags .. T-1 (0-based): rows lags-j .. T-1-j of X.
    return np.hstack([X[lags - j:T - j] for j in range(lags + 1)])


def lagged_tags(tags, lags) -> tuple:
    """Column names for lagged(X, lags): the lag-0 block keeps the plain names, then lag j
    uses f"{tag}@t-{j}", block by block in tag order. Raises ValueError on lags < 0."""
    if lags < 0:
        raise ValueError(f"lags can't be negative, got {lags}")
    tags = tuple(tags)
    return tags + tuple(f"{t}@t-{j}" for j in range(1, lags + 1) for t in tags)


def stack_lagged(runs, lags, warmup) -> np.ndarray:
    """Stack every run's lagged rows for samples warmup+1..T (1-based), in the given run
    order. Lag columns may read warm-up samples, so the rows are the same samples at
    every lags value and only the columns change. Rows never mix runs. Raises ValueError
    if lags > warmup, lags < 0 or warmup < 0, plus everything lagged raises."""
    if lags < 0 or warmup < 0:
        raise ValueError(f"lags and warm-up can't be negative, got {lags} and {warmup}")
    if lags > warmup:
        raise ValueError(f"{lags} lags would reach before sample 1: the warm-up is {warmup} "
                         "(decision 52)")
    blocks = []
    for X in runs:
        if len(X) <= warmup:
            raise ValueError(f"a run of {len(X)} samples ends inside the {warmup}-sample warm-up")
        rows = lagged(X, lags)                 # row i is sample i + lags (0-based)
        blocks.append(rows[warmup - lags:])    # keep samples warmup+1 .. T (1-based)
    return np.vstack(blocks)


def scores(model, X, lags) -> tuple[np.ndarray, np.ndarray]:
    """(T², SPE) for one whole run, each shape (T,), float64, index 0 = sample 1 (the
    convention of alerting.py and eval/metrics.py). X is samples x m, the model's base tags
    in order; the model was fitted on lagged_tags(base, lags), so it has m(lags+1) tags.
    Entries lags.. are pca.scores(model, lagged(X, lags)); the first `lags` entries have no
    complete row and are 0.0. They're never read: lags <= warm-up, calibration reads only
    samples after the warm-up, and decision 52 (lags + n - 1 <= warm-up) keeps every
    persistence window after them. lags = 0 is exactly pca.scores(model, X).
    Raises ValueError if len(model.tags) != m(lags+1), plus everything lagged raises."""
    raise NotImplementedError("Raj: week 3 session 8")


def relation_count(runs, tags, lags, warmup, rng, n_shuffles=20, percentile=95) -> tuple[int, int]:
    """(k, r) at this lag count: k = pca.parallel_analysis on stack_lagged(runs, lags,
    warmup) with lagged_tags, rng, n_shuffles and percentile; r = m(lags+1) - k."""
    X = stack_lagged(runs, lags, warmup)
    k = pca.parallel_analysis(X, lagged_tags(tags, lags), rng, n_shuffles, percentile)
    return k, len(tags) * (lags + 1) - k


def new_relations(r) -> tuple:
    """r_new(l) = r(l) - sum over i < l of (l - i + 1) * r_new(i), for every l in r.
    Values can be negative when a count is off by one. Returns a tuple of ints."""
    r_new = []
    for l, r_l in enumerate(r):
        # relations first seen at an earlier lag i show up (l - i + 1) times here
        earlier = sum((l - i + 1) * r_new[i] for i in range(l))
        r_new.append(int(r_l) - earlier)
    return tuple(r_new)


def choose_lags(count, l_max=L_MAX) -> LagChoice:
    """Apply the lag rule. count(l) -> (k, r) is called for l = 0, 1, ... in order, and
    never past the stop or past l_max. Stop at the first l* >= 1 with r_new(l*) <= 0:
    L = l* - 1. No stop by l_max: L = l_max, capped. The evidence tuples cover every l
    evaluated. Raises ValueError if l_max < 1."""
    if l_max < 1:
        raise ValueError(f"l_max must be at least 1, got {l_max}")
    ks, rs = [], []
    for l in range(l_max + 1):
        k, r = count(l)
        ks.append(int(k))
        rs.append(int(r))
        r_new = new_relations(rs)
        if l >= 1 and r_new[l] <= 0:           # lag l adds nothing new: stop
            return LagChoice(l - 1, tuple(ks), tuple(rs), r_new, capped=False)
    return LagChoice(l_max, tuple(ks), tuple(rs), new_relations(rs), capped=True)
