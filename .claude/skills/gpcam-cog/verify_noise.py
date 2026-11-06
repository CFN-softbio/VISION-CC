#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification and real-data driver for noise_helpers.py.

TWO MODES, one file -- nothing to comment out:

  pixi run check-noise                       synthetic self-test (default)
  python verify_noise.py --csv <log.csv> --value ReZ2_p04 [--sigma 0.05]
                                             run the same estimators on REAL experiment data

Synthetic mode constructs data whose noise and structure we chose, then checks the helpers
recover it -- it catches a regression in the statistics themselves before a run depends on them.
Tolerances are deliberately loose where the estimator is genuinely imprecise: sigma from 15 frames
is only good to ~a factor of 1.75, and asserting tighter would make this file flaky, not useful.

Real-data mode has no pass/fail -- it prints the structure/resolution statistics and the noise card
for a column of an ana_log CSV. Use it before a launch (on the seed rows) or to inspect a finished
run. Add --repeat-col to include the repeat-based half of the card.

No hardware, no gpCAM import; numpy + optional scipy only.
"""
import argparse
import math
import sys
import os

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noise_helpers as nh                                            # noqa: E402

# One generator per section, so adding a check in section 2 cannot change section 4's draws --
# the first version of this file had exactly that coupling and it made failures look random.
RNG = np.random.default_rng(20260805)


def reseed(section):
    global RNG
    RNG = np.random.default_rng(20260805 + 1000 * section)


FAILURES = []


# ---------------------------------------------------------------------------
# Real-data mode
# ---------------------------------------------------------------------------

def run_real(args):
    """Print the structure statistics and noise card for one column of a real ana_log CSV."""
    d = np.genfromtxt(args.csv, delimiter=",", names=True)
    names = d.dtype.names
    for col in (args.x, args.y, args.value):
        if col not in names:
            print("column %r not in %s\navailable: %s" % (col, args.csv, ", ".join(names)))
            return 2

    m = np.ones(d.shape, dtype=bool)
    if args.seq_max is not None and "seq" in names:
        m &= d["seq"] <= args.seq_max
    if args.seq_min is not None and "seq" in names:
        m &= d["seq"] >= args.seq_min

    xy = np.column_stack([d[args.x][m], d[args.y][m]])
    y = d[args.value][m]
    good = np.isfinite(y) & np.all(np.isfinite(xy), axis=1)
    xy, y = xy[good], y[good]

    print("=" * 78)
    print("%s   column %s   %d points" % (os.path.basename(args.csv), args.value, y.size))
    print("  mean %.6g   sd %.6g   Var %.6g" % (y.mean(), y.std(ddof=1), y.var(ddof=1)))
    print("=" * 78)

    rep = fit = None
    if args.repeat_col and args.repeat_col in names:
        rep = nh.repeat_stats(y, d[args.repeat_col][m][good])
        fit = nh.noise_form(rep)
        sigma = rep.s_pool
        print("\nsigma from repeat exposures: s_pool = %.6g  (dof %d)" % (sigma, rep.dof))
    elif args.sigma is not None:
        sigma = args.sigma
        print("\nsigma supplied on the command line: %.6g" % sigma)
    else:
        print("\nNo sigma available. This run has no repeat exposures, and sigma is the anchor for")
        print("every number below -- pass --sigma <value>, or --repeat-col if the log has repeats.")
        print("(That a finished run cannot supply this is exactly what the seed-repeat protocol")
        print(" in docs/noise-model.md exists to prevent.)")
        return 1

    nn = nh.nn_structure(xy, y, sigma)
    print("\nSTRUCTURE / RESOLUTION (nearest-neighbour, no spatial model)")
    print("  NN spacing        : median %.6g   [min %.6g, max %.6g]"
          % (nn.nn_dist_median, nn.nn_dist_min, nn.nn_dist_max))
    print("  coincident pairs  : %d  (excluded -- they measure sigma, not structure)" % nn.n_zero_dist)
    print("  Var(y)/sigma^2    : %.2f" % nn.snr)
    print("  rms(dy_NN)        : %.6g      vs sqrt(2)*sigma = %.6g"
          % (nn.rms_dy, math.sqrt(2) * sigma))
    print("  ratio             : %.2f" % nn.ratio)
    print("  verdict           : %s" % nn.verdict)
    print("  %s" % nn.note)
    if np.isfinite(nn.ell_upper_bound):
        print("  => correlation length is AT OR BELOW %.6g" % nn.ell_upper_bound)

    if rep is not None:
        print("\n" + nh.noise_card(rep, fit, nn, declared_sigma=args.declared_sigma,
                                   fitted_ell=args.fitted_ell).text)
    return 0


def check(name, cond, detail=""):
    status = "ok  " if cond else "FAIL"
    print("  [%s] %s%s" % (status, name, ("  -- " + detail) if detail else ""))
    if not cond:
        FAILURES.append(name)


def approx(a, b, rel=0.25):
    return abs(a - b) <= rel * max(abs(b), 1e-12)


_P = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
_P.add_argument("--csv", help="real ana_log CSV; omit for the synthetic self-test")
_P.add_argument("--value", help="objective column to analyze (real-data mode)")
_P.add_argument("--x", default="x", help="x column (default: x)")
_P.add_argument("--y", default="y", help="y column (default: y)")
_P.add_argument("--sigma", type=float, help="known sigma, if the run has no repeat exposures")
_P.add_argument("--beam-size", type=float,
                help="beam footprint; pairs closer than this share illuminated area and are "
                     "excluded (STRONGLY recommended on real maps)")
_P.add_argument("--repeat-col", help="column grouping repeat exposures, if the run has them")
_P.add_argument("--declared-sigma", type=float, help="sigma the daemon would declare, to check")
_P.add_argument("--fitted-ell", type=float, nargs="*", help="GP's fitted length scale(s), to check")
_P.add_argument("--seq-min", type=float, help="keep rows with seq >= this")
_P.add_argument("--seq-max", type=float, help="keep rows with seq <= this")
_ARGS = _P.parse_args()

if _ARGS.csv:
    if not _ARGS.value:
        _P.error("--value is required with --csv")
    sys.exit(run_real(_ARGS))


# ---------------------------------------------------------------------------
def make_repeats(levels, sigma_of, n=3):
    """Repeat frames at the given signal levels, with sigma given by sigma_of(level)."""
    y, g = [], []
    for k, mu in enumerate(levels):
        s = sigma_of(mu)
        y.extend(RNG.normal(mu, s, size=n))
        g.extend([k] * n)
    return np.asarray(y), np.asarray(g)


def make_field(n=120, ell=0.30, sig=1.0, noise=0.05, box=2.0):
    """Gaussian field on random points with a squared-exponential covariance, plus iid noise."""
    xy = RNG.uniform(-box / 2, box / 2, size=(n, 2))
    d2 = ((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1)
    K = sig ** 2 * np.exp(-0.5 * d2 / ell ** 2) + 1e-10 * np.eye(n)
    f = np.linalg.cholesky(K) @ RNG.standard_normal(n)
    return xy, f + RNG.normal(0, noise, size=n)


# ---------------------------------------------------------------------------
print("\n1. repeat_stats -- pooled sigma and its CI")

TRUE_S = 0.20
y, g = make_repeats([1.0] * 5, lambda m: TRUE_S, n=3)
rep = nh.repeat_stats(y, g)
check("dof = P*(n-1) = 10", rep.dof == 10, "got %d" % rep.dof)
check("s_pool recovers the true sigma", approx(rep.s_pool, TRUE_S, 0.45),
      "s_pool=%.4f true=%.4f" % (rep.s_pool, TRUE_S))
check("true sigma inside the 95%% CI", rep.ci95[0] <= TRUE_S <= rep.ci95[1],
      "CI=[%.4f, %.4f]" % rep.ci95)
check("CI factors match the documented 5x3 design",
      approx(rep.ci95_factor[0], 0.70, 0.03) and approx(rep.ci95_factor[1], 1.75, 0.03),
      "[%.2f, %.2f] x s_pool (doc: [0.70, 1.75])" % rep.ci95_factor)
check("rel SE = 1/sqrt(2*dof)", approx(rep.rel_se, 1 / math.sqrt(20), 1e-6), "%.4f" % rep.rel_se)

y2, g2 = make_repeats([1.0] * 3, lambda m: TRUE_S, n=3)
check("3x3 gives dof 6", nh.repeat_stats(y2, g2).dof == 6)
check("3x3 CI factors match the doc",
      approx(nh.repeat_stats(y2, g2).ci95_factor[0], 0.64, 0.08)
      and approx(nh.repeat_stats(y2, g2).ci95_factor[1], 2.2, 0.08))

y3 = np.concatenate([y2, [5.0]])
g3 = np.concatenate([g2, [99]])
r3 = nh.repeat_stats(y3, g3)
check("singleton position reported but excluded from dof", r3.dof == 6 and 99 in r3.labels)

# ---------------------------------------------------------------------------
reseed(2)
print("\n2. noise_form -- the sign test that must never miss an inverted model")

LEVELS = [0.05, 0.15, 0.4, 1.0, 3.0]

y, g = make_repeats(LEVELS, lambda m: 0.10, n=3)
f = nh.noise_form(nh.repeat_stats(y, g))
check("constant noise -> CONSTANT", f.verdict == nh.CONSTANT, "beta=%.2f" % f.beta)

y, g = make_repeats(LEVELS, lambda m: 0.10 * m, n=3)
f = nh.noise_form(nh.repeat_stats(y, g))
check("value-proportional -> VALUE_PROPORTIONAL", f.verdict == nh.VALUE_PROPORTIONAL,
      "beta=%.2f" % f.beta)
check("alpha recovered near 0.10", approx(f.frac_mean, 0.10, 0.5), "frac_mean=%.3f" % f.frac_mean)

# Strongly inverted (true beta = -0.8): must always be caught. Note the scaling -- sigma at the
# lowest level is 40% of its own mean, no more. A harsher inversion (sigma > mean at the low end)
# makes ybar_p itself noise, which corrupts the regressor and produces wild beta estimates: an
# inverted model can be so severe that it destroys the very data needed to detect it.
INVERTED_STRONG = lambda m: 0.02 * (max(m, 1e-6) / 0.05) ** -0.8      # noqa: E731
det = sum(nh.noise_form(nh.repeat_stats(*make_repeats(LEVELS, INVERTED_STRONG, n=3))).rejected
          for _ in range(40))
check("strongly inverted model is REJECTED (>=90% of draws)", det >= 36,
      "%d/40 detected" % det)

# the run007 form (true beta ~ -0.43) is below this design's detection power; the guarantee is
# only that it is never called constant or proportional
y, g = make_repeats(LEVELS, lambda m: 0.03 + 0.15 * max(0.0, 1.0 - m / 3.0), n=3)
f = nh.noise_form(nh.repeat_stats(y, g))
check("run007-shaped inversion is at least flagged, never called constant",
      f.verdict in (nh.INVERTED, nh.UNDETERMINED), "beta=%.2f verdict=%s" % (f.beta, f.verdict))

y, g = make_repeats([1.0] * 5, lambda m: 0.1, n=3)
check("single signal level -> UNDETERMINED, not a false CONSTANT",
      nh.noise_form(nh.repeat_stats(y, g)).verdict == nh.UNDETERMINED)

# The false-block rate on a genuinely constant sigma is ~12% by design (see noise_form's docstring:
# sensitivity is bought with false alarms, deliberately). This asserts it has not drifted much
# higher, not that it is zero.
# 200 trials, not 40: the true rate is ~11%, and n=40 swings between 2% and 30% by luck alone --
# a flaky assertion is worse than none.
N_TRIAL = 200
false_pos = sum(nh.noise_form(nh.repeat_stats(*make_repeats(LEVELS, lambda m: 0.10, n=3))).rejected
                for _ in range(N_TRIAL))
check("constant-sigma false-block rate stays near the designed ~11%",
      false_pos <= 0.20 * N_TRIAL, "%d/%d = %.0f%% good models blocked"
      % (false_pos, N_TRIAL, 100 * false_pos / N_TRIAL))

# value-proportional -- the 11BM default -- must never be falsely blocked
fp_prop = sum(nh.noise_form(nh.repeat_stats(*make_repeats(LEVELS, lambda m: 0.10 * m, n=3))).rejected
              for _ in range(40))
check("value-proportional models are never falsely blocked", fp_prop == 0, "%d/40" % fp_prop)

# ---------------------------------------------------------------------------
reseed(3)
print("\n3. nn_structure -- signal present? resolved at the sampling step?")

# ell >> sampling step: neighbours differ by noise only
TRUE_NOISE = 0.10
xy, yv = make_field(n=300, ell=1.0, sig=1.0, noise=TRUE_NOISE, box=2.0)
nn = nh.nn_structure(xy, yv, TRUE_NOISE)
check("smooth field -> RESOLVED", nn.verdict == nh.RESOLVED,
      "ratio=%.2f snr=%.1f" % (nn.ratio, nn.snr))
check("smooth field -> ratio near 1", nn.ratio < 1.3, "ratio=%.2f" % nn.ratio)
check("smooth field -> no ell upper bound claimed", not np.isfinite(nn.ell_upper_bound))

# ell << sampling step: neighbours already decorrelated
xy, yv = make_field(n=200, ell=0.02, sig=1.0, noise=TRUE_NOISE, box=2.0)
nn = nh.nn_structure(xy, yv, TRUE_NOISE)
check("fine-structure field -> UNDER-RESOLVED", nn.verdict == nh.UNDER_RESOLVED,
      "ratio=%.2f snr=%.1f" % (nn.ratio, nn.snr))
check("under-resolved -> ell bounded by the sampling step",
      np.isfinite(nn.ell_upper_bound) and nn.ell_upper_bound == nn.nn_dist_median,
      "ell <= %.4f" % nn.ell_upper_bound)
check("under-resolved -> structure variance is a large share of Var(y)",
      nn.struct_var_at_nn > 0.5 * nn.var_y,
      "struct=%.3f var=%.3f" % (nn.struct_var_at_nn, nn.var_y))

# pure noise: no structure at all
xy_n = RNG.uniform(-1, 1, size=(200, 2))
nn_n = nh.nn_structure(xy_n, RNG.normal(0, 0.5, 200), 0.5)
check("pure noise -> NO_STRUCTURE", nn_n.verdict == nh.NO_STRUCTURE,
      "snr=%.2f ratio=%.2f" % (nn_n.snr, nn_n.ratio))
check("pure noise -> snr near 1", approx(nn_n.snr, 1.0, 0.5), "snr=%.2f" % nn_n.snr)

# repeats among the points must not be read as structure
xy_r = np.vstack([xy_n, xy_n[:5]])
y_r = np.concatenate([RNG.normal(0, 0.5, 200), RNG.normal(0, 0.5, 5)])
check("coincident points are excluded", nh.nn_structure(xy_r, y_r, 0.5).n_zero_dist >= 5)

try:
    nh.nn_structure(xy_n, RNG.normal(0, 1, 200), 0.0)
    check("zero sigma rejected", False)
except ValueError:
    check("zero sigma rejected", True)

# ---------------------------------------------------------------------------
reseed(4)
print("\n4. sigma_from_model -- inverted forms are not expressible")

yy = np.array([0.0, 0.5, 2.0])
s_const = nh.sigma_from_model(yy, nh.CONSTANT, floor=0.07)
s_prop = nh.sigma_from_model(yy, nh.VALUE_PROPORTIONAL, frac=0.10, floor=0.05)
check("constant model is flat", np.allclose(s_const, 0.07))
check("proportional model respects the floor", np.isclose(s_prop[0], 0.05))
check("proportional model scales with |y|", np.isclose(s_prop[2], 0.20))
check("sigma is non-decreasing in |y| by construction", np.all(np.diff(s_prop) >= 0))
try:
    nh.sigma_from_model(yy, "inverse_snr")
    check("unknown model rejected", False)
except ValueError:
    check("unknown model rejected", True)

# ---------------------------------------------------------------------------
reseed(5)
print("\n5. noise_card -- gate verdicts")

y, g = make_repeats(LEVELS, lambda m: 0.10 * m, n=3)
rep = nh.repeat_stats(y, g)
fit = nh.noise_form(rep)
xy, yv = make_field(n=300, ell=1.0, sig=1.0, noise=rep.s_pool, box=2.0)
nn = nh.nn_structure(xy, yv, rep.s_pool)
HEALTHY = dict(signal_variance=0.9, signal_variance_floor=1e-3, cv_vs_constant=1.4)

good = nh.noise_card(rep, fit, nn, declared_sigma=rep.s_pool, model=nh.VALUE_PROPORTIONAL,
                     frac=0.10, floor=rep.s_pool, fitted_ell=[1.0, 1.0], **HEALTHY)
check("healthy setup is not blocked", not good.blocking, "; ".join(good.blockers))

pinned = nh.noise_card(rep, fit, nn, declared_sigma=rep.s_pool,
                       signal_variance=1.5e-3, signal_variance_floor=1e-3, cv_vs_constant=1.2)
check("signal_variance at its floor BLOCKS", any("floor" in b for b in pinned.blockers),
      "; ".join(pinned.blockers))

y_i, g_i = make_repeats(LEVELS, lambda m: 0.02 * (max(m, 1e-6) / 0.05) ** -0.8, n=3)
rep_i = nh.repeat_stats(y_i, g_i)
inv = nh.noise_card(rep_i, nh.noise_form(rep_i), nn, declared_sigma=0.1, **HEALTHY)
check("inverted model BLOCKS", any("INVERTED" in b for b in inv.blockers), "; ".join(inv.blockers))

null = nh.noise_card(rep, fit, nn, declared_sigma=rep.s_pool,
                     signal_variance=0.9, signal_variance_floor=1e-3, cv_vs_constant=0.95)
check("posterior not beating a constant BLOCKS",
      any("constant predictor" in b for b in null.blockers), "; ".join(null.blockers))

missing = nh.noise_card(rep, fit, None)
check("un-run checks BLOCK rather than silently pass", missing.blocking, "; ".join(missing.blockers))
check("missing NN check warns", any("nearest-neighbour" in w for w in missing.warnings))

loud = nh.noise_card(rep, fit, nn, declared_sigma=20 * rep.s_pool, **HEALTHY)
check("declared sigma >> repeats warns", any("noisier than it is" in w for w in loud.warnings),
      "; ".join(loud.warnings))

quiet = nh.noise_card(rep, fit, nn, declared_sigma=0.05 * rep.s_pool, **HEALTHY)
check("declared sigma << repeats warns", any("chase noise" in w for w in quiet.warnings))

# the run007 failure mode: structure below the step, GP fitting a huge ell
xy_f, y_f = make_field(n=200, ell=0.02, sig=1.0, noise=rep.s_pool, box=2.0)
nn_f = nh.nn_structure(xy_f, y_f, rep.s_pool)
run007 = nh.noise_card(rep, fit, nn_f, declared_sigma=rep.s_pool,
                       fitted_ell=[4.0, 4.0], **HEALTHY)
check("ell >> sampling step on an under-resolved field BLOCKS",
      any("smoothing over structure" in b for b in run007.blockers), "; ".join(run007.blockers))

check("card text is presentable", "NOISE MODEL CARD" in good.text and "VERDICT" in good.text)
check("card no longer mentions variograms",
      "variogram" not in good.text.lower() and "nugget" not in good.text.lower())

# ---------------------------------------------------------------------------
print("\n" + "=" * 72)
if FAILURES:
    print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("all noise_helpers checks passed")
print("=" * 72)
print("\nSample card:\n")
print(good.text)
