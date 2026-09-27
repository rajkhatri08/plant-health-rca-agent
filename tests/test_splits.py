"""Run-number pools (decision 49): the committed assignment, its checksum, and its rules."""

import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest
import yaml

import dataset.loader as loader_mod
from dataset import splits

REPO = Path(__file__).resolve().parents[1]
EVERY = set(range(1, 501))


@pytest.fixture(scope="module")
def committed():
    return splits.load(REPO)


def test_checksum_in_manifest_matches_committed_file():
    manifest = yaml.safe_load((REPO / "dataset" / "manifest.yaml").read_text())
    assert manifest["splits"]["file"] == "dataset/splits.yaml"
    raw = (REPO / "dataset" / "splits.yaml").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["splits"]["sha256"]


def test_pools_partition_1_to_500(committed):
    pools = committed["pools"]
    assert {k: len(v) for k, v in pools.items()} == {"fit": 250, "early_stop": 50,
                                                      "calibration": 150, "dev": 50}
    assert sum(len(v) for v in pools.values()) == 500
    assert set().union(*map(set, pools.values())) == EVERY


def test_authoring_and_forest_never_use_a_dev_number(committed):
    dev = set(committed["pools"]["dev"])
    authoring, forest = set(committed["authoring"]), set(committed["forest_ceiling"])
    assert len(committed["authoring"]) == 5 and len(authoring) == 5
    assert not authoring & dev and not forest & dev and not authoring & forest
    assert authoring | forest == EVERY - dev
    assert len(committed["forest_ceiling"]) == 445


def test_matches_seed_when_numpy_matches(committed):
    if np.__version__ != committed["numpy"]:
        pytest.skip(f"numpy {np.__version__} differs from {committed['numpy']} recorded in "
                    "splits.yaml; the checksum in dataset/manifest.yaml is the authority. "
                    "Never regenerate the split.")
    assert committed["generator"] == splits.GENERATOR
    fresh = splits.assign(committed["seed"])
    assert fresh == {k: committed[k] for k in ("pools", "authoring", "forest_ceiling")}


def test_write_refuses_to_overwrite(tmp_path):
    target = tmp_path / "splits.yaml"
    splits.write(target)
    before = target.read_bytes()
    with pytest.raises(splits.SplitsError, match="only once"):
        splits.write(target, seed=1)
    assert target.read_bytes() == before


def _fake_repo(tmp_path, text=None, sha=None):
    (tmp_path / "dataset").mkdir()
    src = (REPO / "dataset" / "splits.yaml").read_bytes()
    (tmp_path / "dataset" / "splits.yaml").write_bytes(src if text is None else text.encode())
    entry = {"file": "dataset/splits.yaml", "sha256": sha or hashlib.sha256(src).hexdigest()}
    (tmp_path / "dataset" / "manifest.yaml").write_text(yaml.safe_dump({"splits": entry}))
    return tmp_path


def test_load_refuses_edited_file(tmp_path):
    edited = (REPO / "dataset" / "splits.yaml").read_text().replace("fit: [1,", "fit: [2,", 1)
    repo = _fake_repo(tmp_path, text=edited)
    with pytest.raises(splits.SplitsError, match="SHA-256"):
        splits.load(repo)


def test_load_refuses_missing_manifest_entry(tmp_path):
    repo = _fake_repo(tmp_path)
    (repo / "dataset" / "manifest.yaml").write_text(yaml.safe_dump({"raw_files": {}}))
    with pytest.raises(splits.SplitsError, match="no splits entry"):
        splits.load(repo)


def test_load_validates_even_with_matching_checksum(tmp_path):
    # A bad assignment with a correct checksum is still refused.
    bad = splits.assign()
    bad["authoring"][0] = bad["pools"]["dev"][0]
    text = yaml.safe_dump(bad)
    repo = _fake_repo(tmp_path, text=text, sha=hashlib.sha256(text.encode()).hexdigest())
    with pytest.raises(splits.SplitsError, match="authoring uses a dev run number"):
        splits.load(repo)


def _break(kind):
    d = copy.deepcopy(splits.assign())
    p = d["pools"]
    if kind == "overlap":
        p["fit"][0] = p["dev"][0]
    elif kind == "outside":
        p["fit"][0] = 501
    elif kind == "size":
        p["calibration"].append(p["fit"].pop())
    elif kind == "missing_pool":
        del p["early_stop"]
    elif kind == "authoring_in_dev":
        d["authoring"][0] = p["dev"][0]
    elif kind == "authoring_count":
        d["authoring"].pop()
    elif kind == "forest_has_dev":
        d["forest_ceiling"][0] = p["dev"][0]
    elif kind == "forest_has_authoring":
        d["forest_ceiling"][0] = d["authoring"][0]
    return d


@pytest.mark.parametrize("kind", ["overlap", "outside", "size", "missing_pool", "authoring_in_dev",
                                  "authoring_count", "forest_has_dev", "forest_has_authoring"])
def test_validate_rejects(kind):
    with pytest.raises(splits.SplitsError):
        splits.validate(_break(kind))


def test_validate_accepts_fresh_assignment():
    splits.validate(splits.assign(12345))


# Opt-in check on the real open data: `pytest -q -m opendata`. Excluded by default
# (pyproject addopts) and skipped when data/ is absent, as in CI.
@pytest.mark.opendata
def test_open_faults_copy_fault_free_twin_up_to_sample_20(monkeypatch):
    if not (REPO / "data" / "fault_free_training.parquet").is_file():
        pytest.skip("open data not present")
    monkeypatch.setattr(loader_mod, "REPO_ROOT", REPO)
    monkeypatch.setattr(loader_mod, "SEALED_ROOT", Path.home() / "PycharmProjects" / "plant-health-sealed")
    normal = {}
    for pool in loader_mod.NORMAL_POOLS:
        normal.update(loader_mod.load_normal(pool).runs)
    assert set(normal) == EVERY
    for fault in loader_mod.OPEN_FAULTS:
        faulty = {}
        for pool in loader_mod.FAULTY_POOLS:
            faulty.update(loader_mod.load_faulty(fault, pool).runs)
        assert set(faulty) == EVERY
        differing = [k for k in sorted(EVERY) if not np.array_equal(faulty[k][:20], normal[k][:20])]
        assert differing == [], f"fault {fault}: {len(differing)} runs differ in samples 1-20"