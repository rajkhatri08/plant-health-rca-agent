"""The conventional-alarm baseline (decision 58; PROTOCOL, Alarm comparison).

Eval only: a comparator, never imported by app/. Stubs for Raj; the constants are fixed
by decision 58.

Conventions (the same as app/detector/alerting.py):
- Arrays cover one whole run, index 0 = sample 1, warm-up samples included. Values are
  samples x columns, one column per tag (or per valve), in a fixed order.
- Everything is causal: the output at sample t depends only on samples 1..t.
- Analyzer columns are stored with the last value held between updates, so no update
  logic is needed here: a held value simply stays on the same side of a limit.

Pipeline for one run at limit percentile q:
    lo, hi = tag_limits(calibration runs, q, warmup)      per tag, same q for every tag
    band = DEADBAND_SIGMA[type] * tag_spread(calibration runs, warmup)
    high, low = hysteresis(x, lo, hi, band)               latched alarm conditions
    valve = at_limit(valves)                              fixed positions, no deadband
    points = [high | low columns..., valve columns...]    one column per alarm point
    alert = plant_track(points, n per point, gap, warmup)
        each point's on-delay (n consecutive samples), then OR over points, then the
        off-delay G (episode grouping) with the warm-up off.
"""

import numpy as np

# Deadband as a multiple of the tag's calibration-pool spread, by signal type
# (decision 58). A type missing here has no agreed deadband yet.
DEADBAND_SIGMA = {"temperature": 0.25, "pressure": 0.25, "flow": 0.5, "level": 0.5,
                  "composition": 0.5}
VALVE_LOW = 2.0                      # % open: at or below is "at limit"
VALVE_HIGH = 98.0                    # % open: at or above is "at limit"
ANALYZER_ON_DELAY = 1                # samples of the held series: the first reading past the limit


def tag_limits(runs, q, warmup) -> tuple[np.ndarray, np.ndarray]:
    """(lo, hi) per column: the (100 - q)/2 and (100 + q)/2 percentiles of the pooled
    scored samples (after warm-up) of every run, numpy's default linear percentile.
    So each tag has the same two-sided per-sample false rate, 100 - q percent.

    runs is a list of 2-D arrays (samples x columns), all with the same columns.

    Raises ValueError if runs is empty, the column counts differ, a run isn't 2-D, the
    warm-up doesn't end inside every run, q isn't in (0, 100), or a value is NaN or inf."""
    raise NotImplementedError


def tag_spread(runs, warmup) -> np.ndarray:
    """σ per column: the standard deviation (ddof = 0) of the pooled scored samples of
    every run. The deadband is DEADBAND_SIGMA[type] times this.

    Raises ValueError on the same inputs as tag_limits (except q)."""
    raise NotImplementedError


def hysteresis(x, lo, hi, band) -> tuple[np.ndarray, np.ndarray]:
    """(high, low) latched alarm conditions, bool arrays shaped like x (samples x columns).

    Per column, starting off at sample 1:
    - high turns on when x > hi (strictly) and stays on until x <= hi - band
    - low turns on when x < lo (strictly) and stays on until x >= lo + band
    With band 0 this is plain x > hi and x < lo.

    lo, hi and band are 1-D, one value per column.

    Raises ValueError if x isn't 2-D, the lengths of lo, hi or band don't match x's
    columns, any lo > hi, any band < 0, or anything holds NaN or inf."""
    raise NotImplementedError


def at_limit(valves, low=VALVE_LOW, high=VALVE_HIGH) -> np.ndarray:
    """Valve-at-limit conditions, bool shaped like valves (samples x valves): on where
    the position is <= low or >= high. No deadband.

    Raises ValueError if valves isn't 2-D, low >= high, or it holds NaN or inf."""
    raise NotImplementedError


def plant_track(points, n_per_point, gap, warmup) -> np.ndarray:
    """The plant alarm stream as 0/1 integers, one value per sample.

    points is bool (samples x alarm points). Each point gets its own on-delay: on at t
    when it is on at t and at each of the n - 1 samples before (alerting.persist). The
    stream is the OR over points, then alerting.group(stream, gap, warmup): the warm-up
    is off, and the stream holds gap samples after clearing.

    n_per_point is 1-D, one on-delay per point (n for tags and valves,
    ANALYZER_ON_DELAY for analyzers).

    Raises ValueError if points isn't 2-D or holds anything but 0/1, n_per_point doesn't
    match its columns, any n < 1, any n - 1 > warmup (the memory bound, decision 52),
    gap < 0 or warmup < 0."""
    raise NotImplementedError