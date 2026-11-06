# SciAnalysis Protocol Reference

This document describes all analysis protocols available in SciAnalysis, their parameters, and usage patterns.

---

## Architecture

All protocols inherit from the `Protocol` base class defined in `SciAnalysis/tools.py`.

### Base Class: `Protocol`

**Shared constructor parameters (all protocols accept these):**

| Parameter | Default | Description |
|---|---|---|
| `name` | class name | Human-readable name for the protocol |
| `default_ext` | varies | File extension for output files |
| `run_args` | `{}` | Default parameters merged with per-call kwargs |

**Common `run()` call-time parameters (shared across most protocols):**

| Parameter | Default | Description |
|---|---|---|
| `verbosity` | `3` | Output detail level (0=silent, 5=very verbose) |
| `save_results` | `['plots']` | Output types: `'plots'`, `'txt'`, `'hdf5'`, `'npz'`, `'pkl'`, `'xml'`. **Skill default: `['xml', 'plots', 'txt']`** (set in `run_args`). hdf5 omitted — the 11BM-CMS SciAnalysis build's hdf5 writer errors; xml/plots/txt only. |
| `file_extension` | varies | Override the output file extension |
| `label_filename` | `False` | Use data filename as the plot title |

**Utility methods available to all protocols:**
- `get_outfile()` — constructs output file path
- `output_exists()` — checks if output already exists (for skipping)
- `save_DataLine_HDF5()` — saves 1D curve data to HDF5
- `save_Data2D_HDF5()` — saves 2D image data to HDF5
- `label_filename()` — generates a filename label for plots

---

### Plot-styling parameters (cross-protocol)

These styling parameters are passed through `run_args` (globally, on `ProcessorXS`) or
per-protocol in the `protocols = [...]` list. The parameter names below are the canonical
ones used in the SciAnalysis runtime template (`runXS.py`). Use these names verbatim — do not
invent variants (`cbar`, `cmap_colorbar`,
`grid`, etc. are NOT valid).

| Parameter | Applies to | Default | Description |
|---|---|---|---|
| `rcParams` | base `Protocol.run()` (all protocols) | *(matplotlib defaults)* | Dict of matplotlib `rcParams` applied to the plot (e.g. `axes.labelsize`, `xtick.labelsize`, `ytick.labelsize`, `xtick.major.pad`, `ytick.major.pad`). Also accepts `axes.grid` (`True`/`False`) as the rcParams-level gridline control. |
| `transparent` | 2D image protocols (`q_image`, `qr_image`, `q_image_special`, …) | *(backend default, often transparent)* | `False` = opaque (white) figure background; `True` = transparent PNG background. |
| `colorbar` | 2D image protocols | `False` | `True` = draw an intensity colorbar beside the 2D map. |
| `plot_buffers` | 2D image protocols | *(protocol default)* | `[left, right, bottom, top]` axis margins (figure fraction). Use `[0.2, 0.1, 0.2, 0.1]` to make room for a colorbar. |
| `gridlines` | 1D curve protocols (`circular_average`, `linecut_q`, …) | `False` | `True` = overlay gridlines on the 1D plot. |
| `ylog` | 1D curve protocols (`circular_average`, `fit_FormFactor_Sphere`, …) | `False` | `True` = log scale on the y-axis. **Skill default `True` for `circular_average` everywhere** (general 1D default, not calibration-scoped). |
| `save_data` | 2D image protocols | *(protocol default)* | `False` = skip writing the auxiliary remeshed-data file (plot only). |

The table above defines what each parameter *is*. The VALUES we default to (canonical
`run_args`, 2D/1D plotting defaults) live in `SKILL.md` → *Canonical ProcessorXS
Construction* — set there, not here.

---

## Module: `SciAnalysis/XSAnalysis/Protocols.py`

Protocols for 2D x-ray scattering data (`Data2DScattering`).

---

### Processors (data loaders + dispatch)

Processors are NOT protocols; they are the runner objects that load TIFFs through a `Calibration` + `Mask` and dispatch a list of protocols at each file. Always instantiate exactly **one** processor at module level.

#### `ProcessorXS`

Standard processor for TIFFs on disk.

