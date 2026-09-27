"""eval/run_record.py, on a throwaway git repo (never the real eval/runs/)."""

import hashlib
import json
import math
from datetime import datetime, timezone

import numpy as np
import pytest

from eval import run_record as rr

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def write(repo, **overrides):
    commit, dirty = rr.check_clean(repo)
    out = repo.parent / "model.npz"
    out.write_bytes(b"model bytes")
    kwargs = dict(config={"warmup": 9}, seeds={"pa": 1}, metrics={"k": 3},
                  outputs={"model": out}, commit=commit, dirty=dirty, repo_root=repo, now=NOW)
    kwargs.update(overrides)
    return rr.write("fit_pca", **kwargs)


def test_record_holds_commit_checksums_and_metrics(git_repo):
    path = write(git_repo, metrics={"k": np.int64(3), "share": np.float64(0.5), "ok": True,
                                    "eig": np.array([2.0, 1.0])})
    assert path == git_repo / "eval" / "runs" / "20260927T120000Z_fit_pca.json"
    rec = json.loads(path.read_text())
    assert len(rec["commit"]) == 40 and rec["dirty"] is False
    assert rec["config"] == {"warmup": 9} and rec["seeds"] == {"pa": 1}
    assert rec["metrics"] == {"k": 3, "share": 0.5, "ok": True, "eig": [2.0, 1.0]}
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert rec["data"] == {"manifest_sha256": sha(git_repo / "dataset" / "manifest.yaml"),
                           "splits_sha256": sha(git_repo / "dataset" / "splits.yaml")}
    assert rec["outputs"]["model"]["sha256"] == hashlib.sha256(b"model bytes").hexdigest()
    assert "numpy" in rec["library_versions"]


def test_output_inside_repo_is_recorded_relative(git_repo):
    commit, dirty = rr.check_clean(git_repo)
    (git_repo / "data").mkdir()
    out = git_repo / "data" / "m.npz"
    out.write_bytes(b"x")
    path = rr.write("fit_pca", config={}, seeds={}, metrics={}, outputs={"model": out},
                    commit=commit, dirty=dirty, repo_root=git_repo, now=NOW)
    assert json.loads(path.read_text())["outputs"]["model"]["path"] == "data/m.npz"


@pytest.mark.parametrize("change", ["modify", "untracked"])
def test_dirty_tree_is_refused(git_repo, change):
    if change == "modify":
        (git_repo / "code.py").write_text("x = 2\n")
    else:
        (git_repo / "new.py").write_text("y = 1\n")
    with pytest.raises(rr.RunRecordError):
        rr.check_clean(git_repo)


def test_allow_dirty_is_recorded_as_dirty(git_repo):
    (git_repo / "code.py").write_text("x = 2\n")
    commit, dirty = rr.check_clean(git_repo, allow_dirty=True)
    assert dirty is True
    path = rr.write("fit_pca", config={}, seeds={}, metrics={}, outputs={},
                    commit=commit, dirty=dirty, repo_root=git_repo, now=NOW)
    assert json.loads(path.read_text())["dirty"] is True


def test_earlier_records_dont_make_the_tree_dirty(git_repo):
    write(git_repo)                                  # an uncommitted record in eval/runs/
    assert rr.check_clean(git_repo)[1] is False


def test_no_git_is_refused_unless_allowed(tmp_path):
    with pytest.raises(rr.RunRecordError):
        rr.check_clean(tmp_path)
    assert rr.check_clean(tmp_path, allow_dirty=True) == (None, True)


def test_never_overwrites(git_repo):
    path = write(git_repo)
    before = path.read_text()
    with pytest.raises(rr.RunRecordError):
        write(git_repo, metrics={"k": 99})
    assert path.read_text() == before


def test_infinity_is_a_string_and_nan_is_refused(git_repo):
    path = write(git_repo, metrics={"median_delay": math.inf, "low": -np.inf})
    assert json.loads(path.read_text())["metrics"] == {"median_delay": "inf", "low": "-inf"}
    with pytest.raises(rr.RunRecordError):
        rr.clean_metrics({"x": float("nan")})
    with pytest.raises(rr.RunRecordError):
        rr.clean_metrics({"x": [1.0, np.nan]})


@pytest.mark.parametrize("value", [np.zeros(rr.MAX_LIST + 1), np.zeros((2, 2)), [[1, 2]],
                                   {"a": 1}.keys(), object()])
def test_data_shaped_metrics_are_refused(value):
    with pytest.raises(rr.RunRecordError):
        rr.clean_metrics({"x": value})


def test_nested_metrics_and_error_names_full_key():
    assert rr.clean_metrics({"limits": {"t2": 1.5, "n": 3}}) == {"limits": {"t2": 1.5, "n": 3}}
    with pytest.raises(rr.RunRecordError, match="limits.t2"):
        rr.clean_metrics({"limits": {"t2": float("nan")}})


@pytest.mark.parametrize("name", ["", "Fit", "../x", "fit pca", "_x"])
def test_bad_names_are_refused(git_repo, name):
    with pytest.raises(rr.RunRecordError):
        rr.write(name, config={}, seeds={}, metrics={}, outputs={}, commit="c", dirty=False,
                 repo_root=git_repo, now=NOW)


def test_missing_manifest_is_refused(git_repo):
    (git_repo / "dataset" / "splits.yaml").unlink()
    with pytest.raises(rr.RunRecordError):
        rr.write("fit_pca", config={}, seeds={}, metrics={}, outputs={}, commit="c", dirty=False,
                 repo_root=git_repo, now=NOW)


def test_tests_cannot_reach_the_real_repo():
    # conftest points REPO_ROOT at a path that doesn't exist.
    assert not rr.REPO_ROOT.exists()
