"""Calibrating the limit, persistence and grouping to one budget (decision 54).

The driver that loads data and writes the run record comes in session 4.

The search, the same for every compared detector (a detector only has to give a ratio
track for each q):
    for each (n, G) in N x G:
        q(n, G) = lowest_stable_q(...)          lowest grid q that is safe from the top down
    scores = mean detection rate on the selection runs, per eligible (n, G)
    (n, G, q) = choose(...)

Conventions: arrays cover whole runs (index 0 = sample 1), as in app/detector/alerting.py.
"""

from typing import Callable, Mapping

import numpy as np

from app.detector import alerting
from eval import metrics

Q_GRID = tuple(np.round(np.arange(9500, 10000) / 100, 2).tolist() + np.round(np.arange(99991, 100000) / 1000, 3).tolist())   # 95.00 ... 99.99, then 99.991 ... 99.999 (decision 59)
GAP_RANGE = range(0, 21)                    # off-delay G, samples
SELECTION_FAULTS = tuple(f for f in range(1, 16) if f not in (3, 9, 15))
BUDGET_PER_24H = 1.0
TIE_TOL = 1e-12


def n_range(lags=0, warmup=9) -> range:
    """Persistence windows allowed with this many lags: 1 .. warmup - lags + 1
    (decision 52: lags + n - 1 <= warmup). Raises ValueError if lags > warmup."""
    if lags > warmup:
        raise ValueError(f"lags ({lags}) can't be more than the warm-up ({warmup})")
    return range(1, warmup - lags + 2)          # the largest n satisfies lags + n - 1 == warmup


def limits_at(t2_runs, spe_runs, q, warmup) -> tuple[float, float]:
    """(T²lim, SPElim): the q-th percentile (numpy's default linear method) of each
    statistic over every run's scored samples (index warmup onwards), pooled.

    Raises ValueError if q isn't in (0, 100], if there are no runs, if the two lists
    differ in length or a run's T² and SPE differ in length, or if the warm-up doesn't
    end inside every run."""
    if not 0 < q <= 100:
        raise ValueError(f"q must be in (0, 100], got {q}")
    if len(t2_runs) == 0:
        raise ValueError("no runs to calibrate on")
    if len(t2_runs) != len(spe_runs):
        raise ValueError("T² and SPE must cover the same runs")
    t2_scored, spe_scored = [], []
    for t2, spe in zip(t2_runs, spe_runs):
        t2, spe = np.asarray(t2, dtype=np.float64), np.asarray(spe, dtype=np.float64)
        if len(t2) != len(spe):
            raise ValueError("a run's T² and SPE differ in length")
        if not 0 <= warmup < len(t2):
            raise ValueError(f"the warm-up ({warmup}) doesn't end inside a run")
        t2_scored.append(t2[warmup:])          # scored samples only
        spe_scored.append(spe[warmup:])
    return (float(np.percentile(np.concatenate(t2_scored), q)),
            float(np.percentile(np.concatenate(spe_scored), q)))


def lowest_stable_q(ratio_runs_at: Callable[[float], Mapping[int, np.ndarray]], n, gap,
                    warmup, lags=0, q_grid=Q_GRID, track=None) -> float | None:
    """The lowest q in q_grid such that it and every higher grid value meet the budget
    on the calibration runs; None if the highest grid value already fails.

    ratio_runs_at(q) gives the calibration pool's ratio tracks at limit percentile q,
    as {run number: ratio array}. Each is turned into an alert track with
    alerting.alert_track(ratio, n, gap, warmup, lags), and the budget is met when
    metrics.false_alerts_per_24h over those runs (as normal runs, fault 0) gives at most
    BUDGET_PER_24H.

    Scan from the top of the grid down and stop at the first failure: notifications
    don't always fall as q rises, so a lower q that happens to pass below a failure
    doesn't count.

    track, if given, replaces alerting.alert_track as the way each run's value from
    ratio_runs_at(q) becomes an alert track: track(value, n, gap, warmup, lags) -> 0/1
    array. The alarm baseline uses it for its per-tag on-delays (decision 58).

    Raises ValueError if q_grid is empty or not strictly increasing."""
    build = alerting.alert_track if track is None else track
    grid = list(q_grid)
    if not grid or any(b <= a for a, b in zip(grid, grid[1:])):
        raise ValueError("q_grid must be non-empty and strictly increasing")
    lowest = None
    for q in reversed(grid):                    # from the strictest limit down
        runs = [metrics.ScoredRun(0, k, build(r, n, gap, warmup, lags))
                for k, r in ratio_runs_at(q).items()]
        _, _, per_24h = metrics.false_alerts_per_24h(runs, warmup)
        if per_24h > BUDGET_PER_24H:
            break                               # first failure: nothing below it counts
        lowest = q
    return lowest


WATCH_CAP = 0.02                            # decision 66: any group in Watch at most 2% of normal time


def _pooled_scored(rbc_runs, warmup) -> np.ndarray:
    """Every run's scored samples (index warmup onwards) stacked into one samples x columns
    array, float64, with the checks watch_limits_at and watch_shares share."""
    if len(rbc_runs) == 0:
        raise ValueError("no runs to pool")
    arrays = [np.asarray(r, dtype=np.float64) for r in rbc_runs]
    if any(a.ndim != 2 for a in arrays):
        raise ValueError("every run must be a 2-D array (samples x columns)")
    if len({a.shape[1] for a in arrays}) != 1:
        raise ValueError("every run must have the same columns")
    if any(not 0 <= warmup < len(a) for a in arrays):
        raise ValueError(f"the warm-up ({warmup}) doesn't end inside every run")
    if not all(np.isfinite(a).all() for a in arrays):
        raise ValueError("the runs hold NaN or inf")
    return np.concatenate([a[warmup:] for a in arrays])


