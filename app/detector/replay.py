"""Replay one historian stream through the detector, as of a time (decisions 12, 19, 37).

Runtime code: no imports from dataset/, eval/ or ingest/.

A stream is historian rows `ts, tag, value, quality` for one run, with no run or segment
IDs (CLAUDE.md). The engine resets for each stream. Scoring uses exactly the functions
calibration used: pca.scores -> alerting.plant_ratio -> alerting.alert_track.

As of time `upto`, only rows with ts <= upto are used, so nothing later can change what
is shown for earlier samples.

Bands per sample (the thin slice; Watch needs equipment-group attribution, week 3/4):
- Unknown ("warm-up"): the first `warmup` samples, which aren't scored.
- Unknown ("data"): from the first sample whose fast tags aren't all present with
  quality "good", or that doesn't follow the previous one by STEP_MIN, to the end.
  The data-quality layer isn't built yet (decision 51), so a gap is never read as
  Normal and scoring stops there.
- Alert: the alert track is on (including its off-delay hold, decision 54).
- Normal: otherwise.
`ratio` is the plant ratio (decision 53) on scored samples, and None on Unknown ones.
"""

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from app.detector import alerting, pca

HEADER = ["ts", "tag", "value", "quality"]
GOOD = "good"
STEP_MIN = 3
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ReplayError(ValueError):
    pass


def parse_ts(text):
    try:
        return datetime.strptime(text, TS_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ReplayError(f"timestamp {text!r} isn't in the form 2026-01-05T06:00:00Z") from None


@dataclass(frozen=True)
class Stream:
    ts: tuple                 # sorted datetimes, one per sample
    values: np.ndarray        # samples x tags, float64; NaN where a tag is missing or not good
    tags: tuple


def read_csv(path, tags):
    """A Stream for these tags from a historian CSV. Rows for other tags are ignored.
    Refuses a wrong header, a bad timestamp or value, and a repeated (ts, tag)."""
    tags = tuple(tags)
    col = {t: j for j, t in enumerate(tags)}
    rows, seen = {}, set()
    with open(path, newline="") as f:
        reader = csv.reader(f)
        if next(reader, None) != HEADER:
            raise ReplayError(f"historian CSV header must be {','.join(HEADER)}")
        for line, row in enumerate(reader, start=2):
            if len(row) != 4:
                raise ReplayError(f"line {line}: expected 4 fields")
            ts, tag, value, quality = row
            t = parse_ts(ts)
            if tag not in col:
                continue
            try:
                v = float(value)
            except ValueError:
                raise ReplayError(f"line {line}: value isn't a number") from None
            if (t, tag) in seen:
                raise ReplayError(f"line {line}: {tag} appears twice at {ts}")
            seen.add((t, tag))
            sample = rows.setdefault(t, np.full(len(tags), np.nan))
            sample[col[tag]] = v if quality == GOOD and np.isfinite(v) else np.nan
    order = sorted(rows)
    values = np.vstack([rows[t] for t in order]) if order else np.empty((0, len(tags)))
    return Stream(ts=tuple(order), values=values, tags=tags)


def status(bundle, stream, upto):
    """Per-sample {ts, band, ratio, reason} for every sample with ts <= upto."""
    if stream.tags != bundle.model.tags:
        raise ReplayError("the stream's tags aren't the model's tags")
    lim = bundle.limits
    m = sum(1 for t in stream.ts if t <= upto)             # as of upto: samples 1..m only
    ts, X = stream.ts[:m], stream.values[:m]

    good = 0                                                # samples before the first bad one
    while good < m and np.isfinite(X[good]).all() and (
            good == 0 or ts[good] - ts[good - 1] == timedelta(minutes=STEP_MIN)):
        good += 1

    ratio = alert = None
    if good:
        t2, spe = pca.scores(bundle.model, X[:good])
        ratio = alerting.plant_ratio(t2, spe, lim["t2_lim"], lim["spe_lim"])
        alert = alerting.alert_track(ratio, lim["n"], lim["gap"], lim["warmup"], lim["lags"])

    out = []
    for i in range(m):
        row = {"ts": ts[i].strftime(TS_FORMAT), "band": "Unknown", "ratio": None, "reason": None}
        if i >= good:
            row["reason"] = "data"
        elif i < lim["warmup"]:
            row["reason"] = "warm-up"
        else:
            row["band"] = "Alert" if alert[i] else "Normal"
            row["ratio"] = float(ratio[i])
        out.append(row)
    return out