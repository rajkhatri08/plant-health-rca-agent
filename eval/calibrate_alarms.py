"""Calibrate the conventional-alarm baseline to the false-alert budget (decisions 54, 58).

    python -m eval.calibrate_alarms --list realistic|every [--out PATH] [--allow-dirty]

Steps:
1. Build the list's alarm points from library/tags.yaml (decision 58):
   - realistic: high and low alarms on measurements and analyzers, plus valve-at-limit
   - every: high and low alarms on all 52 tags, no valve-at-limit
2. Calibration pool: σ per high/low tag once. For each q the search asks for, the limits
   (eval.baselines.alarms.tag_limits), every run's latched points, and for every n the
   OR of the on-delayed points (plant_track with G = 0). Those are cached as packed bits,
   because only the off-delay depends on G.
3. For every (n, G): calibrate.lowest_stable_q, with a track builder that reads the cache
   and applies alerting.group for G. The same grid, rule and ranges as decision 54.
4. Selection runs (dataset/selection.yaml) of the selection faults: every eligible
   setting's mean detection rate at its q.
5. Grouped row: calibrate.choose over every (n, G). Ungrouped row: calibrate.choose
   over the G = 0 settings only. Write the limits file and a calibrate_alarms_<list>
   run record with every setting's q, score, floor flag and budget share (decision 55).

Never loads dev (normal or faulty). Refuses a dirty tree unless --allow-dirty. Prints
only counts, the chosen settings and the paths.
"""

import argparse
import functools
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.detector import alerting
from dataset import loader, selection
from eval import calibrate as cal
from eval import metrics, run_record
from eval.baselines import alarms as al
from ingest import tags as tagmap

WARMUP = 9                                  # decision 52
LAGS = 0                                    # alarms look at single samples
LISTS = ("realistic", "every")
MODELS_DIR = run_record.REPO_ROOT / "data" / "models"


class AlarmCalibrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlarmList:
    name: str
    hl_tags: tuple          # tags with high and low alarms, register order
    hl_types: tuple         # their signal types (for the deadband)
    hl_analyzer: tuple      # True for analyzers (fixed on-delay)
    valve_tags: tuple       # valves with a valve-at-limit alarm

    def on_delays(self, n):
        """One on-delay per alarm point, in point order: highs, lows, valves."""
        hl = [al.ANALYZER_ON_DELAY if a else n for a in self.hl_analyzer]
        return hl + hl + [n] * len(self.valve_tags)


def alarm_list(name, repo_root=None) -> AlarmList:
    rows = tagmap.register(repo_root)
    if name == "realistic":
        hl = [r for r in rows if r["kind"] in ("measurement", "analyzer")]
        valves = [r["tag"] for r in rows if r["kind"] == "valve"]
    elif name == "every":
        hl, valves = list(rows), []
    else:
        raise AlarmCalibrationError(f"unknown alarm list {name!r}; one of {LISTS}")
    missing = sorted({r["signal_type"] for r in hl} - set(al.DEADBAND_SIGMA))
    if missing:
        raise AlarmCalibrationError(f"no agreed deadband for signal types {missing}")
    return AlarmList(name, tuple(r["tag"] for r in hl), tuple(r["signal_type"] for r in hl),
                     tuple(r["kind"] == "analyzer" for r in hl), tuple(valves))


