#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed-noise helpers for the GP noise model (11BM-CMS VISION).

Import these instead of re-deriving the statistics; the conventions here are the ones
`docs/noise-model.md` specifies.

Contract:  docs/noise-model.md
Why:       docs/appendix/noise-model-math.md   (human reference)
Verify:    pixi run check-noise                (offline, synthetic ground truth)
           python verify_noise.py --csv <ana_log.csv> --value <column>   (real data)

Three numbers, three questions, no spatial model:

    repeat_stats + noise_form   how big is sigma, and does it track the signal?
    nn_structure                is there structure above the noise, and is my sampling
                                step fine enough to see it?
    noise_card                  assemble both into the pre-launch gate

DELIBERATELY NOT HERE: variograms. They assume second-order stationarity -- one mean, one
covariance depending only on separation -- which an autonomous experiment violates by design,
since the whole point is to map an INHOMOGENEOUS sample. On real run007 data the empirical
semivariogram was non-monotonic (gamma peaked at 2.4x its far-field value), so no standard model
applied and every derived quantity was either meaningless or actively wrong. The nearest-neighbour
statistic below answers the one question the variogram was there for -- "is the structure resolved
at my sampling step?" -- as a purely local comparison that needs no stationarity assumption.

Pure, read-only, stdlib + numpy (scipy optional, only for exact chi-square CIs). No I/O, no
plotting, no gpCAM import -- safe to call from a daemon or a scratch script.

Typical use, from a gpcam daemon or a pre-launch scratch script:

    import noise_helpers as nh

    rep = nh.repeat_stats(y_repeat, groups)          # per-position + pooled sigma
    fit = nh.noise_form(rep)                         # sigma vs signal: form + verdict
    nn  = nh.nn_structure(xy_seed, y_seed, rep.s_pool)   # signal present? resolved?
    card = nh.noise_card(rep, fit, nn, declared_sigma=..., signal_variance=...)
    print(card.text)                                 # -> paste into the launch approval
    assert not card.blocking, card.blockers
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

try:                                     # exact CIs when scipy is present (it is, in the pixi env)
    from scipy.stats import chi2 as _chi2
    _HAVE_SCIPY = True
except Exception:                        # pragma: no cover - graceful degradation
    _HAVE_SCIPY = False

__all__ = [
    "RepeatStats", "FormFit", "NNStructure", "NoiseCard",
    "repeat_stats", "sigma_ci95", "noise_form", "nn_structure",
    "sigma_from_model", "noise_card",
    "CONSTANT", "VALUE_PROPORTIONAL", "INVERTED", "UNDETERMINED",
]


# --------------------------------------------------------------------------------------
# 1. Repeats -> sigma        (docs/noise-model.md §1)
# --------------------------------------------------------------------------------------

@dataclass
class RepeatStats:
    """Per-position and pooled scatter of repeat exposures."""
    labels: list                 # position label per group, in report order
    means: np.ndarray            # ybar_p
    sds: np.ndarray              # s_p   (unbiased, ddof=1)
    counts: np.ndarray           # n_p
    s_pool: float                # pooled sigma
    dof: int                     # sum(n_p - 1)
    ci95: tuple                  # (lo, hi) absolute 95% CI on sigma
    rel_se: float                # 1/sqrt(2*dof)

    @property
    def ci95_factor(self) -> tuple:
        """95% CI expressed as multipliers of s_pool -- the form quoted on the card."""
        if self.s_pool <= 0:
            return (float("nan"), float("nan"))
        return (self.ci95[0] / self.s_pool, self.ci95[1] / self.s_pool)


def repeat_stats(y, groups, labels=None) -> RepeatStats:
    """Pool repeat exposures into a sigma estimate.

    y       : (N,) objective values of the repeat frames
    groups  : (N,) position id per frame (any hashable: int, str, (x,y) tuple)
    labels  : optional display order for the groups

    Positions with fewer than 2 repeats are dropped from the pooled estimate (no variance) but
    still reported, so a truncated seed set is visible rather than silently ignored.
    """
    y = np.asarray(y, dtype=float).reshape(-1)
    groups = np.asarray(groups).reshape(-1)
    if y.size != groups.size:
        raise ValueError("y and groups must have the same length (%d vs %d)" % (y.size, groups.size))

    uniq = list(labels) if labels is not None else list(dict.fromkeys(groups.tolist()))
    means, sds, counts = [], [], []
    ss, dof = 0.0, 0
    for g in uniq:
        yy = y[groups == g]
        yy = yy[np.isfinite(yy)]
        n = yy.size
        counts.append(n)
        means.append(float(np.mean(yy)) if n else float("nan"))
        if n >= 2:
            sds.append(float(np.std(yy, ddof=1)))
            ss += float(np.sum((yy - np.mean(yy)) ** 2))
            dof += n - 1
        else:
            sds.append(float("nan"))

    if dof < 1:
        raise ValueError("no position has >= 2 repeats; cannot estimate sigma")

    s_pool = math.sqrt(ss / dof)
    return RepeatStats(
        labels=uniq,
        means=np.asarray(means), sds=np.asarray(sds), counts=np.asarray(counts),
        s_pool=s_pool, dof=dof,
        ci95=sigma_ci95(s_pool, dof),
        rel_se=1.0 / math.sqrt(2.0 * dof),
    )


