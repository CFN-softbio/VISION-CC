---
name: ana-cog
description: Defines the approved SciAnalysis protocols, runtime structure, filesystem contracts (`TRIGGER.txt`, `ANA_DONE.txt`, `GPCAM_STOP.txt`), and coordination interfaces for generating standalone analysis scripts and watcher daemons at the 11BM beamline.
---

## Purpose

This skill defines the approved SciAnalysis protocols, runtime structure, filesystem contracts, and coordination interfaces for X-ray scattering data processing at the beamline.

## ana-cog is the analysis cog

You own **analysis** at the beamline — turning raw frames into numbers, metrics, calibrations, and the signal gpCAM optimizes. Your toolkit is **SciAnalysis** (everything below): reductions, peak fits, q-images, linecuts, beam-center / calibration, metric extraction — ad-hoc one-off scripts and/or the `ana_runXS_<name>.py` daemon (`TRIGGER.txt` → `ANA_DONE.txt`; append `ana_log.csv`).

## Workspace convention (intermediate code + output)

Your canonical daemon (`ana_runXS_<name>.py`) goes in the **run root** (`$RUN_DIR`). Any **intermediate / ad-hoc / scratch / validation** script you generate goes under **`$RUN_DIR/log/`**, never the run root. Create `log/` if missing.

### ONE SCRIPT AND ONE OUTPUT TREE PER DETECTOR (MANDATORY)

Detectors have different geometries, masks, and calibrations. Never mix their outputs.
**For every detector that has data, create the matching script and output dir:**

| detector data present | script (run root) | output tree |
|---|---|---|
| SAXS | `ana_runXS_saxs.py` | `ana_out_saxs/` |
| WAXS | `ana_runXS_waxs.py` | `ana_out_waxs/` |
| MAXS | `ana_runXS_maxs.py` | `ana_out_maxs/` |

```
$RUN_DIR/
├── ana_runXS_saxs.py          ana_runXS_waxs.py          ana_runXS_maxs.py
├── ana_out_saxs/              ana_out_waxs/              ana_out_maxs/
│   ├── q_image/  (or qr_image/ for GI samples)       <-- TOP LEVEL: per-frame outputs,
│   ├── circular_average/                                 run on ALL data
│   ├── thumbnails/
│   ├── calibration_check/                                the ring-overlay check (first-class output)
│   ├── <any extra per-frame analysis the run needs>
│   ├── results/               (xml written by the protocols)
│   └── calibration_log/       <-- geometry-SEARCH artifacts only (not the checks above)
│       ├── sdd_scan.png / .json      the sweep summary (table + one plot)
│       ├── peakfit_<line>_<tag>/     peakfit_summary_<tag>.json
│       └── calibrant_overlay_<tag>/  per-setting 1D overlays
```

**Top level of `ana_out_*` = the per-frame outputs for all data**, including `calibration_check/`
(the overlay is a first-class result you want visible, not buried). **`calibration_log/` = the
by-products of *searching* for the geometry** — the SDD-scan table and plot, per-setting peak fits
and overlays, any scratch. The distinction is "a result you keep" vs "the debris of the search".

**A scan is throwaway; the chosen geometry is evidence.** Sweeping a parameter must not leave a
full protocol tree per setting — write the per-setting reductions to a temp dir, delete it, and
keep only the scan table plus one summary plot in `calibration_log/`. Then at the ONE chosen
geometry, run the per-frame protocols (they land at the top level) **plus narrow-window peak fits
reporting measured q against expected q**. That table is what demonstrates a calibration is right;
a ring overlay can look plausible by eye, `fitted q0 = 2.0112 vs expected 2.0112, +0.00 %` cannot.
Draw the 1D picture with `calibration_helpers.plot_calibrant_overlay` rather than writing it again.

`OUTPUT_DIR = os.path.join(os.environ['RUN_DIR'], 'ana_out_<detector>')`, created with
`os.makedirs(..., exist_ok=True)` and passed as `output_dir=` to every `ProcessorXS.run(...)` /
`monitor_loop(...)`. Result PNGs and JSON you write yourself go there too.

**Exception — stays at the run root:** `ana_log.csv`, `ana_log.txt`, `ana_metadata.json`
(coordination logs/metadata that gpCAM and writer-cog read), the owned scripts, and flag files.

### CHANGE THE PROTOCOL FOLDER NAME WHEN YOU CHANGE PARAMETERS (MANDATORY)

SciAnalysis writes each protocol's output into a folder named after the protocol, so re-running
with different parameters **silently overwrites** the previous results and leaves figures on disk
whose parameters nobody can recover. Whenever you change a runXS parameter (SDD, beam centre, mask,
energy) or a protocol parameter (`q_max`, `dq`, `ztrim`, fit window, …), **change the protocol's
`name=` so the new output lands in its own folder**:

```python
tag = 'sdd%s' % ('%.4f' % SDD_M).replace('.', 'p')
Protocols.circular_average(name='circular_average_%s' % tag, ylog=True, gridlines=True)
Protocols.calibration_check(name='calibration_check_%s' % tag, AgBH=1, ...)
```

The folder name must identify what changed — `circular_average_sdd0p2350`,
`q_image_qmax0p13`, `fit_CeO2_111`. Then every figure on disk is traceable to the parameters that
produced it, comparisons across settings are possible, and nothing is lost to an overwrite.

## Required Reading

Before writing any code, read:

1. [reference.md](reference.md) — all SciAnalysis protocols and exact parameters
2. [runXS.py](runXS.py) — the structural template for `ana_runXS_<name>.py`. Copy its shape
   into `$RUN_DIR/ana_runXS_<name>.py`; never edit the template itself.
3. [calibration_helpers.py](calibration_helpers.py) — **READ THIS BEFORE ANY ANALYSIS, and always
   before touching a calibration.** It already solves the problems that otherwise get re-derived
   badly. See the table below.

Do not generate code until all three are read.

### calibration_helpers.py — what is in it, and when to use it

