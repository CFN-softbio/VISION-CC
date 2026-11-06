#!/usr/bin/env python3
"""verify_audit.py — check transcript_helpers.py against hand-verifiable references.

Run after any change to the helpers, or to confirm the env on a new host:

    pixi run check-audit          (or: python verify_audit.py)
    python verify_audit.py --no-live      # synthetic checks only, no transcripts needed

Two tiers:
  SYNTHETIC — records built here, so the expected answer is known by construction. Each
              targets one of the traps in SKILL.md §2 (count lives there, not here --
              this docstring already went stale once by hardcoding it).
  LIVE      — run007's real transcripts. These pin numbers that three independent audits
              agreed on; a change means either a real regression or a real discovery, and
              either way it must be explained, not silently accepted.
"""
import argparse
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcript_helpers as th  # noqa: E402

_PASS = _FAIL = 0
_FAILURES = []


def check(label, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("  PASS  %s" % label)
    else:
        _FAIL += 1
        _FAILURES.append(label)
        print("  FAIL  %s   %s" % (label, detail))


def rec(role="user", text="", **kw):
    r = {"type": "user" if role == "user" else "assistant",
         "timestamp": kw.pop("timestamp", "2026-08-01T21:00:00.000Z"),
         "uuid": kw.pop("uuid", "u-0"),
         "message": {"role": role, "content": [{"type": "text", "text": text}]}}
    r.update(kw)
    return r


# ------------------------------------------------------------------ trap 2
def t_human_turns():
    print("\n[trap 2] real human turns vs injected teammate messages")
    human = rec(text="lets end it, do report", origin={"kind": "human"},
                promptSource="typed")
    check("origin.kind=human -> human turn", th.is_human_turn(human))

    notif = rec(text=th.INBOUND_PREFIX + '\n<teammate-message teammate_id="gp-2">hi',
                origin={"kind": "task-notification"}, promptSource="system")
    check("origin.kind=task-notification -> NOT human", not th.is_human_turn(notif))
    check("  ...and IS a task notification", th.is_task_notification(notif))

    # fallback path: no origin field at all (older records)
    legacy_tm = rec(text=th.INBOUND_PREFIX + '\n<teammate-message teammate_id="writer">x')
    check("no origin + teammate wrapper -> NOT human (fallback)",
          not th.is_human_turn(legacy_tm))

    tr = {"type": "user", "timestamp": "2026-08-01T21:00:00.000Z", "uuid": "u-1",
          "message": {"role": "user",
                      "content": [{"type": "tool_result", "content": "ok"}]}}
    check("tool_result -> NOT human", not th.is_human_turn(tr))

    meta = rec(text="<local-command-stdout>Set model</local-command-stdout>", isMeta=True)
    check("isMeta -> NOT human", not th.is_human_turn(meta))

    check("assistant role -> NOT human", not th.is_human_turn(rec(role="assistant", text="hi")))
    check("empty text -> NOT human", not th.is_human_turn(rec(text="   ")))


# ------------------------------------------------------------------ trap 6
def t_queued_human(tmpdir):
    print("\n[trap 6] the QUEUED human channel (an attachment, not a message)")
    q = {"type": "attachment", "timestamp": "2026-08-01T20:58:15.201Z", "uuid": "q-1",
         "attachment": {"type": "queued_command",
                        "prompt": "the ring is about 0.1076 use rhat peak",
                        "commandMode": "prompt", "origin": {"kind": "human"},
                        "timestamp": "2026-08-01T20:58:15.201Z"}}
    check("queued_command -> IS a human turn", th.is_human_turn(q))
    check("text_of() returns the prompt",
          th.text_of(q) == "the ring is about 0.1076 use rhat peak",
          "got %r" % th.text_of(q))
    check("parse_ts() resolves it", th.parse_ts(q) is not None)

    # REGRESSION: prompt is a content-block LIST in some real records. A synthetic test
    # using only the string form passed, then crashed on live data with
    # AttributeError: 'list' object has no attribute 'strip'.
    qlist = {"type": "attachment", "timestamp": "2026-08-01T21:00:00Z", "uuid": "q-L",
             "attachment": {"type": "queued_command", "origin": {"kind": "human"},
                            "prompt": [{"type": "text", "text": "block form"}]}}
    check("queued prompt as BLOCK LIST -> still human", th.is_human_turn(qlist))
    check("  ...and text extracted", th.text_of(qlist) == "block form",
          "got %r" % th.text_of(qlist))
    qstrs = {"type": "attachment", "timestamp": "2026-08-01T21:00:01Z", "uuid": "q-S",
             "attachment": {"type": "queued_command", "origin": {"kind": "human"},
                            "prompt": ["a", "b"]}}
    check("queued prompt as STRING LIST -> handled", th.text_of(qstrs) == "a\nb",
          "got %r" % th.text_of(qstrs))
    qnone = {"type": "attachment", "timestamp": "2026-08-01T21:00:02Z", "uuid": "q-N",
             "attachment": {"type": "queued_command", "origin": {"kind": "human"},
                            "prompt": None}}
    check("queued prompt None -> NOT human, no crash", not th.is_human_turn(qnone))

    noise = {"type": "attachment", "timestamp": "2026-08-01T20:58:16Z", "uuid": "q-2",
             "attachment": {"type": "task_reminder", "prompt": "reminder text"}}
    check("task_reminder attachment -> NOT human", not th.is_human_turn(noise))

    empty = {"type": "attachment", "timestamp": "2026-08-01T20:58:17Z", "uuid": "q-3",
             "attachment": {"type": "queued_command", "prompt": "  ",
                            "origin": {"kind": "human"}}}
    check("empty queued prompt -> NOT human", not th.is_human_turn(empty))

    # the regression that caused this test to exist: iter_records must KEEP the queued
    # human prompt while still dropping the other attachment noise.
    import json
    p = os.path.join(tmpdir, "queued.jsonl")
    with open(p, "w") as fh:
        fh.write(json.dumps(q) + "\n")
        fh.write(json.dumps(noise) + "\n")
        fh.write(json.dumps(rec(text="typed", origin={"kind": "human"})) + "\n")
    kept = list(th.iter_records(p))
    check("iter_records keeps queued human + typed, drops task_reminder",
          len(kept) == 2, "got %d" % len(kept))
    humans = sum(1 for r in th.iter_records(p) if th.is_human_turn(r))
    check("both human channels counted (typed + queued)", humans == 2, "got %d" % humans)


# ------------------------------------------------------------------ trap 3
def t_identity(tmpdir):
    print("\n[trap 3] orchestrator is identified by ABSENCE of agentName")
    import json
    lead = os.path.join(tmpdir, "lead.jsonl")
    mate = os.path.join(tmpdir, "mate.jsonl")
    with open(lead, "w") as fh:
        fh.write(json.dumps(rec(text="hi", sessionId="S-lead")) + "\n")
    with open(mate, "w") as fh:
        fh.write(json.dumps(rec(text="hi", sessionId="S-mate",
                                agentName="gp-2", agentSetting="gpcam-cog")) + "\n")
    a, b = th.session_identity(lead), th.session_identity(mate)
    check("no agentName -> role=team-lead", a.role == "team-lead", "got %r" % a.role)
    check("no agentName -> name='team-lead'", a.name == "team-lead", "got %r" % a.name)
    check("agentName present -> role=teammate", b.role == "teammate", "got %r" % b.role)
    check("agentName present -> name=gp-2", b.name == "gp-2", "got %r" % b.name)
    check("agentSetting captured", b.agent_setting == "gpcam-cog", "got %r" % b.agent_setting)


# ------------------------------------------------------------------ trap 4/5
def t_windows_and_skips(tmpdir):
    print("\n[trap 4] idle-gap window split   [trap 5] timestamp=None records")
    import json
    p = os.path.join(tmpdir, "multi.jsonl")
    ts = ["2026-08-01T20:00:00Z", "2026-08-01T21:00:00Z",   # window 1
          "2026-08-03T18:00:00Z", "2026-08-03T18:30:00Z"]   # window 2 (44 h later)
    with open(p, "w") as fh:
        for i, t in enumerate(ts):
            fh.write(json.dumps(rec(text="m%d" % i, timestamp=t)) + "\n")
        # trap 5: non-message records with timestamp=None must not break the sort
        for typ in ("mode", "file-history-snapshot", "queue-operation"):
            fh.write(json.dumps({"type": typ, "timestamp": None}) + "\n")
    w = th.session_windows(p, gap_hours=6.0)
    check("splits into 2 windows", len(w) == 2, "got %d" % len(w))
    if len(w) == 2:
        check("window 1 has 2 records", w[0]["n"] == 2, "got %d" % w[0]["n"])
        check("gap recorded ~44 h", 43 < w[1]["gap_before_h"] < 46,
              "got %s" % w[1]["gap_before_h"])
    n_msg = sum(1 for _ in th.iter_records(p))
    check("non-message types skipped (4 kept, not 7)", n_msg == 4, "got %d" % n_msg)
    n_all = sum(1 for _ in th.iter_records(p, skip_nonmessage=False))
    check("...but reachable when asked", n_all == 7, "got %d" % n_all)

    single = th.session_windows(p, gap_hours=100.0)
    check("huge gap_hours -> 1 window", len(single) == 1, "got %d" % len(single))


# ------------------------------------------------------------------ messages
def t_messages():
    print("\n[messages] inbound parse, idle detection, outbound + delivery")
    tm = rec(text=th.INBOUND_PREFIX +
             '\n<teammate-message teammate_id="ana-2" color="pink" summary="mask done">\nbody')
    got = th.inbound_teammate(tm)
    check("inbound sender parsed", got and got["from"] == "ana-2", "got %r" % (got,))
    check("inbound summary parsed", got and got["summary"] == "mask done")
    check("inbound not flagged idle", got and not got["is_idle"])

    idle = rec(text=th.INBOUND_PREFIX +
               '\n<teammate-message teammate_id="gp-2">\n{"type":"idle_notification",'
               '"from":"gp-2","idleReason":"available"}\n</teammate-message>')
    gi = th.inbound_teammate(idle)
    check("idle notification detected", gi and gi["is_idle"], "got %r" % (gi,))

    check("plain text -> not inbound", th.inbound_teammate(rec(text="hello")) is None)

    send = {"type": "assistant", "timestamp": "2026-08-01T21:00:00Z", "uuid": "u-2",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "SendMessage",
                 "input": {"to": "writer-2", "message": "plot it", "summary": "plot"}}]},
            "toolUseResult": {"success": True,
                              "message": "Message sent to writer-2's inbox"}}
    outs = th.outbound_sends(send)
    check("one outbound parsed", len(outs) == 1, "got %d" % len(outs))
    if outs:
        check("recipient parsed", outs[0]["to"] == "writer-2")
        check("delivery confirmed from toolUseResult", outs[0]["delivered"] is True)

    undel = dict(send, toolUseResult=None)
    o2 = th.outbound_sends(undel)
    check("no toolUseResult -> delivered=None (unknown, not False)",
          o2 and o2[0]["delivered"] is None, "got %r" % (o2[0]["delivered"] if o2 else None))
    check("non-SendMessage tool ignored", th.outbound_sends(rec(role="assistant")) == [])