def sigma_ci95(s: float, dof: int) -> tuple:
    """Exact 95% CI on sigma from (dof)s^2/sigma^2 ~ chi2(dof); normal approx without scipy."""
    if dof < 1 or not np.isfinite(s):
        return (float("nan"), float("nan"))
    if _HAVE_SCIPY:
        lo = s * math.sqrt(dof / _chi2.ppf(0.975, dof))
        hi = s * math.sqrt(dof / _chi2.ppf(0.025, dof))
        return (lo, hi)
    z = 1.959963985
    rel = 1.0 / math.sqrt(2.0 * dof)
    return (s * max(1e-12, 1.0 - z * rel), s * (1.0 + z * rel))


# --------------------------------------------------------------------------------------
# 2. Form of sigma vs signal        (docs/noise-model.md §1 "Form decision")
# --------------------------------------------------------------------------------------

CONSTANT = "constant"
VALUE_PROPORTIONAL = "value_proportional"
INVERTED = "INVERTED"
UNDETERMINED = "undetermined"


@dataclass
class FormFit:
    """Result of regressing log(s_p) on log|ybar_p|."""
    beta: float                  # slope: 0 = constant, 1 = value-proportional, <0 = inverted
    beta_se: float               # standard error of the slope (nan when P < 3)
    alpha: float                 # sigma = alpha * |y|^beta
    verdict: str                 # CONSTANT | VALUE_PROPORTIONAL | INVERTED | UNDETERMINED
    n_positions: int
    frac_mean: float             # mean(s_p / ybar_p) -- the alpha to use if verdict is proportional
    note: str = ""

    @property
    def rejected(self) -> bool:
        return self.verdict == INVERTED


