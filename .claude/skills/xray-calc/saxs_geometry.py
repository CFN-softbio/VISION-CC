"""SAXS/WAXS geometry calculations for the 11BM-CMS beamline.

Standalone: stdlib only, no relative imports. Drop the skill directory on
sys.path and `import saxs_geometry`.

Provenance: adapted for VISION from VISION_dev_fe/backend/src/xray/saxs_geometry.py,
whose math was in turn translated by hand from that repo's misc/saxs_calc.html.

Changes from the original:
  * The beamline_presets -> beamline_info -> xray_info.toml loader chain was
    replaced by the inline BEAMLINE_MODES dict below. VISION already carries
    per-run geometry in each run's config.json; a TOML would be a third source
    of truth. See "Per-run vs. beamline-invariant" in SKILL.md.
  * The keV*A conversion constant is hoisted to KEV_ANGSTROM and corrected from
    12.398 to 12.398419 (~34 ppm; results differ from the original tool in the
    5th significant figure).
  * asin() domain errors now raise a readable "q unreachable at this energy"
    message instead of a bare `ValueError: math domain error`.
  * saxs_geometry() also returns d_A alongside d_nm (avoids a hand conversion).

Conventions:
  - q in inverse angstrom (A^-1)
  - energies in keV
  - distances: sample-detector in metres, pixel size in micrometres,
    sample length in mm
  - every function returns a dict; scalar results use {"value", "units"}
"""

import math
from typing import Optional

PI = math.pi

#: h*c in keV*angstrom. E[keV] = KEV_ANGSTROM / lambda[A].
KEV_ANGSTROM = 12.398419


# ---------------------------------------------------------------------------
# Beamline-INVARIANT reference data.
#
# These are facts about the hardware that do not change per run: which detector
# stops physically exist and the detector pixel pitch. The values IN USE for a
# given run (energy, the SDD actually selected) live in that run's config.json
# `detector` block and MUST be passed in explicitly -- never rely on
# default_energy_keV below to silently supply them.
# ---------------------------------------------------------------------------
BEAMLINE_MODES = {
    "11BM": {
        "facility": "NSLS-II",
        "common_name": "CMS",
        "default_energy_keV": 13.5,
        "detector_pixel_size_um": 172.0,  # Pilatus
        "modes": {
            "saxs_2m": {"sd_distance_m": 2.0,
                        "description": "SAXS detector tube: standard stop near 2 m"},
            "saxs_3m": {"sd_distance_m": 3.0,
                        "description": "SAXS detector tube: standard stop near 3 m"},
            "saxs_5m": {"sd_distance_m": 5.03,
                        "description": "SAXS detector tube: standard stop near 5 m (max)"},
            "waxs":    {"sd_distance_m": 0.26,
                        "description": "WAXS detector (separate from the SAXS tube)"},
        },
        "notes": (
            "SAXS detector tube has three standard stop positions: ~2 m, ~3 m, ~5 m. "
            "Intermediate distances are NOT available -- recommend the closest standard "
            "stop when a calculation lands between them. WAXS is a separate detector "
            "at ~0.26 m."
        ),
    },
}


def _require(name: str, value):
    if value is None:
        raise ValueError(
            f"'{name}' is required but was not provided. Per-run values come from the "
            f"run's config.json (detector.energy_keV, detector.sdd_m) -- pass them "
            f"explicitly. For 'which stop should I use' questions, call q_on_beamline()."
        )
    return value


def _theta_from_q(q_A: float, wavelength_A: float) -> float:
    """Bragg theta (rad) from q. Readable error past the Ewald limit."""
    s = wavelength_A * q_A / (4 * PI)
    if not -1.0 <= s <= 1.0:
        q_max = 4 * PI / wavelength_A
        raise ValueError(
            f"q = {q_A:g} A^-1 is unreachable at lambda = {wavelength_A:.4f} A "
            f"(E = {KEV_ANGSTROM / wavelength_A:.3f} keV). Maximum accessible q is "
            f"4*pi/lambda = {q_max:.3f} A^-1 (backscattering). Raise the energy to reach it."
        )
    return math.asin(s)


def saxs_geometry(q_A: float, energy_keV: float, sd_distance_m: float,
                  det_pix_size_um: float = 172.0,
                  bs_size_pix: float = 0.0,
                  sample_len_mm: float = 0.0) -> dict:
    """Scattering geometry for a given q and beamline setup.

    Pass energy_keV and sd_distance_m from the run's config.json.
    """
    q_A = _require("q_A", q_A)
    energy_keV = _require("energy_keV", energy_keV)
    sd_distance_m = _require("sd_distance_m", sd_distance_m)

    wavelength_A = KEV_ANGSTROM / energy_keV
    theta_rad = _theta_from_q(q_A, wavelength_A)
    two_theta_rad = 2 * theta_rad
    d_A = 2 * PI / q_A

    det_q_mm = sd_distance_m * math.tan(two_theta_rad) * 1e3
    det_q_pix = det_q_mm * 1e3 / det_pix_size_um

    # Diffuse spread on the detector from finite sample length
    det_diff_mm = sample_len_mm * math.tan(two_theta_rad) * 1e-3 if sample_len_mm else 0.0
    det_diff_pix = det_diff_mm * 1e3 / det_pix_size_um if sample_len_mm else 0.0

    # Beamstop q cutoff
    bs_two_theta = math.atan(bs_size_pix * det_pix_size_um * 1e-6 / sd_distance_m)
    bs_q = 4 * PI * math.sin(bs_two_theta / 2) / wavelength_A

    return {
        "wavelength_A": wavelength_A,
        "two_theta_deg": math.degrees(two_theta_rad),
        "q_nm": 10.0 * q_A,
        "d_A": d_A,
        "d_nm": d_A / 10.0,
        "det_position_mm": det_q_mm,
        "det_position_pix": det_q_pix,
        "det_diff_mm": det_diff_mm,
        "det_diff_pix": det_diff_pix,
        "beamstop_q_cutoff_A": bs_q,
    }


