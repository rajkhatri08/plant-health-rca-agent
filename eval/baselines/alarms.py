"""The conventional-alarm baseline (decision 58; PROTOCOL, Alarm comparison).

Eval only: a comparator, never imported by app/. The constants are fixed by decision 58.

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

from app.detector import alerting

# Deadband as a multiple of the tag's calibration-pool spread, by signal type
# (decision 58). A type missing here has no agreed deadband yet.
DEADBAND_SIGMA = {"temperature": 0.25, "pressure": 0.25, "flow": 0.5, "level": 0.5,
                  "composition": 0.5, "power": 0.5, "valve": 0.5}
VALVE_LOW = 2.0                      # % open: at or below is "at limit"
VALVE_HIGH = 98.0                    # % open: at or above is "at limit"
ANALYZER_ON_DELAY = 1                # samples of the held series: the first reading past the limit


def _scored_pool(runs, warmup) -> np.ndarray:
    """Every run's scored samples (after the warm-up) stacked into one samples x columns
    array, float64. Shared checks for tag_limits and tag_spread."""
    if len(runs) == 0:
        raise ValueError("no runs to pool")
    arrays = [np.asarray(r, dtype=np.float64) for r in runs]
    if any(a.ndim != 2 for a in arrays):
        raise ValueError("every run must be a 2-D array (samples x columns)")
    if len({a.shape[1] for a in arrays}) != 1:
        raise ValueError("every run must have the same columns")
    if any(not 0 <= warmup < len(a) for a in arrays):
        raise ValueError(f"the warm-up ({warmup}) doesn't end inside every run")
    if not all(np.isfinite(a).all() for a in arrays):
        raise ValueError("the runs hold NaN or inf")
    return np.concatenate([a[warmup:] for a in arrays])     # scored samples only


def tag_limits(runs, q, warmup) -> tuple[np.ndarray, np.ndarray]:
    """(lo, hi) per column: the (100 - q)/2 and (100 + q)/2 percentiles of the pooled
    scored samples (after warm-up) of every run, numpy's default linear percentile.
    So each tag has the same two-sided per-sample false rate, 100 - q percent.

    runs is a list of 2-D arrays (samples x columns), all with the same columns.

    Raises ValueError if runs is empty, the column counts differ, a run isn't 2-D, the
    warm-up doesn't end inside every run, q isn't in (0, 100), or a value is NaN or inf."""
    if not 0 < q < 100:
        raise ValueError(f"q must be in (0, 100), got {q}")
    pool = _scored_pool(runs, warmup)
    lo = np.percentile(pool, (100 - q) / 2, axis=0)          # e.g. q = 99: the 0.5th percentile
    hi = np.percentile(pool, (100 + q) / 2, axis=0)          #          and the 99.5th
    return lo, hi


def tag_spread(runs, warmup) -> np.ndarray:
    """σ per column: the standard deviation (ddof = 0) of the pooled scored samples of
    every run. The deadband is DEADBAND_SIGMA[type] times this.

    Raises ValueError on the same inputs as tag_limits (except q)."""
    return _scored_pool(runs, warmup).std(axis=0)


def _latch(turn_on, turn_off) -> np.ndarray:
    """A latched condition, per column: on from a sample where turn_on holds, off from a
    sample where turn_off holds, and otherwise whatever it was (off before any event).
    The two never hold at the same sample. In other words, the latest event wins."""
    event = np.where(turn_on, 1, np.where(turn_off, -1, 0))            # +1 on, -1 off, 0 keep
    t = np.arange(len(event))[:, None]
    latest = np.maximum.accumulate(np.where(event != 0, t, -1), axis=0)  # latest event so far
    state = np.take_along_axis(event, np.maximum(latest, 0), axis=0) == 1
    return state & (latest >= 0)                                       # no event yet: off


def hysteresis(x, lo, hi, band) -> tuple[np.ndarray, np.ndarray]:
    """(high, low) latched alarm conditions, bool arrays shaped like x (samples x columns).

    Per column, starting off at sample 1:
    - high turns on when x > hi (strictly) and stays on until x <= hi - band
    - low turns on when x < lo (strictly) and stays on until x >= lo + band
    With band 0 this is plain x > hi and x < lo.

    lo, hi and band are 1-D, one value per column.

    Raises ValueError if x isn't 2-D, the lengths of lo, hi or band don't match x's
    columns, any lo > hi, any band < 0, or anything holds NaN or inf."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2:
        raise ValueError("x must be a 2-D array (samples x columns)")
    lo, hi, band = (np.asarray(v, dtype=np.float64).ravel() for v in (lo, hi, band))
    if not len(lo) == len(hi) == len(band) == x.shape[1]:
        raise ValueError("lo, hi and band need one value per column")
    if not all(np.isfinite(v).all() for v in (x, lo, hi, band)):
        raise ValueError("x, a limit or a band holds NaN or inf")
    if (lo > hi).any():
        raise ValueError("a low limit is above its high limit")
    if (band < 0).any():
        raise ValueError("a deadband can't be negative")
    high = _latch(x > hi, x <= hi - band)     # above the limit: on; back inside the band: off
    low = _latch(x < lo, x >= lo + band)
    return high, low


