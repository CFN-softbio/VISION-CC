#!/usr/bin/env python3
"""transcript_helpers.py — read a VISION campaign's Claude Code transcripts correctly.

audit-cog's job is to track COMMUNICATION and DECISIONS, not to judge correctness. Doing
that means counting who said what to whom, and every wrong number this project has produced
came from one of the structural traps below. Each is encoded here as a function so it is
solved once:

  1. THE HUB IS BLIND TO SPOKES. Every teammate gets its OWN top-level .jsonl. The
     orchestrator's transcript contains only what the orchestrator sent or received, so a
     hub-only census returns cog<->cog = 0 BY CONSTRUCTION, on any session, forever. This
     project asserted that zero and had it refuted three separate times.
     -> discover_sessions() finds every file; peer traffic REQUIRES the spoke files.

  2. TEAMMATE MESSAGES ARE INJECTED INTO THE `user` ROLE. Counting user-role records as
     "the human" overcounted by 744 in one measured pass.
     -> is_human_turn() uses the structural marker origin.kind, not a text heuristic.

  3. THE ORCHESTRATOR HAS NO agentName. Teammate files carry agentName/agentSetting; the
     hub carries neither. A naive agentName lookup silently DROPS every team-lead record.
     -> session_identity() identifies team-lead by ABSENCE.

  4. ONE FILE CAN HOLD SEVERAL CAMPAIGNS. A resumed session concatenates runs separated by
     long idle gaps; a whole-file count silently mixes them.
     -> session_windows() splits on an idle gap.

  5. NON-MESSAGE RECORDS HAVE timestamp=None. A naive time-sort crashes or misorders.
     -> iter_records() skips them by default.

Stdlib only. No relative imports. Import it directly:

    import sys; sys.path.insert(0, "<repo>/.claude/skills/audit-cog")
    import transcript_helpers as th

CLI:
    python transcript_helpers.py census   [--project DIR] [--gap-hours 6]
    python transcript_helpers.py comms    --out comms.csv [--start ISO] [--end ISO]
"""

import argparse
import collections
import csv
import datetime as _dt
import glob
import json
import os
import re
import sys
import warnings

__all__ = [
    "DEFAULT_PROJECT_DIR", "NON_MESSAGE_TYPES", "HUMAN_INPUT_ATTACHMENTS",
    "SessionIdentity", "discover_archived", "list_archives", "archive_span_days",
    "discover_project_dirs",
    "iter_records", "text_of", "parse_ts", "session_identity", "discover_sessions",
    "is_human_turn", "is_task_notification", "inbound_teammate", "outbound_sends",
    "session_windows", "compaction_count", "build_communication", "channel_counts",
    "verify_peer_delivery", "write_csv",
]

# ---------------------------------------------------------------- constants

# Claude Code keeps a project's transcripts in ~/.claude/projects/<slug>; the slug is the project's
# absolute path with every character other than a letter, digit or '-' turned into '-'.
_REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
DEFAULT_PROJECT_DIR = os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9-]", "-", _REPO))

# Record types that are NOT messages. They carry timestamp=None; including them in a
# time-ordered pass is trap #5.
NON_MESSAGE_TYPES = frozenset({
    "queue-operation", "attachment", "mode", "permission-mode", "ai-title",
    "last-prompt", "file-history-snapshot", "file-history-delta", "system",
})

# TRAP 6 — THE HUMAN SPEAKS ON FOUR CHANNELS, NOT ONE.
# A queued human prompt is stored as type="attachment" with the text at
# attachment.prompt and the marker at attachment.origin.kind == "human". It has NO
# `message` object and NO top-level `origin`, so it is invisible both to a user-role
# census AND to a naive origin.kind check. On run007's offline window these were 33 of
# 132 human inputs -- 25% -- and they carried the session's most substantive science
# questions. They are kept by iter_records() even though `attachment` is skipped
# wholesale; the other attachment types (task_reminder, file, agent_listing_delta, …)
# really are noise.
# The other two channels are NOT records at all and must be counted separately by the
# auditor: AskUserQuestion answers (no user-role turn) and synthetic mass-stop turns.
HUMAN_INPUT_ATTACHMENTS = frozenset({"queued_command"})

