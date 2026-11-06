---
name: audit-cog
description: Run the VISION audit pipeline on a finished run's transcript archive — who said what to whom, who decided what, what went wrong and who caught it — through to its final ledger, one step at a time with src/audit/audit_step.py. On request only, between or after experiments. The model steps run in one go; `cost` reports what they cost.
---

# audit-cog — run the audit pipeline

## What this is

The audit is a fixed pipeline: codebook `src/audit/codebook.md`, code frozen as `pipeline_v6` + `pipeline_v6b`
(tags `audit-v6-frozen`, `audit-v6b-frozen`), released as one merged pipeline (v6 + the v6b time-order step `p10t`
+ the final ledger). audit-cog's whole job is to **run that pipeline correctly on one run and report what it wrote**.

- It does **not** build ledgers by hand, re-derive what the pipeline measures, or answer a question the pipeline
  does not answer — that is reported as *not answered*.
- It does **not** change the pipeline, its prompts, its settings or the codebook. The measurement is the frozen
  code; a changed pipeline is a different instrument.
- Stance, from the codebook: the audit analyses and reports; it never judges the physics, never argues a position.
  Report the pipeline's numbers in its own terms, with its caveats, including the unflattering ones.

**When:** on request only — after a run, between experiments, or later. Never automatic, never while an AE is
running (the archive must be final). Not part of the completion handshake.

## How: one script, one step per call

Everything goes through **`src/audit/audit_step.py`**, from the repo root. Each step takes only the run folder,
works out every path itself, refuses if the step before it was not done, and ends with `NEXT: ...`. Run the steps
as written — no shell variables, no hand-built pipeline commands, no `python -c`.

| # | command (from the repo root) | who | what |
|---|---|---|---|
| 1 | `python3 src/audit/audit_step.py check <run>` | you | the archive is there: orchestrator `.jsonl` + `agents/*.jsonl` |
| 2 | `python3 src/audit/audit_step.py build <run>` | you | the pipeline into `<run>/audit_out/pipeline_code/` from the current commit, then its offline tests |
| 3 | `python3 src/audit/audit_step.py config <run>` | you | drafts `audit_out/audit_config/audit_config_<run>.json` — **then stop: the user reviews it** |
| 4 | `python3 src/audit/audit_step.py record <run>` | you, after the user's OK | records the run in the pipeline's inventory, checks it |
| 5 | `python3 src/audit/audit_step.py fake <run>` | you | the whole pipeline with a stand-in model, in scratch: every stage on this corpus, each model step's job count |
| 6 | `python3 src/audit/audit_step.py dry <run>` | you | p00–p04 for real, stops before the first model step |
| 7 | `python3 src/audit/audit_step.py llm <run>` | you, **as a background task** (see below) | every model step, to the end: minutes for a short run, hours for a day-long one |
| 8 | `python3 src/audit/audit_step.py status <run>` | you | what ran, where it stopped, same code/config throughout |
| 9 | `python3 src/audit/audit_step.py cost <run>` | you | the tokens `llm.py` recorded, per stage, at list price |

**Running `llm`:** start it with `run_in_background: true` (it outlasts a foreground call). Wait for the completion notice — do not poll. Then `status` and `cost`.
Any `STOP:` line: report it verbatim to team-lead and stop; do not work around it.

## What to report at each step

- **check** — the archive folders and counts. No `agents/` → blocker: the archive is team-lead's job
  (`scripts/make_session_log.py`), and peer traffic lives only in the agent transcripts.
- **build** — the commit it was built from and the test result (all PASS, or stop). It refuses while the release
  build has uncommitted changes, and never rebuilds a pipeline that has started.
- **config** — the drafted window (UTC and beamline local, and where it came from), `live_agents`, `run_label`.
  The window is the live run, from the orchestrator session — not folder names. **Show it to the user and wait
  for their OK.** Edit only what they ask; never add a `"v6"` block or a `_gate` key.
- **fake** — `"views": true` and the model steps' job counts. `"views": false` or a failure means a stage breaks
  on this corpus: stop.
- **dry** — from p02's printout: distinct messages and the split by track, the time span, and every quiet stretch
  ≥ 60 min, each with an explanation (beam down, overnight, usage limit) or flagged as a possible missed source.
  An agent inside the window but not in `live_agents` stops p00 (the fake run shows it first): back to `config`
  and the user, then a fresh `build` (the inventory holds the old config's md5).
- **llm** — when it ends: `done`, or the failed stage and the end of `run_v6.log` verbatim. On a failure the user
  decides whether to re-run (`llm --retry`; `llm.py` skips the jobs already done).
- **status** — invocations, `same code / config in all: True / True`, the stop state, the last lines.
- **cost** — the per-stage table and the total, as list price (the publication audits, side
  experiments in the same folders included: run0304 $758, run009 $846, run007 $1,086).
- **The end** — paths (`pipeline_out_v6/RUN_MANIFEST.json`, `pipeline_out_v6/views/`, `audit_out/final_ledger/`),
  corpus counts, the `cost` table (the usage `llm.py` recorded in each `<output>.prov.json`),
  anything skipped (p12 without intent labels) or refused, and what the pipeline does not establish (its README:
  no identity reconsideration; obvious misses, not exhaustive recovery). Paper tables and figures are the user's
  scripts (`discussion/cross_run/src/*_v6.py`), not this job.

## Hard rules

- **Model calls only through `audit_step.py llm`.** Never `llm.py` or `run_pipeline.sh --llm` directly, never
  `--approve` or `--max-tokens` by hand: `llm` runs the pinned model and settings with no token ceiling.
- **Never** edit `src/audit/` or `audit_out/pipeline_code/`; never set `AUDIT_OUT`, `AUDIT_CONFIG`, `AUDIT_MODEL`,
  `AUDIT_EFFORT`, `AUDIT_MAX_TOKENS` or the measurement variables (`audit_step.py` refuses them).
- **Corpus = the run's `transcripts/` archive.** Never `~/.claude/projects/`.
- **Read-only w.r.t. the AE loop:** no flag file, no `*_log.csv`, no message asking a cog to stop.
- Write only under `$RUN_DIR/audit_out/`. **Never delete or overwrite** an earlier audit's output.

## Before reporting completion

1. Every path you name exists; `final_ledger/` and `views/` are non-empty.
2. `status` shows `done` and `same code / config in all: True / True`.
3. Corpus counts and quiet stretches reported from the p02 printout, not recomputed.
4. `cost` reported (per stage and total).
5. Anything not determined, listed.

Or report a blocker. **A stated blocker is a useful result; a silent idle is not.**

## Kept, not used by the pipeline

`transcript_helpers.py` and `verify_audit.py` in this folder are the earlier hand-audit helpers, kept for the
`pixi run check-audit` task. The pipeline does not use them; do not build ledgers with them.
