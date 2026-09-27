"""The selection runs for choosing (n, G) (decisions 54 and 55).

100 run numbers drawn once, with a fixed seed, from the committed forest-ceiling list in
dataset/splits.yaml. The same numbers are used for every selection fault. Dev numbers
can't appear: forest_ceiling excludes them (decision 49).

    python -m dataset.selection --write

writes dataset/selection.yaml once and refuses to overwrite it. The file is then fixed
by its SHA-256 in dataset/manifest.yaml, as splits.yaml is. Uses no data.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import yaml

from dataset import splits

REPO_ROOT = Path(__file__).resolve().parents[1]
SELECTION_FILE = "dataset/selection.yaml"

SEED = 20260929
SIZE = 100
SOURCE = "forest_ceiling"

HEADER = """\
# Selection runs for choosing persistence n and off-delay G (decision 54), written once by
# `python -m dataset.selection --write`. 100 run numbers from forest_ceiling in
# dataset/splits.yaml, the same for every selection fault.
# Fixed by its SHA-256 in dataset/manifest.yaml: never edit or regenerate this file.
"""


class SelectionError(RuntimeError):
    pass


def draw(forest_ceiling, seed=SEED):
    """SIZE distinct run numbers from forest_ceiling, sorted."""
    rng = np.random.default_rng(seed)
    return sorted(int(n) for n in rng.choice(sorted(forest_ceiling), SIZE, replace=False))


def render(assignment, splits_sha256, seed=SEED):
    data = {"seed": seed, "generator": splits.GENERATOR, "numpy": np.__version__,
            "source": SOURCE, "splits_sha256": splits_sha256,
            "numbers": draw(assignment[SOURCE], seed)}
    validate(data, assignment, splits_sha256)
    return HEADER + yaml.safe_dump(data, sort_keys=False, default_flow_style=None, width=100)


def validate(data, assignment, splits_sha256):
    """SIZE distinct numbers, all in forest_ceiling, drawn from this exact splits file."""
    numbers = data.get("numbers") or []
    if len(numbers) != SIZE or len(set(numbers)) != SIZE:
        raise SelectionError(f"selection must hold {SIZE} distinct run numbers")
    if not set(numbers) <= set(assignment[SOURCE]):
        raise SelectionError(f"selection numbers must all come from {SOURCE}")
    if set(numbers) & set(assignment["pools"]["dev"]):
        raise SelectionError("selection uses a dev run number")
    if data.get("source") != SOURCE or data.get("splits_sha256") != splits_sha256:
        raise SelectionError("selection was drawn from a different splits file")


def _splits(repo_root):
    """The committed assignment and the splits file's SHA-256 from the manifest."""
    assignment = splits.load(repo_root)
    manifest = yaml.safe_load((repo_root / "dataset" / "manifest.yaml").read_text())
    return assignment, manifest["splits"]["sha256"]


def load(repo_root=None):
    """The committed selection, after checking its SHA-256 against the manifest."""
    repo_root = Path(repo_root or REPO_ROOT)
    manifest = yaml.safe_load((repo_root / "dataset" / "manifest.yaml").read_text())
    entry = (manifest or {}).get("selection")
    if not entry or entry.get("file") != SELECTION_FILE or not entry.get("sha256"):
        raise SelectionError(f"dataset/manifest.yaml has no selection entry for {SELECTION_FILE}")
    raw = (repo_root / SELECTION_FILE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise SelectionError(f"{SELECTION_FILE} doesn't match its SHA-256 in the manifest; "
                             "restore it from git, never regenerate it")
    data = yaml.safe_load(raw)
    validate(data, *_splits(repo_root))
    return data


def write(repo_root=None, seed=SEED):
    repo_root = Path(repo_root or REPO_ROOT)
    path = repo_root / SELECTION_FILE
    if path.exists():
        raise SelectionError(f"{path} already exists; the selection is drawn only once")
    text = render(*_splits(repo_root), seed=seed)
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help=f"write {SELECTION_FILE} (once)")
    args = parser.parse_args(argv)
    if not args.write:
        parser.print_help()
        return 1
    try:
        sha = write()
    except (SelectionError, splits.SplitsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {SELECTION_FILE}\n\nFor dataset/manifest.yaml:\n"
          + yaml.safe_dump({"selection": {"file": SELECTION_FILE, "sha256": sha}}, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())