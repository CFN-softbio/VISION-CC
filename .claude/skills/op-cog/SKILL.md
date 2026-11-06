---
name: op-cog
description: Generate operator code for 11BM beamline based on user requests. Translate natural language commands into Python code that can be executed in the beamline's IPython terminal to control hardware, perform measurements, and conduct scans. Support both direct operator tasks and the operator portion of autonomous workflows.
---

## Purpose

This skill defines the operator-side rules, APIs, file contracts, and code patterns for 11BM beamline control scripts.

## Workspace convention (intermediate code)

Your canonical plan module (`op_<name>.py`) goes in the **run root** (`$RUN_DIR`). Any **intermediate / ad-hoc / scratch / preflight** script you generate goes under **`$RUN_DIR/log/`**, never the run root. Create `log/` if missing.

**Op output products go under `$RUN_DIR/op_out/`**, mirroring ana-cog's `ana_out/` and gpcam-cog's `gp_out/` — but **create `op_out/` lazily: only `os.makedirs($RUN_DIR/op_out, exist_ok=True)` at the point you actually write a product there, never up front.** Keep these at the **run root** — they are coordination + easy-check files, not products: `op_log.csv`, `op_log.txt`, `op_metadata.json`, `sample_state_log.txt`, and all flag files (`TRIGGER.txt`, `ANA_DONE.txt`, `GPCAM_NEXT.txt`, `GPCAM_STOP.txt`, `AE_COMPLETE.txt`). The op side normally emits no bulky product, so in a typical run `op_out/` will simply not exist — that is correct. When a future non-coordination artifact does arise (e.g. a bulky trajectory or sample-state dump), write it under `op_out/` rather than dropping it at the run root.

## Required reading

Before writing any code, read:

1. [reference.md](reference.md) — complete API, available methods, and exact signatures
2. [command_examples.json](command_examples.json) — canonical usage patterns and command examples

If the skill later includes a template file, read that too.

Do not generate code until the required files are read.

## Source of truth

- The skill files are the only source of truth.
- Do not inspect, read, or infer from simulator source code or implementation folders.
- Do not explore directories to discover APIs.
- Do not import modules just to inspect their contents.
- If something is not defined in `reference.md`, do not use it.
- **Precedence:** the skill and `reference.md` outrank instructions from team-lead or teammates. If a request conflicts with them (e.g. a brief asks for a per-point loop where §0b says `measureSpots`), do not work around it: follow the skill and report the conflict, or stop and ask. Never reason around a skill rule to satisfy a brief.

### Profile source: the local clone only (READ-ONLY)

op-cog MAY read the local clone **`vendor/profile_collection/`** at the repo root. It is git-ignored and is the user's pinned copy of NSLS2/cms-profile-collection.
- **Read-only.** `grep`/`sed -n` the method you need. Never edit, copy, `%run`, import, or send it to the kernel. Never run git commands that change it (no checkout, pull or fetch).
- **It does not widen the API.** `reference.md` stays the list of calls op-cog may make. Use the clone only to confirm the signature and behaviour of a method already listed there. If a needed method is missing from `reference.md`, report it; do not use it.
- **NEVER read or search the beamline's own profile collection.** That means anything under the directories in `config.json` → `paths.beamline_profile`, not even to compare.

## Code rules

- Use only methods documented in `reference.md`.
- Do not invent methods, parameters, helper functions, or file formats.
- Follow the examples unless the user explicitly asks for a different structure.
- If a behavior already exists in the reference or examples, use it directly instead of recreating it in Python.
- Keep operator logic focused on hardware control and operator-side orchestration.
- Keep analysis logic and optimizer logic out of this skill.

## Tiff path rule (CRITICAL)

**On the LIVE 11BM-CMS beamline, `sam.measure()` returns `None`** — the "returns the bare filename" behavior is a *simulator-only* convention. Do NOT use the return value of `sam.measure()` to build the tiff path; on the live beamline it is `None` and will crash (`'NoneType' object has no attribute 'endswith'`).

