"""Plant health API: one stream replayed (status band per sample) and the advisory diagnosis
of its first alert (week 6 S9).

    uvicorn app.api:app --reload

Runtime code: no imports from dataset/, eval/ or ingest/. Advisory only: nothing here
writes to plant controls. Responses carry plant tag names at most, never raw benchmark
names or labels (eval/LEAKAGE.md).

Environment:
- BUNDLE_DIR      detector bundle folder (default app/bundles/pca_v3: Watch and the evidence
                  normals; pca_v2 and pca_v1 are kept)
- REPLAY_CSV      historian CSV for episode 1 (default app/replay/run_v2.csv, with the analyzers;
                  the scores equal run.csv's). Episode 2 is app/replay/episode2.csv (week 6 S9).
- DEMO_DIR        the precomputed diagnosis (default app/replay: demo.json and llm_cache/)
- ALLOWED_ORIGIN  comma-separated browser origins allowed by CORS (default: none)

At startup the bundle is loaded and self-tested and the stream is read. If either fails,
/health returns 503 with the reason and every route returns 503: the app never scores with
a bundle that failed its self-test.

Then the diagnosis is rebuilt from the committed answers (app/agent/demo.py): the shipped graph
(decision 79) through llm.ReplayClient, which refuses a miss. No LLM is ever called. If the demo
isn't built, or can't be rebuilt exactly, only /diagnosis returns 503 (with the reason, also in
/health); the replay routes work as before.

Two fixed episodes (app/agent/demo.EPISODES), labelled "Episode 1" and "Episode 2" only: every
route takes episode=1|2 (default 1). Episode 1 is required; episode 2 is optional (503 for it
alone if its stream is missing).

GET /diagnosis?upto=<ts>&note=<none|emergency|injection>&episode=<1|2>: the diagnosis as of the replay time
(demo.diagnosis_at): nothing before the alert, the provisional diagnosis from the alert + 30 min,
the revised one from + 60 min. Read only: nothing is approved or acted on. Every response is
leak-checked.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import json

from app.agent import demo, llm
from app.detector import bands
from app.detector import bundle as bundle_mod
from app.detector import replay
from shared import leak_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "app" / "replay" / "run_v2.csv"
BANDS = ["Normal", "Alert", "Unknown"]                  # a bundle without Watch boundaries
WATCH_NOTE = "Watch band not built yet: it needs equipment-group attribution"


def create_app(bundle_dir=None, csv_path=None, allowed_origins=None, demo_dir=None, library=None, render=None,
               episode_csvs=None):
    bundle_dir = Path(bundle_dir or os.environ.get("BUNDLE_DIR") or bundle_mod.DEFAULT_BUNDLE)
    demo_dir = Path(demo_dir or os.environ.get("DEMO_DIR") or demo.DEMO_DIR)
    # Episode 1's stream is REPLAY_CSV or the default; every other episode's is its file in the
    # demo folder, unless given (tests).
    streams = {e: Path((episode_csvs or {}).get(e) or demo_dir / name) for e, name in demo.EPISODES.items()}
    streams["1"] = Path(csv_path or os.environ.get("REPLAY_CSV") or (episode_csvs or {}).get("1") or DEFAULT_CSV)
    if allowed_origins is None:
        allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGIN", "").split(",") if o.strip()]
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        state.clear()
        try:
            b = bundle_mod.load(bundle_dir)
            bundle_mod.self_test(b)
            first = replay.read_csv(streams["1"], b.model.tags)           # episode 1 is required
            if not first.ts:
                raise replay.ReplayError("the replay stream is empty")
            state["bundle"], state["streams"], state["episode_errors"] = b, {"1": first}, {}
        except (bundle_mod.BundleError, replay.ReplayError, OSError, ValueError, KeyError) as e:
            state.clear()
            state["error"] = f"{type(e).__name__}: {e}"
        if "bundle" in state:
            for e in demo.EPISODES:
                if e == "1":
                    continue
                try:                                                     # other episodes are optional
                    s = replay.read_csv(streams[e], state["bundle"].model.tags)
                    if not s.ts:
                        raise replay.ReplayError("the stream is empty")
                    state["streams"][e] = s
                except (replay.ReplayError, OSError, ValueError, KeyError) as err:
                    state["episode_errors"][e] = f"{type(err).__name__}: {err}"
            try:
                state["demo"] = demo.start_demo(state["bundle"], demo_dir, streams=streams, library=library,
                                                render=render)
            except Exception as err:            # noqa: BLE001 the demo is optional: any failure, including
                state["demo_error"] = f"{type(err).__name__}: {err}"     # a tools.ToolError, disables only /diagnosis
        yield

    app = FastAPI(title="Plant health monitor", lifespan=lifespan)
    if allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET"])

    def ready(episode="1"):
        if "error" in state or "bundle" not in state:
            raise HTTPException(status_code=503, detail=state.get("error", "not started"))
        if episode not in demo.EPISODES:
            raise HTTPException(status_code=422, detail=f"episode is one of {list(demo.EPISODES)}")
        if episode not in state["streams"]:
            raise HTTPException(status_code=503, detail=f"{demo.EPISODE_LABELS[episode]} isn't available: "
                                                        f"{state['episode_errors'].get(episode)}")
        return state["bundle"], state["streams"][episode]

    def episodes():
        return [{"id": e, "label": demo.EPISODE_LABELS[e]} for e in demo.EPISODES if e in state.get("streams", {})]

    @app.get("/health")
    def health():
        if "error" in state or "bundle" not in state:
            return JSONResponse(status_code=503, content={"status": "error", "self_test": "fail",
                                                          "detail": state.get("error", "not started")})
        return {"status": "ok", "self_test": "pass", "bundle": state["bundle"].name, "episodes": episodes(),
                "diagnosis": "ready" if "demo" in state else f"unavailable: {state.get('demo_error')}"}

    @app.get("/replay/info")
    def info(episode: str = Query("1", description="1 or 2")):
        b, s = ready(episode)
        out = {"episode": {"id": episode, "label": demo.EPISODE_LABELS[episode]}, "episodes": episodes(),
               "start": s.ts[0].strftime(replay.TS_FORMAT), "end": s.ts[-1].strftime(replay.TS_FORMAT),
               "step_min": replay.STEP_MIN, "samples": len(s.ts),
               "warmup_samples": b.limits["warmup"]}
        if b.watch is None:
            return {**out, "bands": BANDS, "note": WATCH_NOTE}
        return {**out, "bands": list(bands.BANDS), "groups": list(b.watch["groups"])}

    @app.get("/replay/status")
    def status(upto: str = Query(..., description="as-of time, e.g. 2026-01-05T07:00:00Z"),
               episode: str = Query("1", description="1 or 2")):
        b, s = ready(episode)
        try:
            as_of = replay.parse_ts(upto)
        except replay.ReplayError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        samples = replay.status(b, s, as_of)
        return {"as_of": upto, "samples": samples, "current": samples[-1] if samples else None}

    @app.get("/diagnosis")
    def diagnosis(upto: str = Query(..., description="as-of time, e.g. 2026-01-05T07:00:00Z"),
                  note: str = Query("none", description="one of the fixed operator notes: none, emergency, injection"),
                  episode: str = Query("1", description="1 or 2")):
        ready(episode)
        if "demo" not in state:
            raise HTTPException(status_code=503, detail=f"the diagnosis isn't available: {state.get('demo_error')}")
        if note not in demo.NOTES:
            raise HTTPException(status_code=422, detail=f"note is one of {list(demo.NOTES)}")
        try:
            as_of = replay.parse_ts(upto)
        except replay.ReplayError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        ep = state["demo"][episode]
        out = {**demo.diagnosis_at(ep["views"], ep["notified_at"], as_of, note),
               "episode": {"id": episode, "label": demo.EPISODE_LABELS[episode]}}
        leak_scan.check(json.dumps(out, sort_keys=True), "the /diagnosis response")
        return out

    return app


app = create_app()