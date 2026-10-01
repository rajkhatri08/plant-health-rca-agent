"""Evidence normals: every tag's normal band on the calibration pool (decisions 62, 68).

    python -m eval.evidence_normals [--out data/models/evidence_normals.json] [--allow-dirty]

The band of a tag is the central 99% of the calibration pool's scored samples (0.5th to
99.5th percentile, pooled, after the warm-up), exactly eval/masked.normal_bands, so "out"
means the same thing in the masked label, the loop states and the signature features. All
52 register tags: the 33 fast tags and the 19 analyzers (their held series, as stored).

Writes the normals file ({tag: [lo, hi]} in register order, with the band, the warm-up
and the pool) and an evidence_normals run record holding every band. Loads only the
calibration pool. Refuses a dirty tree unless --allow-dirty, and never overwrites the file.
"""

import argparse
import json
import sys
from pathlib import Path

from dataset import loader
from eval import masked, run_record
from ingest import tags as tagmap

DEFAULT_OUT = run_record.REPO_ROOT / "data" / "models" / "evidence_normals.json"
POOL = "calibration"


class NormalsError(RuntimeError):
    pass


def normals_record_for(path, repo_root):
    """Path of the single evidence_normals record whose normals output is this file."""
    sha = run_record.sha256(path)
    matches = [p for p in sorted((Path(repo_root) / run_record.RUNS_DIR).glob("*_evidence_normals.json"))
               if json.loads(p.read_text()).get("outputs", {}).get("normals", {}).get("sha256") == sha]
    if len(matches) != 1:
        raise NormalsError(f"expected one evidence_normals record for {path}, found {len(matches)}")
    return matches[0]


def load_normals(path, repo_root):
    """(record path, {tag: (lo, hi)}) for a recorded normals file."""
    record = normals_record_for(path, repo_root)
    doc = json.loads(Path(path).read_text())
    return record, {t: tuple(b) for t, b in doc["tags"].items()}


def run(out=DEFAULT_OUT, *, allow_dirty=False, repo_root=None):
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} already exists; delete it to recompute")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    tags = [r["tag"] for r in tagmap.register()]
    runs = loader.load_normal(POOL)
    cols = tagmap.column_indices(runs.columns, tags)
    bands = masked.normal_bands([runs.runs[k] for k in sorted(runs.runs)], cols,
                                warmup=masked.WARMUP, band=masked.BAND)
    by_tag = {t: [bands[c][0], bands[c][1]] for t, c in zip(tags, cols)}
    flat = [t for t, (lo, hi) in by_tag.items() if not lo < hi]
    if flat:
        raise NormalsError(f"tags with an empty band (lo == hi): {flat}; 'out' would be meaningless")
    doc = {"pool": POOL, "runs": len(runs.runs), "warmup": masked.WARMUP, "band": list(masked.BAND),
           "tags": by_tag}
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    record = run_record.write(
        "evidence_normals",
        config={"pool": POOL, "runs": len(runs.runs), "warmup": masked.WARMUP,
                "band": list(masked.BAND), "tags": len(tags)},
        seeds={},
        metrics={"bands": by_tag},
        outputs={"normals": out}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"{POOL} pool: {len(runs.runs)} runs; bands for {len(tags)} tags "
          f"(central {masked.BAND[1] - masked.BAND[0]:g}%, warm-up {masked.WARMUP})")
    print(f"saved {out}\nrun record: {record}")
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.out, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError,
            run_record.RunRecordError, NormalsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())