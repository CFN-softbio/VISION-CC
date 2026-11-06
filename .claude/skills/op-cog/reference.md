# Reference: 94-sample.py & 95-sample-custom.py

## Overview

These two files define the sample/stage object hierarchy for the CMS beamline control system (Bluesky/NSLS-II). `94-sample.py` provides the base infrastructure; `95-sample-custom.py` builds specialized sample and holder classes on top of it.

> **Provenance.** The "Basic sample functions" section below was verified against `94-sample.py` and `95-sample-custom.py`.
> This file is the list of calls op-cog may make. To confirm a listed method, read the local clone `vendor/profile_collection/` only (SKILL.md → "Profile source").
> Line numbers are for orientation only and may differ in the clone.
> The holder sections at the end were **not** re-verified (holders are out of scope for now).

---

## Basic sample functions (verified)

### Which object `sam` really is

- The live `sam` is created by the scientist's session. It may be a plain 94/95 class (`Sample_Generic`, `SampleTSAXS_Generic`, `SampleGISAXS_Generic`, …) **or a user-defined subclass from the user's own startup script**, which can add axes and change naming. Two facts show the run009 `sam` was such a subclass: it had a `yy` axis, and its frames were named `x2.500_y2.500_th0.000`. Neither comes from 94/95.
- **`Sample` is not defined in 94 or 95.** `Sample('<name>')` works only if the live session defines that name. Check that it exists before you construct with it.
- Learn the live object read-only, with no motion: `sam.pos(verbosity=0)` returns every axis it has, and the attribute `sam.naming_scheme` returns its naming tokens.

### Axes and motors (94 `Sample_Generic`, line 1692; `SampleStage`, line 4890)

| `sam` axis | Path to the motor | Units |
|---|---|---|
| `x` | no motor of its own → the base stage `stg` (`SampleStage`) axis `x` → `smx` | mm |
| `y` | no motor of its own → `stg.y` → `smy` | mm |
| `th` | `sth` directly | deg |

- Plain `Sample_Generic`/`SampleTSAXS_Generic`/`SampleGISAXS_Generic` have **only `x`, `y`, `th`**. In 94, `z`, `chi`, `phi` and `yy` are commented out. `SampleCDSAXS_Generic` adds `phi` (→ `srot`). A `yy` axis (→ `smy2`) exists only if the live session's own class adds it.
- The default base is `stg = SampleStage()` (94, line 5546).
- Coordinates are layered. Each axis has an `origin`, held in its base's coordinates: `sam.x = stg.x − sam.x.origin`, and `stg.x = smx − stg.x.origin`. For `th`: `sam.th = sth − sam.th.origin`. All scalings are +1.

### Per-axis methods (generated for every axis `<a>` by `CoordinateSystem._init_axes`, 94 line 282)

| Call | What it does | Motion? |
|---|---|---|
| `sam.<a>()`, `sam.<a>pos(verbosity=3)` | Read position in sample coordinates. Prints `"<name>.<a> = v units (origin = o)"` when verbosity ≥ 2. Returns a float. | no |
| `sam.<a>posMotor(verbosity=3)` | Read the raw motor position. | no |
| `sam.<a>abs(position=None, wait=True, verbosity=3)` | Absolute move in sample coordinates. Called with no argument, it is a read. | **yes** |
| `sam.<a>r(move_amount=None, verbosity=3)` | Relative move: target = **current readback** + amount. Called with no argument, it is a read. | **yes** |
| `sam.<a>o()` | Go to origin, i.e. `<a>abs(0)`. **This is motion, not a read.** | **yes** |
| `sam.<a>setOrigin(origin=None)` | Redefine the origin. No argument: the current position becomes 0. With a value: that position, in current coordinates, becomes 0. | no |
| `sam.<a>set(new_position)` | Redefine the current position's value by shifting the origin. | no |
| `sam.<a>units()`, `sam.<a>hint()`, `sam.<a>info()` | Read axis info. | no |
| `sam.<a>mark(label, position=None)` | Record a mark. | no |