def at_limit(valves, low=VALVE_LOW, high=VALVE_HIGH) -> np.ndarray:
    """Valve-at-limit conditions, bool shaped like valves (samples x valves): on where
    the position is <= low or >= high. No deadband.

    Raises ValueError if valves isn't 2-D, low >= high, or it holds NaN or inf."""
    v = np.asarray(valves, dtype=np.float64)
    if v.ndim != 2:
        raise ValueError("valves must be a 2-D array (samples x valves)")
    if not low < high:
        raise ValueError(f"the low position ({low}) must be below the high one ({high})")
    if not np.isfinite(v).all():
        raise ValueError("the valve positions hold NaN or inf")
    return (v <= low) | (v >= high)           # nearly shut or nearly wide open


def _checked_points(points, n_per_point, gap, warmup):
    """points as a 2-D array and the on-delays as ints, with the checks plant_track and
    point_tracks share (see plant_track's docstring)."""
    p = np.asarray(points)
    if p.ndim != 2:
        raise ValueError("points must be a 2-D array (samples x alarm points)")
    if not np.isin(p, (0, 1)).all():
        raise ValueError("points must hold only 0/1 values")
    ns = [int(n) for n in n_per_point]
    if len(ns) != p.shape[1]:
        raise ValueError("n_per_point needs one on-delay per alarm point")
    if gap < 0 or warmup < 0:
        raise ValueError(f"gap and warm-up can't be negative, got gap {gap}, warm-up {warmup}")
    if any(n < 1 for n in ns):
        raise ValueError("every on-delay must be at least 1")
    if any(n - 1 > warmup for n in ns):
        raise ValueError(f"memory bound broken: an on-delay n - 1 is more than the warm-up "
                         f"{warmup} (decision 52)")
    return p, ns


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
    p, ns = _checked_points(points, n_per_point, gap, warmup)
    held = np.zeros(len(p), dtype=bool)
    for j, n in enumerate(ns):
        held |= alerting.persist(p[:, j], n)  # each point's own on-delay, then OR them
    return alerting.group(held, gap, warmup).astype(int)


def point_tracks(points, n_per_point, gap, warmup) -> np.ndarray:
    """Each alarm point's own track as 0/1 integers (samples x points), for counting what
    an operator sees (decision 60): per point, alerting.persist(point, n), then
    alerting.group(held, gap, warmup). The OR across points equals plant_track(...),
    because the off-delay is a running max and commutes with the OR.

    Raises ValueError on the same inputs as plant_track."""
    p, ns = _checked_points(points, n_per_point, gap, warmup)
    out = np.zeros(p.shape, dtype=int)
    for j, n in enumerate(ns):
        # this point alone: its on-delay, then the off-delay, with the warm-up off




        out[:, j] = alerting.group(alerting.persist(p[:, j], n), gap, warmup)
    return out