INBOUND_PREFIX = "Another Claude session sent a message:"
_TEAMMATE_RE = re.compile(r'<teammate-message\s+teammate_id="([^"]+)"')
_SUMMARY_RE = re.compile(r'summary="([^"]*)"')

COMMUNICATION_COLUMNS = [
    "ts", "session_file", "observer", "observer_role", "direction",
    "sender", "recipient", "channel", "is_idle_notification", "summary",
    "delivered", "text_chars", "uuid",
]


class SessionIdentity(object):
    """Who wrote a given .jsonl. `role` is 'team-lead' when agentName is ABSENT."""

    __slots__ = ("path", "session_id", "agent_name", "agent_setting", "role", "n_sampled")

    def __init__(self, path, session_id, agent_name, agent_setting, n_sampled=0):
        self.path = path
        self.session_id = session_id
        self.agent_name = agent_name
        self.agent_setting = agent_setting
        self.role = "team-lead" if not agent_name else "teammate"
        self.n_sampled = n_sampled

    @property
    def name(self):
        """The name to use as sender/recipient in a ledger."""
        return self.agent_name or "team-lead"

    def __repr__(self):
        return ("SessionIdentity(name=%r, setting=%r, role=%r, file=%r)"
                % (self.name, self.agent_setting, self.role,
                   os.path.basename(self.path)))


# ---------------------------------------------------------------- primitives

def iter_records(path, skip_nonmessage=True, limit=None):
    """Stream one transcript. Tolerant of truncated final lines (live files grow)."""
    n = 0
    try:
        fh = open(path, "r", errors="replace")
    except (IOError, OSError):
        return
    with fh:
        for line in fh:
            if limit is not None and n >= limit:
                return
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # truncated tail of a growing file
            if skip_nonmessage and rec.get("type") in NON_MESSAGE_TYPES:
                # TRAP 6: a queued HUMAN prompt is an `attachment`. Dropping it wholesale
                # loses a quarter of human input, so let that one subtype through.
                if not _is_human_attachment(rec):
                    continue
            n += 1
            yield rec