# ------------------------------------------------------------------ ledger
def t_peer_accounting():
    print("\n[peer] a send is not a delivery")
    rows = [
        {"direction": "out", "channel": "peer", "sender": "gp-2", "recipient": "ana-2"},
        {"direction": "out", "channel": "peer", "sender": "gp-2", "recipient": "ghost"},
        {"direction": "in", "channel": "peer", "sender": "gp-2", "recipient": "ana-2"},
        {"direction": "out", "channel": "task", "sender": "team-lead", "recipient": "gp-2"},
    ]
    v = th.verify_peer_delivery(rows)
    check("peer sends counted (task excluded)", v["peer_sent"] == 2, "got %d" % v["peer_sent"])
    check("delivery-verified = 1", v["peer_delivery_verified"] == 1,
          "got %d" % v["peer_delivery_verified"])
    check("unverified = 1", v["peer_unverified"] == 1, "got %d" % v["peer_unverified"])

    cc = th.channel_counts([{"channel": "peer", "is_idle_notification": False},
                            {"channel": "peer", "is_idle_notification": True}])
    check("channel_counts totals 2", cc["peer"] == 2)
    cc2 = th.channel_counts([{"channel": "peer", "is_idle_notification": False},
                             {"channel": "peer", "is_idle_notification": True}],
                            exclude_idle=True)
    check("exclude_idle drops the content-free one", cc2["peer"] == 1)


