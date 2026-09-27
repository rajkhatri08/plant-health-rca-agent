"""Calibrating the limit, persistence and grouping to one budget (decision 54).

Stubs for Raj. The driver that loads data and writes the run record comes in session 4.

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

Q_GRID = tuple(np.round(np.arange(9500, 10000) / 100, 2).tolist())   # 95.00, 95.01 ... 99.99
GAP_RANGE = range(0, 21)                    # off-delay G, samples
SELECTION_FAULTS = tuple(f for f in range(1, 16) if f not in (3, 9, 15))
BUDGET_PER_24H = 1.0
TIE_TOL = 1e-12


def n_range(lags=0, warmup=9) -> range:
    """Persistence windows allowed with this many lags: 1 .. warmup - lags + 1
    (decision 52: lags + n - 1 <= warmup). Raises ValueError if lags > warmup."""
    raise NotImplementedError


def limits_at(t2_runs, spe_runs, q, warmup) -> tuple[float, float]:
    """(T²lim, SPElim): the q-th percentile (numpy's default linear method) of each
    statistic over every run's scored samples (index warmup onwards), pooled.

    Raises ValueError if q isn't in (0, 100], if there are no runs, if the two lists
    differ in length or a run's T² and SPE differ in length, or if the warm-up doesn't
    end inside every run."""
    raise NotImplementedError


def lowest_stable_q(ratio_runs_at: Callable[[float], Mapping[int, np.ndarray]], n, gap,
                    warmup, lags=0, q_grid=Q_GRID) -> float | None:
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

    Raises ValueError if q_grid is empty or not strictly increasing."""
    raise NotImplementedError


def selection_score(tracks_by_fault: Mapping[int, list], warmup) -> float:
    """Mean detection rate over SELECTION_FAULTS (each fault weighted equally).

    tracks_by_fault maps a fault number to that fault's alert tracks on the selection
    runs. A fault's rate is the share of its tracks where metrics.detection finds a
    notification in the window (training onset metrics.TRAIN_ONSET, default window).
    Faults 3, 9 and 15 may be present and are ignored.

    Raises ValueError if a fault in SELECTION_FAULTS is missing or has no tracks, or if
    any key isn't an open fault (1-15)."""
    raise NotImplementedError


def choose(candidates: Mapping[tuple[int, int], tuple[float | None, float]]
           ) -> tuple[int, int, float]:
    """(n, gap, q) of the chosen setting.

    candidates maps (n, gap) to (q, score), where q is lowest_stable_q's result and
    score is selection_score's. A setting with q None isn't eligible. The highest score
    wins; scores within TIE_TOL of the best are ties, broken by the smaller n, then the
    smaller gap.

    Raises ValueError if no setting is eligible."""
    raise NotImplementedError
