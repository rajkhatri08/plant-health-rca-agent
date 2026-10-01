"""Signature features, v1 (decision 68): the evidence a diagnosis is matched on.

Runtime code: no imports from dataset/, eval/ or ingest/. Plant tags and loop IDs only.

Everything is as of the diagnosis time and uses normal bands from the calibration pool
(the evidence normals: each tag's central 99%, decision 62), never statistics of the run.

- Readings: the location at the notification t, then "provisional" as of t + 10 samples
  (+30 min) and "revised" as of t + 20 (+60 min) (decision 11).
- Window (F2-A): samples t - n + 1 .. as_of, with n the detector's persistence.
- Fast tags (F1-A), all 33: "out" is outside the band (edges inside) for PERSIST
  consecutive samples, decision 62's rule. high: every such run of samples is above;
  low: below; both: out otherwise (runs on both sides, or a run that crosses sides);
  normal: not out.
- Location (F3-A): the top group and the top TOP_TAGS tags by rbc.rank_at over the n
  triggering samples, from RBC / W ratios the caller computes (decision 65).
- Loops (F4-A), every loop in library/loops.yaml: saturated when its end valve sits at or
  below VALVE_LOW or at or above VALVE_HIGH % open for PERSIST consecutive samples
  (decision 58's positions); else lost when its measurement is out; else compensating
  when its end valve is out; else held. An analyzer-controlled loop judges its
  measurement on the held analyzer series.
- Masked flag: decision 62's plant rule over the window: no measurement or analyzer is
  out while at least one valve is. Analyzers are judged on their held series.
- Analyzers (F5-A), all 19: only values published after the notification and up to the
  diagnosis time count. Fewer than ANALYZER_MIN published: not_yet_available. Otherwise
  high (low) when ANALYZER_PERSIST consecutive published values are above (below) the
  band; normal if neither. If both sides qualify, the most recent run of values decides.
  Values count from when they were published, are held until the next one, and are never
  interpolated.

Analyzers come as {tag: [(sample, value), ...]}, the published values in time order
(1-based samples). A gap (NaN or inf) in the window is refused: it must never read as
normal.
"""

from dataclasses import dataclass

import numpy as np

from app.detector import loops as loops_mod
from app.detector import rbc

PERSIST = 3                     # decision 62: consecutive samples outside the band
ANALYZER_PERSIST = 2            # decision 68: consecutive published values outside the band
ANALYZER_MIN = 2                # fewer published since the notification: not yet available
TOP_TAGS = 3
VALVE_LOW, VALVE_HIGH = 2.0, 98.0   # % open (decision 58)
READINGS = {"provisional": 10, "revised": 20}     # samples after the notification


class FeatureError(ValueError):
    pass


@dataclass(frozen=True)
class Plant:
    """What the features need to know about the plant, from the agent-visible files."""
    fast_tags: tuple        # the 33 fast tags, in the order of the fast array's columns
    analyzers: tuple        # the 19 analyzer tags
    measurements: tuple     # fast tags that aren't valves
    valves: tuple
    loops: dict             # {loop id: (controlled tag, end valve tag)}


def plant_from_files(fast_tags, register=loops_mod.REGISTER, loops_file=loops_mod.LOOPS_FILE) -> Plant:
    import yaml
    from pathlib import Path
    rows = yaml.safe_load(Path(register).read_text())["tags"]
    kind = {r["tag"]: r["kind"] for r in rows}
    fast_tags = tuple(fast_tags)
    if sorted(fast_tags) != sorted(t for t, k in kind.items() if k in ("measurement", "valve")):
        raise FeatureError("fast_tags must be exactly the register's measurements and valves")
    loops = loops_mod.load(loops_file, register)
    return Plant(fast_tags=fast_tags,
                 analyzers=tuple(t for t, k in kind.items() if k == "analyzer"),
                 measurements=tuple(t for t in fast_tags if kind[t] == "measurement"),
                 valves=tuple(t for t in fast_tags if kind[t] == "valve"),
                 loops={i: (lp.controlled, loops_mod.end_valve(loops, i)) for i, lp in loops.items()})


# ---------- single values ----------

def _runs(mask):
    """(start, length) of each run of True in a 1-D boolean array."""
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i - start))
            start = None
    if start is not None:
        out.append((start, len(mask) - start))
    return out


def _finite(x, what):
    x = np.asarray(x, dtype=np.float64)
    if not np.isfinite(x).all():
        raise FeatureError(f"{what} holds NaN or inf in the window; a gap must never read as normal")
    return x