def _coerce_text(v):
    """Text out of a str, a content-block list, or a list of strings. Never raises.

    Transcript payloads are not schema-stable: the same logical field appears as a bare
    string in some records and a block list in others. Every accessor here goes through
    this rather than assuming.
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        parts = []
        for b in v:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                parts.append(b.get("text") or b.get("prompt") or "")
        return "\n".join(p for p in parts if p)
    if isinstance(v, dict):
        return _coerce_text(v.get("text") or v.get("prompt"))
    return str(v)


def _is_human_attachment(rec):
    """A queued human prompt stored as an attachment (trap 6)."""
    if rec.get("type") != "attachment":
        return False
    att = rec.get("attachment")
    if not isinstance(att, dict):
        return False
    if att.get("type") not in HUMAN_INPUT_ATTACHMENTS:
        return False
    origin = att.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return origin["kind"] == "human"
    return True


def text_of(rec):
    """Concatenated text blocks of a record's message. '' when there are none.

    Also returns the prompt of a queued human attachment (trap 6), which has no
    `message` object at all.
    """
    if _is_human_attachment(rec):
        # observed in the wild as EITHER a plain string OR a content-block list --
        # a synthetic test using only the string form missed this and crashed on
        # real data with AttributeError: 'list' object has no attribute 'strip'.
        return _coerce_text((rec.get("attachment") or {}).get("prompt"))
    m = rec.get("message")
    if not isinstance(m, dict):
        return ""
    c = m.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text") or "")
        return "\n".join(parts)
    return ""


def parse_ts(rec):
    """UTC datetime or None. Never raises."""
    ts = rec.get("timestamp")
    if (not ts or not isinstance(ts, str)) and isinstance(rec.get("attachment"), dict):
        ts = rec["attachment"].get("timestamp")
    if not ts or not isinstance(ts, str):
        return None
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------- identity (trap 3)

def session_identity(path, sample=800):
    """Identify a transcript's author.

    TRAP 3: the orchestrator carries NEITHER agentName NOR agentSetting. Absence is the
    signal, so this returns role='team-lead' rather than dropping the file.

    !! LIMIT -- "lacks agentName => orchestrator" is NOT universally
    safe on a LIVE, GROWING project file. The archived copy of run007's orchestrator has
    agentName absent throughout, but the project copy had picked up
    agentName={'offline': 78} by the time it was re-read. Prefer an ARCHIVED / snapshotted
    transcript when identity matters, and treat role on a growing file as provisional.
    This is one more reason the snapshot-first protocol exists: freeze, then attribute.
    """
    agent_name = agent_setting = session_id = None
    n = 0
    for rec in iter_records(path, skip_nonmessage=False, limit=sample):
        n += 1
        if agent_name is None and rec.get("agentName"):
            agent_name = rec["agentName"]
        if agent_setting is None and rec.get("agentSetting"):
            agent_setting = rec["agentSetting"]
        if session_id is None:
            session_id = rec.get("sessionId") or rec.get("session_id")
        if agent_name and agent_setting and session_id:
            break
    if session_id is None:
        session_id = os.path.splitext(os.path.basename(path))[0]
    return SessionIdentity(path, session_id, agent_name, agent_setting, n)


def list_archives(run_dir):
    """Every frozen transcript archive for this run, oldest first.

        $RUN_DIR/transcripts/transcripts_1_<utc>/       mid-run pass
        $RUN_DIR/transcripts/transcripts_final_<utc>/   completion pass

    Each is a FULL COPY, not a delta -- archives are cumulative, so the final one is a
    superset of any earlier one. NEVER merge two archives or sum counts across them; pick
    ONE and audit it. Sorted with `final` last regardless of timestamp.
    """
    tdir = os.path.join(run_dir, "transcripts")
    dirs = [d for d in sorted(glob.glob(os.path.join(tdir, "transcripts_*")))
            if os.path.isdir(d)]
    return sorted(dirs, key=lambda d: ("final" in os.path.basename(d),
                                       os.path.basename(d)))


def archive_span_days(sessions):
    """Wall-clock span of an archive from file mtimes, in days. Cheap (no parsing).

    A large span is the fingerprint of a CONTAMINATED archive -- one built before
    run-scoping existed, so it holds teammates from other runs. On run004 the existing
    archive spanned ~30 days (June dev sessions swept in beside a July run).
    """
    mts = []
    for s in sessions:
        try:
            mts.append(os.path.getmtime(s.path))
        except OSError:
            pass
    if len(mts) < 2:
        return 0.0
    return (max(mts) - min(mts)) / 86400.0


def discover_archived(run_dir, archive=None, require=True, warn_span_days=7.0):
    """THE PRIMARY SOURCE: one frozen transcript archive.

    `archive` may be a full path, a folder name, or None for the LATEST
    (`transcripts_final_*` if present, else the newest `transcripts_N_*`). Falls back to a
    flat legacy `transcripts/` layout for runs archived before the dated-folder scheme.

    Prefer this over discover_sessions() in every normal case. It is self-contained,
    already frozen, holds this run only, and -- because it was written before you existed
    -- cannot contain YOUR transcript, so the auditor cannot audit itself. Reading
    ~/.claude/projects/ instead reintroduces all four problems at once.

    Returns (sessions, archive_dir) so the pass README can cite exactly what it read.

    Raises when nothing is found and require=True: at completion that absence is a FINDING
    (the archive step did not run, or did not run before the audit), never something to
    paper over with a silent fallback.
    """
    tdir = os.path.join(run_dir, "transcripts")
    if archive:
        adir = archive if os.path.isdir(archive) else os.path.join(tdir, archive)
    else:
        found = list_archives(run_dir)
        adir = found[-1] if found else tdir  # legacy flat layout
    paths = sorted(glob.glob(os.path.join(adir, "*.jsonl")))
    paths += sorted(glob.glob(os.path.join(adir, "agents", "*.jsonl")))
    if not paths and require:
        raise IOError(
            "no archived transcripts under %s -- team-lead's make_session_log.py has not "
            "run (it archives the orchestrator log AND per-agent transcripts in one call). "
            "Report this as a finding rather than falling back to ~/.claude/projects/." % adir)
    sessions = [session_identity(p) for p in paths]

    # CONTAMINATION FLAG. A clean per-run archive spans hours, not weeks. A wide span means
    # the archive was built WITHOUT run-scoping and holds teammates from other runs -- exactly
    # run004's case (~30 days, June dev swept in beside a July run). The auditor MUST then pin
    # the run boundary by reading (see the semantic-boundary note below), because the helper
    # cannot tell which sessions belong to this run.
    span = archive_span_days(sessions)
    if span > warn_span_days:
        warnings.warn(
            "audit archive %s spans %.1f days across %d sessions -- larger than the %.0f-day "
            "sanity limit. Likely NOT run-scoped: it may hold teammates from other runs. "
            "Pin this run's boundary by reading a semantic marker (a sample rename, the first "
            "human turn of the run); session_windows() only splits on idle gaps and will miss "
            "a continuously-resumed multi-run session." % (
                os.path.basename(adir.rstrip("/")), span, len(sessions), warn_span_days),
            stacklevel=2)
    return sessions, adir


def discover_project_dirs(base=None, root_slug=None):
    """Every project dir belonging to this repo.

    TRAP 7 -- TRANSCRIPTS ARE SPLIT ACROSS PROJECT DIRS, KEYED BY EACH AGENT'S CWD.
    A teammate spawned with cwd=<repo>/cms_workspace/runs/runNNN writes to a SEPARATE
    project directory named after that path, not to the repo-root one. On run007 the
    repo-root dir held 5 recent transcripts while the run-dir one held 25, plus two more
    dirs for output/ and audit_out/. Auditing only the root dir silently loses ~85% of
    the agent transcripts -- and since peer traffic lives only in spoke files (trap 1),
    that reads as "the agents barely talked to each other".
    """
    base = base or os.path.dirname(DEFAULT_PROJECT_DIR.rstrip("/"))
    if root_slug is None:
        root_slug = os.path.basename(DEFAULT_PROJECT_DIR.rstrip("/"))
    out = []
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        if not os.path.isdir(d):
            continue
        name = os.path.basename(d)
        if name == root_slug or name.startswith(root_slug + "-"):
            if glob.glob(os.path.join(d, "*.jsonl")):
                out.append(d)
    return out or [DEFAULT_PROJECT_DIR]


def discover_sessions(project_dir=None, min_bytes=1, include_subagents=True,
                      all_project_dirs=True):
    """Every transcript for this repo, identified.

    TRAP 1: peer traffic lives ONLY in the spoke files. Auditing the hub alone reports
    cog<->cog = 0 by construction. Always start here, never from a single path.
    TRAP 7: by default this sweeps EVERY cwd-keyed project dir, not just the root one.
    Pass all_project_dirs=False (or an explicit project_dir) to restrict.
    """
    if project_dir is not None:
        dirs = [project_dir]
    elif all_project_dirs:
        dirs = discover_project_dirs()
    else:
        dirs = [DEFAULT_PROJECT_DIR]
    paths = []
    for d in dirs:
        paths += sorted(glob.glob(os.path.join(d, "*.jsonl")))
        if include_subagents:
            paths += sorted(glob.glob(os.path.join(d, "subagents", "*.jsonl")))
    out = []
    for p in paths:
        try:
            if os.path.getsize(p) < min_bytes:
                continue
        except OSError:
            continue
        out.append(session_identity(p))
    return out


# ---------------------------------------------------------------- who spoke (trap 2)

def is_human_turn(rec):
    """True only for a turn the HUMAN actually produced.

    TRAP 2: teammate messages are injected into the `user` role. Counting user-role
    records as human overcounted by 744 in a measured pass. `origin.kind` is the
    structural discriminator; the text prefix is only a fallback for older records.

    TRAP 6: a QUEUED human prompt is an `attachment` with no `message` and no top-level
    `origin`. It is invisible to both checks above, and was 25% of human input on
    run007. Handled first, below.

    !! DO NOT SUBSTITUTE promptSource FOR origin.kind. Measured on run007's human
    records: typed 77, queued 31, **suggestion_accepted 30**. Filtering
    promptSource in {typed, queued} returns 108 and silently DROPS 30 real human turns.
    `origin.kind == "human"` returns 138, which matches communication.csv's 138
    user_turn rows exactly -- two independent methods, same number. promptSource is used
    below only to EXCLUDE "system", never to whitelist.

    NOT COVERED — count these separately, they are not records:
      * AskUserQuestion answers (a human decision with no user-role turn at all; one
        run007 menu was REJECTED outright, which is a decision leaving no turn)
      * synthetic mass-stop turns
    """
    if _is_human_attachment(rec):
        return bool(text_of(rec).strip())
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return origin["kind"] == "human"
    m = rec.get("message")
    if not isinstance(m, dict) or m.get("role") != "user":
        return False
    if rec.get("isMeta"):
        return False
    if rec.get("promptSource") == "system":
        return False
    t = text_of(rec)
    if not t.strip():
        return False
    for marker in ("<teammate-message", INBOUND_PREFIX, "<system-reminder",
                   "<local-command-", "<command-name>", "<command-message>"):
        if marker in t:
            return False
    c = m.get("content")
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                return False
    return True


def is_task_notification(rec):
    origin = rec.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") == "task-notification"
    return rec.get("promptSource") == "system"


def inbound_teammate(rec):
    """Parse an inbound teammate message, or None.

    Returns {"from", "summary", "is_idle", "chars"}. Idle notifications are detected
    because they are content-free: they are the noise floor in which a real stall is
    invisible, and they must be countable separately from substantive traffic.
    """
    t = text_of(rec)
    if INBOUND_PREFIX not in t and "<teammate-message" not in t:
        return None
    m = _TEAMMATE_RE.search(t)
    sender = m.group(1) if m else None
    if sender is None:
        return None
    s = _SUMMARY_RE.search(t)
    return {
        "from": sender,
        "summary": (s.group(1) if s else "")[:300],
        "is_idle": '"type":"idle_notification"' in t.replace(" ", ""),
        "chars": len(t),
    }


def outbound_sends(rec):
    """Every SendMessage issued in this record.

    Delivery is confirmed from the record's own toolUseResult ("Message sent to X's
    inbox") when present. Send-side counting alone OVERCOUNTS (a send is not a delivery);
    hub-side counting UNDERCOUNTS to zero. Delivery-verified is the honest middle.
    """
    m = rec.get("message")
    if not isinstance(m, dict) or not isinstance(m.get("content"), list):
        return []
    tur = rec.get("toolUseResult")
    tur_txt = json.dumps(tur) if tur is not None else ""
    out = []
    for b in m["content"]:
        if not (isinstance(b, dict) and b.get("type") == "tool_use"
                and b.get("name") == "SendMessage"):
            continue
        inp = b.get("input") or {}
        to = inp.get("to") or inp.get("recipient")
        body = inp.get("message")
        if not isinstance(body, str):
            body = json.dumps(body) if body is not None else ""
        delivered = None
        if tur_txt:
            delivered = ("Message sent to" in tur_txt and (to or "") in tur_txt)
        out.append({
            "to": to,
            "summary": (inp.get("summary") or "")[:300],
            "chars": len(body),
            "delivered": delivered,
            "is_idle": '"type":"idle_notification"' in body.replace(" ", ""),
        })
    return out


# ---------------------------------------------------------------- windows (trap 4)

def session_windows(path, gap_hours=6.0):
    """Split one transcript into campaigns separated by an idle gap.

    TRAP 4: a resumed session concatenates a live run and later analysis in ONE file. A
    whole-file count mixes corpora that were supposed to be compared. Returns
    [{"start","end","n","gap_before_h"}] in order.
    """
    stamps = []
    for rec in iter_records(path):
        t = parse_ts(rec)
        if t is not None:
            stamps.append(t)
    if not stamps:
        return []
    stamps.sort()
    windows = []
    cur_start, prev, n = stamps[0], stamps[0], 0
    gap_before = 0.0
    for t in stamps:
        gap = (t - prev).total_seconds() / 3600.0
        if gap >= gap_hours:
            windows.append({"start": cur_start, "end": prev, "n": n,
                            "gap_before_h": round(gap_before, 2)})
            cur_start, gap_before, n = t, gap, 0
        prev = t
        n += 1
    windows.append({"start": cur_start, "end": prev, "n": n,
                    "gap_before_h": round(gap_before, 2)})
    return windows


def compaction_count(path):
    """Context compactions — a real audit signal: the orchestrator's memory reset here."""
    n = 0
    for rec in iter_records(path, skip_nonmessage=False):
        if rec.get("subtype") == "compact_boundary":
            n += 1
    return n