def noise_form(rep: RepeatStats, k_sigma: float = 1.5) -> FormFit:
    """Decide whether sigma is constant, value-proportional, or (fatally) inverted.

    This is a SIGN TEST, not a measurement of beta -- with n=3 repeats each s_p carries ~50%
    error, so the decision is made against beta's own standard error rather than a fixed
    tolerance. A fixed band cannot work for both cases seen in practice: sampling noise alone
    produces beta ~ -0.25 on a genuinely constant sigma, while the run007 inverted form sits at
    beta ~ -0.45 -- a threshold separating those two is a coin flip, but their significance is not.

    - INVERTED (blocks a launch) only when beta is negative by more than k_sigma standard errors.
    - A negative-but-insignificant beta returns UNDETERMINED with an explicit "possible inversion"
      note, never a clean CONSTANT -- silence there is what let run007 through.

    k_sigma = 1.5 is chosen for SENSITIVITY, not for statistical decorum. Measured over 200 trials
    at the default 5x3 design (verify_noise.py section 2):

        k_sigma      1.0    1.5    2.0    3.0
        false-block   19%    12%     7%     4%    (on a genuinely CONSTANT sigma)
        detects -0.43 76%    58%    40%    13%    (the run007 shape)
        detects -0.8  98%    98%    92%    78%

    A false block costs one conversation at a gate that is already a human decision; a false
    negative costs a campaign. Value-proportional models -- the 11BM default -- are never falsely
    blocked (0% at every k). Even so, 5x3 detects the run007 shape only ~58% of the time, which is
    why the UNDETERMINED warning band below exists: it covers what the block misses.
    """
    m = np.asarray(rep.means, dtype=float)
    s = np.asarray(rep.sds, dtype=float)
    ok = np.isfinite(m) & np.isfinite(s) & (np.abs(m) > 0) & (s > 0)
    P = int(ok.sum())
    if P < 2:
        return FormFit(float("nan"), float("nan"), float("nan"), UNDETERMINED, P, float("nan"),
                       "need >= 2 positions with a finite mean and sd")

    lx, ly = np.log(np.abs(m[ok])), np.log(s[ok])
    if np.ptp(lx) < 1e-9:                    # all positions at the same signal level
        return FormFit(float("nan"), float("nan"), float("nan"), UNDETERMINED, P,
                       float(np.mean(s[ok] / np.abs(m[ok]))),
                       "all positions at one signal level -- form is undeterminable; "
                       "spread the positions or treat sigma as constant")

    beta, logalpha = np.polyfit(lx, ly, 1)
    alpha = math.exp(logalpha)
    frac_mean = float(np.mean(s[ok] / np.abs(m[ok])))

    # Standard error of the slope from the regression residuals (needs >= 3 positions).
    if P >= 3:
        resid = ly - (beta * lx + logalpha)
        s2 = float(np.sum(resid ** 2)) / (P - 2)
        sxx = float(np.sum((lx - lx.mean()) ** 2))
        beta_se = math.sqrt(s2 / sxx) if sxx > 0 and s2 >= 0 else float("nan")
    else:
        beta_se = float("nan")

    lo = beta + k_sigma * beta_se if np.isfinite(beta_se) else beta   # upper edge of the CI
    hi = beta - k_sigma * beta_se if np.isfinite(beta_se) else beta   # lower edge of the CI
    warn_edge = beta + 1.0 * beta_se if np.isfinite(beta_se) else beta

    if lo < 0.0:
        verdict = INVERTED
        note = ("sigma RISES as the signal falls (beta = %.2f +/- %.2f, negative at >%.0f sigma) "
                "-- rejected by docs/noise-model.md; do not launch on this model"
                % (beta, beta_se, k_sigma))
    elif warn_edge < 0.0:
        # Negative by more than 1 SE but less than k_sigma: too weak to block, far too suspicious
        # to call "constant". This band is where a real inversion of the run007 kind lands at the
        # default 5x3 design -- the detection power simply is not there, so it must not pass silently.
        verdict = UNDETERMINED
        note = ("beta = %.2f +/- %.2f: negative but not significant at %.0f sigma. POSSIBLE "
                "INVERSION -- this design cannot resolve it; add positions or repeats, or widen "
                "the signal range, before trusting a constant-sigma model" % (beta, beta_se, k_sigma))
    elif hi > 0.5:
        verdict = VALUE_PROPORTIONAL
        note = "sigma tracks |y| (beta = %.2f) -> use sigma = max(floor, alpha*|y|)" % beta
    elif lo < 0.5:
        verdict = CONSTANT
        note = "sigma flat across signal levels (beta = %.2f) -> use sigma = s_pool" % beta
    else:
        verdict = UNDETERMINED
        note = ("beta = %.2f +/- %.2f straddles the constant and proportional cases -- report both "
                "and let the user choose" % (beta, beta_se))

    if np.isfinite(beta_se) and beta_se > 0.6:
        note += " [beta poorly determined: widen the signal range across positions]"

    return FormFit(float(beta), float(beta_se), alpha, verdict, P, frac_mean, note)


# --------------------------------------------------------------------------------------
# 3. Structure and resolution, without a spatial model     (docs/noise-model.md §2)
# --------------------------------------------------------------------------------------

RESOLVED = "resolved"
UNDER_RESOLVED = "UNDER-RESOLVED"
NO_STRUCTURE = "no structure above noise"


@dataclass
class NNStructure:
    """Nearest-neighbour difference statistics -- local, no stationarity assumption."""
    n_points: int
    nn_dist_median: float        # typical sampling step actually achieved
    nn_dist_min: float
    nn_dist_max: float
    rms_dy: float                # rms difference between nearest-neighbour pairs
    var_y: float                 # variance of the field over the sampled points
    sigma: float                 # the sigma it was compared against (from repeats)
    snr: float                   # var_y / sigma^2 -- is there any signal at all
    ratio: float                 # rms_dy / (sqrt(2)*sigma) -- 1.0 means "neighbours differ by noise only"
    struct_var_at_nn: float      # variance already decorrelated at the NN step (>= 0)
    verdict: str
    n_zero_dist: int = 0         # coincident points excluded (they are repeats, not structure)
    note: str = ""

    @property
    def ell_upper_bound(self):
        """If neighbours differ by more than noise, the correlation length is at or below the
        sampling step. Returns that step, else nan (ell is above it, but unbounded from here)."""
        return self.nn_dist_median if self.verdict == UNDER_RESOLVED else float("nan")