**How `<a>abs` / `<a>r` settle (94 `Axis.move_absolute`, line 756):**
- It writes the motor setpoint directly (`motor.user_setpoint.value = …`). This is **not** a bluesky plan, so the RunEngine is not involved.
- For `x` and `y`, the move is passed down to `stg.xabs(…, verbosity=0)`, so the stage level does not wait.
- **It waits only when `verbosity >= 2` (the default is 3).** It polls the readback every 0.05 s until `|readback − target| ≤ 0.01` (mm or deg) **or 10 s have passed**. Then it returns.
- With `verbosity < 2` it **does not wait at all** and returns as soon as the setpoint is written.
- The `wait=` argument is accepted and **ignored**.
- It **never raises** if the motor does not arrive (limit, stall, IOC rejected the setpoint, still moving after 10 s). It just returns `None`. A move longer than ~10 s therefore returns with the motor still moving.
- After any move that matters, read the position back (`sam.<a>pos(verbosity=0)`) and compare it with the target yourself.
- If the axis is disabled, it prints `"Axis … disabled"` and does nothing.

### Whole-object position and origin methods (`CoordinateSystem`, 94 lines 452–646)

- `sam.pos(verbosity=3)`: read only. Returns a `dict` `{axis: position}` over all axes in sorted order. It prints each axis when verbosity ≥ 2. **`verbosity=` is accepted**; `verbosity=0` is silent.
- `sam.origin(verbosity=3)`: read only. Returns `{axis: origin}`, with origins in the base's coordinates. It prints when verbosity ≥ 2.
- `sam.gotoOrigin(axes=None)`: **motion**. It calls `<a>o()` (that is, `<a>abs(0)`, with the default verbosity, so it waits) on each axis **in turn**. `None` moves **all** axes. Pass a **list** (`['x','y']`): a string is iterated character by character, so `'th'` fails with `KeyError`.
- `sam.setOrigin(axes, positions=None)`: no motion. It calls `<a>setOrigin()` (or `<a>setOrigin(pos)`) for each axis in the list.
- `sam.save_state()`: read only. Returns `{"origin": {axis: origin}}`. It contains **origins only, not positions.** To snapshot a sample, record `sam.pos(verbosity=0)` **and** `sam.save_state()`.
- `sam.restore_state(state)`: no motion. It sets each axis origin from `state["origin"]`. Every axis of `sam` must be present, or it raises `KeyError`. It changes the coordinate frame only; to return to an old position, move afterwards.
- `sam.mark(label, *axes, **axes_positions)` / `sam.marks(verbosity=3)` / `sam.goto(label, verbosity=3, **additional)`: in-memory marks, lost when the session restarts. `goto` is **motion**. An unknown label prints a message and returns without raising.

### Name and naming scheme (94 lines 1561, 1929–2039)

- Constructor: `Sample_Generic(name, base=None, **md)`. `base` defaults to `stg`.
  - It sets `md` defaults `exposure_time=1.0`, `measurement_ID=1`, `SAXS_time=0.5`, `WAXS_time=2`, `MAXS_time=None`.
  - It creates `RE.md["userpy_alias_directory"]` if that is missing.
  - A new object has **all origins at 0**, so it drops any alignment held by the old `sam`.