def watch_limits_at(rbc_runs, p, warmup) -> np.ndarray:
    """Boundaries at percentile p (decisions 65, 66): per column, the p-th percentile
    (numpy's default linear method) of that column over every run's scored samples
    (index warmup onwards), pooled over runs. rbc_runs is a list of whole-run arrays,
    samples x columns (RBC per group, or per tag), index 0 = sample 1. Returns shape
    (columns,), float64.

    Raises ValueError if p isn't in (0, 100], if there are no runs, if runs have different
    column counts, if the warm-up doesn't end inside every run, or on NaN or inf."""
    if not 0 < p <= 100:
        raise ValueError(f"p must be in (0, 100], got {p}")
    return np.percentile(_pooled_scored(rbc_runs, warmup), p, axis=0)   # one limit per column


def watch_shares(rbc_runs, limits, warmup) -> tuple[float, np.ndarray]:
    """(any_share, column_shares) over every run's scored samples, pooled. A column is in
    Watch at a sample when its value is strictly above its limit (RBC_g / W_g > 1).
    any_share is the share of samples with at least one column in Watch; column_shares[j]
    is column j's own share. Same refusals as watch_limits_at, plus limits whose length
    isn't the column count or that aren't finite and > 0."""
    pool = _pooled_scored(rbc_runs, warmup)
    lim = np.asarray(limits, dtype=np.float64)
    if lim.ndim != 1 or len(lim) != pool.shape[1]:
        raise ValueError(f"need one limit per column ({pool.shape[1]}), got shape {lim.shape}")
    if not (np.isfinite(lim).all() and (lim > 0).all()):
        raise ValueError("every limit must be a finite number > 0")
    above = pool > lim                                  # strictly above its limit: in Watch
    return float(above.any(axis=1).mean()), above.mean(axis=0)


def watch_limit(rbc_runs, warmup, cap=WATCH_CAP, q_grid=Q_GRID) -> float | None:
    """The shared percentile p for every group's Watch boundary (decision 66): the lowest
    p in q_grid such that it and every higher grid value give watch_shares(...)[0] <= cap
    at watch_limits_at(rbc_runs, p, warmup). Scan from the top down and stop at the first
    failure, as lowest_stable_q does. None if the highest grid value already fails; the
    driver then stops with an error.

    Raises ValueError if q_grid is empty or not strictly increasing, or cap isn't in
    [0, 1), plus watch_limits_at's refusals."""
    grid = list(q_grid)
    if not grid:
        raise ValueError("the grid is empty")
    if any(b <= a for a, b in zip(grid, grid[1:])):
        raise ValueError("the grid must be strictly increasing")
    if not 0 <= cap < 1:
        raise ValueError(f"the cap must be in [0, 1), got {cap}")
    best = None
    for p in reversed(grid):                            # strictest boundaries first
        any_share, _ = watch_shares(rbc_runs, watch_limits_at(rbc_runs, p, warmup), warmup)
        if any_share > cap:
            break                                       # first failure: stop, as lowest_stable_q does
        best = p
    return best


def selection_score(tracks_by_fault: Mapping[int, list], warmup) -> float:
    """Mean detection rate over SELECTION_FAULTS (each fault weighted equally).

    tracks_by_fault maps a fault number to that fault's alert tracks on the selection
    runs. A fault's rate is the share of its tracks where metrics.detection finds a
    notification in the window (training onset metrics.TRAIN_ONSET, default window).
    Faults 3, 9 and 15 may be present and are ignored.

    Raises ValueError if a fault in SELECTION_FAULTS is missing or has no tracks, or if
    any key isn't an open fault (1-15)."""
    for f in tracks_by_fault:
        if not 1 <= f <= 15:
            raise ValueError(f"fault {f} isn't an open fault (1-15)")
    rates = []
    for f in SELECTION_FAULTS:
        tracks = tracks_by_fault.get(f)
        if not tracks:
            raise ValueError(f"fault {f} is missing or has no tracks")
        hits = sum(metrics.detection(t, metrics.TRAIN_ONSET, warmup=warmup).detected
                   for t in tracks)
        rates.append(hits / len(tracks))        # this fault's detection rate
    return float(np.mean(rates))                # every fault weighted equally


def choose(candidates: Mapping[tuple[int, int], tuple[float | None, float]]
           ) -> tuple[int, int, float]:
    """(n, gap, q) of the chosen setting.

    candidates maps (n, gap) to (q, score), where q is lowest_stable_q's result and
    score is selection_score's. A setting with q None isn't eligible. The highest score
    wins; scores within TIE_TOL of the best are ties, broken by the smaller n, then the
    smaller gap.

    Raises ValueError if no setting is eligible."""
    eligible = {s: (q, score) for s, (q, score) in candidates.items() if q is not None}
    if not eligible:
        raise ValueError("no (n, gap) setting meets the budget")
    best = max(score for _, score in eligible.values())
    tied = [s for s, (_, score) in eligible.items() if score >= best - TIE_TOL]
    n, gap = min(tied)                          # smaller n first, then smaller gap
    return n, gap, eligible[(n, gap)][0]
