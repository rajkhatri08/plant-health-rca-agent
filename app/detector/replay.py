"""Replay one historian stream through the detector, as of a time (decisions 12, 19, 37).

Runtime code: no imports from dataset/, eval/ or ingest/.

A stream is historian rows `ts, tag, value, quality` for one run, with no run or segment
IDs (CLAUDE.md). The engine resets for each stream. Scoring uses exactly the functions
calibration used: pca.scores -> alerting.plant_ratio -> alerting.alert_track.

As of time `upto`, only rows with ts <= upto are used, so nothing later can change what
is shown for earlier samples.

Bands per sample (app/detector/bands.py has the precedence, decision 66):
- Unknown ("warm-up"): the first `warmup` samples, which aren't scored.
- Unknown ("data"): from the first sample whose fast tags aren't all present with
  quality "good", or that doesn't follow the previous one by STEP_MIN, to the end.
  The data-quality layer isn't built yet (decision 51), so a gap is never read as
  Normal and scoring stops there.
- Alert: the alert track is on (including its off-delay hold, decision 54).
- Watch (only with a bundle that has Watch boundaries): not Alert, and at least one
  group's ratio RBC_g / W_g is above 1.
- Normal: otherwise.
`ratio` is the plant ratio (decision 53) on scored samples, and None on Unknown ones.

With Watch boundaries each row also has:
- `groups`: {group: {"ratio": RBC_g / W_g, "band": "Watch" or "Normal"}} on scored
  samples, None on Unknown ones. RBC comes from app/detector/rbc.py, the same code the
  Watch calibration and the dev table use.
- `attributed`: during an Alert, the group ranked first at the notification that started
  it (decision 65); None otherwise.
"""

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from app.detector import alerting, bands, pca, rbc

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


def read_publications(path, tags):
    """{tag: ((ts, value), ...)} in time order for these tags (the analyzers), from a
    historian CSV whose analyzer rows sit only at publication times. Nothing is held or
    interpolated here; the caller holds the last value. A value whose quality isn't
    "good", or that isn't finite, is kept as NaN: a gap must never read as normal. Same
    refusals as read_csv."""
    tags = tuple(tags)
    out, seen = {t: [] for t in tags}, set()
    with open(path, newline="") as f:
        reader = csv.reader(f)
        if next(reader, None) != HEADER:
            raise ReplayError(f"historian CSV header must be {','.join(HEADER)}")
        for line, row in enumerate(reader, start=2):
            if len(row) != 4:
                raise ReplayError(f"line {line}: expected 4 fields")
            ts, tag, value, quality = row
            t = parse_ts(ts)
            if tag not in out:
                continue
            try:
                v = float(value)
            except ValueError:
                raise ReplayError(f"line {line}: value isn't a number") from None
            if (t, tag) in seen:
                raise ReplayError(f"line {line}: {tag} appears twice at {ts}")
            seen.add((t, tag))
            out[tag].append((t, v if quality == GOOD and np.isfinite(v) else float("nan")))
    return {t: tuple(sorted(items, key=lambda p: p[0])) for t, items in out.items()}


def group_ratios(bundle, X):
    """RBC_g / W_g for every sample of X (samples x the model's tags), groups in the
    Watch file's order."""
    w = bundle.watch
    names = list(w["groups"])
    cols = [tuple(bundle.model.tags.index(t) for t in w["groups"][g]["tags"]) for g in names]
    M = rbc.index_matrix(bundle.model, bundle.limits["t2_lim"], bundle.limits["spe_lim"])
    limits = np.array([w["groups"][g]["w"] for g in names])
    return rbc.group_rbc(bundle.model, M, X, cols) / limits, names


def status(bundle, stream, upto):
    """Per-sample {ts, band, ratio, reason} for every sample with ts <= upto, plus
    `groups` and `attributed` when the bundle has Watch boundaries."""
    if stream.tags != bundle.model.tags:
        raise ReplayError("the stream's tags aren't the model's tags")
    lim = bundle.limits
    m = sum(1 for t in stream.ts if t <= upto)             # as of upto: samples 1..m only
    ts, X = stream.ts[:m], stream.values[:m]

    good = 0                                                # samples before the first bad one
    while good < m and np.isfinite(X[good]).all() and (
            good == 0 or ts[good] - ts[good - 1] == timedelta(minutes=STEP_MIN)):
        good += 1

    ratio = alert = g_ratio = names = owner = None
    watch = bundle.watch is not None
    if good:
        t2, spe = pca.scores(bundle.model, X[:good])
        ratio = alerting.plant_ratio(t2, spe, lim["t2_lim"], lim["spe_lim"])
        alert = alerting.alert_track(ratio, lim["n"], lim["gap"], lim["warmup"], lim["lags"])
        if watch:
            g_ratio, names = group_ratios(bundle, X[:good])
            owner = bands.attributed(alert, g_ratio, lim["warmup"], lim["n"], names)

    out = []
    for i in range(m):
        row = {"ts": ts[i].strftime(TS_FORMAT), "band": "Unknown", "ratio": None, "reason": None}
        if watch:
            row.update(groups=None, attributed=None)
        if i >= good:
            row["reason"] = "data"
        elif i < lim["warmup"]:
            row["reason"] = "warm-up"
        else:
            row["band"] = bands.plant_band(False, bool(alert[i]), g_ratio[i] if watch else None)
            row["ratio"] = float(ratio[i])
            if watch:
                row["groups"] = {g: {"ratio": float(r), "band": b}
                                 for g, r, b in zip(names, g_ratio[i], bands.group_bands(g_ratio[i]))}
                row["attributed"] = owner[i]
        out.append(row)
    return out