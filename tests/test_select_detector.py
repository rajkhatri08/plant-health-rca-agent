"""eval/select_detector.py on fake calibrate_pca records in a throwaway git repo (never
the real eval/runs/). Decision 63: DPCA only if its selection score is more than 0.03
higher; otherwise static PCA stays."""

import json

import pytest

from eval import calibrate_driver as drv
from eval import select_detector as sd

OLD_GRID = {"first": 95.0, "last": 99.99, "points": 500}
NEW_GRID = {"first": 95.0, "last": 99.999, "points": 509}
DATA = {"manifest_sha256": "m" * 64, "splits_sha256": "s" * 64}


def calibration(repo, tmp_path, stamp, detector, score, *, lags=0, grid=NEW_GRID, dirty=False,
                data=DATA, **config):
    """A limits file and the calibrate_pca record that wrote it. Returns both paths."""
    limits = tmp_path / f"{detector}_{stamp}_limits.json"
    limits.write_text(json.dumps({"detector": detector, "stamp": stamp}))
    cfg = {"detector": detector, "warmup": 9, "lags": lags, "q_grid": grid,
           "budget_per_24h": 1.0, "selection_faults": [1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14],
           "selection_runs": 100, **config}
    rec = {"name": "calibrate_pca", "commit": "c" * 40, "dirty": dirty, "config": cfg, "data": data,
           "outputs": {"limits": {"path": str(limits), "sha256": sd.run_record.sha256(limits)}},
           "metrics": {"chosen": {"n": 3, "gap": 13, "q": 97.07, "score": score}}}
    path = repo / "eval" / "runs" / f"{stamp}_calibrate_pca.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec))
    return limits, path


def grid_check(repo, static_record, static_limits, *, unchanged=True, dirty=False,
               stamp="20260928T104704Z"):
    rec = {"name": "check_grid_refinement", "dirty": dirty,
           "config": {"calibration_record": static_record.relative_to(repo).as_posix(),
                      "limits_sha256": sd.run_record.sha256(static_limits)},
           "metrics": {"unchanged": unchanged}}
    path = repo / "eval" / "runs" / f"{stamp}_check_grid_refinement.json"
    path.write_text(json.dumps(rec))
    return path


@pytest.fixture
def pair(git_repo, tmp_path):
    """Session 8's situation: static on the old grid (0.975) with a passing grid check,
    DPCA on the new grid (0.9791666...)."""
    s_lim, s_rec = calibration(git_repo, tmp_path, "20260927T150527Z", "pca_static", 0.975,
                               grid=OLD_GRID)
    d_lim, d_rec = calibration(git_repo, tmp_path, "20260928T175708Z", "pca_dynamic",
                               0.9791666666666666, lags=1)
    g = grid_check(git_repo, s_rec, s_lim)
    return {"repo": git_repo, "tmp": tmp_path, "static": s_lim, "dynamic": d_lim,
            "static_record": s_rec, "dynamic_record": d_rec, "grid_record": g}


def select(p, **kw):
    return sd.run(p["static"], p["dynamic"], repo_root=p["repo"], **kw)


def the_record(p):
    (path,) = (p["repo"] / "eval" / "runs").glob("*_select_detector.json")
    return json.loads(path.read_text())


# ---------- the rule ----------

@pytest.mark.parametrize("static, dynamic, expected", [
    (0.975, 0.9791666666666666, "pca_static"),   # session 8: +0.004
    (0.5, 0.53, "pca_static"),                   # exactly 3 points (float gives 0.0300...03)
    (0.97, 1.0, "pca_static"),                   # exactly 3 points again (float: 0.0300...03)
    (0.9, 0.9308333333333333, "pca_dynamic"),    # 37/1200 above: the next possible score step
    (0.9, 0.8, "pca_static"),                    # DPCA worse
])
def test_verdict(static, dynamic, expected):
    assert sd.verdict(static, dynamic)[1] == expected


def test_margin_is_three_points():
    assert sd.MARGIN == 0.03 and sd.TOLERANCE < 1 / 1200 / 1000


# ---------- the whole selection ----------

def test_session_8_pair_keeps_static_and_writes_the_record(pair, capsys):
    chosen, diff = select(pair)
    assert chosen == "pca_static" and diff == pytest.approx(0.0041666666666666)
    rec = the_record(pair)
    assert rec["dirty"] is False
    assert rec["metrics"] == {"static_score": 0.975, "dynamic_score": 0.9791666666666666,
                              "difference": pytest.approx(diff), "dynamic_lags": 1,
                              "verdict": "pca_static"}
    cfg = rec["config"]
    assert cfg["rule"] == "decision 63" and cfg["margin"] == 0.03
    assert cfg["static_calibration_record"] == "eval/runs/20260927T150527Z_calibrate_pca.json"
    assert cfg["dynamic_calibration_record"] == "eval/runs/20260928T175708Z_calibrate_pca.json"
    assert cfg["grid_check_record"] == "eval/runs/20260928T104704Z_check_grid_refinement.json"
    assert cfg["static_limits_sha256"] == sd.run_record.sha256(pair["static"])
    out = capsys.readouterr().out
    assert "verdict (decision 63): pca_static" in out and "run record:" in out


