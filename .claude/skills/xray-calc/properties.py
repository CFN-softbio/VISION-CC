"""Material/atomic X-ray properties via xraylib.

Standalone: no relative imports. Drop the skill directory on sys.path and
`import properties`.

Provenance: adapted for VISION from VISION_dev_fe/backend/src/xray/properties.py.
Change from the original: the NIST compound database IS now wired in (the
original noted it as missing), so ~180 named materials carry their own density.

A material argument may be any of three things, resolved in this order:

  1. A pure element symbol      -- 'Au', 'Si'   (density from xraylib)
  2. A NIST material name       -- 'Kapton Polyimide Film', 'Water, Liquid'
                                   (density from NIST -- no need to supply one)
  3. A chemical formula         -- 'SiO2', 'C22H10N2O5'
                                   (density REQUIRED: stoichiometry carries no
                                    packing information -- graphite and diamond
                                    share a formula)

Every returned dict includes a `source` string recording where the density came
from, so a script's stdout is self-documenting.

All energies are in keV, thicknesses in micrometres, densities in g/cm^3.
"""

import math
from typing import Optional

import xraylib

_EDGE_MAP = {
    "K":  xraylib.K_SHELL,
    "L1": xraylib.L1_SHELL,
    "L2": xraylib.L2_SHELL,
    "L3": xraylib.L3_SHELL,
    "M1": xraylib.M1_SHELL,
    "M2": xraylib.M2_SHELL,
    "M3": xraylib.M3_SHELL,
    "M4": xraylib.M4_SHELL,
    "M5": xraylib.M5_SHELL,
}


# ---------------------------------------------------------------------------
# NIST compound database (~180 named materials, each WITH a density)
# ---------------------------------------------------------------------------

def list_nist_compounds(substring: Optional[str] = None) -> list:
    """NIST material names xraylib knows, optionally filtered (case-insensitive).

    Call with no argument to see all of them. Useful ones at a scattering
    beamline: 'Kapton Polyimide Film', 'Polyethylene Terephthalate (Mylar)',
    'Water, Liquid', 'Air, Dry (near sea level)', 'Silicon Dioxide'.
    """
    names = list(xraylib.GetCompoundDataNISTList())
    if substring:
        s = substring.lower()
        names = [n for n in names if s in n.lower()]
    return names


def nist_compound(name: str) -> dict:
    """Resolve a NIST material by name; returns its record including density.

    Exact match (case-insensitive) wins. Otherwise a UNIQUE substring match is
    accepted. An ambiguous substring RAISES rather than picking one -- 'water'
    matches both 'Water, Liquid' (1.0 g/cm^3) and 'Water Vapor' (0.00076), a
    factor of ~1300 that must never be resolved silently.
    """
    all_names = list(xraylib.GetCompoundDataNISTList())
    low = name.lower().strip()

    for n in all_names:
        if n.lower() == low:
            return dict(xraylib.GetCompoundDataNISTByName(n))

    hits = [n for n in all_names if low in n.lower()]
    if len(hits) == 1:
        return dict(xraylib.GetCompoundDataNISTByName(hits[0]))
    if len(hits) > 1:
        raise ValueError(
            f"{name!r} is ambiguous in the NIST compound list -- it matches "
            f"{hits}. Use the full name."
        )
    raise KeyError(
        f"{name!r} is not a NIST material name. "
        f"Try list_nist_compounds('<keyword>') to search."
    )


def _nist_or_none(name: str) -> Optional[dict]:
    """NIST record, or None if there's no match. Ambiguity still raises."""
    try:
        return nist_compound(name)
    except KeyError:
        return None


# ---------------------------------------------------------------------------
# Material resolution
# ---------------------------------------------------------------------------

def _atomic_number_or_none(formula: str) -> Optional[int]:
    """Return atomic number for an element symbol, or None for anything else."""
    try:
        Z = xraylib.SymbolToAtomicNumber(formula)
    except Exception:
        return None
    return Z if Z > 0 else None


def _resolve_element(formula: str) -> int:
    """Strict element resolution (used for edges/lines that only apply to atoms)."""
    Z = _atomic_number_or_none(formula)
    if Z is None:
        raise ValueError(f"{formula!r} is not a pure element; this calculation "
                         "(edge / fluorescence line) only applies to single elements.")
    return Z


