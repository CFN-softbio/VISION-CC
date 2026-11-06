#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
stitch_pilatus.py -- multi-position Pilatus stitcher for 11BM (CMS). CLI or library.

Merges frames taken at two (or more) detector positions into one image with the
inter-module GAPS FILLED:

    final = sum_i (data_i * mask_i) / sum_i (mask_i)

shifting each position onto a common grid first. Uncovered pixels get SENTINEL (-2);
downstream, mask with `data > -2` and do NOT apply the gaps mask, or you discard exactly
what the stitch recovered. Output is uint32 TIFF (so -2 reads back as -2 in PIL mode 'I').

Distilled from StitchPilatus/stitch_800k.ipynb. Three deliberate differences, each a bug
there:
  * the notebook averages `-2` dead-pixel FLAGS in as if they were counts, halving any
    pixel flagged at one position and valid at the other (75 px/frame on our MAXS data);
  * it pairs by scan number + a hand-set `interval`, globbed as a bare substring, so
    `interval=1` mis-pairs any run with several angles per position;
  * it silently drops repeat measurements of the same sample/x/th.

Usage:
    stitch_pilatus.py --input <raw_dir | one.tiff> [--output-dir DIR] [--limit N]
                      [--scianalysis <config.json paths.scianalysis>]
    stitch_pilatus.py --input <raw_dir> --dry-run          # show pairing, write nothing

