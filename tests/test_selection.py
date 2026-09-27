"""Selection runs (decision 54), on a fake repo holding a copy of the real splits file."""

import hashlib
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from dataset import selection, splits

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "dataset").mkdir(parents=True)
    shutil.copy(REPO / "dataset" / "splits.yaml", root / "dataset" / "splits.yaml")
    real = yaml.safe_load((REPO / "dataset" / "manifest.yaml").read_text())
    (root / "dataset" / "manifest.yaml").write_text(yaml.safe_dump({"splits": real["splits"]}))
    return root


def add_to_manifest(root, sha):
    path = root / "dataset" / "manifest.yaml"
    m = yaml.safe_load(path.read_text())
    m["selection"] = {"file": selection.SELECTION_FILE, "sha256": sha}
    path.write_text(yaml.safe_dump(m))


def test_draw_is_100_forest_ceiling_numbers_never_dev(repo):
    assignment = splits.load(repo)
    numbers = selection.draw(assignment["forest_ceiling"])
    assert len(numbers) == 100 and len(set(numbers)) == 100 and numbers == sorted(numbers)
    assert set(numbers) <= set(assignment["forest_ceiling"])
    assert not set(numbers) & set(assignment["pools"]["dev"])
    assert not set(numbers) & set(assignment["authoring"])


def test_draw_is_fixed_by_the_seed(repo):
    forest = splits.load(repo)["forest_ceiling"]
    assert selection.draw(forest) == selection.draw(forest)
    assert selection.draw(forest, seed=1) != selection.draw(forest)


def test_write_then_load(repo):
    sha = selection.write(repo)
    raw = (repo / selection.SELECTION_FILE).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha
    add_to_manifest(repo, sha)
    data = selection.load(repo)
    assert data["seed"] == selection.SEED and data["source"] == "forest_ceiling"
    assert data["numbers"] == selection.draw(splits.load(repo)["forest_ceiling"])


def test_write_refuses_to_overwrite(repo):
    selection.write(repo)
    before = (repo / selection.SELECTION_FILE).read_bytes()
    with pytest.raises(selection.SelectionError):
        selection.write(repo)
    assert (repo / selection.SELECTION_FILE).read_bytes() == before


def test_load_refuses_missing_manifest_entry(repo):
    selection.write(repo)
    with pytest.raises(selection.SelectionError):
        selection.load(repo)


def test_load_refuses_edited_file(repo):
    add_to_manifest(repo, selection.write(repo))
    path = repo / selection.SELECTION_FILE
    path.write_text(path.read_text() + "# edited\n")
    with pytest.raises(selection.SelectionError):
        selection.load(repo)


def edited(repo, change):
    """A selection file changed by `change`, re-registered in the manifest (so only
    validation can catch it)."""
    selection.write(repo)
    path = repo / selection.SELECTION_FILE
    data = yaml.safe_load(path.read_text())
    change(data, splits.load(repo))
    text = yaml.safe_dump(data)
    path.write_text(text)
    add_to_manifest(repo, hashlib.sha256(text.encode()).hexdigest())


@pytest.mark.parametrize("kind", ["dev", "short", "duplicate", "authoring", "other_splits"])
def test_load_validates_even_with_matching_checksum(repo, kind):
    def change(data, assignment):
        if kind == "dev":
            data["numbers"][0] = assignment["pools"]["dev"][0]
        elif kind == "short":
            data["numbers"] = data["numbers"][:99]
        elif kind == "duplicate":
            data["numbers"][1] = data["numbers"][0]
        elif kind == "authoring":
            data["numbers"][0] = assignment["authoring"][0]      # not in forest_ceiling
        else:
            data["splits_sha256"] = "0" * 64
    edited(repo, change)
    with pytest.raises(selection.SelectionError):
        selection.load(repo)


def test_main_needs_write_flag(capsys):
    assert selection.main([]) == 1

def test_committed_selection_matches_manifest_and_draw():
    # The file Raj wrote in session 4: checksum, rules, and the seeded draw.
    data = selection.load(REPO)
    assert data["seed"] == selection.SEED and len(data["numbers"]) == 100
    if np.__version__ == data["numpy"]:
        assert data["numbers"] == selection.draw(splits.load(REPO)["forest_ceiling"], data["seed"])
