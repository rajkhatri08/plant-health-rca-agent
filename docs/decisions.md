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