def tag_state(x, lo, hi, n=PERSIST) -> str:
    """high, low, both or normal for one tag's samples in the window."""
    x = _finite(x, "a tag")
    above, below = x > hi, x < lo
    out_runs = [r for r in _runs(above | below) if r[1] >= n]
    if not out_runs:
        return "normal"
    sides = set()
    for start, length in out_runs:
        seg = slice(start, start + length)
        if above[seg].all():
            sides.add("high")
        elif below[seg].all():
            sides.add("low")
        else:
            sides.add("both")                                 # the run crosses sides
    return sides.pop() if len(sides) == 1 else "both"


def is_out(x, lo, hi, n=PERSIST) -> bool:
    return tag_state(x, lo, hi, n) != "normal"


def analyzer_state(values, lo, hi, k=ANALYZER_PERSIST, minimum=ANALYZER_MIN) -> str:
    """high, low, normal or not_yet_available for the values published in the window,
    in time order."""
    v = _finite(values, "an analyzer") if len(values) else np.array([])
    if len(v) < minimum:
        return "not_yet_available"
    runs = [(s + length, side) for side, mask in (("high", v > hi), ("low", v < lo))
            for s, length in _runs(mask) if length >= k]
    if not runs:
        return "normal"
    return max(runs)[1]                                       # the most recent qualifying run


def saturated(valve, n=PERSIST) -> bool:
    v = _finite(valve, "a valve")
    return any(length >= n for _, length in _runs((v <= VALVE_LOW) | (v >= VALVE_HIGH)))


def loop_state(measurement, valve, meas_band, valve_band, n=PERSIST) -> str:
    if saturated(valve, n):
        return "saturated"
    if is_out(measurement, *meas_band, n):
        return "lost"
    if is_out(valve, *valve_band, n):
        return "compensating"
    return "held"


def held_series(publications, samples) -> np.ndarray:
    """The held value at each 1-based sample 1..samples: the latest value published at or
    before it, NaN before the first. Never interpolated."""
    out = np.full(samples, np.nan)
    last = 0
    for s, value in publications:
        if s < last:
            raise FeatureError("published values must be in time order")
        if 1 <= s <= samples:
            out[s - 1:] = value
        last = s
    return out


# ---------- readings ----------

def _window(t, n, as_of, length):
    if n < 1 or t - n + 1 < 1 or as_of < t or as_of > length:
        raise FeatureError(f"window {t - n + 1}..{as_of} isn't inside a run of {length} samples")
    return slice(t - n, as_of)


def location(group_ratios, tag_ratios, t, n, group_names, tags) -> dict:
    """The top group and top TOP_TAGS tags at the notification (decision 65)."""
    _, g = rbc.rank_at(group_ratios, t, n)
    _, k = rbc.rank_at(tag_ratios, t, n)
    return {"top_group": group_names[g[0]], "top_tags": [tags[i] for i in k[:TOP_TAGS]]}


def reading(plant, fast, analyzers, bands, t, n, as_of) -> dict:
    """One reading as of sample as_of. fast is samples x plant.fast_tags; analyzers is
    {tag: [(sample, value), ...]}; bands is {tag: (lo, hi)} for all 52 tags."""
    fast = np.asarray(fast, dtype=np.float64)
    w = _window(t, n, as_of, len(fast))
    col = {tag: j for j, tag in enumerate(plant.fast_tags)}
    series = {tag: fast[w, j] for tag, j in col.items()}
    for tag in plant.analyzers:
        series[tag] = held_series(analyzers.get(tag, []), as_of)[w]

    tags = {tag: tag_state(series[tag], *bands[tag]) for tag in plant.fast_tags}
    loops = {i: loop_state(series[m], series[v], bands[m], bands[v])
             for i, (m, v) in plant.loops.items()}
    held_out = any(is_out(series[tag], *bands[tag]) for tag in plant.measurements + plant.analyzers)
    valve_out = any(is_out(series[tag], *bands[tag]) for tag in plant.valves)
    after = {tag: [v for s, v in analyzers.get(tag, []) if t < s <= as_of] for tag in plant.analyzers}
    return {"tags": tags,
            "loops": loops,
            "analyzers": {tag: analyzer_state(after[tag], *bands[tag]) for tag in plant.analyzers},
            "masked": bool(valve_out and not held_out)}


def extract(plant, fast, analyzers, bands, t, n, group_ratios, tag_ratios, group_names) -> dict:
    """The location and both readings for a notification at sample t. A reading whose
    time is past the end of the data is left out (as of the provisional time, there's no
    revised reading yet)."""
    missing = [tag for tag in plant.fast_tags + plant.analyzers if tag not in bands]
    if missing:
        raise FeatureError(f"no evidence normals for {missing[:5]}")
    out = {"location": location(group_ratios, tag_ratios, t, n, group_names, list(plant.fast_tags))}
    for name, offset in READINGS.items():
        if t + offset <= len(fast):
            out[name] = reading(plant, fast, analyzers, bands, t, n, t + offset)
    return out