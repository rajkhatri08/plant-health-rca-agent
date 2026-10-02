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

### 2026-09-28: week 3 session 2 (continued), divergence functions and first dev table
- **Changed:**
  - **`eval/metrics.py`:** Raj implemented `first_divergence` and `before_divergence_share` against the session 2 tests (committed as 28dd675). Claude didn't review the implementation in this session; the tests pass.
  - **Dev table (Raj, 28dd675, clean tree):** `python -m eval.dev_table`.
    - Record `eval/runs/20260928T064324Z_dev_table_pca_static.json`; table `data/tables/20260928T064324Z_dev_table_pca_static.md` (gitignored, its SHA-256 in the record).
    - The record isn't committed yet.
  - **Results (static PCA, n = 3, G = 15, q = 95.57; 50 dev run numbers):**
    - **Mean detection over the 12 faults:** 0.982 (95% interval 0.972 to 0.990). The selection score on forest-ceiling runs was 0.975.
    - **Faults 3, 9, 15:** 0.06, 0.08 and 0.12 (mean 0.087, interval 0.02 to 0.16), against a chance rate of 0.06 (0.00 to 0.14). That's at chance, as expected.
    - **Before divergence:** 0 detections in every fault, including the 13 detections in faults 3, 9 and 15. So no reported detection was luck by construction.
    - **Detected in every run (1.00):** faults 1, 2, 4–8, 11, 12 and 14.
      - Median delay of 9 min: faults 4, 5, 6, 7 and 14.
      - Longer: fault 1 at 15 min, 12 at 24, 11 at 27, 2 at 45 and 8 at 52.5.
    - **Fault 13:** 0.98 (0.94 to 1.00), with a median delay of 124.5 min (IQR 96–170.25).
    - **Fault 10:** 0.80 (0.68 to 0.90), with a median delay of 139.5 min (IQR 97.5–224.25).
    - **Share still flagged:** 1.00 or close for most faults. Fault 5 is at 0.52, fault 10 at 0.765 and fault 11 at 0.993. Fault 5 is a masked-fault candidate for session 6 (Raj).
    - **Normal dev:** 47 notifications in 1,227.5 h, 0.919 per 24 h (0.645 to 1.212).