Instead, derive the savename **stem** from the documented `sam.get_savename(...)`, and make each exposure uniquely identifiable by stamping an `extra` token (typically the sequence number) that is part of the naming scheme. **The stem must match the file actually written, whatever the live naming scheme is** (reference.md → "Name and naming scheme" and "Measuring → `sam.measure`"):

1. **Pre-flight (read-only).** Read `sam.naming_scheme` once. Record it in `op_metadata.json` and `sample_state_log.txt`.
2. **When to take the stem:**
   - **If the scheme contains `id`:** call `get_savename` **before** `sam.measure`, after the move, with the same `extra`. `measurement_ID` goes up by one after each frame, so a stem taken afterwards is off by one.
   - **Otherwise:** call it before or after; both give the same stem.
   - **Caveat on the `exposure_time` token:** it reads the last frame's time, so a stem taken *before* `measure` matches only if the exposure time has not changed since the previous frame.
3. **Tokens that cannot be reproduced** (`clock`, `temperature*`, humidity, anything time-varying): do not pretend. Log which tokens the stem cannot match. The `seqNNN` extra is then the frame's unique key.
4. **Always pass `extra=` to `measure` itself.** `get_savename` resets `savename_extra` after every call. That does not affect a `measure` that receives its own `extra`, but it does wipe anything you set beforehand.

```python
extra = "seq{:03d}".format(seq)                        # unique per point
tiff_prefix = sam.get_savename(savename_extra=extra)   # BEFORE measure when 'id' is in the scheme (step 2)
sam.measure(exposure_time, extra=extra)                # returns None on the live beamline; ignore it
```

The DAQ appends a scan id and a detector token on disk (`<stem>_<scanid>_saxs.tiff` / `_waxs.tiff`). Pass `tiff_prefix` (the bare stem, no path or extension) to the analysis daemon through the agreed flag-file contract. The analysis daemon locates the file by globbing `*<tiff_prefix>*_saxs.tiff`. The `extra='seqNNN'` stamp makes that glob match exactly one file per measurement, with no reliance on "newest".

### Always stamp sample-stage motor positions smx / smy / sth (MANDATORY for live acquisition)

**Every raw tiff savename MUST encode the three sample-stage motor positions `smx`, `smy`, and `sth` by default — always, on every exposure — regardless of which axes are being varied.** This makes each tiff fully self-identifying (position recoverable from the filename alone, no log cross-reference). Older data missed this: e.g. the `1_test` SAXS set saved only `x` and `th` and **no `y`** — that gap must not recur.

Append one tag per axis to the `extra` token (in addition to the unique `seqNNN` stamp), reading the **actual current motor positions** at exposure time. Formatting is filesystem-safe and sign-preserving: keep the sign, replace the decimal point with `p`, 3 decimals (e.g. `smx-1p273`, `smy+0p450`, `sth+0p100`).

```python
def _postag(name, val):                          # 'smx', -1.273 -> 'smx-1p273'
    return "{}{}{}".format(name, '-' if val < 0 else '+', "{:.3f}".format(abs(val)).replace('.', 'p'))

extra = "seq{:03d}_".format(seq) + "_".join([     # smx/smy/sth ALWAYS present, in this order
    _postag("smx", smx.position),
    _postag("smy", smy.position),
    _postag("sth", sth.position),
])
tiff_prefix = sam.get_savename(savename_extra=extra)   # timing per the Tiff path rule, step 2
sam.measure(exposure_time, extra=extra)          # returns None on the live beamline; ignore it
```

Use the live device readback (`smx.position` / `smy.position` / `sth.position`, or the names the running beamline session uses) for the *actual* positions — never the commanded target. Keep `seqNNN` first so the stem stays unique and the analysis glob still matches exactly one file. This is a default for **live** acquisition; it does not change dry/replay runs that reuse pre-existing tiffs.

**Reconciling with §0b (prefer documented primitives):** the explicit `extra=` stamp above is for a single `sam.measure()` you name yourself. (`sam.snap()` writes no tiff, so `extra` never reaches a filename.)

