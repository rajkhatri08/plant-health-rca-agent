<!-- Destination: docs/decisions.md -->
# Decisions

Each entry says what was decided and why. New decisions go at the bottom, with a date.

## Design review, September 2026

1. **Detection, not prediction.** App 3 is early fault detection and diagnosis. "Early" means lead time over grouped conventional alarms at the same false-alert budget. No remaining-life claims. *Why:* TEP faults are injected disturbances in 1–2-day runs, not slow degradation.

2. **Two-stage diagnosis, tested against real baselines.** A structured signature matcher ranks candidates; the LLM adjudicates, declines and explains. It's compared with random, a random forest (5-run label budget and all runs) and LLM-only, plus unknown-fault and leave-one-out tests. The LLM keeps its re-ranking role only if it beats the matcher by at least 5 points. *Why:* otherwise it's a classifier with extra steps.

3. **Three leakage walls.** Labels live only in `eval/` and the sealed folder; the agent sees plant-style tag names; the test split and unknown faults are sealed and every access is logged. *Why:* the agent, the model's memory and the builder can each leak the answer.

4. **Work orders as a controlled experiment (Should).** As-of queries, per-case seeded histories with knobs for real clues, misleading clues and documentation quality, and a canary condition. *Why:* synthetic history can hide the answer key.

5. **Every threshold comes from calibration data.** Run-level splits, empirical limits, one budget in false alerts per 24 hours for the whole pipeline, settings chosen on dev, and the protocol committed before any test run. *Why:* tuning on test invalidates every number.

6. **A fair alarm comparison.** Realistic per-tag alarms (deadbands, on-delays) at the same budget, plus a row with the same grouping rule. Notifications per episode in the first 2 hours are reported next to detection. App 3 is advisory and never touches control-system alarms. *Why:* a strawman baseline makes any reduction meaningless.

7. **Bad data and sensor faults (Should).** A data-quality layer; injected sensor faults outside control loops at four sizes; a sensor verdict needs positive evidence. Triage order: bad data, then sensor, then work in progress, then process. *Why:* real plants ask "is the sensor lying?" first.

8. **Show the time problem, then fix it.** Autocorrelation is plotted, not assumed. DPCA lags are chosen on the fit pool. The published-number check comes first, and the production detector is chosen on dev by a written rule. *Why:* static PCA ignores time, and averages hide failures.

9. **Reconstruction-based contributions.** One definition for every detector: the drop in score after rebuilding a tag from the others. Lags are combined per tag, and groups are rebuilt jointly. Contributions are symptom locations, not causes. *Why:* plain contributions smear blame onto healthy tags.

10. **Controllers.** The loop map comes from the control strategy that generated the data. Measurement held plus valve shifted means compensation, so look upstream. Watch valve headroom, and report masked faults separately. *Why:* controllers move faults into valves and can hide them almost entirely (IDV5).

11. **Analyzers.** Stored at the time each value became available, with its dead time. Used as diagnosis evidence only. Diagnosis is provisional at +30 minutes and revised at +60. *Why:* analyzers are slow, late and stepped.

12. **Status bands, not a 0–100 score.** Normal, Watch, Alert and Unknown, plus the ratio to the alert limit, all from the same statistic as the alerts. The plant view shows the worst group. *Why:* an undefined number can't be defended.

13. **An autoencoder only if it earns its place (Should).** Masked training, scaled errors, equal tuning budgets, inference-mode scoring. *Why:* a network that copies its input detects nothing.

14. **A fixed evidence path for diagnosis.** The router is used only for operator questions. *Why:* skipping evidence is the failure that matters.

15. **No vector search for signatures or the library.** Structured matching that counts contradictions; library entries fetched by ID; hybrid search only for documents. *Why:* embeddings treat opposites as neighbours and blur identifiers.

16. **Governance that changes answers.** One revision in force as of the diagnosis time; drafts invisible; overdue entries flagged, not dropped; author and approver are different accounts; each diagnosis records every version it used. *Why:* governance nobody tests does nothing.

17. **LangGraph for real features only.** A fixed graph, approval pause, saved state, +60 re-entry and injected as-of time. Nodes stay plain functions; a separate append-only diagnosis record; side effects run once. *Why:* "the job post lists it" isn't a reason.

18. **No stitched timeline.** The demo replays one run against a work-order history. *Why:* joins create fake anomalies and reveal onsets.

19. **One scoring engine.** Evaluation replays through the same code as the demo, with no look-ahead and one plant clock. *Why:* two code paths quietly disagree.

20. **Measured, trustworthy LLM output.** Pinned model, repeats and bootstrap intervals, end-to-end latency and full cost, and a faithfulness check on everything the output says. *Why:* otherwise the LLM numbers can't be reproduced or trusted.