def grain_size_from_peak_width(q_Lwidth_A: float) -> dict:
    """Grain (correlation) length from a Lorentzian peak width in q (A^-1)."""
    K = 2 * math.sqrt(math.log(2) / PI)
    L_nm = 0.2 * PI * K / q_Lwidth_A
    return {"value": L_nm, "units": "nm", "K_scherrer_like": K}


def strain_from_peak_width(sigma_G_A: float, q_A: float) -> dict:
    """Microstrain sigma from a Gaussian width sigma_G (A^-1) at peak position q (A^-1).

    WARNING -- UNVALIDATED. Carried over from the original tool unchanged; the
    expression has not been checked against a known reference case. Verify
    against a standard before quoting this in a report or publication.
    """
    beta_G = sigma_G_A * 2 * math.sqrt(2 * math.log(2))  # FWHM equivalent
    d_nm = 0.2 * PI / q_A
    s = 1.0 / d_nm  # nm^-1
    strain_sigma = beta_G * 10.0 / (2 * PI * 2 * s)
    return {
        "value": strain_sigma,
        "units": "dimensionless",
        "beta_G_invA": beta_G,
        "_warning": "UNVALIDATED expression -- verify against a reference case.",
    }


def wavelength_from_energy(energy_keV: float) -> dict:
    return {"value": KEV_ANGSTROM / energy_keV, "units": "A"}


def energy_from_wavelength(wavelength_A: float) -> dict:
    return {"value": KEV_ANGSTROM / wavelength_A, "units": "keV"}


def q_on_beamline(q_A: float, beamline: str = "11BM",
                  energy_keV: Optional[float] = None,
                  det_pix_size_um: Optional[float] = None) -> dict:
    """Where a target q lands in each of the beamline's configured detector stops.

    Use for 'what SDD do I need?' / 'will q=X be reachable?' -- it reports every
    available mode with that mode's fixed SDD, so you can recommend a real stop
    rather than an arbitrary distance.

    energy_keV defaults to the beamline's nominal energy; pass the run's actual
    detector.energy_keV when interpreting real data.
    """
    bl = BEAMLINE_MODES.get(beamline)
    if bl is None:
        raise ValueError(f"Unknown beamline {beamline!r}. Known: {sorted(BEAMLINE_MODES)}")

    energy = energy_keV if energy_keV is not None else bl.get("default_energy_keV")
    if energy is None:
        raise ValueError(f"No default energy for {beamline!r}; please supply energy_keV.")
    pix = det_pix_size_um if det_pix_size_um is not None else bl["detector_pixel_size_um"]

    modes = bl.get("modes", {})
    if not modes:
        raise ValueError(f"Beamline {beamline!r} has no configured modes.")

    wavelength_A = KEV_ANGSTROM / energy
    two_theta_rad = 2 * _theta_from_q(q_A, wavelength_A)

    rows = []
    for mode_name, mode_cfg in modes.items():
        sdd_m = mode_cfg["sd_distance_m"]
        det_q_mm = sdd_m * math.tan(two_theta_rad) * 1e3
        rows.append({
            "mode": mode_name,
            "sd_distance_m": sdd_m,
            "det_position_mm": det_q_mm,
            "det_position_pix": det_q_mm * 1e3 / pix,
            "description": mode_cfg.get("description", ""),
        })

    return {
        "beamline": beamline,
        "energy_keV": energy,
        "q_A": q_A,
        "wavelength_A": wavelength_A,
        "two_theta_deg": math.degrees(two_theta_rad),
        "d_A": 2 * PI / q_A,
        "d_nm": 0.2 * PI / q_A,
        "modes": rows,
        "notes": bl.get("notes", ""),
    }


def sdd_for_q(q_A: float, energy_keV: float,
              det_position_mm: float = 80.0) -> dict:
    """Inverse: the SDD that places q at a target detector radius (mm).

    det_position_mm defaults to 80 mm -- roughly mid-detector for a 1k Pilatus,
    a common 'comfortable' radius. Pass an explicit value if one is specified.

    NOTE: 11BM's SAXS tube only has discrete stops (2 / 3 / 5.03 m). Cross-check
    the answer with q_on_beamline() and recommend the nearest real stop.
    """
    q_A = _require("q_A", q_A)
    energy_keV = _require("energy_keV", energy_keV)

    wavelength_A = KEV_ANGSTROM / energy_keV
    two_theta_rad = 2 * _theta_from_q(q_A, wavelength_A)
    sdd_m = (det_position_mm * 1e-3) / math.tan(two_theta_rad)

    return {
        "value": sdd_m,
        "units": "m",
        "two_theta_deg": math.degrees(two_theta_rad),
        "wavelength_A": wavelength_A,
        "det_position_mm": det_position_mm,
    }
