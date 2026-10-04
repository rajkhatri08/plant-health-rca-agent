<!-- Destination: CLAUDE.md (repo root) -->
# CLAUDE.md: Plant Health & Root-Cause Agent (App 3)

## What this is
Early fault detection and diagnosis for a simulated chemical plant, built on the Tennessee Eastman benchmark (Rieth et al. dataset). It flags abnormal behaviour by equipment group and proposes ranked, evidence-backed causes for a human to approve. It is advisory only: it never predicts remaining life and never acts on the plant.

Read these when a task touches them:
- `docs/PLAN.md`: this week's task, scope and cut line
- `docs/decisions.md`: what was decided and why
- `eval/PROTOCOL.md`: pre-registered evaluation rules and values
- `eval/LEAKAGE.md`: what must never reach the agent or the builder

## How we work
- Raj writes the core logic: PCA limits and calibration, metric code, matcher scoring, reconstruction-based contributions (RBC), LangGraph nodes. For these, review, write tests and explain. Don't write the implementation unless Raj asks for it explicitly.
- You may write scaffolding: loaders, FastAPI routes, the UI page, CI and Docker config, test scaffolds.
- Raj is learning PCA monitoring, control loops and LangGraph through this project. When a change touches them, explain the idea in two or three sentences.
- Start each task in plan mode. Keep changes small and explain every diff.
- Ask before adding a dependency. Versions are pinned in the lockfile.
- Don't make design changes. Add them under "Decisions needed" in `docs/log.md`.
- End every session by appending an entry to `docs/log.md` (template at the top of that file).

## Stack
Python, FastAPI, PostgreSQL + SQLAlchemy (Neon), scikit-learn and numpy, pytest, Pydantic, LangGraph (no LangChain: prompts are plain Python templates and tools are our own functions; `langchain-core` is present only as LangGraph's dependency; no agent executors, no chat memory, no vector search for the library), Gemini through the official `google-genai` SDK behind one provider adapter, with a pinned model ID (decision 76), static HTML front end, Render and Vercel.

## Hard rules

### Leakage
- Sealed data (the raw downloads, the test split, and faults 16–20 in any split) and test labels live outside this folder, in `~/PycharmProjects/plant-health-sealed/`. Never try to read them. Never set `EVAL_MODE=1`. Never run the one-time conversion script; Raj runs it.
- `app/` never imports `eval/` or `ingest/`. Only `dataset/` reads raw data files.
- Test labels and anything about faults 16–20 live only in the sealed folder. Train/dev labels are used only in `dataset/`, `eval/` and notebooks, never in `app/` or `library/`.
- Nothing the agent sees (prompts, `library/`, tool outputs) may contain fault labels (IDV…), raw benchmark tag names (XMEAS/XMV), the benchmark's name or its source paper. Raw names are allowed only on the builder side (`dataset/`, `ingest/`) and never appear in `app/`, `library/`, prompts or tool outputs.
- Historian columns are `ts, tag, value, quality`. No run or segment IDs.
- Split by run number, the same number across every training file, never by samples. Fit all preprocessing on the fit pool only.

### Time
- No look-ahead when scoring: no centred windows, zero-phase filters, per-run normalisation, interpolation or backward shifts. Use past samples only.
- Every tool is as-of the diagnosis time. `as_of` and `history_id` come from graph state, never from the LLM.
- Analyzer values count from when they became available. Hold the last value; never interpolate.

### Safety
- The app is advisory. No tool writes to plant controls.
- Recommended actions come only from library action IDs, with their safety preconditions attached from the entry.
- Approvals happen only through the approval step, never through chat.

### Engineering
- One scoring engine for evaluation and the demo.
- No pickles. Store arrays, and ONNX if a network ships.
- CI runs the fast checks on every push and never loads test data.
- Every reported number comes from a run record, never a notebook.
- Secrets only in environment variables. Never commit keys.

## Repo layout
- `app/`: runtime (API, detector, agent). `app/agent/prompts/` and the agent tools are agent-visible.
- `library/`: failure-mode entries, tag register and asset register (agent-visible).
- `ingest/`: raw data to historian; with `dataset/`, the only places raw names appear.
- `dataset/`: the only loader for raw data.
- `eval/`: protocol, leakage rules and evaluation code. Never imported by `app/`.
- `shared/`: code both `app/` and `eval/` use, kept outside both (the leak scan, whose patterns spell raw names and so can't live in `app/`). Imports nothing of ours.
- `docs/`: `PLAN.md`, `decisions.md`, `log.md`.
- `notebooks/`: exploration only, train/dev data only.
- `tests/`
- `data/`: converted open data, gitignored. Raw downloads never enter the repo. The data manifest is in git.

## Commands
- Tests: `pytest -q`
- Convert raw data (Raj runs this; Claude Code never runs it): `python -m dataset.convert <name>`, one of `fault_free_training` (first, with `--crosscheck`), `fault_free_testing`, `faulty_training`, `faulty_testing`.
- Run the API locally: `uvicorn app.api:app --reload` (health at `/health`, replay at `/replay/info` and `/replay/status?upto=<ts>`).
- Run the page locally: `ALLOWED_ORIGIN=http://localhost:8080 uvicorn app.api:app --reload` in one terminal and `python -m http.server 8080 -d web` in another, then open http://localhost:8080.
- Build the detector bundle (after a fit and a calibration run): `python -m eval.build_bundle`. With Watch: `--watch data/models/pca_static_watch.json` (pca_v2). With the evidence normals as well: `--watch … --normals data/models/evidence_normals.json` (pca_v3).
- Export the replay stream once: `python -m ingest.export_replay` (since week 6 S2 it writes `app/replay/run_v2.csv` with the analyzers, and `eval/replay_source_v2.yaml`; the served `run.csv` is the first export).
- LLM smoke call (Raj runs this; it spends about Rs 0.01): `python -m eval.gemini --smoke`, with `GEMINI_API_KEY` in the gitignored `.env`. Add `--thinking-level low` if the API refuses `minimal`. Output-schema check (one call, about Rs 0.005): `python -m eval.gemini --schema-check`.
- CI: `.github/workflows/ci.yml` runs `pytest -q` on every push, with no data and no secrets. Every test runs under a guard (`tests/conftest.py`): no `GEMINI_API_KEY`, no `.env`, no network beyond loopback.
- Add the lint command here when it's created.

## Deployment
- API: https://plant-health-api.onrender.com (Render, Singapore, free plan; sleeps when idle, so the first request takes about a minute). Configured by `render.yaml`; installs `requirements-app.txt`.
- Page: https://plant-health-rca-agent.vercel.app (Vercel, root directory `web/`). Its API base is `RENDER_API_URL` in `web/index.html`.
- `ALLOWED_ORIGIN` on Render is the Vercel URL, set in the Render dashboard, never in the repo. Vercel preview URLs aren't allowed.

## Git
- Work on main. Don't create branches, commit or push unless Raj asks.
