<!-- Destination: eval/TEST_PLAN.md -->
# The frozen test run: test plan (DRAFT for Raj's review; not committed, not tagged)

This plan fixes everything the test run uses before any sealed data is opened. It goes with
`eval/PROTOCOL.md` v2, whose pre-registered values it adds to, and both are tagged together.
Every value here comes from Raj's S0 answers 1–26 (`docs/log.md`, week 7 kickoff), his S1
answers Q1–Q4, the S1e and S2 answers, or a committed record named beside it.

**Scope (Raj):** no Should item is built before the test run. Any Should work comes after it,
is evaluated on dev only, and is reported as a post-test extension, never in these tables.

## 1. Freeze and tag
- **The freeze:** this file and PROTOCOL v2 are committed together. That commit is tagged
  `protocol-v2-frozen` and pushed to GitHub before the first command of section 4 (S0 answer 2).
- **One commit for the whole run:** every command in section 4 runs on the tagged commit with
  a clean tree. Records in `eval/runs/` and the access log don't count as dirty, so the
  records can be committed after the run.
- **Crash or budget stop (S0 answer 3):**
  - **If it happens before any metric has been shown:** the fix goes in a logged patch commit
    whose diff touches only the crash, and the command is rerun under the same tag. Both
    attempts stay in the access log and the session log.
  - **Once any metric has been shown:** any change is a new protocol version, and both results
    are reported.
- **Every test record is committed,** including incomplete ones (PROTOCOL, Reporting).

## 2. Frozen values

