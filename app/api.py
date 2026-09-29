"""Plant health API: the thin slice (one stream replayed, status band per sample).

    uvicorn app.api:app --reload

Runtime code: no imports from dataset/, eval/ or ingest/. Advisory only: nothing here
writes to plant controls. Responses carry plant tag names at most, never raw benchmark
names or labels (eval/LEAKAGE.md).

Environment:
- BUNDLE_DIR      detector bundle folder (default app/bundles/pca_v1)
- REPLAY_CSV      historian CSV for the replayed stream (default app/replay/run.csv)
- ALLOWED_ORIGIN  comma-separated browser origins allowed by CORS (default: none)

At startup the bundle is loaded and self-tested and the stream is read. If either fails,
/health returns 503 with the reason and /replay/* returns 503: the app never scores with
a bundle that failed its self-test.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.detector import bands
from app.detector import bundle as bundle_mod
from app.detector import replay

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "app" / "replay" / "run.csv"
BANDS = ["Normal", "Alert", "Unknown"]                  # a bundle without Watch boundaries
WATCH_NOTE = "Watch band not built yet: it needs equipment-group attribution"


def create_app(bundle_dir=None, csv_path=None, allowed_origins=None):
    bundle_dir = Path(bundle_dir or os.environ.get("BUNDLE_DIR") or bundle_mod.DEFAULT_BUNDLE)
    csv_path = Path(csv_path or os.environ.get("REPLAY_CSV") or DEFAULT_CSV)
    if allowed_origins is None:
        allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGIN", "").split(",") if o.strip()]
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        state.clear()
        try:
            b = bundle_mod.load(bundle_dir)
            bundle_mod.self_test(b)
            state["stream"] = replay.read_csv(csv_path, b.model.tags)
            if not state["stream"].ts:
                raise replay.ReplayError("the replay stream is empty")
            state["bundle"] = b
        except (bundle_mod.BundleError, replay.ReplayError, OSError, ValueError, KeyError) as e:
            state.clear()
            state["error"] = f"{type(e).__name__}: {e}"
        yield

    app = FastAPI(title="Plant health monitor", lifespan=lifespan)
    if allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET"])

    def ready():
        if "error" in state or "bundle" not in state:
            raise HTTPException(status_code=503, detail=state.get("error", "not started"))
        return state["bundle"], state["stream"]

    @app.get("/health")
    def health():
        if "error" in state or "bundle" not in state:
            return JSONResponse(status_code=503, content={"status": "error", "self_test": "fail",
                                                          "detail": state.get("error", "not started")})
        return {"status": "ok", "self_test": "pass", "bundle": state["bundle"].name}

    @app.get("/replay/info")
    def info():
        b, s = ready()
        out = {"start": s.ts[0].strftime(replay.TS_FORMAT), "end": s.ts[-1].strftime(replay.TS_FORMAT),
               "step_min": replay.STEP_MIN, "samples": len(s.ts),
               "warmup_samples": b.limits["warmup"]}
        if b.watch is None:
            return {**out, "bands": BANDS, "note": WATCH_NOTE}
        return {**out, "bands": list(bands.BANDS), "groups": list(b.watch["groups"])}

    @app.get("/replay/status")
    def status(upto: str = Query(..., description="as-of time, e.g. 2026-01-05T07:00:00Z")):
        b, s = ready()
        try:
            as_of = replay.parse_ts(upto)
        except replay.ReplayError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        samples = replay.status(b, s, as_of)
        return {"as_of": upto, "samples": samples, "current": samples[-1] if samples else None}

    return app


app = create_app()