<!-- Destination: docs/log.md -->
# Session log

Claude Code appends one entry at the end of every session, newest at the bottom. Raj pastes the week's entries into the Claude.ai App 3 Project for review.

## Template

### YYYY-MM-DD: task
- **Changed:**
- **Tests:**
- **Unsure about:**
- **Decisions needed:**

## Entries

### 2026-09-24: rules read-back and data/protocol decisions
- **Changed:** docs only. Recorded decisions 33–43 in `docs/decisions.md`. Updated leakage wording and the repo layout in `CLAUDE.md`. Updated leakage wording in `eval/LEAKAGE.md`. Updated splits, onset offsets, budget, keep rule, decline thresholds, warm-up, published-number check and cut-line scoring in `eval/PROTOCOL.md`. Updated the week 0 row in `docs/PLAN.md`. No code.
- **Tests:** none (docs only).
- **Unsure about:** the whole of `data/` is gitignored, so the data manifest must live outside `data/` (for example `dataset/manifest.yaml`) to be in git.
- **Decisions needed:** the exact warm-up value (must be under 10 samples); which published table and variable set the published-number check uses; where the data manifest lives.

### 2026-09-27: week 0 skeleton, converter, manifest, tag map
- **Changed:**
  - **Skeleton:** `app/` (with `agent/prompts/`), `library/`, `ingest/`, `dataset/`, `notebooks/`, `tests/`. Also `requirements.txt` (pinned, including transitive dependencies), `pyproject.toml` (pytest config only), and three backstop patterns in `.gitignore`.
  - **Bash deny rules** in `.claude/settings.json` for the sealed folder and the converter. All three were probed and refused without a prompt.
  - **`dataset/manifest.yaml`**, the single source for MD5s, runs per fault and samples per run.
  - **`dataset/rdata_stream.py`**, the streamed reader from decision 47.
  - **`dataset/convert.py`:**
    - The access-log line is written first, before the raw file is opened.
    - Guards; MD5 check; id checks from float64 statistics; fault, run and sample validation before any write.
    - Routing, with a second check at the open write.
    - One report per side, and a manifest snippet.
  - **`ingest/tag_map.yaml` and `library/tags.yaml`**, 52 tags.
  - **CLAUDE.md:** the convert command.
  - **`decisions.md`:** decisions 44–48.
  - Not run: the converter. Raj runs it.
- **Tests:** `pytest -q`, 179 passed, all on a fake repo and synthetic files. They cover:
  - the reader against pyreadr for gzip, bzip2, xz and uncompressed files
  - chunk boundaries, every form of row names, ALTREP columns, and rejection of unsupported types
  - routing for all four files, the guards, and every validation failure
  - reports, the access log (including failed and killed runs), and the dirty-flag scope
  - the crosscheck, and the sentinel never appearing in stdout, stderr, reports or the log
  - the tag files, and the leak scanner, including its own positive and negative cases

  Two real issues were caught while writing the tests. `route()` sent any fault of `fault_free_training` to open data; it now requires fault 0. And a comment in `library/tags.yaml` mentioned "component letters".
- **Unsure about:**
  - The reader has only seen files from pyreadr's writer and my test writer, not from R itself. The `--crosscheck` run on `fault_free_training` is the first real test.
  - Character row names in the big file would make skipping them slow: a Python loop over about 9.6M elements, possibly tens of seconds. It adds no memory.
- **Decisions needed:** analyzer dead time. In week 1, confirm from the published simulator code how an analyzer update is published (is the value at t the sample taken at t − dead time?) and cite it. Until then `library/tags.yaml` carries the nominal 6/6 and 15/15 minutes. The data can't settle it: the step pattern only confirms the update interval, and onsets fall on analyzer update times.

### 2026-09-27: conversion run (Raj)
- **Changed:** ran the four conversions from commit f425808 with a clean tree (`dirty: false`). Filled `download_date`, `terms` and the conversion section in `dataset/manifest.yaml`. `eval/test_access.log` has one line per run.
- **Tests:**
  - The crosscheck against pyreadr on `fault_free_training` printed "identical: yes" (55 columns).
  - Rows: 250,000 / 480,000 / 5,000,000 / 9,600,000, with 500 runs per fault and 500 or 960 samples per run. No non-finite values in any file.
  - Faults 1-15 of `faulty_training` went to `data/`; everything else went to the sealed folder.
  - Outside the repo, the reader was also checked against files written by R 4.3.3 itself: format versions 2 and 3; gzip, bzip2, xz and uncompressed; compact, integer and character row names; compact integer sequences. All matched R's values exactly, which settles the first "Unsure about" in the previous entry.
- **Unsure about:** nothing new.
- **Decisions needed:** nothing new. Analyzer dead time is still open for week 1.