Pure, read-only, no side effects; SciAnalysis imported lazily inside the functions. Safe to import
and run as part of a cal-check without separate approval.

**BEAM CENTRE — exactly two functions, pick by whether a direct-beam frame exists.**

| function | use it when | instead of |
|---|---|---|
| `estimate_direct_beam_center(tiff, thresh_frac)` | **a DIRECT-BEAM tiff exists** — a bright central spot on the detector (SAXS transmission). Intensity-weighted centroid. | eyeballing a centroid |
| **`fit_beam_center_rings(tiff, mask, exclude_quadrant=)`** | **EVERY other case (WAXS/MAXS, no direct beam).** Uses `find_rings`, then takes the centre as the mean of the brightest ring's and the widest ring's Kåsa centre. `x0, y0`, gradient estimate `x0_grad, y0_grad`, `agree_px`, per-ring list. **Independent of SDD.** | the removed crest/symmetry finders |
| **`refine_sdd_from_rings(tiff, mask, center, sdd_prior, calibrant='AgBH'\|'CeO2')`** | **solve the distance, AFTER the centre.** N-RING DISAMBIGUATION: tries the bright rings as each low order (discrete hypotheses), each fixes an SDD exactly, keeps the one where the MOST rings land on integer orders. Scores ONLY the target calibrant. `sdd_prior` brackets, doesn't answer. Returns `sdd_refined`, `n_agree`, `assignments`, `rms_pct`. | the blind grid scan + fitting every order |
| `find_rings(tiff, mask, center=, r_min=)` | the shared ring detector both of the above call | a hand-rolled radial profile |
| `plot_calibrant_overlay(dat, out, agbh_q1=, ceo2_a=, fitted=)` | the 1D visual check — expected AgBH/CeO2 lines (+ fitted peaks) on the circular average | ad-hoc matplotlib |
| `scan_sdd_vs_calibrant(...)` | LEGACY coarse grid scan; superseded by `refine_sdd_from_rings`, kept as a fallback | — |
| `load_detector_mask_array` / `save_mask_png` | mask as boolean array / render a mask | re-reading PNGs yourself |

**How `fit_beam_center_rings` proves itself.** Each ring's centre is fitted independently, so the
brightest ring's and the widest ring's centres must **agree** (`agree_px` ≤ ~1 px) — that agreement
across a range of radii, and with the gradient estimate, is the validation. Disagreement means tilt
or an untrustworthy centre. On MAXS pass `exclude_quadrant` for the dead region.

**How `refine_sdd_from_rings` proves itself.** One ring can't pin SDD (it's order n at one distance,
n+1 at another). The answer is trustworthy only when **several rings agree on ONE SDD** — ideally a
**contiguous** run of orders (n4, n5, n6, …). Read `n_agree` (want ≥ 3–5) and `rms_pct` (want < ~0.5%).
A 2-ring, non-contiguous "match" (e.g. n2 + n12) is a coincidence, not a solve.

**Order is fixed: CENTRE first (`fit_beam_center_rings` / `estimate_direct_beam_center`), then
distance (`refine_sdd_from_rings`).** SDD about a wrong centre cannot converge — a wrong centre
smears the rings out of the circular average. **Always** then run `calibration_check` and look at
the image: the overlay rings must sit on the scattering rings.

**If a parameter tweak is not enough** — a different fit model, derived metrics, custom plot
annotations, chained fits — load the **`ana-customization`** skill and subclass the protocol
inline. Never edit SciAnalysis source, and never write a protocol from scratch.

## Source of Truth

The skill files are the only source of truth.

Do not:

- inspect the SciAnalysis source tree
- infer protocols or parameters from implementation
- explore directories to discover functionality
- use any protocol, parameter, or workflow not defined in `reference.md`

If something is not defined in `reference.md`, do not use it.

## Runtime Configuration

`SciAnalysis_PATH` comes from the run's `config.json` (`paths.scianalysis`, set at Step 0) —
**do not hard-code it.** Read it from `config.json` at the top of every generated script and
append it to `sys.path`. `runXS.py` and `calibration_helpers.py` carry no built-in path. For a
quick offline one-off with no `config.json`, ask the user where SciAnalysis is installed.

### Detector mask lookup (MANDATORY)

Every generated script that needs a detector mask MUST look for it under the
SciAnalysis masks directory:

```
<SciAnalysis_PATH>/SciAnalysis/XSAnalysis/masks/Dectris/
```

Available masks follow the naming convention `<Detector>_<type>-mask.png` (e.g.
`Pilatus2M_gaps-mask.png`, `Pilatus300k_main_gaps-mask.png`). The script should
select the mask matching the detector in use. Never fall back to a bare all-valid
mask when a matching file exists in this directory.

The detector name and mask file should be specified in the run's `config.json`
(field `detector.mask_file`). If `config.json` is not yet available (e.g. a quick
one-off cal-check), construct the path from `SciAnalysis_PATH` + detector name:

```python
MASK_DIR = os.path.join(SciAnalysis_PATH, 'SciAnalysis', 'XSAnalysis', 'masks', 'Dectris')
MASK_FILE = os.path.join(MASK_DIR, 'Pilatus2M_gaps-mask.png')  # match to detector in use
```

## Canonical ProcessorXS Construction

`ProcessorXS` must be instantiated exactly once at module startup.

### Canonical default `run_args` (use verbatim)

Every generated script builds `run_args` from this canonical block. These are the
DEFAULTS — only override a key when the request explicitly calls for it.

```python
load_args = {'calibration': calibration, 'mask': mask}

run_args = {
    'verbosity': 3,
    # hdf5 omitted — the 11BM-CMS SciAnalysis build's hdf5 writer errors; xml/plots/txt only.
    'save_results': ['xml', 'plots', 'txt'],
    'rcParams': {
        'axes.labelsize': 25,
        'xtick.labelsize': 20,
        'ytick.labelsize': 20,
        'xtick.major.pad': 10,
        'ytick.major.pad': 10,
    },
}

process = Protocols.ProcessorXS(load_args=load_args, run_args=run_args)
```

