"""Event-level detection metrics (eval/PROTOCOL.md, Detection metrics; decision 49).

Conventions:
- An alert track is a 1-D array of 0/1 (or bool), one value per sample. Index 0 is
  sample 1. Any other value (NaN, 2, 0.5) is refused: a gap is not an alert.
- Sample numbers in arguments and results are 1-based, as in the protocol.
- `onset` is the last pre-fault sample: 20 in training runs, 160 in testing runs.
- The first `warmup` samples aren't scored. Scoring starts at sample warmup + 1.
- If the track is on at the first scored sample, that sample is a notification.
- Quantiles interpolate linearly between sorted values. A point between an infinity
  and anything else is that infinity, never NaN.
"""

import math
from dataclasses import dataclass
from typing import Callable, NamedTuple, Sequence

import numpy as np

SAMPLE_MIN = 3
WINDOW_SAMPLES = 80           # useful detection window: 4 h after onset
TRAIN_ONSET = 20
TEST_ONSET = 160
BOOTSTRAP_N = 2000
INF = math.inf


@dataclass(frozen=True)
class ScoredRun:
    fault: int                # 0 for a normal run
    run: int                  # run number (decision 49)
    alert: np.ndarray         # the run's alert track


class Detection(NamedTuple):
    detected: bool
    sample: int | None        # 1-based sample of the first notification in the window
    delay_min: float          # (sample - onset) * SAMPLE_MIN; INF on a miss


def notifications(alert, warmup) -> list[int]:
    """1-based samples where the track turns on, among the scored samples."""
    if warmup < 0:
        raise ValueError("warm-up can't be negative")
    a = np.asarray(alert)
    if not np.isin(a, (0, 1)).all():                  # NaN, 2, 0.5 ... are refused
        raise ValueError("an alert track must hold only 0/1 values; a gap is not an alert")
    a = a.astype(bool)
    result = []
    for i in range(warmup, len(a)):     # skip the warm-up; i is 0-based, so sample = i + 1
        is_on = a[i]
        # "Was off before" is True at the first scored sample (nothing scored before it),
        # or when the previous sample was off. The `or` stops early, so a[-1] is never read.
        was_off_before = i == warmup or not a[i - 1]
        if is_on and was_off_before:
            result.append(i + 1)        # store the 1-based sample number
    return result


def detection(alert, onset, window=WINDOW_SAMPLES, warmup=0, sample_min=SAMPLE_MIN) -> Detection:
    """Detected if a notification falls in samples onset+1 .. onset+window.
    Raises ValueError if warmup >= onset."""
    if warmup >= onset:
        raise ValueError(f"warm-up ({warmup}) must end before onset ({onset})")
    for s in notifications(alert, warmup):          # switch-on moments, in time order
        if onset + 1 <= s <= onset + window:        # inside the detection window?
            return Detection(True, s, float((s - onset) * sample_min))
    return Detection(False, None, INF)              # no switch-on in the window: missed


def _quantile(values, q):
    """The q-quantile of already-sorted values, interpolating linearly between the two
    neighbours. A point between an infinity and anything else is that infinity."""
    pos = q * (len(values) - 1)                 # where the q-point sits in the sorted list
    lo = math.floor(pos)                        # index of the value just below it
    hi = min(lo + 1, len(values) - 1)           # index of the value just above it
    frac = pos - lo                             # how far between the two (0 to 1)
    a, b = values[lo], values[hi]
    if frac == 0 or a == b:
        return a                                # on a value, or between two equal ones
    if a == -INF and b == INF:
        raise ValueError("a quantile falls between -inf and +inf, so it is undefined")
    if b == INF:
        return INF                              # between something and a miss: a miss
    if a == -INF:
        return -INF
    return a + frac * (b - a)


def delay_summary(delays: Sequence[float]) -> tuple[float, float, float]:
    """(median, q1, q3) of per-run delays, misses as INF. Linear interpolation between
    sorted values; any interpolation that touches INF gives INF, never NaN.
    Raises ValueError on an empty sequence or a NaN delay."""
    if len(delays) == 0:
        raise ValueError("no delays to summarise")
    values = [float(d) for d in delays]
    if any(math.isnan(v) for v in values):
        raise ValueError("a delay is NaN; a miss must be INF")
    values.sort()                                   # misses (INF) sort to the end
    return _quantile(values, 0.5), _quantile(values, 0.25), _quantile(values, 0.75)