### 2026-09-27: week 1 session 1, decision 49 and protocol update
- **Changed:** docs only.
  - **`docs/decisions.md`:** decision 49, pools by run number (Raj's decision), under a new heading "Week 1 decisions, 27 September 2026".
  - **`eval/PROTOCOL.md`:**
    - **Data and splits:** the last pre-fault sample (20 in training, 160 in testing), a run-numbers paragraph, and the split table rewritten by run number (same 5 authoring numbers for every fault; forest ceiling is the other 445 non-dev numbers).
    - **Detection metrics:** false alerts per 24 h use normal runs only, and chance rates say "normal runs only". Intervals bootstrap over run numbers, with every file's run drawn together, on dev and on test.
    - **Diagnosis:** the LLM-variance bootstrap is over run numbers.
  - **Mirror edits:** in `eval/LEAKAGE.md` wall 3, authoring numbers are outside the dev pool and listed in `dataset/splits.yaml`. In `CLAUDE.md`, "split by run number".
  - Week 1 plan approved: sessions 1, 2 and 5 today; 3 and 4 later this week.
- **Tests:** none (docs only).
- **Unsure about:** nothing new.
- **Decisions needed:**
  - **Onset-to-divergence window (Raj):** alerts between onset and the first sample where a run differs from its fault-free twin happen identically on the twin, so they are chance alerts. Decide how detection credit and chance rates handle that window. Faults 1 and 3 first differ at sample 21; fault 13 first differs anywhere from sample 23 to 61, depending on the run.
  - **McNemar's test assumes independent cases**, but diagnosis cases that share a run number aren't independent. Keep McNemar with a stated caveat, or use a paired bootstrap over run numbers.
  - **PCA component-count rule:** the protocol has a rule for DPCA lags but none for PCA components. It must be written in before the fit is used.
  - **Metric details for session 3:** the delay median with misses (proposed: misses count as +∞); whether an alert already on at the first sample after warm-up counts as a notification (proposed: yes); the exact warm-up value (still open from week 0).

### 2026-09-27: week 1 session 2, run-number splits, loader, leak tests
- **Changed:**
  - **Wording fix (decision 49 and PROTOCOL run-numbers paragraph):** the sharing was checked by Raj on faults 1, 2, 3 and 13. The open-data test in `tests/test_splits.py` checks all open faults 1–15. Faults 16–20 are sealed.
  - **`dataset/splits.py`** (seed 20260928) and **`dataset/splits.yaml`**, written once by `python -m dataset.splits --write`. A second run was refused. The file's SHA-256 is recorded in `dataset/manifest.yaml` (`splits: {file, sha256}`), which is the authority.
  - **`dataset/loader.py`:**
    - **Pools:** `load_normal(pool)` and `load_faulty(fault, pool)` take their run numbers only from the committed assignment.
    - **Refusals:** `load_testing()` always refuses in week 1, as do faults 16–20 and paths that resolve outside `<repo>/data` or into the sealed folder.
    - **Integrity checks:** each file's SHA-256 against `open_reports`, and the structure (runs 1..500, samples 1..N).
  - **`dataset/convert.py`:** `_file_hash` renamed to `file_hash` (approved). No behaviour change.
  - **`tests/conftest.py`:** the autouse fixture now also points the loader at non-existent roots and unsets `EVAL_MODE`.
  - **`pyproject.toml`:** an `opendata` marker, excluded by default (`-m 'not opendata'`).
  - **New test files:** `tests/test_splits.py`, `tests/test_loader.py`, and `tests/test_walls.py` (import and read walls). The plan had the walls in `test_loader.py`; I put them in their own file because they aren't about the loader.
- **Tests:**
  - **Default run:** `pytest -q` gives 249 passed, 1 deselected (179 existing and 70 new). The new tests cover:
    - the partition of 1..500 and the pool sizes
    - the checksum match
    - the seed comparison, which runs only when the numpy version matches
    - write-once
    - tampered, unlisted or invalid splits files
    - rule 1 (every pool, every fault's dev numbers equal normal dev)
    - rule 2 (the same 5 authoring numbers for every fault, none of them dev; forest ceiling is 445 numbers with no dev or authoring numbers; faulty runs refused in the normal pools)
    - sealed refusals (faults 16–20, the test split, a sealed absolute path, `..` traversal, a symlink into the sealed folder), all with `EVAL_MODE` unset
    - changed data files, missing runs and wrong fault numbers
    - `app/` imports and raw-file reads outside `dataset/`
  - **Open-data check:** `pytest -q -m opendata` passed. On the real open data, samples 1–20 of every run of every open fault (1–15) equal the fault-free run with the same number. This extends Raj's check on faults 1, 2, 3 and 13 to all open faults.
  - Rules 3 and 4 get their tests with the metric code in session 3.
- **Unsure about:**
  - The loader hashes each file on every load, about 55 MB each. That's fine now; add a cache if it gets slow.
  - The read-wall scan is textual (`.parquet`, `pyarrow`, `pyreadr`, and so on), so a future non-data use of pyarrow outside `dataset/` would trip it.
- **Decisions needed:** nothing new.

### 2026-09-27: week 1 session 5, analyzer dead time
- **Changed:**
  - **`docs/decisions.md`:** decision 50. Analyzer dead time equals one update interval: 6/6 min for the 14 reactor-feed and purge analyzers, 15/15 min for the 5 product analyzers. The value published at an update is the sample taken at the previous update. Cited to `teprob.f` (`TEFUNC`, lines 132–164 and 730–756) and `temexd_mod.c` v1.3.3 (lines 3215–3269), both from Ricker's archive, retrieved today, with zip checksums.
  - **`library/tags.yaml`:** header comment only. "Nominal until confirmed" becomes "confirmed (decision 50)", with the one-interval rule and no source names (agent-visible). All 19 analyzer rows already had the confirmed values.
  - The code was downloaded to the session scratchpad, outside the repo, and not committed.
- **Tests:** `pytest -q` gives 249 passed, 1 deselected (leak scan still clean). No new tests.
- **Unsure about:**
  - **Which simulator version generated the data:** the Dataverse text doesn't say and the dataset paper is paywalled. A secondary source says it was the revised model. It doesn't affect decision 50, because both versions share the analyzer logic.
  - **Which recorded 3-minute sample first shows each new analyzer value:** that depends on the recording side (update time against record time, and `TGAS` accumulating in single precision), not on the process code. The step pattern in the data already fixes the update interval. Check the alignment on the open data when the analyzer evidence tool is built (week 4 or 6).
- **Decisions needed:** none new. The analyzer dead-time item from week 0 is closed by decision 50.

### 2026-09-27: week 1 session 3, metric definitions, stubs and tests
- **Changed:**
  - Explained the detection-metric definitions in chat with a worked example. Raj confirmed he understood.
  - **`eval/metrics.py`:** stubs only (signatures, docstrings, constants, the `ScoredRun` and `Detection` types). Every function raises `NotImplementedError`. Raj implements them.
  - **`tests/test_metrics.py`:** 50 hand-built cases, each with its expected value worked out in a comment:
    - notifications, including the rule-2 case of an alert on at the first scored sample
    - detection and delay, on training and testing onsets and at the window edges
    - delay median and IQR with misses as +∞, including the case where two infinities are interpolated
    - false alerts per 24 h and chance rate, which refuse fault runs (rule 4)
    - share still flagged
    - the bootstrap over run-number groups (rule 3) and the paired bootstrap using the same draw
  - Raj's answers used: misses count as +∞; an alert on at the first scored sample is a notification; warm-up is a parameter; the onset-to-divergence window isn't tested.
- **Tests:** `tests/test_metrics.py` gives 50 failed, all `NotImplementedError`, as expected until Raj implements. The rest of the suite gives 249 passed, 1 deselected.
- **Unsure about:** nothing new.
- **Decisions needed:** three placeholders in `tests/test_metrics.py`, which Claude proposed and Raj hasn't explicitly confirmed:
  - quantiles use linear interpolation, and any interpolation touching +∞ gives +∞
  - the bootstrap uses B = 2000 with a percentile interval
  - share still flagged runs from first detection to the end of the run, both ends included, with misses excluded

  Once confirmed, write them into PROTOCOL.md (Detection metrics).

### 2026-09-27: week 1 session 3 (continued), metric code implemented and reviewed
- **Changed:**
  - **`eval/metrics.py`:** implemented by Raj, with step-by-step guidance from the Claude.ai chat, against `tests/test_metrics.py`. Claude reviewed it and didn't change it.
  - **Review findings** (Raj fixes `metrics.py` himself; tests now added for each):
    1. **Bootstrap intervals return NaN when the statistic can be +∞** (for example a median delay with many misses). `np.percentile` interpolates ∞ with ∞ into NaN: `bootstrap_ci` with a +∞ statistic gives `(nan, nan)`. The paired version gives ∞ − ∞ = NaN.
    2. **NaN delays pass through `delay_summary` silently** and give `(nan, nan, nan)`.
    3. **Tracks aren't checked for 0/1:** NaN counts as on (`notifications([0, nan, 0], 0)` gives `[2]`), so gaps could count as alerts.
    4. **A warm-up longer than a run gives negative hours** in `false_alerts_per_24h`.
    5. **Untested:** the paired run-number mismatch error in `paired_bootstrap_ci`.
    6. **Untested:** the empty-input errors in `bootstrap_ci` and `paired_bootstrap_ci`.
  - **Raj's answers:**
    - The three placeholders are confirmed.
    - Tests for 1–6 expect `ValueError` only, with no message matching.
    - For 1: `bootstrap_ci` never returns NaN. A statistic that is +∞ in every resample gives (∞, ∞), and one that is sometimes finite gives (finite, ∞). `paired_bootstrap_ci` raises when both statistics are the same infinity in a resample.
  - **`eval/PROTOCOL.md`, Detection metrics:**
    - **Detected:** defines a notification, including that an alert already on at the first scored sample counts.
    - **Delay:** misses count as +∞ (so the median is +∞ when more than half are missed); linear quantiles, and +∞ wins.
    - **Persistence:** from first detection to the end of the run, both ends included, with misses left out and the detected count reported.
    - **Intervals:** B = 2000, percentile method, seed in the run record.
  - **`tests/test_metrics.py`:** 14 new tests for findings 1–6, and the header now says the placeholders are confirmed.
- **Tests:**
  - `pytest -q` gives 10 failed, 303 passed, 1 deselected.
  - The 10 failures are the new tests for findings 1–4, expected until Raj fixes `metrics.py`.
  - These new tests already pass: 5, 6, and the case of 4 where a run's length equals the warm-up (it already raises through the zero-hours check).
- **Unsure about:** nothing new.
- **Decisions needed:** how a paired delay comparison is reported when resamples hit ∞ − ∞. The code will raise, so a delay comparison can't run until a protocol line says what to do (for example compare detection rates, or drop those resamples and report how many).

### 2026-09-27: week 1 session 4, PCA explanation, component rule, stubs and tests
- **Changed:**
  - **Explained in chat:** PCA monitoring, T² and SPE, with the 2-tag example (correlation 0.9, k = 1): (1, 1) gives T² 1.05 and SPE 0; (1, −1) gives T² 0 and SPE 2. Also the three component-count options. Raj confirmed he understood.
  - **Raj's choices:**
    - Component count: parallel analysis with 20 shuffles, the 95th percentile, fixed seed 20260927, on the fit pool after warm-up. The cumulative explained variance is printed as a sanity figure.
    - The zero-variance guard stays (his fit-pool check found no constant tag).
    - The published-number check uses the published table's number of components, like its variable set.
  - **`eval/PROTOCOL.md`, Detection:**
    - A new "PCA components" bullet with the rule and its caveat: with about 125,000 autocorrelated samples it behaves like λ > about 1.03 and may keep one or two extra components.
    - Published-number check: the number of components is added next to the variable set (still _TBD_).
  - **`app/detector/pca.py`:** stubs only, all raising `NotImplementedError`, for Raj. The module docstring fixes the conventions: ddof=1, correlation-matrix eigenvalues in descending order, the sign rule, row-by-row scoring and `.npz` with no pickles.
  - **`ingest/tags.py`** (Claude): the raw-to-tag map, the register, the 33 fast tags, and column indices.
  - **`eval/fit_pca.py`** (Claude): the fit driver.
    - **Steps:** takes `--warmup` (0–9, per the protocol's "under 10"), loads the fit pool through the loader, keeps the fast tags, drops warm-up, runs parallel analysis, fits, and saves the `.npz`.
    - **Guards:** refuses to overwrite an existing model.
    - **Output:** prints only shapes, k and the sanity figure.
  - **Tests:** `tests/test_pca.py` (27 tests) and `tests/test_fit_pca.py` (9 tests). Hand values were checked with plain numpy in a scratch run.
- **Tests:**
  - `pytest -q` gives 28 failed, 321 passed, 1 deselected.
  - The 28 failures are all `NotImplementedError` from the PCA stubs (27 in `test_pca.py` and the driver's fit-and-save test). They pass once Raj implements `pca.py`.
  - Raj's `metrics.py` fixes make all 64 metric tests pass.
- **Unsure about:**
  - Parallel analysis tests use strong factor structure, so k doesn't depend on how the shuffles consume the rng. Real data will sit much closer to the threshold, which is the caveat in PROTOCOL.
  - The driver hasn't been run on real data; it needs `pca.py` and a warm-up value.
- **Decisions needed:**
  - The warm-up value (still open).
  - The published table, its variable set and its number of components, before that check runs.
  - Whether to record "the published-number check uses the published component count" as its own decision or as an addition to decision 39. For now it's only in PROTOCOL.

### 2026-09-27: week 1 session 4 (continued), PCA implemented, reviewed and smoke-tested
- **Changed:**
  - **`app/detector/pca.py`:** implemented by Raj, with step-by-step guidance from the Claude.ai chat, against `tests/test_pca.py`. Claude reviewed it and didn't change it.
  - **Review findings** (Raj fixes `pca.py` himself; decisions below):
    1. **`scores()` doesn't refuse NaN/inf.** `fit()` and `parallel_analysis()` do. A NaN sample gives NaN T² and SPE, which compare as "below limit", so a gap would silently mean "normal". Either refuse it here or leave it to the data-quality layer, but state which.
    2. **`save()` uses `np.savez`, which appends `.npz` when the path lacks it.** So `--out model` writes `model.npz`, while the driver's overwrite guard checks `model` and the driver prints the wrong path. The default path ends in `.npz`, so there's no effect today.
    3. **`load()` doesn't check that the arrays fit together** (tag count, loadings shape, k against the eigenvalues). That's minor now, and it belongs with the week 2 bundle self-test.
  - **Smoke test** (Claude ran `python -m eval.fit_pca --warmup 5`; warm-up 5 is a placeholder, not a decision):
    - fit pool X is 123,750 × 33 (250 runs × 495 samples)
    - parallel analysis gives k = 12
    - cumulative explained variance at k is 0.788
    - It wrote `data/models/pca_static.npz` (gitignored). Delete it before the real fit, because the driver refuses to overwrite.
  - **Raj's decisions on the findings:**
    1. `scores()` raises `ValueError` on NaN or inf for now, so a gap can never read as normal. Revisit when the data-quality layer marks gaps as Unknown before scoring. Recorded as decision 51 in `docs/decisions.md`.
    2. `save()` raises `ValueError` on a path that doesn't end in `.npz`.
    3. The `load()` consistency checks are deferred to the week 2 bundle self-test.
  - **`tests/test_pca.py`:** 6 new tests expecting `ValueError` only. Three are for finding 1 (NaN, inf, −inf in `scores()`). Three are for finding 2 (`pca`, `pca.txt`, `pca.npz.bak`, each also checking that nothing is written).
- **Tests:**
  - Before the new tests, `pytest -q` passed in full, including all PCA and driver tests (per Raj; the smoke test is separate and adds no tests).
  - Now it gives 6 failed, 349 passed, 1 deselected. The 6 failures are the new tests, expected until Raj updates `pca.py`.
- **Unsure about:** k = 12 comes from the placeholder warm-up and is near the rule's λ ≈ 1.03 regime, per the caveat in PROTOCOL. It isn't a result and must not be reported. Reported numbers come from run records.
- **Decisions needed:**
  - The warm-up value (still open).
  - The published table, its variable set and its number of components.
  - Whether the component-count choice for the published-number check becomes its own decision.

### 2026-09-27: week 2 session 1, warm-up decision and week 2 plan
- **Changed:** docs only.
  - **`docs/decisions.md`:** decision 52 (Raj's): the warm-up is 9 samples (27 min), and scoring starts at sample 10. It's filed under a new heading, "Week 2 decisions, 27 September 2026". Raj called it decision 51, but 51 was already taken by the NaN refusal.
  - **`eval/PROTOCOL.md`:** the warm-up row now reads "9 samples (27 min); scoring starts at sample 10; lags + persistence window − 1 ≤ 9". A sentence under Detection → Limits binds the persistence window to the warm-up.
  - **Week 2 plan approved:**
    - Today: sessions 1–3, each stopped for review and commit.
    - Later: calibration implementation and driver, recording the published-number check, the thin-slice backend, and the UI and deploy.
  - **Raj's answers, to record as decisions 53 and 54 in session 3:**
    - Plant ratio: r = max(T²/T²lim, SPE/SPElim) at a shared percentile q.
    - Persistence: n consecutive samples, n in 1–10. Grouping: an off-delay G, in 0–20 samples.
    - q is the lowest value that meets the budget on the calibration pool.
    - (n, G) is chosen by the mean detection rate on a seeded subsample of 100 forest-ceiling run numbers, not on dev.
    - Every compared detector uses the same search.
  - **Other choices:**
    - The published table is Yin et al. 2012 (33 variables). Raj confirms the component count from the full text; otherwise the check uses our parallel-analysis k and says so. It gets recorded in PROTOCOL in session 5.
    - The thin slice reads a committed CSV of one dev run, with columns `ts, tag, value, quality`.
    - Approved dependencies: fastapi, uvicorn, httpx and matplotlib.
    - The dataset's public-domain dedication is confirmed.
- **Tests:** none (docs only).
- **Unsure about:** nothing new.
- **Decisions needed:**
  - The warm-up is closed by decision 52.
  - Does the (n, G) selection mean include faults 3, 9 and 15, which the protocol's summary excludes as near-undetectable? Raj's rule says faults 1–15.
  - The published table's component count: Raj is confirming it from the full text.
  - Still open from week 1: the onset-to-divergence window, McNemar against a paired bootstrap, and how to report a paired delay comparison when resamples hit ∞ − ∞.
  - Later item: move the replay data from the committed CSV to a Neon historian table.

### 2026-09-27: week 2 session 2, run records, real fit, autocorrelation plot
- **Changed:**
  - **`eval/run_record.py` (new, Claude):** writes `eval/runs/<UTC stamp>_<name>.json`. Each record holds:
    - the commit and a dirty flag
    - the config and seeds
    - the SHA-256 of `dataset/manifest.yaml` and `dataset/splits.yaml`
    - numpy and Python versions
    - the SHA-256 of each output file
    - the metrics

    Guards:
    - A dirty tree, or no git, is refused unless `--allow-dirty`, and the record then says `dirty: true`. `eval/runs/` itself doesn't count as a change.
    - Metrics are scalars or flat lists of at most 64 values, so data values can't be stored. +∞ is written as `"inf"`, and NaN is refused.
    - A record is never overwritten.
  - **`eval/fit_pca.py`:** checks for a clean tree before loading anything, and writes a `fit_pca` record after saving. It gains an `--allow-dirty` flag.
  - **`eval/plot_autocorr.py` (new, Claude):** pooled autocorrelation of T² and SPE on the fit pool, lags 0–40. Each run is scored on its own after the warm-up, and lag pairs never cross a run boundary. It saves a PNG to `data/plots/` (gitignored). It's a script instead of a notebook, so no Jupyter.
  - **`requirements.txt`:** matplotlib 3.11.2 (approved) and its six transitive dependencies, pinned.
  - **`tests/conftest.py`:** tests can't reach the real `eval/runs/`. A new `git_repo` fixture gives tests a throwaway committed repo.
  - Committed as 7070ab7.
  - **Fit, run by Raj at 7070ab7 with a clean tree:** `python -m eval.fit_pca --warmup 9`. Record `eval/runs/20260927T093509Z_fit_pca.json`:
    - 250 fit runs and 122,750 samples (250 × 491)
    - k = 12 by parallel analysis
    - cumulative explained variance 0.7886 (a sanity figure)
  - **Plot, run by Raj:** `python -m eval.plot_autocorr --warmup 9` wrote `data/plots/autocorr_fit.png`. Raj's reading (exploration only, not reported): T² lag-1 about 0.33, with a long tail near 0.1–0.2; SPE close to white.
- **Tests:** `pytest -q` gives 389 passed, 1 deselected. 34 are new:
  - 22 in `tests/test_run_record.py`
  - 8 in `tests/test_plot_autocorr.py`: hand-computed autocorrelations, including one where joining runs would give a different answer; an AR(1) check; and a check that the plot writes a PNG
  - 4 in `tests/test_fit_pca.py`: the record, the dirty-tree refusal before loading, `--allow-dirty`, and `main`'s exit code
- **Unsure about:**
  - **k sits at the edge of the rule.** From the record, the 12th eigenvalue is 1.035 and the 13th is 0.976. That's the λ ≈ 1.03 regime from the caveat in PROTOCOL: a different seed or shuffle count could plausibly give k = 11 or 13. This isn't a change request; the rule is pre-registered and k = 12 stands.
  - **Autocorrelation makes the effective sample size smaller than the count.** T²'s lag-1 of 0.33 with a long tail means exceedances come in clusters. That's why the limit, persistence and grouping are calibrated as events on whole runs (session 3), not as a per-sample rate. It's also why the bootstrap resamples whole runs.
  - `app/detector/pca.py` gained a trailing newline, probably when the IDE saved it. Raj committed it with this session.
- **Decisions needed:** nothing new. Still open: whether the (n, G) selection mean includes faults 3, 9 and 15; and the Yin 2012 component count.

### 2026-09-27: week 2 session 3, limits, persistence and grouping: decisions, stubs, tests
- **Changed:**
  - **Two corrections to the approved plan, with Raj's answers:**
    - **No bisection.** Notifications don't always fall as q rises: a higher limit can split one alert into two. So q is searched on a grid, and for each (n, G) it's the lowest grid value such that it and every higher one meet the budget. The scan goes from the top down and stops at the first failure.
    - **Warm-up in the persistence window.** The plan's test list said the window "never reaches back into the warm-up". Decision 52 means the opposite: the window may use warm-up samples, but never reaches before sample 1.
    - Raj also chose to leave faults 3, 9 and 15 out of the selection mean.
  - **`docs/decisions.md`:** decision 53, the plant ratio r = max(T²/T²lim, SPE/SPElim) at a shared percentile q, with alert condition r > 1. Decision 54 covers:
    - persistence as an on-delay of n consecutive samples, n in 1..10 − L
    - grouping as an off-delay G in 0..20, which visibly holds the alert for G samples, with its state starting at the first scored sample
    - the grid 95.00 … 99.99 (500 points) and the stable-lowest-q rule
    - selection by mean detection rate over the 12 faults, on a seeded subsample of 100 forest-ceiling run numbers, with ties going to the smaller n, then the smaller G
    - the same search for every compared detector
  - **`eval/PROTOCOL.md`, Detection → Limits:** the same rules, in short.
  - **`app/detector/alerting.py` (stubs for Raj):** `plant_ratio`, `persist`, `group`, `alert_track`. Runtime code, pure numpy, with no imports from `eval/`. The docstrings fix the conventions: whole-run arrays, causal, 0/1 integer tracks.
  - **`eval/calibrate.py` (stubs for Raj):** the constants `Q_GRID`, `GAP_RANGE`, `SELECTION_FAULTS`, `BUDGET_PER_24H` and `TIE_TOL`, and the functions `n_range`, `limits_at`, `lowest_stable_q`, `selection_score`, `choose`. `lowest_stable_q` takes a function from q to ratio tracks, so the week 3 alarm baseline can reuse it.
  - **`tests/test_alerting.py` and `tests/test_calibrate.py`:** 84 hand-built cases, each with its expected values worked out in a comment. They cover:
    - the ratio and its refusals
    - on-delay and off-delay edges
    - a window that uses warm-up samples, and n = 10 reaching exactly sample 1
    - the memory bound
    - no look-ahead, checked by truncating the input and by changing future samples
    - grouping merging notifications across a dip
    - pooled linear-percentile limits
    - a lucky pass below a failure being skipped, with the top-down scan checked by recording which q values were asked for
    - the budget pooled over runs, with warm-up excluded
    - equal fault weights, with 3, 9 and 15 ignored
    - the tie rules
  - **Checking the expected values:** the tests were run against a throwaway reference implementation in the session scratchpad, outside the repo, and all 84 passed.
- **Tests:** `pytest -q` gives 83 failed, 390 passed, 1 deselected. The 83 failures are all `NotImplementedError` from the stubs, and they pass once Raj implements `alerting.py` and `calibrate.py`. The one new test that already passes checks the constants.
- **Unsure about:**
  - **Calibrating exactly to the budget.** Tuning q exactly to 1 per 24 h on calibration makes dev likely to land a little above it (a winner's-curse effect). Dev false alerts, with an interval, will show how much. There's no margin in the protocol, and I'm not proposing one before seeing dev.
  - **The off-delay adds to "share still flagged".** It holds the alert G samples after clearing, which raises the persistence metric slightly. Delay and detection are unaffected.
- **Decisions needed:**
  - **The selection subsample for session 4:** a seed for the 100 forest-ceiling run numbers, and where the list lives. I propose `dataset/selection.yaml`, written once like `splits.yaml`, with its SHA-256 in `dataset/manifest.yaml`.
  - The Yin 2012 component count (Raj, from the full text).
  - Still open from week 1: the onset-to-divergence window; McNemar against a paired bootstrap; and how to report a paired delay comparison when resamples hit ∞ − ∞.

### 2026-09-27: week 2 session 3 (continued), alerting and calibration implemented and reviewed
- **Changed:**
  - **`app/detector/alerting.py` and `eval/calibrate.py`:** implemented by Raj, with step-by-step guidance from the Claude.ai chat, against `tests/test_alerting.py` and `tests/test_calibrate.py`. Claude reviewed them and didn't change them.
  - **Review:** saved word for word to `~/Desktop/review-w2s3.md`, outside the repo. The implementation is correct against decisions 52–54.
    - Your vectorised `persist` and `group` matched the plain-loop reference on 3,000 random cases, with 0 mismatches.
    - The findings, for Raj to act on or not:
      1. **Design:** on synthetic calibration-sized data, (n = 10, G = 20) passed the budget at every grid value, so q landed on the grid floor (95.00). The floor then sets the limit, not the budget.
      2. **Speed:** about 35 ms per grid step (ratios 12, tracks 11, counting 13). Up to 12.7 s per (n, G), and at most about 45 min for all 210 settings. The session 4 driver can reuse the ratio tracks per q across settings.
      3. **Non-integer n or gap** gives `TypeError` or `IndexError` instead of `ValueError`, and `True` is accepted as n = 1.
      4. **Small gaps:** `n_range` accepts negative lags; `limits_at` passes NaN through (caught later by `plant_ratio`); the budget comparison is a float comparison against 1.0.
    - None of these affects results today.
  - Scratch timing and equivalence scripts are in the session scratchpad, not in the repo.
- **Tests:** `pytest -q` gives 473 passed, 1 deselected.
- **Unsure about:** the floor finding comes from synthetic data. Whether real calibration data reaches `Q_GRID[0]` will only show in the session 4 run.
- **Raj's decisions on the review:**
  - **Finding 1 (decision 55):** the grid floor stays at 95.00 on purpose. A setting that meets the budget at the floor stays eligible. The session 4 driver flags it in the run record with the share of the budget it uses. Recorded in `docs/decisions.md`, and in `eval/PROTOCOL.md` under Detection → Limits.
  - **Finding 2:** no change. The driver reuses the ratio tracks per q (session 4).
  - **Findings 3 and 4:** no change now. They stay as known minor items:
    - `persist` or `group` with a non-integer n or gap raises `TypeError` or `IndexError` instead of `ValueError`, and `True` is accepted as n = 1
    - `n_range` accepts negative lags or warm-up
    - `limits_at` passes NaN through (caught later by `plant_ratio`)
    - the budget check is a float comparison against 1.0
- **Decisions needed:**
  - **The selection subsample:** the seed and the file (proposed: `dataset/selection.yaml`, write-once, with its SHA-256 in the manifest).
  - The Yin 2012 component count (Raj).
  - Still open from week 1: the onset-to-divergence window; McNemar against a paired bootstrap; and how to report a paired delay comparison when resamples hit ∞ − ∞.

### 2026-09-27: week 2 session 4, selection runs, calibration driver, calibration and dev check
- **Changed:**
  - **`dataset/selection.py` (Claude):** draws the 100 selection run numbers once, seed 20260929, from forest-ceiling. It follows `splits.py`: write-once, with its SHA-256 checked against the manifest. The file also records the SHA-256 of the splits file it was drawn from. Loading refuses dev or authoring numbers even when the checksum matches.
  - **`dataset/selection.yaml`:** written once by Raj with `python -m dataset.selection --write`. Its SHA-256 is in `dataset/manifest.yaml` (`selection:`). Committed as d47ba5f.
  - **`eval/calibrate_driver.py` (Claude):**
    - finds the model's `fit_pca` record by the model's SHA-256 and takes the warm-up from it
    - scores the calibration pool once, and runs `lowest_stable_q` for all (n, G)
    - scores the selection runs of the 12 selection faults once, then scores each eligible setting and calls `choose`
    - writes `data/models/pca_static_limits.json` (gitignored) and a `calibrate_pca` run record, which has every setting's q, score, floor flag and budget share (decision 55)

    It never loads dev. The limits per q are cached; the ratio tracks aren't, since keeping all 500 would take about 300 MB.
  - **`eval/check_dev.py` (Claude):** a separate command. It checks that the model and limits belong to one recorded calibration run, then reports normal dev false alerts per 24 h with a 2,000-resample percentile bootstrap over run numbers (seed 20260930).
  - **Calibration (Raj, d47ba5f, clean tree):** record `eval/runs/20260927T150527Z_calibrate_pca.json`.
    - 150 calibration runs; selection of 100 runs × 12 faults.
    - **All 210 settings are eligible.** 147 are pinned at the grid floor (q = 95.00): every setting with n ≥ 4. For n = 1–3, q is 99.89–99.90, 98.44–98.57 and 95.49–96.02.
    - **Chosen: n = 3, G = 15, q = 95.57,** with T²lim = 21.532 and SPElim = 13.099. It's not at the floor.
    - On calibration: 153 notifications in 3,682.5 h, which is 0.997 per 24 h (99.7% of the budget).
    - Selection score 0.975, per-fault rates: 1.0 for faults 1, 2, 4, 5, 6, 7, 8, 11, 12 and 14; 0.96 for fault 13; 0.74 for fault 10. These are selection figures on forest-ceiling runs, not dev results, and aren't for reporting.
  - **Dev check (Raj, d47ba5f, clean tree):** record `eval/runs/20260927T150758Z_dev_false_alerts.json`. 50 normal dev runs, 1,227.5 h scored, 47 notifications, **0.919 false alerts per 24 h (95% interval 0.665 to 1.173)**, against a budget of 1.0.
- **Tests:** `pytest -q` gives 502 passed, 1 deselected. 29 are new:
  - 12 in `tests/test_selection.py`
  - 11 in `tests/test_calibrate_driver.py`: the limits equal the calibration percentiles, the chosen setting equals `choose` applied to the recorded table, every eligible setting is within the budget, the floor is flagged, only calibration and selection data are loaded, and the refusals come before any loading
  - 6 in `tests/test_check_dev.py`: the reading equals a direct count, only normal dev is loaded, the same seed gives the same interval, and the provenance refusals

  The runs are separate and add no tests.
- **Unsure about:**
  - **The (n, G) choice is decided by one run.** The winner's score (0.975) is higher than (3, 13) and (3, 14) (0.9742) by 1/1200, one detection among the 1,200 selection runs. The tie tolerance is 1e-12, so this counts as a real difference under decision 54. The choice of G within n = 3 is therefore close to noise. n = 3 itself is clearer: its best score beats n = 2 (0.9725) and n = 4 (0.9683).
  - **G = 15 is a 45-minute off-delay.** Each alert stays on 45 min after the ratio clears. That raises "share still flagged", and the UI band will show Alert through the hold. Detection and delay are unaffected.
  - **Dev is under budget, but the interval reaches 1.173.** The point estimate (0.919) shows no winner's-curse effect. With 50 runs, though, dev can't rule out a rate slightly above budget.
  - **Floor settings use much less of the budget.** For n ≥ 4 the budget share at the floor falls from 0.398 to 0.026. So for long persistence, the floor, not the budget, sets the limit. That's what decision 55 accepted, and none of those settings won.
  - **A test I promised isn't written yet.** It should check that the committed `dataset/selection.yaml` matches the manifest and the draw, like `test_splits.py` does for the splits. Raj ran the write himself, so the test is still to do.
  - **A small in-sample effect in the selection runs (no change).** Selection runs from fit- or calibration-pool numbers share samples 1–20 with runs used to fit the model or set the limits. That touches only the pre-onset samples.
- **Decisions needed:**
  - None new from these runs; the chosen setting follows decisions 53–55 as written.
  - Still open: the Yin 2012 component count (Raj); the onset-to-divergence window; McNemar against a paired bootstrap; how to report a paired delay comparison when resamples hit ∞ − ∞; and moving the replay data to a Neon historian (later).

### 2026-09-27: week 2 session 5, published-number check recorded (decision 56)
- **Changed:** docs only.
  - **`docs/decisions.md`:** decision 56 (Raj's).
    - **Table:** Yin, Ding, Haghani, Hao and Zhang (2012), *J. Process Control* 22(9) 1567–1581, doi:10.1016/j.jprocont.2012.06.009. It's the per-fault detection-rate table for PCA T² and SPE, cited by later papers as Table 4.
    - **Variable set:** 33 variables (22 continuous measurements and 11 manipulated variables).
    - **Components:** to be confirmed from the full text; otherwise k = 12, reported as a deviation.
    - **Method:** the paper's per-sample rate at its 99% limit, on our dev runs. It checks the method, not identical data.
  - **`eval/PROTOCOL.md`, Detection → Published-number check:** the three _TBD_s are replaced with the table, the variable set and the component rule, with the same method sentence and a pointer to decision 56.
  - **Checked (read-only):** the 33 fast tags map exactly to the first 22 continuous measurements and the 11 manipulated variables in `ingest/tag_map.yaml`, so Yin's variable set equals the production tag set.
  - Raj's earlier answer in chat: the 99% limits are theoretical, as published. That's an F-distribution limit for T² and the Jackson–Mudholkar limit for SPE. It isn't in PROTOCOL yet (see below).
- **Tests:** none (docs only).
- **Unsure about:**
  - **The table number:** "Table 4" comes from later papers citing Yin, not from the paper itself, and it's recorded that way. The component count is still unconfirmed.
  - **Dev runs aren't the paper's test runs:** they're training runs, with 500 samples and onset after sample 20. The paper's test runs have 960 samples and onset after 160. So the post-onset stretch is 480 samples here against 800 there. That's part of "method, not identical data".
- **Decisions needed:**
  - **The component count (Raj),** from the full text before the check runs.
  - **The kind of 99% limit, in PROTOCOL:** Raj chose theoretical in chat. Write it into PROTOCOL: an F-distribution limit for T² and the Jackson–Mudholkar limit for SPE at α = 0.01, fitted on the fit pool. They're PCA limits, so they're Raj's code: Claude writes stubs and hand-built tests.
  - **What counts as agreement:** not decided. My proposal is per-fault rates for T² and SPE on the dev runs of open faults except 3, 9 and 15, with agreement within 10 points; report how many agree and list those that don't, with no overall pass or fail.
  - **The committed-selection test** is still to write: `dataset/selection.yaml` against the manifest and the draw.
  - Still open: the onset-to-divergence window; McNemar against a paired bootstrap; how to report a paired delay comparison when resamples hit ∞ − ∞; and moving the replay data to a Neon historian (later).

### 2026-09-27: week 2 session 6, thin slice backend
- **Changed:**
  - **Dependencies (approved):** fastapi 0.141.1, uvicorn 0.54.0 and httpx 0.28.1, with 13 transitive packages, pinned in `requirements.txt`.
  - **`app/detector/bundle.py` (Claude):** loads a bundle folder (`model.npz` and `limits.json`). The self-test refuses:
    - a model whose SHA-256 doesn't match the limits
    - record checksums that aren't SHA-256s
    - limits that aren't positive, persistence that breaks decision 52, or non-integer settings
    - tags that aren't the register's measurements and valves in order (read from `library/tags.yaml`, not `ingest/`)
    - wrong array shapes, NaN, a zero scale, kept eigenvalues that aren't the leading ones or aren't descending, or loadings that aren't orthonormal
    - a known-answer failure: scoring the fit mean must give T² = SPE = 0

    This closes week 1 finding 3.
  - **`app/detector/replay.py` (Claude):**
    - reads historian CSV rows (`ts, tag, value, quality`) and ignores tags outside the model
    - scores as of `upto`, using only rows up to that time, through `pca.scores`, then `alerting.plant_ratio`, then `alerting.alert_track`: the same functions calibration used
    - bands:
      - the warm-up is Unknown ("warm-up")
      - from the first sample with a missing or non-good tag, or a time step other than 3 min, everything is Unknown ("data") and scoring stops
      - otherwise Alert or Normal, with the ratio
  - **`app/api.py` (Claude):** `create_app()` with `GET /health`, `GET /replay/info` and `GET /replay/status?upto=`.
    - The bundle is self-tested at startup; if it fails, or the stream is missing, `/health` and `/replay/*` return 503 with the reason, and nothing is scored.
    - CORS allows only the origins in `ALLOWED_ORIGIN`, with none by default.
    - There are only GET routes (advisory).
    - `/replay/info` says the Watch band isn't built yet.
  - **`eval/build_bundle.py` (Claude):** builds `app/bundles/pca_v1/` from `data/models/pca_static.npz` and `pca_static_limits.json`. It adds the SHA-256 of the fit and calibration run records to `limits.json`; each must match exactly one record. It builds in a temporary folder, self-tests, then moves the result into place, and never overwrites a bundle.
  - **`ingest/export_replay.py` (Claude):** a mechanical choice: fault 13 on the lowest dev run number (Raj's rule).
    - Writes `app/replay/run.csv`: 33 fast tags, plant names, a synthetic clock from 2026-01-05T06:00:00Z in 3-min steps, values via `repr()` so float32 round-trips exactly, and no run, fault or sample columns.
    - Writes `eval/replay_source.yaml` (builder side): fault, run, pool, the CSV's SHA-256, rows, and the commit and dirty flag.
    - Never overwrites either file.
  - **Leak scan:** `tests/test_leak_scan.py` now scans `app/api.py`, `app/replay/` and the bundle's text files with the full pattern set. `tests/test_api.py` scans every live response body, including errors, and checks for no `run`, `fault` or `sample_number` keys. `tests/test_thin_slice_artifacts.py` scans a live API on the committed files.
  - **CI:** `.github/workflows/ci.yml` runs `pytest -q` on push and pull request, on Python 3.13, with no data and no secrets.
  - **CLAUDE.md:** commands for running the API, building the bundle and exporting the replay, and the CI line.
  - **The test I owed:** the committed `dataset/selection.yaml` against the manifest, the rules and the seeded draw (added to `tests/test_selection.py`).
  - **Not run yet:** `python -m eval.build_bundle` and `python -m ingest.export_replay`. They run after Raj commits, so the replay source records a clean commit.
- **Tests:** `pytest -q` gives 572 passed, 4 skipped, 1 deselected. 66 are new:
  - `test_bundle.py` (26)
  - `test_replay.py` (17): float32 round trip; bands and ratios identical to the calibration driver's tracks, with Normal before a step and Alert after it; as-of prefixes; each kind of bad data giving Unknown from there on with earlier samples unchanged; malformed CSVs
  - `test_api.py` (14)
  - `test_export_replay.py` (7)
  - `test_build_bundle.py` (4)
  - the leak scan (1)
  - the committed selection (1)

  The 4 skipped are `test_thin_slice_artifacts.py`, which runs once `eval/replay_source.yaml` exists; from then on a missing or changed file fails.
- **Unsure about:**
  - **The CSV is larger than I planned:** 500 samples × 33 tags = 16,500 rows. With exact `repr()` values it should be roughly 0.9 MB, not the "about 100 KB" I estimated in the plan. Exact values are what make the replay score identically to evaluation. Rounding to 9 significant digits would shrink it about a third, but the replay would no longer be bit-identical.
  - **The stream start reveals the onset to anyone who knows the convention:** a training run's fault starts 1 h in, between samples 20 and 21, which is 07:00 on the synthetic clock (sample 1 is 06:00). The UI viewer is a human. For the agent (week 6), the as-of evidence tools must not expose the stream start or the time since the stream began.
  - **Starlette deprecation:** starlette 1.7 warns that `httpx` in its test client is deprecated in favour of `httpx2`. Tests pass. Switching needs a new dependency, so it's left for Raj.
  - **Leftover blank lines:** `app/detector/alerting.py` has four trailing blank lines that I didn't add, probably from the IDE. Raj decides whether to keep them.
  - **Replay stops at the first bad sample:** a stand-in until the data-quality layer exists (decision 51). A single gap turns the rest of the stream Unknown.
- **Decisions needed:**
  - How the replay resumes after a data gap, once the data-quality layer is built: reset the engine with a new warm-up, or bridge short gaps.
  - Whether to move the test client to `httpx2`.
  - Still open: the Yin 2012 component count and the agreement band; theoretical 99% limits into PROTOCOL; the onset-to-divergence window; McNemar against a paired bootstrap; how to report a paired delay comparison when resamples hit ∞ − ∞; moving the replay data to Neon (later).

### 2026-09-27: week 2 session 7, web page and deploy config
- **Changed:**
  - **Session 6 artifacts (Raj, committed before this session):** `app/bundles/pca_v1/`, `app/replay/run.csv` and `eval/replay_source.yaml`. Raj's local replay: 9 Unknown, 56 Normal, 435 Alert, first alert at 09:15 (sample 66).
  - **Raj's test change (65a1352, before this session):** the replay-ratio tests in `tests/test_replay.py` now compare ratios to 12 significant digits (`RATIO_REL = 1e-12`), not exact equality, so they pass on CI's maths libraries. Bands are still compared exactly. So the session 6 entry's "bands and ratios identical" now means identical bands and ratios equal to about 12 significant digits. CI is green.
  - **`web/index.html` (Claude):** a static page, with no build step and no external scripts or fonts. It shows:
    - the current band as a labelled pill, with the Unknown reason (warm-up, missing data, or "holding" during the off-delay)
    - the current ratio against the limit of 1, with a meter
    - plant time, and the band counts so far
    - a chart: the ratio on a log scale with the limit line, over a band strip per sample
    - Play/Pause, Step and Reset controls, plus a speed setting of 1, 4 or 16 samples per tick. They call `/replay/status` with an increasing `upto`, one request at a time.
    - notes: advisory only, the Watch band not built (taken from `/replay/info`), as-of scoring, and the warm-up
    - a "waking the server" message after 3 s, for Render's cold start

    The API base comes from the hostname: `localhost`, `127.0.0.1` or `file://` use `http://127.0.0.1:8000`; anything else uses the single constant `RENDER_API_URL`, marked "Fill this in after the Render deploy". It uses light and dark colours, works at phone width, and never shows a fault or run number.
  - **`web/vercel.json`:** a static site (`cleanUrls`, and `nosniff` and referrer-policy headers), with no builds, functions or rewrites.
  - **`render.yaml`:** App 2's pattern. `runtime: python`, `region: singapore`, `plan: free`, `buildCommand: pip install -r requirements-app.txt`, `startCommand: uvicorn app.api:app --host 0.0.0.0 --port $PORT`, `healthCheckPath: /health`, `PYTHON_VERSION` "3.13", and `ALLOWED_ORIGIN` with `sync: false`. There's no `DATABASE_URL` and no `rootDir`, because the app reads `library/tags.yaml` from the repo root.
  - **`requirements-app.txt`:** 15 pins, derived rather than guessed. They're the third-party packages `app/` imports (fastapi, numpy, PyYAML), uvicorn, and every dependency of those from their installed metadata. There's no pandas, pyarrow, matplotlib, pytest or httpx on the server.
  - **Leak scan:** `web/` is added to the served-text scan in `tests/test_leak_scan.py`.
  - **CLAUDE.md:** the command for running the page locally (API with `ALLOWED_ORIGIN=http://localhost:8080`, and `python -m http.server 8080 -d web`).
- **Tests:** `pytest -q` gives 587 passed, 1 deselected. The 4 artifact tests from session 6 now run and pass. 11 are new:
  - `tests/test_requirements_app.py` (5): every app pin equals the `requirements.txt` pin; everything `app/` imports is installed, plus uvicorn; the list is closed under runtime dependencies; no data or test tooling is deployed; and the `render.yaml` fields
  - `tests/test_web.py` (6): one marked API constant and the local rule; the advisory and Watch notes; only `/health`, `/replay/info` and `/replay/status`, all GET; no external scripts or URLs; no run or fault number wording; a static Vercel config
- **Local smoke test (Claude):** uvicorn with `ALLOWED_ORIGIN=http://localhost:8080`.
  - `/health` gave 200 with the CORS header for that origin, and the self-test passed.
  - `/replay/info` gave 500 samples, 06:00 to 06:57 the next day.
  - `/replay/status` up to 23:57 gave 360 samples: 9 Unknown, 56 Normal, 295 Alert, with the first alert at 09:15. That matches Raj's run.
  - The page wasn't opened in a browser by Claude: Raj checks it by eye.
- **Unsure about:**
  - **`PYTHON_VERSION: "3.13"`** (Raj's value): I believe Render accepts major.minor and uses the latest patch. If the build log says otherwise, set it to 3.13.15, the version the pins were resolved on.
  - **The dependency closure test evaluates markers on macOS.** The only platform-marked dependencies in this set are Windows-only, so Linux on Render installs the same list.
  - **`app/detector/alerting.py`** again shows a trailing-newline change I didn't make.
- **Decisions needed:** none new. Still open: the Yin 2012 component count and the agreement band; the theoretical 99% limits in PROTOCOL; how the replay resumes after a data gap; `httpx2`; the onset-to-divergence window; McNemar against a paired bootstrap; how to report a paired delay comparison when resamples hit ∞ − ∞; Neon (later).

### 2026-09-28: week 2 session 7 (continued), deployed
- **Changed:**
  - **Committed by Raj:** 4e95144 (the session 7 page and deploy config) and 9f2c203. The second commit set `RENDER_API_URL` in `web/index.html` to the Render URL, and updated `tests/test_web.py` to allow that URL in place of the placeholder.
  - **Deployed by Raj (by hand, following the session 7 steps):**
    - **API:** https://plant-health-api.onrender.com (Render blueprint from `render.yaml`, Singapore, free plan).
    - **Page:** https://plant-health-rca-agent.vercel.app (Vercel, root directory `web/`, static).
    - `ALLOWED_ORIGIN` on Render is set to the Vercel URL in the dashboard. Raj checked CORS and `/health` with curl.
  - **CLAUDE.md:** a new "Deployment" section with both URLs, where `ALLOWED_ORIGIN` lives, the cold-start note, and that Vercel preview URLs aren't allowed.
- **Tests:** `tests/test_web.py` passes with the real URL. No new tests.
- **Unsure about:**
  - Whether Render took `PYTHON_VERSION` "3.13" as written or needed the patch version. The deploy works either way. If the dashboard shows a different value from `render.yaml`, align them.
  - Nothing checks the deployed site automatically. A stale bundle or a CORS change would only show up by hand. A scheduled health check is a later item, not in scope.
- **Decisions needed:**
  - Week 2's "done when" is "an alert shows in the UI, and the referrer gets the link". The alert shows. Sending the link is Raj's step and isn't recorded here yet.
  - Still open: the Yin 2012 component count and the agreement band; the theoretical 99% limits in PROTOCOL; how the replay resumes after a data gap; `httpx2`; the onset-to-divergence window; McNemar against a paired bootstrap; how to report a paired delay comparison when resamples hit ∞ − ∞; Neon (later).

### 2026-09-28: week 3 session 1, decision 57 and week 3 plan
- **Changed:** docs only.
  - **`docs/decisions.md`:** decision 57 (Raj's), under a new heading "Week 3 decisions, 28 September 2026".
    - Detection stays scored from the documented onset (20 in training runs, 160 in testing runs). Nothing is credited or dropped by comparing with the fault-free twin.
    - A diagnostic column gives the share of detections that came before the run first differs from its twin (the normal run with the same run number).
    - First divergence uses the detector's own input tags, with exact float32 equality. "Before" means notification sample < divergence sample.
    - It's computed on dev. On test it's reported only if the test twins share streams, which is checked once at the frozen test run and logged.
  - **`eval/PROTOCOL.md`, Detection metrics:** a new "Before divergence (diagnostic)" bullet with the same rules. The per-fault table gains a "Detected before divergence" column after "Chance rate".
  - **`docs/PLAN.md`:** a new "Schedule notes" section. The Watch band moves to after week 4's RBC, and uses each group's joint RBC as its statistic. The page keeps "Watch isn't built yet" until then.
  - **Week 3 plan approved.** Today: sessions 1–3, each stopped for review and commit.
    1. Decision 57 (this session).
    2. Dev detection table v1 for static PCA, with the divergence metric (stubs for Raj) and `eval/dev_table.py` (Claude).
    3. Alarm baseline: decision 58, then stubs and tests.

    Later:

    4. Alarm calibration and lead time.
    5. Loop map.
    6. Masked-fault rule and valve headroom.
    7. DPCA lag rule, stubs and tests.
    8. DPCA fit, calibration and table rows, with the selection rule applied.
    9. Week close.

    Watch per group follows RBC in week 4.
  - **Raj's answers, to record as decisions in their sessions:**
    - **Alarm baseline (session 3, decision 58):**
      - Deadbands of 0.25σ for temperature and pressure, and 0.5σ for flow, level and analyzers, all of the calibration-pool spread.
      - Valve-at-limit alarms at ≤ 2% or ≥ 98% open, held for n samples.
      - Analyzers are in the realistic list, with a one-update on-delay.
      - The on-delay is per tag, before the OR. Raj adds an optional track-builder argument to `lowest_stable_q` (default: today's `alert_track`), with tests.
      - The ungrouped row uses G = 0 and searches only n and q.
    - **Lead time (session 4):** the median over runs where both detected, with a run-number bootstrap interval over those runs, and four counts (both, only App 3, only alarms, neither). Delay pairs with ∞ are never subtracted.
    - **Masked rule (session 6):**
      - The normal band is the calibration pool's central 99%.
      - A fault is masked if ≥ 50% of its runs meet the rule, decided on the 100 selection runs, not on dev. PROTOCOL → Loops will change from "decided from dev runs" to that.
      - Headroom is the distance to 0% and 100% open.
      - Claude writes the code, and Raj reviews it.
    - **DPCA lag rule (session 7):** Ku, Storer and Georgakis (1995) new-relations rule, with k from the existing parallel analysis and L_max = 4. Whatever L it gives stands, including L = 0; in that case DPCA equals static PCA and the table says so.
    - **Carried items stay out of week 3:** the Yin component count, the agreement band and the theoretical 99% limits are decided together before the published-number check runs.
- **Tests:** none new (docs only). `pytest -q` gives 587 passed, 1 deselected, unchanged. With the opendata test included, 588 passed.
  - `app/detector/alerting.py` again shows only a trailing-newline change that Claude didn't make (probably the IDE). Raj decides whether to commit it.
- **Unsure about:**
  - **The week is over budget.** The estimate is about 17.5 h, including Raj's implementation time, against 15 planned. If sessions 1–6 run long, DPCA (sessions 7–8) moves per the cut line.
  - **Ku's rule and the component edge.** It counts components with the parallel-analysis rule, whose k sits near the λ ≈ 1.03 edge, so relation counts may be off by one. The rule's evidence (k and r_new at each L) goes in the fit record.
- **Decisions needed:**
  - The onset-to-divergence window is closed by decision 57.
  - Still open: the Yin 2012 component count, the agreement band and the theoretical 99% limits (decided together before the check); how the replay resumes after a data gap; `httpx2`; McNemar against a paired bootstrap; Neon (later).
  - The ∞ − ∞ item is closed for lead time by Raj's answer above. It's still open for other paired delay comparisons, where the same rule is proposed for PCA vs DPCA.

### 2026-09-28: week 3 session 2, dev detection table v1: divergence stubs, driver, tests
- **Changed:**
  - **`eval/metrics.py` (stubs for Raj, decision 57):**
    - `first_divergence(run, twin)`: the 1-based first sample where any column differs, by exact equality, or None if the runs are identical. It refuses non-2-D input, shape mismatches, NaN and inf.
    - `before_divergence_share(detections, divergences)` returns (before, detected). Misses are left out. "Before" means notification < divergence, and a run that never diverges counts as before. It refuses a length mismatch and a divergence that isn't None or an integer ≥ 1 (bool refused, numpy integers accepted).
  - **`tests/test_metrics.py`:** 25 new hand-built cases, each with a worked comment. The header now points to decision 57 instead of "not tested".
  - **`eval/dev_table.py` (Claude):**
    - **Checks before loading anything:** a clean tree, then that the limits file came from one `calibrate_pca` record (reusing `check_dev.calibration_record_for`) and that the model matches. It refuses lags ≠ 0 until session 8.
    - **Loads:** only `load_normal("dev")` and `load_faulty(f, "dev")` for f = 1..15.
    - **Scoring:** through `calibrate_driver.score_runs` and `tracks`, the same path as calibration.
    - **Per fault:**
      - rate with interval
      - before divergence (count of detected), on the model's own input columns against the normal dev run with the same number; a run that differs from its twin at or before sample 20 stops the run (decision 49)
      - median delay and IQR, with the median's interval
      - share still flagged (the mean over detected runs, with the count)
      - family
    - **Summary:** the equal-weight mean over the 12 faults, and over 3, 9 and 15 separately. Each has a joint run-number bootstrap and refuses faults with different run numbers.
    - **Last row:** normal dev false alerts per 24 h with an interval, the hours, and the chance rate with an interval.
    - **Intervals:** every one uses seed 20261001, so every statistic sees the same draws. Per-run values are computed once with the metric functions and looked up inside the bootstrap.
    - **Outputs:** a `dev_table_<detector>` record, plus `data/tables/<stamp>_dev_table_<detector>.md`, rendered from the record's stored values. The record holds the table's SHA-256.
    - "Right place", "Masked" and "Lead time" read "—".
  - **`tests/test_dev_table.py`:** 17 tests on synthetic runs. They cover:
    - only dev loaded, each fault once
    - rows equal direct metric calls
    - detections before a late divergence are counted
    - refusal of a divergence before onset
    - fault keys 1–15 only, and no 16–20 anywhere in the record
    - the table equals `render` of the saved record
    - the same seed gives the same numbers
    - refusals before loading
    - equal-weight means, and unequal run numbers refused
    - the normal row checked by hand
    - rendering of ∞ and "—"
- **Tests:** `pytest -q` gives 32 failed, 596 passed, 1 deselected.
  - All 32 failures are `NotImplementedError` from the two stubs: 25 in `test_metrics.py`, and the 7 run-level tests in `test_dev_table.py`.
  - Against a throwaway reference implementation in the session scratchpad, outside the repo, all 628 pass.
- **Unsure about:**
  - **Share still flagged is aggregated as the mean over detected runs.** PROTOCOL defines it per run but doesn't say mean or median. I used the mean, with the count of runs.
  - **The chance rate is one number, repeated in each fault's row.** It comes from the normal dev runs at fake onset 20, so it's the same for every fault. It's stored once in the record.
  - **The summary rows use a joint bootstrap** (one draw of run numbers brings every fault's run along), per rule 3. Per-fault intervals resample that fault's runs by the same draws.
- **Decisions needed:** none new.
- **Next (Raj):** implement the two stubs, then `pytest -q`. After committing, run `python -m eval.dev_table` on a clean tree.
