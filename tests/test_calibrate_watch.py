"""eval/calibrate_watch.py and check_dev's Watch reading on synthetic runs (never data/).
Calibrate static PCA with the driver first, then the Watch band.

These need Raj's watch_limit, watch_limits_at and watch_shares, and fail with
NotImplementedError until they exist.
"""

import json

import numpy as np
import pytest

import dataset.loader as loader_mod
from app.detector import groups, rbc
from eval import calibrate as cal
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import check_dev, run_record
from ingest import tags as tagmap
from tests.test_calibrate_driver import GAPS, GRID, dpca_setup, setup  # noqa: F401 (fixtures)
from tests.test_fit_pca import two_factor_runs

WGRID = (90.0, 95.0, 98.0, 99.0, 99.5, 99.9)


@pytest.fixture
def limits(setup):
    """setup with static limits calibrated (small grid), and the load log cleared."""
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    setup["calls"].clear()
    return {**setup, "watch": setup["out"].parent / "watch.json"}


def calibrate(c, **kw):
    return cw.run(c["model_path"], c["out"], c["watch"], repo_root=c["repo"], q_grid=WGRID, **kw)


def direct(c, runs):
    """Group and tag RBC per run, straight from rbc.py."""
    lim = json.loads(c["out"].read_text())
    model = c["model"]
    M = rbc.index_matrix(model, lim["t2_lim"], lim["spe_lim"])
    table = groups.load(model.tags)
    cols = tagmap.column_indices(runs.columns, model.tags)
    g, t = [], []
    for k in sorted(runs.runs):
        X = runs.runs[k][:, cols]
        g.append(rbc.group_rbc(model, M, X, list(table.values())))
        t.append(rbc.tag_rbc(model, M, X))
    return g, t, lim


def the_record(c, name="calibrate_watch"):
    (path,) = (c["repo"] / "eval" / "runs").glob(f"*_{name}.json")
    return json.loads(path.read_text())


# ---------- calibrate_watch ----------

def test_watch_file_matches_direct_calibration(limits):
    doc = calibrate(limits)
    g_runs, t_runs, lim = direct(limits, limits["calib"])
    p = cal.watch_limit(g_runs, lim["warmup"], q_grid=WGRID)
    assert doc["p"] == p and p is not None
    table = groups.load(limits["model"].tags)
    assert list(doc["groups"]) == list(table)
    assert [len(v["tags"]) for v in doc["groups"].values()] == [8, 6, 2, 7, 3, 7]
    assert [v["w"] for v in doc["groups"].values()] == pytest.approx(
        cal.watch_limits_at(g_runs, p, lim["warmup"]), rel=1e-12)
    assert list(doc["tags"]) == list(limits["model"].tags)
    assert list(doc["tags"].values()) == pytest.approx(cal.watch_limits_at(t_runs, p, lim["warmup"]), rel=1e-12)
    assert doc["model_sha256"] == lim["model_sha256"]
    assert doc["limits_sha256"] == run_record.sha256(limits["out"])
    assert json.loads(limits["watch"].read_text()) == doc


def test_record_holds_p_boundaries_and_shares(limits):
    doc = calibrate(limits)
    rec = the_record(limits)
    m, cfg = rec["metrics"], rec["config"]
    assert m["p"] == doc["p"] and m["at_floor"] == (doc["p"] == WGRID[0])
    assert m["w_group"] == {g: v["w"] for g, v in doc["groups"].items()}
    assert m["w_tag"] == doc["tags"]
    shares = m["calibration"]
    assert shares["any_group_share"] <= cal.WATCH_CAP
    assert shares["any_group_share"] >= max(shares["group_shares"].values())
    assert m["scored_samples"] == 20 * (120 - json.loads(limits["out"].read_text())["warmup"])
    assert cfg["cap"] == cal.WATCH_CAP and cfg["calibration_runs"] == 20
    assert cfg["calibration_record"].endswith("_calibrate_pca.json")
    assert rec["outputs"]["watch"]["sha256"] == run_record.sha256(limits["watch"])


def test_shares_match_the_boundaries(limits):
    doc = calibrate(limits)
    g_runs, _, lim = direct(limits, limits["calib"])
    w = np.array([v["w"] for v in doc["groups"].values()])
    any_share, per = cal.watch_shares(g_runs, w, lim["warmup"])
    rec = the_record(limits)["metrics"]["calibration"]
    assert rec["any_group_share"] == pytest.approx(any_share)
    assert list(rec["group_shares"].values()) == pytest.approx(per)


def test_loads_only_the_calibration_pool(limits):
    calibrate(limits)
    assert limits["calls"] == [("normal", "calibration")]


def test_no_grid_value_meets_the_cap(limits):
    with pytest.raises(drv.CalibrationError, match="decision 66"):
        calibrate(limits, cap=0.0)
    assert not limits["watch"].exists()


