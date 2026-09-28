"""From T² and SPE to one plant alert track (decisions 52, 53, 54; PROTOCOL, Detection).

Runtime code: pure numpy, no imports from dataset/, eval/ or ingest/.

Conventions (the same as eval/metrics.py):
- Every array covers one whole run, index 0 = sample 1, warm-up samples included. The
  statistics are computed during the warm-up; nothing is scored there.
- `warmup` is the number of unscored samples (9 in the protocol). Scoring starts at
  sample warmup + 1.
- Everything is causal: the value at sample t depends only on samples 1..t, so cutting
  the input at t never changes the output up to t.
- A track is a 0/1 integer array, which eval/metrics.notifications accepts.

Pipeline (alert_track):
    r = plant_ratio(T², SPE, T²lim, SPElim)      max of the two ratios (decision 53)
    exceed = r > 1                               strictly above: r == 1 is not an exceedance
    held = persist(exceed, n)                    on-delay: n consecutive exceedances
    alert = group(held, gap, warmup)             off-delay: holds G samples after clearing
"""

import numpy as np


def _binary(a, name) -> np.ndarray:
    """a as a 1-D bool array, refusing anything other than 0/1 (NaN, 2, 0.5 ...)."""
    a = np.asarray(a)
    if a.ndim != 1:
        raise ValueError(f"{name} must be a 1-D array")
    if not np.isin(a, (0, 1)).all():
        raise ValueError(f"{name} must hold only 0/1 values")
    return a.astype(bool)


def plant_ratio(t2, spe, t2_lim, spe_lim) -> np.ndarray:
    """max(T² / T²lim, SPE / SPElim) per sample, float64.

    Raises ValueError if t2 and spe aren't 1-D arrays of the same length, if either holds
    NaN or inf, or if a limit isn't a finite number > 0."""
    t2 = np.asarray(t2, dtype=np.float64)
    spe = np.asarray(spe, dtype=np.float64)
    if t2.ndim != 1 or spe.ndim != 1 or len(t2) != len(spe):
        raise ValueError("T² and SPE must be 1-D arrays of the same length")
    if not (np.isfinite(t2).all() and np.isfinite(spe).all()):
        raise ValueError("T² or SPE holds NaN or inf; a gap must never read as normal")
    for name, lim in (("T² limit", t2_lim), ("SPE limit", spe_lim)):
        if not (np.isfinite(lim) and lim > 0):
            raise ValueError(f"the {name} must be a finite number > 0, got {lim}")
    return np.maximum(t2 / t2_lim, spe / spe_lim)     # whichever statistic is further out


def persist(exceed, n) -> np.ndarray:
    """On-delay. Bool array: True at sample t when exceed is on at t and at each of the
    n - 1 samples before it. The window never reaches before sample 1, so the first n - 1
    samples are always False. n = 1 returns exceed unchanged (as bool).

    Raises ValueError if exceed holds anything other than 0/1 (or bool), or n < 1."""
    if n < 1:
        raise ValueError(f"the persistence window n must be at least 1, got {n}")
    e = _binary(exceed, "exceed")
    counts = np.concatenate(([0], np.cumsum(e)))      # counts[i] = exceedances in samples 1..i
    held = np.zeros(len(e), dtype=bool)
    # Exceedances in the n samples ending at each t (t = n .. end): the alert holds
    # only when all n of them exceeded.
    held[n - 1:] = (counts[n:] - counts[:-n]) == n
    return held


def group(held, gap, warmup) -> np.ndarray:
    """Off-delay (episode grouping). Bool array: False for the warm-up samples; at a
    scored sample t, True when held is on at any scored sample from t - gap to t.
    So the alert stays on for gap samples after held clears, and a re-alert within that
    time is the same episode. Held samples in the warm-up never count, so the grouping
    state starts at the first scored sample. gap = 0 returns held with the warm-up off.

    Raises ValueError if held holds anything other than 0/1 (or bool), gap < 0, or
    warmup < 0."""
    if gap < 0 or warmup < 0:
        raise ValueError(f"gap and warm-up can't be negative, got gap {gap}, warm-up {warmup}")
    h = _binary(held, "held").copy()
    h[:warmup] = False                                # warm-up samples never count
    counts = np.concatenate(([0], np.cumsum(h)))
    t = np.arange(len(h))                             # 0-based index of each sample
    start = np.maximum(t - gap, 0)                    # window t - gap .. t, clipped at sample 1
    alert = (counts[t + 1] - counts[start]) > 0       # held anywhere in the window?
    alert[:warmup] = False
    return alert


def alert_track(ratio, n, gap, warmup, lags=0) -> np.ndarray:
    """The plant alert track: group(persist(ratio > 1, n), gap, warmup), as 0/1 integers.

    The detector's memory must fit in the warm-up (decision 52): lags + n - 1 <= warmup,
    so at the first scored sample the whole window lies inside the run.

    Raises ValueError if that bound is broken, if n < 1, gap < 0, lags < 0 or
    warmup < 0, if ratio isn't 1-D, or if it holds NaN or inf."""
    if n < 1 or gap < 0 or lags < 0 or warmup < 0:
        raise ValueError(f"need n >= 1 and gap, lags, warm-up >= 0; got n {n}, gap {gap}, "
                         f"lags {lags}, warm-up {warmup}")
    if lags + n - 1 > warmup:
        raise ValueError(f"memory bound broken: lags + n - 1 = {lags + n - 1} is more than "
                         f"the warm-up {warmup} (decision 52)")
    r = np.asarray(ratio, dtype=np.float64)
    if r.ndim != 1:
        raise ValueError("ratio must be a 1-D array")
    if not np.isfinite(r).all():
        raise ValueError("ratio holds NaN or inf; a gap must never read as normal")
    return group(persist(r > 1, n), gap, warmup).astype(int)