# ---------------------------------------------------------------- the ledger

def _channel(sender_role, recipient_role, is_human, is_idle):
    if is_human:
        return "human"
    if is_idle:
        return "protocol"
    if sender_role == "team-lead" and recipient_role == "teammate":
        return "task"
    if sender_role == "teammate" and recipient_role == "team-lead":
        return "report"
    if sender_role == "teammate" and recipient_role == "teammate":
        return "peer"
    return "other"


def build_communication(sessions, start=None, end=None, dedup=True):
    """The communication ledger across ALL sessions.

    `sessions` must come from discover_sessions() — passing the hub alone reproduces
    trap 1. Outbound sends are recorded from the sender's file; inbound teammate messages
    from the recipient's. Both are kept: their disagreement IS the delivery signal.
    """
    name_to_role = {}
    for s in sessions:
        name_to_role[s.name] = s.role
    rows = []
    for s in sessions:
        for rec in iter_records(s.path):
            t = parse_ts(rec)
            if t is None:
                continue
            if start and t < start:
                continue
            if end and t > end:
                continue
            uuid = rec.get("uuid") or ""
            base = {
                "ts": t.isoformat(), "session_file": os.path.basename(s.path),
                "observer": s.name, "observer_role": s.role, "uuid": uuid,
            }
            if is_human_turn(rec):
                rows.append(dict(base, direction="in", sender="HUMAN",
                                 recipient=s.name, channel="human",
                                 is_idle_notification=False, summary="",
                                 delivered="", text_chars=len(text_of(rec))))
                continue
            inb = inbound_teammate(rec)
            if inb:
                srole = name_to_role.get(inb["from"], "teammate")
                rows.append(dict(
                    base, direction="in", sender=inb["from"], recipient=s.name,
                    channel=_channel(srole, s.role, False, inb["is_idle"]),
                    is_idle_notification=inb["is_idle"], summary=inb["summary"],
                    delivered=True, text_chars=inb["chars"]))
            for snd in outbound_sends(rec):
                rrole = name_to_role.get(snd["to"], "teammate")
                rows.append(dict(
                    base, direction="out", sender=s.name, recipient=snd["to"],
                    channel=_channel(s.role, rrole, False, snd["is_idle"]),
                    is_idle_notification=snd["is_idle"], summary=snd["summary"],
                    delivered=("" if snd["delivered"] is None else snd["delivered"]),
                    text_chars=snd["chars"]))
    rows.sort(key=lambda r: r["ts"])
    if dedup:
        seen, out = set(), []
        for r in rows:
            k = (r["ts"], r["sender"], r["recipient"], r["direction"], r["uuid"])
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        rows = out
    return rows


