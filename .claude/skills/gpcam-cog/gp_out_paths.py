"""Tagged, never-overwritten output paths for gpCAM daemon products in <RUN_DIR>/gp_out/.

Why: run009 wrote its per-iteration posterior history to ONE fixed file, and each of 13 daemon
restarts overwrote it, so only the last phase survived. Every daemon start must write its own
file set, named with the run tag team-lead sets in config.json -> run_tag (scripts/make_run_tag.py,
e.g. 'phase4_seq0724_20260809T0528'); this module never invents a phase.

Lives with the gpcam-cog skill (like xray-calc's modules). Usage in a gpCAM daemon:

    sys.path.insert(0, "<repo>/.claude/skills/gpcam-cog")
    from gp_out_paths import launch_tag, tagged_path
    TAG = launch_tag(RUN_DIR, cfg, log=log)           # once, at daemon start
    POST_HISTORY = tagged_path(RUN_DIR, "gpcam_posterior_history", TAG)
    POSTERIOR    = tagged_path(RUN_DIR, "gpcam_posterior", TAG)
    HYPER_CSV    = tagged_path(RUN_DIR, "gpcam_hyperparameters", TAG, ext=".csv")

tagged_path() never returns an existing file: if the name is taken it adds _r2, _r3, ...
"""
import csv
import os
import re


def _last_scan_id(run_dir):
    """Last scan ID if a log records one (column 'scan_id' or 'scan'); None otherwise."""
    for name in ("op_log.csv", "ana_log.csv"):
        path = os.path.join(run_dir, name)
        if not os.path.exists(path):
            continue
        last = None
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                for key in ("scan_id", "scan"):
                    v = (row.get(key) or "").strip()
                    if v:
                        last = v
        if last:
            return re.sub(r"[^0-9A-Za-z]", "", last)
    return None


def launch_tag(run_dir, cfg=None, log=print):
    """Tag for this daemon start. Team-lead owns it: read cfg['run_tag'] (set by
    scripts/make_run_tag.py, e.g. 'phase4_seq0724_20260809T0528'); never compute a phase here.
    Fallback if run_tag is missing: beamline local time only ('YYYYmmddTHHMMSS'), with a warning,
    so a missing tag never overwrites anything. A last scan ID, if a log records one, is appended.
    """
    tag = (cfg or {}).get("run_tag")
    if tag:
        tag = re.sub(r"[^0-9A-Za-z_.-]", "", str(tag))
    else:
        import datetime
        from zoneinfo import ZoneInfo
        tag = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%dT%H%M%S")
        log(f"WARN config.json has no run_tag (team-lead: scripts/make_run_tag.py); using local time '{tag}'")
    scan_id = _last_scan_id(run_dir)
    if scan_id:
        tag += f"_scan{scan_id}"
    return tag


def tagged_path(run_dir, base, tag, ext=".npz"):
    """<run_dir>/gp_out/<base>_<tag><ext>, creating gp_out/; never an existing file (adds _rN)."""
    out = os.path.join(run_dir, "gp_out")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{base}_{tag}{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(out, f"{base}_{tag}_r{n}{ext}")
        n += 1
    return path