- `sam.name` is a plain attribute. Setting it in place (`sam.name = '<name>'`) changes the `name` token of every later file and the metadata. Origins are kept. (`position_id` keeps the construction name; it is used only by 94's position-file helpers, which are not documented here.)
- **Default `naming_scheme`:**
  - `Sample_Generic` / `SampleTSAXS_Generic`: `["name", "extra", "exposure_time", "id"]`
  - `SampleGISAXS_Generic`: `["name", "extra", "th", "exposure_time"]`
  - `SampleCDSAXS_Generic`: `["name", "extra", "phi", "exposure_time"]`
  - Delimiter `"_"`.
  - **None of the 94/95 defaults encodes `x` or `y`.**
- `sam.naming(scheme=[...], delimeter="_")`: **setter.** Calling it with no arguments **resets** the scheme to the 94 default. It is not a read; read `sam.naming_scheme` instead.
- **How each token is formatted (`get_naming_string`):**
  - axis name → `<axis>` + signed value, 3 decimals: `x+2.500`, `th-0.100`. The **sign is always written.**
  - `exposure_time` → `1.00s`
  - `clock` → `12.3s`
  - `temperature*` → `T25.000C`
  - `id` → the integer `md['measurement_ID']`
  - `extra` → the `savename_extra` string. If it is `None`, the token is **skipped**.
  - `spot_number` → `spot3`
  - `energy` → `13.5kev`
  - `SAXSx/SAXSy/WAXSx/WAXSy/MAXSx/MAXSy` → `SAXSy+0.00`
  - any key in `sam.md` → `str(value)`
  - any unknown token → inserted as **literal text**
- `sam.get_savename(savename_extra=None)`: read only, no motion. It joins the tokens with the delimiter, replaces `' '`→`_` and `'/'`→`-slash-`, and returns the **stem** (no scan id, detector or extension).
  - **`extra` goes in the position of the `"extra"` token in the scheme** (second, by default).
  - Every token is evaluated **at call time**: axis positions, temperature, `clock`, `md['exposure_time']`, and `md['measurement_ID']`.
  - Side effect: it resets `md['savename_extra']` to `None`.

### Measuring

**`sam.measure(exposure_time=None, extra=None, measure_type="measure", verbosity=3, tiling=None, stitchback=False, **md)`** (94 line 3140)

- It **blocks** on the kernel's main thread: `RE(count(detectors))`. The shutter is opened before and closed after.
- It **returns `None`.**
- `tiling=None` takes one frame. `'ygaps'` / `'xygaps'` move the detectors over 2 / 4 tiles, append `_pos1…` to `extra`, and restore the detector positions afterwards. Any other value raises `ValueError`.
- **Pass `exposure_time` explicitly.** With `None`, the detector call is made with `None` and the time falls back to `md['SAXS_time'/'WAXS_time']`.
- A negative time prints `"Exposure time must be POSITIVE."` and takes no frame. It does not raise.
- With no detectors selected, it prints `ERROR` and returns.
- It increments `md['measurement_ID']` by 1 **after** the frame. It does not move the sample.
- **On-disk name (94 `handle_file_datasecurity`, line 2650):**
  - Format: `<RE.md["userpy_alias_directory"]>/<det>/raw/<get_savename(extra)>_<scan_id>_<det>.tiff`. This is a symlink to the detector's own file.
  - `<det>` is `saxs` (pilatus2m-1), `waxs` (pilatus800k-1), `maxs` (pilatus800k-2) or `waxs_temp` (pilatus300k-1).
  - The stem in the link is computed **after** the exposure, but **before** `measurement_ID` is incremented.
  - The scan id always makes the name unique. If the link already exists, `os.symlink` raises.
- **Consequence for op-side stems:** a `get_savename(savename_extra=extra)` call made *after* `measure` reproduces the on-disk stem **only if** the scheme has no `id` (it is one higher by then) and no `clock`, and no axis has moved since. Read `sam.naming_scheme` once before relying on that.

**`sam.snap(exposure_time=None, extra=None, measure_type="snap", verbosity=3, **md)`** (94 line 2872)
- A quick exposure through the same path, with `handlefile=False`.
- **No symlinked tiff is written** to the user directory, so `extra` does not reach a filename, and `measurement_ID` is not incremented.
- It blocks and returns `None`. Use it for alignment, not for data you need to analyse.

**`sam.measureSpots(num_spots, translation_amount, axis, exposure_time=None, extra=None, measure_type="measureSpots", **md)`** (94 line 3752; 95 override line 110)
- **Defaults differ by class:**
  - 94 `Sample_Generic` (and TSAXS): `num_spots=4, translation_amount=0.2, axis="y"`
  - 95 `SampleGISAXS_Generic`: `num_spots=2, translation_amount=0.1, axis="x"`
  - **Always pass all three.**
- For each spot it does three things: `measure(exposure_time, extra, …)`, then `sam.<axis>r(translation_amount)` (default verbosity, so it waits ≤ 10 s to within 0.01 and does not raise), then increments `md['spot_number']`.
- **It measures, then steps.** After `N` spots the axis is left at **start + N·translation_amount**, one step past the last spot. It does **not** return to the start.
- All spots share the same `extra`.
- Uniqueness of each frame comes from the scan id, and from `id` when the scheme has it. Position appears in the name **only if** the live `naming_scheme` contains the axis token. `spot_number` is set in `md` but is **not** in any default scheme; it also persists and keeps counting across calls.

**`sam.measureTimeSeries(exposure_time=None, num_frames=10, wait_time=None, extra=None, measure_type="measureTimeSeries", verbosity=3, tiling=None, fix_name=True, **md)`** (94 line 3775)
- It calls `measure` `num_frames` times, with `time.sleep(wait_time)` after each frame. It does not move the sample.
- With `fix_name=True` it inserts `"clock"` before the last token of `naming_scheme` and **never restores the scheme**. Later files keep the `clock` token.

---

## 94-sample.py: Base Infrastructure (overview)

### `CoordinateSystem` (line 229)
Base class for all stages and samples. Layered coordinate systems: each instance sits on a `base_stage`. Methods are documented under "Basic sample functions" above. It also has `gotoAlignedPosition()` and the generators `_mov(axes, positions)` / `_movr(axes, positions)` (bluesky `bps.movr`, used with `yield from`).

### `Axis` (line 648)
One motor axis within a `CoordinateSystem`. Handles origin offset and scaling. `search(...)` / `search_plan(...)` are iterative beam-finding scans, used by alignment.

### `Sample_Generic` (line 1551)
The main sample class. Its basic functions are above. Other methods (not re-verified for op use): `get_md`, `expose` (internal), `measure_single` (internal to `measure`), `measureRock`, `scan_measure` / `series_measure`, `handle_file` / `handle_fileseries`, `do`, `setTemperature` / `temperature`, `humidity`, `intMeasure`, `transmission_data_output`, `monitor_scheme` / `track_scheme`.

### `Stage` (line 4886) / `SampleStage` (line 4890)
Minimal `CoordinateSystem` subclasses. **`SampleStage` axes: `x`→`smx`, `y`→`smy`, `th`→`sth`.** The default stage is `stg = SampleStage()`.

### `Holder` / `PositionalHolder` (lines 4927 / 5383): not re-verified, out of scope
- `Holder`: `addSample`, `removeSample`, `getSample`, `getSamples`, `listSamples`, `gotoSample`, `doSamples`, `doTemperature(s)`, `setTemperature` / `temperature`.
- `PositionalHolder`: `slot`, `get_slot_position`, `addSampleSlot`, `addSampleSlotPosition`, `listSamplesPositions` / `listSamplesDetails`, `intMeasure`, `saveSampleStates(output_file)` / `restoreSampleStates(input_file)`, `checkPositions`.

---

## 95-sample-custom.py: Specialized Classes

All classes inherit from the base classes in `94-sample.py`.

### Sample Classes

| Class | Parent | Line | Purpose |
|---|---|---|---|
| `SampleTSAXS_Generic` | `Sample_Generic` | 31 | TSAXS/TWAXS transmission samples. Same axes and naming as `Sample_Generic`. |
| `SampleGISAXS_Generic` | `Sample_Generic` | 102 | GISAXS/GIWAXS. Naming `["name","extra","th","exposure_time"]`. Overrides the `measureSpots` defaults (2, 0.1, `"x"`). |
| `SampleCDSAXS_Generic` | `Sample_Generic` | 1043 | CD-SAXS. Adds `phi` (→ `srot`). Naming `["name","extra","phi","exposure_time"]`. |
| `SampleXR_WAXS` | `SampleGISAXS_Generic` | 1077 | X-ray reflectivity + WAXS |
| `SampleGonio_Generic` | `SampleGISAXS_Generic` | 1737 | SmarAct goniometer: **broken in this revision**, see below |
| `SampleSecondStage` | `SampleGISAXS_Generic` | 1778 | Second sample stage. Origins preset: x −1.9, y 18.97, th 0.348. |

**`SampleGISAXS_Generic` other methods (not re-verified for op use):** `measureIncidentAngle(angle, exposure_time, extra, tiling, **md)`, `measureIncidentAngles(angles, …)` (default angles `[0.08, 0.10, 0.12, 0.15, 0.20]`), `measureIncidentAngles_Stitch` (deprecated alias), `align`, `swing`, `search_plan`, `alignQuick`, `do`, `do_SAXS` / `do_WAXS`.

**`SampleXR_WAXS` key additions:** `XR_scan`, `XR_align`, `XR_check_alignment`, `th2thscan`.

**`SampleCDSAXS_Generic` key additions:**
- `phi` axis (→ `srot`, deg), with the full per-axis method set (`phiabs`, `phir`, `phipos`, `phio`, …).
- `rot_angles_default = np.arange(-45, 46, 1)`.
- `measureAngle(angle, exposure_time=None, extra=None, measure_type="measure", **md)`: `phiabs(angle)`, then `measure(...)`.
- `measureAngles(angles=None, exposure_time=None, extra=None, measure_type="measureAngles", **md)`: loops `measureAngle` over `angles`, or over `rot_angles_default` when none are given.

**`SampleGonio_Generic`:** its `_set_axes_definitions` *assigns* to `self._axes_definitions.append` instead of calling it. Python raises `AttributeError` on that line, so **this class cannot be constructed** in this revision, and its `phi` / `trans` / `trans2` axes do not exist. Its `__init__` would set the origins `x = −17.7`, `y = 9`.

> **Tomography note:** in this revision, rotational `phi` motion (via `srot`) is exposed only on `SampleCDSAXS_Generic`. Plain `Sample_Generic`, `SampleTSAXS_Generic` and `SampleGISAXS_Generic` define only `x, y, th`.

---

### Holder Classes (not re-verified; out of scope, line numbers from an older revision)

| Class | Parent | Purpose |
|---|---|---|
| `GIBar` | `PositionalHolder` | GISAXS/GIWAXS bar holder |
| `CapillaryHolder` | `PositionalHolder` | TSAXS capillary holder |
| `CapillaryHolderThreeRows` | `CapillaryHolder` | Three-row capillary variant |
| `CapillaryHolderHeated` | `CapillaryHolder` | Heated capillary holder |
| `GIBar_long_thermal` | `GIBar` | Thermal GI bar (long version) |
| `GIBar_Linkam` | `GIBar` | GI bar with Linkam N₂ dome |
| `WellPlateHolder` | `PositionalHolder` | Well-plate (row/column grid) |
| `PaloniThermalStage` | `CapillaryHolder` | Brass thermal stage (UCSB) |
| `DSCStage` | `CapillaryHolder` | DSC capsule transmission stage |
| `CapillaryHolderThermal` | `CapillaryHolder` | Generic thermal capillary holder |
| `GIBarSecondStage` | `GIBar` | GI bar on second stage |
| `HumidityStage` | `GIBar` | GI humidity stage |
| `HumidityTransmissionStage` | `CapillaryHolder` | Transmission humidity stage |
| `InstecStage60` | `CapillaryHolder` | Instec HCS 60 (Kent State) |
| `OffCenteredHoder` | `GIBar` | GTSAXS off-centered holder |

**`GIBar` key additions:**
- `addSampleSlotPosition(sample, slot, x, y, th, ...)`: slot positions include theta.
- `setMeasure(detector, incident_angles, exposure_time, tiling)`: configure the default measurement.
- `alignSamples(range, step, align_step, x_offset, ...)`: align all samples on the bar.
- `alignSamplesQuick(...)` / `alignSamplesVeryQuick(...)`: faster alignment sweeps.
- `measureSamples(range, angles, exposure_time, ...)`, `doSamples(range, ...)`, `doSamples_Stitch(...)`.

**`CapillaryHolder` key additions:** `get_slot_position(slot)` (pitch-based), `measure_Stitch(...)`, `measureSamples(...)`.

**`WellPlateHolder` key additions:** `slot(sample_number)`, `get_slot_position(slot)`, `namingWellPlate(name, row_range, column_range)`, `gotoAlignedPosition()`.
