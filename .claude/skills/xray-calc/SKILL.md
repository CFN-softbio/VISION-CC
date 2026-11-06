---
name: xray-calc
description: X-ray geometry and material calculations for 11BM-CMS — convert between q, d-spacing, 2-theta, energy and wavelength; find where a q lands on the detector, what sample-detector distance a target q needs, or whether a q is reachable at all; get grain/correlation length and microstrain from peak widths; and compute transmission, attenuation length, mass attenuation, absorption edges and fluorescence lines for elements and compounds via xraylib. Open this skill for questions like "what d-spacing is this peak", "what SDD do I need for q=0.05", "will q=X reach the detector", "which SAXS stop should I use", "what's the transmission through 200 um of kapton", "how thick can my sample be at 13.5 keV", "what's the grain size from this peak width", "where's the Cu K edge". Team-lead runs this DIRECTLY — do NOT spawn an agent for it.
---

# Skill: X-ray Calculations (geometry · material properties)

Deterministic X-ray arithmetic, offline. Two modules live beside this file:

| Module | Covers |
|---|---|
| `saxs_geometry.py` | q ↔ d ↔ 2θ ↔ λ ↔ E, detector position, SDD solving, detector-stop selection, grain size / microstrain from peak widths |
| `properties.py` | transmission, attenuation length, µ/ρ, absorption edges, fluorescence lines (xraylib; elements, ~180 named NIST materials, and arbitrary formulas) |

Both are stdlib-flat (no relative imports, no package). `properties.py` needs
`xraylib`, which is in the pixi env.

`verify.py` sits beside them and checks both against hand-verifiable references
(Bragg and SDD round-trips, Beer-Lambert self-consistency, textbook edge/line
energies, NIST-vs-formula agreement). Run it with **`pixi run check-xray`** after
any change to either module, or to confirm the env is sound on a new host.

---

## The one hard rule

**Never state an X-ray number you computed in your head.** Write a script, run
it, and quote only what appears in its stdout. This is the same rule as the
repo-wide "write scripts, never inline `python -c`" convention, and it exists
because a confidently-wrong `2π/q` is indistinguishable from a right one in a
report.

Put the script in the run's scratch dir — `$RUN_DIR/log/xray_<what>.py` — per the
CLAUDE.md rule that ad-hoc code never lands in the run root. Outside a run, use
any scratch path and say where you put it.

## Calling pattern

```python
#!/usr/bin/env python3
"""One-line statement of the question being answered."""
import json, sys

sys.path.insert(0, "/abs/path/to/.claude/skills/xray-calc")
import saxs_geometry as geo
import properties as props

# Per-run values come from config.json -- never hard-code, never guess.
cfg = json.load(open("/abs/path/to/runs/runNNN/config.json"))
E   = cfg["detector"]["energy_keV"]
SDD = cfg["detector"]["sdd_m"]

r = geo.saxs_geometry(q_A=0.21, energy_keV=E, sd_distance_m=SDD)
for k, v in r.items():
    print(f"{k:>22} = {v:.6g}" if isinstance(v, float) else f"{k:>22} = {v}")
```

Run it with the pixi prefix (`pixi run python …`), or the direct interpreter
fallback in `docs/terminal-launch.md` if `pixi run` is unavailable on the host.

## Per-run vs. beamline-invariant — read this before passing arguments

This is the source-of-truth rule that keeps the geometry consistent:

| Kind | Where it lives | How to use it |
|---|---|---|
| **Per-run** — energy in use, SDD actually selected, detector, mask | the run's `config.json` → `detector` block | **Read and pass explicitly.** Confirmed with the user at Step 0. |
| **Beamline-invariant** — which SDD stops physically exist, pixel pitch | `BEAMLINE_MODES` in `saxs_geometry.py` | Reference data. Use for "which stop?" questions only. |

`q_on_beamline()` will fall back to a nominal 13.5 keV if you don't pass
`energy_keV`. **Don't let it** when you're interpreting real data — pass the
run's actual energy. The fallback is for planning questions asked before a run
exists.

`config.json` does not currently carry a pixel size; the functions default to
172 µm (Pilatus). If a different detector is ever used, pass `det_pix_size_um`.

## Worked examples

**"What d-spacing is the peak at q = 0.21 Å⁻¹?"**
```python
r = geo.saxs_geometry(q_A=0.21, energy_keV=E, sd_distance_m=SDD)
# -> r["d_A"], r["d_nm"], r["two_theta_deg"], r["det_position_mm"]
```