`run_args` is merged into every protocol's `run()`, so `save_results` and `rcParams`
apply to all protocols in the `protocols = [...]` list unless a protocol overrides them.
`save_results` and `rcParams` are both base-`Protocol.run()` keys (see `reference.md`
→ Base Class `Protocol`, and the Plotting-style appendix). The three output types
`['xml', 'plots', 'txt']` give the XML results record, the plot images, and the
ASCII `.dat` curves in one pass. (hdf5 omitted — the 11BM-CMS SciAnalysis build's
hdf5 writer errors; xml/plots/txt only.)

Rules:

- instantiate once at module level
- never instantiate inside loops
- never recreate per file
- never reinitialize per call
- build `run_args` from the canonical block above; do not silently drop `save_results`
  or `rcParams`

### Plotting defaults (DEFAULT for all generated scripts)

These are the documented plotting DEFAULTS. The exact parameter names are taken from the
canonical template (`runXS.py`) and recorded in `reference.md` → *Plot-styling parameters
(cross-protocol)*. **Do not invent variants.**

**The default per-frame protocol set** (what runs on ALL data, into the top level of `ana_out_*`):

- `circular_average` — the 1D curve;
- **`q_image` for TRANSMISSION samples, `qr_image` for GRAZING-INCIDENCE (GI) samples** — the 2D
  map. GI geometry uses `qr_image` (in-plane qr vs qz); pick by sample geometry, not by detector;
- `thumbnails` — a quick raw-image thumbnail so a browse of the run is possible at a glance.

This set is **one protocol list applied per frame**, so it is identical for **batch** and **live**:
- **batch (offline)** — `process.run(infiles, protocols, output_dir=...)`; pass the whole glob, the
  ProcessorXS loops internally. This is how a directory is reduced.
- **live (AE)** — `process.monitor_loop(source_dir, pattern, protocols, output_dir=...)`.
There is no separate "batch defaults" — the same three (or four, on a calibrant frame) run on every
frame either way. Never hand-roll a `for file in files` loop; hand the list to `run()`.

`calibration_check` runs at the same top level (a first-class per-geometry check); only the
geometry-*search* by-products go under `calibration_log/` (see the output-tree section).

**2D image protocols** — `q_image`, `qr_image`, `q_image_special`, and any 2D detector /
q-space image: set `transparent=False` and add a colorbar with `colorbar=True`. Keep
`plot_buffers=[0.2, 0.1, 0.2, 0.1]` so the colorbar has room.

```python
# 2D images (q_image, qr_image, q_image_special, …) — opaque + colorbar
Protocols.q_image(transparent=False, colorbar=True,          # qr_image for GI samples
                  plot_buffers=[0.2, 0.1, 0.2, 0.1],
                  blur=None, ztrim=[0.05, 0.005], method='nearest')

# 1D curves — gridlines on; circular_average also log-y, everywhere
Protocols.circular_average(ylog=True, gridlines=True)

# raw-image thumbnail — default for every frame (same params as calibration rule 4c)
Protocols.thumbnails(name='thumbnails', crop=None, blur=2.0, resize=0.2, ztrim=[0.05, 0.005])
```

`ylog=True` is a standing default (not calibration-scoped): on a linear axis the low-q rise
dwarfs everything else. Override only when a request asks for linear. If a 1D protocol does
not accept `gridlines`, add `'axes.grid': True` to that script's `rcParams` instead of
inventing a parameter — the canonical `run_args` deliberately leaves `axes.grid` unset.

## Protocol Usage — the line is UPSTREAM vs DOWNSTREAM of the protocol output

The normal shape of an analysis is: **run the protocols, then write a small script that loads what
they wrote.** Both halves are expected. What must never happen is reimplementing the first half.

| | do this |
|---|---|
| **Upstream** — reduction, geometry & calibration, peak fitting, masking, circular/sector averaging | use the **helper** (`calibration_helpers.py`) or the **protocol**. Never reimplement. |
| **Downstream** — reading `.dat` / `.npz` / `results/*.xml`, overlaying expected lines, comparing settings, custom figures, summary tables | **write the small script.** This is ordinary work, not a fallback, and needs no justification. |

- Do not reimplement protocol behaviour in Python, and do not recreate outputs a protocol already
  generates (`.dat` files, per-measurement plots).
- Use protocol outputs as inputs for further computation — that is what they are for.

**Why this is a rule and not a preference.** A protocol runs through the same `Calibration`
object the rest of the pipeline uses, so what it reports is what the pipeline believes. A
parallel hand-rolled implementation can be internally perfect and still describe a different
geometry than the one the data is being reduced under — and nothing will flag the divergence.
Two costly examples from run007:

- **Calibration.** The SAXS SDD was solved by three separate bespoke radial-profile scripts
  that imported neither `Calibration` nor the `xray-calc` module, while
  `Protocols.calibration_check(AgBH=True)` — which overlays the expected rings on the actual
  image, through the actual calibration — was run only afterwards, as a rubber stamp. Geometry
  determination belongs to `calibration_check`; iterate `set_distance()` until the overlay sits
  on the rings. `xray-calc` converts an *already-calibrated* q; it does not establish geometry.
- **Peak finding.** A hand-rolled background subtraction plus `scipy.find_peaks` on a MAXS
  circular average produced twenty "peaks" that turned out to be one broad feature sliced by
  module gaps, averaged about a beam centre sitting in a dead detector quadrant. The protocol
  path (`calibration_check` overlay first, then `circular_average_q2I_fit`) would have shown
  the geometry was wrong before any peak list existed.

**When a protocol genuinely does not cover it** (a custom order parameter, a bespoke gate),
subclass or extend rather than starting from raw arrays — see the `ana-customization` skill —
and keep the `Calibration`/`Mask` objects in the loop so the geometry stays shared.

## Save the evidence for every decision (MANDATORY)