def test_dpca_wins_above_the_margin(git_repo, tmp_path):
    s, _ = calibration(git_repo, tmp_path, "20260928T000001Z", "pca_static", 0.9)
    d, _ = calibration(git_repo, tmp_path, "20260928T000002Z", "pca_dynamic", 0.95, lags=1)
    assert sd.run(s, d, repo_root=git_repo)[0] == "pca_dynamic"
    assert len(list((git_repo / "eval" / "runs").glob("*_select_detector.json"))) == 1


def test_same_grid_needs_no_grid_check(git_repo, tmp_path):
    s, _ = calibration(git_repo, tmp_path, "20260928T000001Z", "pca_static", 0.975)
    d, _ = calibration(git_repo, tmp_path, "20260928T000002Z", "pca_dynamic", 0.98, lags=1)
    sd.run(s, d, repo_root=git_repo)
    assert json.loads(next((git_repo / "eval" / "runs").glob("*_select_detector.json")).read_text()
                      )["config"]["grid_check_record"] is None


# ---------- refusals ----------

@pytest.mark.parametrize("key, value", [
    ("selection_faults", [1, 2, 4]),
    ("selection_runs", 50),
    ("budget_per_24h", 2.0),
    ("warmup", 8),
])
def test_refuses_calibrations_that_differ(git_repo, tmp_path, key, value):
    s, _ = calibration(git_repo, tmp_path, "20260928T000001Z", "pca_static", 0.975)
    d, _ = calibration(git_repo, tmp_path, "20260928T000002Z", "pca_dynamic", 0.98, lags=1,
                       **{key: value})
    with pytest.raises(sd.SelectionError, match=key):
        sd.run(s, d, repo_root=git_repo)


def test_refuses_different_data(git_repo, tmp_path):
    s, _ = calibration(git_repo, tmp_path, "20260928T000001Z", "pca_static", 0.975)
    d, _ = calibration(git_repo, tmp_path, "20260928T000002Z", "pca_dynamic", 0.98, lags=1,
                       data={**DATA, "manifest_sha256": "x" * 64})
    with pytest.raises(sd.SelectionError, match="manifest"):
        sd.run(s, d, repo_root=git_repo)


def test_refuses_a_dirty_calibration(git_repo, tmp_path):
    s, _ = calibration(git_repo, tmp_path, "20260928T000001Z", "pca_static", 0.975)
    d, _ = calibration(git_repo, tmp_path, "20260928T000002Z", "pca_dynamic", 0.98, lags=1, dirty=True)
    with pytest.raises(sd.SelectionError, match="dirty"):
        sd.run(s, d, repo_root=git_repo)


def test_refuses_swapped_limits(pair):
    with pytest.raises(sd.SelectionError, match="expected pca_static"):
        sd.run(pair["dynamic"], pair["static"], repo_root=pair["repo"])


def test_refuses_limits_without_a_record(pair):
    stray = pair["tmp"] / "stray.json"
    stray.write_text("{}")
    with pytest.raises(drv.CalibrationError, match="expected one calibrate_pca record"):
        sd.run(pair["static"], stray, repo_root=pair["repo"])


def test_refuses_grid_mismatch_without_a_check(pair):
    pair["grid_record"].unlink()
    with pytest.raises(sd.SelectionError, match="0 check_grid_refinement"):
        select(pair)


@pytest.mark.parametrize("kw", [{"unchanged": False}, {"dirty": True}])
def test_refuses_a_failed_or_dirty_grid_check(pair, kw):
    grid_check(pair["repo"], pair["static_record"], pair["static"], **kw)   # overwrites
    with pytest.raises(sd.SelectionError, match="unchanged"):
        select(pair)


def test_ignores_a_grid_check_for_other_limits(pair):
    pair["grid_record"].unlink()
    other = pair["tmp"] / "other_limits.json"
    other.write_text("{}")
    grid_check(pair["repo"], pair["static_record"], other)  # same record, other limits file
    with pytest.raises(sd.SelectionError, match="0 check_grid_refinement"):
        select(pair)


def test_refuses_dirty_tree_before_reading(pair):
    (pair["repo"] / "code.py").write_text("x = 2\n")
    pair["static_record"].unlink()                          # would fail later if read
    with pytest.raises(sd.run_record.RunRecordError, match="dirty"):
        select(pair)
    assert not list((pair["repo"] / "eval" / "runs").glob("*_select_detector.json"))


def test_main_reports_errors(pair, capsys, monkeypatch):
    monkeypatch.setattr(sd.run_record, "REPO_ROOT", pair["repo"])
    pair["grid_record"].unlink()
    assert sd.main(["--static", str(pair["static"]), "--dynamic", str(pair["dynamic"])]) == 1
    assert "error:" in capsys.readouterr().err
