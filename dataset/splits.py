"""Run-number pools (decision 49).

In the training files, run number k is one random stream shared across files, so
pools are assigned by run number, once, and the same assignment applies to the
fault-free file and every fault.

    python -m dataset.splits --write

writes dataset/splits.yaml once and refuses to overwrite it. The file is then fixed
by its SHA-256 in dataset/manifest.yaml, not by re-running the generator: numpy
doesn't promise the same Generator stream across versions. Uses no data.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SPLITS_FILE = "dataset/splits.yaml"

SEED = 20260928
GENERATOR = "numpy.random.default_rng (PCG64)"
N_RUNS = 500
POOL_SIZES = {"fit": 250, "early_stop": 50, "calibration": 150, "dev": 50}
N_AUTHORING = 5

HEADER = """\
# Run-number pools (decision 49), written once by `python -m dataset.splits --write`.
# One assignment for the fault-free file and every fault in the training files.
# Fixed by its SHA-256 in dataset/manifest.yaml: never edit or regenerate this file.
# authoring: the same 5 non-dev numbers for every known fault.
# forest_ceiling: the other 445 non-dev numbers.
"""


class SplitsError(RuntimeError):
    pass


def assign(seed=SEED):
    """The assignment for a seed: {"pools": {...}, "authoring": [...], "forest_ceiling": [...]}."""
    rng = np.random.default_rng(seed)
    perm = rng.permutation(np.arange(1, N_RUNS + 1))
    pools, start = {}, 0
    for name, size in POOL_SIZES.items():
        pools[name] = sorted(int(n) for n in perm[start:start + size])
        start += size
    non_dev = sorted(set(range(1, N_RUNS + 1)) - set(pools["dev"]))
    authoring = sorted(int(n) for n in rng.choice(non_dev, N_AUTHORING, replace=False))
    forest_ceiling = sorted(set(non_dev) - set(authoring))
    return {"pools": pools, "authoring": authoring, "forest_ceiling": forest_ceiling}


def render(seed=SEED):
    data = {"seed": seed, "generator": GENERATOR, "numpy": np.__version__, "n_runs": N_RUNS,
            **assign(seed)}
    validate(data)
    return HEADER + yaml.safe_dump(data, sort_keys=False, default_flow_style=None, width=100)


def validate(data):
    """Rules 1 and 2 of decision 49: the pools partition 1..N_RUNS with the fixed sizes;
    authoring numbers are outside dev; forest_ceiling is the rest of the non-dev numbers."""
    everything = set(range(1, N_RUNS + 1))
    pools = data.get("pools") or {}
    if set(pools) != set(POOL_SIZES):
        raise SplitsError(f"pools must be exactly {sorted(POOL_SIZES)}, found {sorted(pools)}")
    for name, size in POOL_SIZES.items():
        numbers = pools[name]
        if len(numbers) != size or len(set(numbers)) != size:
            raise SplitsError(f"pool {name} must hold {size} distinct run numbers")
        if not set(numbers) <= everything:
            raise SplitsError(f"pool {name} has run numbers outside 1..{N_RUNS}")
    if set().union(*map(set, pools.values())) != everything:
        raise SplitsError(f"the pools don't cover 1..{N_RUNS} without overlap")
    non_dev = everything - set(pools["dev"])
    authoring = data.get("authoring") or []
    if len(set(authoring)) != N_AUTHORING or len(authoring) != N_AUTHORING:
        raise SplitsError(f"authoring must hold {N_AUTHORING} distinct run numbers")
    if not set(authoring) <= non_dev:
        raise SplitsError("authoring uses a dev run number")
    forest = data.get("forest_ceiling") or []
    if len(forest) != len(set(forest)) or set(forest) != non_dev - set(authoring):
        raise SplitsError("forest_ceiling must be exactly the non-dev numbers minus authoring")


def load(repo_root=None):
    """The committed assignment, after checking its SHA-256 against the manifest."""
    repo_root = Path(repo_root or REPO_ROOT)
    manifest = yaml.safe_load((repo_root / "dataset" / "manifest.yaml").read_text())
    entry = (manifest or {}).get("splits")
    if not entry or entry.get("file") != SPLITS_FILE or not entry.get("sha256"):
        raise SplitsError(f"dataset/manifest.yaml has no splits entry for {SPLITS_FILE}")
    raw = (repo_root / SPLITS_FILE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise SplitsError(f"{SPLITS_FILE} doesn't match its SHA-256 in the manifest; "
                          "restore it from git, never regenerate it")
    data = yaml.safe_load(raw)
    validate(data)
    return data


def write(path, seed=SEED):
    path = Path(path)
    if path.exists():
        raise SplitsError(f"{path} already exists; the assignment is made only once")
    text = render(seed)
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help=f"write {SPLITS_FILE} (once)")
    args = parser.parse_args(argv)
    if not args.write:
        parser.print_help()
        return 1
    try:
        sha = write(REPO_ROOT / SPLITS_FILE)
    except SplitsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {SPLITS_FILE}\n\nFor dataset/manifest.yaml:\n"
          + yaml.safe_dump({"splits": {"file": SPLITS_FILE, "sha256": sha}}, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())