def false_alerts_per_24h(normal_runs: Sequence[ScoredRun], warmup, sample_min=SAMPLE_MIN
                         ) -> tuple[int, float, float]:
    """(notifications, hours counted, notifications per 24 h) over normal runs only
    (rule 4). Hours count scored samples only. Raises ValueError on any fault run, or if
    the warm-up doesn't end inside a run."""
    count, scored_samples = 0, 0
    for r in normal_runs:
        if r.fault != 0:                              # rule 4: normal runs only
            raise ValueError(f"run {r.run} is from fault {r.fault}; "
                             "false alerts are counted on normal runs only")
        if not 0 <= warmup < len(r.alert):
            raise ValueError(f"warm-up {warmup} doesn't end inside run {r.run}")
        count += len(notifications(r.alert, warmup))  # every switch-on here is a false alert
        scored_samples += len(r.alert) - warmup       # samples after the warm-up
    hours = scored_samples * sample_min / 60
    if hours == 0:
        raise ValueError("no scored hours to count")
    return count, hours, count / hours * 24


def chance_rate(normal_runs: Sequence[ScoredRun], fake_onset, window=WINDOW_SAMPLES, warmup=0
                ) -> float:
    """Share of normal runs 'detected' with a fake onset (rule 4: normal runs only).
    Raises ValueError on any fault run or an empty sequence."""
    if len(normal_runs) == 0:
        raise ValueError("no normal runs to score")
    hits = 0
    for r in normal_runs:
        if r.fault != 0:                              # rule 4: normal runs only
            raise ValueError(f"run {r.run} is from fault {r.fault}; "
                             "chance rates use normal runs only")
        if detection(r.alert, fake_onset, window, warmup).detected:
            hits += 1                                 # a lucky "detection" with no fault
    return hits / len(normal_runs)


def share_still_flagged(alert, first_detection) -> float:
    """Share of samples first_detection .. end of run where the track is on, both ends
    included. Raises ValueError if first_detection is None or the track is off there."""
    if first_detection is None:
        raise ValueError("no detection, so nothing to measure")
    a = np.asarray(alert, dtype=bool)
    if not 1 <= first_detection <= len(a):
        raise ValueError(f"sample {first_detection} isn't in this run")
    rest = a[first_detection - 1:]                # sample n is index n - 1
    if not rest[0]:
        raise ValueError(f"the alert is off at sample {first_detection}")
    return float(rest.mean())                     # mean of True/False = share that is on


def first_divergence(run, twin) -> int | None:
    """1-based first sample where run and its fault-free twin differ in any column, by
    exact equality; None if they're identical (decision 57).

    run and twin are 2-D arrays (samples x columns), already cut to the detector's own
    input tags, in the same column order. Up to the sample before this one, a causal
    detector sees the same inputs on both runs, so its tracks are identical there.

    Raises ValueError if either isn't 2-D, if their shapes differ, or if either holds
    NaN or inf (NaN never equals itself, so it would read as a divergence)."""
    a, b = np.asarray(run), np.asarray(twin)
    if a.ndim != 2 or b.ndim != 2:
        raise ValueError("run and twin must be 2-D arrays (samples x columns)")
    if a.shape != b.shape:
        raise ValueError(f"run and twin differ in shape: {a.shape} vs {b.shape}")
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        raise ValueError("run or twin holds NaN or inf")
    differs = (a != b).any(axis=1)              # one True/False per sample: any column differs?
    if not differs.any():
        return None                             # identical all the way through
    return int(np.argmax(differs)) + 1          # first differing row, as a 1-based sample


