"""eval/check_grid_refinement.py on synthetic runs: calibrate with the driver on a small
grid first, then check "new points" above that grid's top."""

import json

import pytest

import dataset.loader as loader_mod
from app.detector import alerting
from eval import calibrate as cal
from eval import calibrate_driver as drv
from eval import check_grid_refinement as cgr
from eval import run_record
from tests.test_calibrate_driver import GAPS, GRID, WARMUP, setup  # noqa: F401 (fixture)

NEW = (99.95, 99.99, 99.999)                 # above the test grid's top (99.9)


# ---------- the shortcut rule ----------

@pytest.mark.parametrize("old_q, top_q, expected", [
    (95.57, 99.991, 95.57),      # all new points pass: the scan continues to the old answer
    (None, 99.991, 99.991),      # the old top failed, every new point passes: stops at 99.991
    (95.57, 99.995, 99.995),     # 99.994 fails: the scan stops above it
    (95.57, None, None),         # 99.999 already fails: ineligible
    (None, None, None),
])
def test_new_stable_q(old_q, top_q, expected):
    assert cgr.new_stable_q(old_q, top_q, cgr.NEW_POINTS) == expected


def test_new_points_are_the_nine_finer_ones():
    assert cgr.NEW_POINTS == (99.991, 99.992, 99.993, 99.994, 99.995, 99.996, 99.997, 99.998, 99.999)


# ---------- the whole check ----------

@pytest.fixture
def calibrated(setup, monkeypatch):
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    calls = []

    def load_normal(pool):
        calls.append(pool)
        if pool != "calibration":
            pytest.fail(f"grid check loaded normal pool {pool}")
        return setup["calib"]

    monkeypatch.setattr(loader_mod, "load_normal", load_normal)
    monkeypatch.setattr(loader_mod, "load_faulty", lambda *a: pytest.fail("grid check loaded faulty runs"))
    return {**setup, "calls": calls}


def check(c, **kw):
    return cgr.run(c["out"], c["model_path"], repo_root=c["repo"], new_points=NEW, **kw)


@pytest.mark.parametrize("loosen", [None, 0.3])
def test_matches_a_direct_scan_of_the_extended_grid(calibrated, monkeypatch, loosen):
    # The shortcut must give exactly what lowest_stable_q gives on old grid + new points.
    # With loosen, the limits at 99.99 and above are scaled down, so some settings fail
    # there and the scan has to stop inside the new points (the other branch of the rule).
    # The old grid (up to 99.9) is untouched, so the recorded old answers still hold.
    if loosen:
        real = cal.limits_at
        monkeypatch.setattr(cal, "limits_at", lambda t2, spe, q, w: tuple(
            x * (loosen if q >= 99.99 else 1) for x in real(t2, spe, q, w)))
    _, settings = check(calibrated)
    if loosen:
        assert any(s["new_q"] != s["old_q"] for s in settings.values())
    scored = drv.score_runs(calibrated["model"], calibrated["calib"])
    t2 = [scored[k][0] for k in sorted(scored)]
    spe = [scored[k][1] for k in sorted(scored)]

    def ratio_runs_at(q):
        lim = cal.limits_at(t2, spe, q, WARMUP)
        return {k: alerting.plant_ratio(a, b, *lim) for k, (a, b) in scored.items()}

    for key, row in settings.items():
        n, gap = (int(x) for x in key[1:].split("_g"))
        assert row["new_q"] == cal.lowest_stable_q(ratio_runs_at, n, gap, WARMUP, 0, GRID + NEW)


def test_record_and_verdict(calibrated):
    unchanged, settings = check(calibrated)
    (path,) = (calibrated["repo"] / "eval" / "runs").glob("*_check_grid_refinement.json")
    rec = json.loads(path.read_text())
    changed = [k for k, s in settings.items() if s["new_q"] != s["old_q"]]
    assert unchanged == (not changed) == rec["metrics"]["unchanged"]
    assert rec["metrics"]["changed"] == len(changed)
    assert rec["metrics"]["settings_checked"] == len(settings) == len(list(cal.n_range(0, WARMUP))) * len(GAPS)
    assert rec["config"]["new_points"] == list(NEW)
    assert rec["config"]["calibration_record"].endswith("_calibrate_pca.json")


def test_a_failing_new_point_is_reported_and_exits_1(calibrated, monkeypatch):
    monkeypatch.setattr(cal, "lowest_stable_q", lambda *a, **k: None)   # 99.999 fails everywhere
    unchanged, settings = check(calibrated)
    assert not unchanged
    assert all(s["new_q"] is None for s in settings.values())
    for p in (calibrated["repo"] / "eval" / "runs").glob("*_check_grid_refinement.json"):
        p.unlink()                                  # two runs in one second share a name
    monkeypatch.setattr(cgr, "run", lambda *a, **k: (False, {}))
    assert cgr.main([]) == 1


def test_loads_only_the_calibration_pool(calibrated):
    check(calibrated)
    assert calibrated["calls"] == ["calibration"]


def test_refuses_dirty_tree_before_loading(calibrated):
    (calibrated["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        check(calibrated)
    assert calibrated["calls"] == []


def test_refuses_a_different_model(calibrated, tmp_path):
    other = tmp_path / "other.npz"
    other.write_bytes(calibrated["model_path"].read_bytes() + b"x")
    with pytest.raises(drv.CalibrationError):
        cgr.run(calibrated["out"], other, repo_root=calibrated["repo"], new_points=NEW)
    assert calibrated["calls"] == []