Any analysis that informs a decision — a calibration, a window choice, a peak assignment, an
include/exclude call — **must leave a figure a human can check**, not just a number in a
message. Numbers in prose are unfalsifiable; a plot shows whether the fit sat on the data.

- Save to the owning cog's output dir (`ana_out/…`, or `log/` for one-off diagnostics), at a
  path you state in the message that reports the result.
- Show the **input and the fit together** — the curve with its background, the image with the
  overlay, the peak positions against the model lines — so the reader can disagree.
- Plot in the space where the claim is falsifiable. Detector radius is geometry-independent;
  q is not, since it already assumes the geometry under test.
- If a result is *negative* ("no rings", "not this calibrant"), the figure matters more, not
  less: that is the claim hardest to take on trust.

This is not the same as the writer-cog report. It is the working evidence behind a call, and
it is what makes a decision reviewable months later.

## Data Access Rules

Use the expected SciAnalysis output structure, rooted at `OUTPUT_DIR = $RUN_DIR/ana_out`:

```python
OUTPUT_DIR = os.path.join(os.environ['RUN_DIR'], 'ana_out')
os.makedirs(OUTPUT_DIR, exist_ok=True)
# example product path:
os.path.join(OUTPUT_DIR, 'circular_average', basename + '.dat')
```

Do not guess file locations outside defined patterns. `ana_log.csv` and other
coordination logs/metadata are the exception — they stay at the run root, not under `OUTPUT_DIR`.

## Canonical Coordination Contract

The flag-file + log contract is defined ONCE in **`docs/flag-file-contract.md`** (the LIVE
11BM-CMS contract, verified in production). op-cog, ana-cog, and gpcam-cog all follow it — do not
redefine names/formats here; coordinate any change across all three cogs in that file.

### Analysis-Side Handshake (per that contract)