def verify_peer_delivery(rows):
    """Cross-check peer sends against the recipient's own inbound record.

    Three numbers exist for peer traffic and they are NOT interchangeable:
      hub-only census   -> 0    (wrong by construction)
      send-side count   -> high (counts sends that may never have landed)
      delivery-verified -> the honest figure
    """
    inbound = set()
    for r in rows:
        if r["direction"] == "in" and r["sender"] != "HUMAN":
            inbound.add((r["sender"], r["recipient"]))
    sent = verified = 0
    unverified = []
    for r in rows:
        if r["direction"] != "out" or r["channel"] != "peer":
            continue
        sent += 1
        if (r["sender"], r["recipient"]) in inbound:
            verified += 1
        else:
            unverified.append(r)
    return {"peer_sent": sent, "peer_delivery_verified": verified,
            "peer_unverified": len(unverified), "unverified_rows": unverified}


def channel_counts(rows, exclude_idle=False):
    c = collections.Counter()
    for r in rows:
        if exclude_idle and r["is_idle_notification"]:
            continue
        c[r["channel"]] += 1
    return c


def write_csv(rows, path, columns=None):
    columns = columns or COMMUNICATION_COLUMNS
    d = os.path.dirname(os.path.abspath(path))
    if d:
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in columns})
    return path


