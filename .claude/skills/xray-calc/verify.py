#!/usr/bin/env python3
"""Verify the xray-calc skill modules against hand-checkable reference values.

Every check is an independent cross-check, not a regression snapshot: Bragg and
SDD round-trips, Beer-Lambert self-consistency, textbook edge/line energies, and
the NIST-vs-formula agreement for the same material by two different routes.

Geometry is stdlib-only and always runs. The properties/xraylib section is
skipped with a notice if xraylib isn't installed.

Run:  pixi run check-xray
  or: python .claude/skills/xray-calc/verify.py
"""
import math
import os
import sys

# Modules under test sit beside this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import saxs_geometry as geo  # noqa: E402

fails = []


def check(label, got, want, tol):
    ok = abs(got - want) <= tol
    print(f"  [{'OK ' if ok else 'FAIL'}] {label:<42} got={got:.6g}  want={want:.6g}")
    if not ok:
        fails.append(label)


print("== geometry ==")

# d = 2*pi/q is exact arithmetic, independent of energy/SDD.
r = geo.saxs_geometry(q_A=0.21, energy_keV=13.5, sd_distance_m=5.0)
check("d_A at q=0.21", r["d_A"], 2 * math.pi / 0.21, 1e-9)
check("d_nm == d_A/10", r["d_nm"], r["d_A"] / 10.0, 1e-12)
check("q_nm == 10*q_A", r["q_nm"], 2.1, 1e-12)

# lambda = 12.398419 / E
check("lambda at 13.5 keV", r["wavelength_A"], 12.398419 / 13.5, 1e-9)

# Bragg round trip: q = 4*pi*sin(theta)/lambda
lam = r["wavelength_A"]
theta = math.radians(r["two_theta_deg"]) / 2
check("q recovered from 2theta", 4 * math.pi * math.sin(theta) / lam, 0.21, 1e-9)

# Detector radius round trip: tan(2theta) * SDD
check("det_position_mm", r["det_position_mm"],
      5.0 * math.tan(math.radians(r["two_theta_deg"])) * 1e3, 1e-6)
check("det_position_pix", r["det_position_pix"], r["det_position_mm"] * 1e3 / 172.0, 1e-6)

# E <-> lambda round trip
e = geo.energy_from_wavelength(geo.wavelength_from_energy(13.5)["value"])["value"]
check("E->lambda->E round trip", e, 13.5, 1e-9)

# sdd_for_q is the inverse of saxs_geometry's detector radius
sdd = geo.sdd_for_q(q_A=0.05, energy_keV=13.5, det_position_mm=80.0)["value"]
back = geo.saxs_geometry(q_A=0.05, energy_keV=13.5, sd_distance_m=sdd)
check("sdd_for_q inverts to 80 mm", back["det_position_mm"], 80.0, 1e-6)

# q_on_beamline: 4 stops, monotonic in SDD
ob = geo.q_on_beamline(q_A=0.05, energy_keV=13.5)
stops = [m["sd_distance_m"] for m in ob["modes"]]
radii = [m["det_position_mm"] for m in ob["modes"]]
print(f"  [{'OK ' if stops == [2.0, 3.0, 5.03, 0.26] else 'FAIL'}] "
      f"stops present                               {stops}")
if stops != [2.0, 3.0, 5.03, 0.26]:
    fails.append("stops")
ratio = radii[1] / radii[0]
check("radius scales with SDD (3m/2m)", ratio, 1.5, 1e-9)

# Ewald limit: q > 4*pi/lambda must raise a readable error, not math domain error
qmax = 4 * math.pi / lam
try:
    geo.saxs_geometry(q_A=qmax * 1.01, energy_keV=13.5, sd_distance_m=5.0)
    print("  [FAIL] Ewald-limit guard did not raise")
    fails.append("ewald guard")
except ValueError as ex:
    ok = "unreachable" in str(ex)
    print(f"  [{'OK ' if ok else 'FAIL'}] Ewald-limit guard raises readable error")
    if not ok:
        fails.append("ewald message")

# Grain size: L = 0.2*pi*K/width, K = 2*sqrt(ln2/pi)
K = 2 * math.sqrt(math.log(2) / math.pi)
g = geo.grain_size_from_peak_width(q_Lwidth_A=0.004)
check("grain size at width=0.004", g["value"], 0.2 * math.pi * K / 0.004, 1e-9)