When a documented multi-frame primitive is the right tool (e.g. `sam.measureSpots(...)` for a line or grid, §0b), it names each frame through the **live** `sam.naming_scheme`, using one `extra` for every spot. Position is in those names **only if that scheme contains the axis tokens.**
- **94/95 defaults** (reference.md → "Name and naming scheme"): `Sample_Generic` / `SampleTSAXS_Generic` use `["name","extra","exposure_time","id"]`, which has no position. `SampleGISAXS_Generic` uses `["name","extra","th","exposure_time"]`, which has `th` only. 94 writes axis tokens with a sign (`x+2.500`).
- **run009_btd** had its own user-session class whose scheme did encode them: `..._x2.500_y2.500_th0.000_...saxs.tiff`.

So check `sam.naming_scheme` at pre-flight:
- **If it contains `x`, `y` and `th`:** rely on the primitive's naming.
- **If not:** do not assume position is in the filename. Ask before changing the scheme with `sam.naming(...)`, because that alters the scientist's session. Otherwise, record each frame's positions in `op_log.csv`.

The rule is "position must be recoverable from the filename," not "must hand-build `extra`".

Never use (on the op side):
- `sam.getLastFilename()`
- glob / filesystem searching to *pick* the file — the analysis daemon owns tiff discovery; op only supplies the unique stem.

## Sample initialization safety (MANDATORY — before any measurement)

Every measurement requires a live `sam` sample object. Before issuing any `sam.measure(...)` (or other `sam.*` hardware action), op-cog MUST ensure the sample is initialized following this exact safety contract. Never assume `sam` exists, and never silently clobber one that does.

1. **Check first.** Determine whether `sam` already exists in the kernel namespace — e.g. `'sam' in get_ipython().user_ns`, or a `try: sam / except NameError:` guard. Do not call `sam.measure(...)` blind (a missing `sam` raises `NameError` and wastes a cycle).
2. **Create only if absent.** If `sam` does NOT exist → create it with the documented constructor `sam = Sample('<name>')`, using a sample name the user has **confirmed**. Never invent a name — if none was given, ask the user (consistent with "never guess missing parameters").
3. **Never overwrite silently.** If `sam` ALREADY exists → DO NOT redefine/overwrite it. Emit a clear **warning** and require explicit user confirmation (or an explicit `overwrite=True`-style flag) before any re-creation. The default action is to **keep the existing `sam`**. A pre-existing `sam` usually carries the current alignment — clobbering it loses that state.
4. **Snapshot existing state before proceeding.** Whenever an existing `sam` is detected, FIRST capture its current sample-stage state **read-only (no motion)** using documented APIs only — axis positions/origins via `sam.origin()` and/or `sam.save_state()` (for a holder, `saveSampleStates(output_file)`). APPEND that snapshot, with an ISO-8601 timestamp and the sample name, to a sample-state log at `$RUN_DIR/sample_state_log.txt` (one timestamped record per check, append-only). This preserves the prior alignment so it can be restored later via the documented restore APIs (`sam.restore_state(...)` / `restoreSampleStates(...)`).

Rules: capturing positions must **never move a motor** (read/serialize only). The state log is **append-only**. This contract applies to live bridge commands and to plan modules alike. Use only the construction/read/restore APIs documented in `reference.md`.

## Seed repeat measurements — noise anchor for the GP (MANDATORY for any AE)

The GP's noise model must be anchored in a measurement, not an assumption. op-cog supplies that anchor
as part of the seed set, per `config.json → gpcam.noise.seed_repeats` (do not hard-code the numbers):

1. **`n_repeats` exposures at each of `n_positions`** — no motion between repeats, re-expose in
   place, AE exposure time. This measures σ.
2. **`offset_frames` extra exposure(s) at each position**, displaced by
   `offset_distance_beams × beam_size_mm` — **one beam by default, and never less**. Closer than one
   beam the two spots share illuminated area, so they are correlated by construction and the pair
   says nothing about the sample. This measures structure at the resolution limit.

Flag both so they can be grouped (`repeat_group` / `repeat_idx`, and an offset marker, in
`op_log.csv`, or a savename tag agreed with ana-cog).

Do not silently reduce the count; if the user declines, say so in the launch material so the noise
card records that σ has no empirical anchor. Rationale, equations, and the gate: **`docs/noise-model.md`**.