# ---------------------------------------------------------------- CLI

def _cmd_census(args):
    sessions = discover_sessions(args.project)
    print("transcripts: %d" % len(sessions))
    leads = [s for s in sessions if s.role == "team-lead"]
    mates = [s for s in sessions if s.role == "teammate"]
    print("  team-lead (no agentName): %d   teammates: %d" % (len(leads), len(mates)))
    by_setting = collections.Counter(s.agent_setting or "-" for s in mates)
    print("  agent settings: " + ", ".join("%s=%d" % kv for kv in by_setting.most_common()))
    big = sorted(sessions, key=lambda s: os.path.getsize(s.path), reverse=True)[:args.top]
    print("\n%-42s %10s %-16s %s" % ("file", "MB", "agent", "windows(gap>=%gh)" % args.gap_hours))
    for s in big:
        mb = os.path.getsize(s.path) / 1e6
        w = session_windows(s.path, args.gap_hours)
        desc = "; ".join("%s->%s n=%d" % (x["start"].strftime("%m-%d %H:%M"),
                                          x["end"].strftime("%m-%d %H:%M"), x["n"])
                         for x in w[:3])
        if len(w) > 3:
            desc += " …(+%d)" % (len(w) - 3)
        print("%-42s %10.2f %-16s %s" % (os.path.basename(s.path)[:42], mb, s.name[:16], desc))
        if len(w) > 1:
            print("       ^ MULTI-WINDOW: a whole-file count would MIX these corpora (trap 4)")