1. Poll `TRIGGER.txt`
2. Parse `seq|x|y|tiff_prefix` (pipe-separated; `x|y` = the run's parameter columns, `tiff_prefix` = bare savename stem)
3. Delete `TRIGGER.txt`
4. Locate the tiff by globbing `*<tiff_prefix>*_saxs.tiff` (op supplies the stem; ana owns discovery); if that finds nothing, glob `*seqNNN*_saxs.tiff` (`seq` from TRIGGER, 3 digits) and take the newest match — the live naming scheme can hold tokens op cannot reproduce (e.g. a clock), and newest covers retries like `seqNNNa2` (`docs/flag-file-contract.md`)
5. Run `process.run([tiff_path], ...)`
6. Load protocol output files, extract metrics
7. Append `ana_log.csv` (`seq` first column)
8. Write `ANA_DONE.txt`
9. Exit on `GPCAM_STOP.txt`; otherwise repeat

**Every TRIGGER gets a row and an `ANA_DONE.txt` — failures included.** If the frame never appears
within the wait (neither glob in step 4 finds a settled file), or the protocol raises / writes no
result, still append the `ana_log.csv` row for that `seq` — parameter columns from TRIGGER, **NaN in
every metric column** — write `ANA_DONE.txt`, and log an `ERROR` line in `ana_log.txt` naming the
cause (frame not found: the globs tried and the wait; fit failure: the exception). Both failures take
this one path. The loop keeps going; gpCAM treats a NaN objective as missing (not trained on, no
imputation) while still counting that point as measured for the min-step mask and the budget. Never
skip the row or withhold `ANA_DONE.txt` — that stalls op on its `ANA_DONE` wait and gpCAM on its
`analysis_wait_timeout_s` and ends the run `STALLED` over one bad frame. A gated objective of `0.0` is
a real value, not a failure; NaN is reserved for "no measurement".

There is **no** `SEEDS_DONE.txt` / `OP_DONE.txt` handshake and **no** `temperature`-only TRIGGER
format — those were simulator-era. The legacy `WORKSPACE = '...SciAnalysis-master'` constant is not
the exchange dir; all flag files live in `$RUN_DIR`.

## Logging

Append analysis results to `ana_log.csv` inside `$RUN_DIR`. This is the single analysis-side log: gpCAM reads it to train its surrogate, writer-cog reads it to plot. Columns are experiment-specific (e.g., `seq,smx,smy,signal` for 2D; `seq,T,q0,intensity,fwhm` for a 1D temperature scan with peak fitting). Always include `seq` as the first column so it joins cleanly with `op_log.csv`. **Never rewrite `ana_log*.csv` in place:** for a backfill, a column change or a dedupe, first `run_files.backup(path, "rewrite")` (`scripts/run_files.py`, repo root on `PYTHONPATH`), then write a temp file in `$RUN_DIR` and `os.replace()` it into place (`docs/ownership.md`, Backups).

**Seed repeat frames (AE runs).** op-cog measures a few repeat exposures at the same position to anchor
the GP noise model (`docs/noise-model.md`). These are **ordinary frames — analyze and log every one**;
never dedup or collapse rows by position, since repeats at an identical `(x,y)` are deliberate. Nothing
else is required of ana-cog; gpcam-cog computes the statistics from `ana_log.csv`.

## Calibration helpers (reusable)

For calibration / circular-average tasks, reuse the proven, git-tracked helpers in
[calibration_helpers.py](calibration_helpers.py) instead of re-deriving the logic.
They are generalized from the validated run001_ana AgBH calibration check (direct-beam
seeding, CMS Pilatus 2M 5 m mask loading, effective-mask PNG dump; AgBH q1 +0.37%, GOOD).
Import them; they have no top-level side effects and use only SciAnalysis objects/protocols
defined in `reference.md` (`Calibration`, `Mask`, `Data2D`, `ProcessorXS`, and the
`fit_calibration` / `circular_average` / `calibration_check` protocols).

These are **safe pure-analysis utilities** — read-only inputs, deterministic, no writes to
data directories — and may be run without separate user approval.

**Functions + signatures:**

Beam-center seeding:
- `estimate_direct_beam_center(tiff_path, loader=None, thresh_frac=0.5) -> (x0, y0) | None`
  Robust intensity-weighted centroid of the bright direct-beam blob (thresholded at
  `thresh_frac*max`, not a bare argmax, to avoid cosmic rays). Returns `None` on failure so
  the caller can fall back to the detector center.

Masks (see rule 2 — masks come from the stock beamline PNGs):
- `load_detector_mask_array(mask_file, target_shape) -> bool[H,W]`
  Load a mask PNG as a boolean array (True = masked), transposing/validating against the
  detector shape. Use it to union an extra PNG (e.g. the generic gaps mask) into the
  configured `detector.mask_file`.

Output rendering:
- `save_mask_png(mask, out_path, title=None) -> masked_fraction`
  Renders the effective mask (Agg backend, white=valid/black=masked, `origin='upper'` to match
  SciAnalysis 2D images), title includes masked %, returns the masked fraction.

Geometry calibration (detector-agnostic — SAXS & WAXS):
- `find_rings(tiff_path, mask, center=None, exclude_quadrant=None, r_min=20, n_rings=12, ...) -> dict`
  The shared ring DETECTOR that both center- and SDD-solving build on. Fine 1-px azimuthal-median
  radial profile about `center` (bootstraps a gradient-intersection center if none given),
  Savitzky-Golay background, `find_peaks` on the residual → ring radii; Kåsa-fits each ring's
  pixels for a per-ring `(cx, cy, R, resid_std, intensity)`. Returns {center, gradient_center,
  rings}. Fine detection is what recovers the full harmonic series (coarse binning merges/misses
  rings and invents half-integer orders). Pass `exclude_quadrant` for a dead region.
- `fit_beam_center_rings(tiff_path, mask, exclude_quadrant=None) -> dict`
  Beam center from RING GEOMETRY (no direct beam needed), SDD-independent. Calls `find_rings`,
  then takes the center as the mean of the brightest ring's and the widest ring's Kåsa center.
  Returns {x0, y0, x0_grad, y0_grad, agree_px, rings}. The ring centers must AGREE (small
  `agree_px`, ≤ ~1 px) — that is the validation. This is the ONLY ring-geometry center finder;
  the older crest-fit and line-symmetry functions were removed (fragile on real MAXS data).
- `refine_sdd_from_rings(tiff_path, mask, center, sdd_prior, calibrant='AgBH', q1=None,
  ceo2_a=5.411, tol_pct=1.0, min_rings_agree=2, ...) -> dict`
  Solve SDD by N-RING DISAMBIGUATION, center fixed. One ring is order n at one SDD and n+1 at
  another, so a single ring pins nothing; this tries each bright ring as each plausible low order
  (discrete hypotheses), each of which fixes an SDD exactly, and keeps the SDD where the MOST
  detected rings land on integer calibrant orders. `sdd_prior` only brackets the search (per
  `SDD_PRIORS_M`), it does not supply the answer. Scores ONLY the target calibrant's line list.
  Returns {sdd_refined, n_agree, accepted, assignments, rms_pct, sdd_prior, candidates}. Trust it
  only when several rings agree — ideally a contiguous order run (n4,n5,n6,…); read `n_agree`
  (≥3–5) and `rms_pct` (<~0.5%). Can pass pre-computed `rings=` to reuse a `find_rings` result.
- `scan_sdd_vs_calibrant(tiff_path, mask, center, sdd_grid, calibrant='AgBH', ...) -> dict`
  LEGACY coarse grid scan (superseded by `refine_sdd_from_rings`; kept as a fallback). With the
  center fixed, scans SDD and picks the value minimising mean |%-error| of visible calibrant
  rings. A single-ring minimum is a false solve — that degeneracy is exactly what
  `refine_sdd_from_rings` exists to break; prefer it.
- `plot_calibrant_overlay(source, out_path, agbh_q1=None, ceo2_a=None, fitted=None, ...) -> dict`
  The 1D visual check: draws the EXPECTED AgBH orders / CeO2 lines (and fitted peak positions,
  if given) on a circular-average `.dat`, so a human can see whether they coincide.

**Standing rules for cal-check / circular-average tasks:**

1. **Solve the beam center for the detector you actually have, then verify with
   `calibration_check`.** The beam center is NOT fixed across experiments — on WAXS it can move
   a lot per run (the detector is repositioned) and there is usually **no direct-beam frame**.
   So do NOT assume a fixed center and do NOT rely on `fit_calibration` to find it. The full
   decision procedure is the dedicated section **"Detector-agnostic geometry calibration (SAXS
   & WAXS)"** below; in brief:
   - **SAXS with a direct-beam tiff** → seed the center with `estimate_direct_beam_center`
     (robust centroid), then refine SDD with `Protocols.fit_calibration(material='AgBH01')`.
   - **WAXS (or any frame with no usable direct beam)** → the center comes from the **ring
     geometry itself** (fit circles to the scattering arcs, `fit_beam_center_rings`), NOT from a
     centroid and NOT from `fit_calibration`.
   **CRITICAL — what `fit_calibration` actually does on this build:** it refines the
   **sample-detector DISTANCE only**. It does **not** move the beam center (it returns
   `x0,y0` exactly equal to the seed), and on short-distance / beamstop-occluded WAXS frames it
   can raise a `ValueError` mid-run while still writing a bad distance. Treat any
   `fit_calibration` result where `x0,y0 == seed` as "center NOT refined", and never report a
   center as refined just because `fit_calibration` ran. `calibration_check` (rule 4d) is a
   SEPARATE protocol that only *draws* the expected rings for visual verification — it never
   moves geometry.