21. **Deployment follows the detector choice.** Ship matrices if PCA wins. Versioned bundles with a startup self-test, no pickles, ONNX only if the autoencoder ships. *Why:* don't build machinery for a model you won't ship.

22. **Event-level metrics.** Detection, chance rate, delay with misses counted, false alerts per 24 hours, bootstrap by run, per-fault tables. *Why:* per-sample rates hide failures.

23. **One library schema.** Four event types, ISO 14224 terms used correctly, structured signatures and actions, governance fields, links by ID. *Why:* the first schema mixed different kinds of knowledge.

24. **Only tested entries.** 12 process entries now; instrument and planned-activity entries come with the sensor work; distractors (Could) are frozen before test. *Why:* untested entries are unverified advice.

25. **Sources with roles and licences.** A source register, entries in our own words, and a provenance tag on every passage. *Why:* the original sources didn't fit their jobs.

26. **Tested guardrails.** Structural protections separated from behavioural ones; a safety test set with zero-tolerance categories; injection tests on every text channel. *Why:* asserted guardrails aren't guardrails.

27. **Feedback through review (Could).** Structured capture, closure verdicts as ground truth, drafts approved together with their test cases. *Why:* tribal knowledge must be tested like any other entry.

28. **MLOps as four guarantees.** Reproducible, versioned, tested, monitored. *Why:* a list of tools isn't a guarantee.

29. **A README that doesn't oversell.** Layered, headline numbers with their context, limitations right after results, tiered reproduction, an honest line on AI assistance. *Why:* overclaiming costs more than it gains.

30. **Study tied to the build.** Each topic is learned in the week it's built (see `docs/PLAN.md`).

31. **Personal interview prep.** Not tracked in this repo.

32. **Scope fits the hours.** 3 hours a day, planned at 15 hours a week; Must, Should, Could and Won't; a cut line; feature freeze on 15 November. *Why:* the fixed plan was bigger than the time available.

## Tools and workflow
- Build in PyCharm with Claude Code. Design and reviews happen in the Claude.ai App 3 Project, and the repo is the bridge between them (`CLAUDE.md`, `docs/`, `eval/`).
- LangGraph runs the diagnosis flow from week 6, after a spike in week 5. Fallback: plain Python.
- LangChain is used only for the model wrapper, tool definitions and prompt templates.
- Raj writes the core logic; Claude Code writes scaffolding and tests, and explains.

## Data and protocol decisions, 24 September 2026

33. **Raj seals the data himself.** Raw downloads (the four RData files) go in `~/PycharmProjects/plant-health-sealed/raw`, never in the repo. Raj runs the one-time conversion in a normal terminal. Claude Code may write the script but never runs it. Open data (normal training runs, and training runs of faults 1–15) goes to `data/`. Everything else (all testing files, and faults 16–20 from any file) goes to the sealed folder. The script prints only counts and checksums. *Why:* the raw training file mixes quarantined faults with open ones, so whoever converts it sees sealed data.

34. **Raw names and labels by side.** Raw names are fine in `dataset/` and `ingest/` (builder side) and never appear in `app/`, `library/`, prompts or tool outputs. Test labels and anything about faults 16–20 live only in the sealed folder. Train/dev labels may be used in `dataset/`, `eval/` and notebooks, never in `app/` or `library/`. *Why:* the loader has to read raw columns, and the old wording contradicted that.

35. **Week 0 loads the dataset's own files.** "Loads by split" means the dataset's four files, converted. Run-level pools come in week 1. *Why:* the pools are week 1 work.

36. **A normal dev pool.** Fit 250, early stop 50, calibration 150, normal dev 50. *Why:* dev false alerts and chance rates need normal runs that didn't set the limits.

37. **No run IDs in the historian.** The demo replays one run at a time and the engine resets at each new stream. Run boundaries are handled on the dataset side. `history_id` is the work-order history key. Warm-up is the longest lag or window in samples, pre-registered, and under 10 samples. *Why:* training runs keep most of their 1 h pre-onset period.

38. **Onset offset per split.** 1 h into training runs, 8 h into testing runs. Chance rates use fake onsets at the offset of the runs they're compared with. *Why:* the offset differs between splits.

39. **Published-number check uses the published variable set.** It uses whichever variable set the compared table used, and the table and set are recorded in the protocol. The production detector stays on the 33 fast tags. *Why:* a check is only meaningful like-for-like.

40. **One alert stream.** The false-alert budget applies to the plant-level statistic. Groups are attributed, not alerted separately. Each group's Watch boundary is calibrated to the 2% cap. *Why:* alerts come from one statistic, so there is no budget to split.