def test_refuses_existing_output_before_loading(limits):
    limits["watch"].write_text("{}")
    with pytest.raises(FileExistsError):
        calibrate(limits)
    assert limits["calls"] == []


def test_refuses_dirty_tree_before_loading(limits):
    (limits["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        calibrate(limits)
    assert limits["calls"] == []


def test_refuses_limits_without_a_record(limits):
    lim = json.loads(limits["out"].read_text())
    lim["q"] = 50.0
    limits["out"].write_text(json.dumps(lim))
    with pytest.raises(drv.CalibrationError):
        calibrate(limits)
    assert limits["calls"] == []


def test_refuses_another_model(limits, tmp_path):
    other = tmp_path / "other.npz"
    other.write_bytes(limits["model_path"].read_bytes() + b"x")
    with pytest.raises(drv.CalibrationError, match="isn't the model"):
        cw.run(other, limits["out"], limits["watch"], repo_root=limits["repo"], q_grid=WGRID)
    assert limits["calls"] == []


def test_refuses_dpca_limits(dpca_setup):
    drv.run(dpca_setup["model_path"], dpca_setup["out"], repo_root=dpca_setup["repo"], q_grid=GRID,
            gap_range=GAPS)
    dpca_setup["calls"].clear()
    with pytest.raises(drv.CalibrationError, match="DPCA"):
        cw.run(dpca_setup["model_path"], dpca_setup["out"], dpca_setup["out"].parent / "w.json",
               repo_root=dpca_setup["repo"], q_grid=WGRID)
    assert dpca_setup["calls"] == []


def test_main_reports_errors(limits, capsys, monkeypatch):
    monkeypatch.setattr(run_record, "REPO_ROOT", limits["repo"])
    limits["watch"].write_text("{}")
    assert cw.main(["--model", str(limits["model_path"]), "--limits", str(limits["out"]),
                    "--out", str(limits["watch"])]) == 1
    assert "error:" in capsys.readouterr().err


# ---------- check_dev --watch ----------

@pytest.fixture
def watched(limits, monkeypatch):
    """Watch calibrated, then loaders that serve only normal dev."""
    calibrate(limits)
    dev = two_factor_runs(numbers=range(101, 111), samples=120, seed=11)
    calls = []

    def load_normal(pool):
        calls.append(pool)
        if pool != "dev":
            pytest.fail(f"dev check loaded normal pool {pool}")
        return dev

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", lambda *a: pytest.fail("dev check loaded faulty runs"))
    return {**limits, "dev": dev, "dev_calls": calls}


def check(c, **kw):
    return check_dev.run(c["out"], c["model_path"], repo_root=c["repo"], n_boot=50, **kw)


def test_dev_watch_shares_match_direct(watched):
    check(watched, watch_path=watched["watch"])
    doc = json.loads(watched["watch"].read_text())
    g_runs, _, lim = direct(watched, watched["dev"])
    any_share, per = cal.watch_shares(g_runs, np.array([v["w"] for v in doc["groups"].values()]),
                                      lim["warmup"])
    rec = the_record(watched, "dev_false_alerts")
    w = rec["metrics"]["watch"]
    assert w["p"] == doc["p"] and w["cap"] == cal.WATCH_CAP
    assert w["any_group_share"] == pytest.approx(any_share)
    assert list(w["group_shares"]) == list(doc["groups"])
    assert list(w["group_shares"].values()) == pytest.approx(per)
    assert rec["config"]["watch_record"].endswith("_calibrate_watch.json")
    assert rec["config"]["watch_sha256"] == run_record.sha256(watched["watch"])
    assert watched["dev_calls"] == ["dev"]                       # dev loaded once


def test_dev_without_watch_is_unchanged(watched):
    check(watched)
    rec = the_record(watched, "dev_false_alerts")
    assert "watch" not in rec["metrics"] and "watch_record" not in rec["config"]


def test_dev_refuses_a_watch_file_without_a_record(watched):
    doc = json.loads(watched["watch"].read_text())
    doc["p"] = 50.0
    watched["watch"].write_text(json.dumps(doc))
    with pytest.raises(drv.CalibrationError, match="calibrate_watch"):
        check(watched, watch_path=watched["watch"])
    assert watched["dev_calls"] == []


def test_dev_refuses_a_watch_file_with_other_groups(watched):
    # A recorded watch file whose groups don't match the register for this model.
    doc = json.loads(watched["watch"].read_text())
    doc["groups"] = dict(reversed(list(doc["groups"].items())))
    watched["watch"].write_text(json.dumps(doc))
    runs = watched["repo"] / "eval" / "runs"
    (path,) = runs.glob("*_calibrate_watch.json")
    rec = json.loads(path.read_text())
    rec["outputs"]["watch"]["sha256"] = run_record.sha256(watched["watch"])
    path.write_text(json.dumps(rec))
    with pytest.raises(drv.CalibrationError, match="groups"):
        check(watched, watch_path=watched["watch"])
    assert watched["dev_calls"] == []