Detector and shift are auto-resolved; override with --detector / --shift-x / --shift-y.
"""

from __future__ import print_function

import os
import re
import sys
import glob
import argparse

import numpy as np
from PIL import Image


__all__ = [
    'DETECTORS', 'SENTINEL',
    'parse_name', 'match_key', 'find_groups', 'check_pairing',
    'identify_detector', 'measure_shift', 'verify_shift',
    'stitch_files', 'stitch_arrays', 'load_gaps_mask', 'save_stitched',
]

# SciAnalysis's Dectris gaps masks. SciAnalysis lives at config.json -> paths.scianalysis;
# pass it as --scianalysis or export SCIANALYSIS_PATH.
MASK_SUBDIR = os.path.join('SciAnalysis', 'XSAnalysis', 'masks', 'Dectris')
MASK_DIR = os.path.join(os.environ.get('SCIANALYSIS_PATH', ''), MASK_SUBDIR)

SENTINEL = -2            # "no position covered this pixel"

# shifts[i] = (dx, dy) applied to position i to bring it onto position 0's grid;
# dy > 0 shifts UP, dx > 0 shifts RIGHT. 30 px is the standard CMS pos1->pos2 move on
# both detectors (2M value measured on a GISAXS dataset). It is a convention, not
# a law -- verify_shift() re-derives it from the data on every run.
_SHIFTS = [(0, 0), (0, 30), (30, 0), (30, 30)]

DETECTORS = {
    'pilatus800k2': {'size': (981, 1043), 'shifts': _SHIFTS,
                     'mask': os.path.join(MASK_DIR, 'Pilatus800k2_gaps-mask.png')},
    'pilatus800k':  {'size': (981, 1043), 'shifts': _SHIFTS,
                     'mask': os.path.join(MASK_DIR, 'Pilatus800k_gaps-mask.png')},
    'pilatus2m':    {'size': (1475, 1679), 'shifts': _SHIFTS,
                     'mask': os.path.join(MASK_DIR, 'Pilatus2M_gaps-mask.png')},
}

# <sample>_<pos>_<seq>_x<x>_th<th>_<exp>s_<uid>_<frame>_<det>.tiff
_POS = re.compile(r'_(pos\d+)_')
_SEQ = re.compile(r'_pos\d+_(\d+)_')
_TH = re.compile(r'_th([-\d.]+)_')
_X = re.compile(r'_x(-?[\d.]+)_')
_EXP = re.compile(r'_([\d.]+)s_')

# Must be identical across positions: two positions are the same measurement.
IDENTITY_FIELDS = ('sample', 'x', 'th', 'exposure', 'detector')


def parse_name(path):
    """Filename -> field dict, or None if there is no _posN_ field (not stitchable)."""
    stem = re.sub(r'\.tiff?$', '', os.path.basename(path))
    m = _POS.search(stem)
    if not m:
        return None
    pos = m.group(1)
    g = lambda rx: (rx.search(stem).group(1) if rx.search(stem) else None)
    seq = _SEQ.search(stem)
    return {'path': path, 'stem': stem, 'pos': pos,
            'sample': stem.split('_' + pos + '_')[0],
            'seq': int(seq.group(1)) if seq else None,
            'th': g(_TH), 'x': g(_X), 'exposure': g(_EXP),
            'detector': stem.split('_')[-1]}


def match_key(info):
    """Fields identifying one measurement, excluding seq/uid which always differ."""
    return tuple(info[f] for f in IDENTITY_FIELDS)


def find_groups(source_dir, positions, match_by='key', interval=1, pattern='*',
                verbose=True):
    """Group frames into {key: {pos: info}} sets to stitch together.

    match_by='key'      pair on IDENTITY_FIELDS. Recommended: no arithmetic, so the
                        pos1->pos2 scan offset (which depends on how many frames were
                        taken per position) never has to be known.
    match_by='interval' notebook behaviour: seq + interval*i within a sample.
    """
    files = sorted(glob.glob(os.path.join(source_dir, pattern + '.tiff')) +
                   glob.glob(os.path.join(source_dir, pattern + '.tif')))
    parsed = [p for p in (parse_name(f) for f in files) if p]
    groups, n_repeat = {}, 0

    if match_by == 'key':
        # A key can recur: same sample re-measured later. Bucket and pair by sequence
        # order rather than collapsing, which would silently drop the repeat.
        buckets = {}
        for i in parsed:
            if i['pos'] in positions:
                buckets.setdefault(match_key(i), {}).setdefault(i['pos'], []).append(i)
        for key, by_pos in buckets.items():
            for lst in by_pos.values():
                lst.sort(key=lambda i: (i['seq'] is None, i['seq']))
            depth = max(len(v) for v in by_pos.values())
            n_repeat += depth > 1
            for n in range(depth):
                tag = key if depth == 1 else key + ('rep{}'.format(n + 1),)
                groups[tag] = {p: v[n] for p, v in by_pos.items() if n < len(v)}
        if verbose and n_repeat:
            print('  repeated keys    : {} -- paired in sequence order, not merged'
                  .format(n_repeat))
    else:
        idx = {(i['sample'], i['pos'], i['seq']): i for i in parsed}
        first = positions[0]
        for i in parsed:
            if i['pos'] != first or i['seq'] is None:
                continue
            grp = {first: i}
            for n, pos in enumerate(positions[1:], start=1):
                p = idx.get((i['sample'], pos, i['seq'] + interval * n))
                if p:
                    grp[pos] = p
            groups[(i['sample'], i['seq'])] = grp

    complete = {k: g for k, g in groups.items() if len(g) == len(positions)}
    partial = {k: g for k, g in groups.items() if len(g) != len(positions)}
    if verbose:
        print('  files found      : {} ({} without _posN_, skipped)'
              .format(len(files), len(files) - len(parsed)))
        print('  complete groups  : {}'.format(len(complete)))
        if partial:
            print('  INCOMPLETE       : {} -- not stitched:'.format(len(partial)))
            for g in sorted(partial.values(), key=lambda g: str(sorted(g))):
                miss = ','.join(p for p in positions if p not in g)
                print('      {}  missing[{}]'.format(g[sorted(g)[0]]['stem'], miss))
    return complete, partial


def check_pairing(groups, positions, max_offset=30, verbose=True):
    """Validate pairing before any pixels are touched. Two independent checks:

    1. Scan-number offset, consistent WITHIN each sample (it equals frames-per-position,
       so it differs legitimately BETWEEN samples -- one raw dir can hold a standard shot
       back-to-back at +1 next to a sample at +5), and no larger than max_offset.
    2. IDENTITY_FIELDS agree inside every group.

    Neither suffices alone: a uniformly wrong interval yields a perfectly consistent
    offset and is caught only by (2); ragged mis-pairing is caught only by (1).

    Returns (ok, offsets).
    """
    ref = positions[0]
    offsets, bad_fields = {}, {}
    for g in groups.values():
        for pos in positions[1:]:
            a, b = g[ref]['seq'], g[pos]['seq']
            if a is not None and b is not None:
                offsets.setdefault((g[ref]['sample'], pos), []).append(b - a)
        for f in IDENTITY_FIELDS:
            vals = {i[f] for i in g.values() if i[f] is not None}
            if len(vals) > 1:
                bad_fields.setdefault(f, []).append((g[ref]['stem'], sorted(vals)))

    ok = True
    if verbose:
        print('\nPAIRING CHECK  (offset consistent within each sample; fields identical '
              'within each group)')

    per_pos = {}
    for (sample, pos), offs in offsets.items():
        per_pos.setdefault(pos, {})[sample] = offs
    for pos in sorted(per_pos):
        samples = per_pos[pos]
        tally = {}
        for offs in samples.values():
            for o in offs:
                tally[o] = tally.get(o, 0) + 1
        if verbose:
            print('  {} offset from {} : {}'.format(
                pos, ref, ', '.join('{:+d} (x{})'.format(o, tally[o])
                                    for o in sorted(tally))))
        ragged = [(s, sorted(set(o))) for s, o in sorted(samples.items())
                  if len(set(o)) > 1]
        if ragged:
            ok = False
            if verbose:
                print('    !! INCONSISTENT WITHIN A SAMPLE -- probable mis-pairing:')
                for s, u in ragged:
                    print('        {}  offsets {}'.format(s, u))
        elif verbose and len(tally) > 1:
            print('    {} distinct offsets across {} samples -- OK, each sample is '
                  'internally consistent'.format(len(tally), len(samples)))
        if tally and max(abs(o) for o in tally) > max_offset:
            ok = False
            if verbose:
                print('    !! |offset| exceeds --max-offset {}'.format(max_offset))

    if bad_fields:
        ok = False
        if verbose:
            print('  !! FIELD MISMATCH -- these are not the same measurement:')
            for f in IDENTITY_FIELDS:
                bad = bad_fields.get(f)
                if bad:
                    print('      {:<10} differs in {} group(s), e.g. {} -> {}'
                          .format(f, len(bad), bad[0][0], bad[0][1]))
    elif verbose:
        print('  identity fields   : {} agree in every group'
              .format(', '.join(IDENTITY_FIELDS)))
    if verbose:
        print('  verdict           : {}'.format('OK' if ok else 'PROBLEM (see above)'))
    return ok, offsets


def _shift(arr, dx, dy, fill=0):
    """Shift by (dx right, dy up), filling what moves in."""
    out = np.full_like(arr, fill)
    h, w = arr.shape
    ys, yd = (dy, 0) if dy >= 0 else (0, -dy)
    xd, xs = (dx, 0) if dx >= 0 else (0, -dx)
    hh, ww = h - abs(dy), w - abs(dx)
    if hh > 0 and ww > 0:
        out[yd:yd + hh, xd:xd + ww] = arr[ys:ys + hh, xs:xs + ww]
    return out


def load_gaps_mask(mask_file, shape):
    """Gaps mask as a boolean VALID map (True = usable)."""
    m = np.array(Image.open(mask_file).convert('I')).astype(float)
    if m.shape != shape:
        raise ValueError('mask {} != frame {} (wrong detector?)'.format(m.shape, shape))
    if m.max() <= 0:
        raise ValueError('mask {} is entirely zero'.format(mask_file))
    return (m / m.max()) > 0.5


def identify_detector(input_path, pattern='*'):
    """Identify the detector from one frame: dimensions, then gaps-mask fit.

    Size alone cannot separate 800k from 800k2 (both 981x1043) -- and neither can the
    masks' valid FRACTION, which is 0.7425 for both. The same dead area is arranged
    differently, so the pixel pattern settles it (1.0000 vs 0.6287 in practice).
    """
    if os.path.isfile(input_path):
        probe = input_path
    else:
        cands = sorted(glob.glob(os.path.join(input_path, pattern + '.tiff')) +
                       glob.glob(os.path.join(input_path, pattern + '.tif')))
        if not cands:
            raise SystemExit('ERROR: no frames under {}; pass --detector.'
                             .format(input_path))
        probe = cands[0]

    arr = np.array(Image.open(probe).convert('I'))
    h, w = arr.shape
    hits = [n for n, d in DETECTORS.items() if d['size'] == (w, h)]
    if not hits:
        raise SystemExit('ERROR: {} is {}x{}, matching no registry entry ({}).'
                         .format(os.path.basename(probe), w, h,
                                 ', '.join('{}={}x{}'.format(n, *DETECTORS[n]['size'])
                                           for n in sorted(DETECTORS))))
    how = '{}x{}'.format(w, h)
    if len(hits) > 1:
        valid = arr >= 0
        scores = {}
        for n in hits:
            try:
                scores[n] = float((load_gaps_mask(DETECTORS[n]['mask'],
                                                  arr.shape) == valid).mean())
            except Exception:
                pass
        ranked = sorted(scores, key=lambda n: -scores[n])
        if not ranked or (len(ranked) > 1 and
                          scores[ranked[0]] - scores[ranked[1]] < 0.001):
            raise SystemExit('ERROR: {} matches {} and their masks fit equally well; '
                             'pass --detector.'.format(how, ', '.join(sorted(hits))))
        how += '; by mask fit ({})'.format(
            ', '.join('{}={:.4f}'.format(n, scores[n]) for n in ranked))
        hits = ranked
    print('  detector   : {} ({} in {})'.format(hits[0], how, os.path.basename(probe)))
    return hits[0]


def measure_shift(a, b, search=60):
    """Measure (dx, dy) bringing frame b onto frame a's grid.

    Phase correlation on log intensity gives the magnitude robustly; its sign convention
    is easy to invert, so the sign is settled empirically by shifting both ways and
    keeping whichever correlates better on commonly-valid pixels.

    Returns (dx, dy, score, runner_up). A small score gap means "do not trust this".
    """
    def prep(x):
        y = np.where(x > 0, np.log1p(np.maximum(x, 0)), 0.0)
        return y - y.mean()

    R = np.fft.rfft2(prep(a)) * np.conj(np.fft.rfft2(prep(b)))
    cc = np.fft.irfft2(R / (np.abs(R) + 1e-12), s=a.shape)
    dy, dx = np.unravel_index(np.argmax(cc), cc.shape)
    h, w = a.shape
    dy -= h if dy > h // 2 else 0
    dx -= w if dx > w // 2 else 0
    if abs(dy) > search or abs(dx) > search:
        return None, None, 0.0, 0.0

    def agreement(ddx, ddy):
        bs = _shift(b, ddx, ddy, fill=-9.0)
        v = (a > 0) & (bs > 0)
        return (float(np.corrcoef(np.log1p(a[v]), np.log1p(bs[v]))[0, 1])
                if v.sum() >= 1000 else -1.0)

    cand = {(dx, dy): agreement(dx, dy), (-dx, -dy): agreement(-dx, -dy)}
    best, worst = max(cand, key=cand.get), min(cand, key=cand.get)
    return best[0], best[1], cand[best], cand[worst]


def verify_shift(group, positions, shifts, min_margin=0.02, verbose=True):
    """Re-derive the shift from one real pair and compare with what will be used.

    Cheap insurance against the rare beamtime moved by something other than 30 px -- a
    wrong shift still produces a plausible image, so it never announces itself.

    Returns (status, measured): True confirmed, None inconclusive, False contradicted.
    None is distinct from True on purpose; calling an unverifiable result "confirmed"
    would be false assurance.
    """
    a = np.array(Image.open(group[positions[0]]['path']).convert('I')).astype(float)
    measured, mismatch, unclear = {}, False, False

    for i, pos in enumerate(positions[1:], start=1):
        b = np.array(Image.open(group[pos]['path']).convert('I')).astype(float)
        dx, dy, score, runner = measure_shift(a, b)
        want = shifts[i]
        measured[pos] = (dx, dy, score, runner)

        if dx is None:
            unclear = True
            if verbose:
                print('  {} : INCONCLUSIVE (no correlation peak); keeping {}'
                      .format(pos, want))
            continue
        if verbose:
            print('  {} : measured ({:+d}, {:+d})  configured ({:+d}, {:+d})   '
                  'corr {:.3f} vs {:.3f} inverted'
                  .format(pos, dx, dy, want[0], want[1], score, runner))

        # (0,0) cannot be a real move: the correlation locked onto detector-fixed
        # structure (gaps/beamstop) rather than the sample. It also makes the sign test
        # degenerate, since +0 == -0. Common when much of the frame is masked.
        if (dx, dy) == (0, 0) or score - runner < min_margin:
            unclear = True
            if verbose:
                why = ('measured zero shift, so the correlation locked onto '
                       'detector-fixed structure, not the sample'
                       if (dx, dy) == (0, 0) else
                       'the two signs score within {:.3f}'.format(score - runner))
                print('      INCONCLUSIVE: {}. Keeping the configured shift; this is '
                      'NOT evidence against it.'.format(why))
        elif (dx, dy) != want:
            mismatch = True
            if verbose:
                print('      !! MISMATCH: data say ({:+d}, {:+d}). 30 px is the usual '
                      'move but exceptions happen -- if this beamtime differed, re-run '
                      'with --shift-x {} --shift-y {}.'.format(dx, dy, dx, dy))

    return (False if mismatch else (None if unclear else True)), measured


def stitch_arrays(datas, valid, shifts):
    """Average positions onto a common grid. Returns (array, covered fraction)."""
    if not (len(datas) == len(valid) == len(shifts)):
        raise ValueError('datas, valid and shifts must be the same length')
    acc = np.zeros(datas[0].shape, dtype=float)
    cnt = np.zeros(datas[0].shape, dtype=float)
    for d, v, (dx, dy) in zip(datas, valid, shifts):
        vf = v.astype(float)
        acc += _shift(d * vf, dx, dy)
        cnt += _shift(vf, dx, dy)
    covered = cnt > 0
    out = np.full(acc.shape, float(SENTINEL))
    out[covered] = acc[covered] / cnt[covered]
    return out, float(covered.mean())


def stitch_files(paths, mask_file, shifts, size=None):
    """Stitch one frame path per position, in position order."""
    datas, shape = [], None
    for p in paths:
        a = np.array(Image.open(p).convert('I')).astype(float)
        if shape is None:
            shape = a.shape
        elif a.shape != shape:
            raise ValueError('{} is {}, expected {}'
                             .format(os.path.basename(p), a.shape, shape))
        datas.append(a)
    if size is not None and shape != (size[1], size[0]):
        raise ValueError('frames are {} but registry says {} -- wrong --detector?'
                         .format(shape, (size[1], size[0])))
    gaps = load_gaps_mask(mask_file, shape)
    # Negative pixels are Dectris bad/inactive FLAGS, not counts -- excluding them is
    # the whole point vs the notebook, which averages them in and halves the result.
    return stitch_arrays(datas, [gaps & (a >= 0) for a in datas], shifts)


def save_stitched(arr, outfile):
    """uint32 TIFF, matching the notebook so existing readers keep working."""
    Image.fromarray(arr.astype(np.uint32)).save(outfile)


def main():
    ap = argparse.ArgumentParser(description='Stitch multi-position Pilatus frames.')
    ap.add_argument('--input', required=True, help='raw DIRECTORY or a single .tiff')
    ap.add_argument('--output-dir', default=None, help='default <input>/../stitched')
    ap.add_argument('--detector', default='auto', choices=['auto'] + sorted(DETECTORS))
    ap.add_argument('--positions', default='pos1,pos2', help='reference position first')
    ap.add_argument('--match-by', default='key', choices=['key', 'interval'])
    ap.add_argument('--interval', type=int, default=1, help='with --match-by interval')
    ap.add_argument('--pattern', default='*', help='glob over basenames')
    ap.add_argument('--limit', type=int, default=0, help='stitch at most N groups')
    ap.add_argument('--mask', default=None, help='override the registry mask')
    ap.add_argument('--scianalysis', default=None,
                    help='SciAnalysis root (config.json paths.scianalysis); default $SCIANALYSIS_PATH')
    ap.add_argument('--shift-x', type=int, default=None)
    ap.add_argument('--shift-y', type=int, default=None)
    ap.add_argument('--suffix', default='_stitched')
    ap.add_argument('--force', action='store_true', help='overwrite existing outputs')
    ap.add_argument('--dry-run', action='store_true', help='report only, write nothing')
    ap.add_argument('--max-offset', type=int, default=30)
    ap.add_argument('--ignore-pairing-check', action='store_true')
    ap.add_argument('--no-verify-shift', action='store_true')
    args = ap.parse_args()

    if args.scianalysis:
        for d in DETECTORS.values():
            d['mask'] = os.path.join(args.scianalysis, MASK_SUBDIR, os.path.basename(d['mask']))

    positions = [p.strip() for p in args.positions.split(',') if p.strip()]
    if len(positions) < 2:
        raise SystemExit('ERROR: need at least two positions.')

    det_name = (identify_detector(args.input, args.pattern)
                if args.detector == 'auto' else args.detector)
    det = DETECTORS[det_name]

    if args.shift_x is not None or args.shift_y is not None:
        dx, dy = args.shift_x or 0, args.shift_y or 0
        shifts, src = [(dx * i, dy * i) for i in range(len(positions))], 'command line'
    else:
        if len(positions) > len(det['shifts']):
            raise SystemExit('ERROR: registry defines {} shift(s), {} requested.'
                             .format(len(det['shifts']), len(positions)))
        shifts, src = det['shifts'][:len(positions)], 'registry'

    mask_file = args.mask or det['mask']
    if not os.path.isfile(mask_file):
        raise SystemExit('ERROR: mask not found: {}'.format(mask_file))

    inp = os.path.abspath(args.input)
    if os.path.isdir(inp):
        source_dir, single = inp, None
    elif os.path.isfile(inp):
        source_dir, single = os.path.dirname(inp), inp
    else:
        raise SystemExit('ERROR: --input not found: {}'.format(inp))
    out_dir = args.output_dir or os.path.join(
        os.path.dirname(os.path.normpath(source_dir)), 'stitched')

    print('=' * 78)
    print('STITCH  detector={}  positions={}'.format(det_name, ','.join(positions)))
    print('  source     : {}\n  output     : {}'.format(source_dir, out_dir))
    print('  mask       : {}'.format(mask_file))
    print('  shifts     : {}   [from {}]'.format(shifts, src))
    print('  match-by   : {}{}'.format(args.match_by,
          '  (interval={})'.format(args.interval)
          if args.match_by == 'interval' else ''))
    print('=' * 78)

    complete, _ = find_groups(source_dir, positions, args.match_by, args.interval,
                              args.pattern)
    if single:
        info = parse_name(single)
        if not info:
            raise SystemExit('ERROR: {} has no _posN_ field.'
                             .format(os.path.basename(single)))
        complete = {k: g for k, g in complete.items()
                    if any(i['path'] == single for i in g.values())}
    if not complete:
        raise SystemExit('ERROR: nothing to stitch.')

    if not check_pairing(complete, positions, args.max_offset)[0] \
            and not (args.dry_run or args.ignore_pairing_check):
        raise SystemExit('\nABORTED: pairing check failed. Mis-paired frames produce '
                         'images that look fine and are wrong. Fix --pattern, or use '
                         '--ignore-pairing-check if you have confirmed the pairing.')

    if not args.no_verify_shift:
        print('\nSHIFT CHECK  (re-measured from the data)')
        try:
            status, _ = verify_shift(complete[sorted(complete, key=str)[0]],
                                     positions, shifts)
            print('  {}'.format({True: 'configured shift CONFIRMED by the data.',
                                 None: 'configured shift NOT VERIFIED (inconclusive) -- '
                                       'used as given; neither confirmed nor '
                                       'contradicted.',
                                 False: 'see mismatch above.'}[status]))
        except Exception as exc:
            print('  could not verify ({!r}); using the configured shift.'.format(exc))

    # After the checks, so they still see the whole dataset.
    if args.limit and len(complete) > args.limit:
        keep = sorted(complete, key=str)[:args.limit]
        print('\n  --limit {}: stitching {} of {} group(s)'
              .format(args.limit, len(keep), len(complete)))
        complete = {k: complete[k] for k in keep}

    if args.dry_run:
        print('\nDRY RUN -- would stitch {} group(s):'.format(len(complete)))
        for g in sorted(complete.values(), key=lambda g: g[positions[0]]['stem']):
            print('  {}'.format(g[positions[0]]['stem']))
            for p in positions:
                print('      {:<6} {}'.format(p, os.path.basename(g[p]['path'])))
        return 0

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    done = skipped = errors = 0
    cov = []
    for g in sorted(complete.values(), key=lambda g: g[positions[0]]['stem']):
        stem = g[positions[0]]['stem']
        outfile = os.path.join(out_dir, stem + args.suffix + '.tiff')
        if os.path.isfile(outfile) and not args.force:
            print('  exists, skipping (--force to overwrite): {}'.format(stem))
            skipped += 1
            continue
        try:
            arr, c = stitch_files([g[p]['path'] for p in positions], mask_file, shifts,
                                  size=det['size'])
            save_stitched(arr, outfile)
            cov.append(c)
            done += 1
            print('  {}{}  ->  coverage {:.4f}'.format(stem, args.suffix, c))
        except Exception as exc:
            errors += 1
            print('  ERROR on {}: {!r}'.format(stem, exc))

    print('\n' + '=' * 78)
    print('DONE. stitched {}, skipped {}, errors {}.'.format(done, skipped, errors))
    if cov:
        try:
            one = float(load_gaps_mask(mask_file,
                                       (det['size'][1], det['size'][0])).mean())
            print('  coverage {:.4f}..{:.4f}  vs {:.4f} for a single frame  '
                  '-> +{:.2f}% of detector recovered'
                  .format(min(cov), max(cov), one, 100 * (min(cov) - one)))
        except Exception:
            print('  coverage {:.4f}..{:.4f}'.format(min(cov), max(cov)))
    print('  uncovered pixels = {}; downstream mask is (data > {})'
          .format(SENTINEL, SENTINEL))
    print('  output: {}'.format(out_dir))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