def _cmd_comms(args):
    sessions = discover_sessions(args.project)
    start = _dt.datetime.fromisoformat(args.start.replace("Z", "+00:00")) if args.start else None
    end = _dt.datetime.fromisoformat(args.end.replace("Z", "+00:00")) if args.end else None
    rows = build_communication(sessions, start, end)
    write_csv(rows, args.out)
    print("wrote %s  (%d rows)" % (args.out, len(rows)))
    cc = channel_counts(rows)
    tot = sum(cc.values()) or 1
    print("\nchannel split:")
    for k, v in cc.most_common():
        print("   %-10s %6d  %5.1f%%" % (k, v, 100.0 * v / tot))
    idle = sum(1 for r in rows if r["is_idle_notification"])
    print("   (idle notifications, content-free: %d = %.1f%%)" % (idle, 100.0 * idle / tot))
    pv = verify_peer_delivery(rows)
    print("\npeer traffic: sent=%d delivery-verified=%d unverified=%d"
          % (pv["peer_sent"], pv["peer_delivery_verified"], pv["peer_unverified"]))
    if pv["peer_sent"] == 0:
        print("   !! zero peer traffic — did you pass ONLY the hub? that returns 0 by construction")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project", default=DEFAULT_PROJECT_DIR)
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("census", help="identify every transcript + show idle-gap windows")
    c.add_argument("--gap-hours", type=float, default=6.0)
    c.add_argument("--top", type=int, default=12)
    c.set_defaults(func=_cmd_census)
    m = sub.add_parser("comms", help="build the communication ledger")
    m.add_argument("--out", required=True)
    m.add_argument("--start")
    m.add_argument("--end")
    m.set_defaults(func=_cmd_comms)
    a = p.parse_args(argv)
    if not getattr(a, "func", None):
        p.print_help()
        return 2
    a.func(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