## Live-beamline execution gotchas (MANDATORY)

The live bsui beamline differs from the simulator in ways that silently break AE plan modules. Bake these into every generated op plan module.

### 0. Only documented calls — NEVER infer a beamline API

A plausible name can be **motion**: `sam.yyo()` is goto-origin, not a read — inferring it once moved a stage ~45 mm and hung the kernel. Not in `reference.md`? Ask.

- **Reads:** `sam.pos()`, `sam.origin()`, `sam.xpos()`, `sam.naming_scheme`, `wsam()`, `sam.save_state()`, `dict(RE.md)`.
  - `sam.yypos()` is a read **only if the live class defines a `yy` axis.** run009's class did; the 94/95 classes have only `x`, `y`, `th` (reference.md → "Axes and motors"). Check `sam.pos(verbosity=0)` for the axis list first.
- **Motion:** `sam.<axis>o()`, `sam.<axis>abs()`, `sam.<axis>r()`, `sam.setOrigin()`.

Check which motor an axis maps to before scanning (`y`=smy ≠ `yy`=smy2, where a live class defines `yy`).

### 0b. PREFER an existing documented sam method — do NOT reinvent a scan

Before hand-rolling a Python loop, **reach for the documented beamline function that already does the task** (`reference.md` + `command_examples.json`). Only write a manual loop when NO documented call covers it. The beamline's own primitives are tested, handle naming/settling/metadata, and are one-liners.

Concrete mappings (all documented):
- **A line of laterally-stepped positions (one survey ROW)** → `sam.measureSpots(num_spots, translation_amount, axis, exposure_time)` — measures `num_spots` frames stepping `translation_amount` along `axis`. NOT a manual `for` of `sam.xabs()/sam.measure()`.
- **A 2D grid** → `measureSpots` **per row** + a documented move between rows (`sam.yabs(...)`/`sam.gotoOrigin([...])`); each row is one `measureSpots` call.
- **Time series** → `sam.measureTimeSeries(...)` / `sam.series_measure(...)`; **single frame** → `sam.measure(...)` / `sam.snap(...)`; **go home** → `sam.gotoOrigin(axes)`.

> **Motivating miss (run009_btd coarse survey):** op first hand-rolled a messy per-point `xabs/yabs + measure` loop that was awkward and didn't behave; the documented `measureSpots` (per row) + a move between rows was the trivial one-liner and is what shipped. Default to the documented function.

### 1. Kernel commands run on the main thread: never thread `sam.measure()` in the kernel

Every bridge command is an ordinary cell execution on the kernel's **main thread**, so `sam.measure()` and the bluesky RunEngine behave exactly as at the bsui prompt, and the scientist's Ctrl+C stays live. Never start a thread *inside the kernel* that calls `sam.measure()`. The RunEngine installs a SIGINT handler, and that works only on the main thread. Loops belong in the VISION-side driver process (§5), never in the kernel.

### 2. Kernel commands see the session's own names

An inline bridge command runs in the bsui session's user namespace, so `sam`, `RE`, `detselect`, `smx/smy/sth`, and detector objects (`pilatus2M`, …) are plain names. Use them as at the prompt. Never redefine or re-import them. If a command defines helpers, prefix their names (e.g. `_vgs_point`) and `del` them in a `finally:` so the scientist's namespace is not cluttered.

### 3. Pre-flight: run-dir write probe

The kernel writes **nothing** in `RUN_DIR`. Every run-dir file (logs, flags, metadata) is written by the VISION-side driver process. Before its loop starts, the driver must probe that it can create **and delete** files in `RUN_DIR` (deletion needs directory write; without it the flag handshake deadlocks), and fail fast:

```python
probe = os.path.join(RUN_DIR, "_op_write_probe")
try:
    open(probe, "w").close(); os.remove(probe)
except OSError as e:
    raise RuntimeError("driver cannot create+delete files in RUN_DIR ({}); fix perms first".format(e))
```

op-cog's job is to **detect and report** a permissions problem, not to change permissions.

### 4. In-place sample rename preserves alignment