- **Tests:** `pytest -q` gives 628 passed, 1 deselected.
- **Unsure about:**
  - **9 min is the floor, not a measured speed.** With n = 3 and the onset after sample 20, the earliest possible notification is sample 23, which is (23 − 20) × 3 = 9 min. So faults 4, 5, 6, 7 and 14 are detected as fast as the persistence setting allows, and their delay can't separate detectors that are both at that floor. DPCA can't beat it either, unless its search picks n < 3.
  - **"Step faults at 9 min" isn't quite the grouping.** The 9 min group is 4, 5, 6, 7 and 14. Faults 1 and 2 are also steps but take 15 and 45 min, and 14 isn't a step. Worth wording carefully in the write-up. (Raj's summary, not the record.)
  - **Two dev false-alert intervals exist.** `check_dev` gave 0.665 to 1.173 (seed 20260930); the dev table gives 0.645 to 1.212 (seed 20261001). The count, hours and rate are identical. Only the bootstrap seed differs, which shows how much a 2,000-resample percentile interval moves with the seed. The table's interval is the one to report with the table. It isn't a new decision; noting it so the two records don't look contradictory.
  - **Fault 5's low share still flagged** fits controller compensation: the alert clears as the loop absorbs the disturbance. It's a candidate only; the masked rule is decided on the selection runs in session 6, not on this dev result.
  - The delay-median intervals carry float interpolation tails (for example 119.9625…). They're correct values, and the table prints them as they are.
- **Decisions needed:** none new.

### 2026-09-28: week 3 session 3, alarm baseline: decision 58, stubs, tests
- **Changed:**
  - **`docs/decisions.md`, decision 58 (Raj's answers from the week 3 plan):**
    - per-tag high and low limits at the same calibration percentile, (100 − q)/2 in each tail
    - deadbands of 0.25σ for temperature and pressure, and 0.5σ for flow, level and analyzers
    - valve-at-limit alarms at ≤ 2% or ≥ 98% open, held for n samples
    - realistic and every-tag lists; analyzers get a one-update on-delay
    - on-delay per tag, before the OR
    - an ungrouped row with G = 0
    - calibration by decision 54's search, through a track-builder argument on `lowest_stable_q`
    - lead time as agreed
  - **`eval/baselines/__init__.py` and `eval/baselines/alarms.py`:**
    - **Constants (Claude, from decision 58):** `DEADBAND_SIGMA`, `VALVE_LOW` 2.0, `VALVE_HIGH` 98.0, `ANALYZER_ON_DELAY` 1.
    - **Stubs for Raj:**
      - `tag_limits(runs, q, warmup)`: pooled scored-sample percentiles at (100 − q)/2 and (100 + q)/2, per column
      - `tag_spread(runs, warmup)`: pooled ddof-0 σ per column
      - `hysteresis(x, lo, hi, band)`: latched high and low conditions
      - `at_limit(valves)`
      - `plant_track(points, n_per_point, gap, warmup)`: each point's on-delay via `alerting.persist`, then OR, then `alerting.group`, with decision 52's memory bound checked per point
  - **`tests/test_alarms.py`:** 50 hand-built cases with worked comments. They cover:
    - two-sided limits, and warm-up exclusion
    - σ
    - latching and clearing at the band edge, a limit value that isn't an alarm, band 0 as a plain comparison, starting off at sample 1, and independent columns
    - no look-ahead (by truncating the input, and by changing the future)
    - inclusive valve limits
    - the key case: two points taking turns give an unbroken OR, but no alarm with a per-point on-delay of 2
    - mixed on-delays, the off-delay, and the warm-up used by the on-delay but not scored
    - equality with persist, OR and group on random points
    - the memory-bound edge, and refusals
  - **`tests/test_calibrate.py`:** 3 tests for Raj's new `track` argument on `lowest_stable_q`:
    - a custom builder replaces `alert_track`, gets (x, n, gap, warmup, lags), and drives the budget, scanning down as before
    - the budget is pooled over runs
    - passing `alert_track` explicitly gives the same answer as the default
- **Tests:** `pytest -q` gives 52 failed, 628 passed, 1 deselected.
  - 49 failures are `NotImplementedError` from the stubs.
  - 3 are `TypeError` (no `track` argument yet).
  - Against a throwaway reference implementation in the session scratchpad, outside the repo, all 681 pass. That counts the constants test, which already passes.
- **Unsure about:**
  - **The hysteresis latch has unbounded memory.** Once on, a tag stays on until it clears the band, however long ago it latched. It still starts off at sample 1 and uses only samples from the same run, so decision 52's rule (no state from before the run) holds. The memory bound L + n − 1 ≤ 9 is about windows, and the latch isn't a window. As I read decision 52 this is fine, but it's worth saying in the write-up.
  - **Analyzer values are already held in the data** (the last value until the next update), so the stubs need no update-timing logic. The planned "hold-last-value" test became the one-update on-delay (below).
- **Decisions needed** (proposals built into the stubs and tests; easy to change before Raj implements):
  1. **Hysteresis edges:**
     - high turns on at x > hi (strict, like r > 1) and clears at x ≤ hi − band
     - low turns on at x < lo and clears at x ≥ lo + band
     - the state starts off at sample 1
  2. **σ:** the pooled ddof-0 standard deviation of the calibration pool's scored samples, fixed once, not per q.
  3. **The analyzer on-delay of one update:** the alarm fires on the first reading past the limit (on-delay 1 sample of the held series), and it isn't searched with n. That reads PROTOCOL's "at least one sample (one update for analyzers)" as the same minimum in each unit. The other reading is two consecutive readings.
  4. **Compressor power** (signal type `power`, CP-JI-502) has no agreed deadband. I propose 0.5σ, like flow. `DEADBAND_SIGMA` leaves it out until decided, so the session 4 driver would refuse it.
  5. **The every-tag list:** I propose high and low alarms on all 52 tags, including the 11 valves (deadband 0.5σ for valves?), and no valve-at-limit alarms, which belong to the realistic list only. Valves then need a deadband too.
  6. **The valve-at-limit alarm has no deadband.** It clears as soon as the position leaves the ≤ 2 or ≥ 98 zone.

### 2026-09-28: week 3 session 3 (continued), alarm baseline implemented and reviewed
- **Changed:**
  - **`eval/baselines/alarms.py` and the `track` argument on `eval/calibrate.py:lowest_stable_q`:** implemented by Raj, with guidance from the Claude.ai chat, against the session 3 tests (committed as e29abbc). Claude reviewed them and didn't change them.
  - **Raj confirmed three of the session 3 proposals:**
    - alarms turn on at strict edges (x > hi, x < lo) and clear at inclusive ones (x ≤ hi − band, x ≥ lo + band), starting off at sample 1
    - σ is the pooled ddof-0 standard deviation of the calibration pool's scored samples
    - the analyzer on-delay is the first reading past the limit (1 sample of the held series)
  - **Review:** correct against decision 58 and the confirmed details.
    - Raj's vectorised latch (the latest on/off event wins) and `plant_track` matched a plain-loop reference on 3,000 random cases each, with integer values so the edges are hit exactly. There were 0 mismatches.
    - `lowest_stable_q` behaves as before without `track`. With it, only the builder is used, and it gets (value, n, gap, warmup, lags).
    - The findings, for Raj to act on or not:
      1. **Speed, which matters for session 4.** At calibration scale (150 runs × 500 samples × 41 alarmed tags plus 11 valves), one grid step costs about 0.47 s: 118 ms for `tag_limits`, 104 ms for `hysteresis` and 247 ms for `plant_track`. Called naively through `lowest_stable_q`, each (n, G) setting that scans to the grid floor redoes all of it for up to 500 q values. With the 210 settings of decision 54 that's many hours per tag list.
         - The limits, the latched points and the per-point on-delays don't depend on G. Only `group` does.
         - So the session 4 driver should build the points once per q, and the OR of on-delayed points once per (q, n), leaving only `group` per G. That's about 500 × 10 `plant_track`-sized steps per list, roughly 20 minutes, not hours.
         - This is a driver design point for session 4. It needs no change to Raj's functions, but the track builder will need a cache keyed on (q, n).
      2. **`plant_track` with no alarm points returns an always-off stream.** A driver bug that produced an empty tag list would look like a perfectly quiet baseline. Refusing zero points would catch it.
      3. **`plant_track` casts each on-delay with `int()`,** so 2.7 silently becomes 2 and `True` becomes 1. That's the same class as week 2's finding 3 for `persist` and `group`.
      4. **Cosmetic:** the first paragraph of the `lowest_stable_q` docstring still says each value is turned into a track with `alert_track`. The new paragraph on `track` covers it, so this only affects how it reads.
    - None of these affects results today.
- **Tests:** `pytest -q` gives 681 passed, 1 deselected.
- **Unsure about:** the three confirmed details aren't in `docs/decisions.md` yet. Decision 58 still lists only the answers from the plan. Adding them is a small edit for the next session, with Raj's OK.
- **Decisions needed:**
  - **Still open from session 3:**
    - the compressor power deadband (proposed 0.5σ, like flow)
    - the every-tag list (proposed: high and low alarms on all 52 tags, including the valves, which then need a deadband; valve-at-limit alarms in the realistic list only)
    - whether the valve-at-limit alarm has no deadband (proposed: none)
  - **Findings 2 and 3 above:** change or leave.
  - Still open: how the replay resumes after a data gap; `httpx2`; McNemar against a paired bootstrap; Neon (later). The Yin component count, agreement band and theoretical 99% limits are decided together before the published-number check runs.

### 2026-09-28: week 3 session 4a, alarm calibration driver
- **Changed:**
  - **Raj's answers (recorded in decision 58, under "Details confirmed"):**
    - Compressor power 0.5σ.
    - The every-tag list: high and low alarms on all 52 tags, valves at 0.5σ, and no valve-at-limit alarms.
    - Valve-at-limit alarms have no deadband.
    - The three details Raj confirmed after session 3 (hysteresis edges, σ, analyzer on-delay) are now written into decision 58 as well.
    - The question on review findings 2 and 3 came back unanswered, so `plant_track` is unchanged.
  - **`eval/baselines/alarms.py`:** `DEADBAND_SIGMA` gains `"power": 0.5` and `"valve": 0.5`, per the answers. Claude edited only this constant in Raj's file; `tests/test_alarms.py` is updated to match, and its header now says the details are confirmed.
  - **`eval/calibrate_alarms.py` (Claude):** `python -m eval.calibrate_alarms --list realistic|every`.
    - **Lists from `library/tags.yaml`:**
      - realistic: 41 high/low tags (22 measurements, 19 analyzers) plus 11 valve-at-limit alarms
      - every: 52 high/low tags
      - a signal type without an agreed deadband is refused
    - **The search:** σ comes from the calibration pool, computed once. For each q the search asks for, the latched points are built once, and the base track (the OR of on-delayed points, from `plant_track` with G = 0) is cached as packed bits for every n. The track builder given to Raj's `lowest_stable_q` then applies only `alerting.group` for G. That's the speed plan from the session 3 review.
    - **Selection:** each eligible setting is scored on the 100 selection runs × 12 faults at its own q, taking settings in q order so each q's points build once.
    - **The two rows:** the grouped row is `calibrate.choose` over every (n, G); the ungrouped row is `choose` over G = 0 only.
    - **Outputs:** `data/models/alarms_<list>_limits.json` (lists, σ, bands, and each row's n, G, q and per-tag lo/hi), and a `calibrate_alarms_<list>` run record with both rows, their calibration budget and selection rates, and the full settings table with floor flags and budget shares.
    - **Guards:** it never loads dev, and a dirty tree or an existing output is refused before any loading. The warm-up is 9 (decision 52), passed as a parameter so tests can use 3.
  - **`tests/test_calibrate_alarms.py`:** 14 tests on synthetic runs. They cover:
    - both lists' composition and on-delays
    - the cached track equals `plant_track` on directly built points, for several q, n, G and runs, on both lists
    - grouping after the cache equals grouping the raw OR
    - the limits file equals `tag_limits` at each chosen q
    - both rows equal `choose` on the recorded table
    - every eligible setting meets the budget by a direct count, with the recorded budget share
    - only calibration and selection are loaded
    - the every-tag list runs
    - refusals before loading
- **Tests:** `pytest -q` gives 695 passed, 1 deselected.
- **Checked on the real calibration pool (read only, nothing recorded):**
  - One grid step (points plus 10 values of n) takes about 4.5 s for the realistic list and 5.0 s for the every-tag list. One budget check takes about 18 ms.
  - The worst case is 1 to 1.5 h per list. The two lists can run in parallel terminals.
  - At q = 99.99, n = 3, G = 15, both lists give 0.38 false alerts per 24 h, so both can meet the budget.
- **Unsure about:**
  - **The analyzer alarms set a floor that n can't lower.** Their on-delay is fixed at the first reading, so only q suppresses them. At q = 99.99 the 38 analyzer points alone give 0.36 per 24 h on the calibration pool. Expect the realistic list's q to sit high and its settings to differ less across n than PCA's did. That follows from decision 58; it isn't a bug.
  - **The synthetic test data now holds analyzer values for 5 samples,** like real updates. With fresh noise every sample, no setting met the budget in the small test pool, for the reason above.
- **Decisions needed:**
  - Review findings 2 and 3 (`plant_track` with no points, and non-integer on-delays): change or leave. The driver always passes non-empty lists and integer n.
  - **For session 4b (dev rows, lead time, notification counts):**
    - how "per 10 minutes" is counted with 3-minute samples (proposed: 10-minute periods on the clock, with a sample counted in the period its time falls in)
    - how chattering is defined for 3-minute samples (proposed: an alarm point that turns on 3 or more times in 10 samples, which is 30 minutes)
  - Still open: how the replay resumes after a data gap; `httpx2`; McNemar against a paired bootstrap; Neon (later).
- **Next (Raj):** commit, then run `python -m eval.calibrate_alarms --list realistic` and `--list every` on a clean tree.

### 2026-09-28: week 3 session 4a (continued), alarm calibrations and decision 59 (finer q grid)
- **Changed:**
  - **Alarm calibrations (Raj, 239b816):**
    - Records `eval/runs/20260928T103138Z_calibrate_alarms_realistic.json` and `eval/runs/20260928T103200Z_calibrate_alarms_every.json`.
    - Both lists chose q = 99.98 (grouped) and 99.99 (ungrouped). All 21 n = 1 settings were ineligible in both.
    - They're kept as the evidence for decision 59, and superseded.
  - **`docs/decisions.md`, decision 59 (Raj's):**
    - After 95.00 … 99.99 in 0.01 steps, the grid adds 99.991 … 99.999 in 0.001 steps: 509 points, for every detector.
    - Everything else in decisions 54 and 55 stands.
    - *Why:* at the top of the grid, one 0.01 step halves or doubles each alarm point's false rate, so the coarse grid could force the baseline stricter than the budget needs, which would flatter App 3.
  - **`eval/PROTOCOL.md`, Detection → Limits:** the grid sentence now gives both parts (509 points) and points to decision 59.
  - **`eval/calibrate.py`:** the `Q_GRID` line only (Claude, as Raj asked).
  - **`tests/test_calibrate.py`:** the grid test now checks 509 points, the first 500 unchanged, and the nine new ones exactly.
  - **`eval/check_grid_refinement.py` (Claude):** `python -m eval.check_grid_refinement`.
    - **Inputs:** the static-PCA limits file and model. It checks them against the single `calibrate_pca` record (reusing `check_dev`'s provenance check) and loads only the calibration pool.
    - **The rule:** `lowest_stable_q` scans from the top and stops at the first failure. So each setting's new answer follows from `lowest_stable_q` over the nine new points alone plus the old recorded q:
      - if all nine pass, the old q stands (or 99.991, if the old top had failed)
      - otherwise, the scan stops inside the new points
    - **Output:** a `check_grid_refinement` record with, for every (n, G), the old and new q and where the new points became stable, plus the verdict and the chosen setting. It prints the verdict and exits 1 if anything changed.
    - It doesn't re-run the calibration.
  - **`tests/test_check_grid_refinement.py`:** 13 tests. They cover:
    - the shortcut rule's five cases
    - the nine new points
    - on a driver calibration, the shortcut equals a direct `lowest_stable_q` scan of the old grid plus the new points, both as-is and with limits loosened at the top so some scans stop inside the new points (so both branches are tested)
    - the record and verdict, and exit 1 on a change
    - only the calibration pool is loaded
    - refusals before loading
- **Tests:** `pytest -q` gives 708 passed, 1 deselected.
- **Unsure about:**
  - **At 99.999 the alarm limits sit at the extremes of the calibration pool.** Each tail is (100 − q)/2 = 0.0005%, and a tag has 150 × 491 = 73,650 scored samples. So the 0.0005th percentile falls between the lowest and second-lowest values (position 0.37). The limit then rests on one or two samples per tag. That's within decision 59; noting it for when the alarm results come back.
  - **The PCA check should pass.** All 210 static-PCA settings were eligible, so 99.99 already passed for all of them. At a stricter q the limits only rise, which usually lowers notifications, but the grid search itself assumes that isn't guaranteed. That's why it's checked rather than assumed.
  - `eval/baselines/alarms.py` shows only a trailing-newline change that Claude didn't make (probably the IDE).
- **Decisions needed:** unchanged from session 4a (findings 2 and 3; the session 4b count and chattering definitions).

### 2026-09-28: week 3 session 4a (continued), grid check and alarm re-calibration on the refined grid
- **Changed:** runs only (Raj, 2e5db3f, clean tree). No code.
  - **Grid check:** `eval/runs/20260928T104704Z_check_grid_refinement.json`.
    - All 210 static-PCA settings pass at all nine new points, so every stable q is unchanged (0 changed).
    - The chosen setting stands: n = 3, G = 15, q = 95.57. The PCA calibration isn't re-run.
  - **Alarm calibrations on the 509-point grid.** Both lists have all 210 settings eligible, against 189 of 210 on the old grid.
    - **Realistic** (`eval/runs/20260928T105104Z_calibrate_alarms_realistic.json`):
      - n = 1, G = 0, q = 99.992, selection score 0.9533
      - calibration: 123 notifications in 3,682.5 h, 0.802 per 24 h (80% of the budget)
    - **Every tag** (`eval/runs/20260928T105126Z_calibrate_alarms_every.json`):
      - n = 1, G = 0, q = 99.992, score 0.9542
      - calibration: 147 in 3,682.5 h, 0.958 per 24 h
    - **In both lists, the grouped and ungrouped rows chose the same setting.** The best score is at G = 0, and ties go to the smaller G.
    - **Selection rates, both lists:** 1.00 for every selection fault except 10 (0.46 realistic, 0.47 every) and 13 (0.98).
  - **The superseded records** (`20260928T103138Z_…realistic`, `20260928T103200Z_…every`, 500-point grid) are kept as decision 59's evidence.
- **Tests:** unchanged, 708 passed, 1 deselected.
- **Reading the change:**
  - **The earlier gap between the lists, 0.84 vs 0.92, was mostly the coarse grid.**
    - On the old grid no n = 1 setting could meet the budget, so both lists were pushed to n = 2 (q = 99.98 or 99.99).
    - The realistic list suffered most. Fault 4 fell to 0.13 (grouped) against 0.98 for every-tag, and fault 14 to 0.48 against 0.67.
    - With the finer top, n = 1 at q = 99.992 is eligible and wins in both lists. Fault 4 is 1.00 and fault 14 is 1.00 in both, and the gap shrinks to 0.0009: one detection in 1,200 selection runs (fault 10).
    - So the list composition barely matters at the calibrated setting.
  - **Decision 59's concern holds.** The coarse grid had made the baseline stricter than the budget needed. The realistic list now uses 80% of the budget instead of 96% (grouped) or 50% (ungrouped).
  - **n = 1 means no on-delay.** Every alarm point annunciates on the first sample past its limit, and the deadband alone controls chattering. That's worth watching in the chattering count (session 4b).
  - **The limits rest on the extremes.** At q = 99.992 each tail is 0.004%, about 3 samples per tag among 73,650. Each alarm limit sits between the third and fourth most extreme calibration samples of its tag.
- **Decisions needed:** findings 2 and 3 on `plant_track` (still unanswered); the session 4b definitions (next).

### 2026-09-28: week 3 session 4b, alarm rows, operator load and lead time: decision 60, stubs, driver, tests
- **Changed:**
  - **Raj's answers (decision 60, all four as recommended):**
    - **Per 10 minutes and flood:** onset-aligned periods by sample time. There are twelve periods in the 2-h window, (10j, 10j + 10] minutes, with 3 or 4 samples each.
    - **Chattering:** 3 or more turn-ons of one alarm point within 10 samples.
    - **The notification unit:** each alarm point (a tag's high, a tag's low, a valve-at-limit), with its own on-delay and the row's off-delay G applied per point. App 3 counts its one plant stream.
    - **Lead time:** against the realistic grouped row only.
  - **`eval/PROTOCOL.md`, Alarm comparison:**
    - the tag lists as built
    - the definitions above
    - the lead-time rule: the median of (baseline − App 3) over both-detected runs, positive when App 3 is earlier, with an interval over those runs and the four counts
  - **`eval/metrics.py` (stubs for Raj):**
    - constants `NOTIFY_SAMPLES` 40, `PERIOD_MIN` 10, `FLOOD_ABOVE` 10, `CHATTER_TIMES` 3 and `CHATTER_SPAN` 10, and the `LeadTime` tuple
    - `period_counts(notification_samples, onset, …)`
    - `is_chattering(notification_samples, first, last, …)`
    - `lead_time(app, base)`
  - **`eval/baselines/alarms.py` (stub for Raj):** `point_tracks(points, n_per_point, gap, warmup)`, each point's persist then group, for counting per point. Its OR across points equals `plant_track`.
  - **Tests (hand-built, worked comments):**
    - 24 in `tests/test_metrics.py`: period edges (30 min belongs to period 2), 3 or 4 samples per period, the testing onset, chattering edges (9 vs 10 samples apart), window cut-offs, lead-time counts and signs, odd medians, None without both detected, and refusals
    - 9 in `tests/test_alarms.py`: a hand case; OR equals `plant_track` for G of 0, 3 and 15; refusals
  - **`eval/dev_table.py` (Claude), refactored around two detector adapters:**
    - **`PCADetector`:** as before.
    - **`AlarmDetector`:** one row of an alarm list, rebuilt from its limits file (lo/hi, bands, on-delays) through `hysteresis`, `at_limit`, `plant_track` and `point_tracks`. Its divergence inputs are its alarmed tags.
    - **Provenance:** the kind comes from the limits file, which must be the output of exactly one calibration record (`calibrate_pca`, or `calibrate_alarms_<list>`).
    - **Every row** now carries `load`: notifications per episode (mean and max), per 10 min, the peak 10-min count, flood share, chattering points per run, and the share from chattering. The Markdown gains an "Operator load" table.
    - **App 3's rows** carry `lead` against `alarms_realistic_grouped`: the median, its interval over both-detected runs, and the four counts. It refuses an every-tag file, a lead on an alarm row, and mismatched warm-ups, all before loading.
    - **The CLI:**
      - `--row grouped|ungrouped` for alarm files
      - App 3 defaults `--lead-vs` to `data/models/alarms_realistic_limits.json`
      - `--no-lead` leaves the column empty
      - the existing PCA call still works
  - **`tests/test_dev_table.py`:** 13 new tests. They cover:
    - operator load by hand, including flood and no notifications
    - `lead_row` by hand
    - both alarm lists' rows equal direct scoring from the limits file, including their load
    - App 3's lead time and load equal direct calls
    - refusals before loading (no row, a bad row, a row on PCA, lead against every-tag, lead on an alarm row, an altered alarm limits file)
    - CLI routing
    - The fixture calibrates both alarm lists on synthetic plant-like runs first.
- **Tests:** `pytest -q` gives 45 failed, 707 passed, 1 deselected.
  - All 45 failures are `NotImplementedError` from the four stubs: 23 in `test_metrics.py`, 9 in `test_alarms.py` and 13 in `test_dev_table.py`.
  - The session 2 PCA run tests are among them now, because every row computes the operator load.
  - Against a throwaway reference implementation in the session scratchpad, outside the repo, all 752 pass.
- **Not run:** nothing touched dev in this session.
- **Unsure about:**
  - **"Per 10 min" is always the per-episode count ÷ 12,** because every run has the same twelve periods. It's kept because PROTOCOL names it, and the peak 10-min count and the flood share carry the extra information.
  - **The operator load is counted on fault runs only,** in the notification window. Normal-operation load for the alarm rows is just the false alerts per 24 h already in the last row.
  - **With n = 1 and G = 0 (both lists' chosen settings),** grouped and ungrouped alarm rows will be identical. They're run separately anyway, because PROTOCOL lists both rows.
- **Decisions needed:** findings 2 and 3 on `plant_track` (still unanswered).
- **Next (Raj):** implement the four stubs. After committing, on a clean tree:
  - `python -m eval.dev_table` (App 3, with lead time against realistic grouped)
  - `python -m eval.dev_table --limits data/models/alarms_realistic_limits.json --row grouped`, then `--row ungrouped`
  - `python -m eval.dev_table --limits data/models/alarms_every_limits.json --row grouped`, then `--row ungrouped`

### 2026-09-28: week 3 session 4b (continued), dev tables for App 3 and the alarm baseline
- **Changed:**
  - **Raj implemented** `period_counts`, `is_chattering`, `lead_time` and `point_tracks` (1e70fb1). Claude didn't review them in this session; all tests pass.
  - **Runs (Raj, 1e70fb1, clean tree), committed as 02f1893:**
    - `eval/runs/20260928T112351Z_dev_table_pca_static.json`: App 3, with lead time against `alarms_realistic_grouped`
    - `eval/runs/20260928T112413Z_dev_table_alarms_realistic_grouped.json`
    - `eval/runs/20260928T112441Z_dev_table_alarms_every_grouped.json`
    - The ungrouped rows weren't run. Both lists chose G = 0, so ungrouped is the same setting as grouped.
  - **No retuning on dev** (Raj). Nothing here feeds back into calibration or selection.
- **Findings (dev, 50 run numbers). Every figure below is from the three records.**
  1. **The lead-time hypothesis isn't supported on dev.**
     - **Where the realistic alarms (n = 1) are earlier:** on 8 of the 12 summary faults, by 3 to 9 min in median.
       - 9 min on fault 2 (interval −12 to −6)
       - 6 min on faults 4, 5, 6, 7, 12 and 14
       - 3 min on fault 13 (interval −6 to 0)
     - **Where App 3 is earlier:**
       - 3 min on fault 1 (interval 3 to 3)
       - 4.5 min on fault 8 (3 to 6)
       - 10.5 min on fault 10 (−6 to 55.6, over only 24 runs where both detected)
       - 3 min on fault 11 (−3 to 15)
       - Only faults 1 and 8 have intervals above 0.
     - **Where the alarms' lead comes from:** much of it is the persistence floor. With n = 3, App 3 can't notify before sample 23, 9 min after onset. With n = 1, the alarms can notify at sample 21, 3 min after onset. On faults 4, 5, 6, 7 and 14, App 3 is at its 9-min floor and the alarms at their 3-min floor, which is exactly the −6 min. That doesn't change the finding. It says where the gap comes from: the calibrated persistence, not the monitoring statistic.
     - (Raj's summary said 7 faults; the record has 8, listed above.)
  2. **The alarms exceed the budget on unseen normal runs.**
     - **Realistic:** 1.39 false alerts per 24 h (1.08 to 1.70; 71 in 1,227.5 h). The whole interval is above the budget of 1. The chance rate is 0.22 (0.12 to 0.34).
     - **Every-tag:** 1.56 (1.23 to 1.90; 80 in 1,227.5 h), chance rate 0.26.
     - **App 3:** 0.92 (0.65 to 1.21; 47 in 1,227.5 h), chance 0.06 (0.00 to 0.14).
     - **Why, most likely:** at q = 99.992 each per-tag limit rests on about 3 extreme calibration samples, so the limits don't carry over to new runs. App 3's single statistic, at q = 95.57, is set by thousands of samples.
     - **What it means for finding 1:** on dev, the alarm baseline effectively runs at about 1.4 times the budget. That's a looser operating point than App 3's, and it favours the alarms' lead time.
     - **Luck in the alarm detections:** the alarms also have detections before divergence, which App 3 has none of (decision 57). Realistic has 1 of 26 on fault 10 and 2 of 49 on fault 13; every-tag has 1 of 27 and 2 of 50. That's consistent with their higher chance rate.
  3. **Operator load in the first 2 h (decision 60).**
     - **App 3:** 1 notification per episode on every detected fault (mean 1.0; fault 13 has 0.5, fault 11 a maximum of 2), with no floods and no chattering.
     - **Realistic alarms:** up to 65.3 per episode on fault 14 (max 68), all from chattering (share 1.00, 4.0 chattering points per run). 52.5 on fault 7 (max 60), with floods in 4% of 10-minute periods (peak 16). Between 24 and 30 on faults 1, 5, 6 and 12.
     - **Every-tag alarms:** higher again. 99.0 on fault 14 (floods 10%), 66.7 on fault 7 (floods 8%).
  4. **Coverage on fault 10:** App 3 detects 0.80 (median delay 139.5 min), against 0.52 for realistic (231 min) and 0.54 for every-tag. On the 16 runs only App 3 detected, the alarms have no delay to compare. That's why the lead time there covers only 24 runs.
  5. **Share still flagged on fault 4:**
     - App 3 1.00 against realistic 0.01. The realistic alarms clear while the control loop masks the fault.
     - Every-tag gives 1.00: it has high and low alarms on the valves, and the valve carries the fault once the loop compensates. The realistic list has only valve-at-limit alarms, so it loses the fault.
     - This is the masking mechanism session 6 formalises.
     - Fault 7 shows the same pattern, milder: realistic 0.62, every-tag 1.00. So does fault 11: 0.35 against 0.74, with App 3 at 0.99.
- **Summary detection (12 faults):** App 3 0.982 (0.972 to 0.990), realistic 0.958 (0.947 to 0.970), every-tag 0.962 (0.950 to 0.973).
- **Tests:** 752 passed, 1 deselected.
- **Unsure about:**
  - **The comparison isn't at equal false-alert rates on dev,** even though both were calibrated to one budget. Decision 54's rule was applied as written; the alarm baseline overshoots on new runs. How the README states this is Raj's call. The AMOC curve (delay against false alerts per 24 h) in PROTOCOL is the tool that would put both on one axis.
  - **The persistence floor** (finding 1) is a property of the selection (n = 3 won on detection rate, which delay doesn't enter). It isn't a reason to change anything on dev.
- **Decisions needed:** none new from these runs; no retuning on dev. Still open: findings 2 and 3 on `plant_track`; how the replay resumes after a data gap; `httpx2`; McNemar against a paired bootstrap; Neon (later).

### 2026-09-28: week 3 session 5, loop map (decision 61)
- **Changed:**
  - **Sourcing (Claude; web and code in the session scratchpad only):**
    - The Dataverse record names neither the simulator nor the control strategy, and no primary statement was found in secondary sources.
    - Two candidate control codes were read:
      - Ricker's `temexd_mod.zip` (`MultiLoop_mode1.mdl`, the Mode-1 decentralized strategy)
      - the Russell, Chiang and Braatz closed-loop code `temain_mod.f`, from a public mirror, sha256 in decision 61
    - The open data rules out the first: in it the recycle and steam valves are fixed inputs, but all 11 valves vary in the fit pool.
    - The data matches the second: the fit-pool means of all nine fixed-setpoint PI loops equal its setpoints within 0.002 units (at most 0.003 sd), and the valve means equal its initial valve positions.
    - Read-only; nothing recorded.
  - **`library/loops.yaml` (agent-visible):** 19 loops, with plant tags only.
    - Each loop has an id following its controlled tag (FD-FI-101 → FD-FIC-101), the controlled tag, the output (a valve or another loop's setpoint), the mode (P or PI), the setpoint (fixed with a value in register units, or cascaded) and the period in seconds.
    - The purge loop also carries its pressure override.
    - No source, author or raw names; provenance is builder-side.
  - **`docs/decisions.md`, decision 61:** the source, file hash, line ranges and retrieval date, the four checks, the loop ↔ controller table, modes, and what the map makes visible.
    - **Proportional-only loops:** the four feed flows, the purge flow, both levels and the steam flow. They can settle off setpoint.
    - **Production rate** is held by the condenser cooling water valve.
    - **The purge override** never acts in normal operation.
  - **`eval/PROTOCOL.md`, Loops:** points at `library/loops.yaml` and decision 61. The masked-list sentence ("decided from dev runs") is left for session 6, which changes it to the selection runs per Raj's answer.
  - **`tests/test_loops.py`:** 10 tests. They cover:
    - ids unique and derived from the controlled tag
    - controlled tags are measurements or analyzers, each used once
    - each of the 11 valves is moved by exactly one loop
    - outputs are a valve or another loop
    - "cascaded" exactly when a master moves the setpoint, with one master each
    - cascades acyclic and ending in a valve
    - modes and periods, with an analyzer loop's period equal to its update interval
    - the override's ordering
    - the file passes the leak scan, with no raw or controller names
    - opt-in (`-m opendata`): every fixed-setpoint PI loop's fit-pool mean is within 0.02 sd of its setpoint. It passes on the real data.
  - **`tests/test_leak_scan.py`:** `WORDS` gains the control-strategy sources' author names (chiang, lyman, georgakis, larsson, skogestad, bathelt, jelali). Agent-visible text still passes.
- **Tests:** `pytest -q` gives 761 passed, 2 deselected. `pytest -q -m opendata tests/test_loops.py` passes.
- **Unsure about:**
  - **The strategy is identified from the data, not from a statement by the dataset's authors.** The setpoint match is exact to the code's printed precision on nine independent loops, so I'm confident. Still, decision 61 says it plainly, as decision 50 did for the simulator version.
  - **Decision 50's shortened hashes have their suffixes swapped.** Today's downloads give `tecode.zip` = `2536e8a8…7a8db724` and `temexd_mod.zip` = `e43227aa…c4b16b0d`; decision 50 reads `2536e8a8…4b16b0d` and `e43227aa…a8db724`. The prefixes are right, the endings swapped. Decision 61 uses the correct value. Decision 50 is Raj's record, so it isn't edited without his OK.
  - **The P-only loops matter for session 6.** A proportional-only loop doesn't return its measurement exactly to setpoint, so the masked rule's "measurement inside its normal band" is the right test (decision 58 wording), not "at setpoint".
  - **`CD-FV-302` (the condenser cooling water valve) is the production-rate valve.** The condenser group in the tag register (decision 48) is correct physically: the valve sits on the condenser's utility line. But a shift in that valve can mean a production-rate correction rather than a condenser problem, which matters for diagnosis entries later.
- **Decisions needed:**
  - Correct decision 50's two shortened hashes (above)?
  - Still open: findings 2 and 3 on `plant_track`; how the replay resumes after a data gap; `httpx2`; McNemar against a paired bootstrap; Neon (later).

### 2026-09-28: week 3 session 6, masked-fault rule and valve headroom (decision 62)
- **Changed** (Claude writes, Raj reviews, per Raj):
  - **Raj's answers to three design questions (all as recommended):**
    - **"Leaves" and "stays inside"** are judged as 3 consecutive samples outside the band.
    - **A cascade master's valve** is the end valve of its cascade.
    - **Fault level:** a fault is masked by a loop at ≥ 50% of its selection runs, and masked if any loop masks it.
    - **Why the question was asked:** judged per sample, 91% of normal calibration runs came out "masked" by some loop; with 3 consecutive samples, 3% do. This was measured read-only on the calibration pool, which the bands come from. Nothing was recorded.
  - **`docs/decisions.md`, decision 62:** the rule, the band, where it's decided, the fault level, and headroom.
  - **`eval/PROTOCOL.md`, Loops:** "decided from dev runs" becomes "decided on the 100 selection runs (never on dev)". The rule, band, fault level and headroom are listed, and the masked list itself reads "not yet decided".
  - **`app/detector/loops.py` (runtime, no eval/ingest/dataset imports):**
    - `load()`: reads `library/loops.yaml` against the register, and refuses duplicates, a valve on two loops, cycles, and non-valve outputs.
    - `end_valve()`
    - `headroom()`: min(position, 100 − position); refuses NaN, inf, or a position outside 0–100.
    - `valve_headroom()`: every looped valve's position, headroom and loop, as of one sample.
    - It isn't wired into the API or page yet.
  - **`eval/masked.py`:** `python -m eval.masked`.
    - **Functions:** `normal_bands`, `outside_for`, `run_masked`, `loop_columns`, `shares` and `verdict`.
    - **Driver:** bands from the calibration pool; each open fault 1–15 on the selection runs.
    - **Output:** a `masked_faults` record. Per fault it has every loop's share, the masking loops and the verdict. As a sanity figure it has the share of normal calibration runs the rule would call masked (in-sample). The config holds the loop map's SHA-256.
    - It never loads dev.
  - **`eval/dev_table.py`:** `--masked <masked_faults record>` fills the Masked column ("yes (loops)" or "no").
    - It refuses a file that isn't a `masked_faults` record, or one made with a different loop map (by SHA-256), before loading.
    - The config names the record.
  - **Tests:** 54 new.
    - **`tests/test_app_loops.py` (22):** loading, end valves through one and two cascade levels, headroom values and refusals, `valve_headroom` coverage, and five kinds of inconsistent map refused.
    - **`tests/test_masked.py` (29):**
      - pooled percentile bands, with worked values
      - 3-consecutive edge cases: a band edge counts as inside; alternating below and above counts as outside
      - `run_masked`: window edges (samples 21 and 100), a 2-sample blip still held, an excursion that starts before the window
      - shares at exactly 50%
      - the driver on synthetic runs: a pushed condenser valve is masked by ST-FIC-603 in every run, and a fault that also moves the measurements isn't masked
      - only calibration and forest-ceiling are loaded; refusals
    - **`tests/test_dev_table.py` (3):** the Masked column from a record, and refusals for a different loop map or a non-masked record.
- **Tests:** `pytest -q` gives 815 passed, 2 deselected.
- **Not run:** nothing was run on selection or dev in this session.
- **Unsure about:**
  - **The rule can flag a loop whose valve moves for a reason unrelated to the fault's cause.** For example, a cascaded inner loop whose setpoint legitimately moves while its measurement follows the setpoint. "Masked by L" says where the fault shows, not where it starts. The table names the loop, so this is visible.
  - **"Held" judges only the loop's own measurement,** so a fault can be masked by one loop while other measurements move. That matches "a loop absorbs it", not "the fault is invisible", and PROTOCOL's wording now says "measurement held while a valve absorbs the fault".
  - **The normal-run sanity figure is in-sample** (the calibration pool set the bands). It checks the rule, not a held-out rate.
- **Decisions needed:** decision 50's swapped hash suffixes (from session 5) are still open.
- **Next (Raj):** review; commit; then `python -m eval.masked` on a clean tree. After that:
  - write the masked list into PROTOCOL → Loops
  - optionally re-run `python -m eval.dev_table --masked <record>` so App 3's table shows the column

### 2026-09-28: week 3 session 6 (continued), masked rule judged on the settled half (Raj's review)
- **Changed:**
  - **Raj's review:** the code, headroom and dev-table column are approved. One change before anything runs: both "held" and "absorbed" are judged on the settled half of the window, samples onset + 41 … onset + 80 (2 to 4 h after onset). PERSIST = 3, the bands and the 50% share stay.
  - **`eval/masked.py`:**
    - a new `SETTLE = WINDOW // 2` (40)
    - `run_masked(…, settle=SETTLE)` judges samples onset + settle + 1 … onset + window, and refuses a settle outside 0 … window − 1
    - a run of consecutive samples outside the band counts only from onset + 41
    - the record's config gains `judged_samples` [61, 100]
    - the docstring and printout say so
    - the normal-calibration sanity figure goes through `run_masked`, so it uses the same half-window
  - **`docs/decisions.md`, decision 62:** the rule now says the settled half. A new "why the settled half" bullet cites fault 4's alarms firing at 3 min and clearing within a few samples. It also notes that the 91% and 3% normal figures were measured over the whole 4 h, and that the run records the figure for the settled half.
  - **`eval/PROTOCOL.md`, Loops:** the rule line says the settled half, samples onset + 41 … onset + 80.
  - **`tests/test_masked.py`:** the window-edge cases are moved to 61…100. New cases:
    - an onset transient in the measurement (samples 21–25) doesn't disqualify
    - a valve excursion only in the first 2 h isn't absorption
    - 58–60 is just outside; 59–61 gives only one judged sample; 61–63 counts
    - `settle = 0` restores the whole window and then the transient disqualifies
    - settle refusals
    - the constants and the record's `judged_samples`
- **Tests:** `pytest -q` gives 823 passed, 2 deselected.
- **Not run:** nothing on selection or dev.
- **Unsure about:** the settled half has 40 samples instead of 80, so a chance 3-sample excursion is less likely there. The normal sanity figure will likely fall below the 3% measured over 4 h. The run records it.
- **Decisions needed:** decision 50's swapped hash suffixes are still open.

### 2026-09-28: week 3 session 6 (continued), first masked run and the plant-level amendment
- **Changed:**
  - **First run (Raj, 774108d, clean tree):** `eval/runs/20260928T154511Z_masked_faults.json`, per-loop rule on the settled half.
    - 10 of 15 faults came out masked: 1, 2, 4, 5, 6, 7, 8, 11, 12 and 13. The recycle-flow loop CP-FIC-501 was among the masking loops for 7 of them: 1, 2, 5, 6, 7, 8 (with RX-TIC-204 on 1, 6 and 7), 12 and 13. Faults 4 and 11 were masked by the reactor temperature loops.
    - Not masked: 3, 9, 10, 14 and 15.
    - Normal calibration runs: 0.02 masked by any loop.
    - **Raj's reading:** the recycle loop absorbs nearly every plant-wide disturbance. That's real compensation, but not hiding (faults 1 and 6 are visible in many measurements), so "any loop" doesn't separate faults usefully.
    - The record is kept as the evidence, and is superseded. It isn't committed yet.
  - **Decision 62 amended (Raj's):**
    - **The label becomes plant level.** A run is masked when, in samples onset + 41 … onset + 80, no measurement or analyzer is out for 3 consecutive samples while at least one valve is. A fault is masked when at least 50% of its selection runs are. The bands and PERSIST are unchanged.
    - **Per-loop results stay in the record as diagnosis evidence.**
    - **The sanity figure** uses the plant-level rule on the normal calibration runs.
    - **Absorbing valves** (Claude's detail, to confirm): the valves out in at least 50% of a fault's masked runs; if none reaches that, the most frequent, ties included.
  - **`eval/masked.py`:**
    - New: `RULE = "plant"`, `plant_columns()` (41 held tags, 11 valves, from the register), `plant_masked()` (returns the verdict and the valves out) and `absorbing_valves()`.
    - `run_masked`, `shares` and `verdict` are unchanged, and are now the per-loop evidence.
    - Per fault, the record holds `masked`, `masked_share`, `absorbing_valves`, `valve_shares`, `absorbing_loops` and `loop_shares`.
    - The config gains `rule`, `held_tags` and `valves`. The normal sanity figure has `plant`, `max_loop` and `loop_shares`.
  - **`eval/dev_table.py`:**
    - The Masked column shows the plant-level verdict, "yes (absorbing valves)" or "no".
    - It refuses a record without `rule: plant`, so the superseded record can't fill the column. The loop-map check stays.
  - **`docs/decisions.md`, decision 62:** the label, the per-loop evidence and "why the label became plant level", citing the first record and its 10-of-15 result.
  - **`eval/PROTOCOL.md`, Loops:** the label and the per-loop evidence.
  - **Tests:**
    - **`tests/test_masked.py`:**
      - `plant_masked`: one or two valves out; nothing out; an analyzer out too; a 2-sample blip; an onset transient; a valve out only in the first 2 h
      - window refusals
      - `absorbing_valves`: the threshold, the tie fallback and the single-most-frequent fallback, and empty input
      - the register split
      - the driver: fault 5 (only CD-FV-302 moves) is masked with absorbing valve CD-FV-302 and loop ST-FIC-603. Fault 6 (the same valve, plus reactor pressure, which is in no loop) isn't masked at plant level, but ST-FIC-603 still absorbs it, which is the case the amendment fixes. Fault 7 is neither.
    - **`tests/test_dev_table.py`:** the column shows the absorbing valves; the superseded record is refused.
- **Tests:** `pytest -q` gives 835 passed, 2 deselected.
- **Not run:** the amended rule hasn't run on the selection runs.
- **Unsure about:** the plant-level label is strict. One measurement or analyzer out for 3 samples in the settled half makes a run visible, so the masked list may be short or empty. That fits "hidden from a measurement-based view", and the per-loop evidence still records the compensation.
- **Decisions needed:**
  - Confirm the absorbing-valve rule (above).
  - Decision 50's swapped hash suffixes (still open).
- **Next (Raj):** commit, including the superseded record; then `python -m eval.masked`.

### 2026-09-28: week 3 session 6 (close), masked list fixed
- **Changed:**
  - **Plant-level run (Raj, 64404fc, clean tree):** `eval/runs/20260928T155738Z_masked_faults.json`.
    - **Masked:** fault 4 only. 58 of 100 selection runs are masked, and in every one of them RX-FV-206 (the reactor cooling water valve) is out. The absorbing loops are RX-TIC-204 and RX-TIC-205.
    - **Every other fault is unmasked.** Fault 3's masked share is 0.01; all the others are 0.00.
    - **Per-loop evidence, kept for diagnosis:** CP-FIC-501 absorbs faults 1, 2, 5, 6, 7, 8, 12 and 13; RX-TIC-204 absorbs 1, 4, 6 and 7; RX-TIC-205 absorbs 4 and 11. No loop absorbs 3, 9, 10, 14 or 15.
    - **Normal calibration runs:** 0.007 (1 of 150) masked at plant level. That's in-sample for the bands.
    - The record isn't committed yet.
  - **`eval/PROTOCOL.md`, Loops:** the masked list is fixed before test. Fault 4 is masked, absorbed by RX-FV-206; faults 1–3 and 5–15 are unmasked; faults 16–20 are sealed and have no label.
  - **`docs/decisions.md`, decision 62:** both records, the superseded one (per-loop, 10 of 15) and the one in force (plant level, fault 4), with their figures.
- **Tests:** no code change. `pytest -q` is 835 passed, 2 deselected, as last run.
- **Unsure about:**
  - **Fault 4 is close to the threshold:** 58 of 100 runs against 50%. A different subsample could land either side. The rule and threshold were fixed before this run, so the label stands, but the README should give the 58%.
  - **Fault 5 isn't masked at plant level (0.00),** though its disturbance is the kind a loop compensates. The recycle loop absorbs it, but some measurement or analyzer stays out in the settled half on every run. This is a finding, not a problem with the rule.
  - **Masked and unmasked results will be reported separately (PROTOCOL).** With one masked fault, the masked group is fault 4 alone, which should be said wherever the split is shown.
- **Decisions needed:** decision 50's swapped hash suffixes (still open). The absorbing-valve rule is moot for now: fault 4 has one valve, out in every masked run.
- **Next:** commit the record and these docs. The dev tables can be re-run with `--masked eval/runs/20260928T155738Z_masked_faults.json` when useful; that's optional, and can wait for the week-close table (session 10).

### 2026-09-28: week 3 session 7, DPCA lag rule stubs and tests
- **Changed:**
  - **Raj's answers (to record as a decision when the rule is implemented):**
    - **Stop:** the search runs l = 0, 1, …. At the first l* ≥ 1 with r_new(l*) ≤ 0, lag l* adds nothing, so L = l* − 1. r_new(0) = 0 isn't a stop.
    - **Cap:** if no stop comes by L_max = 4, L = 4 and the result is marked capped. With warm-up 9 that allows n ≤ 6 (decision 52).
  - **`app/detector/dpca.py` (new; stubs for Raj, each raises NotImplementedError):**
    - `lagged(X, lags)`: one run, rows [x_t | x_{t-1} | … | x_{t-L}], past samples only
    - `lagged_tags(tags, lags)`: plain names for lag 0, then `TAG@t-j`
    - `stack_lagged(runs, lags, warmup)`: rows for samples warmup+1..T of each run. Lag columns may read warm-up samples, and rows never mix runs, so every l is compared on the same samples.
    - `relation_count(...)`: returns (k, r), with k from `pca.parallel_analysis` on the stacked matrix and r = m(L+1) − k
    - `new_relations(r)`
    - `choose_lags(count, l_max=4)`: returns `LagChoice(lags, k, r, r_new, capped)`, which is the evidence for the fit record. `count(l)` is called lazily, never past the stop.
    - The paper is cited in the tests, not in `app/`: "georgakis" is on the leak-scan word list.
  - **`tests/test_dpca.py` (new, 41 tests, worked comments):**
    - `lagged`, `lagged_tags` and `stack_lagged`: hand examples, no look-ahead, no run mixing, warm-up reads, refusals
    - `new_relations`: five hand cases, including an off-by-one count giving r_new = −1
    - `choose_lags` on fake counts:
      - static → L = 0
      - lag-1 → L = 1
      - negative r_new stops
      - a stop at l = 4 gives L = 3, not capped
      - no stop → L = 4, capped
      - lazy calls
      - refusals
      - the rule's known blind spot: a relation first seen at lag 3 with nothing new at lag 1 gives L = 0
    - **Two end-to-end synthetic plants through parallel analysis:** static gives k = (2, 4) and L = 0; one lag-1 pair gives k = (2, 3, 4), r = (2, 5, 8), r_new = (2, 1, 0) and L = 1. Before writing these, Claude checked the k values with a scratch script that built the lagged matrices inline (not committed). The kept eigenvalues are ≥ 1.8 and the next is ≈ 0.08, so the result doesn't sit near the edge.
- **Tests:** `tests/test_dpca.py` gives 40 failed (NotImplementedError from the stubs, as intended) and 1 passed (`L_MAX == 4`). Everything else is unchanged: 835 passed, 2 deselected.
- **Unsure about:**
  - **The rule stops at the first lag with nothing new**, so relations that skip lags are missed (pinned by a test). On the plant, the parallel-analysis edge (λ ≈ 1.03) can also make r_new go negative by one and stop early. `LagChoice` keeps k, r and r_new at every l, so the fit record shows this.
  - **Each l should get a fresh `default_rng(PA_SEED)`** in the session 8 driver (the tests do this), so a result doesn't depend on how many l's ran before it.
- **Decisions needed:**
  - The lagged column-name format `TAG@t-j` (used in error messages now, and by RBC's "lags combined per tag" in week 4).
  - Record the stop and cap readings above as a decision in `docs/decisions.md` and PROTOCOL → Detection when Raj confirms after review.
  - Decision 50's swapped hash suffixes (still open).
- **Next (Raj):** review, then implement the six stubs until `tests/test_dpca.py` passes. Session 8: fit driver, calibration and table rows.

### 2026-09-28: week 3 session 7 (close), lag rule implemented (Raj, acf1ed6)
- **Changed:** `app/detector/dpca.py`, all six functions implemented by Raj (with guidance from the Claude.ai chat). Tests unchanged since 3fba58b.
- **Tests:** `pytest -q` gives 876 passed (835 + the 41 in `tests/test_dpca.py`), as Raj reports.
- **Claude's review (no changes made):** matches every docstring contract, with no correctness problems.
  - `lagged` builds each block as a slice of X, so no row can read a later sample. `np.hstack` always returns a new array, so the caller's X is never aliased.
  - `stack_lagged` keeps rows from `warmup − lags` onwards, which is exactly samples warmup+1..T. It checks each run's length before lagging.
  - `choose_lags` calls `count` lazily, converts numpy ints to int, and returns the r_new it stopped on.
  - Small points, none blocking:
    1. `lags` isn't checked to be an integer. 1.5 fails later with a TypeError and `True` counts as 1. That's the same as `alerting.alert_track`.
    2. `stack_lagged([])` raises numpy's "need at least one array" ValueError. It's a ValueError, but the message is unclear.
    3. `new_relations` uses `int(r_l)`, which would silently truncate a non-integer count. Counts are always ints, so this is harmless.
    4. **Memory on the real fit pool at l = 4:** about 122,750 rows × 165 columns ≈ 160 MB per copy, and `parallel_analysis` holds three copies (X, Z and one shuffle), so the peak is about 0.5–0.7 GB. That's fine locally, and the fit never runs on Render.
- **Unsure about:** carried from the stubs entry. Parallel analysis's λ ≈ 1.03 edge can push r_new negative by one at l = 1 and stop at L = 0. The session 8 record keeps k, r and r_new at every l so this is visible.
- **Decisions needed:**
  - The stop reading (L = l* − 1, and r_new(0) isn't a stop) and the cap (L = 4, flagged) aren't in `docs/decisions.md` or PROTOCOL yet. They should be recorded before the lag rule runs on the fit pool (session 8).
  - The lagged name format `TAG@t-j`.
  - Decision 50's swapped hash suffixes (still open).

### 2026-09-28: week 3 session 8, stage 1: DPCA whole-run scoring stub and tests
- **Plan approved (two stages):**
  - **Stage 1 (this entry):** Raj's one core piece, as a stub with tests.
  - **Stage 2 (Claude, after Raj implements it):**
    1. Decision 63, drafted by Claude and confirmed by Raj before any run.
    2. `eval/fit_dpca.py`: the lag rule on the fit pool, a fresh `default_rng(PA_SEED)` per l, and `pca.fit` on `stack_lagged` with k = `choice.k[L]`. The `fit_dpca` record holds the full evidence.
    3. `calibrate_driver`, generalised: lags and detector come from the fit record, `n_range(L, warmup)`, and all scoring goes through `dpca.scores`. Static behaviour is unchanged.
    4. `check_dev` and `dev_table` take lags (the header shows L, with a note when L = 0).
    5. Synthetic tests for all of it.

    Then Raj runs the four commands.
- **Changed:**
  - **`app/detector/dpca.py`:** a new stub `scores(model, X, lags)` (Raj). It returns whole-run (T², SPE), index 0 = sample 1, with entries lags.. equal to `pca.scores` on `lagged` rows. The first `lags` entries are 0.0 and never read: L ≤ warm-up, `limits_at` reads only after the warm-up, `group` ignores warm-up samples, and decision 52 keeps every persistence window after sample L. So `alerting`, `calibrate` and `metrics` stay unchanged, and there's one scoring engine.
  - **`tests/test_dpca.py`:** 13 new tests:
    - lags = 0 is exactly `pca.scores`
    - a hand example (X = 1, 2, 3, one lag: T² = 0, 2, 4.5 and SPE = 0, 1, 4)
    - placement, length and dtype
    - float32 input
    - causal at t = 3, 10 and 500
    - the pad is never read: pads set to 1e9 give the same limits and the same alert tracks at L = 4 for (n, G) = (1, 0), (6, 0), (6, 5) and (3, 20), with a check that some tracks do alert
    - refusals: a model fitted with other lags, negative lags, no complete row, NaN/inf
  - **Checking the tests:** Claude ran them against a throwaway reference `scores` patched in from the scratchpad (not in the repo): 54 passed. That run showed the causal test needs a tolerance, because BLAS sums in an order that depends on the row count (as in `test_pca.test_scoring_is_row_by_row`). The test uses rel 1e-12.
- **Tests:** `tests/test_dpca.py` gives 13 failed (NotImplementedError, as intended) and 41 passed. The rest gives 835 passed, 2 deselected. Nothing else was run: no drivers, no data.
- **Not Claude's:** `eval/baselines/alarms.py` has two trailing blank lines added, probably by the IDE. Left alone.
- **Unsure about:** L = 4 (capped) leaves n ≤ 6, against static PCA's chosen n = 3. The persistence search space shrinks as L grows, which matters only if the best static setting needs n > 10 − L.
- **Decisions needed:**
  - **Decision 63 before stage 2 runs:** the lag rule's stop and cap readings, and the pad convention.
  - **A written selection rule for PCA vs DPCA.** PROTOCOL → Detection says "the production detector is chosen on dev by the selection rule", but no rule is written. It's needed before the week-close table. The ∞ − ∞ item for paired delay comparisons belongs with it.
  - **If DPCA is selected,** `build_bundle` and `replay` must score with `dpca.scores`. Today they would refuse a DPCA model with a column-count ValueError, not score it wrongly.
  - The lagged name format `TAG@t-j`; decision 50's swapped hash suffixes (still open).
- **Next (Raj):** review and implement `dpca.scores` until `tests/test_dpca.py` passes, then confirm decision 63's readings. Claude then does stage 2.

### 2026-09-28: week 3 session 8, stage 2: decision 63, DPCA fit, calibration and dev table (code only, nothing run)
- **Raj (950eb57):** implemented `dpca.scores` (with guidance from the Claude.ai chat). 889 tests passed. Claude read it: it matches the contract.
- **Changed:**
  - **`docs/decisions.md`, decision 63 (Raj's, confirmed before any DPCA result):**
    - the lag rule's stop and cap readings
    - the fresh generator per l on the same rows
    - the 0.0 pad
    - `TAG@t-j` names
    - **the selection rule:** decided on the 100 selection runs, not dev. DPCA replaces static PCA only if its selection score (`metrics.chosen.score` in its `calibrate_pca` record) is more than 3 points higher, read as more than 0.03 on the 0–1 scale. Both detectors are reported on dev. Paired delays use the lead-time convention.
  - **`eval/PROTOCOL.md`, Detection:** the Detector line now states the lag rule, the names and the pad. "Chosen on dev by the selection rule" is replaced by decision 63's rule.
  - **`eval/fit_dpca.py` (new, Claude):**
    - Before loading anything, it refuses an existing output, a warm-up outside 0..9 and L_max > warm-up (decision 52), then a dirty tree.
    - It runs the lag rule on the fit pool (fast tags, whole runs, a fresh `default_rng(20260927)` per l), fits `pca.fit` on the L-lagged matrix with k = k(L) (no second parallel analysis), and saves the `.npz`.
    - **The `fit_dpca` record:**
      - config: detector `pca_dynamic`, base tags, warmup, lags, l_max and the PA settings
      - metrics: L, capped, `static_equivalent`, `lag_rule` {k, r, r_new}, k, cumulative explained, and `eigenvalues_near_k` (5 on each side of the cut)
    - **Why not the full eigenvalue list:** records cap lists at 64 numbers, and m(L+1) is 66–165. The full list is in the saved model, which the record pins by SHA-256. The tests caught this: the first version would have saved the model and then failed to write the record, orphaning the model. The metrics are now validated before saving.
  - **`eval/calibrate_driver.py`:**
    - The detector and L come from the fit record, `fit_pca` or `fit_dpca`, with static defaults. It searches `n_range(L, warmup)`.
    - A new `input_tags(model, lags)` refuses a model whose columns aren't the base tags lagged L times, including a lagged model read with lags = 0. It runs before any loading.
    - `score_runs` and `tracks` take `lags` (default 0), and all scoring goes through `dpca.scores`. The static numbers are unchanged, and a test checks they're bit-identical.
  - **`eval/check_dev.py`:** scores with the limits' lags and records them.
  - **`eval/check_grid_refinement.py`:** scores with the limits' lags. It already read them but scored unlagged, which on a DPCA limits file would have raised.
  - **`eval/dev_table.py`:**
    - `PCADetector` takes lags.
    - Its input tags (for decision 57's divergence) are the base tags.
    - The header adds ", L = … lags", plus "(L = 0: DPCA equals static PCA)" when that holds.
  - **`eval/build_bundle.py`:** refuses limits with lags ≠ 0. The replay scores unlagged samples, so the demo bundle stays static until a DPCA replay is built.
- **Tests (23 new):**
  - `tests/test_fit_dpca.py` (11): a lag-1 plant on the 33 fast tags gives L = 1 with k = (2, 3, 4), r = (31, 63, 95) and r_new = (31, 1, 0). The record holds the evidence, which equals `choose_lags` on the same data. A static plant gives L = 0 and a model identical, array for array, to `fit_pca`'s. Refusals come before loading, and `main`'s exit code is checked.
  - `test_calibrate_driver.py` (+5): the DPCA limits and record (n in 1..2 at warm-up 3, L = 2), limits equal to percentiles of `dpca.scores`, static scoring bit-identical, `input_tags`, and a fit record with the wrong lags refused before loading.
  - `test_dev_table.py` (+6): DPCA rows equal direct scoring (divergence on base tags), the record and table name L, and the lag note.
  - `test_build_bundle.py` (+1): a DPCA model is refused.
  - `pytest -q` gives 912 passed, 2 deselected.
- **Not run:** no driver and no data, as asked.
- **Next (Raj runs, in order, on a clean tree):**
  1. `python -m eval.fit_dpca --warmup 9`, then read L and the evidence. k(0) should equal the static k = 12: same rows, same seed.
  2. `python -m eval.calibrate_driver --model data/models/pca_dynamic.npz --out data/models/pca_dynamic_limits.json`
  3. `python -m eval.check_dev --limits data/models/pca_dynamic_limits.json --model data/models/pca_dynamic.npz`
  4. `python -m eval.dev_table --limits data/models/pca_dynamic_limits.json --model data/models/pca_dynamic.npz --masked eval/runs/20260928T155738Z_masked_faults.json`
  5. **Selection (decision 63):** compare `metrics.chosen.score` in the two `calibrate_pca` records. Nothing computes this yet. A small script that reads both records and writes a `select_detector` record would keep the rule's result in a run record (CLAUDE.md: every reported number comes from a run record). Proposed for week close.
- **Unsure about:**
  - **Step 1's memory:** about 0.5–0.7 GB at l = 4. The rows run over 250 runs × 491 samples.
  - **If the rule gives L = 0,** steps 2–4 still run and reproduce static PCA's numbers under the name `pca_dynamic`. The table says so.
  - **"3 points" is read as 0.03 on the 0–1 score.** Raj to confirm.
- **Not Claude's:** `eval/baselines/alarms.py` now has three trailing blank lines added outside this session (the IDE). Left alone.
- **Decisions needed:**
  - Confirm the 0.03 reading.
  - The `select_detector` record for step 5.
  - Decision 50's swapped hash suffixes (still open).

### 2026-09-28: week 3 session 8 (close), DPCA results (Raj's runs, 952b422 and 395f43b)
- **Records:** `eval/runs/20260928T172623Z_fit_dpca.json`, `…175708Z_calibrate_pca.json`, `…175722Z_dev_false_alerts.json`, `…175722Z_dev_table_pca_dynamic.json`.
- **Lag rule:** L = 1.
- **Calibration:** n = 3, G = 13, q = 97.07. Selection score 0.97917, against static PCA's 0.975 (`eval/runs/20260927T150527Z_calibrate_pca.json`). The difference is 0.0042 ≤ 0.03, so static PCA stays (decision 63). Session 10's `select_detector` records this verdict.
- **DPCA on dev:**
  - mean detection 0.975 over the 12 summary faults (static: 0.982)
  - false alerts 1.075 per 24 h (0.76–1.41; static 0.919)
  - chance rate 0.12 (static 0.06)
  - faults 1, 4, 5, 6, 7, 12 and 14 each show "only alarms 1" in the lead-time column
  - static PCA has "neither 1" on fault 13

### 2026-09-29: week 3 session 10 (week close), stage 1: selection record, missed-run check, decision 50
- **Plan approved.** Stage 1 is code and docs, with nothing run but `pytest`. Raj then runs the data commands (below). The week 3 summary and the `docs/PLAN.md` update come after, from those records.
- **Changed:**
  - **`eval/select_detector.py` (new):** `python -m eval.select_detector`.
    - It checks for a clean tree before reading anything.
    - It finds each calibrate record from its limits file (`check_dev.calibration_record_for`), so a superseded record can't be picked.
    - It refuses a detector mix-up, a dirty calibrate record, and different selection faults, runs, budget, warm-up, manifest or splits.
    - **Grids:** the static record used the old 500-point grid and DPCA the 509-point one. So it requires the clean `check_grid_refinement` record for the static limits showing `unchanged: true` (`…104704Z`), and names that record in its own record.
    - **Rule:** DPCA only if `dynamic − static > 0.03`. A 1e-9 tolerance absorbs float rounding (0.53 − 0.5 = 0.030000000000000027), so exactly 3 points keeps static. Scores move in steps of 1/1200, so the tolerance can't change a real verdict.
    - It writes a `select_detector` record: the scores, the difference, `dynamic_lags` and the verdict.
  - **`eval/check_missed.py` (new):** `python -m eval.check_missed --limits … --model …`. It checks Raj's hypothesis about the "only alarms 1" runs.
    - It scores dev through `dev_table`'s detectors, against the realistic grouped alarms, and loads only dev.
    - **Per fault:** App 3's missed run numbers and the only-alarms ones.
    - **For each missed run of a summary fault:**
      - `cause` ("on at onset" or "no alert in window")
      - `on_at_onset` and `on_through_window`
      - the last notification before onset and the first after
      - the twin's notifications up to onset
      - whether the faulty and twin tracks are equal up to onset
    - **Summary:** the only-alarms run numbers, `same_run_everywhere`, `all_on_at_onset` and `hypothesis_holds`.
    - No new metric code: it uses `metrics.detection` and `metrics.notifications` only.
  - **`docs/decisions.md`, decision 50:** the two shortened hashes are corrected (`tecode.zip` `2536e8a8…7a8db724`, `temexd_mod.zip` `e43227aa…c4b16b0d`), with a line saying so. Nothing else in the decision changed.
- **Tests:**
  - **`tests/test_select_detector.py` (23):**
    - verdicts: session 8's pair, two exact 3-point boundaries, the next 1/1200 step above, and DPCA worse
    - the record's contents
    - no grid check needed on equal grids
    - refusals: four config keys, the data manifest, a dirty calibrate record, swapped limits, limits without a record, a missing, failed, dirty or other-limits grid check, and a dirty tree before reading
    - `main`'s exit code
  - **`tests/test_check_missed.py` (14):**
    - hand tracks: an alert bridging onset (15 → end: missed, on at onset); on at onset then off; no alert in the window; an alert cleared before onset is a detection; a warm-up alert; a twin that differs before onset
    - the summary: holds, and fails with two run numbers or off at onset
    - the driver equals direct scoring on `test_dev_table`'s synthetic runs, and loads only dev
    - refusals: an alarm row as App 3, the every-tag list, and a dirty tree before loading
  - `pytest -q`: 949 passed, 2 deselected. With addopts cleared, all 951 pass, including the 2 open-data tests.
- **Not run:** no driver.
- **Next (Raj, on a clean tree after committing):**
  1. `python -m eval.select_detector`
  2. `python -m eval.dev_table --masked eval/runs/20260928T155738Z_masked_faults.json`
  3. `python -m eval.dev_table --limits data/models/alarms_realistic_limits.json --row grouped --masked eval/runs/20260928T155738Z_masked_faults.json`
  4. `python -m eval.dev_table --limits data/models/alarms_every_limits.json --row grouped --masked eval/runs/20260928T155738Z_masked_faults.json`
  5. `python -m eval.check_missed --limits data/models/pca_dynamic_limits.json --model data/models/pca_dynamic.npz`
  6. `python -m eval.check_missed` (static PCA; covers fault 13's "neither 1")

  Then Claude checks that the three re-run tables equal the old records apart from `masked` (`…112351Z`, `…112413Z`, `…112441Z`, which become superseded). Claude also reads the answer to the hypothesis from the `check_missed` records, and writes the week 3 summary and the PLAN update.
- **Unsure about:**
  - **The synthetic driver test only produces "on at onset" misses.** The plant-like dev runs sit outside the two-factor PCA model, so every track is on. The "no alert in window" path is covered by the hand-built tests, not the driver test.
  - **"The same run number each time" can fail even if the mechanism holds.** Two runs could each bridge onset. The record separates `same_run_everywhere` from `all_on_at_onset`, so it will show which part fails.
- **Decisions needed:**
  - **PROTOCOL's key-values table (line 16) still says the detector is chosen "within 3 points of the best dev detection rate".** That contradicts decision 63 and PROTOCOL → Detection. Should it be updated to decision 63's wording?
  - Carried: the `TAG@t-j` name format; findings 2 and 3 on `plant_track`; replay after a data gap; `httpx2`; McNemar against a paired bootstrap; Neon (later).

### 2026-09-29: week 3 session 10 (close), selection verdict, masked tables, missed-run check
- **Runs (Raj, 58d6733, clean tree), committed as 209c65b:**
  - `eval/runs/20260929T020335Z_select_detector.json`
  - `…020336Z_dev_table_pca_static.json`
  - `…020402Z_dev_table_alarms_realistic_grouped.json`
  - `…020427Z_dev_table_alarms_every_grouped.json`
  - `…020515Z_check_missed_pca_dynamic.json`
  - `…020537Z_check_missed_pca_static.json`
- **Selection (decision 63):** static 0.975, DPCA (L = 1) 0.97917, difference +0.0042 against the 0.03 margin. The verdict is `pca_static`. The record cites both calibrate records and the grid check (`…104704Z`), which covers the grids that differ.
- **Masked tables, checked by Claude (jq, read-only):**
  - Each of the three re-run records equals its superseded record (`…112351Z`, `…112413Z`, `…112441Z`) in every metric and config value except the new `masked` fields and `masked_record`.
  - A negative control (static against realistic alarms) did show a difference, so the comparison isn't vacuous.
  - Every fault has a Masked verdict. Fault 4 is "yes (RX-FV-206)"; the others read "no".
  - The static table is therefore unchanged on real data after session 8's DPCA generalisation of the scoring path.
  - The three old records are superseded.
- **The one-missed-run hypothesis (Raj's reading, checked against the records by Claude):**
  - **DPCA's single miss is run 368 on each of faults 1, 4, 5, 6, 7, 12 and 14.** It's the only-alarms run in every one.
    - On each, App 3's alert turned on at sample 15, 18 minutes before onset, in the stretch the faulty run shares with its twin.
    - The normal dev run 368 has the same notification at 15, and the tracks are identical up to onset.
    - The alert was still on at onset (sample 20), stayed on through the whole window (21–100), and never switched on anew. So no detection is scored.
  - **The summary flags read False only because of fault 10.** Its only-alarms run 417 is a genuine miss: no alert in the window, first switch-on at sample 109, 9 samples after the window.
    - All 8 of DPCA's fault 10 misses are like that, with first switch-ons at samples 103–143.
  - **Static PCA has no on-at-onset misses.**
    - Fault 10's only-alarms runs 132 and 417 are genuine, with first switch-ons at 102 and 109.
    - Fault 13's miss, run 383, is genuine (switch-on at 117). The alarms missed it too, so it's "neither".
  - **Recorded (Raj): the hypothesis holds for the one-miss pattern (faults 1, 4, 5, 6, 7, 12, 14).** False alerts have a second cost: an alert already on hides the next fault's start. PROTOCOL counts only a new notification after onset, so the fault reaches no one as news.
  - **Run 368 alone accounts for DPCA's whole dev gap.**
    - It costs 7 × 0.02 / 12 = 0.0117 on the summary mean.
    - DPCA gains 0.04 on fault 10 and 0.02 on fault 13, together +0.005.
    - Net −0.0067, which is exactly 0.9817 → 0.975.
- **Changed:**
  - **`eval/PROTOCOL.md`, key values:** the "Detector selection" row now states decision 63's rule (the selection runs, not dev; > 0.03; otherwise static stays). Raj approved it.
  - **`docs/log.md`:** this entry and the week 3 summary.
  - **`docs/PLAN.md`:** the week 3 close note.
- **Tests:** no code change in this stage. The suite is as at 58d6733: 949 passed, 2 deselected.
- **Unsure about:** nothing new.
- **Decisions needed:** none new. Carried items are in the summary below.

### 2026-09-29: week 3 summary
- **Done when:** met. The per-fault detection table on dev exists for static PCA and DPCA, next to both alarm lists. Every one has the Masked column, and static PCA has lead time against the realistic grouped alarms. Static PCA stays the production detector (decision 63, `…020335Z_select_detector.json`).
- **Decisions 57–63:**
  - 57: detection scored from the documented onset; twin divergence as a diagnostic only
  - 58: the conventional-alarm baseline
  - 59: the finer top of the q grid, for every detector
  - 60: operator-load counts and lead time
  - 61: the loop map from the generating control code
  - 62: the masked-fault rule, judged on the settled half, at plant level; valve headroom
  - 63: the DPCA lag rule, the pad, lagged names and the selection rule
  - Also: decision 50's hashes corrected, and PROTOCOL's selection row aligned with decision 63.
- **Built:**
  - the divergence metric
  - the alarm baseline and its calibration
  - the operator-load, chattering and lead-time functions
  - `library/loops.yaml` and `app/detector/loops.py` (headroom)
  - `eval/masked.py`
  - DPCA (`app/detector/dpca.py`, `eval/fit_dpca.py`, a lag-aware calibration, dev check and dev table)
  - `eval/select_detector.py` and `eval/check_missed.py`
  - Tests went from 587 to 949.
- **Headline dev numbers (50 run numbers; means over the 12 summary faults; 95% run-number bootstrap intervals):**

  | Detector | Record | Detection | Faults 3, 9, 15 | False alerts per 24 h | Chance rate |
  |---|---|---|---|---|---|
  | App 3, static PCA (n 3, G 15, q 95.57) | `…020336Z_dev_table_pca_static` | 0.982 (0.972–0.990) | 0.087 | 0.92 (0.65–1.21) | 0.06 (0.00–0.14) |
  | DPCA, L = 1 (n 3, G 13, q 97.07) | `…175722Z_dev_table_pca_dynamic` | 0.975 (0.948–0.992) | 0.133 | 1.08 (0.76–1.41) | 0.12 (0.04–0.22) |
  | Realistic alarms, grouped (n 1, G 0, q 99.992) | `…020402Z_dev_table_alarms_realistic_grouped` | 0.958 (0.947–0.970) | 0.200 | 1.39 (1.08–1.70) | 0.22 (0.12–0.34) |
  | Every-tag alarms, grouped (n 1, G 0, q 99.992) | `…020427Z_dev_table_alarms_every_grouped` | 0.962 (0.950–0.973) | 0.253 | 1.56 (1.23–1.90) | 0.26 (0.14–0.38) |

- **Findings, in plain terms:**
  1. **App 3 isn't earlier than the realistic alarms on most faults.**
     - The alarms lead by a median 6 minutes on faults 4, 5, 6, 7, 12 and 14, by 9 on fault 2 and by 3 on fault 13.
     - App 3 leads on faults 1 (3 min), 8 (4.5), 10 (10.5, over 24 both-detected runs) and 11 (3). Only 1 and 8 have intervals above 0.
     - Most of the 6-minute gap is the persistence floor: n = 3 can't notify before 9 minutes, n = 1 can at 3.
  2. **App 3 wins on operator load and coverage.**
     - App 3 gives 1 notification per episode, with no floods and no chattering.
     - The realistic alarms give up to 65 per episode (fault 14, all chattering) and flood on fault 7.
     - On fault 10, App 3 detects 0.80 against 0.52.
  3. **The alarms run over budget on unseen runs** (1.39 and 1.56 per 24 h). App 3's point estimate is within it (0.92, though its interval reaches 1.21). So the lead-time comparison favours the alarms' looser operating point. The README must say so.
  4. **Masking:** only fault 4 is masked (58 of 100 selection runs, absorbed by RX-FV-206). On it, the realistic alarms clear (share still flagged 0.01) while App 3 holds (1.00).
  5. **DPCA doesn't earn its place.**
     - On the selection runs it's +0.004, far below the 0.03 margin.
     - On dev it's 0.007 lower than static PCA. Run 368 accounts for all of that (session 10).
     - It costs a higher false-alert rate (1.08 against 0.92) and a doubled chance rate.
  6. **False alerts have a second cost.** An alert already on at onset hides the next fault's start. DPCA's false alert at sample 15 of run 368 bridged into seven faults and cost one detection on each. Static PCA has no such misses on dev.
  7. **Genuine misses are late, not silent.** Every fault 10 miss, for both detectors, first alerts 2–52 samples after the 4 h window (samples 102–152).
- **Carried to week 4 (open):**
  - **The published-number check (Must, Metrics) hasn't run.** It still needs the Yin 2012 component count, the agreement band and the theoretical 99% limits, decided together first. It's week 2 work, still open.
  - **Status bands:** the Watch band follows RBC (schedule note). The plant ratio and bands are shipped.
  - **README wording** for finding 3: the comparison isn't at equal dev false-alert rates. An AMOC curve would put both detectors on one axis.
  - **Decisions:** the `TAG@t-j` name format (needed by RBC's "lags combined per tag"; DPCA isn't shipping, so it's low priority); findings 2 and 3 on `plant_track`; replay after a data gap; `httpx2`; McNemar against a paired bootstrap; Neon (later).
- **Week 4 (19–25 Oct in the plan, starting early):** reconstruction-based contributions and signature features, the library schema, and the first 5 entries.

### 2026-09-29: week 4 kickoff, plan and Raj's answers
- **Changed:** docs only (this entry). No code, and nothing run.
- **Week 4 plan approved.** Each session stops for review and commit.
  1. **S1:** decisions 64–66 (RBC, right place, Watch), in docs and PROTOCOL.
  2. **S2:** RBC core. Raj writes `app/detector/rbc.py`; Claude writes stubs, tests and the group loader.
  3. **S3:** Watch calibration. Raj writes `watch_limit`; Claude writes `eval/calibrate_watch.py` and the dev Watch share.
  4. **S4:** right place and top tags on dev. Raj writes `metrics.right_place`; Claude writes the dev-table columns. This is the week's "done when".
  5. **S5:** status bands in the runtime. Claude writes `bands.py`, bundle `pca_v2`, the API, the page, and the parity test.
  6. **S6:** decision 68 (the feature vocabulary, Raj), then decision 67 (library schema) and Claude's schema models and store.
  7. **S7:** Claude writes `features.py` (Raj reviews it) and `eval/authoring.py` (authoring runs only), which produce the provenance files.
  8. **S8:** Raj drafts the first 5 entries (faults 1, 4, 5, 6 and 13), Claude reviews them, and the week closes.
  - If the week runs long, S7 and S8 move to the start of week 5.
- **Raj's answers, to record as decisions in S1 (and 68 in S6):**
  - **RBC (64):** on the combined index φ = T²/T²lim + SPE/SPElim. Groups are rebuilt jointly and ranked by RBC_g / W_g.
  - **Attribution (65):**
    - Read as of the notification: the mean of RBC_g / W_g over the n samples that triggered it (t − n + 1 … t).
    - The same reading 30 minutes later is a secondary figure.
    - Family → groups, fixed before any RBC result:
      - feed composition → feed
      - feed supply → feed
      - feed temperature → stripper and feed (the mixed feed of reactants 1 and 2 enters the stripper)
      - reactor cooling → reactor
      - condenser cooling → condenser
      - reaction kinetics → reactor

      A miss is an honest result, not a reason to change the map.
  - **Watch (66):**
    - One shared percentile p for every group's W_g: the lowest stable value on the q grid such that at most 2% of normal calibration samples have any group in Watch.
    - No persistence, no notifications, and each group's own share is reported.
  - **Who writes:**
    - Claude writes `bands.py` to decision 66's rule.
    - Raj defines the feature vocabulary. Claude writes and tests `features.py`, and Raj reviews it.
    - Raj drafts the entry text. Claude reviews it for schema, leak scan and consistency with the evidence.
    - The approver can't be Claude. In S6, Claude proposes how author ≠ approver works honestly in a one-person demo.
  - **Not this week:**
    - DPCA RBC (lags combined per tag): not built, because DPCA doesn't ship.
    - The published-number check stays carried: the paper's values aren't in hand yet.
- **Tests:** none (docs only). The suite is unchanged: 949 passed, 2 deselected.
- **Unsure about:**
  - **Hours.** About 8 sessions will likely exceed 15 h.
  - **The plant-level Watch cap spreads 2% across six groups,** so each group's W_g sits higher than a per-group cap would put it. That's intended. The per-group shares will show it.
- **Decisions needed:** none new. Carried items are as in the week 3 summary.

### 2026-09-29: week 4 session 1, decisions 64–66 (RBC, right place, Watch)
- **Changed:** docs only.
  - **`docs/decisions.md`:** a new heading, "Week 4 decisions, 29 September 2026", with decisions 64–66 as Raj answered Q1–Q5 and Q9. All are fixed before any RBC result on real data.
    - **64:** RBC on φ = T²/T²lim + SPE/SPElim (M written out). Tag RBC and joint group RBC over each group's fast tags. Groups ranked by RBC_g / W_g. DPCA RBC noted as not built.
    - **65:** attribution as the mean of RBC_g / W_g over the n triggering samples (t − n + 1 … t), with the reading 10 samples later as a secondary figure. The family → groups map is fixed, with feed temperature allowing stripper or feed. It stays in `eval/` and PROTOCOL only.
    - **66:** Watch when RBC_g / W_g > 1. One shared percentile p, the stable-lowest on the q grid, keeps any-group Watch at or below 2% of calibration scored samples. No persistence, no notifications. Plant band precedence Unknown, Alert, Watch, Normal. The attributed group is marked during an Alert. Shares are reported per group and any-group, on calibration and normal dev.
  - **`eval/PROTOCOL.md`:**
    - the Watch-band cap row (now plant level)
    - Detection: new Attribution and Watch band bullets, replacing "each group's Watch boundary is calibrated to the watch-band cap"
    - Detection metrics: Right place, with the reading window, the +30 min secondary figure and the map
  - The feed-temperature reason is worded by role ("the mixed feed of reactants 1 and 2"), not component letter (decision 44).
- **Tests:** `pytest -q` gives 949 passed, 2 deselected (no code change).
- **Unsure about (Claude's wording, beyond the answers; please confirm):**
  - **"If no grid value qualifies, the calibration stops with an error"** (decision 66). This mirrors decision 54's "not eligible", but here there's only one setting.
  - **"Unknown = warm-up or bad data"** is today's replay behaviour, restated in decision 66's precedence.
  - **The +30 min window** is written as samples t + 10 − n + 1 … t + 10, the same n-sample mean shifted by 10 samples.
- **Decisions needed (before S4 computes anything):**
  - **The right-place denominator.** PROTOCOL's column is "Detected (any / right place)". Is right place reported as right-place detections over all runs (the same denominator as "any", so the two rates compare directly), over detected runs, or both? Suggestion: over all runs in the column, with "k of detected" beside it.
  - **Top tags in S4:** rank tags by raw tag RBC, mean over the same triggering window. Single tags are all one-dimensional in the same φ, so raw values compare fairly, unlike groups. Confirm, or name another reading.
- **Next:** S2, RBC core (Raj writes `app/detector/rbc.py`; Claude writes the stubs, tests and group loader), after review and commit.

### 2026-09-29: week 4 session 2, RBC stubs, tests and the group loader
- **Raj's answers from S1, recorded in decision 65:**
  - Right place is reported over all runs (beside "any"), with "k of detected" beside it.
  - Top tags are ranked by RBC_i / W_i over the same triggering window. W_i is at the same shared p as the W_g and is computed in S3; it sets no band.
- **Changed:**
  - **`app/detector/groups.py` (Claude, complete):** `load(tags)` returns {group: column indices in the given order}.
    - Groups are in register order; a group with none of the tags is left out.
    - It refuses a tag not in the register (including `TAG@t-j` names), a repeated tag, or a register row with no group.
    - On the 33 fast tags: feed 8, reactor 6, condenser 2, separator 7, compressor 3, stripper 7.
  - **`app/detector/rbc.py` (stubs for Raj, NotImplementedError):**
    - `index_matrix(model, t2_lim, spe_lim)`
    - `combined_index(model, M, X)`
    - `tag_rbc(model, M, X)`
    - `group_rbc(model, M, X, groups)`: groups as column-index tuples
    - `rank_at(ratios, t, n)`: decision 65's triggering-window mean and order, one function for groups and tags
    - The docstrings give the formulas, conventions and refusals.
  - **`tests/test_groups.py` (9, passing):** order and sizes, the partition, the given order, known members, empty groups dropped, and refusals.
  - **`tests/test_rbc.py` (40, failing on the stubs as intended):**
    - hand values: M for the 2-tag model at two sets of limits, and for a 3-tag model built by hand; tag RBC for z = (1, 0) and z = e1
    - φ equals T²/T²lim + SPE/SPElim, and r ≤ φ ≤ 2r (φ isn't the plant ratio)
    - RBC equals its definition (φ(z) minus the smallest φ(z − Ξf), found by Cholesky and least squares) for every tag and three groups. So the tests don't trust the closed form.
    - a single-tag fault is fully removed and ranked first; 0 ≤ RBC ≤ φ; a one-tag group equals tag RBC; a group ≥ each member; the all-tags group equals φ; a fault inside a group is fully removed by it
    - the smearing case (below)
    - float32 input computes in float64, and scoring is row by row
    - refusals: NaN or inf, wrong columns, a wrong M shape, bad groups, bad limits
    - `rank_at`: a window mean by hand, ties in column order, nothing read after t (NaN at t + 1 is ignored), and window refusals
- **Checking the tests:** Claude ran them against a throwaway reference `rbc` in the session scratchpad (not in the repo; the temporary copy of the test file was deleted). All 40 pass, plus the 9 group tests.
- **Tests:** `pytest -q` gives 40 failed (the stubs), 958 passed, 2 deselected.
- **Finding while writing the smearing test (a scratch search, not a result on data):**
  - The textbook plain contribution to SPE, ((I − PPᵀ)z)_i², misranked a single-tag fault in 670 cases across 400 random models.
  - A plain contribution to the combined index (the M^½ decomposition) misranked none in the same search.
  - So the test shows smearing with the SPE contribution. It uses a 3-tag model where the healthy tag gets 0.2304 against the faulty tag's 0.1296, while RBC ranks the faulty tag first with all of φ.
  - What this means for decision 64: on the combined index, RBC's advantage for single-tag faults is a guarantee (it is always right), not a gap measured on these models.
- **The idea (for Raj):**
  - RBC asks: if I let the model rebuild these tags from the others, how much of the abnormality disappears?
  - A tag that carries the fault alone disappears completely when rebuilt, so it scores all of φ and ranks first.
  - A healthy tag only removes whatever part of the fault happens to lie along it.
  - Plain contributions instead split the index up tag by tag. For SPE, a correlated healthy tag can end up with the biggest share.
- **Unsure about:**
  - **The group loader returns index tuples keyed by name, and `group_rbc` takes the tuples.** Drivers pass `tuple(groups.load(model.tags).values())` and keep the names in the same order.
  - **`group_rbc` inverts each group's ΞᵀMΞ.** M is positive definite, so it's invertible. For the 8-tag feed group, solving is steadier than inverting, but that's Raj's choice.
- **Decisions needed:** PROTOCOL → Right place doesn't yet mention the two S4 answers (the denominator and top tags by RBC_i / W_i). They're in decision 65 only, as asked. Mirror them in PROTOCOL?
- **Next (Raj):** implement `app/detector/rbc.py` until `tests/test_rbc.py` passes. Then S3 (Watch calibration, with W_i alongside W_g).

### 2026-09-29: week 4 session 3, Watch calibration stubs, driver and dev reading
- **Raj (S2, committed):** implemented `app/detector/rbc.py` (with guidance from the Claude.ai chat). All 40 RBC tests pass.
- **Changed:**
  - **`eval/calibrate.py` (stubs for Raj, NotImplementedError):**
    - `WATCH_CAP = 0.02`
    - `watch_limits_at(rbc_runs, p, warmup)`: per-column pooled percentile of scored samples
    - `watch_shares(rbc_runs, limits, warmup)`: the any-column share and each column's share, strict "above"
    - `watch_limit(rbc_runs, warmup, cap, q_grid)`: the stable-lowest p, scanned from the top, None if the top fails
    - The two helpers are stubbed too, because they're limit and calibration code, as `limits_at` is.
  - **`eval/calibrate_watch.py` (Claude, new):** `python -m eval.calibrate_watch`.
    - **Before loading:** it refuses an existing output, a dirty tree, limits without a `calibrate_pca` record, another model, and DPCA limits (RBC isn't built for DPCA, decision 64).
    - **Scoring:** the calibration pool once, as whole-run group RBC and tag RBC through `rbc.py`, with groups from `groups.load(model.tags)`.
    - **Calibration:** p = `watch_limit`, and a p of None stops with decision 66's error. W_g and W_i come from `watch_limits_at` at p.
    - **Watch file:** `data/models/pca_static_watch.json` holds p, the cap, each group's tags and W_g, each tag's W_i, and the model and limits SHA-256s.
    - **Record:** `calibrate_watch` holds p, whether it's the grid floor, every W_g and W_i, the scored sample count, and the any-group and per-group shares on calibration.
    - **Helpers for later sessions:** `watch_record_for`, and `load_watch` (checks the record, the limits SHA-256 and that the groups match the register).
  - **`eval/check_dev.py`:** a new `--watch <watch file>`.
    - It checks the file before loading anything, then reads the any-group and per-group Watch shares on the same normal dev runs (dev loaded once).
    - They're recorded under `metrics.watch`, with `watch_record` and `watch_sha256` in the config. Without `--watch` the record is unchanged.
    - `calibrate_watch` is imported inside `run`, because `calibrate_watch` imports `check_dev` for `calibration_record_for`.
- **Tests:**
  - **`tests/test_watch_limit.py` (24, hand-built):** two columns of 1..100 over two runs, with a 1e6 warm-up sample that would move every percentile if it were counted.
    - Pooled linear percentiles, and warm-up skipped.
    - Shares by hand. "Aligned" columns count their exceedances once. "Reversed" columns add up: 2% + 2% = 4%, so the plant cap is stricter than a per-group one.
    - A value equal to its limit isn't in Watch.
    - p = 98 aligned and 99 reversed on a 4-point grid. The bottom of the grid when everything passes. None when the top fails. p = 97.98 on the real grid.
    - Refusals.
  - **`tests/test_calibrate_watch.py` (16):** on the calibration fixture's 33 real fast-tag names. The watch file equals direct calibration; the record; the shares; only calibration loaded; no qualifying p; five refusals before loading; `main`'s exit code; `check_dev --watch` against a direct computation; unchanged without `--watch`; and a file with no record or with other groups refused before loading.
  - **Checked against a throwaway reference** of the three stubs (a pytest plugin in the scratchpad, not the repo): all 46 pass (these plus `test_check_dev.py`). That check caught a bug in my test helper, which indexed raw dataset columns by plant tag. It now uses `tagmap.column_indices`, as the driver does.
  - **`pytest -q`:** 30 failed and 4 errors (all NotImplementedError from the stubs; the errors are the fixture that calibrates Watch), 1004 passed, 2 deselected.
- **Not run:** no driver, no data.
- **The idea (for Raj):**
  - Each group's Watch boundary is a high percentile of its own normal RBC. With one shared percentile, every group is equally strict.
  - The cap counts a sample once if any group is above its line. So six groups each at 2% would put the plant in Watch up to about 12% of the time, and the search raises p until the union is at most 2%.
- **Unsure about:**
  - **The shares have no interval.** They're a sanity reading, like the calibration shares. A run-number bootstrap could be added if the README quotes them.
  - **The any-group share is monotone in p**, because every boundary rises with p. So the stable-lowest rule gives the same p as "lowest passing". It's kept for consistency with decision 54.
- **Decisions needed:** none new. Carried: whether to mirror decision 65's S4 answers in PROTOCOL.
- **Next (Raj):** implement the three functions until `tests/test_watch_limit.py` and `tests/test_calibrate_watch.py` pass. After committing, on a clean tree:
  1. `python -m eval.calibrate_watch`
  2. `python -m eval.check_dev --watch data/models/pca_static_watch.json`

### 2026-09-29: week 4 session 3 (close), Watch calibrated (Raj's runs)
- **Raj (e8700f0):** implemented `watch_limits_at`, `watch_shares` and `watch_limit`. All S3 tests pass.
- **Runs (Raj, e8700f0, clean tree):**
  - `eval/runs/20260929T065812Z_calibrate_watch.json`
  - `eval/runs/20260929T065821Z_dev_false_alerts.json`
- **Calibration (150 runs, 73,650 scored samples):**
  - p = 99.67 (not the grid floor).
  - Any-group Watch share 0.0195, at or below the 2% cap. Each group's own share is 0.0033.
  - W_g: feed 1.001, reactor 0.941, separator 0.782, stripper 0.547, compressor 0.530, condenser 0.368. Every tag's W_i is in the record.
- **Normal dev (50 runs):**
  - Any-group Watch share 0.0200.
  - By group: feed 0.0035, reactor 0.0023, condenser 0.0039, separator 0.0039, compressor 0.0033, stripper 0.0036.
  - False alerts per 24 h 0.919 (0.665–1.173). That's identical to the week 2 `check_dev` record (`…20260927T150758Z`, same seed), so the `--watch` extension changed nothing in the false-alert reading.
- **Reading (Raj):**
  - The groups' Watch samples barely overlap: 6 × 0.33% ≈ 1.99%, against a union of 1.95%. So each group is abnormal on its own samples, and the plant-level cap works out to about 1/6 of 2% per group.
  - The cap carries over to unseen normal runs: 2.00% on dev against 1.95% on calibration.
- **Tests:** unchanged since e8700f0; all pass (1038 passed, 2 deselected, as Raj reports).
- **Unsure about:** dev's 0.0200 sits right at the cap. It's a single reading with no interval, and the cap is set on calibration only, so this is expected, not a breach.
- **Decisions needed:** none new.

### 2026-09-29: week 4 session 4, right place and top tags: stub, dev-table columns, tests
- **Changed:**
  - **`eval/metrics.py` (stub for Raj, NotImplementedError):**
    - `right_place(order, names, allowed)`: is `names[order[0]]` in the family's groups? `order` comes from `rbc.rank_at`.
    - It refuses an empty order or one that isn't a permutation, repeated names, an empty `allowed`, and an `allowed` group that isn't in `names`, so a typo in the map can't read as a miss.
    - Also `SECONDARY_OFFSET = 10` (30 min).
  - **`eval/dev_table.py` (Claude):**
    - **`FAMILY_GROUPS`:** decision 65's map, next to `FAMILIES`.
    - **`attribution_row`:** for each detected run, `rank_at` over the n triggering samples (n is the calibrated persistence) on the group ratios RBC_g / W_g and the tag ratios RBC_i / W_i. The same group reading is taken 10 samples later.
    - **Per fault it gives:**
      - the right-place rate over all runs (a run that's missed or wrongly placed counts 0), with the run-number bootstrap interval and "right of detected"
      - the same 30 minutes later
      - the three tags most often ranked first, with counts (ties in model column order)
      - the most frequent top group and its share of the detected runs
      - Faults 3, 9 and 15 get top tags and top group only.
    - **Summary:** equal-weight right-place means over the 12 faults (joint bootstrap), at the notification and 30 minutes later.
    - **`--watch <watch file>`:** App 3 only; an alarm row is refused before loading. The file is checked with `calibrate_watch.load_watch` before loading. RBC is computed through `calibrate_watch.rbc_runs`, the same path as the Watch calibration.
    - **Record:** `config.attribution` (watch record and SHA-256, p, window n, offset 10, the family map), `faults.*.attribution` and `metrics.right_place`.
    - **Table:** the main column reads "any (interval) / right place (interval), k of d detected". A new "Attribution at the notification" section has, per fault, the family groups, right place now and 30 minutes later, the top group with its share, and the top tags with counts.
    - Without `--watch`, everything is as before.
- **Tests:**
  - **`tests/test_right_place.py` (15, hand-built):** allowed and not, a two-group family, second place still a miss, numpy order, seven refusals, and 10 samples = 30 minutes.
  - **`tests/test_dev_table_attribution.py` (11):**
    - **The map equals decision 65.** Every family is mapped, only register groups are used, and 3, 9 and 15 have no family.
    - **Two planted faults.** Fault 10 steps only the stripper's tags: top group stripper, right place on every detected run. Fault 1 steps only the condenser's tags: top group condenser, right place 0, the honest miss.
    - **Rows match RBC computed directly** (argmax of window means) for faults 1, 5, 10 and 13: right now, right 30 minutes later, top-tag counts and top-group share.
    - Excluded faults have no right place; the summary is the equal-weight mean; the record and table are rendered from the record.
    - Unchanged without `--watch`; a watch file for other limits is refused before loading; `--watch` on an alarm row is refused.
  - **Checked against a throwaway `right_place` reference** (a scratchpad plugin): these and `test_dev_table.py` give 63 passed. That caught two bugs in my own table test, which picked a "| 10 |" line from the wrong section. It now splits the table by section.
  - **`pytest -q`:** 21 failed (all NotImplementedError from the stub), 1043 passed, 2 deselected.
- **Not run:** no driver, no data.
- **Also (Raj's S3 runs, this commit):** the two S3 records are untracked, ready to commit with this.
- **The idea (for Raj):**
  - Right place asks whether the group the detector blames when it first notifies is where the family's fault actually lives.
  - Averaging the ratios over the n samples that triggered the alert uses exactly what the operator had at that moment, with nothing after.
  - The 30-minute reading shows whether the blame settles on the right place or drifts once the disturbance spreads through the loops.
- **Unsure about:**
  - **The top group's share** counts the most frequent group; a tie goes to the earlier group in register order. The top tags break ties by model column order.
  - **The 30-minute window can reach past the 4 h window** (at most sample 110 in 500-sample training runs). That's fine for training runs. A test run notifying near its end would need a guard, but test isn't touched until the frozen run.
- **Decisions needed:** none new. Carried: mirror decision 65's S4 answers in PROTOCOL?
- **Next (Raj):** implement `metrics.right_place` until `tests/test_right_place.py` and `tests/test_dev_table_attribution.py` pass. After committing, on a clean tree:
  `python -m eval.dev_table --masked eval/runs/20260928T155738Z_masked_faults.json --watch data/models/pca_static_watch.json`
  Then review the attribution section: this week's "done when".

### 2026-09-29: week 4 session 4 (close), right place and top tags on dev (Raj's run and review)
- **Raj (d2d2547):** implemented `metrics.right_place`; the S4 tests pass.
- **Run (Raj, d2d2547, clean tree):** `eval/runs/20260929T073949Z_dev_table_pca_static.json`. Static PCA, with the masked column and lead time as before. Attribution uses `…065812Z_calibrate_watch.json` (p = 99.67), window n = 3, and the 30-minute reading 10 samples later.
- **Right place (mean over the 12 summary faults, over all runs):**
  - 0.69 (0.67–0.70) at the notification
  - 0.54 (0.52–0.56) 30 minutes later

  | Fault | Right place (right/detected) | 30 min later | Top group (share) | Top tags (runs ranked first) |
  |---|---|---|---|---|
  | 1 | 0.00 (0/50) | 0.00 | compressor (0.80) | ST-PI-602 49, CP-JI-502 1 |
  | 2 | 0.00 (0/50) | 0.00 | separator (1.00) | SP-FV-407 25, SP-FI-406 19, RX-PI-202 4 |
  | 4 | 1.00 (50/50) | 1.00 | reactor (1.00) | RX-FV-206 50 |
  | 5 | 1.00 (50/50) | 0.22 | condenser (1.00) | SP-TI-401 46, CD-TI-301 4 |
  | 6 | 1.00 (50/50) | 1.00 | feed (1.00) | FD-FV-105 32, FD-FI-101 18 |
  | 7 | 1.00 (50/50) | 1.00 | feed (1.00) | FD-FI-104 31, ST-PI-602 19 |
  | 8 | 0.00 (0/50) | 0.18 | compressor (0.90) | ST-PI-602 48, CP-JI-502 2 |
  | 10 | 0.78 (39/40) | 0.72 | stripper (0.95) | ST-TI-604 39, SP-PI-403 1 |
  | 11 | 1.00 (50/50) | 0.96 | reactor (1.00) | RX-FV-206 50 |
  | 12 | 0.90 (45/50) | 0.36 | condenser (0.90) | SP-TI-401 43, CD-TI-301 5, SP-PI-403 1 |
  | 13 | 0.54 (27/49) | 0.02 | reactor (0.55) | RX-PI-202 40, RX-TI-205 3, SP-PI-403 3 |
  | 14 | 1.00 (50/50) | 1.00 | reactor (1.00) | RX-TI-205 29, RX-FV-206 20, RX-TI-204 1 |

  Faults 3, 9 and 15 have no family. Their few detections (3, 4 and 6) have scattered top tags.
- **"Done when" met: Raj's review of the top tags.**
  - **Every detectable fault's top tags make physical sense:**
    - 4 and 11 on the reactor cooling water valve RX-FV-206
    - 14 on RX-TI-205 and RX-FV-206
    - 6 on FD-FV-105 and FD-FI-101
    - 7 on FD-FI-104
    - 10 on ST-TI-604
    - 5 and 12 on SP-TI-401, then CD-TI-301
    - 13 on RX-PI-202
  - **Faults 1, 2 and 8** are composition faults on the mixed feed (reactants 1 and 2). They score 0 because RBC points to where their effect shows, not to the feed: the gas loop (ST-PI-602 and the compressor) for 1 and 8, and the purge (SP-FV-407, SP-FI-406) for 2.
    - The feed's fast tags are flow-controlled, so they hold.
    - The analyzers that would show composition aren't in the PCA (decision 11: they're diagnosis evidence only).
  - **The map stays as pre-registered (decision 65).** It isn't changed after seeing dev.
  - **Attribution drifts by +30 min** (fault 5: 1.00 → 0.22; fault 13: 0.54 → 0.02). That supports reading it at the notification, as decision 65 does.
- **Claude's additional observations (record only, no change):**
  - **Fault 7's second top tag is ST-PI-602** (19 of 50), the same gas-loop tag that leads faults 1 and 8.
  - **On faults 5 and 12, the top group is the condenser (right place) while the top tag is SP-TI-401,** a separator tag. Groups and tags are each divided by their own W, so the two rankings can disagree. The group's joint RBC carries the right place here, not the single top tag.
  - **Fault 13's top group is split:** reactor 0.55, the rest spread. RX-PI-202 is the top tag on 40 of 49 runs, but the reactor group leads on only 27.
- **Leakage (Raj, for S7 and S8):** these dev observations must not shape the library entries (LEAKAGE wall 3). Entries come from the authoring runs only. `eval/authoring.py` (S7) will load only the 5 authoring run numbers and refuse every other pool.
- **Tests:** unchanged since d2d2547; all pass (as Raj reports).
- **Decisions needed:**
  - Carried: mirror decision 65's S4 answers (denominator, top tags by RBC_i / W_i) in PROTOCOL → Right place?
  - For the README: right place 0.69 comes with the structural reason for 1, 2 and 8 (composition shows only in the analyzers, which the detector doesn't use). How that's worded is Raj's call.
- **Next:** S5, status bands in the runtime (`bands.py`, bundle `pca_v2` with the Watch file, API, page, parity test).

### 2026-09-29: week 4 session 5, status bands in the runtime (bands, bundle v2, replay, API, page)
- **Changed (Claude, per Q6):**
  - **`app/detector/bands.py` (new):** `plant_band` with decision 66's precedence (Unknown, Alert, Watch, Normal); `group_bands` (strictly above 1 is Watch; NaN or inf refused); `notifications` (the protocol's definition, restated because `app/` can't import `eval/`); `attributed` (below).
  - **`app/detector/bundle.py`:**
    - A bundle may hold `watch.json`, loaded as `Bundle.watch`; `pca_v1` has none and behaves as before.
    - **The self-test, when `watch.json` is present:**
      - every key is there
      - it was calibrated for this model (SHA-256)
      - the record and limits checksums are SHA-256s
      - warm-up and detector match `limits.json`
      - lags are 0
      - p is in (0, 100]
      - the groups are the register's groups, in order, with the register's tags in model order
      - every W_g and W_i is finite and > 0
      - known answer: every group's RBC at the fit mean is 0
  - **`app/detector/replay.py`:** with Watch boundaries, each row adds `groups` ({group: {ratio RBC_g / W_g, band}}; None on Unknown rows) and `attributed`. The plant band follows `bands.plant_band`. RBC goes through `rbc.py`, the same code as the Watch calibration and the dev table. Rows from a v1 bundle are unchanged, key for key.
  - **`app/api.py`:** `/replay/info` for a v2 bundle gives `bands` = Normal, Watch, Alert, Unknown and `groups` (the six names), with no note. For v1 it's unchanged (the note stays). Routes are unchanged, and every route is still a GET.
  - **`eval/build_bundle.py`:** `--watch <watch file>` writes `watch.json`. That's the watch file (checked with `calibrate_watch.load_watch`: its record, the limits checksum, the register's groups) plus `watch_record_sha256`. The default output is then `app/bundles/pca_v2`. `pca_v1` is never touched: a bundle is never overwritten.
  - **`web/index.html`:**
    - **A group panel**, hidden until the API reports groups: each group's band pill, its ratio (Watch at 1) with a meter, and during an Alert a red outline on the attributed group, marked "Symptoms show here first (attributed when the alert began)".
    - **Watch in the pill, the band strip, the counts and the legend** (the legend entry is hidden until groups exist).
    - **Notes:**
      - "Watch is an early, silent signal: it doesn't raise an alert."
      - "It shows where the symptoms appear, not what caused them, and it isn't an instruction to act."
    - With a v1 API, the page is exactly as before. No fault or run numbers, and no benchmark names.
- **The attributed-group rule (my reading of decision 66, to confirm):** during an Alert, the page marks the group ranked first at the notification that started the episode (`rank_at` over the n triggering samples, decision 65), held until the alert ends. It isn't re-ranked each sample: decision 66 says "the top-ranked group (decision 65)", and the +30 min drift (fault 5: 1.00 → 0.22) is why.
- **Tests (new or extended):**
  - **`test_bands.py` (21):** precedence (nine cases); strict > 1; NaN refused; `notifications` equals `eval.metrics.notifications` on random tracks; attribution by hand (fixed for the episode, re-ranked for a new one, nothing read after the notification, an alert on at the first scored sample).
  - **`test_bundle.py` (+19):** a v2 bundle passes and v1 has no Watch; 14 kinds of bad `watch.json` (another model, a bad SHA-256, warm-up or detector mismatch, p out of range, group order, W ≤ 0 or NaN, reordered tags, a missing tag, W_i < 0); a missing key; lags 1; a register that moves a tag to another group.
  - **`test_replay.py` (+5):**
    - **Parity with the evaluation path on a synthetic run:** every scored sample's group ratios (`calibrate_watch.rbc_runs` / W_g), group bands and plant band equal the evaluation's, and at every notification the attributed group equals `rank_at` on the evaluation ratios. It isn't vacuous: Watch appears before the step and alerts are attributed.
    - Attributed only during an Alert and held per episode; Unknown rows carry no groups; as-of prefix stability, including attribution; v1 rows unchanged.
  - **`test_api.py` (+4):** v2 health and info; the row contract; a failed Watch self-test returns 503 and blocks scoring; the leak scan and forbidden keys on every v2 response.
  - **`test_build_bundle.py` (+4):** v2 has three files and `watch.json` = the watch file plus its record's SHA-256, and passes the self-test; a watch file with no record, or one for other limits, is refused and leaves nothing behind; `main` defaults to `pca_v2` with `--watch` and `pca_v1` without.
  - **`test_web.py` (+3):** the panel is hidden until groups exist; the advisory wording; Watch has a colour in every theme.
  - **`test_replay_parity_opendata.py` (new, opt-in with `-m opendata`):** the committed `app/replay/run.csv` through `pca_v2` equals the evaluation path on the same dev run, loaded from the open data (fault and run from `eval/replay_source.yaml`, builder side): bands, plant ratio, group ratios, and the attributed group at every notification. It skips until `pca_v2` exists, so it hasn't run yet.
  - **`pytest -q`:** 1120 passed, 3 deselected (the opt-in open-data tests).
- **Checking the tests:** two first versions failed for test-side reasons. At p = 99, a 60-sample synthetic stream never reached Watch, so the test bundle now uses p = 90. And two calibrations in one second collided on the record name, so that test now writes a second calibrate record by hand. No code change came from either.
- **Not run:** `build_bundle` (as asked), the page in a browser, and the real-data parity test.
- **Kept as is:**
  - `DEFAULT_BUNDLE` is still `pca_v1`, so the API, Render and the committed thin-slice tests keep working until `pca_v2` exists.
  - `eval/baselines/alarms.py` shows a change I didn't make (the IDE again). Left alone.
- **The idea (for Raj):**
  - The plant band says how the whole plant looks right now. The group panel says where it looks unusual.
  - Watch lights a group when its reconstruction-based contribution passes its own boundary, often before any alert.
  - When an alert starts, the page freezes the group that best explained the triggering samples, so the operator sees one stable "symptoms show here" answer for the episode rather than a marker that wanders as the disturbance spreads.
- **Unsure about:**
  - **The page hasn't been tried in a browser** against a v2 API. The JS is covered only by string checks. After the build, it should be tried locally (CLAUDE.md, run the page locally).
  - **Response size:** each row now carries six group objects. The full 500-sample stream is about 6 times larger; fine for this demo.
- **Decisions needed:** confirm the attributed-group rule above (fixed at the episode's notification).
- **Next (Raj):** review and commit, then on a clean tree:
  1. `python -m eval.build_bundle --watch data/models/pca_static_watch.json` (writes `app/bundles/pca_v2`)
  2. `pytest -q -m opendata tests/test_replay_parity_opendata.py`
  3. Try the page locally against `BUNDLE_DIR=app/bundles/pca_v2`.

  Then Claude switches `DEFAULT_BUNDLE` to `pca_v2` (and the `render.yaml` comment), and Raj redeploys (Render, Vercel).

### 2026-09-29: week 4 session 5 (close), pca_v2 is the default bundle
- **Raj:**
  - Confirmed the attributed-group rule: fixed at the episode's notification.
  - Built and committed `app/bundles/pca_v2` (63ffc7e) and checked the page locally.
- **Changed (Claude):**
  - **`app/detector/bundle.py`:** `DEFAULT_BUNDLE` is `pca_v2`. The API, the Render deploy and the committed thin-slice tests use it from now on. `pca_v1` is kept, unchanged.
  - **`app/api.py`:** the `BUNDLE_DIR` docstring default reads `pca_v2`.
  - **`eval/build_bundle.py`:** explicit `DEFAULT_V1` (without `--watch`) and `DEFAULT_V2` (with it). Without this, switching `DEFAULT_BUNDLE` would have quietly made a plain build target `pca_v2`.
  - **`render.yaml`:** the comment names `pca_v2` as the committed default, with `pca_v1` kept.
  - **`tests/test_thin_slice_artifacts.py`:**
    - the default is `pca_v2` and passes its self-test
    - `pca_v1` is kept and still passes, with no Watch
    - `pca_v2`'s `watch_record_sha256` is a committed `calibrate_watch` record
    - the live API on the committed files reports the six groups and the Watch band, with no leaks
  - **`tests/test_build_bundle.py`:** `main` defaults to `DEFAULT_V1` without `--watch`.
- **A bug in S5's real-data parity test (Claude's), found and fixed:**
  - `tests/conftest.py` points the loader at a folder that doesn't exist (the safety wall). My test caught the loader's error and turned it into a skip. So it had been skipping, not passing: a skip prints `s`, not `F`.
  - It now follows the other open-data tests: it skips only when `data/faulty_training/` is absent, points the loader's repo root at the real repo (the sealed root stays pointed nowhere), and lets any loader error fail.
  - It also asserts the dev run alerts, so the attribution check can't be empty.
  - Run now for real: `pytest -q -m opendata` gives 3 passed (the loop setpoints, the twins, and the parity). The committed replay stream through `pca_v2` equals the evaluation path on the same dev run: every band, the plant ratio and the six group ratios on every scored sample, and the attributed group at every notification.
  - **Raj's earlier "the open-data parity test passes" was most likely this skip.** The page check stands on its own.
- **Tests:** `pytest -q` gives 1122 passed, 3 deselected; `pytest -q -m opendata` gives 3 passed.
- **Not run:** no deploy. Render and Vercel pick up `pca_v2` on Raj's next push and redeploy.
- **Unsure about:** Render's free instance scores the full 500-sample stream per request, now with group RBC too. That's six small solves per sample, fine locally. It may add latency on the free plan and is worth a look after the deploy.
- **Decisions needed:** none new.
- **Next:** Raj pushes and redeploys, then checks the live page. Then S6: decision 68 (the feature vocabulary, Raj), then decision 67 (library schema), with Claude's proposal for an honest author ≠ approver in a one-person demo.

### 2026-09-29: week 4 session 6, decisions 67 and 68, library schema and store
- **Raj's choices (from `~/Desktop/s6_proposals.md`):**
  - **Features:** F1-A (high, low, both, normal on all 33 fast tags), F2-A, F3-A (the notification only), F4-A with the plant masked flag, F5-A, F6-A (no dynamics in v1).
  - **Event types:** decision 7's four.
  - **Storage:** one file per revision, never edited.
  - **Author ≠ approver:** option 1, with the 24-hour gap and an upgrade path to option 2.
  - **Action kinds:** check, confirm, request a setpoint change, escalate.
  - **ISO 14224 fields hold "unverified"** until Raj checks the category names against a source he can access.
- **Changed:**
  - **`docs/decisions.md`:** decision 67 (schema, storage, governance) and decision 68 (feature vocabulary v1), under week 4.
  - **`app/library/schema.py` (new, Claude):** Pydantic models (extra fields refused, frozen) for:
    - `Revision`: identity, equipment, `iso14224`, `signature` (location at the notification, then provisional and revised readings of tags, loops, analyzers and the masked flag, each item required or supporting), actions, links, sources, governance
    - `Approval`: must record all six gates: schema, leak scan, provenance, preconditions, entry tests, 24 h gap
    - `Review`
    - **Refused:**
      - an ID that isn't a slug or looks like a label (fault-N, idv)
      - any ISO value except `unverified`, or `not_applicable` for the failure mode only (the verified lists are empty)
      - an action without a non-empty safety precondition, without `approval_required: true`, or of another kind
      - a signature with nothing required
      - times without a time zone
      - effective_from before created_at, and review_due not after it
      - wrong `supersedes`, a repeated action_id, and self-links
  - **`app/library/store.py` (new, Claude):**
    - **`load()`** checks, and refuses the whole library on the first problem:
      - file names; IDs matching names; revisions 1..K with no gaps
      - references against `library/tags.yaml` and `library/loops.yaml`: signature tags must be fast tags and analyzers must be analyzers
      - accounts: roles; the author's account can't approve; Claude only reviews; the same person can't claim independence; approval at least 24 h after created_at
      - related entries exist; an action_id belongs to one entry
    - **`Library.in_force(as_of)` and `get()`:** the highest revision approved and effective by as_of; a withdrawn one takes the entry out; drafts are invisible; past review_due is flagged, not dropped; the reference is `entry_id@r<k>`.
    - **`agent_view()`:** the revision without `sources`, plus the reference, the overdue flag and the approval label ("self-approved (single-person demo)" or "independently approved").
  - **`library/accounts.yaml` (new):** `raj` (author) and `raj-review` (approver) are the same person; `claude` is reviewer only.
  - **`library/entries/.gitkeep`:** the empty entries folder.
- **Claude's reconciliation (to confirm):**
  - "Never edited" and "a draft until it has an approval block" conflict if the block sits inside the revision.
  - So an approval is its own file, `r<k>.approval.yaml`, written only by the gated command, and a reviewer's note is `r<k>.review-<account>.yaml`.
  - Recorded in decision 67 as Claude's detail.
- **Tests:** `tests/test_library.py` (65).
  - **Schema:** the example is valid; the vocabulary equals decision 68; 23 kinds of invalid revision refused, each differing from the valid example by one change; an approval missing any one gate refused.
  - **In force:** empty library; draft invisible; the approval time and a later effective_from; r2 taking over only from its approval; withdrawal; overdue flagged; as_of must be aware; an independent approval by another person; `agent_view` strips sources.
  - **Governance:** approval by the author's account, by Claude, by an unknown account, a claimed independence by the same person, and under 24 h, all refused; the author role required; a Claude review kept; bad accounts refused (Claude as approver or author, unknown roles, duplicates); the committed accounts are option 1.
  - **Files and references:** five layout errors, eight reference errors, an action_id reused across entries, and related entries that resolve.
  - **The committed library:** it loads, holds only process entries, passes the leak scan, and every file under `library/entries/` has at most one commit (skipped without git history).
  - I also checked by hand that the leak scan catches "fault 4" and "idv4" in entry text.
  - **`pytest -q`:** 1187 passed, 3 deselected.
- **Run:** only pytest and an import check that loads the committed (empty) library. No data, no drivers.
- **Not built (needed before S8 approvals):** the gated approval command that writes `r<k>.approval.yaml` after checking all six gates. The store refuses an approval without them, but nothing writes one yet.
- **Unsure about:**
  - **Source IDs aren't checked yet.** `sources` takes any strings: the source register (decision 25) doesn't exist yet.
  - **The immutability test depends on git history.** CI's shallow checkout sees one commit per file anyway, so the check is only meaningful locally.
  - **`family` uses PROTOCOL's family names.** They're mechanism families, not fault labels, but they are the same names the right-place map uses.
- **Decisions needed:**
  - Confirm the approval-file reconciliation.
  - Where the gated approval command lives and when it's built: builder side, probably `eval/approve_entry.py`, before S8.
  - The source register (decision 25), before entries cite sources.
  - Carried: mirror decision 65's S4 answers in PROTOCOL?
- **Next:** S7, `app/detector/features.py` (Claude writes, Raj reviews), the evidence normals for all 52 tags, and `eval/authoring.py` (authoring runs only), which writes the provenance files.

### 2026-09-29: week 4 session 7, features, evidence normals and authoring (code only, nothing run)
- **Raj's answers (S6 close):**
  - The approval file is confirmed.
  - The gated approval command is `eval/approve_entry.py`, built in S8 before the first approval.
  - The source register is `eval/sources.yaml` (builder side), and entries cite only its opaque IDs, because source titles name the benchmark.
  - Mirror decision 65's S4 answers in PROTOCOL.
- **Changed, docs:**
  - **`docs/decisions.md`, decision 67:** the approval file marked confirmed; `eval/approve_entry.py` named; `eval/sources.yaml` and opaque IDs added.
  - **`eval/PROTOCOL.md`, Right place:** reported both ways, and top tags by RBC_i / W_i over the triggering window (with W_i at p, setting no band).
- **Changed, code:**
  - **`app/library/schema.py`:** `sources` must be opaque IDs of the form `src-NNN` (Claude's format, to confirm), so no title-like ID (for example `src-yin-2012`) can reach `library/`. Two new refusal tests.
  - **`app/detector/features.py` (new, Claude writes, Raj reviews):** decision 68, runtime.
    - **`tag_state`:** out is decision 62's rule, 3 consecutive samples outside the band with the edges inside. high or low when every such run is on one side; both otherwise, including one run that crosses sides.
    - **`analyzer_state`:** only values published after the notification and up to the diagnosis time. Fewer than 2 is not_yet_available. high or low on 2 consecutive published values out. If both sides qualify, the most recent run decides (Claude's reading, to confirm).
    - **`loop_state`:** saturated (end valve at or below 2% or at or above 98% for 3 consecutive samples), then lost, then compensating, then held. Analyzer-controlled loops are judged on the held analyzer series.
    - **The masked flag:** decision 62's plant rule over the window, with analyzers judged on their held series, as decision 62 did.
    - **`location`:** `rbc.rank_at` over the n triggering samples, the top group and the top 3 tags.
    - **`reading` and `extract`:** the window runs from t − n + 1 to the diagnosis time. Provisional is at t + 10, revised at t + 20, and a reading past the end of the data is left out.
    - **Refusals:** a gap in the window, a window outside the run, and a tag with no normal band.
    - **`plant_from_files`:** the fast tags, analyzers, measurements, valves, and each loop's controlled tag and end valve, from `library/`.
  - **`eval/evidence_normals.py` (new):** `python -m eval.evidence_normals`.
    - It computes all 52 tags' central-99% bands on the calibration pool with `eval/masked.normal_bands`, so the numbers are exactly decision 62's.
    - It writes `data/models/evidence_normals.json` and an `evidence_normals` record holding every band.
    - It refuses an existing file, a dirty tree before loading, and an empty band (lo = hi).
    - Also `load_normals`, which needs the file's record.
  - **`eval/authoring.py` (new):** `python -m eval.authoring`.
    - **Loads only the authoring pool** (5 run numbers) of faults 1, 4, 5, 6 and 13, and checks it got exactly 5 authoring runs. `load_authoring` refuses any other fault.
    - **Scores** through calibration's alert path, `metrics.detection`, `calibrate_watch.rbc_runs` over W, and `features.extract`.
    - **Analyzer publications are recovered from the held series:** every change must fall on one schedule every update interval (2 or 5 samples), and the publications are every sample on it. A change off the schedule refuses the run instead of guessing.
    - **Writes `eval/provenance/fault_NN.yaml`** with a builder-side header: the runs; per run, the detection, notification sample, delay and features; and a summary giving, per feature, the count of each state over the detected runs. Plus an `authoring` record (the input records and limits checksum, detected counts per fault, each provenance file's SHA-256). The files and the record name each other.
    - **Provenance is per fault,** because entry IDs don't exist until S8. The entry → provenance link will be a small key in `eval/`.
- **Tests:**
  - **`tests/test_features.py` (42):** tag states (edges, 2 vs 3 in a row, both kinds of both); analyzer states (the minimum, the most recent side); loop precedence; held series; whole readings on the real register and loop map (normal, a valve absorbing gives masked and compensating through the cascade, a measurement out gives lost and unmasked, an analyzer out unmasks through its held series); analyzers counted only after t; as-of (NaN after the diagnosis time isn't read); the window start; refusals; extract (location, no revised reading before +60 min, missing normals).
  - **`tests/test_evidence_normals.py` (5):** bands equal `masked.normal_bands` for all 52 tags; the record; the load round trip; refusals.
  - **`tests/test_authoring.py` (12):** publications (schedule, an equal consecutive value still counts, off-schedule and never-changing refused); only faults 1, 4, 5, 6, 13 from the authoring pool; provenance contents and counts (one quiet run isn't detected and has no features); features equal a direct `features.extract`; the record ties files and inputs; refusals before loading; nothing written under `library/`.
  - The first authoring run found fault 1's synthetic step too small to detect (a test-data issue); the step was raised.
  - **`pytest -q`:** 1248 passed, 3 deselected.
- **Not run:** `evidence_normals` and `authoring` on real data (as asked).
- **The idea (for Raj):**
  - The features turn "what the plant looked like" into a short list of categorical states, one per tag, loop and analyzer, using the same "out" rule everywhere. The matcher can then count agreements and contradictions against an entry's signature.
  - Authoring runs the whole detector, exactly as evaluation does, on the 5 authoring runs only, and writes down how often each state appeared. You write the signature from those counts and never from dev.
- **Unsure about:**
  - **The analyzer schedule** is checked on the data, not assumed. If the real held series change off a single schedule (for example if the dataset's first sample isn't on the schedule), `authoring` will refuse loudly; tell me what it says.
  - **Analyzer bands come from the held series at 3-minute resolution.** Each publication repeats 2 or 5 times, evenly, so the percentiles match those of the published values except at the run edges.
  - **"Most recent side decides"** for an analyzer out high and low in one window isn't in decision 68.
- **Decisions needed:**
  - Confirm `src-NNN` as the opaque source ID format.
  - Confirm "most recent side decides" for analyzers.
  - Confirm provenance per fault (`eval/provenance/fault_NN.yaml`) with an entry key in `eval/` at S8.
- **Next (Raj, after review and commit, on a clean tree):**
  1. `python -m eval.evidence_normals`
  2. `python -m eval.authoring`

  Then S8: `eval/approve_entry.py`, `eval/sources.yaml`, and the first 5 entries from the provenance files.

### 2026-10-02: week 4 session 8, steps 1–4: one_of, source register, gated approval, entry key and template
- **Raj (S7 close):** S7 ran and is committed (`eval/runs/20261001T182856Z_evidence_normals.json`, `…_authoring.json`, `eval/provenance/fault_{01,04,05,06,13}.yaml`). Confirmed: `src-NNN` IDs, the most recent side for an analyzer out on both sides, and provenance per fault with an entry key in `eval/`.
- **Step 1, decision 68 amended (Raj, from the authoring evidence, not dev):**
  - Tag and analyzer expectations may give `one_of` several acceptable states, and any of them agrees. Exactly one of `state` or `one_of` (at least 2 different states). Loops keep a single state.
  - **The evidence:** `fault_13.yaml` has RX-PI-202, SP-PI-403 and ST-PI-602 low on 3 detected runs and high on 1, at both readings.
  - **Code:** `app/library/schema.py`, with `accepted()` on every expectation.
  - **Tests (+9 in `tests/test_library.py`):** valid `one_of`, six refusals (neither, both, one state, repeated, unknown, an analyzer state on a tag), loops refusing `one_of`, and the store loading a `one_of` entry.
- **Step 2, `eval/sources.yaml` (builder side):** seven sources, pre-filled from what the decisions already cite:
  - src-001: authoring evidence (own work)
  - src-002: the dataset (its terms, from the manifest)
  - src-003: the simulator archive (decision 50)
  - src-004: the control code (decision 61)
  - src-005: the published-number paper (decision 56)
  - src-006: the DPCA lag rule (decision 63)
  - src-007: ISO 14224 (decisions 23, 67)
  - Each has a role, a licence (four "to confirm") and the decision citing it. IDs are never reused or renumbered.
  - **`tests/test_sources.py` (4):** IDs unique and in order, all fields present, no title or link appears in `library/`, and the register isn't in `library/`.
- **Step 3, `eval/approve_entry.py` (Claude):** `python -m eval.approve_entry <entry_id> <k> --approver raj-review`.
  - **The six gates, all evaluated and reported at once; nothing is written unless all pass:**
    1. **schema:** the whole library loads through the store, and every cited source is in `eval/sources.yaml` (my addition, folded into this gate).
    2. **leak_scan:** the revision file, with the CI patterns.
    3. **provenance:** the entry key names the file; the file is an output of an authoring record; the family matches; and the signature agrees with the detected authoring runs: a required item on every run, a supporting item on at least half (my thresholds, to confirm).
    4. **preconditions.**
    5. **entry_tests:** a clean `entry_tests` record says `entry@rk` passed.
    6. **gap_24h.**
  - **Other refusals:** an approver without the role or the author's account, a dirty tree, an existing approval (never overwritten), and an unknown revision.
  - **`independent`** is computed from the accounts (same person: false), not an option.
  - After writing, it reloads the store and removes the file if the store refuses it.
  - **The leak-scan patterns moved to `eval/leak_scan.py`,** so CI and the approval gate share one definition. `tests/test_leak_scan.py` imports and re-exports them; nothing else changed.
  - **`tests/test_approve_entry.py` (27):** in a throwaway git repo with a copy of the register and loop map.
    - A full approval: file contents, the store label, and `independent` true for another person.
    - Each gate failing on its own: an unknown source, a library that doesn't load, a leak, no key, no authoring record, the wrong family, a required item agreeing on 3 of 4, four ways for entry tests to fail, and 23 h 59 min.
    - Supporting at exactly half passes and a quarter fails; `one_of` agreement; agreement counts; all failures reported together.
    - Approver refusals (the author's account, Claude, unknown); no overwrite; dirty tree; unknown revision; `main`; the entry-key refusals.
- **Step 4:**
  - **`eval/entry_provenance.yaml`:** empty (`entries: {}`), with the line format in a comment. Raj adds one line per entry with its r1.
  - **`docs/entry_template.yaml`:** a commented r1 template, not in `library/`, that validates against the schema. `tests/test_entry_template.py` (2) checks it validates, shows `one_of` and passes the leak scan. Its tags and states are placeholders, not authoring evidence.
- **Tests:** `pytest -q` gives 1290 passed, 3 deselected.
- **Not run:** nothing on data; no approval.
- **Unsure about:**
  - **The entry_tests gate can't pass yet.** There's no entry-test runner until the matcher (week 5), so `approve_entry` will refuse every entry until then. That's the honest reading of decision 24 ("only tested entries"), but it means no approval this week.
  - **The agreement thresholds** (required: all detected authoring runs; supporting: at least half) are mine. They decide what "the signature agrees with its provenance" means.
  - **The leak scan's word list** doesn't include the published-number paper's or the control code's other authors (for example Yin or Russell). The sources test catches each exact title and link. Adding names is Raj's call.
  - **Not Claude's:** `eval/baselines/alarms.py` shows a change again (the IDE). Left alone.
- **Decisions needed:**
  - **The agreement thresholds** for the provenance gate (1.0 required, 0.5 supporting).
  - **The entry_tests gate before week 5:** wait for the matcher, or define an interim entry test? For example, the entry's own signature scored against held-out authoring runs isn't possible with only 5 runs.
  - Whether to add more source-author names to the leak scan's word list.
- **Next (Raj):** review and commit; write the five r1 drafts from the provenance files, adding each to `eval/entry_provenance.yaml`. Approvals wait for the entry_tests decision and 24 h after each `created_at`.

### 2026-10-02: week 4 session 8 (continued), Raj's answers, leak-scan names, approve --check
- **Raj's answers:**
  1. **The agreement thresholds are confirmed:** required items on every detected authoring run, supporting items on at least half. Recorded in decision 67's gate list.
  2. **The entry_tests gate waits for the matcher.** There's no interim test. The five entries stay drafts this week and are approved in week 5, once real entry tests exist. Recorded in decision 67.
  3. **Add the sources' authors' distinctive surnames to the leak scan.**
  4. **Add a `--check` mode to `approve_entry`.**
- **Changed:**
  - **`eval/leak_scan.py`:** adds `yin`, `haghani`, `russell` and `storer` as whole words. Chiang, Braatz, Ricker, Vogel, Georgakis, Lyman, Rieth and Bathelt were already there. Not added:
    - Ku: too short.
    - Ding, Hao, Zhang: common words or surnames that would false-positive.
    - Downs: "ups and downs", which an existing test must pass. "Vogel" covers that paper.
  - **`tests/test_leak_scan.py`:** the new names are caught ("Yin et al.", "Haghani", "Russell's code", "Storer", plus the existing names spelled out); ordinary text still passes ("yinyang flow", "a restorer valve", "ding dong"). Agent-visible and served text were scanned first: none of the new names appear.
  - **`eval/LEAKAGE.md`, CI checks:** the runtime scan line now describes the surname list instead of naming two authors.
  - **`eval/approve_entry.py`:** `--check` (`python -m eval.approve_entry <entry_id> <k> --check [--approver …]`).
    - It evaluates and reports the six gates, and the approver if given, on any tree, dirty or not, and never writes.
    - It prints when the 24-hour gap will allow approval, and a one-line summary. It exits 0 only when every gate passes.
    - `--approver` is required only without `--check`.
    - The approval path is unchanged; the shared pieces moved into `_now`, `approver_problem` and `report`.
  - **`tests/test_approve_entry.py` (+5):** `--check` on an uncommitted draft (reports leak_scan and gap_24h, writes nothing), all gates passing on a dirty tree, an approver that can't approve, an existing approval left as it is, and `main`'s exit codes and the `--approver` requirement.
- **Tests:** `pytest -q` gives 1306 passed, 3 deselected (+5 `--check` tests, +11 leak-scan cases).
- **Expected for every draft until week 5:** `--check` will show entry_tests FAIL (no runner yet), and gap_24h FAIL for the first 24 hours after `created_at`. All other gates should pass before a draft is committed.
- **Decisions needed:** none new.
- **Next (Raj):** write the five r1 drafts and run `--check` on each before committing it; then add each to `eval/entry_provenance.yaml`. Approvals come in week 5.

### 2026-10-02: week 4 session 8 (close), five r1 drafts and Claude's reviews
- **Raj:** wrote the five r1 drafts (with guidance from the Claude.ai chat, reviewed himself) and committed them with the entry key (9f900c7, ffdbc30, 8d1c04f). Each passed `--check` on schema, leak scan, provenance and preconditions.

  | Entry | Provenance | Authoring runs detected |
  |---|---|---|
  | `reactor-cooling-water-warm-supply` | `fault_04.yaml` | 5 of 5 |
  | `condenser-cooling-water-warm-supply` | `fault_05.yaml` | 5 of 5 |
  | `reactant-1-feed-supply-loss` | `fault_06.yaml` | 5 of 5 |
  | `mixed-feed-reactant-ratio-shift` | `fault_01.yaml` | 5 of 5 |
  | `reaction-rate-drift` | `fault_13.yaml` | 4 of 5 (late: 54 to 159 min) |
- **Claude's review (as reviewer, never approver):**
  - `--check` re-run: schema, leak scan, provenance and preconditions pass for all five; entry_tests and gap_24h fail, as expected until week 5.
  - All 56 signature items checked against the authoring evidence: every required item agrees on every detected run, and every supporting item on at least half (two at 4 of 5, one at 3 of 4).
  - **The description claims that aren't in the signatures were checked too, and match:**
    - reactor temperature held normal (cooling)
    - compressor power low at the revised reading (condenser) and at both readings (feed supply, ratio shift)
    - the reactant-1 composition loop losing control (feed supply)
    - feed valve and gas-loop pressures high (ratio shift)
  - **Non-blocking notes for an r2 (in the review files):**
    - **feed supply:** "fully open within the hour" holds on 4 of 5 runs.
    - **reaction drift:** the signature uses loop CP-FIC-501, but `equipment.loops` and `links.loops` are empty.
    - **ratio shift:** the description contrasts it with the feed-supply entry, but `related_entries` is empty.
  - **No sign of dev influence.** The ratio shift's compressor location matches what dev showed in S4, but the authoring evidence supports it on its own (5 of 5).
  - **Wrote `library/entries/<entry>/r1.review-claude.yaml` for all five.** The notes contain no fault numbers, run numbers or provenance file names (the leak scan passes), and the store loads them with `claude` as reviewer.
  - The reaction-drift note's delay range was corrected (to 54 to 159 min) before any commit.
- **Tests:** unchanged code; the library, leak-scan and sources tests pass (122). The full suite was last 1306 passed, 3 deselected.
- **Decisions needed:** none new.

### 2026-10-02: week 4 summary
- **Done when: met.** The top tags look right on dev faults: Raj's review in S4 (`eval/runs/20260929T073949Z_dev_table_pca_static.json`).
- **Decisions 64–68** (all fixed before the results they govern):
  - 64: RBC on the combined index; groups rebuilt jointly; ranked by RBC_g / W_g
  - 65: attribution over the n triggering samples; the family → groups map; right place reported both ways; top tags by RBC_i / W_i
  - 66: the Watch band, capped at the plant level
  - 67: the library schema, storage, governance, source register and gated approval
  - 68: the feature vocabulary, amended for `one_of`
- **Built:**
  - **S1–S2:** decisions 64–66; `app/detector/rbc.py` (Raj) and `app/detector/groups.py`.
  - **S3:** the Watch calibration (`watch_limit`, Raj; `eval/calibrate_watch.py`, `check_dev --watch`).
  - **S4:** right place and top tags in the dev table (`metrics.right_place`, Raj).
  - **S5:** status bands in the runtime (`bands.py`), bundle `pca_v2`, the group panel on the page; live on Render and Vercel.
  - **S6:** the library schema and store, the accounts.
  - **S7:** `features.py`, the evidence normals, authoring and provenance.
  - **S8:** `one_of`, `eval/sources.yaml`, `eval/approve_entry.py` (with `--check`), the leak-scan patterns in `eval/leak_scan.py` with the sources' surnames, the entry key and template, and five r1 drafts reviewed.
  - **Tests:** 949 → 1306.
- **Headline numbers, each from its record:**
  - **Watch** (`…065812Z_calibrate_watch.json`, `…065821Z_dev_false_alerts.json`): p = 99.67. Any-group Watch 1.95% of calibration samples and 2.00% of normal dev; each group about 0.33%. False alerts unchanged (0.919 per 24 h).
  - **Right place** (`…073949Z_dev_table_pca_static.json`): 0.69 (0.67–0.70) at the notification, 0.54 (0.52–0.56) 30 min later. Faults 1, 2 and 8 score 0: composition shows only in the analyzers, which the detector doesn't use. Attribution drifts by +30 min, which supports reading it at the notification.
  - **Parity:** the committed replay stream through `pca_v2` equals the evaluation path on the real dev run (`pytest -m opendata`).
  - **Authoring** (`…20261001T182856Z_authoring.json`): faults 1, 4, 5, 6 detected on 5 of 5 authoring runs, fault 13 on 4 of 5 (late).
- **Findings, in plain terms:**
  1. RBC places most faults in the right group, and fails honestly where the cause is invisible to the detector's tags.
  2. The plant-level Watch cap holds on unseen normal runs.
  3. The five entries' signatures agree with their authoring evidence, and their texts claim nothing the evidence doesn't show.
  4. **No entry is approved yet.** That's deliberate: decision 24 needs real entry tests, which come with the matcher.
- **A process lesson:** S5's real-data parity test first skipped silently (the conftest's data wall turned a loader error into a skip), and "passes" was reported. It now fails rather than skips on a loader error, and the S5 log says so. An `s` in pytest output needs checking.
- **Carried to week 5 (open):**
  - **Approve the five drafts:** the entry-test runner with the matcher, then `eval/approve_entry.py`. The 24 h gap opens about 19:00 UTC on 2 October 2026 (created_at 18:58–19:03 UTC on 1 October).
  - **The published-number check (Must, Metrics):** still needs the paper's component count, agreement band and theoretical 99% limits.
  - **ISO 14224 category names:** Raj to verify; until then the fields hold `unverified`.
  - **Licences "to confirm"** in `eval/sources.yaml`.
  - **The r2 notes** from the reviews (minor).
  - **Bundle `pca_v3`** with the evidence normals, when the agent needs them at runtime.
  - **Not built:** RBC for DPCA (decision 64); dynamics in the features (decision 68).
- **Week 5 (26 Oct–1 Nov in the plan, starting early):** 7 more entries (12 in total), the matcher, the random-forest baseline, and the 3-hour LangGraph spike.

### 2026-10-02: week 5 kickoff, plan and Raj's answers
- **Changed:** docs only (this entry). No code, and nothing run.
- **Week 5 plan approved.** Each session stops for review and commit, and Raj runs every data job on a clean tree. Nothing touches the test split, faults 16–20 or the sealed folder.
  1. **S1:** decisions 69–72, made before any dev result: matcher scoring and decline (69), diagnosis cases on dev (70), entry tests (71), baselines (72). Claude drafts options; Raj chooses.
  2. **S2:** the matcher. Claude writes the stub and tests in `app/diagnosis/matcher.py`, and moves the signature-item evaluation out of `eval/approve_entry.py` into `app/`, so the gate and the matcher share it. Raj writes the scoring.
  3. **S3:** Claude writes `eval/cases.py` (authoring's scoring path, shared and parameterised by fault and pool) and `eval/entry_tests.py` (writes the `*_entry_tests.json` records the approval gate reads). Raj runs the entry tests and approves the five drafts through `eval/approve_entry.py`.
  4. **S4:** `eval/authoring.py --faults` for faults 2, 7, 8, 10, 11, 12 and 14, never overwriting a committed provenance file. Raj runs it.
  5. **S5:** Raj drafts seven r1 entries; Claude reviews them and runs the entry tests; Raj approves each 24 h after its `created_at`.
  6. **S6:** diagnosis metrics (Raj; Claude writes stubs and tests), the random floor, and the forest scaffolding (Claude).
  7. **S7:** the dev diagnosis table: matcher, forest on 5 runs, ceiling forest and random, with top-k, decline thresholds and leave-one-out on faults 2 and 11. This is the week's "Done when".
  8. **S8:** the 3-hour LangGraph spike in `spikes/langgraph/`, against pass criteria Raj writes first; the verdict for week 6; the week close.
- **Raj's answers:**
  1. **Entry tests (for decision 71):** authoring runs only, ranked first with ties allowed. On its own detected authoring runs, the entry has no required contradictions and is first or tied for first. On every other entry's detected authoring runs, it never ranks strictly above the right entry. Ties are honest ambiguity between physical twins (a step and a random variation of the same disturbance); they show up in the dev table, not as a failed approval.
  2. **New entries and approved ones:** a new entry must not break approved ones. Before a new entry is approved, every approved entry's tests are re-run on the larger library. If one fails, the new entry is revised before its approval. An old entry gets an r2, through the normal approval, only if it's shown to be too broad. Approved entries stay in force meanwhile.
  3. **Readings (for decision 69):** both are reported, with provisional (+30 min) as the headline, consistent with decision 65. The +30 min diagnosis scores the provisional items; the +60 min diagnosis scores both readings.
  4. **The matcher** lives in `app/diagnosis/matcher.py`.
  5. **Dependencies:** scikit-learn and langgraph are approved, pinned in `requirements.txt`, and not in `requirements-app.txt` until week 6 needs them.
  6. **The forest:** Claude writes the scaffolding; Raj fixes its hyperparameters in decision 72 before it runs.
  7. **The spike** lives in `spikes/langgraph/`.
  8. **Hours:** all 12 entries stay. If time runs short, the spike moves ahead of S7.
  9. **Carried items** (the published-number check, ISO 14224 names, source licences, the r2 notes) stay parked this week.
- **Tests:** none (docs only). The suite is unchanged: 1306 passed, 3 deselected (last run in week 4 S8).
- **Unsure about:**
  - **Hours.** Eight sessions will likely exceed 15 h.
  - **Thin authoring evidence.** Faults 2, 8 and 10 may be detected on few of their 5 authoring runs. If any has 0 of 5, it goes under Decisions needed; no other runs are swapped in.
  - **Answer 1 and step vs random twins:** under "never strictly above", a twin pair that always ties passes both entries' tests, so the approval gate doesn't separate them. The dev table will show how often they tie.
- **Decisions needed:** decisions 69–72 in S1.

### 2026-10-02: week 5 session 2, shared item verdicts, matcher stubs and tests
- **Note on S1:** commit f3932a8's message names decisions 69–72, but it only adds the S0 entry here. `docs/decisions.md` still ends at 68, and PROTOCOL is unchanged (it still says McNemar). S2 is built from Raj's pasted decision 69 text, which the matcher's docstring quotes and marks "not yet written into docs/decisions.md".
- **Changed:**
  - **`app/diagnosis/items.py` (new, Claude):** one definition of agree, contradict and unknown for a signature item against `features.extract()`'s dict (one engine, decision 19).
    - **unknown:** the item's reading is missing (past the end of the run), or an analyzer is `not_yet_available` and the item doesn't accept that.
    - Items keep the gate's order and names; each carries its scope (location, provisional, revised) and weight.
  - **`eval/approve_entry.py`:** `_items` is removed. `agreement()` now counts `verdict == agree` from `app/diagnosis/items.py`. Behaviour is unchanged: unknown and contradict both count against an item, as a missing reading did before. `--check` on two real drafts gives the same gate results as before (schema and provenance pass, entry_tests fails).
  - **`app/diagnosis/matcher.py` (new; stubs for Raj, plus wiring):**
    - Constants `WEIGHTS` (required 2, supporting 1) and `SCOPES` (+30 min: location and provisional; +60 min: everything).
    - The `Score` type.
    - Stubs that raise `NotImplementedError`: `score`, `rank`, `credit`, `decline`.
    - Wiring by Claude: `candidates` (the revisions in force via `Library.in_force`, by entry_id) and `match` (candidates, then score, then rank; refuses an unknown diagnosis time).
  - **Conventions in the docstring (Claude's, to confirm):**
    - fit is an exact `Fraction`, so ties are exact.
    - A ranking is a list of tied blocks ordered by ref.
    - Top-k credit for a block covering ranks a..b (m entries) is 1 if k ≥ b, 0 if k < a, else (k − a + 1)/m.
    - "Below the threshold" is strict, and an empty ranking declines.
    - The threshold is an argument, so per-time or shared thresholds both fit.
- **Tests: `tests/test_matcher.py`, 41 tests:**
  - **Passing now (15):** the item order, scopes and weights; exact match; contradictions; `one_of`; a missing reading is unknown; analyzer `not_yet_available`; the gate uses the shared items, with unknown counting against an item; the decision 69 constants; candidates as-of (none, a withdrawn entry in force before its r2, a draft never, a later approval); a naive time refused; `match` refusing an unknown time; the wall for `app/diagnosis`.
  - **Failing with `NotImplementedError` until Raj implements (26):** scores by hand (exact match 8/8 and 10/10; a required contradiction 1/2 and 1/5; a supporting contradiction 6/8; `one_of`; unknown supporting 7/8 and required 7/9; a missing revised reading 4/5); fit is exact; ranking (contradictions first, ties as one block, empty); credit (8 cases, a three-way tie at first, a block lower down); decline (every entry with a required contradiction, the threshold strict, empty); `match` returns only entries in force.
  - **`pytest -q`:** 26 failed, 1321 passed, 3 deselected (1306 before, plus the 15 new passing tests). All 26 failures are the matcher stubs' `NotImplementedError`; nothing else fails. There's one warning, which doesn't come from the matcher, approval or library tests.
- **The idea (for Raj):** a similarity score (an embedding or a cosine) rewards how much two patterns overlap. A single opposite reading, such as a valve high where the entry needs it low, barely moves it, so a near-mirror-image fault can look like a close neighbour. Counting agreements and contradictions per listed item makes one required contradiction decisive (it ranks the entry below every entry without one). The score also explains itself, item by item, which the faithfulness check and the reviewer can trace (decision 15).
- **Unsure about:**
  - **An entry with nothing listed in scope** (only revised items) would divide by zero at +30 min. None of the five drafts does this; decision 69 doesn't say. Raj's call: refuse it in the schema, or define fit for it.
  - **The credit formula for top-k** is my reading of "the same way".
  - **Not Claude's:** `eval/baselines/alarms.py` has a 2-line change from the IDE again. Left alone.
- **Decisions needed:**
  - **Record decisions 69–72 and the PROTOCOL mirrors,** with answers to S1's six points (leave-one-out correctness, McNemar, the forest under leave-one-out, decline thresholds per time, the random floor's family accuracy, the wording).
  - Confirm the conventions above, and the zero-weight case.
- **Next (Raj):** implement `score`, `rank`, `credit` and `decline`, then `pytest -q tests/test_matcher.py`.

### 2026-10-02: week 5 session 2 (close), matcher implemented, decisions 69–72 recorded
- **Raj:** implemented `score`, `rank`, `credit` and `decline` in `app/diagnosis/matcher.py` (with guidance from the Claude.ai chat). 40 of 41 matcher tests passed. The one failure was a test typo, which Raj found: `test_match_ranks_only_entries_in_force` compared a sorted list with `[ENTRY, THIRD]`, which should be `[THIRD, ENTRY]`.
- **Claude's review of the matcher (as reviewer):** it follows decision 69 and the conventions.
  - Scope by diagnosis time; weights 2 and 1; unknown counted in the total only.
  - Fit as an exact fraction; blocks keyed on (required contradictions, fit) and ordered by ref.
  - The credit formula as specified.
  - Decline on an empty ranking, a required contradiction in the top block (rank puts the fewest first, so then every entry has one), or a fit strictly below the threshold.
  - `score` also raises on a zero total, which the new schema rule now prevents.
  - No issues found.
- **Changed:**
  - **`tests/test_matcher.py`:** the typo fixed (test only; the matcher untouched).
  - **`app/library/schema.py`:** a signature must list at least one location or provisional item, so every entry can be scored at +30 min (Raj's answer to the zero-weight case).
  - **`tests/test_library.py`:** that refusal added to the invalid-revision cases; two new valid cases (a location item only, a provisional item only, with the required item in revised). The five real entries still load.
  - **`docs/decisions.md`:** a new "Week 5 decisions" section with decisions 69–72, from Raj's S1 text and his answers to the six points. Claude's conventions are marked confirmed.
  - **`eval/PROTOCOL.md`:** the mirrors.
    - Pre-registered values: top-k counts tied blocks fractionally, and there's one decline threshold per diagnosis time for the matcher and each forest.
    - Cases: leave-one-out for the matcher and the forests (correct only when declined, family accuracy alongside, forests retrained without the left-out classes), plus the dev cases and false-alert cases.
    - Methods: the random floor's analytic values; the forests' training sets and fixed hyperparameters; the matcher's ranking.
    - Metrics: the paired bootstrap as the headline, with McNemar alongside.
    - Governance: entry tests before approval.
- **Tests:** `pytest -q` gives 1350 passed, 3 deselected (+26 matcher, +3 schema). The one warning is the old `httpx2` deprecation notice from the test client.
- **Claude's readings, to confirm:**
  - **Leave-one-out scope.** Answer 1 ("correct when declined") is recorded for the matcher and the forests, which can't flag a family-level answer. PROTOCOL's rule for the agent on test is left as it was: a decline, or a family-level answer flagged "mechanism not in library". So are decision 42's cut-line scoring and the LLM keep rule's "unknowns declined". If answer 1 was meant for every method, those lines change too.
  - **The forest seed:** the S1 text says the seed is recorded in the decision, but gives no value. Decision 72 says "value to be set by Raj before the forests run in S6".
- **Not changed:** `app/diagnosis/matcher.py`'s module docstring still says decision 69 is "not yet written into docs/decisions.md" and calls the conventions "to confirm", and says the threshold question is "open in S1". These lines are now out of date. It's Raj's file, so it was left as it is.
- **Not Claude's:** `eval/baselines/alarms.py` still shows a 2-line change from the IDE. Left alone.
- **Decisions needed:**
  - The forest seed's value (decision 72), before S6.
  - Confirm the leave-one-out scope above.
- **Next:** S3, the case builder (`eval/cases.py`) and the entry-test runner (`eval/entry_tests.py`), then Raj runs the entry tests and approves the five drafts.

### 2026-10-02: week 5 session 3, case builder and entry-test runner (code only, nothing run)
- **Changed:**
  - **`eval/cases.py` (new, Claude):** `python -m eval.cases <pool> [--faults …]`.
    - Authoring's scoring path, moved here unchanged:
      - `load_inputs` loads the model, limits, Watch boundaries and evidence normals, each checked against its record.
      - `publications_from_held` is unchanged.
      - `score_pool` gives the per-run detection and features at the first notification after onset.
    - Pools: `authoring`, `dev` and `forest_ceiling`. Faults: the 12 known faults only (3, 9, 15 and 16–20 are refused before loading).
    - Writes `data/cases/<stamp>_<pool>/fault_NN.json` (gitignored: labels and run numbers) and a `cases` run record holding each file's SHA-256.
    - Refuses a dirty tree before loading, and never overwrites.
  - **`eval/authoring.py`:** now calls `cases.load_inputs` and `cases.score_pool`. `AuthoringError` and `publications_from_held` are aliases of the shared ones. FAULTS, the refusals and the provenance files are unchanged. S4 adds `--faults`.
  - **`eval/entry_tests.py` (new, Claude):** `python -m eval.entry_tests <entry_id> <k>`, decision 71's tests.
    - **The library under test:** the revisions in force now, with the subject in place of its own entry's revision. Other drafts are left out.
    - **The cases:** the detected runs in each entry's provenance file. Each file must be named in the entry key and written by a committed authoring record, as the approval gate requires. Nothing is loaded from data/.
    - **The tests, at both diagnosis times, through the matcher:** self, specificity, and regression (every other entry's self and specificity on the larger library). An entry with no detected run fails its self test.
    - **The record:** `*_entry_tests.json` with `config.entry` (`entry_id@r<k>`), `as_of`, the library (each reference and revision-file SHA-256, each provenance path and SHA-256), and `metrics.passed` plus the failure counts. That's the shape the approval gate reads.
    - It prints every failure, refuses a dirty tree before reading anything unless `--allow-dirty` (a dirty record never satisfies the gate), and exits 0 only when passed.
- **The pin on authoring's output:**
  - **`tests/test_authoring.py`, every push:** `GOLDEN` is the SHA-256 of the provenance content (everything but commit, dirty, record and input paths), taken from the pre-S3 code (b1c0edc) on the synthetic fixture, twice, with the same value both times. It still matches after the move.
  - **`tests/test_cases_opendata.py`, opt-in (`pytest -q -m opendata`):** recomputes the five committed provenance files from the inputs they name, and checks runs, per-run evidence and summary for equality. Not run: it reads data/. Missing data or models skip it; a loader error fails it.
- **Tests:**
  - **`tests/test_cases.py` (18):**
    - the 12 known faults and pools; data/cases is gitignored
    - authoring uses the shared path
    - the same per-run evidence as authoring
    - dev files and record; all 12 by default
    - nine bad requests refused before loading; a dirty tree; never overwriting; `main`
  - **`tests/test_entry_tests.py` (20):**
    - **Passing:** an entry alone, with the record's shape; the approval gate accepting the record; a distinct approved entry; a tied twin.
    - **Failing:** a required contradiction (2 failures, one per time); not first (8); specificity with regression flagging the other entry (8 and 8); no detected run.
    - **Which library:** other drafts left out; an approval after as_of left out; r2 replacing r1; the approved revision as the subject.
    - **Refusals:** unknown revision; an entry without provenance; provenance no record wrote; a dirty tree writes nothing; `--allow-dirty` writes a record the gate ignores; nothing written under library/; `main`'s exit codes.
  - **`pytest -q`:** 1389 passed, 4 deselected (the new opendata test is the fourth). The one warning is the old `httpx2` notice.
- **Not run:** `eval.cases`, `eval.entry_tests` and the opendata pin. Nothing touched data/ or the test split.
- **The idea (for Raj):** the entry tests replay the matcher on the evidence each signature was written from. Self asks whether an entry recognises its own runs. Specificity asks whether it steals another entry's runs. Regression asks whether adding it breaks anything already approved. Only authoring runs are used, so passing says nothing about dev; that's what S7's table is for.
- **Unsure about:**
  - **The library is "in force now".** An approved entry whose `effective_from` is still in the future is left out of the library under test, so a test run before then won't see it.
  - **Regression reports, but doesn't name a culprit.** If an approved entry fails, the subject is the likely cause (decision 71: revise the new entry). The printed messages show which runs.
  - **Normal dev runs** (decision 70's false-alert cases) aren't in `cases.py` yet. They need every notification, not the first after onset, so they come with S7.
  - **Drafts aren't tested against each other.** Decision 71's library is the approved entries plus the subject, so the order of approval decides which pairs are checked when. Sequential approval covers every pair (Next, step 2). Testing all drafts together isn't in decision 71.
- **Decisions needed:**
  - **The order effect above:** keep sequential approval (it covers all pairs, and the first-approved entry is never tested as the subject against the others), or add a pre-approval check of all drafts together? I lean to sequential, since regression covers the reverse direction.
  - Carried: the forest seed's value (decision 72), and the leave-one-out scope from S2.
- **Next (Raj), on a clean tree after review and commit:**
  1. Optional: `pytest -q -m opendata tests/test_cases_opendata.py` (the pin on real data).
  2. **One entry at a time, in sequence:** `python -m eval.entry_tests <entry> 1`, commit the record, `python -m eval.approve_entry <entry> 1 --approver raj-review`, commit the approval, then the next entry.
     - The library under test holds only approved entries plus the subject. Run all five tests first and each draft is tested alone, and the five are never checked against each other.
     - In sequence, the k-th entry's specificity and the regression check cover every pair with the entries approved before it, so all ten pairs get checked once all five are in.
     - The order of the five is Raj's choice. If a later entry fails against an earlier one, decision 71 says revise the later one (an r2 for the earlier one only if it's shown to be too broad).
