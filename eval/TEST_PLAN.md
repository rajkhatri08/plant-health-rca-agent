<!-- Destination: eval/TEST_PLAN.md -->
# The frozen test run: test plan (frozen at tag protocol-v2-frozen)

This plan fixes everything the test run uses before any sealed data is opened. It goes with
`eval/PROTOCOL.md` v2, whose pre-registered values it adds to, and both are tagged together.
Every value here comes from one of these, named beside it:
- Raj's S0 answers 1–26 (`docs/log.md`, week 7 kickoff)
- his S1 answers Q1–Q4, and his S1e and S2 answers
- his reviews of this plan (6, 8 and 9 October 2026)
- a committed record

**Scope (Raj):** no Should item is built before the test run. Any Should work comes after it,
is evaluated on dev only, and is reported as a post-test extension, never in these tables.

## 1. Freeze, tag and the crash rule
- **The freeze:** this file and PROTOCOL v2 are committed together. That commit is tagged
  `protocol-v2-frozen` and pushed to GitHub before the first command of section 4 (S0 answer 2).
- **The crash rule, per command (S0 answer 3, as refined in review):** a crash or stop may be
  patched under the same tag only if both of these hold:
  - the command that stopped, and every later command, has shown no metric
  - the patch touches only the crashed code path, and nothing that produced a result already shown

  The patch is a logged commit, and every attempt stays in the access log and the session log.
  Otherwise any change is a new protocol version, and both results are reported.
- **Patches and the dry run:** a patch after step 11 (the dry run) means rerunning the dry run
  on the patch commit. The code enforces this: the paid run refuses a dry run from another commit.
- **Reading the stops this way:**
  - **Step 10:** a fingerprint mismatch stops before any test load and has shown no metric,
    so it can be patched under the rule above.
  - **Step 12:** a budget stop is covered by the pre-registered rerun in section 6.
- **Every test record is committed,** including incomplete ones (PROTOCOL, Reporting). An
  incomplete record is never tabled.

## 2. Frozen values

