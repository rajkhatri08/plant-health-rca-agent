"""ingest/export_replay.py on synthetic runs (never data/)."""

import csv
import hashlib

import numpy as np
import pytest
import yaml

import dataset.loader as loader_mod
from dataset import splits
from dataset.convert import VARIABLES
from dataset.loader import Runs
from ingest import export_replay as ex
from tests.test_fit_pca import FAST, two_factor_runs
from tests.test_leak_scan import find_leaks

DEV = [44, 7, 301]


@pytest.fixture
def fake(tmp_path, monkeypatch, git_repo):
    calls = []
    runs = two_factor_runs(numbers=DEV, samples=30)

    def load_faulty(fault, pool):
        calls.append((fault, pool))
        return Runs("faulty_training", fault, pool, VARIABLES, runs.runs)

    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    monkeypatch.setattr(splits, "load", lambda repo_root=None: {"pools": {"dev": DEV}})
    return {"csv": git_repo / "app" / "replay" / "run.csv",
            "source": git_repo / "eval" / "replay_source.yaml",
            "repo": git_repo, "runs": runs, "calls": calls}


def export(f):
    return ex.run(f["csv"], f["source"], repo_root=f["repo"])


def test_mechanical_choice_is_fault_13_on_the_lowest_dev_number(fake):
    doc = export(fake)
    assert fake["calls"] == [(13, "dev")]
    assert doc["fault"] == 13 and doc["run"] == 7 and doc["pool"] == "dev"


def test_csv_is_historian_rows_with_plant_names(fake):
    export(fake)
    with open(fake["csv"], newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["ts", "tag", "value", "quality"]
    body = rows[1:]
    assert len(body) == 30 * 33
    assert [r[1] for r in body[:33]] == FAST                        # register order
    assert body[0][0] == "2026-01-05T06:00:00Z" and body[33][0] == "2026-01-05T06:03:00Z"
    assert {r[3] for r in body} == {"good"}


def test_values_round_trip_float32_exactly(fake):
    export(fake)
    with open(fake["csv"], newline="") as f:
        body = list(csv.reader(f))[1:]
    from ingest import tags as tagmap
    cols = tagmap.column_indices(VARIABLES, FAST)
    x = fake["runs"].runs[7]
    got = np.array([float(r[2]) for r in body]).reshape(30, 33)
    assert np.array_equal(got, x[:, cols].astype(np.float64))
    assert np.array_equal(got.astype(np.float32), x[:, cols])


def test_csv_reveals_neither_the_fault_nor_the_run(fake):
    export(fake)
    text = fake["csv"].read_text()
    assert find_leaks(text) == []
    header = text.splitlines()[0]
    assert header == "ts,tag,value,quality"


def test_source_is_builder_side_and_pins_the_csv(fake):
    export(fake)
    doc = yaml.safe_load(fake["source"].read_text())
    assert doc["csv"] == "app/replay/run.csv"
    assert doc["csv_sha256"] == hashlib.sha256(fake["csv"].read_bytes()).hexdigest()
    assert doc["rows"] == 990 and doc["samples"] == 30 and doc["tags"] == 33
    assert len(doc["commit"]) == 40 and doc["dirty"] is False


@pytest.mark.parametrize("which", ["csv", "source"])
def test_refuses_to_overwrite_before_loading(fake, which):
    fake[which].parent.mkdir(parents=True, exist_ok=True)
    fake[which].write_text("old")
    with pytest.raises(FileExistsError):
        export(fake)
    assert fake["calls"] == [] and fake[which].read_text() == "old"
