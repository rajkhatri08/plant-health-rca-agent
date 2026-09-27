"""From T² and SPE to one plant alert track (decisions 52, 53, 54; PROTOCOL, Detection).

Runtime code: pure numpy, no imports from dataset/, eval/ or ingest/. Stubs for Raj.

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


def plant_ratio(t2, spe, t2_lim, spe_lim) -> np.ndarray:
    """max(T² / T²lim, SPE / SPElim) per sample, float64.

    Raises ValueError if t2 and spe aren't 1-D arrays of the same length, if either holds
    NaN or inf, or if a limit isn't a finite number > 0."""
    raise NotImplementedError


def persist(exceed, n) -> np.ndarray:
    """On-delay. Bool array: True at sample t when exceed is on at t and at each of the
    n - 1 samples before it. The window never reaches before sample 1, so the first n - 1
    samples are always False. n = 1 returns exceed unchanged (as bool).

    Raises ValueError if exceed holds anything other than 0/1 (or bool), or n < 1."""
    raise NotImplementedError


def group(held, gap, warmup) -> np.ndarray:
    """Off-delay (episode grouping). Bool array: False for the warm-up samples; at a
    scored sample t, True when held is on at any scored sample from t - gap to t.
    So the alert stays on for gap samples after held clears, and a re-alert within that
    time is the same episode. Held samples in the warm-up never count, so the grouping
    state starts at the first scored sample. gap = 0 returns held with the warm-up off.

    Raises ValueError if held holds anything other than 0/1 (or bool), gap < 0, or
    warmup < 0."""
    raise NotImplementedError


def alert_track(ratio, n, gap, warmup, lags=0) -> np.ndarray:
    """The plant alert track: group(persist(ratio > 1, n), gap, warmup), as 0/1 integers.

    The detector's memory must fit in the warm-up (decision 52): lags + n - 1 <= warmup,
    so at the first scored sample the whole window lies inside the run.

    Raises ValueError if that bound is broken, if n < 1, gap < 0, lags < 0 or
    warmup < 0, if ratio isn't 1-D, or if it holds NaN or inf."""
    raise NotImplementedError