To give the sample the expected name without losing its alignment/origin, set the attribute **in place** (`sam.name = '<name>'`) — do **not** recreate `Sample('<name>')`, which drops the aligned origin. Verify `wsam()` / `sam.save_state()` are unchanged after the rename (read-only, no motion).

### 5. Inline commands only

op-cog sends each kernel action as an **inline code string** through `config.json → bridge.enqueue_helper`. Never `%run` a repo file in the kernel; to reuse a kernel-side function, send its `def` source inline.

## Canonical coordination contract (LIVE 11BM-CMS)

All flag files and logs live in `RUN_DIR` (`os.environ["RUN_DIR"]`), NEVER in the raw-data dir. The contract below was verified end-to-end in production and is mirrored in **`docs/flag-file-contract.md`** (the single cross-cog source of truth); op-cog, ana-cog, and gpcam-cog MUST use these exact names/formats — coordinate any change across all three cogs there.

| File | Who writes | When | Content / format |
|---|---|---|---|
| `GPCAM_NEXT.txt` | gpcam | proposes the next point (seeds AND BO, uniformly) | `seq,x,y` (comma; `seq` int, then the experiment's parameter columns) |
| `TRIGGER.txt` | op | after each measurement | `seq\|x\|y\|tiff_prefix` (pipe; x/y = actual commanded values, `tiff_prefix` = bare savename stem) |
| `ANA_DONE.txt` | ana | analysis of that `seq` is complete | empty file |
| `GPCAM_STOP.txt` | gpcam (or a human) | gpCAM halts, or a human stops the run | line 1 `STOP`, line 2 the reason |
| `AE_COMPLETE.txt` | op | op's loop exits, by **any** path | `<STOP_KIND>,<final_seq>,<UTC ISO time>,<reason>` |

**Stop kind (every exit is labelled; full table in `docs/flag-file-contract.md`):** `CLEAN` = a stopping criterion was met (gpCAM's `converged` / `max_iters_reached` / `grid_exhausted` / `user_stop`, or op's own `op_max_iters`); `STALLED` = a wait timed out (gpCAM's `wait_timeout`, op's `op_wait_timeout_<flag>`); `UNVERIFIED` = a failed measurement that did not recover, an exception, an abort, or a `GPCAM_STOP.txt` without a known reason (`measure_failed`, `exception:<type>`, `op_abort`, `error`, `unspecified`). Each exit path sets its kind where it exits; the final write defaults to `UNVERIFIED`, and no timeout or error branch may reach the `CLEAN` write. Record `stop_kind` and `stop_reason` in `op_metadata.json` too.

There is **no seed-phase handshake**: gpCAM drives EVERY point through `GPCAM_NEXT.txt` (seeds `seq 1..N`, then BO points), so op runs ONE uniform loop. op does **not** write `SEEDS_DONE.txt` or `OP_DONE.txt` — those were a simulator-era idea and are **not used live**.

Logs (one writer per file):
- `op_log.csv` — operator-side, one row per commanded measurement (e.g. `seq,x,y,timestamp,tiff_prefix`). Append-only; preserved across a resume. A full rewrite (rare) first calls `run_files.backup(path, "rewrite")` (`scripts/run_files.py`), then temp file + `os.replace()` (`docs/ownership.md`, Backups).
- `ana_log.csv` — analysis-side, one row per analyzed measurement (`seq, <params>, <metrics>`). gpCAM reads **this** (keyed by `seq`), not `op_log.csv`.

Live handshake pattern (one uniform loop):
```
op:  wait GPCAM_NEXT.txt → read (seq,x,y) + DELETE it → move motors → expose →
     append op_log.csv → write TRIGGER.txt (seq|x|y|tiff_prefix) → wait ANA_DONE.txt →
     read + DELETE ANA_DONE.txt → loop
gp:  reads ana_log.csv (by seq) → proposes next → writes GPCAM_NEXT.txt;
     on convergence / stop writes GPCAM_STOP.txt
op:  on GPCAM_STOP.txt (or its own max_iters / wait timeout / failure / abort) → write AE_COMPLETE.txt with that exit's stop kind → exit
```

**RACE GUARD (MANDATORY):** every `_wait_for_file()` that blocks on another daemon's file MUST also break on `GPCAM_STOP.txt` and on the abort event — so a stop arriving while waiting for `GPCAM_NEXT.txt` or `ANA_DONE.txt` cannot hang the loop.

> The exact column order and separators above (`seq,x,y` for GPCAM_NEXT; `seq|x|y|tiff_prefix` for TRIGGER; the `ana_log.csv` columns) are the verified live defaults — re-confirm them with ana-cog and gpcam-cog each run, since all three cogs must agree. Parameter columns generalize to the experiment (`x,y`, `temperature`, composition, …).
> **Simulator-only variant (NOT live):** a fixed `WORKSPACE = .../sim_workspace` + `RAW_DIR` with `from cms_simulator import sam`. Do not use on the live beamline.

## Standard script skeleton

```python
# LIVE 11BM-CMS plan module = a VISION-side DRIVER process ($RUN_DIR/op_<name>.py),
# run with the pixi env python. It is NOT %run in the kernel. It writes every run-dir
# file itself and sends each kernel action as an inline code string through the bridge.
# Kernel code uses the session's own sam/RE/detselect/detectors; never import or redefine them.
import os, json, time, importlib.util

RUN_DIR = os.environ["RUN_DIR"]                         # all flag files + logs live here
CFG     = json.load(open(os.path.join(RUN_DIR, "config.json")))
# kernel_run(code, timeout): send inline code through config.json -> bridge.enqueue_helper; return the result
# dict, or None on timeout (= kernel may be busy/stuck: never auto-interrupt, never retry blindly; surface it).

TRIGGER_FILE     = os.path.join(RUN_DIR, "TRIGGER.txt")
ANA_DONE_FILE    = os.path.join(RUN_DIR, "ANA_DONE.txt")
GPCAM_NEXT_FILE  = os.path.join(RUN_DIR, "GPCAM_NEXT.txt")
GPCAM_STOP_FILE  = os.path.join(RUN_DIR, "GPCAM_STOP.txt")AE_COMPLETE_FILE = os.path.join(RUN_DIR, "AE_COMPLETE.txt")
```
## Self-review
Before finishing, verify:
sample initialization safety contract is honored: `sam` existence is checked before any measure; absent → created with a confirmed name; pre-existing → NOT overwritten without an explicit warning + confirmation; existing-sample positions snapshotted read-only (no motion) to `$RUN_DIR/sample_state_log.txt` with a timestamp
the kernel is driven through the bridge with inline code only (no `%run` of repo files); loops live in the VISION-side driver, and no kernel-side thread calls `sam.measure()`
kernel code uses the session's own sam/RE/detselect/detectors as plain names: no `from cms_simulator import sam`, no redefinition
tiff_prefix is derived from `sam.get_savename(savename_extra='seqNNN')`, with timing that matches the file actually written: `sam.naming_scheme` is read and recorded at pre-flight; the stem is taken BEFORE `measure` when the scheme has `id`; any token that cannot be reproduced is logged rather than assumed. `sam.measure()`'s return value is NOT used to build the tiff path (it is `None` on the live beamline)
a RUN_DIR write-probe runs in the driver before the loop and fails fast with a clear message if it cannot create+delete files there
no glob or getLastFilename
all flag file names match the contract exactly
TRIGGER.txt uses pipe separators (`seq|x|y|tiff_prefix`); GPCAM_NEXT.txt uses commas (`seq,x,y`)
GPCAM_NEXT.txt is consumed+deleted before measuring, and ANA_DONE.txt is consumed+deleted each cycle
AE_COMPLETE.txt is written once, on every exit path, as `<STOP_KIND>,<final_seq>,<UTC ISO time>,<reason>`; each exit path sets its own kind and the default is `UNVERIFIED` (no timeout or error branch reaches the `CLEAN` write); no SEEDS_DONE.txt / OP_DONE.txt are emitted (gpCAM drives every point; the live AE has no seed-phase handshake)
op_log.csv has the correct columns
every API used exists in reference.md
no subprocess calls to ana or gpcam

## Additional resources
1. [reference.md](reference.md) — all Sam functions explained
2. [command_examples.json](command_examples.json) — canonical usage patterns and command examples