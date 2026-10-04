"""Build a committed detector bundle, app/bundles/pca_v1/, pca_v2/ or pca_v3/ (decision 21).

    python -m eval.build_bundle [--model data/models/pca_static.npz]
                                [--limits data/models/pca_static_limits.json]
                                [--out app/bundles/pca_v1]
    python -m eval.build_bundle --watch data/models/pca_static_watch.json
                                [--out app/bundles/pca_v2]
    python -m eval.build_bundle --watch data/models/pca_static_watch.json
                                --normals data/models/evidence_normals.json
                                [--out app/bundles/pca_v3]

Copies the model and writes limits.json: the calibrated limits plus the SHA-256 of the
fit and calibration run records they came from. Each must match exactly one record in
eval/runs/. The bundle is built in a temporary folder, self-tested, then moved into
place; an existing bundle is never overwritten. Prints only the path and checksums.

With --watch (a watch file from eval/calibrate_watch.py), it also writes watch.json: the
watch file plus the SHA-256 of its calibrate_watch run record. The watch file must come
from these limits and this model, with the register's groups (calibrate_watch.load_watch).
The default output is then app/bundles/pca_v2.

With --normals as well (an evidence normals file from eval/evidence_normals.py), it also
writes normals.json: the normals file plus the SHA-256 of its evidence_normals run record
(evidence_normals.load_normals finds exactly one). The watch.json already holds the Watch
tag boundaries (W_i) the features' top tags need, so pca_v3 is pca_v2 plus normals.json.
--normals needs --watch. The default output is then app/bundles/pca_v3. Building it doesn't
change the served bundle (bundle.DEFAULT_BUNDLE).
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from app.detector import bundle as bundle_mod
from app.detector import pca
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import check_dev, evidence_normals, run_record

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_V1 = bundle_mod.DEFAULT_BUNDLE.parent / "pca_v1"      # without --watch
DEFAULT_V2 = bundle_mod.DEFAULT_BUNDLE.parent / "pca_v2"      # with --watch
DEFAULT_V3 = bundle_mod.DEFAULT_BUNDLE.parent / "pca_v3"      # with --watch and --normals


def run(model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT, out=DEFAULT_V1,
        *, watch=None, normals=None, repo_root=None, register=bundle_mod.REGISTER):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} already exists; a bundle is never overwritten")
    if normals is not None and watch is None:
        raise ValueError("--normals needs --watch: the features rank the location by RBC / W")
    fit_path, _ = drv.fit_record_for(model_path, repo_root)
    cal_path = check_dev.calibration_record_for(limits_path, repo_root)
    limits = json.loads(Path(limits_path).read_text())
    if limits["lags"] != 0:                     # the replay scores unlagged samples (decision 63)
        raise drv.CalibrationError(f"the demo bundle is static PCA only; these limits have "
                                   f"{limits['lags']} lags")
    if limits["model_sha256"] != run_record.sha256(model_path):
        raise drv.CalibrationError(f"{model_path} isn't the model these limits were calibrated for")
    watch_doc = None
    if watch is not None:
        watch_record, doc = cw.load_watch(watch, limits_path, pca.load(model_path), repo_root)
        watch_doc = {**doc, "watch_record_sha256": run_record.sha256(watch_record)}
    normals_doc = None
    if normals is not None:
        normals_record, _ = evidence_normals.load_normals(normals, repo_root)
        normals_doc = {**json.loads(Path(normals).read_text()),
                       "normals_record_sha256": run_record.sha256(normals_record)}
    limits = {**limits, "fit_record_sha256": run_record.sha256(fit_path),
              "calibration_record_sha256": run_record.sha256(cal_path)}

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        staged = Path(tmp) / out.name
        staged.mkdir()
        shutil.copyfile(model_path, staged / "model.npz")
        (staged / "limits.json").write_text(json.dumps(limits, indent=2) + "\n")
        if watch_doc is not None:
            (staged / "watch.json").write_text(json.dumps(watch_doc, indent=2) + "\n")
        if normals_doc is not None:
            (staged / "normals.json").write_text(json.dumps(normals_doc, indent=2) + "\n")
        bundle_mod.self_test(bundle_mod.load(staged), register)    # refuse before moving
        staged.rename(out)
    print(f"bundle {out}: model {limits['model_sha256'][:12]}…, "
          f"fit record {limits['fit_record_sha256'][:12]}…, "
          f"calibration record {limits['calibration_record_sha256'][:12]}…"
          + (f", watch record {watch_doc['watch_record_sha256'][:12]}… (p = {watch_doc['p']})"
             if watch_doc else "")
          + (f", normals record {normals_doc['normals_record_sha256'][:12]}… "
             f"({len(normals_doc['tags'])} tags)" if normals_doc else "") + "; self-test passed")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--watch", type=Path, default=None,
                        help="a watch file (eval/calibrate_watch.py) for Watch boundaries")
    parser.add_argument("--normals", type=Path, default=None,
                        help="an evidence normals file (eval/evidence_normals.py); needs --watch")
    parser.add_argument("--out", type=Path, default=None,
                        help=f"default {DEFAULT_V1.name}, {DEFAULT_V2.name} with --watch, "
                             f"or {DEFAULT_V3.name} with --watch and --normals")
    args = parser.parse_args(argv)
    out = args.out or (DEFAULT_V3 if args.normals else DEFAULT_V2 if args.watch else DEFAULT_V1)
    try:
        run(args.model, args.limits, out, watch=args.watch, normals=args.normals)
    except (ValueError, FileExistsError, FileNotFoundError, drv.CalibrationError,
            bundle_mod.BundleError, evidence_normals.NormalsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())