"""The random-forest baselines and the random floor (decision 72; PROTOCOL, Diagnosis:
Methods). Eval only: a comparator, never imported by app/, never shipped.

Forests:
- inputs: decision 68's features, one-hot. One forest per diagnosis time, scoring the
  same scope as the matcher (decision 69): location and provisional at "provisional",
  location, provisional and revised at "revised". A reading that's missing (past the
  end of the run) encodes as all zeros.
- the columns come from the plant (library/tags.yaml, library/loops.yaml) and decision
  68's vocabulary, never from the data, so every state has a column whether or not it
  was seen.
- forest-5 trains on the detected authoring runs; the ceiling forest on the detected
  forest_ceiling runs. Labels are entry_ids.
- HYPERPARAMS are fixed by decision 72, with SEED 20261002; nothing is tuned.
- Arrays only: a forest lives in memory for the run that fits it and is never saved
  (no pickles, no joblib). Its outputs are rankings and probabilities.
- ranking: classes grouped into tied blocks by equal probability, best first, each block
  ordered by entry_id (the same shape as the matcher's). A forest declines when its top
  probability is strictly below the threshold for that diagnosis time (set on dev in S7).
- leave-one-out: drop_classes removes the left-out entries' rows before fitting.

Random floor: the analytic chance values over the N entries in force, with no decline:
top-1 = 1/N, top-3 = min(3, N)/N, and family accuracy the mean over cases of (entries in
the case's family) / N.
"""

from fractions import Fraction
from pathlib import Path

import numpy as np
import yaml
from sklearn.ensemble import RandomForestClassifier

from app.detector import loops as loops_mod
from app.diagnosis import matcher
from app.library import schema

SEED = 20261002
HYPERPARAMS = {"n_estimators": 500, "max_features": "sqrt", "min_samples_leaf": 1,
               "class_weight": "balanced", "bootstrap": True, "random_state": SEED}
STATES = {"tags": schema.TAG_STATES, "loops": schema.LOOP_STATES, "analyzers": schema.ANALYZER_STATES}


class ForestError(ValueError):
    pass


def plant_vocabulary(register=loops_mod.REGISTER, loops_file=loops_mod.LOOPS_FILE) -> dict:
    """{"groups", "tags" (fast), "loops", "analyzers"}, in register and loop-map order."""
    rows = yaml.safe_load(Path(register).read_text())["tags"]
    return {"groups": list(dict.fromkeys(r["group"] for r in rows)),
            "tags": [r["tag"] for r in rows if r["kind"] in ("measurement", "valve")],
            "loops": list(loops_mod.load(loops_file, register)),
            "analyzers": [r["tag"] for r in rows if r["kind"] == "analyzer"]}


def columns(vocab, at) -> list:
    """The one-hot column names for diagnosis time at."""
    if at not in matcher.SCOPES:
        raise ForestError(f"at must be one of {tuple(matcher.SCOPES)}, got {at!r}")
    cols = [f"location.top_group={g}" for g in vocab["groups"]]
    cols += [f"location.top_tags~{t}" for t in vocab["tags"]]
    for reading in matcher.SCOPES[at][1:]:
        for kind, states in STATES.items():
            cols += [f"{reading}.{kind}.{key}={s}" for key in vocab[kind] for s in states]
        cols += [f"{reading}.masked=True", f"{reading}.masked=False"]
    return cols


def encode(feature_dicts, cols) -> np.ndarray:
    """cases x columns of 0/1 (uint8). Refuses a value with no column."""
    index = {c: j for j, c in enumerate(cols)}
    readings = sorted({c.split(".")[0] for c in cols} - {"location"})
    X = np.zeros((len(feature_dicts), len(cols)), dtype=np.uint8)

    def on(i, name):
        if name not in index:
            raise ForestError(f"no column for {name}")
        X[i, index[name]] = 1

    for i, f in enumerate(feature_dicts):
        on(i, f"location.top_group={f['location']['top_group']}")
        for t in f["location"]["top_tags"]:
            on(i, f"location.top_tags~{t}")
        for reading in readings:
            if reading not in f:
                continue                                    # missing reading: all zeros
            for kind in STATES:
                for key, state in f[reading][kind].items():
                    on(i, f"{reading}.{kind}.{key}={state}")
            on(i, f"{reading}.masked={bool(f[reading]['masked'])}")
    return X


def drop_classes(X, y, classes):
    """Leave-one-out: the rows whose label isn't in classes."""
    keep = ~np.isin(np.asarray(y), list(classes))
    return X[keep], np.asarray(y)[keep]


def fit(X, y) -> RandomForestClassifier:
    """A forest with decision 72's fixed hyperparameters and seed. Never saved."""
    y = np.asarray(y)
    if len(np.unique(y)) < 2:
        raise ForestError("a forest needs at least two classes")
    return RandomForestClassifier(**HYPERPARAMS).fit(X, y)


def rankings(model, X) -> list:
    """Per case, the classes as tied blocks by equal probability, best first, each block
    ordered by entry_id."""
    out = []
    for p in model.predict_proba(X):
        blocks = {}
        for cls, prob in zip(model.classes_, p):
            blocks.setdefault(float(prob), []).append(str(cls))
        out.append(tuple(tuple(sorted(blocks[prob])) for prob in sorted(blocks, reverse=True)))
    return out


def top_probability(model, X) -> np.ndarray:
    return model.predict_proba(X).max(axis=1)


def declines(model, X, threshold) -> np.ndarray:
    """True where the top probability is strictly below threshold."""
    return top_probability(model, X) < threshold


def random_floor(n_entries, case_family_sizes) -> dict:
    """The analytic random floor: {"top1", "top3", "family"} as exact fractions.
    case_family_sizes holds, per case, the number of entries in force in its family."""
    if n_entries < 1 or not case_family_sizes:
        raise ForestError("the random floor needs entries and cases")
    return {"top1": Fraction(1, n_entries),
            "top3": Fraction(min(3, n_entries), n_entries),
            "family": sum(Fraction(s, n_entries) for s in case_family_sizes) / len(case_family_sizes)}