41. **LLM keep rule and decline thresholds.** Keep the LLM only if it is at least 5 points better than the matcher on one of top-1, family accuracy or unknowns declined, on average and in every repeat. It must also be no more than 2 points worse on any of them, on average across repeats. Decline thresholds use dev runs, not authoring runs. *Why:* a win on one metric shouldn't hide a loss on another.

42. **Scoring faults cut from the library.** If the cut line removes 7, 8, 10 and 12, then 7, 8 and 12 are scored like leave-one-out and 10 needs a strict decline. They are reported separately from 16–20. *Why:* 7, 8 and 12 still have same-family entries; 10 doesn't.

43. **Minimal week 0 skeleton.** Folder layout, pinned requirements and pytest config. App 2's deploy setup is reused in week 2. Approved dependencies: pyreadr, pandas, pyarrow, numpy, pytest. *Why:* deployment isn't needed until the thin slice.

## Week 0 build decisions, 26 September 2026

44. **Tag names and descriptions.**
    - **Descriptions use roles, not component letters:**

      | Letter | Role |
      |---|---|
      | A | reactant 1 |
      | C | reactant 2 |
      | D | reactant 3 |
      | E | reactant 4 |
      | B | inert |
      | F | byproduct |
      | G | product 1 |
      | H | product 2 |

      So "A and C feed" becomes "mixed feed (reactants 1 and 2)".
    - **Units** are written in plain form, not the paper's abbreviations.
    - **Letters** appear only in `ingest/tag_map.yaml`.
    - **The remaining fingerprint** (plant layout, 52 tags) is accepted. The memorization probe measures it, and the README states it under Limitations.
    - **Tag numbers** run in sequence within each area, and every valve is `-FV-`. So no tag name implies a control loop before the week-3 loop map. Feed valves FD-FV-105..108 follow the same order as the feed flows.
    - **Tag names are permanent keys.**

    *Why:* the original letters and units identify the benchmark at a glance, and loop-style numbering would assert a control strategy we haven't mapped yet.

45. **PyYAML is an approved dependency.** *Why:* the converter reads its MD5s from `dataset/manifest.yaml` (one source of truth), and the tag tests parse the YAML files.

46. **Sealed checksums stay sealed.**
    - Each conversion writes `conversion_report_<name>.json` on each side it wrote to.
    - The repo manifest records open-file checksums, and only the SHA-256 of each sealed report.

    *Why:* the repo can show the sealed files haven't changed without describing the test split or faults 16–20.

47. **A streamed RData reader.**
    - `dataset/rdata_stream.py` reads the frame one column at a time, straight into float32, keeping float64 statistics for the checks. Peak memory is about 2.3 GB for the largest file, against 8–9 GB for pyreadr on an 8 GB Mac.
    - It is cross-checked against pyreadr once, on `fault_free_training`.
    - Data is stored as float32; models compute in float64.

    *Why:* pyreadr can't read in chunks, and float32's rounding (about 7 significant digits) is far finer than the simulated measurement noise.

48. **Group rule.**
    - A tag belongs to the unit its instrument sits on.
    - In-vessel sensors go with that vessel, fresh-feed lines with feed, and utility lines with the unit they serve.
    - Any other line goes with the vessel it leaves, or the vessel it enters if it leaves none.
    - So: reactor feed rate → reactor; purge flow, purge valve and purge analyzer → separator; separator temperature → separator.

    *Why:* groups drive the right-place metric, so the rule is fixed before any results.

## Week 1 decisions, 27 September 2026

