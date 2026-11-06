# Artifact Ownership (STRICT)

Single source of truth for which cog owns which generated file. **Cogs never edit each other's files.** CLAUDE.md keeps a compact summary; this is the full table + conventions.

## Artifact → owner

| Artifact | Agent |
|------|------|
| `runs/runNNN/op_<name>.py` (op kernel plan module) | **op-cog** |
| `runs/runNNN/op_log.csv`, `op_log.txt`, `op_metadata.json`, `sample_state_log.txt` (coordination/logs/metadata — **stay at run root**) | **op-cog** |
| `runs/runNNN/op_out/` — op **output products** (e.g. future trajectory/state dumps), **created lazily — only when a product is actually written**, never as an empty dir. Coordination logs/metadata above stay at the run root. | **op-cog** |
| `runs/runNNN/ana_runXS_<name>.py` (analysis daemon) | **ana-cog** |
| Ad-hoc one-off analysis `ana_<name>_oneoff.py` scripts | **ana-cog** |
| `runs/runNNN/ana_log.csv`, `ana_log.txt`, `ana_metadata.json` (coordination logs/metadata — **stay at run root**) | **ana-cog** |
| `runs/runNNN/ana_out_<detector>/` — ALL analysis **output products**, **one tree per detector** (`ana_out_saxs/`, `ana_out_waxs/`, `ana_out_maxs/`). TOP LEVEL = per-frame outputs for all data: `q_image/` (or `qr_image/` for GI), `circular_average/`, `thumbnails/`, `calibration_check/`, `results/` xml, result PNGs + JSON. `calibration_log/` = geometry-search by-products (sdd-scan table/plot, per-setting scratch, peak-fit summaries, overlays). Protocol folders are re-named when parameters change (`circular_average_sdd0p2350`) so re-runs never overwrite. | **ana-cog** |
| `runs/runNNN/gpcam_<name>.py` (daemon) | **gpcam-cog** |
| `runs/runNNN/gpcam_log.txt`, `gpcam_metadata.json` (coordination/metadata — **stay at run root**; writer reads the metadata there) | **gpcam-cog** |
| `runs/runNNN/gp_out/` — gpcam **output products** (`gpcam_hyperparameters.csv`, `gpcam_posterior.npz`, `gpcam_posterior_history.npz`) | **gpcam-cog** |
| `runs/runNNN/writer_<name>.py` (report generator script) | **writer-cog** |
| `runs/runNNN/output/report_final.html` (experiment report) | **writer-cog** |
| `runs/runNNN/output/results_*.png`, `results_*.gif` (plots + animations) | **writer-cog** |
| `runs/runNNN/launch.sh` | **team-lead** |
| `runs/runNNN/config.json` | **team-lead** |

## Persistence principle

Every cog persists what's needed to fully reconstruct its work without re-running anything — the exact per-cog contract is in each agent file's "Persist everything" section; writer-cog reads structured metadata (JSON + NPZ) first and mines logs only for anomaly notes.

## Backups (live files)

The live files are the ones daemons keep writing during a run: the append-only logs `op_log.csv`, `ana_log*.csv`,
`gpcam_log.txt`, and the `*_metadata.json` state files. A copy is kept before anything can lose rows:

- **Every (re)launch / restart / steer:** `scripts/make_run_tag.py` (pre-flight item 5) copies every live file to
  `log/backup/<file>.<UTC stamp>.start_<run_tag>.bak`. This is team-lead's step; no cog has to remember it.
- **Before a daemon rewrites an append-only log in full** (a backfill, a column change, a dedupe): call
  `run_files.backup(path, "rewrite")` from `scripts/run_files.py` (repo root on `PYTHONPATH`), then write a temp file
  in the same folder and `os.replace()` it into place. Never rewrite one of these logs in place, never truncate it.
  The `*_metadata.json` files are rewritten as state all the time; they get the start backups only.
- Backups are never overwritten (`_2`, `_3`, ... within one second) and never deleted during a run; `log/backup/` is
  scratch under `log/` like the rest.
- Restoring one is a team-lead / human decision: back up the current file the same way first, then copy the chosen
  `.bak` back.

## Filename convention (STRICT)

Every generated script is prefixed with its owning cog: `op_*`, `ana_*`, `gpcam_*`, `writer_*`. This makes ownership obvious from `ls`, lets monitor terminals filter by prefix (`pgrep -f ana_`, `pgrep -f gpcam_`), and prevents agents from accidentally editing each other's scripts. `<name>` is a short experiment tag (e.g., `2d_scan`, `temp_ramp`) shared across cogs in the same run so files stay grouped: `op_2d_scan.py`, `ana_runXS_2d_scan.py`, `gpcam_2d_scan.py`, `writer_2d_scan.py`. The ana daemon keeps the `runXS_` token after its prefix because that name carries SciAnalysis meaning at the beamline.

## Cog state notes

- **Op plan modules** are VISION-side driver processes that send inline commands through the file bridge; the run's state (seq, stop kind, final seq) lives in `op_metadata.json` and `op_log.csv`. The sample state (`sam`, its alignment) is the beamline session's own, which is why a live bridge command on top of a running plan works: it runs in the same kernel and sees the same `sam` object.
- **Analysis daemons** own their own state for the lifetime of the daemon process — `Calibration`, `Mask`, single `ProcessorXS` instance. There is no live REPL — mid-experiment requests to a running analysis daemon must go through command flag files it watches (e.g., `RECALIBRATE.txt`).
