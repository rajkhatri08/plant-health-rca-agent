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