```python
import os
OUTPUT_DIR = os.path.join(os.environ['RUN_DIR'], 'ana_out')  # all analysis output products go here
os.makedirs(OUTPUT_DIR, exist_ok=True)

process = Protocols.ProcessorXS(load_args={'calibration': cal, 'mask': mask},
                                run_args={'verbosity': 3})
process.run(infiles, protocols, output_dir=OUTPUT_DIR, force=True)
# process.monitor_loop(source_dir='../raw/', pattern='*.tif',
#                      protocols=protocols, output_dir=OUTPUT_DIR, force=False)
```

| Constructor arg | Default | Description |
|---|---|---|
| `load_args` | `{}` | Merged into `data.load(**load_args)` — typically `{'calibration', 'mask'}` |
| `run_args` | `{}` | Default kwargs merged into every protocol's `run()` |

#### `ProcessorBS`

Extends `ProcessorXS`. Loads detector frames from a Bluesky **databroker** scan instead of TIFFs on disk. Used together with the `databroker_extract` protocol.

| Method | Description |
|---|---|
| `get_detector_image(recent_days=None, verbosity=3, **constraints)` | Pulls a 2D image (`pilatus2M_image`) from a databroker scan matching `**constraints` (e.g. `uid=...`) |

---

### `HDF5`

Saves the raw detector image to an HDF5 file.

| Parameter | Default | Description |
|---|---|---|
| *(none beyond base)* | | Relies on `save_results` containing `'hdf5'` |

---

### `thumbnails`

Renders a quick-view thumbnail JPEG of the 2D scattering image.

| Parameter | Default | Description |
|---|---|---|
| `crop` | `None` | Fraction of image to crop; `None` = no crop |
| `shift_crop_up` | `0.0` | Shift the crop window upward by this fraction |
| `make_square` | `False` | Force the crop to be square |
| `blur` | `2.0` | Gaussian blur sigma in pixels; `None` skips |
| `resize` | `0.2` | Scale factor (e.g. `0.2` = 20% of original) |
| `ztrim` | `[0.05, 0.005]` | Fraction of intensity values to trim at low/high end |
| `preserve_data` | `True` | Deep-copy data before modifying so downstream protocols see original |

---

### `circular_average`

Computes a 1D circular-average I(q) curve from a 2D scattering pattern. Saves plot and/or ASCII data.

| Parameter | Default | Description |
|---|---|---|
| `bins_relative` | `1.0` | Bin density relative to default (e.g. `2.0` = twice as many bins) |
| `markersize` | `0` | Marker size in the output plot |
| `linewidth` | `1.5` | Line width in the output plot |
| `trim_range` | *(not set)* | `[q_min, q_max]` to trim the output curve |
| `twotheta` | *(not set)* | If `True`, convert q-axis to 2θ (degrees) |
| `dezing` | *(not set)* | If `True`, dezinger the data before averaging |
| `ylog` | `False` | If `True`, use a log scale on the y-axis. **Skill default: `True`** for `circular_average` everywhere (general 1D default, not calibration-scoped — see Plot-styling parameters). |
| `gridlines` | `False` | If `True`, overlay gridlines. **Skill default: `True`** (see Plot-styling parameters). |

---

### `circular_average_sum`

Extends `circular_average`. Computes circular average and also integrates intensity over a specified q range.

| Parameter | Default | Description |
|---|---|---|
| *(all from `circular_average`)* | | |
| `sum_range` | *(required)* | `[q_start, q_end]` range over which to sum intensity |

---

### `circular_average_q2I`

Computes I(q) then multiplies by q^n (Kratky-style plot). Useful for identifying structural length scales.

| Parameter | Default | Description |
|---|---|---|
| `bins_relative` | `1.0` | Bin density relative to default |
| `markersize` | `0` | Marker size in plot |
| `linewidth` | `1.5` | Line width in plot |
| `qn_power` | `2.0` | Exponent n, so the y-axis is q^n × I(q) |
| `num_curves` | `1` | Number of Gaussian peaks for optional fitting |
| `trim_range` | *(not set)* | `[q_min, q_max]` to trim |

---

### `fit_peaks`

**Mixin / fit helper.** Not used directly in a `protocols = [...]` list. Provides `_fit_peaks` (multi-Gaussian + linear + power-law-background lmfit fit) and `_fit` (wraps the fit and produces the annotated `DataLines` plot with χ², q, d₀, σ, ξ for each peak). Other protocols mix it in via multiple inheritance to add Gaussian peak fitting to a binner:

- `circular_average_q2I_fit(circular_average_q2I, fit_peaks)` — Kratky I(q) + peak fit
- `sector_average_fit(sector_average, fit_peaks)` — sector wedge I(q) + peak fit
- `linecut_qr_fit(linecut_qr, fit_peaks)` — qr linecut + peak fit

**Multi-parent subclassing pattern (canonical):** to build a custom protocol that does a sector / linecut bin AND fits in one shot, subclass **both** the binner and `fit_peaks` (this is how the built-in `_fit` classes are constructed):

```python
class my_sector_fit(Protocols.sector_average, Protocols.fit_peaks):
    def __init__(self, name='my_sector_fit', **kwargs):
        self.name = name
        self.default_ext = '.png'
        self.run_args = {'qn_power': 3.5, 'num_curves': 1}
        self.run_args.update(kwargs)

    @tools.run_default
    def run(self, data, output_dir, **run_args):
        results = {}
        line = data.sector_average_q_bin(**run_args)
        # ...optional Kratky scaling, trim, save .dat...
        lines = self._fit(line, results, **run_args)   # populates results in-place
        lines.plot(save=self.get_outfile(data.name, output_dir), **run_args)
        return results
```

**Fit-time `run_args` consumed by `_fit_peaks`:**

| Parameter | Default | Description |
|---|---|---|
| `num_curves` | `1` | Number of Gaussian peaks to fit |
| `q0` | auto from max | Peak position seed; scalar or list-of-q for multi-peak |
| `sigma` | `0.1 × x_span` | Initial peak width guess |
| `fit_range` | *(not set)* | `[x_start, x_end]` sub-range used for the fit |
| `instrumental_resolution` | *(not set)* | Subtracted in quadrature from σ when computing grain size ξ |
| `show_curves` | `False` | Overlay individual Gaussian components in the plot (when `num_curves > 1`) |

**Result keys written by `_fit` into the protocol's `results` dict** (per peak `i` ∈ `1..num_curves`):

| Key | Value |
|---|---|
| `fit_peaks_prefactor{i}` | `{value, error}` — Gaussian amplitude |
| `fit_peaks_x_center{i}` | `{value, error}` — peak position q |
| `fit_peaks_sigma{i}` | `{value, error}` — peak width σ |
| `fit_peaks_d0{i}` | `{value, error}` — d-spacing in nm (`0.1 · 2π / q`) |
| `fit_peaks_grain_size{i}` | `{value, error}` — grain size ξ in nm |
| `fit_peaks_m`, `fit_peaks_b` | `{value, error}` — linear-bg slope and intercept |
| `fit_peaks_qp`, `fit_peaks_qalpha` | `{value, error}` — power-law-bg prefactor and exponent (off by default) |
| `fit_peaks_prefactor_total` | scalar — Σ \|prefactor\| |
| `fit_peaks_chi_squared` | scalar — `lm_result.chisqr / lm_result.nfree` |
| `fit_peaks_d0`, `fit_peaks_grain_size` | aliases for `_d01`, `_grain_size1` |

