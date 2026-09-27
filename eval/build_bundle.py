"""Build the committed detector bundle app/bundles/pca_v1/ (decision 21).

    python -m eval.build_bundle [--model data/models/pca_static.npz]
                                [--limits data/models/pca_static_limits.json]
                                [--out app/bundles/pca_v1]

Copies the model and writes limits.json: the calibrated limits plus the SHA-256 of the
fit and calibration run records they came from. Each must match exactly one record in
eval/runs/. The bundle is built in a temporary folder, self-tested, then moved into
place; an existing bundle is never overwritten. Prints only the path and checksums.
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from app.detector import bundle as bundle_mod
from eval import calibrate_driver as drv
from eval import check_dev, run_record

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT, out=bundle_mod.DEFAULT_BUNDLE,
        *, repo_root=None, register=bundle_mod.REGISTER):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} already exists; a bundle is never overwritten")
    fit_path, _ = drv.fit_record_for(model_path, repo_root)
    cal_path = check_dev.calibration_record_for(limits_path, repo_root)
    limits = json.loads(Path(limits_path).read_text())
    if limits["model_sha256"] != run_record.sha256(model_path):
        raise drv.CalibrationError(f"{model_path} isn't the model these limits were calibrated for")
    limits = {**limits, "fit_record_sha256": run_record.sha256(fit_path),
              "calibration_record_sha256": run_record.sha256(cal_path)}

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        staged = Path(tmp) / out.name
        staged.mkdir()
        shutil.copyfile(model_path, staged / "model.npz")
        (staged / "limits.json").write_text(json.dumps(limits, indent=2) + "\n")
        bundle_mod.self_test(bundle_mod.load(staged), register)    # refuse before moving
        staged.rename(out)
    print(f"bundle {out}: model {limits['model_sha256'][:12]}…, "
          f"fit record {limits['fit_record_sha256'][:12]}…, "
          f"calibration record {limits['calibration_record_sha256'][:12]}…; self-test passed")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--out", type=Path, default=bundle_mod.DEFAULT_BUNDLE)
    args = parser.parse_args(argv)
    try:
        run(args.model, args.limits, args.out)
    except (FileExistsError, FileNotFoundError, drv.CalibrationError, bundle_mod.BundleError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())