49. **Pools by run number (Raj's decision).**
    - **Finding (open data):** in the training files, run number k is one random stream shared across files. Raj checked faults 1, 2, 3 and 13: in all 500 runs, samples 1–20 of faulty run k are exact copies of fault-free run k. The open-data test in `tests/test_splits.py` checks all open faults, 1–15. Faults 16–20 are sealed and can't be checked. The fault starts between samples 20 and 21 (between 160 and 161 in testing). The dataset's notes say training and testing seeds don't overlap.
    - **Rule 1:** pools are assigned by run number once, with a fixed seed. The same assignment applies to the fault-free file and every fault in the training file. Each run number belongs to exactly one pool: fit (250), early stop (50), calibration (150) or dev (50). The assignment is committed in `dataset/splits.yaml`.
    - **Rule 2:** faulty dev runs use the dev numbers. Authoring runs (5 per fault, the same 5 numbers for every fault) and forest training take faulty runs only from numbers outside the dev pool.
    - **Rule 3:** bootstrap intervals resample run numbers, taking every file's run with that number together. This applies on test too, where sharing can't be checked.
    - **Rule 4:** false-alert and chance rates come from normal runs only. The pre-fault part of a faulty run is a copy of the normal run with the same number and isn't counted again. This applies on test too.

    *Why:* runs that share a number are correlated. Pooling them separately per file would put the same stream in calibration and dev, and treating them as independent overstates precision.

50. **Analyzer dead time equals one update interval (confirmed from the simulator code).**
    - **Rule:** at each analyzer update, the published value is the composition captured at the previous update, plus measurement noise. Then the current composition is stored for the next update. So the value published at time t is the sample taken at t − interval.
      - Reactor feed and purge analyzers (14 tags): update every 0.1 h, dead time 0.1 h (6/6 minutes).
      - Product analyzer (5 tags): update every 0.25 h, dead time 0.25 h (15/15 minutes).
      - The nominal values already in `library/tags.yaml` are confirmed. Only its header comment changed.
    - **Sources:** both retrieved 27 September 2026 from N. L. Ricker's Tennessee Eastman archive, https://depts.washington.edu/control/LARRY/TE/download.html.
      - **Original code:** `tecode.zip` (sha256 `2536e8a8…4b16b0d`), `teprob.f`, subroutine `TEFUNC`.
        - Header comments, lines 132–164: "Sampling Frequency = 0.1 hr / Dead Time = 0.1 hr", and 0.25 / 0.25 for the product analysis.
        - Code, lines 730–756: on the first call (time 0), `XDEL` and `XMEAS` are both set to the current composition, with `TGAS=0.1` and `TPROD=0.25`. At each update, `XMEAS(I)=XDEL(I)` plus noise from `TESUB6`, then `XDEL(I)=XCMP(I)`, then `TGAS=TGAS+0.1` (0.25 for `TPROD`).
      - **Revised model:** `temexd_mod.zip` (sha256 `e43227aa…a8db724`), `temexd_mod.c` version 1.3.3 (Bathelt, Ricker and Jelali, 2015).
        - Lines 3215–3269 contain the same logic.
        - Its change log (version 1.1.0) adds a random-seed parameter.
    - **Which version made the data:** the Dataverse description doesn't name the simulator, and the dataset paper is paywalled. A secondary source says the data came from the revised model. The seed parameter in version 1.1.0 fits a dataset of 500 seeded runs per fault. Either way, the analyzer logic is identical in both versions, so the conclusion doesn't depend on which one was used.
    - **Also identical in the plant model of the code decision 61 found generated the data (checked 28 September 2026):** the Russell–Chiang–Braatz `teprob.f` (same mirror as decision 61, sha256 `409975e070780a3b…28a56a1f238d45e3`) has the header comments at lines 134–166 and the update code at lines 735–761, each word for word the same as `tecode.zip`'s lines 132–164 and 730–756. `TGAS` and `TPROD` are set nowhere else in either file.
    - **Consequence for decision 11:** the historian timestamps a value at the update time. The evidence layer treats it as describing the process one interval earlier, and holds it until the next update.

    *Why:* diagnosis evidence and the analyzer delay floor per fault in the protocol both depend on how late an analyzer value is.

51. **Scoring refuses NaN or inf (Raj's decision).** `scores()` in the PCA detector raises `ValueError` on any NaN or inf value, instead of returning NaN T² and SPE. Revisit when the data-quality layer is built: it will mark gaps as Unknown (decision 12) before scoring, so they never reach the detector.

    *Why:* NaN compares as "below the limit", so a gap would otherwise silently read as normal.

## Week 2 decisions, 27 September 2026

52. **Warm-up is 9 samples (Raj's decision).**
    - **Rule:** each run's first 9 samples (27 minutes) aren't scored, the most decision 37 allows. Scoring starts at sample 10.
    - **Memory bound:** any detector's memory must fit inside the warm-up. With L lags (past samples appended; the current sample isn't a lag) and a persistence window of n samples, L + n − 1 ≤ 9.
      - Static PCA (L = 0) allows n ≤ 10.
      - DPCA with 2 lags allows n ≤ 8.
    - **Consequence:** the DPCA lag rule (week 3) is capped by the persistence window, and the other way round.
    - Training runs keep 11 scored pre-onset samples (10–20).

    *Why:* the first scored decision must use only samples from the same run, with no padding or state from before the run started. A longer warm-up isn't allowed by decision 37.

53. **One plant ratio from T² and SPE (Raj's decision).**
    - **Rule:** r = max(T² / T²lim, SPE / SPElim). Both limits are the same per-sample percentile q of the calibration pool's scored samples (after warm-up, pooled over runs, numpy's default linear percentile), each taken for its own statistic.
    - **Alert condition:** r > 1.
    - **Display:** the ratio shown next to the status band is this r (decision 12).

    *Why:* the protocol has one plant-level alert stream (decision 40). Giving both statistics one percentile makes one number drive both the alert and the band.

54. **Persistence, grouping and how they're calibrated (Raj's decision).**
    - **Persistence (on-delay):** the condition holds at sample t when r > 1 at t and at each of the n − 1 samples before it, n in 1..10 − L (decision 52).
      - The window may use warm-up samples; that is what the warm-up is for.
      - It never reaches before sample 1.
      - Nothing before sample 10 is scored, so the track is off there.
    - **Episode grouping (off-delay):** the alert is on at t when the persistence condition held at any scored sample from t − G to t, G in 0..20.
      - A re-alert within G samples of clearing continues the same episode.
      - The alert visibly holds for G samples after the condition clears.
      - Grouping state starts at the first scored sample.
    - **Limit search:**
      - The grid is q = 95.00, 95.01 … 99.99 (500 points).
      - For each (n, G), q is the lowest grid value such that it and every higher grid value give at most 1 notification per 24 h on the calibration pool (normal runs, warm-up excluded).
      - If no grid value qualifies, that (n, G) isn't eligible.
      - Notifications don't always fall as q rises, because a higher limit can split one alert into two. So the search checks the grid and doesn't bisect.
    - **Choosing (n, G):**
      - The setting with the highest mean detection rate wins. Detection is per PROTOCOL: training onset 20, a 4 h window, and warm-up 9.
      - The mean is over the open faults except 3, 9 and 15 (12 faults), matching the protocol's summary.
      - The runs are a fixed, seeded subsample of 100 run numbers from the forest-ceiling pool, the same numbers for every fault. The seed and the list are committed, with the list's SHA-256 in `dataset/manifest.yaml`.
      - Ties within 1e-12 go to the smaller n, then the smaller G.
      - Dev is not used, so it stays an honest preview.
    - **Same search for every detector:** every compared detector that gives a ratio track, including the grouped conventional-alarm baseline, uses this budget, grid, (n, G) range and tie rule (decision 6).

    *Why:* the limit, persistence and grouping trade off against each other, so they're calibrated together to one budget. The choice among settings that meet the budget needs fault runs, and dev must stay unused.

55. **The q grid's floor stays at 95.00 (Raj's decision).**
    - **Rule:** the grid's lower end is 95.00, on purpose. A setting that meets the budget at the floor stays eligible.
    - **Record:** the calibration driver flags every such setting in the run record, with the share of the budget it uses (its false alerts per 24 h on the calibration pool, divided by the budget).
    - **Consequence:** for a setting at the floor, the limit is set by the grid, not the budget, and it uses less of the budget. The flag and the share make that visible.

    *Why:* below the 95th percentile, r > 1 would be common in normal operation, and the ratio shown next to the status band (decision 12) would lose its meaning.