**Fit staging inside `_fit_peaks` (do NOT replicate by hand — it's done for you):**
1. all params frozen except `sigma1` → fit
2. freeze `sigma1`, vary `x_center1` → fit
3. relax `m`, `b`, all peaks' `prefactor/sigma/x_center` → final fit

---

### `circular_average_q2I_fit`

Extends `circular_average_q2I` **and** `fit_peaks` (multiple inheritance). Computes q^n·I(q) and fits Gaussian peaks. Combines Kratky analysis and peak fitting in one step.

Accepts all parameters from `circular_average_q2I` plus the following peak fitting parameters:

| Parameter | Default | Description |
|---|---|---|
| `num_curves` | `1` | Number of Gaussian peaks to fit |
| `q0` | auto-detected | Peak position hint(s); can be scalar or list |
| `sigma` | `0.1 × x_span` | Initial peak width guess |
| `fit_range` | *(not set)* | `[x_start, x_end]` sub-range to fit |
| `instrumental_resolution` | *(not set)* | Subtracted in quadrature from sigma when computing grain size |
| `show_curves` | *(not set)* | Show individual component curves in plot |

---

### `fit_FormFactor_Sphere`

Fits a 1D circular-average curve to a polydisperse sphere form factor model using `lmfit`. Loads input data from a prior `circular_average` run.

| Parameter | Default | Description |
|---|---|---|
| `load_from` | `'circular_average'` | Sub-directory from which to load the `.dat` file |
| `markersize` | `0` | Plot marker size |
| `linewidth` | `1.5` | Plot line width |
| `ylog` | `True` | Use log scale on y-axis |
| `initial_guess` | *(required)* | Dict of `{param_name: value}` for the fit |
| `limits` | *(required)* | Dict of `{param_name: [min, max]}` for fit bounds |
| `trim_range` | *(not set)* | `[q_min, q_max]` to trim data |
| `save_fit` | *(not set)* | If `True`, save fit curve as `.dat` file |

**Model parameters (inside `initial_guess` / `limits`):**

| Model Parameter | Description |
|---|---|
| `radius` | Sphere radius (Å) |
| `sigma` | Polydispersity (fraction of radius) |
| `delta_rho` | Scattering length density contrast |
| `qpower_scale` | Power-law background prefactor |
| `qpower` | Power-law background exponent |
| `background` | Flat background offset |

---

### `sector_average`

Computes I(q) by averaging only within an angular sector of the 2D pattern.

| Parameter | Default | Description |
|---|---|---|
| `bins_relative` | `1.0` | Bin density |
| `markersize` | `0` | Plot marker size |
| `linewidth` | `1.5` | Plot line width |
| `show_region` | `False` | Show the integration region; `'save'` saves it |
| `dezing` | *(not set)* | Dezinger before averaging |
| `angle_min` | *(required)* | Minimum angle of the sector (degrees) |
| `angle_max` | *(required)* | Maximum angle of the sector (degrees) |
| `angle_center` | *(required)* | Center angle of the sector (degrees) |
| `angle_spread` | *(required)* | Half-width of the sector (degrees) |

---

### `sector_average_qr`

Same as `sector_average` but in the qr/qz coordinate system (for grazing-incidence geometry).

*(Same parameters as `sector_average`.)*

---

### `peak_feature`

Same sector-average extraction but specifically for tracking peak features.

*(Same parameters as `sector_average`.)*

---

### `sector_average_fit`

Extends `sector_average` **and** `fit_peaks` (multiple inheritance). Sector average followed by Gaussian peak fitting via `fit_peaks._fit_peaks` / `_fit`.

| Parameter | Default | Description |
|---|---|---|
| *(all from `sector_average`)* | | |
| `error` | `False` | Show error bars in plot |
| `qn_power` | `None` | If set, multiply by q^n before fitting |
| `num_curves` | `1` | Number of Gaussian peaks to fit |
| `q0` | auto-detected | Peak position hint(s) |
| `sigma` | `0.1 × x_span` | Initial peak width guess |
| `fit_range` | *(not set)* | `[x_start, x_end]` sub-range to fit |

---

### `roi`

Computes statistics (sum, mean, etc.) for a region-of-interest (ROI) in q-space. Saves results to a text file.

| Parameter | Default | Description |
|---|---|---|
| `extra` | `''` | Extra string appended to output filename |
| `show_region` | *(not set)* | If `True`/`'save'`, show/save the ROI region on the image |
| `q_min` | *(required)* | Minimum q bound of the ROI |
| `q_max` | *(required)* | Maximum q bound of the ROI |
| `chi_min` | *(required)* | Minimum chi (angle) bound of the ROI |
| `chi_max` | *(required)* | Maximum chi (angle) bound of the ROI |

---

### `linecut_angle`

Extracts a 1D curve of I(χ) (azimuthal angle) at a fixed q. Useful for measuring orientation.

| Parameter | Default | Description |
|---|---|---|
| `show_region` | `False` | Show/save the integration region |
| `plot_range` | `[-180, 180, 0, None]` | Axis limits `[xmin, xmax, ymin, ymax]` for the plot |
| `markersize` | `0` | Marker size |
| `linewidth` | `1.5` | Line width |
| `q0` | *(required)* | Center q for the linecut |
| `dq` | *(required)* | Half-width in q |
| `smooth` | *(not set)* | Smooth the result by this many bins |
| `polarization_correction` | *(not set)* | If `True`, apply polarization correction |

---

### `linecut_angle_graininess`

Extends `linecut_angle`. Azimuthal linecut with grain-number analysis. Quantifies the number of crystalline grains contributing to a scattering ring.

| Parameter | Default | Description |
|---|---|---|
| *(all from `linecut_angle`)* | | |
| `ztrim` | `[0.1, 0.01]` | Intensity trim for the reference image |
| `smooth` | `0.25` | Smoothing as a fraction of sigma_chi |
| `multiplicity` | `6` | Symmetry multiplicity of the ring (e.g. 6 for hex) |
| `scattering_volume` | `None` | If set, compute grain density (mm⁻³) and physical grain size |
| `sigma_q` | *(auto)* | Peak width in q; auto-loaded from prior `circular_average_q2I_fit` results |
| `background` | *(auto)* | Background level; auto-loaded from prior `circular_average_q2I_fit` results |

---

### `linecut_qr`

Extracts a 1D linecut along qr (in-plane momentum transfer) for GISAXS geometry.

| Parameter | Default | Description |
|---|---|---|
| `show_region` | `False` | Show/save the integration region |
| `plot_range` | `[None, None, 0, None]` | Axis limits |
| `qz_min` | *(required)* | Minimum qz defining the horizontal slice |
| `qz_max` | *(required)* | Maximum qz defining the horizontal slice |

---

### `linecut_qx`

Extends `linecut_qr`. Same as `linecut_qr` but labeled as a qx linecut in corrected space.

*(Same parameters as `linecut_qr`.)*

---

### `linecut_qz`

Extracts a 1D linecut along qz (out-of-plane momentum transfer) for GISAXS geometry.

| Parameter | Default | Description |
|---|---|---|
| `show_region` | `False` | Show/save the integration region |
| `plot_range` | `[None, None, 0, None]` | Axis limits |
| `qr` | *(required)* | Center qr for the vertical slice (or use `qr_min`/`qr_max`) |
| `qr_min` | *(required)* | Minimum qr for the slice |
| `qr_max` | *(required)* | Maximum qr for the slice |

---

### `linecut_q`

Extracts a 1D linecut along a specified direction in q-space.

| Parameter | Default | Description |
|---|---|---|
| `show_region` | `False` | Show/save the integration region |
| `plot_range` | `[None, None, 0, None]` | Axis limits |

---

### `linecut_qr_fit`

Extends `linecut_qr` **and** `fit_peaks` (multiple inheritance). qr linecut followed by Gaussian peak fitting via `fit_peaks._fit_peaks` / `_fit`.

| Parameter | Default | Description |
|---|---|---|
| *(all from `linecut_qr`)* | | |
| `num_curves` | `1` | Number of peaks to fit |
| `trim_range` | *(not set)* | Trim before fitting |
| `q0` | auto-detected | Peak position hint(s) |
| `sigma` | `0.1 × x_span` | Initial peak width guess |

---

### `linecut_qz_fit`

Extends `linecut_qz`. qz linecut followed by Gaussian peak fitting, including refraction correction for GISAXS.

| Parameter | Default | Description |
|---|---|---|
| *(all from `linecut_qz`)* | | |
| `show_guides` | `True` | Overlay feature positions (direct, horizon, specular, Yoneda) |
| `incident_angle` | *(auto from filename)* | Extracted from filename if not provided |
| `critical_angle_film` | *(not set)* | Film critical angle (degrees); enables refraction-corrected q values |

---

### `linecut_angle_fit`

Extends `linecut_angle`. Azimuthal linecut followed by orientation analysis: fits η-function and Maier-Saupe distribution, computes FWHM and orientation factor.

| Parameter | Default | Description |
|---|---|---|
| *(all from `linecut_angle`)* | | |
| `plot_range` | `[-90, 90, None, None]` | Axis limits |
| `do_max` | `True` | Compute and mark the maximum position and FWHM |
| `do_fits` | `True` | Fit η and Maier-Saupe orientation distributions |
| `between_convention` | `False` | If `True`, use "between-peak" angle convention |

---

### `calibration_check`

Overlays calibration rings from known standard materials onto the 2D scattering image. Saves a plot for visual inspection.

| Parameter | Default | Description |
|---|---|---|
| `dq` | `0.01` | Fractional ring width (ring width = q × dq) |
| `AgBH` | *(not set)* | If `True`, overlay silver behenate rings |
| `CeO2` | *(not set)* | If `True`, overlay cerium oxide rings |
| `q0` | *(not set)* | Custom first-order ring position |
| `num_rings` | `5` | Number of harmonic rings to overlay when using `q0` |
| `resize` | *(not set)* | Resize image before plotting |

---

### `fit_calibration`

Fits the beam-center position and sample-to-detector distance by minimizing the width of a calibrant ring.

| Parameter | Default | Description |
|---|---|---|
| `material` | `'AgBH01'` | Calibrant material (`'AgBH01'` = silver behenate) |

---

### `q_image`

Re-meshes the 2D detector image into (qx, qz) or (qy, qz) coordinates and saves a calibrated scattering map.

| Parameter | Default | Description |
|---|---|---|
| `blur` | `None` | Gaussian blur before remeshing |
| `ztrim` | `[0.05, 0.005]` | Intensity trim for auto-scaling |
| `method` | `'nearest'` | Interpolation method for remeshing |
| `q_max` | *(not set)* | If set, restricts plot to `[-q_max, +q_max]` in both axes |
| `transparent` | *(backend default)* | Figure background. **Skill default: `False`** (opaque). |
| `colorbar` | `False` | Draw intensity colorbar. **Skill default: `True`**. |
| `plot_buffers` | *(protocol default)* | `[left, right, bottom, top]` margins; use `[0.2, 0.1, 0.2, 0.1]` with a colorbar. |

---

### `qr_image`

Extends `q_image`. Remeshes into (qr, qz) coordinates (in-plane vs. out-of-plane) for GISAXS.

| Parameter | Default | Description |
|---|---|---|
| *(all from `q_image`)* | | |
| `dezing_fill` | *(not set)* | Fill dezingered pixels before remeshing |

---

### `q_image_special`

Extends `q_image`. Same as `q_image` but applies the detector mask during remeshing and adds visual markers for horizon, specular, Yoneda, and transmitted-beam positions.

| Parameter | Default | Description |
|---|---|---|
| *(all from `q_image`)* | | |
| `incident_angle` | *(auto from filename)* | Sample tilt angle (degrees) |
| `critical_angle` | *(required)* | Film critical angle (degrees) for Yoneda position |

---

### `q_phi_image`

Remeshes the 2D scattering data into (q, φ) polar coordinates where φ is the azimuthal angle. Useful for studying orientation.

| Parameter | Default | Description |
|---|---|---|
| `blur` | `None` | Gaussian blur before remeshing |
| `bins_relative` | `0.5` | Radial bin density relative to default |
| `bins_phi` | `360.0` | Number of azimuthal bins |
| `ztrim` | `[0.05, 0.005]` | Intensity trim |
| `method` | `'nearest'` | Interpolation method |
| `yticks` | `[-180,-90,0,90,180]` | Tick positions on φ axis |
| `save_data_pickle` | `True` | Save q-data as `.pkl` |
| `q_max` | *(not set)* | If set, restricts q range |

---

### `export_STL`

Converts a 2D scattering image into an STL file for 3D printing, treating intensity values as height.

| Parameter | Default | Description |
|---|---|---|
| `crop` | `None` | Crop fraction |
| `shift_crop_up` | `0.0` | Shift crop window up |
| `blur` | `0.5` | Gaussian blur sigma |
| `resize` | `1.0` | Rescaling factor |
| `ztrim` | `[0.05, 0.005]` | Intensity trim |
| `stl_pedestal` | `75.0` | Minimum height of the base (3D-print units) |
| `stl_zscale` | `200.0` | Max height range above pedestal (3D-print units) |
| `crop_zone` | `None` | Manual crop `[xi, xf, yi, yf]` in pixels |
| `crop_beam` | `None` | Crop a `[width, height]` box around beam center |
| `crop_GI` | `None` | Crop a GISAXS-style half-box of width `w` below beam center |
| `logo_file` | `None` | Path to a PNG logo to embed into the base of the model |
| `logo_resize` | `1.0` | Resize factor for the logo |

---

### `metadata_extract`

Parses metadata from a filename using regex patterns and records file timestamps and sizes.

| Parameter | Default | Description |
|---|---|---|
| `patterns` | *(see below)* | List of `[name, regex]` pairs |

**Default extracted fields:** `theta`, `x_position`, `y_position`, `annealing_temperature`, `annealing_time`, `exposure_time`, `sequence_ID`.

---

### `databroker_extract`

Looks up a Bluesky databroker entry matching the current file and extracts metadata.

| Parameter | Default | Description |
|---|---|---|
| `constraints` | `None` | Extra dict of metadata constraints for db search |
| `timestamp` | `True` | Narrow search by file timestamp |
| `timestamp_window` | `3600` | Window (seconds) around file timestamp to search |
| `recent_days` | `None` | Restrict search to the last N days |
| `section` | `'start'` | Which document section to pull metadata from |