class Pool:
    """One pool's runs cut to the list's columns, with base tracks cached per (q, n).

    A base track is the OR of the on-delayed points with the warm-up off (plant_track
    with G = 0); alerting.group then applies any G, which gives exactly
    plant_track(points, on-delays, G, warmup)."""

    def __init__(self, runs, alist, limits, band, warmup, all_n=(), numbers=None):
        hl_cols = tagmap.column_indices(runs.columns, alist.hl_tags)
        v_cols = tagmap.column_indices(runs.columns, alist.valve_tags) if alist.valve_tags else []
        self.alist, self.limits, self.band, self.warmup = alist, limits, band, warmup
        self.numbers = sorted(runs.runs) if numbers is None else list(numbers)
        missing = [k for k in self.numbers if k not in runs.runs]
        if missing:
            raise AlarmCalibrationError(f"run numbers {missing[:5]} aren't in {runs.pool} "
                                        f"for fault {runs.fault}")
        self.hl = {k: runs.runs[k][:, hl_cols] for k in self.numbers}
        self.at_limit = {k: al.at_limit(runs.runs[k][:, v_cols]) if v_cols else None
                         for k in self.numbers}            # q doesn't move these
        self.length = {k: len(runs.runs[k]) for k in self.numbers}
        self.all_n = tuple(all_n)       # n values to build together whenever q is new
        self.cache = {}                 # (q, n) -> {run number: packed bits}
        self._points_q, self._points = None, None

    def _points_at(self, q):
        if self._points_q != q:
            lo, hi = self.limits(q)
            pts = {}
            for k in self.numbers:
                high, low = al.hysteresis(self.hl[k], lo, hi, self.band)
                parts = [high, low] + ([self.at_limit[k]] if self.at_limit[k] is not None else [])
                pts[k] = np.hstack(parts)
            self._points_q, self._points = q, pts
        return self._points

    def base(self, q, n):
        if (q, n) not in self.cache:
            pts = self._points_at(q)
            for m in {n, *self.all_n}:
                if (q, m) not in self.cache:
                    ns = self.alist.on_delays(m)
                    self.cache[(q, m)] = {k: np.packbits(al.plant_track(p, ns, 0, self.warmup).astype(bool))
                                          for k, p in pts.items()}
        return self.cache[(q, n)]

    def track(self, q, k, n, gap):
        held = np.unpackbits(self.base(q, n)[k], count=self.length[k]).astype(bool)
        return alerting.group(held, gap, self.warmup).astype(int)

    def tracks(self, q, n, gap):
        return [self.track(q, k, n, gap) for k in self.numbers]