def before_divergence_share(detections: Sequence[Detection],
                            divergences: Sequence[int | None]) -> tuple[int, int]:
    """(detections before divergence, detected runs) over one fault's runs (decision 57).

    detections[i] and divergences[i] belong to the same run. Missed runs are left out.
    A detected run counts as "before" when its notification sample is less than its
    divergence sample, or when it never diverges (None): either way the twin's track is
    identical up to that notification, so the detection is luck.

    Raises ValueError if the two sequences differ in length, or a divergence isn't None
    or an integer >= 1 (Python or numpy integers; bool is refused)."""
    if len(detections) != len(divergences):
        raise ValueError("detections and divergences must have the same length")
    before = detected = 0
    for d, div in zip(detections, divergences):
        if div is not None and (isinstance(div, bool) or not isinstance(div, (int, np.integer))
                                or div < 1):
            raise ValueError(f"a divergence must be None or an integer >= 1, got {div!r}")
        if not d.detected:
            continue                            # misses are left out
        detected += 1
        if div is None or d.sample < div:
            before += 1                         # the twin's track is identical up to here: luck
    return before, detected


NOTIFY_SAMPLES = 40           # notification window: 2 h after onset (alarm comparison)
PERIOD_MIN = 10               # counting period for "per 10 minutes" and flood (decision 60)
FLOOD_ABOVE = 10              # a period with more than this many notifications is a flood
CHATTER_TIMES = 3             # chattering: this many turn-ons ...
CHATTER_SPAN = 10             # ... within this many consecutive samples (30 min)


class LeadTime(NamedTuple):
    median_min: float | None  # median of (baseline delay - App 3 delay) over both-detected runs
    both: int
    only_app: int
    only_base: int
    neither: int


def period_counts(notification_samples, onset, window=NOTIFY_SAMPLES, period_min=PERIOD_MIN,
                  sample_min=SAMPLE_MIN) -> list[int]:
    """Notifications per period in the notification window (decision 60).

    The window is samples onset + 1 .. onset + window. A sample s is (s - onset) *
    sample_min minutes after onset, and period j holds the minutes in
    (j * period_min, (j + 1) * period_min]. There are ceil(window * sample_min /
    period_min) periods (12 for the defaults), and every one is returned, zeros included.
    Samples outside the window are ignored.

    Raises ValueError if window < 1, period_min <= 0 or sample_min <= 0."""
    if window < 1 or period_min <= 0 or sample_min <= 0:
        raise ValueError("window must be >= 1, and period_min and sample_min > 0")
    counts = [0] * math.ceil(window * sample_min / period_min)       # 12 periods by default
    for s in notification_samples:
        if onset + 1 <= s <= onset + window:                        # inside the window
            minutes = (s - onset) * sample_min                      # time after onset
            counts[math.ceil(minutes / period_min) - 1] += 1        # (10j, 10j + 10] -> period j
    return counts


def is_chattering(notification_samples, first, last, times=CHATTER_TIMES,
                  span=CHATTER_SPAN) -> bool:
    """True if at least `times` of the notification samples that lie in first..last fall
    within `span` consecutive samples, i.e. some `times` of them have
    last - first <= span - 1 (decision 60).

    notification_samples are 1-based and ascending (as notifications() returns them).

    Raises ValueError if they aren't strictly ascending, first > last, times < 1 or
    span < 1."""
    s = list(notification_samples)
    if any(b <= a for a, b in zip(s, s[1:])):
        raise ValueError("notification samples must be strictly ascending")
    if first > last:
        raise ValueError(f"first ({first}) can't be after last ({last})")
    if times < 1 or span < 1:
        raise ValueError("times and span must be at least 1")
    inside = [x for x in s if first <= x <= last]
    for i in range(len(inside) - times + 1):
        # `times` consecutive turn-ons from inside[i]: do they fit in `span` samples?
        if inside[i + times - 1] - inside[i] <= span - 1:
            return True
    return False