print("\n== properties (xraylib) ==")
try:
    import properties as props

    # Si K edge is a textbook value: 1.839 keV
    k = props.edge_energy("Si", "K")["value"]
    check("Si K edge (keV)", k, 1.839, 0.01)

    # Cu K-alpha1 ~ 8.048 keV
    ka = props.fluorescence_line_energy("Cu", "KA1")["value"]
    check("Cu KA1 (keV)", ka, 8.048, 0.02)

    # Transmission must fall in (0,1) and drop with thickness
    t100 = props.transmission("Si", 13.5, 100)["value"]
    t200 = props.transmission("Si", 13.5, 200)["value"]
    ok = 0 < t200 < t100 < 1
    print(f"  [{'OK ' if ok else 'FAIL'}] T(Si) decreases with thickness      "
          f"100um={t100:.4f} 200um={t200:.4f}")
    if not ok:
        fails.append("transmission monotonic")

    # Beer-Lambert self-consistency: T(2t) == T(t)^2
    check("T(200um) == T(100um)^2", t200, t100 ** 2, 1e-9)

    # attenuation length: T at exactly 1 attenuation length == 1/e
    L = props.attenuation_length("Si", 13.5)["value"]
    check("T at 1 att. length == 1/e", props.transmission("Si", 13.5, L)["value"],
          math.exp(-1), 1e-9)

    # Compound without density must raise
    try:
        props.transmission("C22H10N2O5", 13.5, 200)
        print("  [FAIL] compound without density did not raise")
        fails.append("density guard")
    except ValueError as ex:
        ok = "Density is required" in str(ex)
        print(f"  [{'OK ' if ok else 'FAIL'}] compound w/o density raises")
        if not ok:
            fails.append("density message")

    # Kapton with density works
    kap = props.transmission("C22H10N2O5", 13.5, 200, density=1.42)["value"]
    ok = 0.9 < kap < 1.0
    print(f"  [{'OK ' if ok else 'FAIL'}] kapton 200um @13.5keV plausible       T={kap:.4f}")
    if not ok:
        fails.append("kapton")

    print("\n== NIST compound database ==")

    n_all = len(props.list_nist_compounds())
    ok = n_all > 150
    print(f"  [{'OK ' if ok else 'FAIL'}] NIST list populated                   n={n_all}")
    if not ok:
        fails.append("nist list")

    # Named material resolves WITHOUT a density
    knist = props.transmission("Kapton Polyimide Film", 13.5, 200)
    print(f"  [OK ] NIST kapton needs no density        T={knist['value']:.6f}")
    print(f"         source: {knist['source']}")
    check("NIST kapton density", knist["density_g_cm3"], 1.42, 1e-9)

    # NIST mixture rule vs. formula+density: same material, two routes.
    # Small delta expected -- NIST mass fractions are rounded to 6 dp.
    check("NIST kapton == formula kapton", knist["value"], kap, 5e-4)

    # Unique substring match is accepted
    sub = props.nist_compound("Kapton")
    ok = sub["name"] == "Kapton Polyimide Film"
    print(f"  [{'OK ' if ok else 'FAIL'}] unique substring 'Kapton' resolves")
    if not ok:
        fails.append("substring match")

    # Ambiguous substring MUST raise -- Water, Liquid vs Water Vapor differ ~1300x
    try:
        props.nist_compound("water")
        print("  [FAIL] ambiguous 'water' did not raise")
        fails.append("ambiguity guard")
    except ValueError as ex:
        ok = "ambiguous" in str(ex)
        print(f"  [{'OK ' if ok else 'FAIL'}] ambiguous 'water' raises")
        if not ok:
            fails.append("ambiguity message")

    # Both water phases resolve explicitly, and differ hugely
    wl = props.transmission("Water, Liquid", 13.5, 1000)["value"]
    wv = props.transmission("Water Vapor", 13.5, 1000)["value"]
    ok = wv > wl
    print(f"  [{'OK ' if ok else 'FAIL'}] liquid vs vapor water differ     "
          f"liquid={wl:.4f} vapor={wv:.6f}")
    if not ok:
        fails.append("water phases")

    # Element path unaffected by the new branch
    au = props.transmission("Au", 13.5, 1.0)
    check("Au 1um unchanged", au["value"], 0.771466, 1e-5)
    print(f"         source: {au['source']}")

except ImportError as ex:
    print(f"  SKIPPED — xraylib not importable yet ({ex}).")
    print("  Run `pixi install` then re-run this script.")

print()
if fails:
    print(f"FAILURES: {fails}")
    sys.exit(1)
print("all checks passed")
