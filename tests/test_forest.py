"""eval/baselines/forest.py: decision 72's forests and the analytic random floor, on
synthetic cases over the real tag register and loop map."""

from fractions import Fraction as F
from pathlib import Path

import numpy as np
import pytest

from app.library import schema
from eval.baselines import forest as fo

REPO = Path(__file__).resolve().parents[1]
VOCAB = fo.plant_vocabulary()


def case(fv206="normal", group="reactor", top=("RX-FV-206", "RX-TI-204", "RX-TI-205"), revised=True, masked=False):
    """A full feature dict: every fast tag, loop and analyzer present, as features.extract gives."""
    def reading():
        tags = {t: "normal" for t in VOCAB["tags"]}
        tags["RX-FV-206"] = fv206
        return {"tags": tags, "loops": {lp: "held" for lp in VOCAB["loops"]},
                "analyzers": {a: "not_yet_available" for a in VOCAB["analyzers"]}, "masked": masked}
    f = {"location": {"top_group": group, "top_tags": list(top)}, "provisional": reading()}
    if revised:
        f["revised"] = reading()
    return f


# ---------- decision 72's fixed settings ----------

def test_hyperparameters_and_seed_are_decision_72():
    assert fo.SEED == 20261002
    assert fo.HYPERPARAMS == {"n_estimators": 500, "max_features": "sqrt", "min_samples_leaf": 1,
                              "class_weight": "balanced", "bootstrap": True, "random_state": 20261002}


def test_no_pickles_and_nothing_saved():
    src = (REPO / "eval" / "baselines" / "forest.py").read_text()
    code = src.split('"""', 2)[2]                       # past the module docstring
    for word in ("pickle", "joblib", "dump(", ".save(", "open(", "write_"):
        assert word not in code, word


def test_scikit_learn_is_pinned_for_eval_only():
    full = (REPO / "requirements.txt").read_text()
    app = (REPO / "requirements-app.txt").read_text()
    assert "scikit-learn==1.9.1" in full and "scikit-learn" not in app


# ---------- columns from the plant, not the data ----------

def test_vocabulary_is_the_register_and_loop_map():
    assert len(VOCAB["tags"]) == 33 and len(VOCAB["analyzers"]) == 19 and len(VOCAB["loops"]) == 19
    assert "reactor" in VOCAB["groups"] and "stripper" in VOCAB["groups"]


def test_columns_follow_the_matchers_scope():
    g, t = len(VOCAB["groups"]), len(VOCAB["tags"])
    per_reading = t * len(schema.TAG_STATES) + 19 * len(schema.LOOP_STATES) + 19 * len(schema.ANALYZER_STATES) + 2
    prov, rev = fo.columns(VOCAB, "provisional"), fo.columns(VOCAB, "revised")
    assert len(prov) == g + t + per_reading and len(rev) == g + t + 2 * per_reading
    assert not any(c.startswith("revised.") for c in prov)
    assert len(set(rev)) == len(rev)
    with pytest.raises(fo.ForestError):
        fo.columns(VOCAB, "final")


def test_encode_one_hot():
    cols = fo.columns(VOCAB, "revised")
    X = fo.encode([case(fv206="high")], cols)
    on = {c for c, v in zip(cols, X[0]) if v}
    assert X.dtype == np.uint8
    assert "location.top_group=reactor" in on and "location.top_tags~RX-TI-205" in on
    assert "provisional.tags.RX-FV-206=high" in on and "provisional.tags.RX-FV-206=normal" not in on
    assert "revised.masked=False" in on
    # one state per tag, loop and analyzer, per reading; one group; three top tags
    assert X.sum() == 1 + 3 + 2 * (33 + 19 + 19 + 1)


def test_missing_reading_is_all_zeros():
    cols = fo.columns(VOCAB, "revised")
    X = fo.encode([case(revised=False)], cols)
    assert not any(v for c, v in zip(cols, X[0]) if c.startswith("revised."))


def test_provisional_columns_ignore_the_revised_reading():
    cols = fo.columns(VOCAB, "provisional")
    assert (fo.encode([case(revised=True)], cols) == fo.encode([case(revised=False)], cols)).all()


def test_encode_refuses_a_value_with_no_column():
    bad = case()
    bad["provisional"]["tags"]["RX-FV-206"] = "sideways"
    with pytest.raises(fo.ForestError):
        fo.encode([bad], fo.columns(VOCAB, "provisional"))
    with pytest.raises(fo.ForestError):
        fo.encode([case(group="nowhere")], fo.columns(VOCAB, "provisional"))


# ---------- fit, rank, decline ----------

def train():
    cols = fo.columns(VOCAB, "provisional")
    feats = [case(fv206="high")] * 6 + [case(fv206="low")] * 6 + [case(fv206="both", masked=True)] * 6
    y = ["warm"] * 6 + ["cold"] * 6 + ["stick"] * 6
    return cols, fo.encode(feats, cols), np.array(y)


def test_fit_is_deterministic_with_the_seed():
    cols, X, y = train()
    a, b = fo.fit(X, y), fo.fit(X, y)
    assert a.n_estimators == 500 and a.random_state == fo.SEED
    assert np.array_equal(a.predict_proba(X), b.predict_proba(X))


def test_rankings_put_the_right_class_first_and_group_ties():
    cols, X, y = train()
    model = fo.fit(X, y)
    r = fo.rankings(model, fo.encode([case(fv206="high"), case(fv206="low")], cols))
    assert r[0][0] == ("warm",) and r[1][0] == ("cold",)
    assert sorted(e for block in r[0] for e in block) == ["cold", "stick", "warm"]
    probs = model.predict_proba(fo.encode([case(fv206="high")], cols))[0]
    assert len(r[0]) == len(set(probs.tolist()))        # one block per distinct probability


def test_declines_strictly_below_the_threshold():
    cols, X, y = train()
    model = fo.fit(X, y)
    x = fo.encode([case(fv206="high")], cols)
    top = fo.top_probability(model, x)[0]
    assert not fo.declines(model, x, top)[0]             # equal isn't below
    assert fo.declines(model, x, top + 1e-9)[0]


def test_drop_classes_for_leave_one_out():
    cols, X, y = train()
    X2, y2 = fo.drop_classes(X, y, ["cold"])
    assert len(X2) == 12 and set(y2) == {"warm", "stick"}
    assert "cold" not in fo.fit(X2, y2).classes_


def test_fit_needs_two_classes():
    cols, X, y = train()
    with pytest.raises(fo.ForestError):
        fo.fit(X[:6], y[:6])


# ---------- random floor ----------

def test_random_floor_is_analytic():
    # 12 entries; families of 3, 2 and 1 entries
    got = fo.random_floor(12, [3, 3, 2, 1])
    assert got == {"top1": F(1, 12), "top3": F(3, 12), "family": (F(3, 12) * 2 + F(2, 12) + F(1, 12)) / 4}
    assert fo.random_floor(2, [1])["top3"] == 1
    with pytest.raises(fo.ForestError):
        fo.random_floor(12, [])