### Detector and inputs (open data, fixed by checksum)
| Item | Value | Source |
|---|---|---|
| Detector | static PCA, 33 fast tags, k = 12 | `eval/runs/20260927T093509Z_fit_pca.json` |
| Model | `data/models/pca_static.npz`, SHA-256 `1e4aa9e6…afae5` | the fit record |
| Limits | `data/models/pca_static_limits.json`, SHA-256 `0fae67e5…9371e`: n = 3, G = 15, q = 95.57, warm-up 9, L = 0 | `eval/runs/20260927T150527Z_calibrate_pca.json` |
| Watch boundaries | `data/models/pca_static_watch.json`, SHA-256 `9a841978…3ec7b`, p = 99.67 | `eval/runs/20260929T065812Z_calibrate_watch.json` |
| Evidence normals | `data/models/evidence_normals.json`, SHA-256 `7a12d045…ed631` | `eval/runs/20261001T182856Z_evidence_normals.json` |
| Alarm baseline, realistic list | `data/models/alarms_realistic_limits.json`, SHA-256 `3562506e…c8f20` (grouped and ungrouped rows) | `eval/runs/20260928T105104Z_calibrate_alarms_realistic.json` |
| Alarm baseline, every tag | `data/models/alarms_every_limits.json`, SHA-256 `833c97bd…be37` | `eval/runs/20260928T105126Z_calibrate_alarms_every.json` |
| DPCA (confirmation row only; A) | model `data/models/pca_dynamic.npz`, SHA-256 `33433c41…201f`; limits `data/models/pca_dynamic_limits.json`, SHA-256 `e8b8c436…a558c`: L = 1, n = 3, G = 13, q = 97.07, warm-up 9 | `eval/runs/20260928T172623Z_fit_dpca.json`, `eval/runs/20260928T175708Z_calibrate_pca.json`; selection `eval/runs/20260929T020335Z_select_detector.json` (decision 63) |
| Masked list | fault 4 (RX-FV-206); 1–3 and 5–15 unmasked; 16–20 "not labelled" (S0 answer 8) | `eval/runs/20260928T155738Z_masked_faults.json` |
| Bundle | `app/bundles/pca_v3` (the agent's tools) | decision 75; S2 of week 6 |
| Data | `dataset/manifest.yaml` SHA-256 `b5f36f53…c95`; `dataset/splits.yaml` SHA-256 `99fdaabb…202c` | the manifest |

### Detection (S0 answers 5–10; S1 Q3, Q4; S1e)
- **Runs:** all 500 runs of each testing-file fault 1–20 and all 500 normal testing runs,
  with the fault after sample 160 (S0 answers 5, 6). Faults 16–20 come from the testing file only.
- **Bootstrap:** run-number bootstrap, B = 2000, seed 20261001. Test run numbers are treated
  as shared across files (S0 answer 7).
- **Twin check (S0 answer 9, S1 Q3):** samples 1–160, exact float32 equality on the 33 fast
  tags, all or nothing. If the twins aren't shared, "detected before divergence" reads
  "not reported".
- **Summaries (S1 Q4; Raj's addition 1):**
  - **Detection:** the summary covers faults 1–20 except 3, 9 and 15 (PROTOCOL). Two more
    means are reported beside it:
    - over the same 12 faults as dev (1–15 except 3, 9, 15), so dev and test compare like for like
    - over faults 16–20 on their own

    Faults 3, 9 and 15 keep their separate mean. Each is an equal-weight mean with a joint
    run-number bootstrap.
  - **Right place:** summarised over the 12 family faults. Faults 16–20 read "n/a" for family and right place.
  - **Code needed before the freeze:** `dev_table --split test` computes only the 17-fault
    summary and the 3, 9, 15 mean today. The 12-fault and 16–20 means must be added and
    tested before the tag (Claude's driver change).
- **Detector rows:** static PCA (the shipped detector) and DPCA, which is a confirmation row
  only (Raj's answer A; PROTOCOL: "test only confirms the choice"). Static PCA stays shipped
  whatever DPCA shows. Also the four alarm rows: realistic and every-tag lists, grouped and
  ungrouped.
- **Masked column:** on every row, including the alarm rows (Raj's answer B). It's a label on
  the fault, and no metric changes.
- **Lead time:** against the realistic list's grouped row (decision 60).
- **Plots (S0 answer 10):** the cumulative detection curve is drawn from the PCA test table
  record (horizons 6 … 240 min). The AMOC curve covers static PCA only, with the pooled median
  delay and the operating point at q = 95.57 (S1e). The README shows at most one cumulative figure.

### Diagnosis without the LLM (S0 answers 11–13, 16; S1 Q2)
- **Library as-of:** `2026-10-05T00:00:00+00:00`. Every entry is at r1 except
  `mixed-feed-temperature-wander` at r2.
- **Matcher rules (S0 answer 11):** threshold 1/3 at the provisional time and 5/11 at the
  revised time, k = 2. They're re-derived on dev at that library and must equal the
  fingerprint record's exactly. The week 5 values are recorded beside them.
- **Forests (S0 answer 13):** refit with seed 20261002 from the authoring and ceiling runs,
  with no pickles. Before any test load, every rule and every forest's per-case dev
  probabilities must match the **`diag_fingerprint` record** (not yet made: section 3). On a
  mismatch the run stops.
- **Scopes (S0 answer 12):** all detected test runs, and the subsample. The paired bootstrap
  runs on the subsample only.
- **Leave-one-out (S0 answer 16):** one entry removed at a time, at the full library's thresholds:

  | Fault | Entry removed |
  |---|---|
  | 1 | `mixed-feed-reactant-ratio-shift@r1` |
  | 4 | `reactor-cooling-water-warm-supply@r1` |
  | 5 | `condenser-cooling-water-warm-supply@r1` |
  | 13 | `reaction-rate-drift@r1` |

- **Unknown faults 16–20:** correct only when declined.

### The agent and the LLM (S0 answers 14–19, 21, 22)
- **Model and settings (decision 76):**
  - `gemini-3.1-flash-lite`, temperature 0, `thinking_level` minimal, 1024 max output tokens
  - schema `diagnosis-1`
  - prices read on 4 October 2026 ($0.25 and $1.50 per 1M tokens; INR 96.33 per USD)
- **Prompt:** SHA-256 `fa39b73e6acc48a3fd253852a812fba4d793866fe755f310ab066cbd211c5ee0`,
  checked again on 5 October 2026.
- **Subsample (S0 answer 14):** seed 20261006. One draw of 10 run numbers out of 1–500, used
  for every fault and for the normal runs' false-alert cases.
- **False alerts (S0 answer 15):** every notification on the 10 drawn normal runs, with no cap.
  More than 50 stops the run, and Raj is told.
- **Shipped flow (decision 79):** the shipped flow, the matcher alone and the LLM re-ranker,
  from the same passes. The keep rule is reported, not applied (S0 answer 19). The LLM-only
  diagnostic is "not run" (S0 answer 18).
- **The keep rule's unknowns:** on test these are faults 16–20 plus the leave-one-out cases.
  As on dev (decision 77, B2), a failed check or an API error on an unknown case counts as
  not declined for the keep rule only (Raj's addition 2). Everywhere else it scores as no
  diagnosis, reported separately. The driver reads the 16–20 rows as unknown rows under B2.
- **Budget (S0 answer 17):**
  - The cap is Rs 500, on Tier 1, with `--min-interval 1`.
  - The dry run's expected cost must be at most Rs 400 at 5 repeats. If it's over, repeats
    are cut to 3, never cases. If 3 is also over, the run stops and Raj is told.
- **Latency:** per call from the batch. Cold start is "not applicable".
- **Outputs (S0 answers 21, 22):** the LLM cache, per-case rows, `calls.jsonl`, the ledger
  and the case-listing tables stay in `~/PycharmProjects/plant-health-sealed/`. Only
  aggregates are committed.

### Not run on test (dev only)
- the published-number check and its FAR-matched diagnostic (decision 56)
- the safety set (decision 78)
- the memorization probes (LEAKAGE wall 2)
- any Should item

## 3. Before the freeze (dev only; no sealed data)
1. **Raj:** run the forest fingerprint on dev and commit it:
   ```
   python -m eval.diag_table --library-as-of 2026-10-05T00:00:00+00:00 --fingerprint
   ```
   It writes `eval/runs/<stamp>_diag_table.json` and `eval/runs/<stamp>_diag_fingerprint.json`.
2. **Claude:** read the fingerprint record and check that its matcher thresholds and k equal
   the dev agent run's (`eval/runs/20261005T021042Z_agent_run.json`: 1/3 provisional, 5/11
   revised, k = 2). Then put its path in place of `<FP>` in section 4.
3. **Claude (once approved):** add the two extra detection means to `dev_table --split test`
   (the 12 dev-equivalent faults, and faults 16–20), with tests. It's a driver change only;
   the metric functions are unchanged. Raj reviews and commits it.
4. **Raj:** review this plan. Then commit this file and PROTOCOL, tag `protocol-v2-frozen`,
   and push the commit and the tag. `pytest -q` must be green on the tagged commit.

## 4. The command sequence (Raj runs every command; Claude reads the records only)
Every command that opens sealed data starts with `EVAL_MODE=1`. Each one writes one access-log
line per file it loads, 219 lines in all (expected counts below). In the paths below,
`<FP>` is the fingerprint record, and `<TWIN>`, `<DRY>` and `<RUN>` are the records made in
steps 1, 11 and 12.

| # | Command | Expected output | Access-log lines |
|---|---|---|---|
| 1 | `EVAL_MODE=1 python -m eval.twin_check` | "fault f: N of 500 runs match their twin on samples 1-160" for f = 1–20; "verdict: shared" or "not shared"; a `twin_check` record | 21 |
| 2 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check <TWIN> --limits data/models/pca_static_limits.json --model data/models/pca_static.npz --lead-vs data/models/alarms_realistic_limits.json --masked eval/runs/20260928T155738Z_masked_faults.json --watch data/models/pca_static_watch.json` | "test: 500 run numbers x 20 faults; detector pca_static"; the mean detection over faults 1–20 except 3, 9, 15; a `test_table_pca_static` record and table | 21 |
| 3 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check <TWIN> --limits data/models/pca_dynamic_limits.json --model data/models/pca_dynamic.npz --lead-vs data/models/alarms_realistic_limits.json --masked eval/runs/20260928T155738Z_masked_faults.json` (DPCA, confirmation only; no Watch file, as on dev) | "detector pca_dynamic"; a `test_table_pca_dynamic` record and table | 21 |
| 4 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check <TWIN> --limits data/models/alarms_realistic_limits.json --row grouped --masked eval/runs/20260928T155738Z_masked_faults.json` | a `test_table_alarms_realistic_grouped` record | 21 |
| 5 | the same as 4 with `--row ungrouped` | `test_table_alarms_realistic_ungrouped` | 21 |
| 6 | the same as 4 with `--limits data/models/alarms_every_limits.json --row grouped` | `test_table_alarms_every_grouped` | 21 |
| 7 | the same as 6 with `--row ungrouped` | `test_table_alarms_every_ungrouped` | 21 |
| 8 | `EVAL_MODE=1 python -m eval.curves amoc --split test --limits data/models/pca_static_limits.json --model data/models/pca_static.npz` | "test: 509 AMOC points; operating point q = 95.57: …"; a `test_amoc` record | 18 |
| 9 | `python -m eval.curves plot eval/runs/<stamp>_test_table_pca_static.json` and `python -m eval.curves plot eval/runs/<stamp>_test_amoc.json` | two PNGs in `data/plots/` (records only, no data) | 0 |
| 10 | `EVAL_MODE=1 python -m eval.diag_table --split test --library-as-of 2026-10-05T00:00:00+00:00 --fingerprint-record <FP>` | the dev gather, then the fingerprint matching (or a stop before any test load); "test, provisional, subsample: top-1 matcher …"; a `test_diag_table` record; cases in the sealed folder | 18 |
| 11 | `EVAL_MODE=1 python -m eval.agent_table --split test --dry-run --library-as-of 2026-10-05T00:00:00+00:00 --prompt-sha256 fa39b73e6acc48a3fd253852a812fba4d793866fe755f310ab066cbd211c5ee0 --fingerprint-record <FP>` | case counts per kind; projections at 5 and 3 repeats; "paid run: --repeats 5" (or 3, or STOP); a `test_agent_dry_run` record. It stops if there are more than 50 false-alert cases. | 18 |
| 12 | `EVAL_MODE=1 python -m eval.agent_table --split test --evaluation --library-as-of 2026-10-05T00:00:00+00:00 --prompt-sha256 fa39b73e6acc48a3fd253852a812fba4d793866fe755f310ab066cbd211c5ee0 --fingerprint-record <FP> --dry-run-record <DRY> --billing-tier tier-1 --min-interval 1 --repeats <as the dry run says>` | "test run: N of N passes; Rs … spent"; a `test_agent_run` record (incomplete if the budget stops it) | 18 |
| 13 | `python -m eval.agent_table --table <RUN>` | a `test_agent_table` record; tables in `data/tables/` (no case IDs) and in the sealed folder (with them) | 0 |
| 14 | Commit `eval/runs/` and `eval/test_access.log`; Claude writes the log entry from the records | — | — |

**Stops:**
- **Step 10:** a fingerprint mismatch stops before any test load. That's a crash under section 1.
- **Step 11:** a STOP (more than 50 false-alert cases, or 3 repeats still over Rs 400) goes to Raj before step 12.
- **Step 12:** a budget stop leaves an incomplete record. That's a crash under section 1, and the record is never tabled.

## 5. Table layouts (empty; filled only from the records)

### 5.1 Detection, per fault (PROTOCOL; one table per detector row)
| Fault | Family | Masked | Detected (any / right place) | Chance rate | Detected before divergence | Median delay (IQR) | Share still flagged | Lead time vs grouped alarms |
|---|---|---|---|---|---|---|---|---|
| 1 … 20 | | | | | | | | |
| Mean, faults 1–20 except 3, 9, 15 (PROTOCOL's summary) | | | | | | | | |
| Mean, faults 1–15 except 3, 9, 15 (the same 12 as dev) | | | | | | | | |
| Mean, faults 16–20 | | | | | | | | |
| Mean, faults 3, 9, 15 | | | | | | | | |
| Normal operation | false alerts per 24 h (95% interval), hours counted | | | | | | | |

### 5.2 Alarm comparison (decision 60; notification window = the first 2 h)
| Row | List | Detected (mean) | Median delay | Notifications per episode | Per 10 min | Peak 10 min | Flood share | Chattering points per run |
|---|---|---|---|---|---|---|---|---|
| Per-tag alarms | realistic | | | | | | | |
| Per-tag alarms + grouping | realistic | | | | | | | |
| Per-tag alarms | every | | | | | | | |
| Per-tag alarms + grouping | every | | | | | | | |
| App 3 (static PCA) | — | | | | | | | |
| DPCA (confirmation only) | — | | | | | | | |

### 5.3 Attribution (decisions 64, 65; the 12 family faults)
| Fault | Family groups | Right place | Right place 30 min later | Top group (share) | Top tags |
|---|---|---|---|---|---|

### 5.4 Diagnosis without the LLM, per time (provisional is the headline), in two scopes: all detected test runs and the subsample
| Method | Top-1 | Top-3 | Family | Wrongly declined | Recall at k | End-to-end top-1 | False alerts declined | Unknowns declined (16–20) |
|---|---|---|---|---|---|---|---|---|
| matcher | | | | | | | | |
| forest5 | | | | | | | | |
| ceiling | | | | | | | | |
| random | | | | | | | | |

| Method | 16 | 17 | 18 | 19 | 20 |
|---|---|---|---|---|---|

| Fault left out | Entry removed | Method | Cases | Declined | Family |
|---|---|---|---|---|---|

Paired bootstrap of the top-1 difference, on the subsample only: matcher vs forest-5, and matcher vs ceiling.

### 5.5 The agent (decision 79), per time
| View | Top-1 | Top-3 | Family | Wrongly declined | False alerts declined | Leave-one-out declined |
|---|---|---|---|---|---|---|
| matcher | | | | | | |
| shipped, repeat 0 … R−1 | | | | | | |
| re-ranker, repeat 0 … R−1 | | | | | | |

| View | 16–20 declined | 16 | 17 | 18 | 19 | 20 | Leave-one-out declined | 1 | 4 | 5 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|

- **The keep rule:** reported, not applied, with unknowns = 16–20 plus leave-one-out.
- **The paired bootstrap** per repeat (seed 20261001).
- **The LLM's own answers:** confidence against accuracy, agreement across repeats (unstable cases: a count; the list is sealed), miss labels, vetoes and tie-breaks, failed checks and errors.
- **Latency and cost** per call. Cold start "not applicable"; LLM only "not run".

### 5.6 Curves
- the cumulative detection, test (one PNG)
- AMOC, test (one PNG, with the operating point marked)
- each beside its dev counterpart from S1e

## 6. Budget
- **Test LLM budget:** Rs 500, a hard cap per run, checked at worst case before each call (decision 76).
- **The projection rule:** the dry run's expected cost must be at most Rs 400 at 5 repeats. Otherwise repeats drop to 3, never cases. If 3 repeats is also over, stop.
- **Billed:** Tier 1. The cost per paid call on dev was about Rs 0.09. The dry run replaces any estimate.

## 7. Raj's answers to the review (6 October 2026)
- **A. DPCA on test:** yes, as a confirmation row only. Static PCA stays the shipped detector
  whatever DPCA shows. Pinned in section 2; it's step 3 of section 4.
- **B. `--masked` on the alarm rows:** yes. It's a label on the fault, and no metric changes.
- **C. The access-log count:** fine as written. 219 lines assume no crash and no rerun; any
  rerun adds its own lines, which are kept and explained.
- **Additions:**
  1. The 12-fault (dev-equivalent) mean and the 16–20 mean in the detection summary. This
     needs the code change named in section 2 before the tag.
  2. B2 for the keep rule on test's unknown cases (section 2).
  3. The safety set, the probes and the FAR-matched diagnostic are listed under "Not run on test".
