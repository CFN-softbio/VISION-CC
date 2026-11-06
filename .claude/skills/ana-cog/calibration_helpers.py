#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
calibration_helpers.py — reusable utilities for SciAnalysis calibration /
circular-average tasks at the 11BM-CMS beamline.

These are SAFE, PURE-ANALYSIS helpers: they read inputs (tiffs, mask files),
never write to data directories, are deterministic, and have NO top-level side
effects. They may be imported and run as part of a cal-check / circular-average
script without separate user approval.

SciAnalysis is imported lazily inside the functions so this module can be
imported cheaply and so callers control sys.path.

----------------------------------------------------------------------------
WHAT'S HERE
----------------------------------------------------------------------------

RING DETECTION — the shared primitive behind both centre and SDD:
  - find_rings              — fine 1-px azimuthal-MEDIAN radial profile + Savitzky-
                              Golay background + find_peaks -> the ring radii, each
                              Kasa-fitted to a circle. `center=None` bootstraps one
                              by GRADIENT INTERSECTION (ring-edge gradients point at
                              the centre); pass a centre for SDD work. `r_min` reaches
                              the low-q rings used for calibration. Returns rings
                              brightest-first with pixel radius R (geometry-free).

BEAM CENTRE — pick by whether a direct-beam frame exists:
  - estimate_direct_beam_center  — ONLY when a DIRECT-BEAM tiff exists (a bright
                                    central spot): intensity-weighted centroid. SAXS.
  - fit_beam_center_rings        — EVERY other case (WAXS/MAXS, no direct beam):
                                    find_rings then take the centre as the mean of the
                                    brightest ring's and the widest ring's Kasa centre;
                                    they must AGREE (`agree_px`). SDD-independent.
                                    (Older crest-fit / line-symmetry finders were
                                    removed; this is the one to use.)

SDD — anchor rings to calibrant lines:
  - refine_sdd_from_rings   — N-RING DISAMBIGUATION. One ring is order n at one SDD
                              and n+1 at another; several rings only line up on integer
                              orders SIMULTANEOUSLY at the true SDD. Tries the brightest
                              rings as each low order (discrete hypotheses, not a blind
                              scan), each fixes an SDD exactly, keeps the one where the
                              MOST rings agree. Scores ONLY the chosen calibrant. Needs a
                              rough `sdd_prior` (SDD_PRIORS_M) to bracket, not to answer.
  - scan_sdd_vs_calibrant   — LEGACY coarse grid scan (mean %-error vs expected q).
                              Superseded by refine_sdd_from_rings; kept as a fallback.

Masks:
  - load_detector_mask_array     — mask PNG -> True=masked bool array (resized).
  - save_mask_png                — render a Mask/bool array to PNG.

Visual check:
  - plot_calibrant_overlay  — 1D circular average with the EXPECTED AgBH orders
                              and CeO2 lines drawn on it (and fitted peaks, if
                              given), so a human can see whether they coincide.

----------------------------------------------------------------------------
USAGE EXAMPLE — mask from the stock beamline PNG
----------------------------------------------------------------------------

    import sys
    SciAnalysis_PATH = cfg['paths']['scianalysis']['value']   # from the run's config.json
    SciAnalysis_PATH in sys.path or sys.path.insert(0, SciAnalysis_PATH)

    from SciAnalysis.XSAnalysis.Data import Calibration, Data2D, Mask
    import calibration_helpers as ch
    import numpy as np

    mask = Mask(cfg['detector']['mask_file'])   # geometry-matched CMS PNG

    # Optional: union in the generic gaps mask for full inter-chip coverage.
    GAPS_PNG = (SciAnalysis_PATH +
                '/SciAnalysis/XSAnalysis/masks/Dectris/Pilatus2M_gaps-mask.png')
    gaps = ch.load_detector_mask_array(GAPS_PNG, mask.data.shape)  # True=masked
    mask.data = (mask.data.astype(bool) & ~gaps).astype(np.uint8)  # 1=valid

    # Optional: write the effective mask PNG for the run record.
    ch.save_mask_png(mask, '/out/effective_mask.png', title='effective mask')

    # ... then build ProcessorXS once and run fit_calibration /
    # circular_average / calibration_check as usual.
