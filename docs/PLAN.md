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
1. DPCA, moved to after 2 December.
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

## Parking lot
Ideas that come up mid-build go here. Nothing enters scope unless something else leaves.
-
