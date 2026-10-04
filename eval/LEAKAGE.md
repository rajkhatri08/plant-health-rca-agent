<!-- Destination: eval/LEAKAGE.md -->
# Leakage rules

Three walls. CI enforces walls 1 and 2; wall 3 is audited from the access log and git history. The README and notebooks may name the benchmark freely. These rules cover what the agent sees and what the builder touches.

## 1. The agent can't read the answer
- Test labels and anything about faults 16–20 live only in the sealed folder. Train/dev labels, onsets and run IDs may be used in `dataset/`, `eval/` and notebooks, never in `app/` or `library/`. `app/` never imports `eval/` or `ingest/`.
- The historian stores `ts, tag, value, quality`. The dataset's fault, run and sample columns are dropped at ingestion. The onset offset is fixed within each split (1 h into training runs, 8 h into testing runs), so a visible run boundary would give away the onset.
- The historian has no run IDs: the demo replays one run at a time, and the engine resets at each new stream. Run boundaries are handled on the dataset side. `history_id` is the episode's opaque history key: its historian stream, and its work orders when built (Raj, 4 October 2026). It never carries a run or fault number.
- Library entries reach the LLM only through the retrieval tool, which strips source and provenance. Entry IDs describe mechanisms, never fault numbers.
- Few-shot examples come from training runs and carry no labels.
- Work orders (when built) are as-of the diagnosis time. An order closed after that time shows only its opening text. Each case gets its own history, and truth rows stay in `eval/`.

## 2. The model can't lean on benchmark memory
- The agent sees plant-style tags (for example RX-TI-204). XMEAS/XMV names appear only on the builder side (`dataset/`, `ingest/`; the mapping is `ingest/tag_map.yaml`), never in `app/`, `library/`, prompts or tool outputs.
- Prompts and tool outputs never name the benchmark or its source paper.
- Memorization probes run once on the pinned model, with the results saved in `eval/probes/`. Anonymisation is partial; say so under Limitations.

## 3. The builder can't peek
- Signatures are written from at most 5 authoring runs per known fault, using run numbers outside the dev pool (decision 49), listed in `dataset/splits.yaml`. `eval/provenance` lists which runs.
- Raw downloads (the dataset's four RData files) live in `~/PycharmProjects/plant-health-sealed/raw`, never in the repo. Raj runs the one-time conversion in a normal terminal. Claude Code may write the script but never runs it. The script writes open data (normal training runs, and training runs of faults 1–15) to `data/`. It writes everything else (all testing files, and faults 16–20 from any file) to the sealed folder. It prints only counts and checksums, never values.
- The test split is sealed, and faults 16–20 are quarantined in every split. Both are stored outside the project folder. They load only through `dataset/` with `EVAL_MODE=1`, which Raj sets for a pre-registered run. Every such load is logged with its commit in `eval/test_access.log`, which is committed.
- During development, the historian, replay and UI use train and dev data only.
- Claude Code: add deny rules for the sealed folder in `.claude/settings.json`, as a second layer only. The main protection is that the sealed data isn't in the project folder at all.

## CI checks
- Scan prompts and `library/` for fault labels, raw tag names and the benchmark name.
- Scan every tool's output at runtime for the same, plus the sources' authors' distinctive surnames (`eval/leak_scan.py`; very short or common ones are left out to avoid false positives, and "Downs" because of "ups and downs": "Vogel" covers that paper).
- Check that `app/` imports neither `eval/` nor `ingest/`, that only `dataset/` reads raw files, and that the historian columns match the list above.