# ------------------------------------------------------------------ contamination flag
def t_archive_span(tmpdir):
    print("\n[archive] a wide date span warns (contaminated / not run-scoped)")
    import json
    import warnings as _w

    day = 86400.0

    def build_run(name, mtimes):
        """A run dir whose transcripts/agents/ holds files with the given mtimes."""
        rd = os.path.join(tmpdir, name)
        adir = os.path.join(rd, "transcripts", "agents")
        os.makedirs(adir)
        for i, mt in enumerate(mtimes):
            p = os.path.join(adir, "s%d.jsonl" % i)
            with open(p, "w") as fh:
                fh.write(json.dumps(rec(text="x", agentName="gp-%d" % i)) + "\n")
            os.utime(p, (mt, mt))
        return rd

    tight = build_run("tight", [1_000_000, 1_000_000 + 3 * 3600])       # 3 h apart
    wide = build_run("wide", [1_000_000, 1_000_000 + 30 * day])         # 30 d apart

    sess_t, _ = th.discover_archived(tight)
    sess_w, _ = th.discover_archived(wide)
    check("span of a tight archive < 1 day", th.archive_span_days(sess_t) < 1.0,
          "got %.2f" % th.archive_span_days(sess_t))
    check("span of a wide archive ~30 days", 29 < th.archive_span_days(sess_w) < 31,
          "got %.2f" % th.archive_span_days(sess_w))

    def warns_from(run_dir):
        with _w.catch_warnings(record=True) as w:
            _w.simplefilter("always")
            th.discover_archived(run_dir)
            return [x for x in w if "spans" in str(x.message)]

    check("wide archive triggers discover_archived warning", len(warns_from(wide)) == 1)
    check("tight archive is silent", len(warns_from(tight)) == 0)