2. **Masks come from existing PNGs — there is no auto-mask. Pick the one that matches the
   detector + geometry**, set it as `detector.mask_file` in `config.json`, and load it with
   `Mask(mask_file)`. Always print the masked fraction (`save_mask_png`) and eyeball it once.

   - **SAXS (Pilatus 2M)** — the beamstop is part of the mask, so the beamstop STYLE must
     match what is installed. Ready-made examples ship with this skill:
     `example_pilatus2M_circular_5m.png` (round beamstop on an arm, 5 m, 1679×1475, 45.6%
     masked — this is the run003/run004 production mask) and `example_pilatus2M_rod.png`
     (rod beamstop). The stock beamline mask
     `NSLSII_11BM_CMS/Pilatus2M_CMS_5m-mask.png` (44.6%) is the fallback.
   - **WAXS (Pilatus 800k / 800k2)** — **no beamstop at all**; mask only gaps, corners and
     bad pixels. Use the `Dectris/Pilatus800k*` / `Pilatus800k2*` family
     (`_gaps-mask`, `_corner-mask`, `_vertical_gaps-mask`, `_generic-mask`) plus
     `NSLSII_11BM_CMS/Pilatus800k_CMS_badpixels-mask.png`. Never add a beamstop here.
   - **Unions and tweaks** (only when the data shows they are needed): combine PNGs with
     `load_detector_mask_array` — e.g. add `Dectris/Pilatus2M_gaps-mask.png` (7.97%) for full
     inter-chip gap coverage. On SAXS, if the beamstop shadow sits off the fitted beam center,
     shift the **beamstop component only** and keep gaps/corners detector-fixed.
   - Shapes must match the detector (`load_detector_mask_array` transposes if needed and
     raises otherwise) — a 2M mask on an 800k frame is an error, not a resize.
3. **Convert the boolean mask to a SciAnalysis `Mask` for `ProcessorXS`.** The auto-mask
   functions return a `True = masked` boolean array. SciAnalysis `Mask.data` uses the
   inverse convention (`1 = valid, 0 = masked`), so build the Mask as
   `mask = Mask(); mask.data = (~final_masked).astype(np.uint8)`. Record the effective mask
   PNG via `save_mask_png(mask, out_path)` for the run record.
4. **Always emit the FOUR mandatory calibration outputs.** Every CALIBRATION run produces all
   four, every time, using only protocols/params from `reference.md`. The
   `calibration_check` overlay (d) is the actual calibration *verification* protocol — it is
   part of the mandatory set, NOT something the three reduction outputs replace. (It was in
   the original run001_ana version and must not be dropped again.)
   (a) **circular average — I(q):** `Protocols.circular_average(name='circular_average',
       ylog=True, gridlines=True)`
       (optional `bins_relative=1.0`, `trim_range=[q_min, q_max]`). `ylog=True` and
       `gridlines=True` are simply the GENERAL `circular_average` defaults (see Plotting
       defaults above) — they are no longer calibration-scoped, but they remain essential
       here so the AgBH harmonic rings stay visible (on a linear y-axis the low-q rise dwarfs
       the rings). `ylog` is the `reference.md` log-y parameter (`reference.md` line 271,
       "`ylog` | `True` | Use log scale on y-axis"); use that exact name (NOT `yscale`/`logy`).
       Copy-ready calibration circular_average snippet:
       ```python
       # (a) calibration I(q): LOG y-axis so AgBH rings stay visible + gridlines
       Protocols.circular_average(name='circular_average', ylog=True, gridlines=True)
       ```
   (b) **q-image — 2D remapped q-space image:** `Protocols.q_image(name='q_image', blur=None,
       ztrim=[0.05, 0.005], method='nearest')` (optional `q_max=...`; 2D defaults
       `transparent=False, colorbar=True, plot_buffers=[0.2, 0.1, 0.2, 0.1]`);
   (c) **thumbnail — quick detector-image thumbnail:** `Protocols.thumbnails(name='thumbnails',
       crop=None, blur=2.0, resize=0.2, ztrim=[0.05, 0.005])`;
   (d) **calibration check — expected-ring overlay on the 2D image:**
       `Protocols.calibration_check(name='calibration_check', AgBH=True, q0=<q1_invA>,
       num_rings=5, dq=0.01)`. This is the AgBH (silver behenate) ring-overlay verification:
       it draws the expected harmonic rings (at integer multiples of `q0`) on the 2D image so
       a human can confirm the refined geometry. Exact `reference.md` params (lines 474-487):
       `AgBH` (`True` → overlay silver behenate rings), `q0` (custom first-order ring position;
       pass the AgBH q1 here), `num_rings` (default `5`, number of harmonic rings when using
       `q0`), `dq` (default `0.01`, fractional ring width = `q × dq`); `CeO2` and `resize` also
       exist but are not needed for an AgBH check. 2D image protocol → apply the 2D plotting
       defaults (`transparent=False, colorbar=True, plot_buffers=[0.2, 0.1, 0.2, 0.1]`).
   Copy-ready calibration_check snippet:
   ```python
   # (d) AgBH ring-overlay verification on the 2D image (q0 = AgBH first-order q1)
   Protocols.calibration_check(name='calibration_check', AgBH=True, q0=Q1_REF,
                               num_rings=5, dq=0.01,
                               transparent=False, colorbar=True,
                               plot_buffers=[0.2, 0.1, 0.2, 0.1])
   ```
   Note the exact `reference.md` names: the q-image protocol is `q_image` (underscore), the
   thumbnail protocol is `thumbnails` (plural), and the overlay protocol is `calibration_check`
   — use those verbatim, do not invent variants. **Distinction (see rule 1):**
   `fit_calibration` is the geometry *refinement* of the **sample-detector DISTANCE ONLY** (it
   does NOT move the beam center — see rule 1); `calibration_check` is the geometry
   *verification* (overlay). Both belong in a calibration run; rule 4d covers only the
   verification overlay.

## Multi-position stitching (reusable)

Frames taken at two (or more) detector positions (`_pos1_`, `_pos2_`) can be merged into one
image with the Pilatus **inter-module gaps filled**. Reuse the git-tracked
[stitch_pilatus.py](stitch_pilatus.py) — do NOT re-implement it, and do NOT port the beamline
notebook (`StitchPilatus/stitch_800k.ipynb`), which averages `-2` dead-pixel FLAGS in as if
they were photon counts (75 px/frame halved on our MAXS data), pairs by a hand-set
scan-number `interval`, and silently drops repeat measurements.

