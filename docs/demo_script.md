# Demo video script: episode 2 (about 2 min 45 s)

**Page:** https://plant-health-rca-agent.vercel.app

**Before recording:**
- Open the page once, so the API wakes up (the first request takes about a minute).
- Pick Episode 2, press Reset, and set Speed to 4 samples per tick.
- Leave the operator note on "No note".
- Record the browser window only, at a size where the chart and the groups panel are both readable.

**What episode 2 is:** a recorded stream in which the reactor's cooling water supply turns warmer than normal. The reactor temperature controller compensates by opening the cooling valve, so the temperature itself looks almost normal. That's a masked fault: the symptom is hidden by the control loop.

---

## 1. The alert (0:00 to 0:25)
**On screen:** press Play. Let the chart run until the ratio crosses the dashed line and the status band turns red, then press Play again to pause.

**Say:** "This is a replay of plant measurements, scored sample by sample, every three minutes of plant time. Each point uses only data up to that moment. For the first minutes the band is grey while the detector warms up, then green. Here the plant-wide ratio crosses 1 and stays above it, and the band turns to Alert. One disturbance gives one alert, not a flood of them."

## 2. The Watch band and the ratio (0:25 to 0:50)
**On screen:** point at "Alert ratio (limit = 1)", then at the band strip under the chart.

**Say:** "The ratio is how far the plant-wide statistic is from its limit; above 1 is outside normal operation. An alert needs several samples in a row above 1, which keeps false alerts to about one a day. Watch, in amber, is a quieter signal: one equipment group looks unusual against its own normal behaviour, but no alert is raised."

## 3. The top groups (0:50 to 1:10)
**On screen:** scroll to "Equipment groups". Point at Reactor, marked "Symptoms show here first".

**Say:** "Where are the symptoms? The detector rebuilds the data group by group. As of the moment the alert began, the reactor group stands out past its boundary, while the others stay normal. That shows where the symptoms appear, not what caused them."

## 4. The evidence (1:10 to 1:40)
**On screen:** press Step until the first diagnosis appears (30 minutes after the alert). Scroll to the cited evidence: the reactor temperature loop "compensating", the cooling valve RX-FV-206 "high", and "masked: true".

**Say:** "Thirty minutes after the alert, the system gathers evidence as of that time. The reactor temperature loop is compensating: the temperature measurement holds near normal, because the cooling valve, RX-FV-206, has opened unusually far. The valve is absorbing the disturbance. A reading of the temperature alone would miss it; the evidence says the loop is working harder than it should."

## 5. The proposal and its explanation (1:40 to 2:10)
**On screen:** point at "Proposed: Reactor cooling water supply warmer than normal", the explanation, the suggested checks and "Faithfulness check: passed". Then step on to the revised diagnosis at 60 minutes.

**Say:** "A matcher compares this evidence with a governed library of twelve failure modes and proposes the best fit: the cooling water supply is warmer than normal. One language-model call explains the pick, and a deterministic check confirms that every cited fact and action really comes from the evidence and the entry. The explanation was computed in advance; this page never calls a model live. Thirty minutes later, the revised diagnosis agrees."

## 6. The approval pause (2:10 to 2:30)
**On screen:** point at "Awaiting supervisor approval" and the suggested checks with their preconditions. Optionally, switch the operator note to the injection example (the proposal stays the same) and then to the emergency example (the page says to follow the site emergency procedure), and switch back.

**Say:** "Nothing happens without a person. Every suggested check needs a supervisor's approval, with its safety precondition attached by code, not by the model. The system never touches plant controls. And an operator note can't talk it into anything: an injected instruction doesn't change the answer, and a note about an emergency stops the diagnosis and points to the site procedure."

## 7. The numbers and the limits (2:30 to 2:50)
**On screen:** the README's Results section, or stay on the page.

**Say:** "I tested this once, on a sealed test set, with every setting fixed in advance. The detector caught 95.6% of fault runs at about one false alert a day. The matcher named the right cause first 76% of the time. The language model made the system more cautious about unknown faults, but it cost about four points of accuracy, and the README says so, along with the other limits."

---

**Every figure in section 7** is from the test records cited in the README:
- 95.6% and 1.004 false alerts per 24 h: `eval/runs/20261009T030317Z_test_table_pca_static.json`
- 75.7% top-1: `eval/runs/20261009T035840Z_test_diag_table.json`
- the 3.8-point cost: `eval/runs/20261009T044927Z_test_agent_table.json`

Section 7 rounds them to 76% and about four points for speech.
