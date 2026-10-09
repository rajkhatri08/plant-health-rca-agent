<!-- Destination: docs/PLAN.md -->
# App 3 plan

## Budget and dates
- 3 hours a day is about 21 hours a week, planned at 15 (70%). That gives about 113 hours before the freeze.
- This time is on top of Deloitte prep and daily coding, not taken from them.
- Feature freeze: Sunday 15 November 2026.
- Deloitte interview: Wednesday 2 December 2026.
- UptimeAI interview: December 2026. Confirm the date with the referrer.

## Week by week
Learn each topic in the week you build it.

| Week | Dates | Build | Learn | Done when |
|---|---|---|---|---|
| 0 | 24–27 Sep | Minimal skeleton (folder layout, pinned requirements, pytest config; App 2's deploy setup is reused in week 2); Claude Code in PyCharm with these docs; download the dataset, convert it once, write the data manifest; anonymised tag map and tag register; start a time log; ask the referrer for the UptimeAI date | Claude Code basics | The dataset's four files are converted and the open data loads by file (run-level pools come in week 1), and Claude Code explains the rules back correctly |
| 1 | 28 Sep–4 Oct | Run-level splits, sealed test with access log, leak tests; event-level metric code with unit tests; PCA fitted on the fit pool | PCA, T², SPE; splits and pre-registration | Tests pass on hand-built cases |
| 2 | 5–11 Oct | Empirical limits, persistence and episode grouping at one budget; autocorrelation plot; published-number check; thin slice deployed | Empirical limits, autocorrelation | An alert shows in the UI, and the referrer gets the link |
| 3 | 12–18 Oct | Grouped conventional-alarm baseline and lead time; loop map and masked-fault rules; status bands and ratio; DPCA | PID, cascade, saturation, stiction; alarm management (ISA-18.2) | Per-fault detection table on dev, PCA vs DPCA |
| 4 | 19–25 Oct | Reconstruction-based contributions and signature features; library schema; first 5 entries | Contributions and smearing; ISO 14224, FMEA, RCM | Top tags look right on dev faults |
| 5 | 26 Oct–1 Nov | 7 more entries (12 in total); matcher; random-forest baseline; 3-hour LangGraph spike on a toy graph | Random forests; LangGraph basics | Matcher vs forest vs random table on dev |
| 6 | 2–8 Nov | Diagnosis flow in LangGraph: one LLM call, structured output, faithfulness check, declines, approval pause; RCA eval on dev; small safety set | LLM evaluation, prompt injection, safety systems | Unknown faults declined on dev |
| 7 | 9–15 Nov | Frozen test run; README; final `decisions.md`; demo video; work-order history if ahead | Reproducibility | Feature freeze, 15 Nov |
| — | 16 Nov–2 Dec | Deloitte. App 3 gets bug fixes only | — | — |
| — | 3 Dec to UptimeAI | Rehearse, then Should items if there's time | Remaining study topics | — |

## Scope

### Must
- **Data:** anonymised ingest, run-level splits, sealed test, access log, leak tests
- **Metrics:** event-level definitions with unit tests, published-number check
- **Detection:** PCA with empirical limits, persistence and grouping at one budget; DPCA; status bands and ratio
- **Baseline:** grouped conventional alarms, for lead time and notification counts
- **Loops:** loop map and masked-fault rules
- **Isolation:** reconstruction-based contributions
- **Library:** 12 process entries in the full schema, with basic governance
- **Diagnosis:** matcher plus one LLM call in LangGraph, with structured output, faithfulness check, declines and approval; random-forest baseline; unknown-fault test
- **Analyzers:** diagnosis evidence only; the detector uses the 33 fast tags
- **Safety:** structural guardrails plus a small test set
- **One scoring engine** for everything
- **Write-up:** README, `docs/decisions.md`, demo video

### Should, in this order
1. Work-order history with the canary conditions
2. Injected sensor faults, the data-quality layer, instrument and planned-activity entries
3. Small dense autoencoder
4. Replay UI with the parity test

### Could
- Windowed autoencoder and the four-way comparison; ONNX and quantisation
- Operator question interface
- Feedback learning-loop simulation
- Document search with the source register
- Distractor entries; full governance scenarios
- Health page

### Won't (designed and documented, not built)
Stitched timeline, simulator runs, operating-mode changes, in-loop sensor faults, remaining-life prediction, CVA and multiblock models, plant connectors (OPC UA, PI Web API), HAZOP, open-model comparison.

## Cut line
If behind, drop in this order:
1. DPCA, moved to after 2 December. (Moot since week 3: DPCA is built and wasn't selected; static PCA ships, decision 63.)
2. LangGraph, replaced by plain Python with approval as a database status.
3. Four library entries, going from 12 to 8. Faults 7, 8, 10 and 12 join the unknown-fault test.
4. Status bands, replaced by a plain alert list.
5. The safety test set, moved to after 2 December. Structural guardrails stay.
6. Deployment, replaced by a notebook demo plus the recorded video.

Never cut: the sealed test and splits, the tested metric code, the single calibrated budget, the faithfulness check, the README's limitations.

## Checkpoints
- **End of week 1:** compare the time log with 15 hours. If below, switch now to the 2-hour version (8 entries, no DPCA).
- **End of week 3:** if the detection table isn't done, take the first cut.
- **End of week 5:** the LangGraph spike decides whether week 6 uses LangGraph or plain Python.
- **Exam weeks:** count as zero weeks. Move the cut line up.

## After 2 December
1. Rehearse: teach-backs for the core topics and the likely follow-up questions.
2. With two or more weeks before the UptimeAI interview, work down the Should list.

## Schedule notes
- **Watch band moves to after week 4 (Raj, 28 September 2026).** Each group's Watch statistic is the group's joint RBC (decision 9), so the Watch band is built after RBC in week 4. Week 3's status-band work is the plant ratio and bands already shipped. The page keeps "Watch isn't built yet" until then.
- **Week 3 closed (29 September 2026).** Its "Done when" is met: the per-fault dev table exists for static PCA, DPCA and both alarm lists, with the Masked column (records in `docs/log.md`, week 3 summary). Static PCA stays the production detector (decision 63, `eval/runs/20260929T020335Z_select_detector.json`), so the bundle and replay stay static. The end-of-week-3 checkpoint passes, so no cut is taken. The build runs about two weeks ahead of the dates in the table, so week 4 starts now. Still open from earlier weeks: the published-number check (Must, Metrics), which needs the Yin component count, agreement band and theoretical 99% limits decided first.
- **Week 4 closed (2 October 2026).** Its "Done when" is met: Raj reviewed the top tags on dev (right place 0.69 at the notification, `eval/runs/20260929T073949Z_dev_table_pca_static.json`). The Watch band moved here from week 3 and is live (`pca_v2`). The library schema, store, gated approval and five r1 drafts are in place. The drafts stay unapproved until the matcher brings real entry tests in week 5 (decision 24), so approving them joins week 5's work. Still open from week 2: the published-number check (Must, Metrics). The build runs about three weeks ahead of the dates in the table, so week 5 starts now.
- **Week 5 closed (3 October 2026).** Its "Done when" is met: the matcher vs forest vs random table on dev (`eval/runs/20261003T083029Z_diag_table.json`). At +30 min, top-1 is 77.4% for the matcher, 87.6% for forest-5 and 8.3% for random; the matcher declines 85.1% of false alerts against forest-5's 63.8%. All 12 library entries are approved through entry tests and the gated approval, so cut line 3 isn't taken. The end-of-week-5 checkpoint is decided: week 6 uses LangGraph (decision 74), so cut line 2 isn't taken either. Still open from week 2: the published-number check (Must, Metrics). The build runs more than three weeks ahead of the dates in the table, so week 6 starts now.
- **Week 6 closed (5 October 2026).** Its "Done when" is met: the dev agent table reports unknown faults declined against the matcher, with the keep-rule reading (`eval/runs/20261005T024647Z_agent_table.json`).
  - **The keep rule isn't kept at either time.** So the LLM ships as tie-break, explainer and veto over the matcher's order (decision 79), not as a re-ranker.
  - **Under the shipped flow** (cache-only replay, `eval/runs/20261005T074827Z_agent_table.json`): top-1 is 74.9% at +30 min and 78.0% at +60, against the matcher's 77.1% and 79.7%. Unknown faults declined are 95% and 98%, against 87% and 91%.
  - **The safety set:** all three zero-tolerance categories pass in all 5 repeats; 34 of 36 cases pass, and both failures are fail-safe. The memorization probes show the model recognises the plant.
  - **The demo** replays two episodes with precomputed answers and makes no live LLM call.
  - **Cut lines:** none taken; LangGraph, the safety set and deployment all stayed.
  - **Still open:** the published-number check (Must, Metrics, open since week 2).
  - **Pace:** the build runs about four weeks ahead of the dates in the table. Week 7 (the frozen test run, the README, the final `decisions.md`, the demo video) can start now.
- **Week 7 closed (9 October 2026; sessions S0–S6).** Its "Done when" (the feature freeze, due 15 November) is met early.
  - **The frozen test run:** once, on 9 October, on tag `protocol-v2-frozen` (commit 93ac874), with no crash and no rerun (`docs/log.md`, week 7 S4).
  - **The rest:** the README (S5); the closing summary in `docs/decisions.md`; the episode 2 video script (`docs/demo_script.md`). Raj records the video.
  - **Must items:**

    | Must | Status |
    |---|---|
    | Data | Done: anonymised ingest, run-number splits, the sealed test split with its access log, leak tests |
    | Metrics | Done: event-level metrics with unit tests. The published-number check ran (decision 56): 11 of 12 detectable faults within 10 points, so it doesn't agree under the pre-registered rule; fault 10 is the miss, mostly explained by the paper's operating point (post hoc) |
    | Detection | Done: static PCA with calibrated limits, persistence and grouping at one budget; DPCA built and reported, not selected (decision 63); status bands and the ratio |
    | Baseline | Done: grouped and ungrouped conventional alarms, both lists, with lead time and notification counts |
    | Loops | Done: the loop map and the masked-fault rule (decisions 61, 62) |
    | Isolation | Done: reconstruction-based contributions and right place (decisions 64, 65) |
    | Library | Done: 12 process entries in the full schema, approved through entry tests and the gated approval |
    | Diagnosis | Done: the matcher plus one LLM call in LangGraph, with structured output, the faithfulness check, declines, approval and the shipped flow (decision 79); the forest baselines; unknown-fault and leave-one-out tests, on dev and test |
    | Analyzers | Done: diagnosis evidence only; the detector uses the 33 fast tags |
    | Safety | Done: structural guardrails, the emergency screen and the safety set (dev; decision 78) |
    | One scoring engine | Done: evaluation and the demo share the graph and the scoring code |
    | Write-up | README done; `docs/decisions.md` closed; demo video script done, with the recording Raj's |

  - **Cut lines:** none taken in any week.
  - **Should and Could items:** unchanged, for after 15 November. Any of them is evaluated on dev only and reported as a post-test extension (week 7 scope rule).

## Parking lot
Ideas that come up mid-build go here. Nothing enters scope unless something else leaves.
-