Like `calibration_helpers.py`, this is a **safe pure-analysis utility** — read-only inputs,
deterministic, writes only where told — and may be run without separate user approval.
One script covers **both** detectors; there is nothing SAXS- or WAXS-specific to choose.

```bash
export SCIANALYSIS_PATH=<config.json paths.scianalysis>      # or pass --scianalysis
python3 stitch_pilatus.py --input <raw_dir_or_frame.tiff>   # detector + shift auto-resolved
python3 stitch_pilatus.py --input <raw_dir> --dry-run       # show pairing, write nothing
python3 stitch_pilatus.py --input <raw_dir> --limit 10      # quick check before the full run
```
Output defaults to `<input>/../stitched`; override with `--output-dir`.

```python
from stitch_pilatus import (DETECTORS, SENTINEL, parse_name, match_key, find_groups,
                            check_pairing, identify_detector, measure_shift, verify_shift,
                            stitch_files, stitch_arrays, load_gaps_mask, save_stitched)
```

**Rules — each of these has bitten in practice:**

1. **Never hardcode the pos1→pos2 scan offset.** It equals frames-per-position (e.g. `+3` for
   three incident angles, `+5` for five) and is dataset-specific. The default
   `--match-by key` pairs on `(sample, x, th, exposure, detector)`, so the offset is *derived*
   rather than supplied. The notebook's `interval=1` drops 22 of 30 pairs on our MAXS data.

2. **Two independent pairing checks, and neither is redundant.** The offset must be consistent
   *within each sample* — NOT globally: one raw directory legitimately holds several
   acquisition patterns (our SAXS data has a standard at `+1` beside samples at `+5`).
   Separately, `IDENTITY_FIELDS` must agree inside every group. A uniformly wrong interval
   gives a perfectly consistent offset and is caught **only** by the field check; ragged
   mis-pairing is caught **only** by the offset check. The run aborts on failure;
   `--ignore-pairing-check` exists but mis-paired frames look perfectly normal and are wrong.

3. **Downstream masking changes for stitched frames.** Uncovered pixels carry `SENTINEL`
   (`-2`) — import it, don't hardcode. Mask with `valid = (data > -2)` and **do NOT apply the
   gaps mask**: the gaps are filled, so it would discard exactly what the stitch recovered.
   Still mask hot pixels from `config.detector.hot_pixels_row_col` (defects at both positions,
   they survive stitching). Geometry — beam center, SDD — is **unchanged**, since the stitch
   keeps the reference position's pixel grid. Measured coverage:
   WAXS `0.7425 → 0.7911` (+4.9%), SAXS `0.9203 → 0.9905` (+7.0%).

4. **Detector is auto-identified; do not pass `--detector` unless it fails.** Frame dimensions
   first, then — for 800k vs 800k2, which are both 981×1043 — by gaps-mask fit against the
   frame's own inactive pixels (1.0000 vs 0.6287 in practice). Note the masks' valid
   *fraction* is 0.7425 for **both**, so only the pixel pattern separates them.

5. **The 30 px shift is a convention, and is re-verified every run.** 30 px vertical is the
   standard CMS pos1→pos2 move on both detectors, so it lives in the registry — but
   `verify_shift()` re-derives it from a real pair (phase correlation for magnitude, an
   agreement test for sign) and reports CONFIRMED / INCONCLUSIVE / MISMATCH. **INCONCLUSIVE is
   not a warning**: it is expected when much of the frame is masked or sample signal is weak
   (typical on WAXS), and a measured `(0,0)` means the correlation locked onto detector-fixed
   structure, not that the detector didn't move. Act only on MISMATCH, re-running with
   `--shift-x/--shift-y`. A new detector needs a registry entry (`size`, `mask`, `shifts`).

6. **A purely vertical move fills only horizontal gaps.** Vertical module gaps need a third
   position with a horizontal offset: `--positions pos1,pos2,pos3 --shift-x N`.

Repeat measurements (same sample/x/th/exposure collected twice) are paired in sequence order,
i-th `pos1` with i-th `pos2`, never merged.

## Detector-agnostic geometry calibration (SAXS & WAXS)

This is the procedure for finding **beam center (x0,y0)** and **sample-detector distance
(SDD)** on ANY 11BM-CMS frame, with no human in the loop. It must work for SAXS (Pilatus2M,
direct beam usually available) AND WAXS (Pilatus800k, beam center varies per experiment, no
direct beam). Use the reusable helpers `fit_beam_center_rings` and `refine_sdd_from_rings`
(both built on the shared `find_rings` detector) in `calibration_helpers.py` rather than
re-deriving the logic.

### 11BM-CMS geometry priors (use to seed and to bound searches)

| Detector | Typical SDD | Beam center | Direct beam? |
|---|---|---|---|
| **SAXS** (Pilatus2M) | **~2 m, ~3 m, or ~5 m** — and **add +0.2 m for each "open area" offset** (e.g. 5 m open-area ≈ 5.2 m). Pick the nearest prior to the config/filename hint. | fairly stable; a direct-beam tiff usually exists | **usually YES** |
| **WAXS** (Pilatus800k) | **~0.20–0.26 m** (short) | **varies a lot per experiment** — never assume last run's value | **almost never** |

**Calibrants (11BM-CMS uses AgBH or CeO2, mostly AgBH):**
- **AgBH** (silver behenate) — DEFAULT. First-order ring `q1 = 0.1076 Å⁻¹` (d = 58.38 Å);
  harmonics at `n·q1`. Pass `AgBH=True, q0=0.1076` to `calibration_check`.