56. **Published-number check: Yin et al. 2012 (Raj's decision).**
    - **Table:** Yin, S., Ding, S. X., Haghani, A., Hao, H., Zhang, P. (2012). "A comparison study of basic data-driven fault diagnosis and process monitoring methods on the benchmark Tennessee Eastman process." *Journal of Process Control* 22(9), 1567–1581. doi:10.1016/j.jprocont.2012.06.009. It's the per-fault detection-rate table for PCA T² and SPE, cited by later papers as Table 4.
    - **Variable set:** 33 variables (22 continuous measurements and 11 manipulated variables). These are the same as our 33 fast tags, which map exactly to the first 22 measurements and the 11 manipulated variables (checked against `ingest/tag_map.yaml`).
    - **Components:** to be confirmed from the full text before the check runs. If it can't be confirmed, the check uses our parallel-analysis k = 12 (`eval/runs/20260927T093509Z_fit_pca.json`) and reports that as a deviation.
    - **Method:** the check reproduces the paper's per-sample detection rate at its 99% limit on our dev runs. It checks the method, not identical data.

    *Why:* the table uses exactly our production variable set, so the check is like-for-like on variables (decision 39) and needs no analyzer tags.

## Week 3 decisions, 28 September 2026

57. **Detection is scored from the documented onset; twin divergence is a diagnostic only (Raj's decision).**
    - **Rule:** detection stays scored from the documented onset (after sample 20 in training runs, after 160 in testing runs), as PROTOCOL says. Nothing is credited or dropped by comparing with the fault-free twin.
    - **Twin:** the normal run with the same run number (decision 49). On dev, that's the normal dev run with the same number.
    - **Diagnostic column:** per fault, the share of detections whose notification came before the run first differs from its twin.
      - **First divergence:** the first sample where any of the detector's own input tags differs from the twin, by exact equality on the stored float32 values. For PCA and DPCA that's the 33 fast tags; for the alarm baseline, its alarmed tags.
      - **Before:** the notification sample is less than the divergence sample.
      - Reported as a count out of the detected runs. It changes nothing in detection, delay or the summary.
    - **Where:** computed on dev. On test it's reported only if the test twins turn out to share streams. That's checked once, at the frozen test run, and logged. Otherwise the column reads "not reported".

    *Why:* the fault's effect can reach the tags some samples after the documented onset. Up to the divergence sample, the detector's inputs equal the twin's, so a causal detector's track is identical too: a detection there is a false alert that happened to land after onset. Rescoring from divergence would move the pre-registered definition, so the share is shown instead of being used.

58. **The conventional-alarm baseline (Raj's decision).**
    - **Per-tag limits:** each alarmed tag has a high and a low limit at the same per-sample percentile of the calibration pool, (100 − q)/2 in each tail. So every alarmed tag gets the same false rate (PROTOCOL, Alarm comparison), and q is the one number the search moves.
    - **Deadbands** (hysteresis on clearing), as a multiple of the tag's calibration-pool spread σ:
      - temperature and pressure: 0.25σ
      - flow and level: 0.5σ
      - analyzers: 0.5σ
    - **Valve-at-limit alarms:** on at ≤ 2% or ≥ 98% open, held for n samples. These are fixed positions, not calibrated.
    - **Tag lists:** realistic (measurements, analyzers and valve-at-limit alarms) and every tag. Both are reported. Analyzers get a one-update on-delay.
    - **On-delay per tag, before the OR:** each alarm point needs n consecutive samples on. The plant stream is the OR over alarm points.
    - **Rows:** the ungrouped row uses G = 0 and searches only n and q. The grouped row searches (n, G) like decision 54.
    - **Calibration:** the same budget, q grid, stable-lowest-q rule, (n, G) ranges, selection runs and tie rule as decision 54. Raj adds an optional track-builder argument to `lowest_stable_q` (default: today's `alert_track`), so the per-tag pipeline reuses the same search.
    - **Lead time vs grouped alarms:**
      - the median over runs where both detected, with a run-number bootstrap interval over those runs
      - the counts of runs where both, only App 3, only the alarms, or neither detected
      - delay pairs with ∞ are never subtracted
    - The baseline lives in `eval/baselines/`. It's a comparator, not runtime code.
    - **Details confirmed by Raj, 28 September 2026:**
      - **Edges:** an alarm turns on at a strict edge (x > hi, x < lo) and clears at an inclusive one (x ≤ hi − band, x ≥ lo + band). Every alarm starts off at sample 1.
      - **σ:** the pooled ddof-0 standard deviation of the calibration pool's scored samples, computed once, not per q.
      - **Analyzer on-delay:** the first reading past the limit (1 sample of the held series), not searched with n.
      - **Compressor power:** 0.5σ, like flow.
      - **Tag lists:**
        - realistic: high and low alarms on the 22 measurements and 19 analyzers, plus valve-at-limit alarms on the 11 valves
        - every tag: high and low alarms on all 52 tags, with a 0.5σ deadband for valves, and no valve-at-limit alarms
      - **Valve-at-limit alarms have no deadband:** they clear as soon as the valve leaves the ≤ 2% or ≥ 98% zone.

    *Why:* a strawman baseline makes any lead time meaningless (decision 6). Deadbands and per-tag on-delays are what real alarm systems use (ISA-18.2) to cut chattering, and holding every tag to one false rate and the plant stream to the same budget makes the comparison fair.

59. **A finer top to the q grid, for every detector (Raj's decision).**
    - **Rule:** after 95.00, 95.01 … 99.99 (0.01 steps), the grid adds 99.991, 99.992 … 99.999 (0.001 steps), 509 points in all. Everything else in decisions 54 and 55 stands: the stable-lowest-q rule, the floor at 95.00, (n, G) ranges, selection and ties.
    - **Evidence, kept and superseded:** `eval/runs/20260928T103138Z_calibrate_alarms_realistic.json` and `eval/runs/20260928T103200Z_calibrate_alarms_every.json`. Both lists chose q = 99.98 (grouped) and 99.99 (ungrouped), and all 21 n = 1 settings were ineligible in both. Both calibrations are re-run on the new grid.
    - **Static PCA isn't re-calibrated:** `eval/check_grid_refinement.py` checks on the calibration pool that every static-PCA (n, G) setting meets the budget at all nine new points. If so, the top-down scan passes through them to the same stable q as before, and the chosen setting (n = 3, G = 15, q = 95.57) is unchanged.

    *Why:* at the top of the grid, one 0.01 step halves or doubles each alarm point's per-sample false rate (0.02% → 0.01%). So the coarse grid could force the alarm baseline stricter than the budget needs, which would flatter App 3's lead time.

60. **Alarm-comparison counts and lead time (Raj's decision).**
    - **Notification:** for the alarm rows, each alarm point (a tag's high, a tag's low, a valve-at-limit) turning on after its own on-delay and the row's off-delay G, applied per point. For App 3, its one plant stream turning on.
    - **Per 10 minutes and flood:** the 2-h notification window (samples onset + 1 … onset + 40) is split into twelve 10-minute periods by sample time after onset. Period j holds times in (10j, 10j + 10] minutes, so it gets 3 or 4 samples. Per 10 minutes is the mean count per period. Flood is a period with more than 10 notifications, reported as the share of periods.
    - **Chattering:** an alarm point that turns on 3 or more times within any 10 consecutive samples (30 min) inside the window. Reported as chattering points per run, and the share of the window's notifications they caused.
    - **Lead time** is against the realistic list's grouped row only. The every-tag list is reported with its own detection, delay and counts.

    *Why:* 10 minutes isn't a whole number of 3-minute samples, so periods follow time. A chattering alarm needs at least 5 samples to turn on 3 times, and 30 minutes also catches slower flapping. High and low alarms annunciate separately on a real console.

61. **The loop map comes from the closed-loop code the data was generated with (sourced by Claude, for Raj's review).**
    - **Source:** the closed-loop plant-wide control scheme in the modified simulator code by Russell, Chiang and Braatz: `temain_mod.f`, "Copyright 1998-2002 … University of Illinois".
      - It's cited by the code itself as Russell, Chiang and Braatz, *Data-driven Techniques for Fault Detection and Diagnosis in Chemical Processes* (Springer, 2000).
      - Retrieved 28 September 2026 from a public mirror of the group's code, https://github.com/camaramm/tennessee-eastman-profBraatz (`temain_mod.f`, sha256 `31b83c17…350bf635c8b6`). The original host in the file header no longer resolves.
      - Line numbers:
        - setpoints and gains, lines 239–314
        - execution schedule, lines 363–394: inner loops every 3 s, analyzer loops every 360 s, the product-composition loop every 900 s
        - the controllers `CONTRL1`–`CONTRL20`, lines 477–1294
        - the purge override inside `CONTRL6`, lines 687–759
      - `CONTRL12` doesn't exist. `CONTRL22` is defined (line 1295) but never called, so it's left out. The agitator isn't in the data.
    - **Why this code and not another:** the Dataverse description names neither the simulator nor the control strategy, and no primary statement was found. Four checks on the open data point to this code:
      1. **Every valve moves.** All 11 valves vary in the fit pool (σ 0.47 to 3.04 % open). Ricker's Mode-1 decentralized model can't produce that: in `temexd_mod.zip` (sha256 `e43227aaded739cf…669b906c4b16b0d`, the archive decision 50 cites; re-downloaded 28 September 2026), `MultiLoop_mode1.mdl` feeds the compressor recycle valve and the stripper steam valve as fixed "Recycle Valve Position" and "Steam Valve Position" inputs. In this code, every valve is a controller output.
      2. **The PI loops sit at this code's setpoints.** Fit-pool means of the nine fixed-setpoint PI loops, against the code's setpoints (fit pool, after warm-up, 122,750 samples; all within 0.002 units, which is at most 0.003 sd):
         - recycle flow 26.9013 against 26.902
         - reactor level 74.9993 against 75.0
         - reactor temperature 120.4000 against 120.40
         - stripper underflow 22.9472 against 22.949
         - reactor-feed reactant-1 32.1879 against 32.188
         - reactor-feed reactant-3 6.8821 against 6.8820
         - reactor-feed reactant-4 18.7756 against 18.776
         - purge inert 13.8229 against 13.823
         - product reactant-4 0.8358 against 0.83570
      3. **The valve means are this code's initial positions,** for example 63.05, 53.98, 24.65 and 61.30 % open.
      4. **The layout matches this group's published data:** 3-minute samples, onset at 1 h in training runs, and 960-sample test runs with onset at 8 h.
      - Only the Mode-1 decentralized model was checked in detail. The self-optimizing structure in the same archive wasn't, because check 2 is specific to this code.
      - `tests/test_loops.py` repeats check 2 on the open data, opt-in: `pytest -q -m opendata`.
    - **The map:** `library/loops.yaml`, agent-visible, with plant tags only. It has 19 loops, 11 on valves and 8 cascade masters.

      | Loop | Code | Loop | Code |
      |---|---|---|---|
      | FD-FIC-102 | CONTRL1 | RX-AIC-211 | CONTRL13 |
      | FD-FIC-103 | CONTRL2 | RX-AIC-214 | CONTRL14 |
      | FD-FIC-101 | CONTRL3 | RX-AIC-215 | CONTRL15 |
      | FD-FIC-104 | CONTRL4 | ST-TIC-604 | CONTRL16 |
      | CP-FIC-501 | CONTRL5 | RX-LIC-203 | CONTRL17 |
      | SP-FIC-406 | CONTRL6 | RX-TIC-204 | CONTRL18 |
      | SP-LIC-402 | CONTRL7 | SP-AIC-412 | CONTRL19 |
      | ST-LIC-601 | CONTRL8 | ST-AIC-612 | CONTRL20 |
      | ST-FIC-605 | CONTRL9 | RX-TIC-205 | CONTRL10 |
      | ST-FIC-603 | CONTRL11 | | |

      - **Modes are read from each controller's update line.** Integral action means a `TAUI` term. Proportional-only loops are CONTRL1–4 and 6–9: the four feed flows, the purge flow, both levels and the steam flow. The rest are PI.
      - **Loop ids** follow the controlled tag (FD-FI-101 → FD-FIC-101). Tag names are unchanged (decision 44); only the loop map names loops.
    - **Things the map makes visible:**
      - **Proportional-only loops can settle off setpoint under a sustained disturbance.** So for those loops, "held at setpoint" means "inside its normal band", not "at the setpoint".
      - **Production rate** (stripper underflow) is held by the condenser cooling water valve. So that valve carries production corrections, not only condenser duty.
      - **The purge valve has a pressure override:** fully open at separator pressure ≥ 2950 kPa, fully shut at ≤ 2300, released at 2633.7. It never acts in the fit pool, where pressure stays between 2599 and 2670.
    - **Leak scan:** `tests/test_leak_scan.py` now also rejects these sources' author names in agent-visible text.

    *Why:* the masked-fault rules and valve headroom (session 6), and later the diagnosis evidence, need to know which valve holds which measurement. A map guessed from tag names, or taken from a different control strategy, would point the agent at the wrong valve.

62. **The masked-fault rule and valve headroom (Raj's decisions, with Claude's code).**
    - **Where it's decided:** on the 100 selection runs (`dataset/selection.yaml`, forest-ceiling numbers), never on dev, so dev stays an independent check. The list goes into PROTOCOL → Loops before test.
    - **Normal band:** each tag's central 99% on the calibration pool, the 0.5th to 99.5th percentile of the pooled scored samples after warm-up. For a proportional-only loop (decision 61), "held" means inside this band, not at the setpoint.
    - **Rule, per loop and run,** judged on the settled half of the 4 h window, samples onset + 41 … onset + 80 (2 to 4 h after onset; Raj's change on review, before anything ran):
      - **held:** the controlled measurement is never outside its band for 3 consecutive samples in that half
      - **absorbed:** the loop's end valve is outside its band for 3 consecutive samples somewhere in it. For a cascade master, the end valve is the valve at the bottom of its cascade (reactor temperature → RX-FV-206).
      - A run of consecutive samples outside the band counts only from onset + 41 on. The band edges count as inside.
    - **Why 3 consecutive samples (Raj's choice):** judged sample by sample, the rule calls 91% of normal calibration runs masked by at least one loop, because with a 99% band each tag is outside about 1% of the time. With 3 consecutive samples (App 3's calibrated n), 3% of them are. Those figures were measured over the whole 4 h; the run records the figure for the settled half.
    - **Why the settled half:** compensation is what the loop leaves behind once it has acted. A loop's measurement can leave its band briefly at onset, before the controller has moved the valve, and that transient shouldn't disqualify a fault the loop then holds. Fault 4's realistic alarms fired at 3 min and cleared within a few samples, so its reactor temperature may leave the 99% band briefly at onset. The valve has to be out of its band in the same settled half, so a valve that only moves during the transient doesn't count as absorbing.
    - **Fault level:** a fault is masked by loop L when at least 50% of its selection runs meet the rule for L, and it's masked when any loop masks it. The table names the loop(s).
    - **Valve headroom:** min(position, 100 − position) in % open, the distance to the physical limits, as of the latest sample. It's evidence for diagnosis, with no alarm threshold (`app/detector/loops.py`).
    - **It's a label, not a detector,** so it may look ahead within the window. It never reaches `app/` or `library/`.

    *Why:* masked faults are the ones a measurement-based view misses. Fault 4's realistic alarms cleared (share still flagged 0.01) while the every-tag list, which alarms on the valves, held on (1.00). Reporting them separately (PROTOCOL) needs a rule fixed before test that doesn't use dev.