# ------------------------------------------------------------------ live
def t_live():
    print("\n[live] run007 regression pins — three audits agreed on these")
    if not os.path.isdir(th.DEFAULT_PROJECT_DIR):
        print("  SKIP  transcripts not present on this host")
        return
    sessions = th.discover_sessions()
    check("discovers >= 40 transcripts", len(sessions) >= 40, "got %d" % len(sessions))
    mates = [s for s in sessions if s.role == "teammate"]
    check("finds teammate sessions (spokes exist)", len(mates) >= 15, "got %d" % len(mates))
    settings = set(s.agent_setting for s in mates if s.agent_setting)
    for want in ("op-cog", "ana-cog", "gpcam-cog", "writer-cog"):
        check("cog setting present: %s" % want, want in settings)

    orch = [s for s in sessions
            if s.session_id.startswith("8785cc80")]
    if orch:
        w = th.session_windows(orch[0].path, gap_hours=6.0)
        check("orchestrator file is MULTI-window (trap 4 is real here)", len(w) >= 2,
              "got %d" % len(w))

    start = _dt.datetime.fromisoformat("2026-08-01T20:30:00+00:00")
    end = _dt.datetime.fromisoformat("2026-08-02T11:35:00+00:00")
    rows = th.build_communication(sessions, start, end)
    check("live-run ledger non-empty", len(rows) > 500, "got %d" % len(rows))
    v = th.verify_peer_delivery(rows)
    check("PEER SENDS == 73 (matches historian2 + audit-online)",
          v["peer_sent"] == 73, "got %d — investigate before accepting" % v["peer_sent"])
    check("delivery-verified <= sent", v["peer_delivery_verified"] <= v["peer_sent"])
    check("peer traffic NOT zero (trap 1 avoided)", v["peer_sent"] > 0)
    cc = th.channel_counts(rows)
    for ch in ("human", "task", "report", "peer"):
        check("channel present: %s" % ch, cc.get(ch, 0) > 0, "got %d" % cc.get(ch, 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-live", action="store_true", help="skip real-transcript checks")
    a = ap.parse_args()

    import tempfile
    print("=" * 68)
    print("verify_audit.py — transcript_helpers self-check")
    print("=" * 68)
    with tempfile.TemporaryDirectory() as td:
        t_human_turns()
        t_queued_human(td)
        t_identity(td)
        t_windows_and_skips(td)
        t_messages()
        t_peer_accounting()
        t_archive_span(td)
    if not a.no_live:
        t_live()

    print("\n" + "=" * 68)
    print("PASS %d   FAIL %d" % (_PASS, _FAIL))
    if _FAILURES:
        print("failed:")
        for f in _FAILURES:
            print("   - %s" % f)
    print("=" * 68)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