### Detector and inputs (open data, fixed by checksum)
| Item | Value | Source |
|---|---|---|
| Detector (shipped) | static PCA, 33 fast tags, k = 12 | `eval/runs/20260927T093509Z_fit_pca.json` |
| Model | `data/models/pca_static.npz`, SHA-256 `1e4aa9e6…afae5` | the fit record |
| Limits | `data/models/pca_static_limits.json`, SHA-256 `0fae67e5…9371e`: n = 3, G = 15, q = 95.57, warm-up 9, L = 0 | `eval/runs/20260927T150527Z_calibrate_pca.json` |
| Watch boundaries | `data/models/pca_static_watch.json`, SHA-256 `9a841978…3ec7b`, p = 99.67 | `eval/runs/20260929T065812Z_calibrate_watch.json` |
| Evidence normals | `data/models/evidence_normals.json`, SHA-256 `7a12d045…ed631` | `eval/runs/20261001T182856Z_evidence_normals.json` |
| DPCA (a reported row only) | model `data/models/pca_dynamic.npz`, SHA-256 `33433c41…201f`; limits `data/models/pca_dynamic_limits.json`, SHA-256 `e8b8c436…a558c`: L = 1, n = 3, G = 13, q = 97.07, warm-up 9 | `eval/runs/20260928T172623Z_fit_dpca.json`, `eval/runs/20260928T175708Z_calibrate_pca.json`; selection `eval/runs/20260929T020335Z_select_detector.json` (decision 63) |
| Alarm baseline, realistic list | `data/models/alarms_realistic_limits.json`, SHA-256 `3562506e…c8f20` (grouped and ungrouped rows) | `eval/runs/20260928T105104Z_calibrate_alarms_realistic.json` |
| Alarm baseline, every tag | `data/models/alarms_every_limits.json`, SHA-256 `833c97bd…be37` | `eval/runs/20260928T105126Z_calibrate_alarms_every.json` |
| Masked list | fault 4 (RX-FV-206); 1–3 and 5–15 unmasked; 16–20 "not labelled" (S0 answer 8) | `eval/runs/20260928T155738Z_masked_faults.json` |
| Fingerprint | `eval/runs/20261008T181533Z_diag_fingerprint.json` (section 3) | Raj's dev run, commit af5ebc5 |
| Bundle | `app/bundles/pca_v3` (the agent's tools) | decision 75; S2 of week 6 |
| Data | `dataset/manifest.yaml` SHA-256 `b5f36f53…c95`; `dataset/splits.yaml` SHA-256 `99fdaabb…202c` | the manifest |

### Detection (S0 answers 5–10; S1 Q3, Q4; S1e; reviews)
- **Runs:** all 500 runs of each testing-file fault 1–20 and all 500 normal testing runs,
  with the fault after sample 160 (S0 answers 5, 6). Faults 16–20 come from the testing file only.
- **Bootstrap:** run-number bootstrap, B = 2000, seed 20261001. Test run numbers are treated
  as shared across files (S0 answer 7).
- **Twin check (S0 answer 9, S1 Q3):** samples 1–160, exact float32 equality on the 33 fast
  tags, all or nothing. If the twins aren't shared, "detected before divergence" reads
  "not reported".
- **Detector rows:**
  - static PCA, the shipped detector
  - **DPCA, a reported row only (review A, final):**
    - no paired comparison with static PCA, and no verdict
    - static PCA ships whatever it shows
    - the selection, made on the selection runs (decision 63), isn't reopened
    - the row only shows whether that choice holds up on held-out data
  - the conventional-alarm baseline's realistic and every-tag lists, grouped and ungrouped
- **Masked column:** on every row, alarm rows included (review B). PROTOCOL reports detection
  separately for masked and unmasked faults, and the masked fault is where alarms and PCA
  differ most. It's a label on the fault, and no metric changes.
- **Summaries (S1 Q4; review addition 1):**
  - **Detection:** the summary covers faults 1–20 except 3, 9 and 15 (PROTOCOL). Two more
    equal-weight means, each with a joint run-number bootstrap, are reported beside it:
    - over the same 12 faults as dev (1–15 except 3, 9, 15), so dev and test compare like for like
    - over faults 16–20

    Faults 3, 9 and 15 keep their separate mean.
  - **Right place:** summarised over the 12 family faults. Faults 16–20 read "n/a" for family and right place.
- **Lead time:** against the realistic list's grouped row (decision 60).
- **Plots (S0 answer 10):** the cumulative detection curve is drawn from the PCA test table
  record (horizons 6 … 240 min). The AMOC curve covers static PCA only, with the pooled median
  delay and the operating point at q = 95.57 (S1e). The README shows at most one cumulative figure.

### Diagnosis without the LLM (S0 answers 11–13, 16; S1 Q2)
- **Library as-of:** `2026-10-05T00:00:00+00:00`. Every entry is at r1 except
  `mixed-feed-temperature-wander` at r2.
- **Matcher rules (S0 answer 11):** threshold 1/3 at the provisional time and 5/11 at the
  revised time, k = 2. They're re-derived on dev at that library and must equal the
  fingerprint record's exactly (they do: section 3).
- **Forests (S0 answer 13):** refit with seed 20261002 from the authoring and ceiling runs,
  with no pickles. Before any test load, every rule and every forest's per-case dev
  probabilities must match the fingerprint. On a mismatch the run stops.
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
- **The three views (decision 79):** the shipped flow, the matcher alone and the LLM
  re-ranker, from the same passes. The LLM-only diagnostic is "not run" (S0 answer 18).
- **The keep rule:** reported, not applied (S0 answer 19).
  - **Its unknowns:** on test, faults 16–20 plus the leave-one-out cases.
  - **B2, as on dev (decision 77):** a failed check or an API error on an unknown case counts
    as not declined, for the keep rule only. Everywhere else it scores as no diagnosis,
    reported separately.
- **Repeats:** the paid run takes the dry run's `repeats_allowed` (section 6).
- **Latency:** per call from the batch. Cold start is "not applicable".
- **Outputs (S0 answers 21, 22):** the LLM cache, per-case rows, `calls.jsonl`, the ledger
  and the case-listing tables stay in `~/PycharmProjects/plant-health-sealed/`. Only
  aggregates are committed.

### Not run on test (dev only)
- **The published-number check and its FAR-matched diagnostic** (decision 56).
- **The safety set and the memorization probes:** done on dev in week 6 (decision 78; LEAKAGE
  wall 2). They need no test data.
- **Any Should item.**
- **The demo stays on dev data.** No test material goes into `app/` or the deploy (S0 answer 23).

## 3. Before the freeze (dev only; no sealed data)
1. **Done: the forest fingerprint** (Raj, 8 October 2026), committed with the freeze:
   - `eval/runs/20261008T181533Z_diag_fingerprint.json`, commit af5ebc5, clean, scikit-learn 1.9.1
   - made with `python -m eval.diag_table --library-as-of 2026-10-05T00:00:00+00:00 --fingerprint`
   - its `eval/runs/20261008T181533Z_diag_table.json` is committed with it
2. **Done: the check** (Claude). The fingerprint's matcher rules equal the dev agent run's
   (`eval/runs/20261005T021042Z_agent_run.json`):
   - provisional: 1/3, accepted 552/589, short
   - revised: 5/11, accepted 534/589, short
   - k = 2 at both times, with the same library and limits

   Its metrics and config are identical to the earlier fingerprint,
   `eval/runs/20261005T234505Z_diag_fingerprint.json`.
3. **Done: the two driver changes** (Claude, 9 October 2026, with tests; no metric function
   changes):
   - **a.** On test, `dev_table` also records, renders and prints the 12-fault
     (dev-equivalent) mean and the 16–20 mean.
   - **b.** The paid test run takes `--after-budget-stop <incomplete test_agent_run>` (section 6).
     Without `--repeats` it uses the dry run's `repeats_allowed`. Each paid record carries a
     `stop_kind`.
4. **Raj, in this order:**
   1. Commit this file, PROTOCOL, the fingerprint records and the driver changes.
   2. Check that `pytest -q` is green locally and CI is green on GitHub.
   3. Tag `protocol-v2-frozen`.
   4. Push the commit and the tag.
5. **No package installs or upgrades** from the fingerprint run to the end of step 13 of
   section 4. A scikit-learn change would break the fingerprint.

## 4. The command sequence (Raj runs every command; Claude reads the records only)
**No commits between steps 1 and 13. Records in `eval/runs/` and the access log don't make the
tree dirty, and the paid run refuses a dry run from another commit, so the whole sequence runs
on the tagged commit and everything is committed once, at step 14.**

- **`EVAL_MODE=1`:** every command that opens sealed data starts with it.
- **Access log:** each command writes one line per file it loads, 219 lines in all if nothing
  crashes.
- **Pasting:** every command pastes as written. A record made earlier in the sequence is
  picked up with `"$(ls -t eval/runs/*_<name>.json | head -1)"`, the newest of its kind.

| # | Command | Expected output | Access-log lines |
|---|---|---|---|
| 1 | `EVAL_MODE=1 python -m eval.twin_check` | "fault f: N of 500 runs match their twin on samples 1-160" for f = 1–20; "verdict: shared" or "not shared"; a `twin_check` record | 21 |
| 2 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check "$(ls -t eval/runs/*_twin_check.json \| head -1)" --limits data/models/pca_static_limits.json --model data/models/pca_static.npz --lead-vs data/models/alarms_realistic_limits.json --masked eval/runs/20260928T155738Z_masked_faults.json --watch data/models/pca_static_watch.json` | "test: 500 run numbers x 20 faults; detector pca_static" and three means: "faults 1-20 except 3, 9, 15", "faults 1-15 except 3, 9, 15 (as dev)" and "faults 16-20", each with its 95% interval; a `test_table_pca_static` record and table | 21 |
| 3 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check "$(ls -t eval/runs/*_twin_check.json \| head -1)" --limits data/models/pca_dynamic_limits.json --model data/models/pca_dynamic.npz --lead-vs data/models/alarms_realistic_limits.json --masked eval/runs/20260928T155738Z_masked_faults.json` (DPCA, a reported row only; no Watch file, as on dev) | "detector pca_dynamic" and the same three means; a `test_table_pca_dynamic` record and table | 21 |
| 4 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check "$(ls -t eval/runs/*_twin_check.json \| head -1)" --limits data/models/alarms_realistic_limits.json --row grouped --masked eval/runs/20260928T155738Z_masked_faults.json` | a `test_table_alarms_realistic_grouped` record | 21 |
| 5 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check "$(ls -t eval/runs/*_twin_check.json \| head -1)" --limits data/models/alarms_realistic_limits.json --row ungrouped --masked eval/runs/20260928T155738Z_masked_faults.json` | a `test_table_alarms_realistic_ungrouped` record | 21 |
| 6 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check "$(ls -t eval/runs/*_twin_check.json \| head -1)" --limits data/models/alarms_every_limits.json --row grouped --masked eval/runs/20260928T155738Z_masked_faults.json` | a `test_table_alarms_every_grouped` record | 21 |
| 7 | `EVAL_MODE=1 python -m eval.dev_table --split test --twin-check "$(ls -t eval/runs/*_twin_check.json \| head -1)" --limits data/models/alarms_every_limits.json --row ungrouped --masked eval/runs/20260928T155738Z_masked_faults.json` | a `test_table_alarms_every_ungrouped` record | 21 |
| 8 | `EVAL_MODE=1 python -m eval.curves amoc --split test --limits data/models/pca_static_limits.json --model data/models/pca_static.npz` | "test: 509 AMOC points; operating point q = 95.57: …"; a `test_amoc` record | 18 |
| 9 | `python -m eval.curves plot "$(ls -t eval/runs/*_test_table_pca_static.json \| head -1)"` then `python -m eval.curves plot "$(ls -t eval/runs/*_test_amoc.json \| head -1)"` | two PNGs in `data/plots/` (records only, no data) | 0 |
| 10 | `EVAL_MODE=1 python -m eval.diag_table --split test --library-as-of 2026-10-05T00:00:00+00:00 --fingerprint-record eval/runs/20261008T181533Z_diag_fingerprint.json` | the dev gather, then the fingerprint matching (or a stop before any test load); "test, provisional, subsample: top-1 matcher …"; a `test_diag_table` record; cases in the sealed folder | 18 |
| 11 | `EVAL_MODE=1 python -m eval.agent_table --split test --dry-run --library-as-of 2026-10-05T00:00:00+00:00 --prompt-sha256 fa39b73e6acc48a3fd253852a812fba4d793866fe755f310ab066cbd211c5ee0 --fingerprint-record eval/runs/20261008T181533Z_diag_fingerprint.json` | case counts per kind; projections at 5 and 3 repeats; "paid run: --repeats 5" (or 3, or STOP); a `test_agent_dry_run` record. It stops if there are more than 50 false-alert cases. | 18 |
| 12 | `EVAL_MODE=1 python -m eval.agent_table --split test --evaluation --library-as-of 2026-10-05T00:00:00+00:00 --prompt-sha256 fa39b73e6acc48a3fd253852a812fba4d793866fe755f310ab066cbd211c5ee0 --fingerprint-record eval/runs/20261008T181533Z_diag_fingerprint.json --dry-run-record "$(ls -t eval/runs/*_test_agent_dry_run.json \| head -1)" --billing-tier tier-1 --min-interval 1` (repeats come from the dry run) | "test run: N of N passes; Rs … spent"; a `test_agent_run` record (incomplete if the budget stops it: section 6) | 18 |
| 13 | `python -m eval.agent_table --table "$(ls -t eval/runs/*_test_agent_run.json \| head -1)"` | a `test_agent_table` record; tables in `data/tables/` (no case IDs) and in the sealed folder (with them) | 0 |
| 14 | Commit `eval/runs/` and `eval/test_access.log`. Claude writes the log entry from the records. | — | — |

(In this table `\|` stands for the shell's `|`. Markdown needs the backslash inside a table
cell; type `|` when pasting.)

**Stops:**
- **Step 10:** a fingerprint mismatch stops before any test load. That's a crash under section 1.
- **Step 11:** a STOP (more than 50 false-alert cases, or 3 repeats still over Rs 400) goes to Raj before step 12.
- **Step 12:** a budget stop follows section 6.

**After step 14, check the code is the tag's:**
- This prints nothing, or only a logged patch:
  ```
  git diff --stat protocol-v2-frozen HEAD -- . ':(exclude)eval/runs' ':(exclude)eval/test_access.log'
  ```
- Every test record's `commit` is the tag's commit (or the logged patch's).

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
| DPCA (reported row only) | — | | | | | | | |

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

- **The keep rule:** reported, not applied. On test its unknowns are faults 16–20 plus
  leave-one-out, with B2: failed checks and errors on them count as not declined.
- **The paired bootstrap** per repeat (seed 20261001).
- **The LLM's own answers:** confidence against accuracy, agreement across repeats (unstable cases: a count; the list is sealed), miss labels, vetoes and tie-breaks, failed checks and errors.
- **Latency and cost** per call. Cold start "not applicable"; LLM only "not run".

### 5.6 Curves
- the cumulative detection, test (one PNG)
- AMOC, test (one PNG, with the operating point marked)
- each beside its dev counterpart from S1e

## 6. Budget
- **Test LLM budget:** Rs 500, a hard cap per run, checked at worst case before each call (decision 76).
- **The projection rule (S0 answer 17):**
  - The dry run's expected cost must be at most Rs 400 at 5 repeats; otherwise repeats drop
    to 3, never cases. If 3 repeats is also over, stop and tell Raj.
  - The paid run takes the dry run's `repeats_allowed` when `--repeats` is omitted, and
    refuses any other count.
- **A budget stop at step 12 (pre-registered):**
  - Rerun at 3 repeats, with a budget of at most Rs 500 minus what was already spent.
  - `--after-budget-stop` enforces this. It requires that record to be from this commit and
    incomplete because of the budget, then defaults to 3 repeats and the budget left (rounded
    down to the paisa), and refuses anything else.
  - The cache serves every call already made, at no cost.
  - The stopped record is committed and never tabled.
  - **If the rerun stops too, stop and tell Raj.** The code refuses a second rerun.
  - The exact command, run right after the stop, while the stopped record is still the newest
    `test_agent_run`:
    ```
    EVAL_MODE=1 python -m eval.agent_table --split test --evaluation --library-as-of 2026-10-05T00:00:00+00:00 --prompt-sha256 fa39b73e6acc48a3fd253852a812fba4d793866fe755f310ab066cbd211c5ee0 --fingerprint-record eval/runs/20261008T181533Z_diag_fingerprint.json --dry-run-record "$(ls -t eval/runs/*_test_agent_dry_run.json | head -1)" --billing-tier tier-1 --min-interval 1 --after-budget-stop "$(ls -t eval/runs/*_test_agent_run.json | head -1)"
    ```
  - Step 13 then tables the newest `test_agent_run`, which is the completed rerun.
- **Billed:** Tier 1. The cost per paid call on dev was about Rs 0.09. The dry run replaces any estimate.

## 7. Raj's reviews
**6 October 2026:** DPCA as a confirmation row; `--masked` on the alarm rows; the access-log
count; addition 1 (the 12-fault and 16–20 means); addition 2 (B2 on test); addition 3 (the
dev-only list).

**8 October 2026 (with guidance from the Claude.ai chat):**
- no DPCA on test (since withdrawn, below)
- `--masked` on every alarm row
- reruns add their own access-log lines
- no commits between the first and last commands
- the crash rule per command
- the pre-registered budget-stop rerun
- the post-run check that the code is the tag's
- no installs
- section 3's order
- the dev-only list
- B2 on test's unknowns

**9 October 2026, final (with guidance from the Claude.ai chat):**
1. **A, final:** the DPCA row is restored as a reported row only, with no paired comparison
   and no verdict. Static PCA ships whatever it shows, and the selection isn't reopened. The
   8 October reversal was made without knowing about the original choice.
2. Driver change 3a is approved.
3. Driver change 3b is approved and made mechanical: `--after-budget-stop`, and repeats
   defaulting to the dry run's.
4. No placeholders in sections 4 and 6; `--repeats` is dropped from the paid run; the
   rerun's exact command is in section 6.
5. Step 2's expected output names all three detection means.
6. Section 3 step 1 is marked done.
7. The title.