- **CeO2** (cerium oxide) — alternative. Strongest ring is (111) at `q ≈ 2.011 Å⁻¹`
  (a = 5.411 Å, d111 = 3.124 Å); further rings (200) q≈2.322, (220) q≈3.284, (311) q≈3.852.
  Pass `CeO2=True` to `calibration_check`.

### The three knobs are INDEPENDENT — solve them separately

1. **Beam center = pure pixel geometry.** It does not depend on SDD or wavelength. Solve it
   from the image alone.
2. **SDD = a uniform radial q-scale.** For small angles `q ∝ 1/SDD`, so changing SDD just
   rescales the whole q-axis. Solve it by matching ring q-positions, with the center fixed.
3. **The low-q reach of the circular average is SET BY the center**, not by SDD. A wrong
   center (or one near the masked beamstop) makes `qmin` rise and can hide the inner rings.

Never try to fix all three at once; you will chase your tail.

### Procedure

**Step 0 — Mask + energy.** Geometry-matched detector mask for the detector in use (gaps +
CMS badpixels; e.g. `Pilatus2M_gaps-mask.png` for SAXS, `Pilatus800k_gaps-mask.png` +
`NSLSII_11BM_CMS/Pilatus800k_CMS_badpixels-mask.png` for WAXS). **No rough-background** for
ring/calibrant data (it masks the rings). Energy from config (default 13.5 keV → λ=0.9184 Å).

**Step 1 — Beam center (branch on data type):**
- **SAXS with a direct-beam tiff** → `estimate_direct_beam_center(direct_beam_tiff)`
  (robust centroid). Optionally confirm with `fit_beam_center_rings`.
- **WAXS / no direct beam** → `fit_beam_center_rings(tiff, mask, exclude_quadrant=...)`:
  fits CIRCLES to the scattering arcs — a centre-free gradient-intersection bootstrap, then an
  independent Kåsa circle fit per ring. Returns `x0, y0` plus `x0_grad, y0_grad`, `agree_px`,
  and the per-ring list. **The check is that the ring centres AGREE** (`agree_px` ≤ ~1 px) across
  a bright ring and a wide ring, and with the gradient estimate — that is what makes it a real
  measurement, not a guess. **Do NOT use intensity-sharpness / radial-prominence proxies, a single
  ring, or an SDD scan to find the center** — they are nearly degenerate with the centre and give
  flat score maps and corner solutions. The centre is geometry; fit circles to the arcs.

**Step 2 — SDD (center fixed):** `refine_sdd_from_rings(tiff, mask, center, sdd_prior,
calibrant)` — the N-RING DISAMBIGUATION method. It detects the rings (`find_rings`), then tries
each bright ring as each plausible low calibrant order; each hypothesis fixes an SDD exactly, and
it keeps the SDD where the MOST detected rings simultaneously land on integer orders. `sdd_prior`
only brackets the search (WAXS ~0.25 m; SAXS the nearest of 2/3/5 m +0.2 m·offset) — it does not
supply the answer. The result is trustworthy only when **several rings agree on one SDD**, ideally
a contiguous run (n4,n5,n6,…): check `n_agree` (≥3–5) and `rms_pct` (<~0.5%). A single-ring or
non-contiguous "match" is a coincidence. (`scan_sdd_vs_calibrant` is the legacy coarse-grid
fallback; it can lock onto a one-ring false minimum, which is exactly the degeneracy this method
breaks.)

**Step 3 — Verify at the final geometry.** Run `circular_average`, `q_image` (or `qr_image` for
GI), and the `calibration_check` overlay, plus the narrow-window peak fits. Confirm the ideal
calibrant rings sit on the data arcs (the overlay) AND that measured ring q matches expected
(`n·q1` for AgBH) to a few tenths of a percent (the fit). The per-frame outputs — including
`calibration_check/` — land at the top level of `ana_out_<detector>/`; the SDD-scan by-products
and per-setting peak fits go under `calibration_log/`. Persist the final (x0, y0, SDD) in metadata.

### Gotchas that cost real time (bake these in)

- **`fit_calibration` is distance-only and can `ValueError`** on short/occluded WAXS frames
  (see rule 1). It NEVER moves the center. Don't build conclusions on its center output.
- **A reused `Calibration` object caches its q-map.** `set_beam_position(...)` /
  `set_distance(...)` on an existing object do NOT recompute the q-array within one process, so
  a geometry sweep that mutates one object in place produces identical circular averages. **Use
  a FRESH `Calibration` (+ `ProcessorXS`) per geometry** when sweeping. (The `scan_sdd_*` helper
  already does this.) This is the one place the "instantiate ProcessorXS once" rule is
  intentionally relaxed — it applies to per-file daemon loops, not to a deliberate offline
  geometry scan.
- **On a small WAXS detector the inner calibrant orders sit behind the beamstop**, so the
  visible rings may be HIGHER harmonics (e.g. AgBH `n=4,5,6`, not `n=1,2`). This is exactly the
  ambiguity `refine_sdd_from_rings` resolves — it does not assume the first visible ring is n=1;
  it finds the order assignment (and SDD) that makes the most rings consistent. Don't hand-assign
  q1 to the innermost visible ring.
- **Trust the overlay AND the numbers.** The `calibration_check` overlay is the human
  acceptance test (rings on arcs); the circular-average ring %-error is the quantitative one.
  Report both.


## Required Script Shape

Follow [runXS.py](runXS.py) and the approved workflow patterns in [reference.md](reference.md).

## Self-Check (mechanical)

Mechanical checks performed before finishing. Judgment-level checks (one-off vs daemon choice, scope discipline) live in the agent's Final Verification Checklist.

- `ProcessorXS` is instantiated once at module level
- protocols are used instead of reimplemented logic
- `TRIGGER.txt` is parsed with pipe separators
- `TRIGGER.txt` is deleted after reading
- `ANA_DONE.txt` is written each cycle
- `ana_log.csv` uses the expected columns (seq first)
- the script exits on `GPCAM_STOP.txt`
- no subprocess calls are made to op-cog or gpcam-cog
- all protocols used exist in `reference.md`