**"What SDD do I need to see q = 0.008 Å⁻¹?"** — solve, then snap to a real stop:
```python
want = geo.sdd_for_q(q_A=0.008, energy_keV=E)      # ideal continuous SDD
opts = geo.q_on_beamline(q_A=0.008, energy_keV=E)  # where it lands at each real stop
# Recommend the nearest stop from opts["modes"]; quote opts["notes"] --
# the SAXS tube has ONLY 2 / 3 / 5.03 m, no intermediate positions.
```

**"Will q = 3.0 Å⁻¹ reach the detector?"** — `q_on_beamline` reports every mode;
if q exceeds the Ewald limit (4π/λ) the call raises a readable error naming the
maximum accessible q at that energy.

**"Transmission through 200 µm of kapton at 13.5 keV?"** — use the NIST name and
you don't need a density at all:
```python
props.transmission("Kapton Polyimide Film", energy_keV=13.5, thickness_um=200)
# -> value 0.9618, density_g_cm3 1.42, source "NIST 'Kapton Polyimide Film', density from NIST"
props.list_nist_compounds("mylar")   # search the ~180 named materials
```

**"Grain size from a Lorentzian width of 0.004 Å⁻¹?"**
```python
geo.grain_size_from_peak_width(q_Lwidth_A=0.004)   # -> nm
```

## Rules and gotchas

- **Materials resolve in three tiers** — prefer the highest one that applies:
  1. **Element symbol** (`"Au"`, `"Si"`) — density from xraylib.
  2. **NIST material name** (`"Kapton Polyimide Film"`, `"Water, Liquid"`) —
     density from NIST, ~180 available. `list_nist_compounds("<keyword>")` searches.
  3. **Chemical formula** (`"SiO2"`) — **density required**, because
     stoichiometry carries no packing information (graphite and diamond are both
     `"C"`). If the user hasn't given one and no NIST entry fits, **ask** — never
     invent it; a wrong density silently scales transmission and attenuation length.

  Every result carries a `source` field recording which tier and where the
  density came from. Quote it when the number matters.
- **Ambiguous NIST names raise, by design.** `"water"` matches both
  `"Water, Liquid"` (1.0 g/cm³) and `"Water Vapor"` (0.00076) — a ~1300× density
  difference. Use the full name.
- **Edges and fluorescence lines are elements-only.** Compounds raise.
- **`strain_from_peak_width` is UNVALIDATED.** Carried over from the source tool
  unchanged; the expression has not been checked against a reference case. It
  returns a `_warning` key. Do not put its output in a report without verifying
  it first, and say so if you use it.
- **Discrete SAXS stops.** `sdd_for_q` returns a continuous distance, which
  11BM's tube cannot do. Always cross-check with `q_on_beamline` and recommend a
  real stop.
- **Units.** q in Å⁻¹, energy in keV, SDD in m, pixel size in µm, thickness in
  µm, density in g/cm³. Every return dict carries units — quote them.
- The keV·Å constant is `KEV_ANGSTROM = 12.398419`, defined once in
  `saxs_geometry.py`. Don't re-derive it inline.

## Data sources & references

`properties.py` values come from **xraylib**, which compiles established
photon-interaction databases (EPDL97 / Scofield photoionization cross sections,
Bearden & Burr absorption-edge energies, Bearden emission-line energies, Hubbell
scattering data). The authoritative per-quantity mapping is in the xraylib
papers — cite these if a number reaches a publication:

- T. Schoonjans *et al.*, "The xraylib library for X-ray–matter interactions.
  Recent developments," *Spectrochim. Acta B* **66**(11–12), 776–784 (2011).
- A. Brunetti *et al.*, "A library for X-ray matter interaction cross sections
  for X-ray fluorescence applications," *Spectrochim. Acta B* **59**(10–11),
  1725–1731 (2004).

An independent tabulation of the same quantities is CXRO:

- B. L. Henke, E. M. Gullikson, J. C. Davis, "X-ray interactions:
  photoabsorption, scattering, transmission, and reflection at E = 50–30000 eV,
  Z = 1–92," *At. Data Nucl. Data Tables* **54**(2), 181–342 (1993).
  Web calculators: <https://henke.lbl.gov/optical_constants/>

Both are sound for hard-X-ray work and agree closely at 11BM energies. They can
differ **near absorption edges** — if a number matters there, check both and
state which you used.

`saxs_geometry.py` is elementary Bragg/Ewald geometry; no external data source.

## Relationship to other cogs

This skill is **team-lead-callable and stateless** — no daemon, no flag files,
no filename prefix, no place in the completion handshake. It does not spawn an
agent and is not part of the AE loop.

- **ana-cog** owns extracting the peak (`q0`, `width`) from data. This skill
  converts that number into physical quantities. Don't use it to do analysis.
- **op-cog** owns moving hardware. If a calculation implies a motor move
  (changing the detector stop), report the number — op-cog acts on it.
- A future interpretation cog would load this same skill rather than
  reimplementing the math.
