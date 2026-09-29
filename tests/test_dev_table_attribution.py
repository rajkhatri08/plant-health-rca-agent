"""eval/dev_table.py with --watch: right place and top tags (decisions 64, 65), on
synthetic runs (never data/). Calibrate static PCA, then Watch, then build the table.

Two faults are planted where the answer is known:
- fault 10 (feed temperature: stripper or feed) steps only the stripper's tags, so its
  top group is the stripper, which is right;
- fault 1 (feed composition: feed) steps only the condenser's tags, so its top group is
  the condenser, which is a miss. That's the honest result decision 65 asks for.
Every other fault uses dev_table's usual step on every fast tag.

Needs Raj's metrics.right_place; fails with NotImplementedError until it exists.
"""

import json
from collections import Counter

import numpy as np
import pytest

import dataset.loader as loader_mod
from app.detector import groups, rbc
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import dev_table as dt
from eval import metrics
from ingest import tags as tagmap
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)
from tests.test_dev_table import DEV, N_BOOT, SAMPLES, faulty_dev
from tests.test_dev_table import calibrated, with_alarms  # noqa: F401 (fixtures)
from tests.test_fit_pca import FAST, two_factor_runs

WGRID = (90.0, 95.0, 98.0, 99.0, 99.5, 99.9)
PLANTED = {10: "stripper", 1: "condenser"}
STEP = 6.0


def planted(normal, fault):
    """The normal dev runs with a step on one group's tags from sample 21."""
    table = groups.load(FAST)
    cols = tagmap.column_indices(VARIABLES, [FAST[i] for i in table[PLANTED[fault]]])
    runs = {k: v.copy() for k, v in normal.runs.items()}
    for k in runs:
        runs[k][20:, cols] += np.float32(STEP)
    return Runs(name="faulty_training", fault=fault, pool="dev", columns=VARIABLES, runs=runs)


@pytest.fixture
def attributed(setup, monkeypatch, tmp_path):
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    watch = tmp_path / "models" / "watch.json"
    cw.run(setup["model_path"], setup["out"], watch, repo_root=setup["repo"], q_grid=WGRID)
    normal = two_factor_runs(numbers=DEV, samples=SAMPLES, seed=11)
    calls = []

    def load_normal(pool):
        calls.append(("normal", pool))
        if pool != "dev":
            pytest.fail(f"dev table loaded normal pool {pool}")
        return normal

    def load_faulty(fault, pool):
        calls.append(("faulty", fault, pool))
        if pool != "dev" or fault not in range(1, 16):
            pytest.fail(f"dev table loaded fault {fault} from {pool}")
        return planted(normal, fault) if fault in PLANTED else faulty_dev(normal, fault)

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    return {**setup, "normal": normal, "calls": calls, "watch": watch,
            "tables": tmp_path / "tables", "load_faulty": load_faulty}


def build(c, **kw):
    return dt.run(c["out"], c["model_path"], watch=c["watch"], repo_root=c["repo"],
                  tables_dir=c["tables"], n_boot=N_BOOT, **kw)


def the_record(c):
    (path,) = (c["repo"] / "eval" / "runs").glob("*_dev_table_*.json")
    return path, json.loads(path.read_text())


def direct(c, fault):
    """Per detected run: (top group now, top group 30 min later, top tag), from rbc.py."""
    lim = json.loads(c["out"].read_text())
    doc = json.loads(c["watch"].read_text())
    model = c["model"]
    names = list(doc["groups"])
    table = groups.load(model.tags)
    w_g = np.array([doc["groups"][g]["w"] for g in names])
    w_t = np.array([doc["tags"][t] for t in model.tags])
    M = rbc.index_matrix(model, lim["t2_lim"], lim["spe_lim"])
    runs = c["load_faulty"](fault, "dev")
    cols = tagmap.column_indices(runs.columns, model.tags)
    scored = drv.score_runs(model, runs)
    tracks = drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], lim["warmup"])
    out = {}
    for k in sorted(runs.runs):
        d = metrics.detection(tracks[k], dt.ONSET, warmup=lim["warmup"])
        if not d.detected:
            continue
        X = runs.runs[k][:, cols]
        g = rbc.group_rbc(model, M, X, [table[n] for n in names]) / w_g
        t = rbc.tag_rbc(model, M, X) / w_t
        window = slice(d.sample - lim["n"], d.sample)
        later = slice(d.sample + 10 - lim["n"], d.sample + 10)
        out[k] = (names[int(np.argmax(g[window].mean(axis=0)))],
                  names[int(np.argmax(g[later].mean(axis=0)))],
                  model.tags[int(np.argmax(t[window].mean(axis=0)))])
    return out, names


# ---------- the family map ----------

def test_family_groups_are_decision_65():
    assert dt.FAMILY_GROUPS == {
        "feed composition": ("feed",), "feed supply": ("feed",),
        "feed temperature": ("stripper", "feed"), "reactor cooling": ("reactor",),
        "condenser cooling": ("condenser",), "reaction kinetics": ("reactor",)}
    assert set(dt.FAMILIES.values()) == set(dt.FAMILY_GROUPS)
    register_groups = set(groups.load(FAST))
    assert all(set(g) <= register_groups for g in dt.FAMILY_GROUPS.values())
    assert set(dt.FAMILIES) == set(dt.SUMMARY_FAULTS)          # 3, 9 and 15 have no family