def lead_time(app: Sequence[Detection], base: Sequence[Detection]) -> LeadTime:
    """Lead time of App 3 over the baseline on one fault's runs (decisions 58, 60).

    app[i] and base[i] are the two detectors' detections on the same run. The median is
    of base.delay_min - app.delay_min over runs where both detected (positive when App 3
    is earlier), interpolating linearly; None if no run has both. Pairs with a miss are
    never subtracted: they are only counted (only_app, only_base, neither).

    Raises ValueError if the sequences differ in length."""
    if len(app) != len(base):
        raise ValueError("app and base must cover the same runs")
    gaps, only_app, only_base, neither = [], 0, 0, 0
    for a, b in zip(app, base):
        if a.detected and b.detected:
            gaps.append(b.delay_min - a.delay_min)                  # positive: App 3 earlier
        elif a.detected:
            only_app += 1
        elif b.detected:
            only_base += 1
        else:
            neither += 1                                            # misses are only counted
    median = float(np.median(gaps)) if gaps else None
    return LeadTime(median, len(gaps), only_app, only_base, neither)


SECONDARY_OFFSET = 10         # the right-place reading 30 min after the notification (decision 65)


def right_place(order, names, allowed) -> bool:
    """Right place for one detected run (decision 65): the top-ranked group, names[order[0]],
    is one of the true family's groups. order is rbc.rank_at's order for the group ratios
    (highest mean first, ties in column order); names gives each column's group name;
    allowed is the family's groups.

    Raises ValueError if order is empty or isn't a permutation of range(len(names)), if
    names repeat, if allowed is empty, or if allowed names a group that isn't in names
    (a typo in the map must not read as a miss)."""
    raise NotImplementedError("Raj: week 4 session 4")


def _by_run_number(runs):
    """Group runs by run number: {number: [every run with that number]}."""
    groups = {}
    for r in runs:
        groups.setdefault(r.run, []).append(r)
    return groups


def _percentile_interval(values, level):
    """The middle `level` share of the values, e.g. 2.5th to 97.5th percentile. Uses the
    same infinity-safe interpolation as delay_summary."""
    if any(math.isnan(v) for v in values):
        raise ValueError("the statistic returned NaN in a resample")
    ordered = sorted(float(v) for v in values)
    tail = (1 - level) / 2
    return _quantile(ordered, tail), _quantile(ordered, 1 - tail)


def bootstrap_ci(runs: Sequence[ScoredRun], stat: Callable[[list[ScoredRun]], float], rng,
                 n=BOOTSTRAP_N, level=0.95) -> tuple[float, float]:
    """Percentile interval of stat over n resamples of run numbers (rule 3). Each resample
    draws as many run numbers as there are distinct ones, with replacement, and a drawn
    number brings every run with that number (every file) into the resample."""
    groups = _by_run_number(runs)
    numbers = sorted(groups)
    if not numbers:
        raise ValueError("no runs to resample")
    values = []
    for _ in range(n):
        picks = rng.integers(0, len(numbers), size=len(numbers))    # repeats allowed
        resample = [r for i in picks for r in groups[numbers[i]]]   # twins come along
        values.append(stat(resample))
    return _percentile_interval(values, level)


def paired_bootstrap_ci(runs_a: Sequence[ScoredRun], runs_b: Sequence[ScoredRun],
                        stat: Callable[[list[ScoredRun]], float], rng, n=BOOTSTRAP_N,
                        level=0.95) -> tuple[float, float]:
    """Percentile interval of stat(A) - stat(B), with the same run-number draw used for
    both detectors in each resample. Raises ValueError if both statistics are the same
    infinity in a resample, because their difference is then undefined."""
    groups_a, groups_b = _by_run_number(runs_a), _by_run_number(runs_b)
    if set(groups_a) != set(groups_b):
        raise ValueError("both detectors must be scored on the same run numbers")
    numbers = sorted(groups_a)
    if not numbers:
        raise ValueError("no runs to resample")
    values = []
    for _ in range(n):
        picks = rng.integers(0, len(numbers), size=len(numbers))
        drawn = [numbers[i] for i in picks]                         # one draw, used for both
        a = stat([r for k in drawn for r in groups_a[k]])
        b = stat([r for k in drawn for r in groups_b[k]])
        if math.isinf(a) and a == b:
            raise ValueError("both detectors' statistics are infinite in a resample, so "
                             "their difference is undefined; compare a finite statistic")
        values.append(a - b)
    return _percentile_interval(values, level)
