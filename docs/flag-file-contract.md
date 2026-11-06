# Canonical Flag-File & Log Contract (LIVE 11BM-CMS)

Single source of truth for the autonomous-experiment handshake. **op-cog, ana-cog, and gpcam-cog
MUST all use these exact names/formats** — verified end-to-end in production. Any change must be
coordinated across all three cogs *here*. All flag files and logs live in `RUN_DIR`
(`os.environ["RUN_DIR"]`), NEVER in the raw-data dir.

Parameter columns generalize to the experiment: `x,y` below stands for the run's parameter columns
(`smx,smy`, `temperature`, composition, …).

## Analysis method is invisible to this contract

The metric columns of `ana_log.csv` are the SciAnalysis protocol metrics (`q0, I0, …`).

## Flag files

| File | Who writes | When | Content / format |
|---|---|---|---|
| `GPCAM_NEXT.txt` | gpcam | proposes the next point (seeds AND BO, uniformly) | `seq,x,y` (comma; `seq` int, then the parameter columns) |
| `TRIGGER.txt` | op | after each measurement | `seq\|x\|y\|tiff_prefix` (pipe; x/y = actual commanded values, `tiff_prefix` = bare savename stem from `sam.get_savename`, taken as op-cog `SKILL.md` "Tiff path rule" says; it always contains the `seqNNN` extra) |
| `ANA_DONE.txt` | ana | analysis of that `seq` is complete | empty file |
| `GPCAM_STOP.txt` | gpcam (or a human) | gpCAM halts, or a human stops the run | line 1 `STOP`, line 2 the reason (below) |
| `AE_COMPLETE.txt` | op | op's loop exits, by **any** path | `<STOP_KIND>,<final_seq>,<UTC ISO time>,<reason>` (below) |

**No seed-phase handshake.** gpCAM drives EVERY point through `GPCAM_NEXT.txt` (seeds `seq 1..N`,
then BO points), so op runs ONE uniform loop. op does **not** write `SEEDS_DONE.txt` or
`OP_DONE.txt` — those were a simulator-era idea and are **NOT used live**.

## Stop reasons and stop kind (every exit is labelled)

`GPCAM_STOP.txt` line 2 names why gpCAM stopped (line 1 stays `STOP`):

| reason | meaning |
|---|---|
| `converged` | the convergence criterion was met |
| `max_iters_reached` | the point budget is used up |
| `grid_exhausted` | no admissible candidate is left |
| `user_stop` | a human stopped the run on purpose (write `STOP`, then `user_stop`) |
| `wait_timeout` | gpCAM waited longer than `analysis_wait_timeout_s` for a result |
| `error` | an exception in gpCAM |

`AE_COMPLETE.txt` is op's exit record, written on **every** exit path, not only on success:
`<STOP_KIND>,<final_seq>,<UTC ISO time>,<reason>`, e.g. `CLEAN,20,2026-10-31T03:00:09Z,max_iters_reached`.
`final_seq` is the last seq op measured and triggered.

| STOP_KIND | when | reason |
|---|---|---|
| `CLEAN` | a stopping criterion was met | gpCAM's `converged`, `max_iters_reached`, `grid_exhausted`, `user_stop`; op's own `op_max_iters` |
| `STALLED` | a wait timed out: a daemon did not answer | gpCAM's `wait_timeout`; op's `op_wait_timeout_<flag>` |
| `UNVERIFIED` | a measurement failed and did not recover, an exception, an abort, or a stop without a known reason | gpCAM's `error`; `unspecified` (a `GPCAM_STOP.txt` with no or an unknown reason, e.g. a bare `touch`); op's `measure_failed`, `exception:<type>`, `op_abort` |

- **No fall-through.** Each exit path sets its stop kind where it exits, and the final write defaults to
  `UNVERIFIED`: only a path that met a stopping criterion may set `CLEAN`. A timeout or error branch must never
  reach the clean finish; that fall-through wrote `complete,797` in Exp. 2.
- **Consumers read the stop kind, not the file's presence.** `CLEAN` → team-lead runs the completion handshake as a
  normal finish (`docs/completion-protocol.md`); `STALLED` or `UNVERIFIED` → the user hears first.
- Until Exp. 3 the file read `complete,<final_seq>,<timestamp>` on every exit path, so its presence said nothing
  about how a run ended.

## Logs (one writer per file)

- `op_log.csv` — operator-side, one row per commanded measurement (e.g. `seq,x,y,timestamp,tiff_prefix`). Append-only; preserved across a resume.
- `ana_log.csv` — analysis-side, one row per analyzed measurement (`seq, <params>, <metrics>`). **gpCAM reads THIS** (keyed by `seq`), not `op_log.csv`. Always put `seq` first so it joins cleanly with `op_log.csv`.

## Handshake (one uniform loop)

```
op:  wait GPCAM_NEXT.txt → read (seq,x,y) + DELETE it → move motors → expose →
     append op_log.csv → write TRIGGER.txt (seq|x|y|tiff_prefix) → wait ANA_DONE.txt →
     read + DELETE ANA_DONE.txt → loop
ana: poll TRIGGER.txt → parse seq|x|y|tiff_prefix → DELETE TRIGGER.txt →
     glob *<tiff_prefix>*_saxs.tiff (none found → *seqNNN*_saxs.tiff, newest: the live naming
     scheme can hold tokens op cannot reproduce, e.g. clock) → process.run([...]) → extract metrics →
     append ana_log.csv → write ANA_DONE.txt → exit on GPCAM_STOP.txt
gp:  read ana_log.csv (by seq) → propose next → write GPCAM_NEXT.txt;
     on convergence / max-iters / wait timeout / error write GPCAM_STOP.txt (STOP + reason)
op:  on GPCAM_STOP.txt (or its own max_iters / wait timeout / failure / abort) →
     write AE_COMPLETE.txt with the stop kind of THAT exit path → exit
```

## Race guard (MANDATORY for op-cog)

Every `_wait_for_file()` that blocks on another daemon's file MUST also break on `GPCAM_STOP.txt`
and on the abort event — so a stop arriving while waiting for `GPCAM_NEXT.txt` or `ANA_DONE.txt`
cannot hang the loop.

## Simulator-only variant (NOT live — do not use on the beamline)

The legacy simulator used `SEEDS_DONE.txt` / `OP_DONE.txt`, `TRIGGER.txt` as
`tiff_path|temperature|seq`, a fixed `EXCHANGE_DIR` / `WORKSPACE`, and `from cms_simulator import sam`.
None of these apply on the live 11BM-CMS beamline.
