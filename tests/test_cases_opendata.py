"""The S3 move on real data (opt-in: `pytest -q -m opendata`): eval/cases.py's shared path
reproduces the five committed provenance files exactly (runs, per-run detection and
features, and the summary), from the inputs each file names.

Builder side: it loads the authoring pool of faults 1, 4, 5, 6 and 13 only, as
eval/authoring.py did. Like the other open-data tests, it points the loader at the real
repo. Only missing data or models skip it; a loader error fails it.
"""

from pathlib import Path

import pytest
import yaml

from dataset import loader
from eval import authoring, cases

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "data" / "models"
FILES = {f: REPO / "eval" / "provenance" / f"fault_{f:02d}.yaml" for f in authoring.FAULTS}

pytestmark = pytest.mark.opendata


def test_shared_path_reproduces_the_committed_provenance(monkeypatch):
    if not (REPO / "data" / "faulty_training").is_dir():
        pytest.skip("open data not present")
    paths = {"model_path": MODELS / "pca_static.npz", "limits_path": MODELS / "pca_static_limits.json",
             "watch_path": MODELS / "pca_static_watch.json", "normals_path": MODELS / "evidence_normals.json"}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        pytest.skip(f"models not present: {missing}")
    monkeypatch.setattr(loader, "REPO_ROOT", REPO)
    inp = cases.load_inputs(repo_root=REPO, **paths)
    for f, path in FILES.items():
        committed = yaml.safe_load(path.read_text())
        assert committed["inputs"] == inp.records, f"fault {f}: made from other inputs"
        runs = authoring.load_authoring(f)
        per_run = cases.score_pool(inp, runs)
        assert [int(k) for k in sorted(runs.runs)] == committed["runs"]
        assert per_run == committed["per_run"], f"fault {f}: per-run evidence changed"
        assert authoring.summarise(per_run) == committed["summary"], f"fault {f}: summary changed"