def run(list_name, out=None, *, allow_dirty=False, repo_root=None, warmup=WARMUP,
        q_grid=cal.Q_GRID, gap_range=cal.GAP_RANGE):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    alist = alarm_list(list_name)             # the register is repo content, not a run input
    detector = f"alarms_{list_name}"
    out = Path(out or MODELS_DIR / f"{detector}_limits.json")
    if out.exists():
        raise FileExistsError(f"{out} already exists; delete it to recalibrate")
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    chosen_selection = selection.load(repo_root)
    n_values = tuple(cal.n_range(LAGS, warmup))

    # 2. Calibration pool: σ and limits from its scored samples only.
    calib = loader.load_normal("calibration")
    hl_cols = tagmap.column_indices(calib.columns, alist.hl_tags)
    cal_hl = [calib.runs[k][:, hl_cols] for k in sorted(calib.runs)]
    sigma = al.tag_spread(cal_hl, warmup)
    band = np.array([al.DEADBAND_SIGMA[t] for t in alist.hl_types]) * sigma
    limits = functools.cache(lambda q: al.tag_limits(cal_hl, q, warmup))
    cal_pool = Pool(calib, alist, limits, band, warmup, all_n=n_values)
    del calib                                  # the pool keeps its own column slices

    # 3. The search, through lowest_stable_q's track builder.
    def ratio_runs_at(q):
        return {k: (q, k) for k in cal_pool.numbers}

    def build(value, n, gap, warmup_, lags):
        q, k = value
        return cal_pool.track(q, k, n, gap)

    def budget(q, n, gap):
        runs = [metrics.ScoredRun(0, k, t) for k, t in zip(cal_pool.numbers, cal_pool.tracks(q, n, gap))]
        return metrics.false_alerts_per_24h(runs, warmup)

    settings = {(n, gap): cal.lowest_stable_q(ratio_runs_at, n, gap, warmup, LAGS, q_grid, track=build)
                for n in n_values for gap in gap_range}

    # 4. Selection runs, one pool per fault, each setting scored at its own q.
    sel_pools = {f: Pool(loader.load_faulty(f, "forest_ceiling"), alist, limits, band, warmup,
                         numbers=chosen_selection["numbers"])
                 for f in cal.SELECTION_FAULTS}

    def fault_tracks(q, n, gap):
        return {f: p.tracks(q, n, gap) for f, p in sel_pools.items()}

    candidates, table = {}, {}
    for (n, gap), q in sorted(settings.items(), key=lambda s: (s[1] is None, s[1] or 0)):
        row = {"q": q, "score": None, "at_floor": None, "budget_share": None}
        if q is not None:                      # sorted by q, so each q's points build once
            score = cal.selection_score(fault_tracks(q, n, gap), warmup)
            candidates[(n, gap)] = (q, score)
            row.update(score=score, at_floor=q == q_grid[0],
                       budget_share=budget(q, n, gap)[2] / cal.BUDGET_PER_24H)
        else:
            candidates[(n, gap)] = (None, 0.0)
        table[f"n{n}_g{gap}"] = row

    # 5. Grouped row over every setting; ungrouped over G = 0 only.
    rows, doc_rows = {}, {}
    for label, cands in (("grouped", candidates),
                         ("ungrouped", {s: v for s, v in candidates.items() if s[1] == 0})):
        n, gap, q = cal.choose(cands)
        lo, hi = limits(q)
        count, hours, per_24h = budget(q, n, gap)
        rates = {f"fault_{f:02d}": sum(metrics.detection(t, metrics.TRAIN_ONSET, warmup=warmup).detected
                                       for t in ts) / len(ts)
                 for f, ts in fault_tracks(q, n, gap).items()}
        rows[label] = {"n": n, "gap": gap, "q": q, "score": cands[(n, gap)][1],
                       "at_floor": q == q_grid[0],
                       "calibration": {"notifications": count, "hours": hours, "per_24h": per_24h,
                                       "budget_share": per_24h / cal.BUDGET_PER_24H},
                       "selection_rates": rates}
        doc_rows[label] = {"n": n, "gap": gap, "q": q, "lo": lo.tolist(), "hi": hi.tolist()}

    doc = {"detector": detector, "list": list_name, "warmup": warmup, "lags": LAGS,
           "hl_tags": list(alist.hl_tags), "hl_types": list(alist.hl_types),
           "hl_analyzer": list(alist.hl_analyzer), "valve_tags": list(alist.valve_tags),
           "valve_low": al.VALVE_LOW, "valve_high": al.VALVE_HIGH,
           "analyzer_on_delay": al.ANALYZER_ON_DELAY,
           "sigma": sigma.tolist(), "band": band.tolist(), **doc_rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    record = run_record.write(
        f"calibrate_{detector}",
        config={"detector": detector, "list": list_name, "warmup": warmup, "lags": LAGS,
                "hl_tags": len(alist.hl_tags), "analyzers": sum(alist.hl_analyzer),
                "valve_at_limit": len(alist.valve_tags),
                "deadband_sigma": dict(al.DEADBAND_SIGMA),
                "valve_limits": [al.VALVE_LOW, al.VALVE_HIGH],
                "analyzer_on_delay": al.ANALYZER_ON_DELAY,
                "q_grid": {"first": q_grid[0], "last": q_grid[-1], "points": len(q_grid)},
                "n_range": list(n_values), "gap_range": list(gap_range),
                "budget_per_24h": cal.BUDGET_PER_24H,
                "selection_faults": list(cal.SELECTION_FAULTS),
                "selection_runs": len(chosen_selection["numbers"]),
                "calibration_runs": len(cal_pool.numbers)},
        seeds={"selection": chosen_selection["seed"]},
        metrics={**rows,
                 "eligible_settings": sum(q is not None for q in settings.values()),
                 "settings": table},
        outputs={"limits": out}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"{detector}: {len(alist.hl_tags)} high/low tags ({sum(alist.hl_analyzer)} analyzers), "
          f"{len(alist.valve_tags)} valve-at-limit; calibration {len(cal_pool.numbers)} runs")
    print(f"eligible settings: {sum(q is not None for q in settings.values())} of {len(settings)}")
    for label, r in rows.items():
        print(f"{label}: n = {r['n']}, G = {r['gap']}, q = {r['q']}"
              f"{' (grid floor)' if r['at_floor'] else ''}, score {r['score']:.4f}")
    print(f"saved {out}\nrun record: {record}")
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list", required=True, choices=LISTS)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.list, args.out, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError,
            run_record.RunRecordError, selection.SelectionError, AlarmCalibrationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())