# ---------- rows ----------

def test_planted_faults_right_and_wrong(attributed):
    results = build(attributed)
    right = results["faults"]["fault_10"]["attribution"]
    wrong = results["faults"]["fault_01"]["attribution"]
    assert right["top_group"] == "stripper" and wrong["top_group"] == "condenser"
    rp10, rp1 = right["right_place"], wrong["right_place"]
    assert rp10["of_detected"] > 0 and rp10["right"] == rp10["of_detected"]
    assert rp1["of_detected"] > 0 and rp1["right"] == 0 and rp1["rate"] == 0.0
    assert rp10["rate"] == pytest.approx(rp10["right"] / len(DEV))  # over all runs
    assert right["allowed_groups"] == ["stripper", "feed"]


@pytest.mark.parametrize("fault", [1, 5, 10, 13])
def test_rows_match_direct_rbc(attributed, fault):
    results = build(attributed)
    row = results["faults"][f"fault_{fault:02d}"]["attribution"]
    got, names = direct(attributed, fault)
    allowed = dt.FAMILY_GROUPS[dt.FAMILIES[fault]]
    assert row["detected"] == len(got) == row["right_place"]["of_detected"]
    assert row["right_place"]["right"] == sum(g in allowed for g, _, _ in got.values())
    assert row["right_place_30min"]["right"] == sum(g in allowed for _, g, _ in got.values())
    counts = Counter(t for _, _, t in got.values())
    assert row["top_tags"] == {t: counts[t] for t in row["top_tags"]}
    assert list(row["top_tags"].values()) == sorted(counts.values(), reverse=True)[:dt.TOP_TAGS]
    top = Counter(g for g, _, _ in got.values()).most_common(1)[0]
    assert row["top_group_share"] == pytest.approx(top[1] / len(got))


def test_excluded_faults_have_top_tags_but_no_right_place(attributed):
    results = build(attributed)
    for f in dt.EXCLUDED:
        a = results["faults"][f"fault_{f:02d}"]["attribution"]
        assert "right_place" not in a and "allowed_groups" not in a
        assert set(a) >= {"detected", "top_tags", "top_group", "top_group_share"}


def test_summary_is_the_equal_weight_mean(attributed):
    results = build(attributed)
    for key, label in (("summary", "right_place"), ("summary_30min", "right_place_30min")):
        rates = [results["faults"][f"fault_{f:02d}"]["attribution"][label]["rate"]
                 for f in dt.SUMMARY_FAULTS]
        s = results["right_place"][key]
        assert s["rate"] == pytest.approx(np.mean(rates))
        assert s["rate_ci95"][0] <= s["rate"] <= s["rate_ci95"][1]


# ---------- record and table ----------

def test_record_and_table(attributed):
    build(attributed)
    path, rec = the_record(attributed)
    at = rec["config"]["attribution"]
    assert at["watch_record"].endswith("_calibrate_watch.json")
    assert at["window"] == rec["config"]["n"] and at["secondary_offset"] == 10
    assert at["family_groups"]["feed temperature"] == ["stripper", "feed"]
    rel = path.relative_to(attributed["repo"]).as_posix()
    table = next(attributed["tables"].glob("*.md")).read_text()
    assert table == dt.render(rec, rel)
    assert "## Attribution at the notification" in table
    assert "of" in table and "detected" in table
    main, rest = table.split("## Attribution at the notification")
    attribution = rest.split("\n## ")[0]
    main10 = next(line for line in main.splitlines() if line.startswith("| 10 |"))
    attr10 = next(line for line in attribution.splitlines() if line.startswith("| 10 |"))
    assert "10 of 10 detected" in main10                      # right place beside "any"
    assert "stripper, feed" in attr10 and "stripper (1.00)" in attr10


def test_without_watch_right_place_stays_pending(attributed):
    dt.run(attributed["out"], attributed["model_path"], repo_root=attributed["repo"],
           tables_dir=attributed["tables"], n_boot=N_BOOT)
    _, rec = the_record(attributed)
    assert "attribution" not in rec["config"] and "right_place" not in rec["metrics"]
    assert all("attribution" not in r for r in rec["metrics"]["faults"].values())


# ---------- refusals ----------

def test_refuses_a_watch_file_for_other_limits(attributed):
    doc = json.loads(attributed["watch"].read_text())
    doc["p"] = 50.0
    attributed["watch"].write_text(json.dumps(doc))
    with pytest.raises(drv.CalibrationError):
        build(attributed)
    assert attributed["calls"] == []


def test_refuses_watch_for_an_alarm_row(with_alarms, tmp_path):
    stray = tmp_path / "watch.json"
    stray.write_text("{}")
    with pytest.raises(dt.DevTableError, match="alarm row"):
        dt.run(with_alarms["alarms"]["realistic"], None, row="grouped", watch=stray,
               repo_root=with_alarms["repo"], tables_dir=with_alarms["tables"], n_boot=N_BOOT)
    assert with_alarms["calls"] == []