----------------------------------------------------------------------------
"""

import os


# ---------------------------------------------------------------------------
# Rule 1 — robust direct-beam center estimate (SEED only; fit_calibration
# refines). Generalized verbatim from run001_ana.
# ---------------------------------------------------------------------------
def estimate_direct_beam_center(tiff_path, loader=None, thresh_frac=0.5):
    """Estimate a ROUGH beam center (x0, y0) from a direct-beam tiff.

    Loads the tiff, thresholds to the bright blob (pixels >= thresh_frac * max),
    and returns the INTENSITY-WEIGHTED CENTROID of that blob. This is robust
    against a single hot / cosmic-ray pixel — unlike a bare argmax, which would
    latch onto a stray spike. The result is a SEED only; the caller is expected
    to refine it with Protocols.fit_calibration on a calibrant (AgBH).

    Parameters
    ----------
    tiff_path : str
        Path to the direct-beam tiff (read-only). Returns None if absent.
    loader : callable, optional
        SciAnalysis image loader, typically `Data2D` (from
        SciAnalysis.XSAnalysis.Data). If None, it is imported lazily so no
        new dependency is introduced. The loader must accept `infile=` and
        expose a `.data` 2D array attribute.
    thresh_frac : float, default 0.5
        Fraction of the peak intensity used to threshold the bright blob.

    Returns
    -------
    (x0, y0) : tuple of float
        Intensity-weighted centroid in pixel coordinates, or
    None
        on any failure (missing file, empty/non-finite image, no blob), so the
        caller can fall back to the detector geometric center.
    """
    try:
        if not tiff_path or not os.path.exists(tiff_path):
            return None

        import numpy as np
        if loader is None:
            # Lazy import: use SciAnalysis' own loader, no new dependency.
            from SciAnalysis.XSAnalysis.Data import Data2D as loader

        data = loader(infile=tiff_path)
        img = np.asarray(data.data, dtype=float)
        if img.size == 0 or not np.isfinite(img).any():
            return None

        peak = float(np.nanmax(img))
        if not np.isfinite(peak) or peak <= 0:
            return None

        blob = img >= (thresh_frac * peak)
        if not blob.any():
            return None

        ys, xs = np.nonzero(blob)
        w = img[ys, xs]
        wsum = float(w.sum())
        if not np.isfinite(wsum) or wsum <= 0:
            return None

        x0 = float((xs * w).sum() / wsum)
        y0 = float((ys * w).sum() / wsum)
        return x0, y0
    except Exception as e:
        print('  [warn] direct-beam centroid failed: {}'.format(e))
        return None


# ---------------------------------------------------------------------------
# Save the EFFECTIVE mask actually applied as a PNG, returning the masked
# fraction. Generalized from run001_ana (Agg backend, white=valid/black=masked,
# origin='upper' to match SciAnalysis 2D images).
# ---------------------------------------------------------------------------
def save_mask_png(mask, out_path, title=None):
    """Render the EFFECTIVE mask to a PNG and return its masked fraction.

    White = valid (1), black = masked (0). Uses the headless Agg backend (no
    DISPLAY needed) and origin='upper' so the rendered mask matches the
    orientation SciAnalysis uses for its 2D images, letting it overlay the data
    correctly.

    Parameters
    ----------
    mask : Mask
        A SciAnalysis Mask whose `.data` is a 2D array (1 = valid, 0 = masked).
    out_path : str
        Output PNG path (the only thing written).
    title : str, optional
        Title prefix; the masked percentage is always appended.

    Returns
    -------
    float
        Masked pixel fraction in [0, 1], or NaN on render failure.
    """
    import numpy as np

    if mask is None or mask.data is None:
        print('[warn] save_mask_png called with empty mask; nothing rendered')
        return float('nan')

    try:
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        import matplotlib
        matplotlib.use('Agg')   # headless: no GUI, no DISPLAY needed
        import matplotlib.pyplot as plt

        md = np.asarray(mask.data)
        valid = (md != 0)
        masked_fraction = 1.0 - float(np.mean(valid))   # fraction of pixels excluded

        if title:
            full_title = '{} (masked {:.1f}%)'.format(title, 100.0 * masked_fraction)
        else:
            full_title = 'Effective mask (masked {:.1f}%)'.format(100.0 * masked_fraction)

        fig, ax = plt.subplots(figsize=(6, 6))
        # white=valid(1), black=masked(0); origin='upper' matches SciAnalysis 2D image.
        ax.imshow(valid.astype(float), cmap='gray', vmin=0, vmax=1,
                  origin='upper', interpolation='nearest')
        ax.set_title(full_title)
        ax.set_xlabel('x (px)')
        ax.set_ylabel('y (px)')
        fig.savefig(out_path, bbox_inches='tight', dpi=150)
        plt.close(fig)

        print('Effective mask saved: {}'.format(out_path))
        print('Masked pixel fraction: {:.4f} ({:.2f}%)'.format(
            masked_fraction, 100.0 * masked_fraction))
        return masked_fraction
    except Exception as e:
        print('[warn] could not render/save mask PNG: {}'.format(e))
        return float('nan')


# ===========================================================================
# MASKS
# ===========================================================================
# Masks come from the stock beamline PNGs (SKILL.md rule 2), not from a
# builder. Returns boolean arrays where True = masked (invalid).
# ---------------------------------------------------------------------------


def load_detector_mask_array(mask_file, target_shape):
    """Load a beamline mask PNG as a boolean array.

    SciAnalysis convention: white(255) = valid, black(0) = masked. Returns
    a boolean array True = masked. Transposes if the loaded shape matches
    the transpose of `target_shape`. Raises on shape mismatch.
    """
    if not os.path.exists(mask_file):
        raise FileNotFoundError(mask_file)
    from PIL import Image
    import numpy as np
    arr = np.asarray(Image.open(mask_file).convert('L'))
    if arr.shape != target_shape:
        if arr.shape == target_shape[::-1]:
            arr = arr.T
        else:
            raise ValueError('mask shape {} does not match tiff {}'
                             .format(arr.shape, target_shape))
    return arr <= 127  # True = masked


# ---------------------------------------------------------------------------
# Geometry calibration (detector-agnostic): ring circle-fit for the beam
# center, and a 1-D SDD scan against a calibrant. Added from the run005 WAXS
# AgBH calibration. Pure-analysis, read-only, deterministic.
#
#   fit_beam_center_circle  — beam center from ring geometry (WAXS / no direct
#                             beam). Iterated algebraic (Kasa) circle fit to a
#                             ring crest. fit_calibration CANNOT do this (it is
#                             distance-only), so use this for the center.
#   scan_sdd_vs_calibrant   — with the center fixed, scan SDD and pick the value
#                             minimising the mean |%-error| of the visible
#                             calibrant rings vs n*q1. q ~ 1/SDD.
#
# Calibrant first-ring q (A^-1): AgBH q1 = 0.1076 (harmonics n*q1);
#                                CeO2 (111) ~ 2.011.
# ---------------------------------------------------------------------------

# Calibrant reference ring positions (A^-1). AgBH is the 11BM-CMS default.
CALIBRANT_Q = {
    'AgBH': {'q1': 0.1076, 'kind': 'harmonic'},      # rings at n*q1
    'CeO2': {'rings': [2.011, 2.322, 3.284, 3.852],  # (111),(200),(220),(311)
             'kind': 'list'},
}


def scan_sdd_vs_calibrant(tiff_path, mask, center, sdd_grid,
                          calibrant='AgBH', wavelength_A=0.9184,
                          det_w=None, det_h=None, pixel_um=172.0,
                          harmonics=(3, 4, 5, 6), output_dir=None,
                          window_frac=0.10):
    """Scan SDD (center fixed) and pick the SDD best matching the calibrant.

    For each SDD in sdd_grid: build a FRESH Calibration (the q-map is cached, so
    a fresh object per SDD is required) + ProcessorXS, run circular_average, find
    the visible calibrant rings, and score the mean |%-error| vs expected ring q.
    q ~ 1/SDD so this is a cheap 1-D scan. Returns the best SDD and per-SDD table.

    Parameters
    ----------
    tiff_path : str
    mask : SciAnalysis Mask
    center : (x0, y0)  fixed beam center in pixels (from fit_beam_center_circle
        or estimate_direct_beam_center)
    sdd_grid : iterable of float  candidate SDDs in metres (seed from the prior:
        WAXS 0.20-0.26; SAXS nearest of 2/3/5 m + 0.2 m * offset)
    calibrant : 'AgBH' or 'CeO2'
    wavelength_A : float  (13.5 keV -> 0.9184)
    det_w, det_h : int  detector size in px; if None, read from the tiff shape
    pixel_um : float  pixel size (Pilatus = 172.0)
    harmonics : tuple  AgBH harmonic orders to test (use orders that are actually
        on the detector; small WAXS often shows n=4,5,6, not n=1,2)
    output_dir : str  scratch dir for the per-SDD circular_average .dat (defaults
        to a temp dir next to the tiff's analysis area)
    window_frac : float  +/- fractional q-window around each expected ring

    Returns
    -------
    dict with keys 'best_sdd', 'best_mae_pct', 'rings' (list of (label, q_meas,
    pct_err) at best SDD), 'table' (list of (sdd, mae_pct)).
    """
    import os
    import numpy as np
    # Lazy SciAnalysis imports (caller controls sys.path).
    from SciAnalysis.XSAnalysis.Data import Calibration, Data2D
    from SciAnalysis.XSAnalysis import Protocols
    from PIL import Image

    if det_w is None or det_h is None:
        h, w = np.array(Image.open(tiff_path)).shape
        det_w = det_w or int(w); det_h = det_h or int(h)

    base = os.path.splitext(os.path.basename(tiff_path))[0]
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(tiff_path)),
                                  '_sdd_scan')
    os.makedirs(output_dir, exist_ok=True)

    # Expected ring positions for the chosen calibrant.
    cal = CALIBRANT_Q.get(calibrant, CALIBRANT_Q['AgBH'])
    if cal['kind'] == 'harmonic':
        q1 = cal['q1']
        expected = [('n%d' % n, n * q1) for n in harmonics]
    else:
        expected = [('r%d' % i, q) for i, q in enumerate(cal['rings'], 1)]

    def _circ(sdd):
        # FRESH Calibration per SDD (q-map is cached on the object).
        c = Calibration(wavelength_A=wavelength_A)
        c.set_image_size(det_w, height=det_h)
        c.set_pixel_size(pixel_size_um=pixel_um)
        c.set_distance(float(sdd))
        c.set_beam_position(float(center[0]), float(center[1]))
        proc = Protocols.ProcessorXS(load_args={'calibration': c, 'mask': mask},
                                     run_args={'verbosity': 0,
                                               'save_results': ['txt']})
        proc.run([tiff_path],
                 [Protocols.circular_average(name='circular_average', ylog=True)],
                 output_dir=output_dir, force=1)
        dat = os.path.join(output_dir, 'circular_average', base + '.dat')
        a = np.genfromtxt(dat, comments='#')
        a = a[np.all(np.isfinite(a), axis=1)]
        return a[:, 0], a[:, 1]

    def _score(q, I):
        Is = np.convolve(I, np.ones(5) / 5, mode='same')
        rings = []
        for label, qexp in expected:
            w = (q > qexp * (1 - window_frac)) & (q < qexp * (1 + window_frac))
            if w.sum() < 3:
                continue
            qq, ii = q[w], Is[w]
            k = int(np.argmax(ii))
            if 0 < k < len(qq) - 1 and ii[k] >= ii[k - 1] and ii[k] >= ii[k + 1]:
                rings.append((label, float(qq[k]),
                              100.0 * (qq[k] - qexp) / qexp))
        if not rings:
            return None, []
        mae = float(np.mean([abs(p) for _, _, p in rings]))
        return mae, rings

    table = []
    best = (float('inf'), None, [])
    for sdd in sdd_grid:
        q, I = _circ(sdd)
        mae, rings = _score(q, I)
        if mae is None:
            table.append((float(sdd), float('nan')))
            continue
        table.append((float(sdd), mae))
        if mae < best[0]:
            best = (mae, float(sdd), rings)

    return {'best_sdd': best[1], 'best_mae_pct': best[0],
            'rings': best[2], 'table': table}


# ---------------------------------------------------------------------------
# Demo (guarded). Does nothing unless run directly AND given valid paths via
# env vars; otherwise just prints the standing rules. No side effects on import.
# ---------------------------------------------------------------------------
def find_rings(tiff_path, mask, center=None, exclude_quadrant=None, n_rings=12,
               r_min=20, bg_sigma=35, grad_pct=88, min_ring_pixels=40, prom_frac=0.04):
    """Detect the scattering rings and rank them by INTENSITY. The shared primitive behind BOTH
    beam-centre finding and SDD refinement — the same brightest ring anchors both.

    Method: background-subtract to enhance rings; keep strong-gradient 'ring-flank' pixels; if
    `center` is None, bootstrap one by GRADIENT INTERSECTION (each ring-flank gradient is radial,
    so the lines through the flank pixels intersect at the centre); build a radial INTENSITY
    profile about that centre; each profile peak is a ring, ranked brightest-first; fit an
    independent Kåsa circle to each ring's pixels.

    Parameters
    ----------
    tiff_path : str            detector image (read-only)
    mask : SciAnalysis Mask    .data 1=valid / 0=masked
    center : (x, y) or None    if given, rings are profiled about it (use the SOLVED centre for
        SDD work); if None, a gradient-intersection centre is bootstrapped (beam-centre finding).
    exclude_quadrant : (x0,y0,x1,y1) or None   a dead rectangle to drop (MAXS lower-right).
    n_rings : int              how many rings to return (brightest first).

    Returns
    -------
    dict: 'center' (the centre rings were profiled about), 'gradient_center', and 'rings' — a list
        of {R (radius px), cx, cy, resid_std, n, intensity}, brightest first. R is geometry-free
        (pure pixel radius); pass the brightest R to refine_sdd_from_rings.
    """
    import numpy as _np
    from PIL import Image as _Image
    from scipy.ndimage import gaussian_filter as _gf, binary_erosion as _erode

    img = _np.array(_Image.open(tiff_path)).astype(float)
    H, W = img.shape
    valid = _np.isfinite(img) & (img > 0)
    try:
        md = _np.asarray(mask.data)
        if md.shape == img.shape:
            valid &= (md > 0)
    except Exception:
        pass
    yy, xx = _np.mgrid[0:H, 0:W]
    if exclude_quadrant:
        x0, y0, x1, y1 = exclude_quadrant
        valid &= ~((xx > x0) & (yy > y0) & (xx < x1) & (yy < y1))
    valid &= (img < _np.nanpercentile(img[valid], 99.9))     # drop the saturated core
    valid = _erode(valid, iterations=3)                       # stay off gap/mask edges

    z = _np.where(valid, img, 0.0); w = valid.astype(float)
    sm = _gf(z, 2) / _np.maximum(_gf(w, 2), 1e-6)
    bg = _gf(z, bg_sigma) / _np.maximum(_gf(w, bg_sigma), 1e-6)
    ring = _np.where(valid, sm - bg, 0.0)

    gy, gx = _np.gradient(ring); gmag = _np.hypot(gx, gy)
    sel = valid & (gmag > _np.nanpercentile(gmag[valid], grad_pct)) & (gmag > 0)
    ys, xs = _np.nonzero(sel)
    d = _np.c_[gx[sel] / gmag[sel], gy[sel] / gmag[sel]]
    px = _np.c_[xs, ys].astype(float)

    if center is not None:
        cx0, cy0 = float(center[0]), float(center[1])
    else:
        keep = _np.ones(len(px), bool); c = px.mean(0)
        for _ in range(6):
            A = _np.zeros((2, 2)); bvec = _np.zeros(2)
            for p, dd in zip(px[keep], d[keep]):
                proj = _np.eye(2) - _np.outer(dd, dd)
                A += proj; bvec += proj @ p
            c = _np.linalg.solve(A, bvec)
            perp = _np.abs((px - c)[:, 0] * (-d[:, 1]) + (px - c)[:, 1] * d[:, 0])
            keep = perp < _np.nanpercentile(perp[keep], 80)
        cx0, cy0 = float(c[0]), float(c[1])

    def _kasa(x, y):
        A = _np.c_[2 * x, 2 * y, _np.ones_like(x)]
        s, *_ = _np.linalg.lstsq(A, x * x + y * y, rcond=None)
        cx, cy = s[0], s[1]; R = _np.sqrt(s[2] + cx * cx + cy * cy)
        return cx, cy, R, float(_np.std(_np.hypot(x - cx, y - cy) - R))

    r = _np.hypot(xs - cx0, ys - cy0)                    # flank-pixel radii (for Kasa banding)
    rmax = min(cx0, cy0, W - cx0, H - cy0, 480)
    rr = _np.hypot(xx - cx0, yy - cy0)

    # FINE 1-px azimuthal-MEDIAN radial profile of the raw image, then a Savitzky-Golay background
    # and find_peaks. The old 3-px/local-max scan merged and missed rings; 1 px + savgol resolves
    # the full harmonic series (and r_min lets it reach the low-q rings used for calibration).
    from scipy.signal import find_peaks as _fp, savgol_filter as _sg
    edges = _np.arange(r_min, rmax, 1.0)
    rcen = 0.5 * (edges[:-1] + edges[1:])
    ri, Ii = rr[valid].ravel(), img[valid].ravel()
    which = _np.digitize(ri, edges) - 1
    prof = _np.array([_np.median(Ii[which == b]) if (which == b).sum() > 30 else _np.nan
                      for b in range(len(rcen))])
    ok = _np.isfinite(prof)
    rcen, prof = rcen[ok], prof[ok]
    if prof.size < 12:
        return {'center': (round(cx0, 1), round(cy0, 1)),
                'gradient_center': (round(cx0, 1), round(cy0, 1)), 'rings': []}
    win = min(51, (prof.size // 2) * 2 - 1)
    bgp = _sg(prof, max(win, 5), 2)
    resid = prof - bgp
    pk, _p = _fp(resid, prominence=_np.nanmax(resid) * prom_frac, distance=5)
    peaks = sorted([(resid[i], rcen[i]) for i in pk], reverse=True)  # brightest (residual) first
    rings, taken = [], []
    for strength, rc in peaks:
        if any(abs(rc - t) < 12 for t in taken):
            continue
        band = (r > r_min) & (r < rmax) & (_np.abs(r - rc) < 8)
        if band.sum() < min_ring_pixels:
            continue
        cx, cy, R, sd = _kasa(xs[band].astype(float), ys[band].astype(float))
        rings.append({'R': round(R, 1), 'cx': round(cx, 1), 'cy': round(cy, 1),
                      'resid_std': round(sd, 2), 'n': int(band.sum()),
                      'intensity': round(float(strength), 1)})
        taken.append(rc)
        if len(rings) >= n_rings:
            break
    return {'center': (round(cx0, 1), round(cy0, 1)),
            'gradient_center': (round(cx0, 1), round(cy0, 1)), 'rings': rings}


# --- radius <-> q <-> SDD (exact, small-angle NOT assumed) -------------------
def _q_from_radius(r_px, sdd_m, wavelength_A, pixel_um=172.0):
    import numpy as _np
    two_theta = _np.arctan((r_px * pixel_um * 1e-6) / sdd_m)
    return 4 * _np.pi / wavelength_A * _np.sin(two_theta / 2.0)


def _sdd_for_radius_q(r_px, q_target, wavelength_A, pixel_um=172.0):
    """SDD that puts a ring of pixel-radius r_px at q_target."""
    import numpy as _np
    two_theta = 2.0 * _np.arcsin(q_target * wavelength_A / (4 * _np.pi))
    return (r_px * pixel_um * 1e-6) / _np.tan(two_theta)


# Common SDD priors at 11BM-CMS (rough guess to identify WHICH calibrant line the brightest ring
# is; the refinement then pins the exact value). SAXS: 5 m in-hutch / ~6 m open-area, less often
# 2 or 3 m. WAXS/MAXS: ~0.25 m, varying a few cm with the setup -- which is why SDD needs refining.
SDD_PRIORS_M = {'SAXS': [2.0, 3.0, 5.0, 6.0], 'WAXS': [0.25], 'MAXS': [0.25]}


def _calibrant_lines(calibrant, q1, ceo2_a, n_max=12):
    """(label, q) list for the calibrant, in q order. AgBH = harmonic n·q1; CeO2 = fluorite lines."""
    import numpy as _np
    if calibrant.upper() == 'CEO2':
        hkl = [(1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1), (2, 2, 2), (4, 0, 0),
               (3, 3, 1), (4, 2, 0), (4, 2, 2), (5, 1, 1)]
        return [('%d%d%d' % h, 2 * _np.pi * _np.sqrt(sum(i * i for i in h)) / ceo2_a) for h in hkl]
    return [('n%d' % n, n * q1) for n in range(1, n_max + 1)]


def refine_sdd_from_rings(tiff_path, mask, center, sdd_prior, wavelength_A=0.9184,
                          calibrant='AgBH', q1=None, ceo2_a=5.411, pixel_um=172.0,
                          tol_pct=1.0, min_rings_agree=2, sdd_bracket=(0.3, 3.0),
                          exclude_quadrant=None, rings=None):
    """Refine SDD by making MULTIPLE detected rings agree on one distance -- N-ring disambiguation.

    One ring can't pin SDD: a ring of radius R is calibrant order n at one SDD and n+1 at another
    (the n-vs-n+1 degeneracy). Several rings only line up on integer orders SIMULTANEOUSLY at the
    true SDD, so we require agreement across rings.

    Method (discrete hypotheses, NOT a blind scan): each of the two brightest rings is tried as
    each low calibrant line; every (anchor ring, line) pair fixes an SDD EXACTLY (pixel radius is
    geometry-free); at that SDD, map every detected ring's radius -> q -> nearest calibrant line and
    count how many land within `tol_pct`. The hypothesis with the MOST agreeing rings wins (ties
    broken by total residual, weighted by ring intensity). `sdd_prior` (see SDD_PRIORS_M) is used
    only to reject hypotheses whose SDD is outside `sdd_bracket * sdd_prior` -- a loose sanity
    bound, not the answer.

    `center` MUST be the solved beam centre (run fit_beam_center_rings first).

    Returns
    -------
    dict: 'sdd_refined', 'n_agree' (rings on integer orders at that SDD), 'accepted'
        (n_agree >= min_rings_agree), 'assignments' (list of {R, label, q_meas, q_expected,
        err_pct}), 'rms_pct', 'sdd_prior', and 'candidates' (the ranked hypotheses, for audit).
        On not-accepted, sdd_refined = sdd_prior unchanged.
    """
    import numpy as _np
    if q1 is None:
        q1 = 2 * _np.pi / 58.38                       # AgBH d001 = 58.38 A
    if rings is None:
        rings = find_rings(tiff_path, mask, center=center,
                           exclude_quadrant=exclude_quadrant)['rings']
    if len(rings) < 1:
        return {'sdd_refined': sdd_prior, 'accepted': False, 'n_agree': 0,
                'assignments': [], 'rms_pct': None, 'sdd_prior': sdd_prior, 'candidates': []}

    lines = _calibrant_lines(calibrant, q1, ceo2_a)
    lo, hi = sdd_bracket[0] * sdd_prior, sdd_bracket[1] * sdd_prior

    def _assign_at(sdd):
        """Match every ring to its nearest calibrant line at this SDD; keep those within tol_pct."""
        out = []
        for g in rings:
            q = float(_q_from_radius(g['R'], sdd, wavelength_A, pixel_um))
            lab, qe = min(lines, key=lambda t: abs(t[1] - q))
            err = 100.0 * (q - qe) / qe
            if abs(err) <= tol_pct:
                out.append({'R': g['R'], 'label': lab, 'q_meas': round(q, 5),
                            'q_expected': round(qe, 5), 'err_pct': round(err, 3),
                            'intensity': g['intensity']})
        return out

    # Hypotheses: each of the 2 brightest rings placed on each candidate line -> a definite SDD.
    cands = []
    for anchor in rings[:2]:
        for lab, qe in lines:
            sdd = float(_sdd_for_radius_q(anchor['R'], qe, wavelength_A, pixel_um))
            if not (lo <= sdd <= hi):
                continue
            asg = _assign_at(sdd)
            if not asg:
                continue
            wrms = _np.sqrt(_np.average([a['err_pct'] ** 2 for a in asg],
                                        weights=[a['intensity'] for a in asg]))
            # distinct integer orders only (a series should not double up on one line)
            n_distinct = len({a['label'] for a in asg})
            cands.append({'sdd': round(sdd, 4), 'anchor_R': anchor['R'], 'anchor_line': lab,
                          'n_agree': n_distinct, 'rms_pct': round(float(wrms), 3),
                          'assignments': asg})
    # rank: most rings agreeing, then tightest weighted rms
    cands.sort(key=lambda c: (-c['n_agree'], c['rms_pct']))

    if not cands:
        return {'sdd_refined': sdd_prior, 'accepted': False, 'n_agree': 0, 'assignments': [],
                'rms_pct': None, 'sdd_prior': sdd_prior, 'candidates': []}
    best = cands[0]
    accepted = best['n_agree'] >= min_rings_agree
    return {'sdd_refined': best['sdd'] if accepted else sdd_prior,
            'n_agree': best['n_agree'], 'accepted': bool(accepted),
            'assignments': best['assignments'], 'rms_pct': best['rms_pct'],
            'sdd_prior': sdd_prior,
            'candidates': [{k: c[k] for k in ('sdd', 'anchor_line', 'n_agree', 'rms_pct')}
                           for c in cands[:6]]}


# ---------------------------------------------------------------------------
def fit_beam_center_rings(tiff_path, mask, exclude_quadrant=None, n_rings=3,
                          bg_sigma=35, grad_pct=88, min_ring_pixels=60):
    """Beam centre by fitting CIRCLES to the scattering arcs. THE robust method when there is no
    direct beam (broad, gappy, partial rings).

    Rings are circles centred on the beam, so their common centre IS the beam centre -- and it is
    INDEPENDENT OF SDD (distance sets only the radii). Detects rings with `find_rings` (gradient-
    intersection bootstrap + intensity-ranked radial profile + per-ring Kåsa fit), then takes the
    beam centre as the mean of the BRIGHTEST ring and the widest agreeing ring.

    Prefer at least one HIGH-INTENSITY ring and one LARGE-RADIUS ring: the bright ring anchors,
    the wide ring gives the lever arm. If their centres DISAGREE (`agree_px` large), the centre is
    not trustworthy (tilt, or a bad ring).

    Parameters
    ----------
    tiff_path : str            detector image (read-only)
    mask : SciAnalysis Mask    .data 1=valid / 0=masked
    exclude_quadrant : (x0,y0,x1,y1) or None
        a dead rectangle to drop (e.g. (490, 620, 1e9, 1e9) for the MAXS dead lower-right).
    n_rings : int              how many rings to fit (reported; brightest used for the centre)

    Returns
    -------
    dict: 'x0', 'y0' (mean of the chosen rings), 'x0_grad', 'y0_grad' (gradient estimate),
        'agree_px' (spread between the two chosen ring centres -- the error bar), 'rings' (list of
        {R, cx, cy, resid_std, n, intensity}).
    """
    import numpy as _np
    det = find_rings(tiff_path, mask, center=None, exclude_quadrant=exclude_quadrant,
                     n_rings=n_rings, bg_sigma=bg_sigma, grad_pct=grad_pct,
                     min_ring_pixels=min_ring_pixels)
    cx0, cy0 = det['gradient_center']
    rings = det['rings']

    # Beam centre = mean of the BRIGHTEST ring and the widest ring that agrees with it.
    two = rings[:1]
    outer = [g for g in rings if g['R'] > 1.8 * rings[0]['R']] if rings else []
    if outer:
        two.append(max(outer, key=lambda g: g['intensity']))
    elif len(rings) > 1:
        two.append(rings[1])
    if two:
        x0 = float(_np.mean([g['cx'] for g in two])); y0 = float(_np.mean([g['cy'] for g in two]))
        agree = (abs(two[0]['cx'] - two[-1]['cx']), abs(two[0]['cy'] - two[-1]['cy']))
    else:
        x0, y0, agree = cx0, cy0, (float('nan'), float('nan'))
    return {'x0': round(x0, 1), 'y0': round(y0, 1), 'x0_grad': round(cx0, 1),
            'y0_grad': round(cy0, 1), 'agree_px': (round(agree[0], 1), round(agree[1], 1)),
            'rings': rings}


# ---------------------------------------------------------------------------
def plot_calibrant_overlay(source, out_path, agbh_q1=None, ceo2_a=None,
                           fitted=None, title=None, xlim=None, ylog=True,
                           agbh_label_every=5, figsize=(14, 6.5), dpi=130):
    """Overlay EXPECTED calibrant ring positions on a 1D circular average.

    The visual counterpart to scan_sdd_vs_calibrant: a scan gives a number, this shows whether the
    predicted lines actually sit on features. Use it on every calibration, and keep the PNG — a
    calibration claim without this picture cannot be checked by anyone later.

    Parameters
    ----------
    source : str | (array, array)
        Path to a SciAnalysis circular_average `.dat` (cols q, I), or a (q, I) pair.
    out_path : str
        PNG to write. Parent dirs are created.
    agbh_q1 : float or None
        AgBH first-order q (0.10763 A^-1 for d001 = 58.38 A). Orders n*q1 inside the measured
        range are drawn. None -> omit AgBH.
        NOTE: on a small WAXS/MAXS detector this comb is dense (tens of lines, spacing ~q1), so
        "a peak is near an AgBH order" is nearly always true and proves nothing. The plot labels
        the count so that is visible rather than implied.
    ceo2_a : float or None
        CeO2 lattice parameter in A (5.411). Fluorite lines 111/200/220/311/222/400 are drawn and
        labelled. None -> omit CeO2.
    fitted : dict or None
        {label: q_fitted} from a peak fit, drawn as dashed lines so measured and expected can be
        compared directly. This is what turns the figure into evidence.
    title, xlim, ylog, agbh_label_every, figsize, dpi
        Presentation.

    Returns
    -------
    dict with 'path', 'q_range', 'agbh_orders' (n range + count), 'ceo2_lines' (label -> q drawn).
    """
    import os as _os
    import numpy as _np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as _plt

    if isinstance(source, str):
        d = _np.loadtxt(source)
        q, I = d[:, 0], d[:, 1]
    else:
        q, I = (_np.asarray(a, dtype=float) for a in source)
    good = _np.isfinite(q) & _np.isfinite(I) & (I > 0)
    q, I = q[good], I[good]
    if q.size < 2:
        raise ValueError('no usable points in the circular average')

    fig, ax = _plt.subplots(figsize=figsize)
    (ax.semilogy if ylog else ax.plot)(q, I, color='0.15', lw=1.4, zorder=4,
                                       label='circular average')
    info = {'q_range': (float(q.min()), float(q.max())), 'ceo2_lines': {}}

    if agbh_q1:
        n0, n1 = int(_np.ceil(q.min() / agbh_q1)), int(q.max() / agbh_q1)
        for n in range(n0, n1 + 1):
            ax.axvline(n * agbh_q1, color='tab:blue', lw=0.9, alpha=0.5, zorder=1,
                       label='AgBH orders $nq_1$ (n=%d..%d, %d lines)' % (n0, n1, n1 - n0 + 1)
                       if n == n0 else None)
            if agbh_label_every and n % agbh_label_every == 0:
                ax.annotate('%d' % n, (n * agbh_q1, I.max() * 1.02), color='tab:blue',
                            fontsize=8, ha='center', va='bottom')
        info['agbh_orders'] = (n0, n1, n1 - n0 + 1)

    if ceo2_a:
        for lab, m in (('111', 3), ('200', 4), ('220', 8), ('311', 11), ('222', 12), ('400', 16)):
            qc = 2 * _np.pi * _np.sqrt(m) / ceo2_a
            if q.min() <= qc <= q.max():
                ax.axvline(qc, color='tab:red', lw=2.0, alpha=0.95, zorder=3,
                           label='CeO$_2$ expected' if not info['ceo2_lines'] else None)
                ax.annotate(lab, (qc, I.max() * 1.02), color='tab:red', fontsize=10,
                            ha='center', va='bottom', weight='bold')
                info['ceo2_lines'][lab] = float(qc)

    if fitted:
        first = True
        for lab, qf in fitted.items():
            if qf is None or not _np.isfinite(qf) or not (q.min() <= qf <= q.max()):
                continue
            ax.axvline(qf, color='tab:green', lw=1.6, ls='--', zorder=3,
                       label='fitted peak' if first else None)
            first = False

    ax.set_xlim(*(xlim if xlim else (q.min(), q.max())))
    ax.set_xlabel(r'$q$ ($\AA^{-1}$)')
    ax.set_ylabel(r'$I(q)$')
    ax.grid(alpha=0.25, which='both')
    ax.legend(frameon=False, fontsize=9, loc='lower left')
    if title:
        ax.set_title(title, fontsize=10, loc='left')
    fig.tight_layout()
    _os.makedirs(_os.path.dirname(_os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    _plt.close(fig)
    info['path'] = out_path
    return info


# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print(__doc__)
    print('This module is a library of pure-analysis helpers; import it, do not '
          'rely on running it directly. See the usage example above.')