def _resolve_material(material: str, energy_keV: float,
                      density: Optional[float]) -> tuple[float, Optional[float], str]:
    """Return (mu/rho in cm^2/g, rho in g/cm^3 or None, provenance string)."""
    # 1. Pure element
    Z = _atomic_number_or_none(material)
    if Z is not None:
        rho = density if density is not None else xraylib.ElementDensity(Z)
        src = "user" if density is not None else "xraylib ElementDensity"
        return xraylib.CS_Total(Z, energy_keV), rho, f"element Z={Z}, density from {src}"

    # 2. NIST named material -- mixture rule over its mass fractions
    rec = _nist_or_none(material)
    if rec is not None:
        mu_rho = sum(w * xraylib.CS_Total(z, energy_keV)
                     for z, w in zip(rec["Elements"], rec["massFractions"]))
        rho = density if density is not None else rec["density"]
        src = "user override" if density is not None else "NIST"
        return mu_rho, rho, f"NIST {rec['name']!r}, density from {src}"

    # 3. Chemical formula -- density cannot be inferred
    try:
        xraylib.CompoundParser(material)
    except Exception as e:
        raise ValueError(
            f"Could not parse {material!r} as an element, a NIST material name, or a "
            f"chemical formula ({e}). Search named materials with "
            f"list_nist_compounds('<keyword>')."
        )
    return xraylib.CS_Total_CP(material, energy_keV), density, \
        f"formula {material!r}, density from user"


def _cross_section_and_density(material: str, energy_keV: float,
                               density: Optional[float]) -> tuple[float, float, str]:
    """As _resolve_material, but a missing density is a hard error."""
    mu_rho, rho, source = _resolve_material(material, energy_keV, density)
    if rho is None:
        raise ValueError(
            f"Density is required for the chemical formula {material!r} -- stoichiometry "
            "carries no packing information (graphite and diamond are both 'C'). Either "
            "pass density=..., or name a NIST material that carries its own density: "
            "list_nist_compounds('<keyword>'). "
            "Common values: SiO2=2.65, kapton/polyimide=1.42, water=1.0, air=1.225e-3."
        )
    return mu_rho, rho, source


# ---------------------------------------------------------------------------
# Public calculations
# ---------------------------------------------------------------------------

def transmission(material: str, energy_keV: float, thickness_um: float,
                 density: Optional[float] = None) -> dict:
    """Beer-Lambert transmission T = exp(-mu*t).

    Elements and NIST materials supply their own density; a bare chemical
    formula requires one. Pass `density` to override any of them.
    """
    mu_rho, rho, source = _cross_section_and_density(material, energy_keV, density)
    mu_t = mu_rho * rho * (thickness_um * 1e-4)
    return {
        "value": math.exp(-mu_t),
        "units": "fraction",
        "mu_rho_cm2_g": mu_rho,
        "density_g_cm3": rho,
        "mu_t": mu_t,
        "source": source,
    }


def attenuation_length(material: str, energy_keV: float,
                       density: Optional[float] = None) -> dict:
    """1/e attenuation length in micrometres."""
    mu_rho, rho, source = _cross_section_and_density(material, energy_keV, density)
    mu = mu_rho * rho  # 1/cm
    return {
        "value": 1e4 / mu,
        "units": "um",
        "mu_rho_cm2_g": mu_rho,
        "density_g_cm3": rho,
        "source": source,
    }


def mass_attenuation_coefficient(material: str, energy_keV: float) -> dict:
    """mu/rho in cm^2/g via xraylib (see SKILL.md "Data sources & references").

    Density-independent, so a bare formula works without one.
    """
    mu_rho, _rho, source = _resolve_material(material, energy_keV, None)
    return {"value": mu_rho, "units": "cm^2/g", "source": source}


def edge_energy(formula: str, edge: str) -> dict:
    """Absorption edge energy in keV. Elements only (edges are atomic)."""
    Z = _resolve_element(formula)
    if edge not in _EDGE_MAP:
        raise ValueError(f"Unknown edge {edge!r}. Use one of: {sorted(_EDGE_MAP)}")
    return {
        "value": xraylib.EdgeEnergy(Z, _EDGE_MAP[edge]),
        "units": "keV",
        "edge": edge,
    }


def fluorescence_line_energy(formula: str, line: str) -> dict:
    """Fluorescence-line energy in keV. Elements only."""
    Z = _resolve_element(formula)
    line_attr = f"{line.upper()}_LINE"
    if not hasattr(xraylib, line_attr):
        raise ValueError(f"Unknown line {line!r}")
    return {
        "value": xraylib.LineEnergy(Z, getattr(xraylib, line_attr)),
        "units": "keV",
        "line": line.upper(),
    }
