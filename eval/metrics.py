"""Event-level detection metrics (eval/PROTOCOL.md, Detection metrics; decision 49).

Stubs only: Raj implements these against tests/test_metrics.py.

Conventions:
- An alert track is a 1-D array of 0/1 (or bool), one value per sample. Index 0 is
  sample 1.
- Sample numbers in arguments and results are 1-based, as in the protocol.
- `onset` is the last pre-fault sample: 20 in training runs, 160 in testing runs.
- The first `warmup` samples aren't scored. Scoring starts at sample warmup + 1.
- If the track is on at the first scored sample, that sample is a notification.
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
    raise NotImplementedError


def detection(alert, onset, window=WINDOW_SAMPLES, warmup=0, sample_min=SAMPLE_MIN) -> Detection:
    """Detected if a notification falls in samples onset+1 .. onset+window.
    Raises ValueError if warmup >= onset."""
    raise NotImplementedError


def delay_summary(delays: Sequence[float]) -> tuple[float, float, float]:
    """(median, q1, q3) of per-run delays, misses as INF. Linear interpolation between
    sorted values; any interpolation that touches INF gives INF, never NaN.
    Raises ValueError on an empty sequence."""
    raise NotImplementedError


def false_alerts_per_24h(normal_runs: Sequence[ScoredRun], warmup, sample_min=SAMPLE_MIN
                         ) -> tuple[int, float, float]:
    """(notifications, hours counted, notifications per 24 h) over normal runs only
    (rule 4). Hours count scored samples only. Raises ValueError on any fault run."""
    raise NotImplementedError


def chance_rate(normal_runs: Sequence[ScoredRun], fake_onset, window=WINDOW_SAMPLES, warmup=0
                ) -> float:
    """Share of normal runs 'detected' with a fake onset (rule 4: normal runs only).
    Raises ValueError on any fault run or an empty sequence."""
    raise NotImplementedError


def share_still_flagged(alert, first_detection) -> float:
    """Share of samples first_detection .. end of run where the track is on, both ends
    included. Raises ValueError if first_detection is None or the track is off there."""
    raise NotImplementedError


def bootstrap_ci(runs: Sequence[ScoredRun], stat: Callable[[list[ScoredRun]], float], rng,
                 n=BOOTSTRAP_N, level=0.95) -> tuple[float, float]:
    """Percentile interval of stat over n resamples of run numbers (rule 3). Each resample
    draws as many run numbers as there are distinct ones, with replacement, and a drawn
    number brings every run with that number (every file) into the resample."""
    raise NotImplementedError


def paired_bootstrap_ci(runs_a: Sequence[ScoredRun], runs_b: Sequence[ScoredRun],
                        stat: Callable[[list[ScoredRun]], float], rng, n=BOOTSTRAP_N,
                        level=0.95) -> tuple[float, float]:
    """Percentile interval of stat(A) - stat(B), with the same run-number draw used for
    both detectors in each resample."""
    raise NotImplementedError