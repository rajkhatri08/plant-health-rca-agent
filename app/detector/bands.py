"""Status bands per sample (decisions 12, 65, 66).

Runtime code: no imports from dataset/, eval/ or ingest/.

- Plant band, in order of precedence: Unknown (warm-up or bad data), Alert (the plant
  alert track is on), Watch (any group's ratio RBC_g / W_g is above 1), Normal.
- Group band: Watch when that group's ratio is above 1, otherwise Normal. It's strictly
  above, as in the calibration (a ratio of exactly 1 isn't Watch).
- Watch never notifies: only the plant alert track does (decision 66).
- Attributed group: during an Alert, the top-ranked group at the notification that started
  the episode. That's rbc.rank_at over the n samples that triggered it (decision 65), held
  for the rest of the episode. Outside an Alert there's none.
"""

import numpy as np

from app.detector import rbc

UNKNOWN, ALERT, WATCH, NORMAL = "Unknown", "Alert", "Watch", "Normal"
BANDS = (NORMAL, WATCH, ALERT, UNKNOWN)


def group_bands(ratios) -> list:
    """Watch or Normal for each group's ratio at one sample. Refuses NaN or inf."""
    r = np.asarray(ratios, dtype=np.float64)
    if not np.isfinite(r).all():
        raise ValueError("a group ratio is NaN or inf; a gap must never read as Normal")
    return [WATCH if x > 1 else NORMAL for x in r]


def plant_band(unknown, alert_on, ratios=None) -> str:
    """The plant band at one sample, by precedence. ratios is None for a bundle without
    Watch boundaries; then the band is Unknown, Alert or Normal, as in the thin slice."""
    if unknown:
        return UNKNOWN
    if alert_on:
        return ALERT
    if ratios is not None and WATCH in group_bands(ratios):
        return WATCH
    return NORMAL


def notifications(alert, warmup) -> list:
    """1-based samples where the alert track turns on among the scored samples. An alert
    already on at the first scored sample counts there (the protocol's definition)."""
    a = np.asarray(alert).astype(bool)
    return [i + 1 for i in range(warmup, len(a)) if a[i] and (i == warmup or not a[i - 1])]


def attributed(alert, group_ratios, warmup, n, names) -> list:
    """Per sample, the attributed group's name during an Alert, else None.
    group_ratios is samples x groups (RBC_g / W_g over the same samples as alert)."""
    a = np.asarray(alert).astype(bool)
    starts = set(notifications(a, warmup))
    out, current = [], None
    for i in range(len(a)):
        if not a[i]:
            current = None
        elif i + 1 in starts:
            _, order = rbc.rank_at(group_ratios, i + 1, n)
            current = names[order[0]]
        out.append(current)
    return out