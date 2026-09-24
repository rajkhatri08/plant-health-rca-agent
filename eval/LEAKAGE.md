<!-- Destination: eval/LEAKAGE.md -->
# Leakage rules

Three walls. CI enforces walls 1 and 2; wall 3 is audited from the access log and git history. The README and notebooks may name the benchmark freely. These rules cover what the agent sees and what the builder touches.

## 1. The agent can't read the answer
- Fault labels, onsets and run IDs live only in `eval/` and the sealed folder. `app/` never imports `eval/` or `ingest/`.
- The historian stores `ts, tag, value, quality`. The dataset's fault, run and sample columns are dropped at ingestion. Which time range came from which run is recorded in `eval/` only: every fault starts at the same offset into its run, so a visible boundary would give away the onset.
- Library entries reach the LLM only through the retrieval tool, which strips source and provenance. Entry IDs describe mechanisms, never fault numbers.
- Few-shot examples come from training runs and carry no labels.
- Work orders (when built) are as-of the diagnosis time. An order closed after that time shows only its opening text. Each case gets its own history, and truth rows stay in `eval/`.

## 2. The model can't lean on benchmark memory
- The agent sees plant-style tags (for example RX-TI-204). XMEAS/XMV names exist only in `ingest/tag_map.yaml`.
- Prompts and tool outputs never name the benchmark or its source paper.
- Memorization probes run once on the pinned model, with the results saved in `eval/probes/`. Anonymisation is partial; say so under Limitations.

## 3. The builder can't peek
- Signatures are written from at most 5 authoring runs per known fault. `eval/provenance` lists which runs.
- The test split is sealed, and faults 16–20 are quarantined in every split. Both are stored outside the project folder. They load only through `dataset/` with `EVAL_MODE=1`, which Raj sets for a pre-registered run. Every such load is logged with its commit in `eval/test_access.log`, which is committed.
- During development, the historian, replay and UI use train and dev data only.
- Claude Code: add deny rules for the sealed folder in `.claude/settings.json`, as a second layer only. The main protection is that the sealed data isn't in the project folder at all.

## CI checks
- Scan prompts and `library/` for fault labels, raw tag names and the benchmark name.
- Scan every tool's output at runtime for the same, plus the source paper's author names (Downs, Vogel).
- Check that `app/` imports neither `eval/` nor `ingest/`, that only `dataset/` reads raw files, and that the historian columns match the list above.
