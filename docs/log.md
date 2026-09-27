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