def nn_structure(xy, y, sigma: float, beam_size: float = None,
                 ratio_tol: float = 1.3, snr_tol: float = 2.0) -> NNStructure:
    """Is there structure above the noise, and is the sampling step fine enough to resolve it?

    beam_size : PASS THIS. Pairs closer together than one beam footprint share illuminated sample
        area, so they are correlated by construction -- their difference is suppressed by the
        overlap, not by the field being smooth, and including them biases `ratio` toward 1
        ("looks resolved") no matter how fine the real structure is. The beam is a low-pass
        filter: nothing below it is observable by stepping below it. Pairs under one beam are
        therefore excluded and counted. Omitting beam_size only excludes exactly-coincident
        points, which is right for simulated data and wrong for a real map.

    Both questions answered by comparing NEIGHBOURING measurements against sigma. For two points
    separated by d, E[(y_i - y_j)^2] = 2*sigma^2 + 2*(k(0) - k(d)). So:

        d << ell  ->  k(d) ~ k(0)  ->  rms(dy) ~ sqrt(2)*sigma   (neighbours differ by noise only)
        d >> ell  ->  k(d) ~ 0     ->  rms(dy) >> sqrt(2)*sigma  (neighbours already uncorrelated)

    ratio = rms(dy) / (sqrt(2)*sigma) is therefore ~1 when the field is resolved at the sampling
    step and large when the structure is finer than the step. This is a LOCAL statement: it holds
    wherever the pairs happen to be, and needs no assumption that one covariance describes the
    whole map -- which is exactly what an inhomogeneous sample denies.

    Coincident points (repeat exposures) are excluded: they measure sigma, not structure.
    """
    xy = np.atleast_2d(np.asarray(xy, dtype=float))
    y = np.asarray(y, dtype=float).reshape(-1)
    good = np.isfinite(y) & np.all(np.isfinite(xy), axis=1)
    xy, y = xy[good], y[good]
    n = y.size
    if n < 3:
        raise ValueError("need >= 3 finite points for the NN statistic (got %d)" % n)
    if not (sigma > 0 and np.isfinite(sigma)):
        raise ValueError("sigma must be finite and positive (got %r) -- measure repeats first" % sigma)

    d = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=-1)
    np.fill_diagonal(d, np.inf)
    tol = 1e-12 + 1e-9 * float(np.nanmax(d[np.isfinite(d)]) if np.isfinite(d).any() else 1.0)
    if beam_size is not None and beam_size > 0:
        tol = max(tol, float(beam_size))          # overlapping footprints are not independent
    coincident = int(np.sum(np.isfinite(d) & (d <= tol)) // 2)
    d = np.where(d <= tol, np.inf, d)             # drop repeats / sub-beam pairs

    j = np.argmin(d, axis=1)
    nn_d = d[np.arange(n), j]
    keep = np.isfinite(nn_d)
    if keep.sum() < 3:
        raise ValueError("fewer than 3 points have a distinct neighbour")
    nn_d, dy = nn_d[keep], (y[keep] - y[j[keep]])

    rms_dy = float(np.sqrt(np.mean(dy ** 2)))
    var_y = float(np.var(y, ddof=1))
    snr = var_y / (sigma ** 2)
    ratio = rms_dy / (math.sqrt(2.0) * sigma)
    struct_var = max(rms_dy ** 2 / 2.0 - sigma ** 2, 0.0)

    if snr <= snr_tol:
        verdict = NO_STRUCTURE
        note = ("field variance is only %.1fx sigma^2 -- there may be nothing here to learn. "
                "Check the objective definition before blaming the GP." % snr)
    elif ratio > ratio_tol:
        verdict = UNDER_RESOLVED
        note = ("neighbours %.4g apart already differ by %.1fx the noise, so the correlation "
                "length is AT OR BELOW the sampling step (%.4g). A GP fitting ell much larger "
                "than that is not seeing the data." % (float(np.median(nn_d)), ratio,
                                                       float(np.median(nn_d))))
    else:
        verdict = RESOLVED
        note = ("neighbours differ by only %.2fx the noise, so the field varies slowly across the "
                "sampling step: ell is comfortably ABOVE %.4g." % (ratio, float(np.median(nn_d))))

    return NNStructure(
        n_points=n, nn_dist_median=float(np.median(nn_d)), nn_dist_min=float(np.min(nn_d)),
        nn_dist_max=float(np.max(nn_d)), rms_dy=rms_dy, var_y=var_y, sigma=float(sigma),
        snr=float(snr), ratio=float(ratio), struct_var_at_nn=float(struct_var),
        verdict=verdict, n_zero_dist=coincident, note=note)


# --------------------------------------------------------------------------------------
# 4. Applying the model + the pre-launch card        (docs/noise-model.md §3, §4)
# --------------------------------------------------------------------------------------

def sigma_from_model(y, model: str, frac: float = 0.10, floor: float = 0.0) -> np.ndarray:
    """Per-point sigma for the approved model. The ONLY forms this will produce are
    non-decreasing in |y| -- an inverted model cannot be expressed here by construction."""
    y = np.asarray(y, dtype=float)
    if model == CONSTANT:
        return np.full(y.shape, float(floor))
    if model == VALUE_PROPORTIONAL:
        return np.maximum(float(floor), float(frac) * np.abs(y))
    raise ValueError("unknown noise model %r (expected %r or %r)"
                     % (model, CONSTANT, VALUE_PROPORTIONAL))


@dataclass
class NoiseCard:
    text: str
    blockers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return bool(self.blockers)


def noise_card(rep: RepeatStats, fit: FormFit, nn: NNStructure = None,
               declared_sigma=None, model: str = None, frac: float = None, floor: float = None,
               signal_variance=None, signal_variance_floor=None,
               fitted_ell=None, cv_vs_constant=None,
               signal_variance_floor_ratio: float = 2.0,
               ell_vs_nn_max_ratio: float = 10.0) -> NoiseCard:
    """Assemble the pre-launch noise card: the text to paste into the launch approval, plus
    the blocking/warning verdicts. Thresholds come from config.json -> gpcam.noise.gate.

    Any argument left None is reported as "not supplied" rather than silently passing -- a check
    that did not run must not read as a check that passed.
    """
    L, blockers, warnings = [], [], []
    A = L.append

    A("NOISE MODEL CARD  (contract: docs/noise-model.md)")
    A("")
    A("FORM")
    A("  model     : %s" % (model if model else "(not supplied)"))
    if frac is not None or floor is not None:
        A("  frac/floor: %s / %s" % (frac, floor))
    A("  direction : beta = %.2f +/- %.2f  ->  %s" % (fit.beta, fit.beta_se, fit.verdict))
    if fit.note:
        A("              %s" % fit.note)
    if fit.rejected:
        blockers.append("noise model is INVERTED (beta = %.2f +/- %.2f): sigma rises as the signal "
                        "falls" % (fit.beta, fit.beta_se))
    if fit.verdict == UNDETERMINED:
        warnings.append("sigma-vs-signal form undetermined: %s" % fit.note)

    A("")
    A("REPEATS  (%d positions, dof %d)" % (len(rep.labels), rep.dof))
    A("  %-14s %12s %12s %6s" % ("position", "mean", "sd", "n"))
    for lab, m, s, n in zip(rep.labels, rep.means, rep.sds, rep.counts):
        A("  %-14s %12.6g %12.6g %6d" % (str(lab), m, s, n))
    A("  s_pool    : %.6g" % rep.s_pool)
    A("  95%% CI    : [%.6g, %.6g]  =  [%.2f, %.2f] x s_pool   (rel SE %.0f%%)"
      % (rep.ci95[0], rep.ci95[1], rep.ci95_factor[0], rep.ci95_factor[1], 100 * rep.rel_se))
    A("  CAVEAT    : repeats are a LOWER BOUND on sigma (fixed spot: no sub-beam heterogeneity),")
    A("              and this design pins sigma only to ~a factor of %.1f." % rep.ci95_factor[1])
    A("  NOTE      : s_pool uses ONLY within-position scatter (each position's own mean is")
    A("              subtracted), so sample inhomogeneity between positions never enters sigma.")
    A("              That inhomogeneity is what supplies the %d signal levels the form test needs."
      % len(rep.labels))
    # Pooling presumes one sigma for all positions -- true only if the form came back constant.
    if fit.verdict == VALUE_PROPORTIONAL:
        A("  USE       : sigma = max(floor, %.4g * |y|)   [alpha = mean(s_p/ybar_p); a single"
          % fit.frac_mean)
        A("              pooled number would be WRONG here -- sigma differs by position]")
    elif fit.verdict == CONSTANT:
        A("  USE       : sigma = %.6g  (s_pool; pooling is valid because the form is constant)"
          % rep.s_pool)
    else:
        A("  USE       : form undetermined -- do NOT pool blindly. Present both s_pool = %.6g and"
          % rep.s_pool)
        A("              alpha = %.4g, and let the user pick." % fit.frac_mean)

    A("")
    A("STRUCTURE / RESOLUTION")
    if nn is None:
        A("  NOT SUPPLIED")
        warnings.append("nearest-neighbour structure check not supplied")
    else:
        A("  points            : %d   (coincident pairs excluded: %d)" % (nn.n_points, nn.n_zero_dist))
        A("  NN spacing        : median %.6g   [min %.6g, max %.6g]"
          % (nn.nn_dist_median, nn.nn_dist_min, nn.nn_dist_max))
        A("  Var(y)/sigma^2    : %.2f      (is there any signal at all)" % nn.snr)
        A("  rms(dy_NN)/sqrt2s : %.2f      (1.0 = neighbours differ by noise ONLY)" % nn.ratio)
        A("  verdict           : %s" % nn.verdict)
        A("              %s" % nn.note)
        if nn.verdict == NO_STRUCTURE:
            warnings.append("no structure above the noise (Var/sigma^2 = %.1f) -- check the "
                            "objective definition before launching" % nn.snr)
        if nn.verdict == UNDER_RESOLVED:
            warnings.append("structure is finer than the sampling step (neighbours differ by "
                            "%.1fx noise) -- consider a finer grid or a smaller beam" % nn.ratio)

    A("")
    A("DIAGNOSTICS")
    if declared_sigma is None:
        A("  declared sigma vs s_pool   : NOT SUPPLIED")
        warnings.append("declared sigma not supplied -- cannot check it against the repeats")
    else:
        ds = float(np.mean(np.asarray(declared_sigma, dtype=float)))
        r = ds / rep.s_pool if rep.s_pool > 0 else float("nan")
        A("  declared sigma (mean)      : %.6g   = %.2f x s_pool" % (ds, r))
        if np.isfinite(r) and r > 2.0:
            warnings.append("declared sigma is %.1fx the measured repeat scatter -- the GP is being "
                            "told the data is noisier than it is" % r)
        elif np.isfinite(r) and r < 0.5:
            warnings.append("declared sigma is %.1fx BELOW the measured repeat scatter -- the GP "
                            "will chase noise" % (1.0 / r))

    if signal_variance is None or signal_variance_floor is None:
        A("  signal_variance vs floor   : NOT SUPPLIED")
        blockers.append("signal_variance / its lower bound not supplied -- the master check did not run")
    else:
        r = float(signal_variance) / float(signal_variance_floor)
        A("  signal_variance            : %.6g  = %.2f x its lower bound" % (signal_variance, r))
        if r < signal_variance_floor_ratio:
            blockers.append("signal_variance is at its floor (%.2fx): the model has concluded there "
                            "is NO signal -- flat acquisition, wasted beam. Capping ell is not the "
                            "fix." % r)

    if fitted_ell is not None and nn is not None:
        ell = np.atleast_1d(np.asarray(fitted_ell, dtype=float))
        A("  fitted ell vs NN spacing   : %s  vs %.6g"
          % (np.array2string(ell, precision=4), nn.nn_dist_median))
        if nn.verdict == UNDER_RESOLVED and nn.nn_dist_median > 0:
            worst = float(np.max(ell) / nn.nn_dist_median)
            if worst > ell_vs_nn_max_ratio:
                blockers.append("fitted ell is %.0fx the sampling step while neighbours already "
                                "differ by %.1fx the noise -- the GP is smoothing over structure "
                                "the data resolves" % (worst, nn.ratio))
    else:
        A("  fitted ell vs NN spacing   : NOT SUPPLIED")

    if cv_vs_constant is None:
        A("  posterior CV vs constant   : NOT SUPPLIED")
        warnings.append("posterior-vs-constant CV not supplied")
    else:
        A("  posterior CV vs constant   : %.3f x null" % cv_vs_constant)
        if cv_vs_constant <= 1.0:
            blockers.append("the posterior does not beat a constant predictor (%.3f x null) -- it IS "
                            "a constant painted over the map" % cv_vs_constant)

    A("")
    A("VERDICT: %s" % ("BLOCKED -- %d blocker(s)" % len(blockers) if blockers else "clear to present"))
    for b in blockers:
        A("  BLOCK: %s" % b)
    for w in warnings:
        A("  warn : %s" % w)

    return NoiseCard("\n".join(L), blockers, warnings)
