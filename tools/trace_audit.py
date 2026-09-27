# The trace audit: a file's INTERIOR against the combo counter.
#
# Every repair here is graded by one number - the converter's taps + hold ticks equal to the
# judged count the result screen certifies - and a file can hit that number through compensating
# errors: a tick too many in one hold and one too few in another, a tap the game never judged and
# a tap the file lacks. The number cannot see that; the combo counter can. On a play that counted
# every event (a full combo: maxcombo == judged) the counter is a running count of the judged
# events, so at any quiet instant its read minus the file's own running count F(t) is the file's
# cumulative error up to there: 0 all the way through a right file, and a step that STAYS wherever
# a wrong one gained or lost an event. Houseplan S17 (3d17dae) is exact in total and reads -1 from
# 14 s to 38 s; Wedding Crashers S10 (c40c089) reads +1 from 49 s to 92 s.
#
#   python -X utf8 -B tools/trace_audit.py chart "<chart>" [--file <ssc>] [--base <ssc> | --base-rev <rev> | --whole]
#                                                  [--offset S --clock PCT] [--json]
#   python -X utf8 -B tools/trace_audit.py controls [--workers N]
#   python -X utf8 -B tools/trace_audit.py power    [--workers N] [--per-chart N] [--seed S]
#   python -X utf8 -B tools/trace_audit.py corpus   [--workers N] [--date YYYY-MM-DD] [--out-dir DIR]
#   python -X utf8 -B tools/trace_audit.py crops    ["<chart>" ...] [--out <dir under work/rails-audit-scratch>]
#   python -X utf8 -B tools/trace_audit.py version
# (--workers is capped at 6; --no-decode never decodes footage to measure a missing clock)
#
# WHAT IS READ. F(t) is the file's judged events in chart time, enumerated from piu-annotate's own
# lattice converter (the tap rows, each hold head that is not a tap row, and every tick-lattice
# point a hold is held across, outside warps and fakes, that no row already sits on) and checked
# against the converter's taps + ticks - a chart whose enumeration disagrees is not audited. The
# video clock is the tick loop's: the file's own notes matched on screen (note_extract, then
# extract_repair.align). It is taken from the extraction and tick loops' census records (newest
# first) when the file's timing still matches the file it was measured on, and otherwise measured
# here, in an overlay under the scratch dir that reads the shared work/ caches and never writes
# them (a write guard refuses it); the display lag comes from tick_repair.measure_lag on the
# chart's isolated taps. A read counts only at a QUIET instant: its cut at least `quiet` from every
# judged event (a player's GREAT lands up to ~80 ms off the note, and a 30 fps frame adds 33 ms)
# and outside every hold region. A play with no BAD or MISS is one run (nothing resets the
# counter), filtered to its non-decreasing chain; a play with breaks is cut into runs at resets
# (tick_repair.runs). Each run is fitted with a piecewise-constant level (err = read - F), and a
# level held by `strong_reads` agreeing reads over at least `strong_span` seconds is STRONG. Only
# strong levels are evidence.
#
# THE READER'S KNOWN MISREADS are dropped before anything is fitted, each only where the read is
# EXACTLY that misread of the value the counter should show (docs/EVIDENCE-RULES.md, the misread
# table): any 9 read as 5, in any digit and any number of digits at once (the Phoenix 1 atlas does
# this - ASDF D10's 139 as 135, Iolite Sky D21's 9xx as 5xx for ten seconds; bucket 3 will fix the
# atlas, and until then a units-5 read exactly 4 below F, a tens-5 read 40 below, a hundreds-5
# read 400 below is unreliable, not evidence), any 9 read as 8 (Slam S5's 89 as 88 and then 90-98
# as 80-88), dropped leading digits (118 as 18), a truncation shadow (210 as 21), and a rail's
# leading 1 over the zero-padded counter (004 as 104). The value the counter should show is the
# file's count plus the level the play holds - and, on a play the counter never resets, the file's
# count itself as well, so one misread that slips through cannot carry the level off. A real file
# error moves EVERY read by the same amount, so dropping the few whose digits happen to match a
# misread pattern never hides it.
#
# AN EDIT is a stretch where the audited block's judged events differ from the base block's (the
# import commit's, a23cee5, by default): difference events closer than `merge_gap` seconds, or in
# one hold region, are one edit. Each edit gets
#   FLAT       a strong read within `k_rows` judged rows before it and after it, every strong
#              read in that neighbourhood at level 0, and no stretch inside it longer than
#              2 x k_rows judged rows without one;
#   OFF        a strong read in or within k_rows rows of it at a level other than 0 - the reads
#              disagree with the file around this edit (the reason says on which side);
#   UNCOVERED  anything else: no strong read near enough on a side, a reset between the two
#              sides, a GOOD that could hide an event, a timing change, no scan, no clock.
# Never FLAT without reads: no structural anchor (the counter's blank start, its rest at maxcombo)
# stands in for one, because on an exact chart the rest is the certified total by construction.
# On a play with breaks the level is relative to its run, so the two sides must be in one run and
# agree with each other. A play with GOODs never audits FLAT (a GOOD neither breaks nor increments
# the counter, so it could hide exactly the event an edit lost). A level that moves within a run
# is OFF only when nothing but the file explains it: a fall no bigger than the play's GOODs, a
# move of more than `small_move`, or any move on a play whose reads split into more runs than it
# has BADs and MISSes (misreads imitating resets) is UNCOVERED.
#
# COUNTER-DERIVED EDITS. An edit that changes hold ticks under a #TICKCOUNTS the base did not have
# was priced by the counter (the counter loop, the tick loop, their lattice re-authoring) or by
# closure. The reads that priced it cannot also vouch for it, so for such a chart every read whose
# cut falls within `bracket` seconds of a hold region those edits touch is removed before anything
# is fitted, the edit is labelled counter-derived, and FLAT then means the counter OUTSIDE those
# brackets agrees.
#
# TIMING-SENSITIVE STRETCHES. The same trace fitted at the strict margin `quiet_strict` (35 ms, the
# tick loop's JIT) shows levels of +1/-1 on unedited, exact charts - a player hitting early or late
# through a passage reads exactly like a file error there (Overblow D19, Timing S15, Passacaglia
# S4 on the 2026-09-26 research pass). The counter cannot settle those; the frames can. A stretch
# strong at the strict margin with a level the default margin does not confirm is UNSETTLED: its
# reads cannot vouch for anything, so an edit whose evidence lies there is UNCOVERED (never OFF),
# the whole-chart verdict is UNCOVERED, and `crops` writes the frames for a blind review. The same
# holds one margin out: a level that departs from the one before it (0 on a full combo) stands only
# if reads at least `quiet_wide` from every event inside it agree - a file error moves them too,
# early or late hits through a lag measured a few tens of ms off do not (Magical Vacation S16's
# +1 held at 80 ms and not at 150). Unconfirmed, it is unsettled too.
#
# WHOLE-CHART MODE (no base, or --whole): the worst disagreement anywhere - OFF if any strong level
# is not 0 (full combo) or changes within a run (breaks), FLAT if every strong level agrees, with
# `covered` saying whether every judged row sits within k_rows of a strong read.
#
# THE LEDGERS. `corpus` audits every edit-derived exact chart (exact at HEAD, not at a23cee5) and
# writes sources/trace-audit-<date>.json (every edit's verdict and reason, plus the controls'
# calibration and the detection-power table when `controls` / `power` have been run - their
# outputs live under work/rails-audit-scratch/) and sources/protected-promotions.jsonl: one row per
# chart whose every edit is FLAT and covered, whose whole trace has no OFF, and which is neither in
# the quarantine list nor on the owner's revisit list (sources/owner-revisit.json: recorded, not
# acted on). A promotion is bound to the block's content hash (block_sha, the contract in
# tools/guards.py) and to this tool's audit_version: sha256 of this file's source (newlines as LF)
# plus PARAMS, so any change to the rules or the numbers is a new version.
import bisect
import glob
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_map           # noqa: E402
import extract_repair as E  # noqa: E402  (piu-annotate on the path; refuses a converter without the lattice)
import tick_repair as T     # noqa: E402  (the counter reads, chain/runs, the clock, the display lag)
from piu_annotate.formats.sscfile import StepchartSSC        # noqa: E402
from piu_annotate.formats import ssc_to_chartstruct as _C    # noqa: E402

ROOT = E.ROOT
SCRATCH = os.path.join(ROOT, "work", "rails-audit-scratch")
IMPORT_REV = "a23cee5"
QUARANTINE = ("Houseplan S17", "Wedding Crashers S10", "Imagination S12")
# the three 35 ms flags on unedited charts the 2026-09-26 research left unresolved: `crops`
# writes their frames for a blind review whatever this tool's own verdict on them is
BLIND_REVIEW = ("Overblow D19", "Timing S15", "Passacaglia S4")

PARAMS = dict(
    conf=0.60,           # the reader's confidence floor (tick_repair.CONF)
    quiet=0.080,         # s: a read's cut this close to a judged event is not a quiet read
    quiet_strict=0.035,  # s: the strict margin that finds timing-sensitive stretches
    quiet_wide=0.150,    # s: the wide margin a departing level must hold at to be believed
    wide_min=3,          # reads at the wide margin that must agree with it
    hold_margin=0.080,   # s: nor is one inside a hold region, or this close to one
    penalty=6,           # the level fit's cost per level change, in disagreeing reads
    level_min=3,         # a level needs this many reads to be fitted at all
    seg_min=4,           # a fitted segment keeps this many agreeing reads, or is dropped
    strong_reads=8,      # a STRONG level: this many agreeing reads...
    strong_span=0.5,     # ...spanning at least this many seconds
    k_rows=8,            # judged rows: evidence this close on each side covers an edit (8 misses half the
                         # planted pairs 16 does, and promoted the same three charts on 2026-09-27)
    merge_gap=1.0,       # s: difference events closer than this are one edit
    bracket=0.60,        # s: the priced bracket around a counter-derived region (tick_repair.SPAN)
    min_fit=20,          # the clock must have been fitted on this many notes
    timing_tol=0.002,    # s: files whose beat-to-time maps differ by more are different clocks
    small_move=3,        # on a play with breaks, a within-run move larger than this is a run-structure question
    confusions=[[9, 5, [0, 1, 2, 3]], [9, 8, [0, 1, 2, 3]]],  # [true digit, read digit, positions]
)
_SRC = open(os.path.abspath(__file__), "rb").read().replace(b"\r\n", b"\n")
AUDIT_VERSION = hashlib.sha256(_SRC + json.dumps(PARAMS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


DECODE = "--no-decode" not in sys.argv   # measure a missing clock even when that means decoding the footage


# ---------------------------------------------------------------- the block hash (shared contract)

try:
    import guards as _G    # tools/guards.py, the one definition every loop imports, once it lands
    split_blocks, block_tags = _G.split_blocks, _G.block_tags
except ImportError:
    def _normalize(data):
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        return data.replace("\r\n", "\n").replace("\r", "\n")

    def split_blocks(data):
        """(header, [block, ...]): each block from its '#NOTEDATA:' line up to the next or EOF, newlines
        as LF, str.rstrip()'d - tools/guards.py's definition, which this must match byte for byte."""
        lines = _normalize(data).split("\n")
        starts = [i for i, line in enumerate(lines) if line.startswith("#NOTEDATA:")]
        if not starts:
            return "\n".join(lines).rstrip(), []
        ends = starts[1:] + [len(lines)]
        return "\n".join(lines[:starts[0]]).rstrip(), ["\n".join(lines[a:b]).rstrip() for a, b in zip(starts, ends)]

    def _kv(text):
        out = {}
        for kv in text.split(";"):
            if ":" in kv:
                k, *v = kv.strip().split(":")
                if k.startswith("#"):
                    out[k[1:]] = ":".join(v)
        return out

    def block_tags(data):
        header, blocks = split_blocks(data)
        head = _kv(header)
        out = []
        for b in blocks:
            d = dict(head)
            d.update(_kv(b))
            out.append("%s_%s" % (d.get("DESCRIPTION", ""), d.get("SONGTYPE", "")))
        return out


def block_sha(data, tag):
    """sha256 of the chart's block (the first block carrying the converter tag), or None."""
    tags = block_tags(data)
    if tag not in tags:
        return None
    return hashlib.sha256(split_blocks(data)[1][tags.index(tag)].encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- git

_BLOBS = {}


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace")[:200]))
    return r.stdout


def blob_path(rev, ssc_rel):
    """The file as it stood at a revision, written once under the scratch dir (the converter reads
    paths), or None if it did not exist there."""
    key = (rev, ssc_rel)
    if key not in _BLOBS:
        out = os.path.join(SCRATCH, "blobs", "%s_%s.ssc" % (rev, hashlib.md5(ssc_rel.encode("utf-8")).hexdigest()[:16]))
        if not os.path.exists(out):
            r = subprocess.run(["git", "show", "%s:simfiles/%s" % (rev, ssc_rel)], cwd=ROOT, capture_output=True)
            if r.returncode != 0:
                _BLOBS[key] = None
                return None
            os.makedirs(os.path.dirname(out), exist_ok=True)
            tmp = out + ".%d.tmp" % os.getpid()
            with open(tmp, "wb") as f:
                f.write(r.stdout)
            os.replace(tmp, out)
        _BLOBS[key] = out
    return _BLOBS[key]


# ---------------------------------------------------------------- the file's judged events

def time_function(sc):
    """beat -> chart seconds exactly as the converter accumulates it: BPMs, stops and delays applied
    at their beats (a row on a stop's beat is written before the stop), no time inside a warp."""
    V = _C.BeatToValueDict.from_string
    warps, bpms, stops, delays = (V(sc.get(k, "")) for k in ("WARPS", "BPMS", "STOPS", "DELAYS"))
    bp = sorted({b for b in [0.0] + list(bpms.keys()) + list(stops.keys()) + list(delays.keys()) + warps.get_event_times() if b >= 0})
    table, t, bpm = [], 0.0, bpms.get(0.0, bpms[min(bpms)] if bpms else 120.0)
    for i, b in enumerate(bp):
        bpm = bpms.get(b, bpm)
        w = warps.beat_in_any_range(b, inclusive_end=False)
        sd = stops.get(b, 0) + delays.get(b, 0)
        table.append((b, t, bpm, w, sd))
        if i + 1 < len(bp) and not w:
            t += (bp[i + 1] - b) * 60 / bpm + sd
    starts = [x[0] for x in table]

    def at(q):
        q = float(q)
        i = bisect.bisect_right(starts, q) - 1
        if i < 0:
            b, t0, bpm0, _, _ = table[0]
            return t0 + (q - b) * 60 / bpm0
        b, t0, bpm0, w, sd = table[i]
        if q == b or w:
            return t0
        return t0 + sd + (q - b) * 60 / bpm0
    return at, bp


def load_events(path, tag):
    """The block through the converter, with every judged event it derives enumerated in chart time:
    each tap row; each hold head that is not a tap row; each tick-lattice point (a multiple of
    1/TICKCOUNT on the beat grid) after a head and up to a release where a real hold is held, not in
    a warp or fake range and not on a tap or head row (that row is the event). This is
    ssc_to_chartstruct.lattice_hold_ticks point for point; the count must equal the converter's
    taps + ticks or the chart is refused."""
    sc = StepchartSSC.from_song_ssc_file(path, tag)
    if sc is None:
        return dict(error="block %s not found" % tag)
    ctx = {}
    try:
        df, ht, msg = _C.stepchart_ssc_to_chartstruct(sc, context=ctx)
    except Exception as ex:
        return dict(error="convert failed: %s" % ("%s: %s" % (type(ex).__name__, ex))[:120])
    if df is None:
        return dict(error="convert failed: %s" % msg)
    lines = [str(x) for x in df["Line"]]
    beats = [float(x) for x in df["Beat"]]
    times = [float(x) for x in df["Time"]]
    taps = sum(1 for x in lines if "1" in x)
    ticks = sum(int(round(x[2])) for x in ht)
    at, bp = time_function(sc)
    drift = max((abs(at(b) - t) for b, t in zip(beats, times)), default=0.0)
    if drift > 1e-4:
        return dict(error="the beat-to-time map disagrees with the converter's rows by %.4f s" % drift)
    fr = _C._frac
    tap_rows = {fr(b) for b, x in zip(beats, lines) if "1" in x}
    head_rows = {fr(b) for b, x in zip(beats, lines) if "2" in x}
    row_time = {fr(b): t for b, t in zip(beats, times)}
    ev = [(t, "tap", fr(b)) for t, b, x in zip(times, beats, lines) if "1" in x]
    real = ctx.get("real_holds") or []
    for h in sorted({fr(h) for h, _ in real} - tap_rows):
        ev.append((row_time.get(h, at(h)), "head", h))
    held = []
    for h, t in sorted((fr(h), fr(t)) for h, t in real):
        if held and h <= held[-1][1]:
            held[-1][1] = max(held[-1][1], t)
        else:
            held.append([h, t])
    excl = []
    for bd in [ctx.get("warps") or {}] + ([ctx.get("fakes") or {}] if _C.LATTICE_OPTIONS["exclude_fakes"] else []):
        for s0, length in bd.items():
            if length > 0:
                excl.append((fr(s0), fr(s0) + fr(length)))
    spans = _C._rate_spans(ctx.get("holdticks") or {})
    points = []
    for h, t in held:
        for a, b, r in spans.items:
            if r <= 0 or (b is not None and b <= h) or a > t:
                continue
            kmin = math.ceil(a * r) if a > h else math.floor(h * r) + 1
            kmax = math.floor(t * r) if b is None or b > t else math.ceil(b * r) - 1
            for k in range(kmin, kmax + 1):
                p = Fraction(k) / r
                if p in tap_rows or p in head_rows or any(x <= p < y for x, y in excl):
                    continue
                points.append(p)
    ev += [(at(p), "tick", p) for p in points]
    ev.sort()
    if len(ev) != taps + ticks:
        return dict(error="the lattice enumeration gives %d events, the converter %d" % (len(ev), taps + ticks))
    regions = []
    for st, en, tk in sorted((float(x[0]), float(x[1]), int(round(x[2]))) for x in ht):
        if regions and st <= regions[-1][1] + 1e-6:
            regions[-1][1] = max(regions[-1][1], en)
            regions[-1][2] += tk
        else:
            regions.append([st, en, tk])
    rowt = sorted(t for t, x in zip(times, lines) if "1" in x or "2" in x)
    sched = sorted((fr(b), fr(r)) for b, r in (ctx.get("holdticks") or {}).items())
    return dict(times=[t for t, _, _ in ev], kinds=[k for _, k, _ in ev], ebeats=[b for _, _, b in ev], taps=taps, ticks=ticks, implied=taps + ticks,
                tap_times=sorted(t for t, x in zip(times, lines) if "1" in x), rowt=rowt, regions=regions,
                sched=sched, at=at, breakpoints=bp, beats=beats)


def same_clock(ev_a, ev_b, tol):
    """Whether two files put the same beats at the same chart times (so a video clock measured on
    one holds for the other): the largest difference over both files' rows and timing breakpoints."""
    probe = sorted(set(ev_a["beats"]) | set(ev_b["beats"]) | set(ev_a["breakpoints"]) | set(ev_b["breakpoints"]))
    worst = max((abs(ev_a["at"](b) - ev_b["at"](b)) for b in probe), default=0.0)
    return worst <= tol, worst


# ---------------------------------------------------------------- the clock and the play

_ALIGN = None


def alignment_index():
    """chart -> [(source, commit, offset, clock %, fitted_on)], newest census first: the extraction
    and tick loops' records, each measured by extract_repair.align against the file as it stood when
    that census was committed."""
    global _ALIGN
    if _ALIGN is None:
        _ALIGN = {}
        paths = glob.glob(os.path.join(ROOT, "sources", "tick-loop-*.json")) + glob.glob(os.path.join(ROOT, "sources", "extract-loop-*.json"))

        def order(p):
            b = os.path.basename(p)
            return (re.search(r"(\d{4}-\d\d-\d\d)", b).group(1), b.startswith("tick-loop"))
        for p in sorted(paths, key=order, reverse=True):
            rel = "sources/" + os.path.basename(p)
            commit = git("log", "--diff-filter=A", "--format=%H", "-1", "--", rel).decode().strip()
            if not commit:
                continue
            for r in json.load(open(p, encoding="utf-8"))["charts"]:
                al = r.get("alignment")
                if not al or "offset" not in al:
                    continue
                _ALIGN.setdefault(r["chart"], []).append(dict(source=os.path.basename(p), commit=commit[:10], offset=al["offset"],
                                                              clock=al["clock"], fitted_on=al.get("fitted_on") or 0))
    return _ALIGN


# ---------------------------------------------------------------- measuring a clock (the tick loop's way)

_GUARD = [False]
_HOOKED = [False]
_SCRATCH_ABS = os.path.normcase(os.path.abspath(SCRATCH))


def _outside_scratch(path):
    if isinstance(path, int) or path is None:
        return False
    try:
        p = os.path.normcase(os.path.abspath(os.fsdecode(path)))
    except Exception:
        return True
    return not (p == _SCRATCH_ABS or p.startswith(_SCRATCH_ABS + os.sep))


def _write_guard(event, args):
    """While a clock is measured, nothing may be written, renamed or removed outside the scratch dir:
    the shared caches under work/ are read, never touched (a pre-open hook, because a write caught
    after the file is opened has already truncated it)."""
    if not _GUARD[0]:
        return
    paths = ()
    if event == "open":
        path, mode, flags = args
        writing = any(ch in mode for ch in "wax+") if isinstance(mode, str) else \
            bool(isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC))
        paths = (path,) if writing else ()
    elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.truncate", "shutil.rmtree", "os.chmod"):
        paths = (args[0],)
    elif event in ("os.rename", "os.replace", "shutil.copyfile", "shutil.move"):
        paths = tuple(args[:2])
    for p in paths:
        if _outside_scratch(p):
            raise PermissionError("trace_audit: a write outside %s was refused: %r" % (SCRATCH, p))


LOCK_STALE = 900    # s: an overlay lock older than this was left behind by a killed run


def _seed_overlay(vid, ov, fresh=False):
    """Copy the shared caches for one video into its overlay (never a 0-byte or unparseable one); with
    `fresh`, the overlay's own files for the video are discarded first (a pass a killed run left
    half-written - note_extract pickles its pass in place)."""
    import shutil
    for sub in ("receptor", "spritepass"):
        d = os.path.join(ov, "work", sub)
        os.makedirs(d, exist_ok=True)
        if fresh:
            for f in glob.glob(os.path.join(d, vid + ".*")):
                os.remove(f)
        for f in glob.glob(os.path.join(ROOT, "work", sub, vid + ".*")):
            dst = os.path.join(d, os.path.basename(f))
            if os.path.exists(dst) or os.path.getsize(f) == 0 or f.endswith(".tmp"):
                continue
            if f.endswith(".json"):
                try:
                    json.load(open(f, encoding="utf-8"))
                except ValueError:
                    continue
            tmp = dst + ".%d.tmp" % os.getpid()
            shutil.copyfile(f, tmp)
            os.replace(tmp, dst)


def _extract_in_overlay(c, ov):
    """note_extract.extract for the chart with its ROOT and the working directory in the overlay and the
    write guard on. Returns (notes, None) or (None, why)."""
    vids = os.path.join(ov, "videos")
    if not os.path.exists(os.path.join(vids, c["vid"] + ".mp4")):
        # a junction to the footage: nothing is copied, and nothing under it is ever written
        r = subprocess.run(["cmd", "/c", "mklink", "/J", vids, os.path.realpath(os.path.join(ROOT, "videos"))], capture_output=True)
        if r.returncode != 0 or not os.path.exists(os.path.join(vids, c["vid"] + ".mp4")):
            return None, "cannot reach the footage from the overlay"
    import note_extract as NX
    if not _HOOKED[0]:
        sys.addaudithook(_write_guard)
        _HOOKED[0] = True
    saved = (NX.ROOT, NX.CACHE, os.getcwd())
    NX.ROOT, NX.CACHE = ov, True
    os.chdir(ov)
    _GUARD[0] = True
    try:
        notes, meta = NX.extract(c["chart"], quiet=True)
        return notes, None
    except Exception as ex:
        return None, "note extraction failed: %s: %s" % (type(ex).__name__, str(ex)[:160])
    finally:
        _GUARD[0] = False
        NX.ROOT, NX.CACHE = saved[0], saved[1]
        os.chdir(saved[2])
        if os.path.isjunction(vids):
            os.rmdir(vids)      # the junction goes (never its target), so no later clean-up can follow it


def sweep_overlays():
    """Junctions and stale locks a killed run left in the overlays: removed (a junction's target never)."""
    base = os.path.join(SCRATCH, "overlay")
    for d in glob.glob(os.path.join(base, "*", "videos")):
        if os.path.isjunction(d):
            lk = os.path.join(base, os.path.basename(os.path.dirname(d)) + ".lock")
            if not os.path.exists(lk) or time.time() - os.path.getmtime(lk) > LOCK_STALE:
                os.rmdir(d)
    for lk in glob.glob(os.path.join(base, "*.lock")):
        try:
            if time.time() - os.path.getmtime(lk) > LOCK_STALE:
                os.remove(lk)
        except OSError:
            pass


_CLOCK_CODE = []


def clock_code():
    """A hash of the code a measured clock comes out of (the note reader and the alignment), so a
    cached clock is never served back after that code changes."""
    if not _CLOCK_CODE:
        h = hashlib.sha256()
        for m in ("note_extract.py", "receptors.py", "sprites.py", "quantize.py", "extract_repair.py", "corpus_map.py"):
            h.update(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), m), "rb").read().replace(b"\r\n", b"\n"))
        _CLOCK_CODE.append(h.hexdigest()[:10])
    return _CLOCK_CODE[0]


def measure_clock(c, blk, decode=True):
    """The video clock exactly as tick_repair measures it - note_extract's notes aligned to the file's
    own notes by extract_repair.align - run inside a per-video overlay under the scratch dir: the
    shared work/receptor and work/spritepass caches for the video are COPIED in (a 0-byte or
    unreadable one is left behind and rebuilt in the overlay), videos/ is a junction, and
    note_extract and receptors read and write only there while a write guard refuses anything else.
    Cached per video, band and the file's note layout (all the alignment depends on besides the
    footage). Returns dict(offset, clock, fitted_on, source) or dict(error)."""
    ncols = blk["ncols"]
    fnotes, _ = E.file_events(blk["rows"], ncols)
    play = play_of(c["vid"], c["side"]) or {}
    band = play.get("band", "C")
    sig = hashlib.sha256(json.dumps({str(k): [round(x[0], 4) for x in v] for k, v in sorted(fnotes.items())}).encode()).hexdigest()[:16]
    ck = os.path.join(SCRATCH, "clocks", "%s.%s.%s.%s.json" % (c["vid"], band, sig, clock_code()))
    if os.path.exists(ck):
        try:
            return json.load(open(ck, encoding="utf-8"))
        except ValueError:
            pass
    ov = os.path.join(SCRATCH, "overlay", c["vid"])
    have_pass = bool(glob.glob(os.path.join(ROOT, "work", "spritepass", c["vid"] + ".*.pkl")) or
                     glob.glob(os.path.join(ov, "work", "spritepass", c["vid"] + ".*.pkl")))
    if not have_pass and not decode:
        return dict(error="no cached sprite pass for %s, and decoding is off (--no-decode)" % c["vid"])
    for sub in ("receptor", "spritepass"):
        os.makedirs(os.path.join(ov, "work", sub), exist_ok=True)
    lock = os.path.join(SCRATCH, "overlay", c["vid"] + ".lock")
    t0 = time.time()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > LOCK_STALE:
                    os.remove(lock)     # a decode takes minutes; a lock this old was left by a killed run
            except OSError:
                pass
            if time.time() - t0 > 2 * LOCK_STALE:
                return dict(error="the overlay for %s stayed locked" % c["vid"])
            time.sleep(2)
    try:
        if os.path.exists(ck):
            return json.load(open(ck, encoding="utf-8"))
        notes = None
        for attempt in (0, 1):
            _seed_overlay(c["vid"], ov, fresh=attempt > 0)
            notes, err = _extract_in_overlay(c, ov)
            if notes is not None:
                break
        if notes is None:
            return dict(error=err)
        a, b, n_fit, seed = E.align(notes, fnotes, ncols)
        out = dict(source="note_extract + extract_repair.align (the tick loop's clock), measured here", offset=round(-a / b if b else -a, 3),
                   clock=round(100 * (b - 1), 4), fitted_on=n_fit, notes=len(notes), seconds=round(time.time() - t0, 1))
        _write_json(ck, out)
        return out
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def play_of(vid, side):
    cert = corpus_map.certification().get(vid) or {}
    s = cert.get(side) or {}
    other = cert.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")

    def num(k):
        try:
            return int(str(s.get(k) or 0).strip() or 0)
        except ValueError:
            return None
    try:
        judged, mc = int(s["judged"]), int(str(s["maxcombo"]).strip())
    except (KeyError, ValueError, TypeError):
        return None
    return dict(band=band, judged=judged, maxcombo=mc, clean=mc == judged, good=num("good"), bad=num("bad"), miss=num("miss"))


# ---------------------------------------------------------------- the trace

def misread(v, x, P):
    """Whether a read v is exactly one of the reader's known misreads of the value x the file
    predicts there (docs/EVIDENCE-RULES.md): a digit 9 read as 5 or 8, dropped leading digits,
    a truncation shadow, a rail's leading 1 over the zero-padded counter."""
    if x is None or x < 0 or v == x:
        return False
    # digit by digit, any number of digits at once (999 read as 555 is -444, not one -400)
    allowed = {(read_d, true_d, k) for true_d, read_d, positions in P["confusions"] for k in positions}
    sv, sx = str(v), str(x)
    if len(sv) == len(sx) and all(a == b or (int(a), int(b), len(sv) - 1 - i) in allowed for i, (a, b) in enumerate(zip(sv, sx))):
        return True
    if v < x and len(sv) < len(sx) and sx.endswith(sv):
        return True
    if x >= 100 and v in (x // 10, x // 100):
        return True
    for m in (2, 3):
        if v - x == 10 ** m and x < 10 ** m and v // 10 ** m == 1:
            return True
    return False


def segment(pts, P):
    """pts [(cut, err)] sorted -> [{level, reads: [cut, ...]}]: a piecewise-constant fit of the
    level, one disagreeing read costing 1 and a change of level `penalty` (the research prototype's
    trace_dp.segment, 2026-09-26). Segments with fewer than seg_min agreeing reads are dropped."""
    if not pts:
        return []
    cnt = Counter(e for _, e in pts)
    levels = [lv for lv, n in cnt.items() if n >= P["level_min"]] or [cnt.most_common(1)[0][0]]
    L = len(levels)
    cost = [0 if pts[0][1] == lv else 1 for lv in levels]
    back = []
    for i in range(1, len(pts)):
        bk_ = min(range(L), key=lambda k: cost[k])
        bc = cost[bk_]
        e = pts[i][1]
        nc, bk = [], []
        for k in range(L):
            m = 0 if e == levels[k] else 1
            if cost[k] <= bc + P["penalty"]:
                nc.append(cost[k] + m); bk.append(k)
            else:
                nc.append(bc + P["penalty"] + m); bk.append(bk_)
        cost = nc; back.append(bk)
    k = min(range(L), key=lambda k: cost[k])
    path = [k]
    for bk in reversed(back):
        k = bk[k]; path.append(k)
    path = path[::-1]
    segs = []
    for i, k in enumerate(path):
        lv = levels[k]
        if not segs or segs[-1]["level"] != lv:
            segs.append(dict(level=lv, reads=[]))
        if pts[i][1] == lv:
            segs[-1]["reads"].append(pts[i][0])
    return [s for s in segs if len(s["reads"]) >= P["seg_min"]]


def in_spans(x, spans):
    return any(a <= x <= b for a, b in spans)


def trace(ev, raw, a, b, play, brackets, P):
    """The counter against F(t): strong levels per run at the default and strict margins, the
    evidence reads, the unsettled stretches. `brackets` are chart-time spans whose reads priced an
    edit and may not vouch for it."""
    clock = T.Clock(a, b)
    clean = play["clean"]
    # with no BAD or MISS nothing resets the counter (a GOOD neither breaks nor increments it), so
    # the play is one run however the reads fall
    breaks = (play.get("bad") or 0) + (play.get("miss") or 0)
    monotone = clean or breaks == 0
    E_ = ev["times"]
    regions = [dict(t0=r[0], t1=r[1]) for r in ev["regions"]]
    first = [(t, v, 0) for t, v in T.chain(raw)] if monotone else T.runs(raw)
    lag, n_lag = T.measure_lag(first, ev["tap_times"], regions, clock)
    clock.lag = lag

    def F(cut):
        return bisect.bisect_right(E_, cut)
    # The reader's known misreads out FIRST, each judged against the value the counter should be
    # showing - the file's count plus the level the play is holding at that moment (0 on a full
    # combo until the reads themselves say otherwise; after a reset, whatever the new run settles
    # on). Only then are the reads chained, or cut into runs: a stretch of 9xx read as 5xx is a
    # fall that holds, and left in it would be a reset that never happened.
    # The level is tracked from quiet reads only; a read near an event is judged against the value
    # on either side of it, since which side of the event its cut fell on is what the lag cannot say.
    # On a play whose counter never resets the level the file is audited against is 0, so a read is
    # also judged against that: one misread that slips through must not carry the tracked level off
    # and let every misread after it through (Slam S5's 89 read as 88, then 90-98 read as 80-88).
    dropped, keep, recent, level = 0, [], [], 0
    for t, v in raw:
        cut = clock.cut(t)
        f = F(cut)
        k = bisect.bisect_left(E_, cut - P["quiet"])
        quiet = not (k < len(E_) and E_[k] <= cut + P["quiet"])
        bases = {0, level} if monotone else {level}
        if any(misread(v, f + L + d, P) for L in bases for d in ((0,) if quiet else (-1, 0, 1))):
            dropped += 1
            continue
        keep.append((t, v))
        if quiet:
            recent = (recent + [v - f])[-9:]
            if len(recent) >= 5:
                level = Counter(recent).most_common(1)[0][0]
    reads = [(t, v, 0) for t, v in T.chain(keep)] if monotone else T.runs(keep)
    holds = [(r[0] - P["hold_margin"], r[1] + P["hold_margin"]) for r in ev["regions"]]

    def points(quiet):
        per = {}
        for t, v, run in reads:
            cut = clock.cut(t)
            if in_spans(cut, holds) or in_spans(cut, brackets):
                continue
            k = bisect.bisect_left(E_, cut - quiet)
            if k < len(E_) and E_[k] <= cut + quiet:
                continue
            per.setdefault(run, []).append((cut, v - F(cut), v, F(cut)))
        if not clean:
            # after a reset the tracked level is stale until five quiet reads have been seen, so
            # each run is judged again against its own settled level
            for run, pts in per.items():
                base = Counter(e for _, e, _, _ in pts).most_common(1)[0][0]
                per[run] = [q for q in pts if not misread(q[2], q[3] + base, P)]
        return per

    def strong_of(per):
        out = []
        for run, pts in sorted(per.items()):
            for s in segment(sorted((c, e) for c, e, _, _ in pts), P):
                rd = s["reads"]
                out.append(dict(run=run, level=s["level"], first=rd[0], last=rd[-1], n=len(rd), reads=rd,
                                strong=len(rd) >= P["strong_reads"] and rd[-1] - rd[0] >= P["strong_span"]))
        return out
    per = points(P["quiet"])
    segs = strong_of(per)
    per_s = points(P["quiet_strict"])
    segs_s = strong_of(per_s)
    per_w = points(P["quiet_wide"])

    # A file error moves every read after it by the same amount; a player's early or late hits,
    # seen through a display lag measured a few tens of milliseconds off, move only the reads
    # nearest the notes. So a level that departs from the one before it (0 on a full combo) stands
    # only if the reads at least quiet_wide from every event inside it agree - wide_min of them,
    # outnumbering those still at the old level two to one. Otherwise it is unsettled, not OFF.
    strong, unsettled = [], []
    for run in sorted({s["run"] for s in segs}):
        ref = 0 if clean else None
        for s in sorted((x for x in segs if x["run"] == run and x["strong"]), key=lambda x: x["first"]):
            if ref is None or s["level"] == ref:
                ref = s["level"] if ref is None else ref
                strong.append(s)
                continue
            wide = [e for c, e, _, _ in per_w.get(run, []) if s["first"] - 1e-9 <= c <= s["last"] + 1e-9]
            n_lv, n_ref = sum(1 for e in wide if e == s["level"]), sum(1 for e in wide if e == ref)
            if n_lv >= P["wide_min"] and n_lv >= 2 * n_ref:
                strong.append(s)
                if not clean:
                    ref = s["level"]
            else:
                unsettled.append(dict(run=run, level=s["level"] - ref, first=round(s["first"], 3), last=round(s["last"], 3), n=s["n"],
                                      wide_agree=n_lv, wide_against=n_ref, margin="%.0f ms" % (1000 * P["quiet"])))

    # timing-sensitive stretches: strong at 35 ms with a level the default margin does not confirm
    def expected_level(run, lo, hi):
        if clean:
            return 0
        same = [s for s in strong if s["run"] == run and s["last"] >= lo and s["first"] <= hi]
        if not same:
            same = sorted((s for s in strong if s["run"] == run), key=lambda s: min(abs(s["first"] - hi), abs(s["last"] - lo)))[:1]
        return same[0]["level"] if same else None
    for s in segs_s:
        if not s["strong"]:
            continue
        ex = expected_level(s["run"], s["first"], s["last"])
        if ex is None or s["level"] == ex:
            continue
        if any(d["run"] == s["run"] and d["level"] == s["level"] and d["last"] >= s["first"] and d["first"] <= s["last"] for d in strong):
            continue    # the default margin sees the same level: that is a disagreement, not a timing question
        unsettled.append(dict(run=s["run"], level=s["level"] - ex, first=round(s["first"], 3), last=round(s["last"], 3), n=s["n"],
                              margin="%.0f ms" % (1000 * P["quiet_strict"])))
    unsettled.sort(key=lambda u: u["first"])
    unset_spans = [(u["first"] - P["quiet"], u["last"] + P["quiet"]) for u in unsettled]
    evidence = []
    for s in strong:
        for c in s["reads"]:
            if not in_spans(c, unset_spans):
                evidence.append((c, s["level"], s["run"]))
    evidence.sort()
    n_runs = len({r for _, _, r in reads})
    return dict(lag=lag, lag_taps=n_lag, clean=clean, reads=len(raw), on_chain=len(reads), misreads_dropped=dropped,
                structure_ok=monotone or n_runs - 1 <= breaks,
                quiet_points=sum(len(v) for v in per.values()), segments=segs, strong=strong, unsettled=unsettled,
                evidence=evidence, runs=n_runs)


def load_reads(vid, band, mc, P):
    """The counter scan's reads (work/combo/<vid>.<band>.jsonl, combo_reader): (video time, value),
    confident, in the counter's range (it draws nothing below 4; nothing above maxcombo is real),
    sorted - tick_repair.reads_for without its on-demand scan. None when there is no scan."""
    path = os.path.join(ROOT, "work", "combo", "%s.%s.jsonl" % (vid, band))
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    out = []
    for line in open(path, encoding="utf-8"):
        try:
            t, v, c = json.loads(line)
        except ValueError:
            continue
        if v is not None and c >= P["conf"] and 4 <= v <= mc:
            out.append((float(t), int(v)))
    return sorted(out)


def rows_between(rowt, x, y):
    """Judged rows strictly between two chart times."""
    return max(0, bisect.bisect_left(rowt, y) - bisect.bisect_right(rowt, x))


def judge_edit(e, tr, rowt, play, P):
    """FLAT / OFF / UNCOVERED for one edit [lo, hi] from the evidence reads around it."""
    K = P["k_rows"]
    lo, hi = e["lo"], e["hi"]
    evd = tr["evidence"]
    cuts = [c for c, _, _ in evd]
    i_lo = bisect.bisect_left(rowt, lo)
    i_hi = bisect.bisect_right(rowt, hi)
    t_left = rowt[i_lo - K] if i_lo - K >= 0 else -1e9
    t_right = rowt[i_hi + K - 1] if i_hi + K - 1 < len(rowt) else 1e9
    j = bisect.bisect_left(cuts, lo) - 1
    left = evd[j] if j >= 0 else None
    j = bisect.bisect_right(cuts, hi)
    right = evd[j] if j < len(evd) else None
    near = [x for x in evd if t_left <= x[0] <= t_right]
    side = lambda x: None if x is None else dict(cut=round(x[0], 3), level=x[1], run=x[2])
    out = dict(left=side(left), right=side(right),
               left_rows=rows_between(rowt, left[0], lo) if left else None,
               right_rows=rows_between(rowt, hi, right[0]) if right else None)
    inside = [c for c, _, _ in evd if lo < c < hi]
    marks = [lo] + inside + [hi]
    gap = max((rows_between(rowt, x, y) for x, y in zip(marks, marks[1:])), default=0)
    out["inner_gap_rows"] = gap
    covered = bool(left and right and out["left_rows"] <= K and out["right_rows"] <= K and gap <= 2 * K)
    out["covered"] = covered
    unset = [u for u in tr["unsettled"] if u["last"] >= t_left and u["first"] <= t_right]
    if play["clean"]:
        bad = [x for x in near if x[1] != 0]
        far = [x for x in (left, right) if x is not None and x[1] != 0 and x not in near]
        if not bad and far:
            # nothing read between the edit and a disagreeing reading, however far: the file's
            # running count is wrong at the edit, whether or not the edit is what made it so
            w = far[0]
            n = out["left_rows"] if w is left else out["right_rows"]
            return dict(out, verdict="OFF", reason="the nearest strong read %s the edit, %d rows away with nothing read between, is %+d against the file (at %.2fs)" % (
                "before" if w is left else "after", n, w[1], w[0]))
        if bad:
            w = max(bad, key=lambda x: abs(x[1]))
            if w[0] < lo:
                where = "%d rows before the edit" % rows_between(rowt, w[0], lo)
            elif w[0] > hi:
                where = "%d rows after the edit" % rows_between(rowt, hi, w[0])
            else:
                where = "inside the edit"
            lv = lambda x: "none within %d rows" % K if x is None else "%+d" % x[1]
            return dict(out, verdict="OFF", reason="a strong read %s (at %.2fs) is %+d against the file; the nearest reads either side are %s and %s" % (
                where, w[0], w[1], lv(left if left and left[0] >= t_left else None), lv(right if right and right[0] <= t_right else None)))
        if unset:
            return dict(out, verdict="UNCOVERED", reason="a timing-sensitive stretch (%.2f-%.2fs, %+d at 35 ms only) lies within %d rows; the frames decide it" % (
                unset[0]["first"], unset[0]["last"], unset[0]["level"], K))
        if covered:
            return dict(out, verdict="FLAT", reason="level 0 on both sides: %d row(s) before, %d after, no blind stretch over %d rows" % (
                out["left_rows"], out["right_rows"], 2 * K))
        return dict(out, verdict="UNCOVERED", reason=uncovered_why(out, K))
    # a play with breaks: the level is the run's own, so the two sides must share a run and agree
    byrun = {}
    for x in near:
        byrun.setdefault(x[2], []).append(x)
    for run, xs in byrun.items():
        xs.sort()
        moves = [(p, q) for p, q in zip(xs, xs[1:]) if q[1] != p[1]]
        if not moves:
            continue
        p, q = moves[0]
        d = q[1] - p[1]
        verdict, why = move_verdict(d, play, tr, P)
        return dict(out, verdict=verdict, reason="within one run the level moves %+d between %.2fs and %.2fs: %s" % (d, p[0], q[0], why))
    if unset:
        return dict(out, verdict="UNCOVERED", reason="a timing-sensitive stretch (%.2f-%.2fs) lies within %d rows; the frames decide it" % (unset[0]["first"], unset[0]["last"], K))
    if not covered:
        return dict(out, verdict="UNCOVERED", reason=uncovered_why(out, K))
    if left[2] != right[2]:
        return dict(out, verdict="UNCOVERED", reason="the combo broke between the readings either side (run %d -> %d)" % (left[2], right[2]))
    if play.get("good"):
        return dict(out, verdict="UNCOVERED", reason="the reads agree, but the play has %d GOOD(s): a GOOD neither breaks nor increments the counter, so one could hide the event an edit lost" % play["good"])
    return dict(out, verdict="FLAT", reason="one run, one level on both sides: %d row(s) before, %d after" % (out["left_rows"], out["right_rows"]))


def move_verdict(d, play, tr, P):
    """A level that moves within one run of a play with breaks: OFF only where nothing but the file
    can explain it."""
    if abs(d) > P["small_move"]:
        return "UNCOVERED", "a move that size on a play with breaks is a misread or a misplaced reset as often as a file error"
    if not tr["structure_ok"]:
        return "UNCOVERED", "the reads split into %d runs on a play with %d BAD+MISS, so some resets are misreads" % (
            tr["runs"], (play.get("bad") or 0) + (play.get("miss") or 0))
    if d < 0 and -d <= (play.get("good") or 0):
        return "UNCOVERED", "the play has %d GOOD(s), and a GOOD lowers the level by one" % play["good"]
    return "OFF", "no GOOD or reset explains it"


def uncovered_why(out, K):
    if not out["left"] and not out["right"]:
        return "no strong read on either side"
    parts = []
    if not out["left"]:
        parts.append("no strong read before it")
    elif out["left_rows"] > K:
        parts.append("the nearest strong read before it is %d rows away" % out["left_rows"])
    if not out["right"]:
        parts.append("no strong read after it")
    elif out["right_rows"] > K:
        parts.append("the nearest strong read after it is %d rows away" % out["right_rows"])
    if out["inner_gap_rows"] > 2 * K:
        parts.append("%d rows inside it without one" % out["inner_gap_rows"])
    return "; ".join(parts) + " (the limit is %d)" % K


def judge_whole(tr, rowt, play, P):
    """The worst disagreement anywhere, and whether every judged row sits within k_rows of evidence."""
    K = P["k_rows"]
    strong = tr["strong"]
    cuts = [c for c, _, _ in tr["evidence"]]
    marks = [rowt[0] - 1e-6] + cuts + [rowt[-1] + 1e-6] if rowt else []
    gaps = [rows_between(rowt, x, y) for x, y in zip(marks, marks[1:])]
    edge = [gaps[0], gaps[-1]] if gaps else [0, 0]
    inner = max(gaps[1:-1], default=0) if len(gaps) > 2 else (max(gaps) if gaps else 0)
    covered = bool(cuts) and edge[0] <= K and edge[1] <= K and inner <= 2 * K
    within = sum(1 for t in rowt if cuts and _near(cuts, rowt, t, K))
    out = dict(strong=len(strong), evidence=len(cuts), covered=covered, blind_rows=max(gaps, default=0),
               share_within_k=round(within / len(rowt), 3) if rowt else 0.0,
               unsettled=tr["unsettled"])
    fmt = lambda s: dict(run=s["run"], level=s["level"], first=round(s["first"], 3), last=round(s["last"], 3), n=s["n"])
    if play["clean"]:
        off = [s for s in strong if s["level"] != 0]
        if off:
            w = max(off, key=lambda s: (abs(s["level"]), s["n"]))
            return dict(out, verdict="OFF", worst=fmt(w), off=[fmt(s) for s in off],
                        reason="the counter holds %+d against the file from %.2fs to %.2fs (%d reads)" % (w["level"], w["first"], w["last"], w["n"]))
    else:
        moved = []
        for run in sorted({s["run"] for s in strong}):
            ss = sorted((s for s in strong if s["run"] == run), key=lambda s: s["first"])
            for p, q in zip(ss, ss[1:]):
                if q["level"] != p["level"]:
                    d = q["level"] - p["level"]
                    v, why = move_verdict(d, play, tr, P)
                    moved.append((v, dict(fmt(q), level=d), "within run %d the level moves %+d between %.2fs and %.2fs: %s" % (run, d, p["last"], q["first"], why)))
        offs = [m for m in moved if m[0] == "OFF"]
        if offs:
            return dict(out, verdict="OFF", worst=offs[0][1], reason=offs[0][2])
        if moved:
            return dict(out, verdict="UNCOVERED", worst=moved[0][1], reason=moved[0][2])
    if tr["unsettled"]:
        u = tr["unsettled"][0]
        return dict(out, verdict="UNCOVERED", reason="%d timing-sensitive stretch(es), first %.2f-%.2fs at %+d, seen at 35 ms only; the frames decide them" % (
            len(tr["unsettled"]), u["first"], u["last"], u["level"]))
    if not strong:
        return dict(out, verdict="UNCOVERED", reason="no strong reading anywhere (%d quiet reads)" % tr["quiet_points"])
    if not play["clean"] and play.get("good"):
        return dict(out, verdict="UNCOVERED", reason="no level moves within a run, but the play has %d GOOD(s)" % play["good"])
    return dict(out, verdict="FLAT", reason="%d strong level(s), every one agreeing with the file" % len(strong))


def _near(cuts, rowt, t, K):
    """Whether a judged row at t has evidence within K rows on at least one side."""
    j = bisect.bisect_left(cuts, t)
    for c in ([cuts[j - 1]] if j else []) + ([cuts[j]] if j < len(cuts) else []):
        if rows_between(rowt, min(c, t), max(c, t)) <= K:
            return True
    return False


# ---------------------------------------------------------------- edits

def diff_edits(ev_new, ev_base, P):
    """The stretches where the two blocks' judged events differ, in the audited file's chart time."""
    # by exact beat: the two files share one clock (same_clock), and matching by time would split
    # one event in two wherever an added row moved the converter's float accumulation by 1e-5 s
    def keyed(ev):
        return Counter(zip(ev["ebeats"], ev["kinds"]))
    new, old = keyed(ev_new), keyed(ev_base)
    diff = sorted([(ev_new["at"](b), +1, k) for (b, k), n in (new - old).items() for _ in range(n)] +
                  [(ev_new["at"](b), -1, k) for (b, k), n in (old - new).items() for _ in range(n)])
    regions = ev_new["regions"] + ev_base["regions"]

    def region_of(t):
        for i, (a, b, _) in enumerate(regions):
            if a - 1e-6 <= t <= b + 1e-6:
                return i
        return None
    edits = []
    for t, s, k in diff:
        r = region_of(t)
        if edits and (t - edits[-1]["hi"] < P["merge_gap"] or (r is not None and r in edits[-1]["_regions"])):
            x = edits[-1]
        else:
            x = dict(lo=t, hi=t, plus=0, minus=0, kinds={}, _regions=set())
            edits.append(x)
        x["hi"] = max(x["hi"], t)
        x["plus" if s > 0 else "minus"] += 1
        x["kinds"].setdefault(k, [0, 0])[0 if s > 0 else 1] += 1
        if r is not None:
            x["_regions"].add(r)
    return edits


def region_spans(ev, lo, hi):
    """The hold regions of a file overlapping [lo, hi], as (t0, t1)."""
    return [(a, b) for a, b, _ in ev["regions"] if b >= lo - 1e-6 and a <= hi + 1e-6]


# ---------------------------------------------------------------- one chart

_CHARTS = None


def charts():
    global _CHARTS
    if _CHARTS is None:
        _CHARTS = E.charts()
    return _CHARTS


def resolve(name):
    ch = charts()
    if name in ch:
        return ch[name]
    by_key = {c["key"]: c for c in ch.values()}
    if name in by_key:
        return by_key[name]
    raise SystemExit("no certified chart %r" % name)


def audit_chart(c, new_path=None, base_path=None, whole=False, clock=None, P=PARAMS):
    """Audit one chart. c: an entry of extract_repair.charts(). new_path: the file to audit (the
    working tree's by default); base_path: the file to diff against (the import commit's by default),
    `whole` for whole-chart mode only; clock: (offset, clock %) to override the census's."""
    t_start = time.time()
    tag = E.block_tag(c["key"])
    new_path = new_path or os.path.join(ROOT, "simfiles", *c["ssc_rel"].split("/"))
    rec = dict(chart=c["chart"], key=c["key"], ssc_rel=c["ssc_rel"], vid=c["vid"], side=c["side"], expected=c["expected"])
    data = open(new_path, "rb").read()
    rec["block_sha"] = block_sha(data, tag)
    ev = load_events(new_path, tag)
    if ev.get("error"):
        return dict(rec, verdict="UNCOVERED", reason="file: " + ev["error"], edits=[])
    rec["file"] = dict(taps=ev["taps"], ticks=ev["ticks"], implied=ev["implied"], rows=len(ev["rowt"]), regions=len(ev["regions"]))
    rec["exact"] = ev["implied"] == c["expected"]
    # the edits
    edits, timing_changed, base_ev = None, False, None
    if not whole:
        if base_path is None:
            base_path = blob_path(IMPORT_REV, c["ssc_rel"])
        if base_path:
            base_data = open(base_path, "rb").read()
            rec["base_sha"] = block_sha(base_data, tag)
            base_ev = load_events(base_path, tag)
            if base_ev.get("error"):
                base_ev = None
        if base_ev is None:
            rec["base"] = "no base block"
        elif rec.get("base_sha") == rec["block_sha"] and _header(base_data) == _header(data):
            edits = []
        else:
            same, worst = same_clock(ev, base_ev, P["timing_tol"])
            if not same:
                timing_changed = True
                rec["timing_change"] = round(worst, 4)
            else:
                edits = diff_edits(ev, base_ev, P)
                if not edits:
                    rec["base"] = "the blocks differ but derive the same judged events"
    tick_sched_changed = base_ev is not None and base_ev["sched"] != ev["sched"]
    # the play, the reads, the clock
    play = play_of(c["vid"], c["side"])
    if not play:
        return _unaudited(rec, edits, "no maxcombo on the result screen", t_start)
    rec["play"] = play
    raw = load_reads(c["vid"], play["band"], play["maxcombo"], P)
    if not raw:
        return _unaudited(rec, edits, "no counter scan for %s band %s" % (c["vid"], play["band"]), t_start)
    al = None
    if clock:
        al = dict(source="--offset/--clock", offset=clock[0], clock=clock[1], fitted_on=None)
    else:
        for cand in alignment_index().get(c["chart"], []):
            if cand["fitted_on"] < P["min_fit"]:
                continue
            ref = blob_path(cand["commit"], c["ssc_rel"])
            ref_ev = load_events(ref, tag) if ref else None
            if not ref_ev or ref_ev.get("error"):
                continue
            ok, worst = same_clock(ev, ref_ev, P["timing_tol"])
            if ok:
                al = dict(cand, timing_diff=round(worst, 5))
                break
            rec.setdefault("clock_refused", []).append(dict(source=cand["source"], timing_diff=round(worst, 4)))
    if not al:
        # no census clock fits this file: measure one the tick loop's way
        blk = E.load_block(new_path, tag)
        m = measure_clock(c, blk, decode=DECODE) if blk and not blk.get("error") else dict(error="the block did not load")
        if m.get("error"):
            rec["clock_error"] = m["error"]
        elif (m.get("fitted_on") or 0) < P["min_fit"]:
            rec["clock_error"] = "the measured clock fitted only %d notes" % (m.get("fitted_on") or 0)
        else:
            al = m
    if not al:
        why = "no video clock: " + ("no census clock fits this file's timing" if rec.get("clock_refused") else "no extraction or tick-loop alignment") +               ("; measuring one failed (%s)" % rec["clock_error"] if rec.get("clock_error") else "")
        return _unaudited(rec, edits, why, t_start)
    b = 1 + al["clock"] / 100.0
    a = -al["offset"] * b
    # counter-derived edits: their brackets' reads may not vouch
    brackets = []
    if edits:
        for e in edits:
            e["basis"] = "counter-derived" if (tick_sched_changed and "tick" in e["kinds"]) else "independent"
            if e["basis"] == "counter-derived" and P["bracket"] is not None:
                for a0, b0 in region_spans(ev, e["lo"], e["hi"]) + [(e["lo"], e["hi"])]:
                    brackets.append((a0 - P["bracket"], b0 + P["bracket"]))
    tr = trace(ev, raw, a, b, play, brackets, P)
    rec["clock"] = dict(al, lag=tr["lag"], lag_taps=tr["lag_taps"])
    rec["reads"] = dict(confident=tr["reads"], on_chain=tr["on_chain"], misreads_dropped=tr["misreads_dropped"], quiet=tr["quiet_points"],
                        strong=len(tr["strong"]), evidence=len(tr["evidence"]), runs=tr["runs"], unsettled=len(tr["unsettled"]))
    rec["whole"] = judge_whole(tr, ev["rowt"], play, P)
    rec["brackets"] = [[round(x, 3), round(y, 3)] for x, y in _merge(brackets)]
    if whole or edits is None or timing_changed:
        # no base, or the timing moved every event: the chart is audited whole, and FLAT needs
        # every row covered
        w = rec["whole"]
        v = w["verdict"]
        if v == "FLAT" and not w["covered"]:
            v, why = "UNCOVERED", "no disagreement, but not every row is within %d rows of a strong read (the longest blind stretch is %d rows)" % (P["k_rows"], w["blind_rows"])
        else:
            why = w["reason"]
        kind = "timing" if timing_changed else "whole"
        rec["edits"] = [dict(lo=ev["rowt"][0] if ev["rowt"] else 0.0, hi=ev["rowt"][-1] if ev["rowt"] else 0.0, kind=kind, basis="counter-derived" if tick_sched_changed else "independent",
                             verdict=v, covered=v == "FLAT", reason=("the file's timing changed (by up to %.3fs): audited whole - " % rec["timing_change"] if timing_changed else "") + why)]
    else:
        out = []
        for e in edits:
            j = judge_edit(e, tr, ev["rowt"], play, P)
            out.append(dict(lo=round(e["lo"], 3), hi=round(e["hi"], 3), rows=rows_between(ev["rowt"], e["lo"] - 1e-6, e["hi"] + 1e-6),
                            events=dict(added=e["plus"], removed=e["minus"], net=e["plus"] - e["minus"], kinds={k: "+%d/-%d" % tuple(v) for k, v in sorted(e["kinds"].items())}),
                            basis=e["basis"], **j))
        rec["edits"] = out
    return _finish(rec, t_start)


def _header(data):
    return split_blocks(data)[0]


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _unaudited(rec, edits, why, t_start):
    if edits is None:
        rec["edits"] = [dict(kind="whole", verdict="UNCOVERED", covered=False, reason=why)]
    else:
        rec["edits"] = [dict(lo=round(e["lo"], 3), hi=round(e["hi"], 3), verdict="UNCOVERED", covered=False, reason=why) for e in edits]
    rec["whole"] = dict(verdict="UNCOVERED", reason=why)
    return _finish(rec, t_start)


def _finish(rec, t_start):
    vs = [e["verdict"] for e in rec["edits"]]
    w = (rec.get("whole") or {}).get("verdict")
    if "OFF" in vs or w == "OFF":
        rec["verdict"] = "OFF"
    elif vs and all(v == "FLAT" for v in vs):
        rec["verdict"] = "FLAT"
    elif not vs:
        rec["verdict"] = w or "UNCOVERED"
    else:
        rec["verdict"] = "UNCOVERED"
    if "reason" not in rec:
        same = [e for e in rec["edits"] if e["verdict"] == rec["verdict"]]
        rec["reason"] = same[0]["reason"] if same else "whole trace: " + (rec.get("whole") or {}).get("reason", "")
    rec["seconds"] = round(time.time() - t_start, 2)
    return rec


# ---------------------------------------------------------------- populations

def _below_normal():
    """Pool initializer: the machine is shared, so workers run at BelowNormal with one cv2 thread."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception:
        pass


def pool_map(fn, jobs, workers):
    workers = max(1, min(int(workers), 6))
    if workers == 1:
        _below_normal()
        return [fn(j) for j in jobs]
    from multiprocessing import Pool
    with Pool(workers, initializer=_below_normal) as p:
        return p.map(fn, jobs, chunksize=2)


def grade_job(c):
    """(chart, exact at HEAD, exact at the import commit, block sha at both, header same)."""
    tag = E.block_tag(c["key"])
    head = os.path.join(ROOT, "simfiles", *c["ssc_rel"].split("/"))
    base = blob_path(IMPORT_REV, c["ssc_rel"])
    out = dict(chart=c["chart"])
    for label, path in (("head", head), ("base", base)):
        if not path or not os.path.exists(path):
            out[label] = None
            continue
        data = open(path, "rb").read()
        blk = E.load_block(path, tag)
        implied = blk.get("implied") if blk and not blk.get("error") else None
        out[label] = dict(implied=implied, sha=block_sha(data, tag), header=hashlib.sha256(_header(data).encode("utf-8")).hexdigest())
    return out


def populations(workers):
    """Every certified chart graded at HEAD and at the import commit (cached per HEAD commit)."""
    tree = git("rev-parse", "HEAD:simfiles").decode().strip()
    cache = os.path.join(SCRATCH, "grade-%s.json" % tree[:12])
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    ch = charts()
    rows = pool_map(grade_job, list(ch.values()), workers)
    for r in rows:
        c = ch[r["chart"]]
        exp = int(c["expected"])
        r["expected"] = exp
        r["exact_head"] = bool(r["head"] and r["head"]["implied"] == exp)
        r["exact_base"] = bool(r["base"] and r["base"]["implied"] == exp)
        r["untouched"] = bool(r["head"] and r["base"] and r["head"]["sha"] == r["base"]["sha"] and r["head"]["header"] == r["base"]["header"])
    _write_json(cache, rows)
    return rows


def _write_json(path, obj, indent=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".%d.tmp" % os.getpid()
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _whole_job(name):
    c = charts()[name]
    try:
        return audit_chart(c, whole=True)
    except Exception as ex:
        return dict(chart=name, verdict="UNCOVERED", reason="error: %s: %s" % (type(ex).__name__, str(ex)[:120]), edits=[])


def _edit_job(name):
    c = charts()[name]
    try:
        return audit_chart(c)
    except Exception as ex:
        return dict(chart=name, verdict="UNCOVERED", reason="error: %s: %s" % (type(ex).__name__, str(ex)[:120]), edits=[])


def controls(workers):
    """Calibration: every untouched chart (its block and header as at the import commit) that is exact
    and has a counter scan, audited whole. None may come out OFF."""
    t0 = time.time()
    pop = populations(workers)
    names = sorted(r["chart"] for r in pop if r["exact_head"] and r["untouched"])
    rows = pool_map(_whole_job, names, workers)
    rows = [r for r in rows if not (r.get("reason") or "").startswith("no counter scan")]
    cnt = Counter(r["verdict"] for r in rows)
    out = dict(generated=time.strftime("%Y-%m-%d %H:%M"), audit_version=AUDIT_VERSION, params=PARAMS,
               population="certified charts exact at HEAD whose block and song header are byte-identical to %s's, with a counter scan" % IMPORT_REV,
               counts=dict(cnt), clean_plays=sum(1 for r in rows if (r.get("play") or {}).get("clean")),
               covered=sum(1 for r in rows if (r.get("whole") or {}).get("covered")),
               seconds=round(time.time() - t0, 1), charts=[_slim(r) for r in rows])
    _write_json(os.path.join(SCRATCH, "controls.json"), out)
    print("controls: %d audited in %.0fs - %s; %d on full-combo plays; %d covered end to end" % (
        len(rows), out["seconds"], dict(cnt), out["clean_plays"], out["covered"]))
    for r in rows:
        if r["verdict"] == "OFF":
            print("  OFF", r["chart"], "-", r.get("reason"))
    for r in rows:
        if (r.get("whole") or {}).get("unsettled"):
            print("  unsettled", r["chart"], r["whole"]["unsettled"][:3])
    return out


def _slim(r):
    keep = ("chart", "key", "vid", "side", "expected", "exact", "block_sha", "base_sha", "verdict", "reason", "play", "clock", "reads", "brackets",
            "timing_change", "clock_refused", "base", "seconds")
    out = {k: r[k] for k in keep if k in r}
    if "whole" in r:
        out["whole"] = {k: v for k, v in r["whole"].items() if k != "off"}
    out["edits"] = r.get("edits", [])
    return out


# ---------------------------------------------------------------- detection power

SEP_BUCKETS = [(0, 4), (5, 8), (9, 16), (17, 32), (33, 64), (65, 128), (129, 10 ** 9)]
# the default rules (the plants are #TICKCOUNTS edits, so counter-derived: brackets out), the same
# plants read as if measured some other way (no brackets), and the default at two wider k_rows
POWER_VARIANTS = [("counter-derived", {}), ("independent", dict(bracket=None)),
                  ("counter-derived k=16", dict(k_rows=16)), ("counter-derived k=32", dict(k_rows=32))]


def _sites(path, tag):
    sc = StepchartSSC.from_song_ssc_file(path, tag)
    ctx = {}
    df, ht, _ = _C.stepchart_ssc_to_chartstruct(sc, context=ctx)
    fr = _C._frac
    rows = sorted({fr(float(b)) for b in df["Beat"]})
    held = []
    for h, t in sorted((fr(h), fr(t)) for h, t in ctx["real_holds"]):
        if held and h <= held[-1][1]:
            held[-1][1] = max(held[-1][1], t)
        else:
            held.append([h, t])
    excl = [(fr(s), fr(s) + fr(l)) for bd in (ctx["warps"], ctx["fakes"]) for s, l in bd.items() if l > 0]
    sched = sorted((fr(b), fr(r)) for b, r in ctx["holdticks"].items())
    sbeats = [b for b, _ in sched]
    spans = _C._rate_spans(ctx["holdticks"])
    regions = []
    for x, y in sorted((fr(g.start_beat), fr(g.end_beat)) for g in ctx["segments"]):
        if regions and x <= regions[-1][1]:
            regions[-1][1] = max(regions[-1][1], y)
        else:
            regions.append([x, y])
    sites = []
    for h, t in held:
        for a, b, r in spans.items:
            if r <= 0 or r.denominator != 1 or r > 48 or (b is not None and b <= h) or a > t:
                continue
            step = 1 / r
            k0 = math.floor(max(h, a) * r) + 1
            k1 = math.floor(min(t, b if b is not None else t) * r) - 1
            for k in range(k0, k1 + 1):
                p = Fraction(k) / r
                lo, hi = p - step, p + step
                if lo <= h or hi > t or (b is not None and hi >= b) or lo < a:
                    continue
                if any(lo <= x <= hi for x in rows[bisect.bisect_left(rows, lo):bisect.bisect_right(rows, hi)]):
                    continue
                if any(x < hi and y > lo for x, y in excl):
                    continue
                if any(lo <= x <= hi for x in sbeats):
                    continue
                reg = next((i for i, (x, y) in enumerate(regions) if x <= p <= y), None)
                sites.append(dict(p=p, r=r, region=reg))
    return sites, sched


def plant(text, tag, sched, minus, plus):
    """The block's #TICKCOUNTS with one lattice point removed (at minus.p) and one added (between
    plus.p and the next point), everything else as it was."""
    entries = {float(b): float(r) for b, r in sched}
    pm, rm = minus["p"], minus["r"]
    entries[float(pm - 1 / (2 * rm))] = 0.0
    entries[float(pm + 1 / (2 * rm))] = float(rm)
    x, rp = plus["p"] + 1 / (2 * plus["r"]), plus["r"]
    entries[float(x)] = float(2 * rp)
    entries[float(x + 1 / (2 * rp))] = float(rp)
    return T.write_schedule(text, tag, {T.exact(b): r for b, r in entries.items()})


def _power_job(job):
    name, seed, per_chart = job
    c = charts()[name]
    tag = E.block_tag(c["key"])
    path = os.path.join(ROOT, "simfiles", *c["ssc_rel"].split("/"))
    rng = random.Random("%s|%s" % (seed, name))
    out = []
    try:
        ev = load_events(path, tag)
        if ev.get("error"):
            return out
        sites, sched = _sites(path, tag)
        if len(sites) < 2:
            return out
        at = ev["at"]
        rowt = ev["rowt"]
        for s in sites:
            s["t"] = at(float(s["p"]))
        text = open(path, encoding="utf-8", newline="").read()
        tried = 0
        order = list(range(len(SEP_BUCKETS)))
        rng.shuffle(order)
        for bi in order * 2:
            if tried >= per_chart:
                break
            lo_b, hi_b = SEP_BUCKETS[bi]
            for _ in range(40):
                x, y = rng.sample(sites, 2)
                if x["region"] == y["region"] or abs(x["t"] - y["t"]) < 1e-3:
                    continue
                sep = rows_between(rowt, min(x["t"], y["t"]), max(x["t"], y["t"]))
                if lo_b <= sep <= hi_b:
                    break
            else:
                continue
            minus, plus = (x, y) if rng.random() < 0.5 else (y, x)
            new = plant(text, tag, sched, minus, plus)
            pdir = os.path.join(SCRATCH, "plants", c["key"])
            os.makedirs(pdir, exist_ok=True)
            pp = os.path.join(pdir, "%d.ssc" % tried)
            with open(pp, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            tried += 1
            pev = load_events(pp, tag)
            if pev.get("error") or pev["implied"] != ev["implied"]:
                out.append(dict(chart=name, sep=sep, planted=False, why=pev.get("error") or "implied %d != %d" % (pev["implied"], ev["implied"])))
                continue
            d = diff_edits(pev, ev, PARAMS)
            nplus = sum(e["plus"] for e in d)
            nminus = sum(e["minus"] for e in d)
            if nplus != 1 or nminus != 1:
                out.append(dict(chart=name, sep=sep, planted=False, why="diff +%d/-%d" % (nplus, nminus)))
                continue
            row = dict(chart=name, meter=_meter(name), sep=sep, seconds=round(abs(x["t"] - y["t"]), 2), planted=True,
                       first=("minus" if minus["t"] < plus["t"] else "plus"), clean=None)
            for variant, params in POWER_VARIANTS:
                r = audit_chart(c, new_path=pp, base_path=path, P=dict(PARAMS, **params))
                row["clean"] = (r.get("play") or {}).get("clean")
                row[variant] = r["verdict"]
                row[variant + "_why"] = [e.get("reason") for e in r.get("edits", [])][:2]
            out.append(row)
    except Exception as ex:
        out.append(dict(chart=name, planted=False, why="error: %s: %s" % (type(ex).__name__, str(ex)[:120])))
    return out


def _meter(name):
    m = re.search(r"([SD])(\d+)$", name)
    return int(m.group(2)) if m else None


def power(workers, per_chart, seed):
    t0 = time.time()
    ctl = json.load(open(os.path.join(SCRATCH, "controls.json"), encoding="utf-8"))
    names = sorted(r["chart"] for r in ctl["charts"] if (r.get("play") or {}).get("clean") and r.get("clock") and r["chart"] not in BLIND_REVIEW)
    rows = [x for part in pool_map(_power_job, [(n, seed, per_chart) for n in names], workers) for x in part]
    ok = [r for r in rows if r.get("planted")]
    table = []
    for lo, hi in SEP_BUCKETS:
        rs = [r for r in ok if lo <= r["sep"] <= hi]
        line = dict(rows="%d-%s" % (lo, hi if hi < 10 ** 9 else "+"), plants=len(rs))
        for variant, _ in POWER_VARIANTS:
            cnt = Counter(r[variant] for r in rs)
            line[variant] = dict(OFF=cnt["OFF"], UNCOVERED=cnt["UNCOVERED"], FLAT=cnt["FLAT"],
                                 detected=round(cnt["OFF"] / len(rs), 3) if rs else None,
                                 missed=round(cnt["FLAT"] / len(rs), 3) if rs else None)
        table.append(line)
    by_meter = []
    for lo, hi in ((1, 15), (16, 19), (20, 23), (24, 99)):
        rs = [r for r in ok if r["meter"] and lo <= r["meter"] <= hi]
        cnt = Counter(r["counter-derived"] for r in rs)
        by_meter.append(dict(levels="%d-%d" % (lo, hi), plants=len(rs), OFF=cnt["OFF"], UNCOVERED=cnt["UNCOVERED"], FLAT=cnt["FLAT"]))
    out = dict(generated=time.strftime("%Y-%m-%d %H:%M"), audit_version=AUDIT_VERSION, params=PARAMS, seed=seed, per_chart=per_chart,
               variants={v: p for v, p in POWER_VARIANTS},
               charts=len(names), plants=len(ok), refused=len(rows) - len(ok), seconds=round(time.time() - t0, 1),
               method="one #TICKCOUNTS-only compensating pair per plant in a scratch copy of an untouched exact chart on a full-combo play: "
                      "a lattice point removed (rate 0 over +-1/2r) in one hold region and one added (rate 2r over [x, x+1/2r) at a midpoint) "
                      "in another, the converter's total unchanged and the event diff exactly +1/-1; separation = judged rows between the two",
               table=table, by_meter=by_meter, rows=rows)
    _write_json(os.path.join(SCRATCH, "power.json"), out)
    print("power: %d plants on %d charts in %.0fs (%d refused)" % (len(ok), len(names), out["seconds"], out["refused"]))
    for variant, _ in POWER_VARIANTS:
        print("  %s: rows apart, plants, OFF / UNCOVERED / FLAT (detected, missed)" % variant)
        for line in table:
            x = line[variant]
            print("    %-9s %4d  %4d %4d %4d  (%s, %s)" % (line["rows"], line["plants"], x["OFF"], x["UNCOVERED"], x["FLAT"], x["detected"], x["missed"]))
    for m in by_meter:
        print("  levels %-6s plants %4d  OFF %4d UNC %4d FLAT %4d" % (m["levels"], m["plants"], m["OFF"], m["UNCOVERED"], m["FLAT"]))
    return out


# ---------------------------------------------------------------- the corpus ledger

def corpus(workers, date, out_dir=None):
    t0 = time.time()
    pop = populations(workers)
    head = git("rev-parse", "HEAD").decode().strip()
    gained = sorted(r["chart"] for r in pop if r["exact_head"] and not r["exact_base"])
    rows = pool_map(_edit_job, gained, workers)
    promotions = []
    revisit = owner_revisit()
    for r in rows:
        edits = r.get("edits") or []
        ok = bool(edits) and all(e["verdict"] == "FLAT" and e.get("covered") for e in edits) and (r.get("whole") or {}).get("verdict") != "OFF"
        if r["chart"] in QUARANTINE:
            r["quarantined"] = True
        if r["chart"] in revisit:
            # the owner has accepted this chart as it stands: its verdict is recorded, nothing is acted on
            r["owner_revisit"] = "accepted by the owner as it stands (sources/owner-revisit.json): recorded, not acted on, never promoted"
        r["promotable"] = ok and not r.get("quarantined") and not r.get("owner_revisit") and r.get("block_sha") is not None
        if r["promotable"]:
            promotions.append(dict(chart=r["chart"], key=r["key"], block_sha=r["block_sha"], audit="FLAT", covered=True,
                                   audit_version=AUDIT_VERSION, run="trace-audit %s at %s" % (date, head[:7])))
    cnt = Counter(r["verdict"] for r in rows)
    ecnt = Counter(e["verdict"] for r in rows for e in r.get("edits", []))
    basis = Counter((e.get("basis"), e["verdict"]) for r in rows for e in r.get("edits", []))
    ledger = dict(
        generated=time.strftime("%Y-%m-%d %H:%M"), tool="tools/trace_audit.py", audit_version=AUDIT_VERSION, params=PARAMS,
        head=head, import_rev=IMPORT_REV, converter=_converter_id(),
        block_sha="sha256 of the chart's #NOTEDATA block: from its '#NOTEDATA:' line to the next or EOF, UTF-8 (errors=replace), "
                  "CRLF/CR as LF, str.rstrip()'d (tools/guards.py)",
        population="certified charts exact at HEAD and not at %s: the edit-derived exact set" % IMPORT_REV,
        quarantine=list(QUARANTINE), owner_revisit=sorted(revisit & set(gained)), counts=dict(charts=len(rows), **{k: cnt[k] for k in ("FLAT", "OFF", "UNCOVERED")},
                                                 edits=dict(ecnt), promoted=len(promotions)),
        by_basis={"%s %s" % k: v for k, v in sorted(basis.items(), key=str)},
        seconds=round(time.time() - t0, 1), charts=[dict(_slim(r), promotable=r["promotable"], quarantined=r.get("quarantined", False),
                                                     **({"owner_revisit": r["owner_revisit"]} if r.get("owner_revisit") else {})) for r in rows])
    for part, name in (("calibration", "controls.json"), ("power", "power.json")):
        p = os.path.join(SCRATCH, name)
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            if d.get("audit_version") != AUDIT_VERSION:
                ledger[part] = dict(stale=True, audit_version=d.get("audit_version"))
                continue
            if part == "calibration":
                ledger[part] = dict(population=d["population"], counts=d["counts"], clean_plays=d["clean_plays"], covered=d["covered"], seconds=d["seconds"],
                                    off=[dict(chart=r["chart"], reason=r.get("reason")) for r in d["charts"] if r["verdict"] == "OFF"],
                                    unsettled=[dict(chart=r["chart"], stretches=r["whole"].get("unsettled")) for r in d["charts"] if (r.get("whole") or {}).get("unsettled")],
                                    charts=[dict(chart=r["chart"], verdict=r["verdict"], covered=(r.get("whole") or {}).get("covered"), reason=r.get("reason")) for r in d["charts"]])
            else:
                ledger[part] = {k: d[k] for k in ("method", "variants", "seed", "per_chart", "charts", "plants", "refused", "seconds", "table", "by_meter")}
    out_dir = out_dir or os.path.join(ROOT, "sources")
    out = os.path.join(out_dir, "trace-audit-%s.json" % date)
    _write_json(out, ledger)
    pj = os.path.join(out_dir, "protected-promotions.jsonl")
    tmp = pj + ".%d.tmp" % os.getpid()
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for p in sorted(promotions, key=lambda p: p["chart"]):
            f.write(json.dumps(p, ensure_ascii=False, separators=(", ", ": ")) + "\n")
    os.replace(tmp, pj)
    print("corpus: %d edit-derived exact charts in %.0fs - %s; edits %s; %d promoted" % (len(rows), ledger["seconds"], dict(cnt), dict(ecnt), len(promotions)))
    for r in rows:
        if r["verdict"] == "OFF":
            print("  OFF", r["chart"], "-", r.get("reason"))
    return ledger


def owner_revisit():
    """The charts the owner will revisit by hand (sources/owner-revisit.json)."""
    p = os.path.join(ROOT, "sources", "owner-revisit.json")
    if not os.path.exists(p):
        return set()
    d = json.load(open(p, encoding="utf-8"))
    items = d.get("charts", []) if isinstance(d, dict) else d
    return {x.get("chart") if isinstance(x, dict) else x for x in items}


def _converter_id():
    path = _C.__file__
    src = open(path, "rb").read().replace(b"\r\n", b"\n")
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=os.path.dirname(os.path.dirname(os.path.dirname(path))),
                                capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = None
    return dict(module="piu_annotate/formats/ssc_to_chartstruct.py", sha256=hashlib.sha256(src).hexdigest(), commit=commit,
                hold_tick_model=getattr(_C, "HOLD_TICK_MODEL", None))


# ---------------------------------------------------------------- frames for a blind review

def crops(names, out="blind-35ms"):
    """For each chart, six frames across every unsettled or disagreeing stretch and four from anywhere
    else in the chart, cropped to the counter's half of the screen and named by opaque ids, so a
    reviewer reads each counter blind. The key (which chart, when, what the file predicts there)
    goes to a separate file the reviewer is not given. Nothing here decides anything."""
    import cv2
    import combo_reader as CR
    outd = os.path.join(SCRATCH, out)
    os.makedirs(outd, exist_ok=True)
    keyf = os.path.join(SCRATCH, out + "-key.json")
    key = json.load(open(keyf, encoding="utf-8")) if os.path.exists(keyf) else {}
    for name in names:
        c = resolve(name)
        rec = audit_chart(c, whole=True)
        w = rec.get("whole") or {}
        stretches = [("off", s) for s in w.get("off") or []] + [("unsettled " + u.get("margin", ""), u) for u in w.get("unsettled") or []]
        if not stretches:
            print(name, "- nothing unsettled or off; no frames written")
            continue
        al = rec["clock"]
        b = 1 + al["clock"] / 100.0
        a = -al["offset"] * b
        lag = al["lag"]
        ev = load_events(os.path.join(ROOT, "simfiles", *c["ssc_rel"].split("/")), E.block_tag(c["key"]))
        play = rec["play"]
        path = CR.video_path(c["vid"])
        cap = cv2.VideoCapture(path)
        rng = random.Random(name)
        picks = []
        for why, s in stretches:
            span = [s["first"], s["last"]]
            for k in range(6):
                picks.append((why, span[0] + (span[1] - span[0]) * k / 5.0))
        # control frames from anywhere in the chart, so a flagged frame is not told apart by being chosen
        for _ in range(4):
            picks.append(("control", rng.uniform(ev["rowt"][0], ev["rowt"][-1])))
        hx0, hx1 = CR.HALF[play["band"]]
        for why, cut in picks:
            T_ = (cut - a) / b + lag
            cap.set(cv2.CAP_PROP_POS_MSEC, T_ * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            if frame.shape[0] != 720:
                frame = cv2.resize(frame, (1280, 720))
            crop = frame[250:480, hx0:hx1]
            pid = hashlib.sha256(("%s|%.3f|%s" % (name, T_, rng.random())).encode()).hexdigest()[:12]
            cv2.imwrite(os.path.join(outd, pid + ".png"), crop)
            F = bisect.bisect_right(ev["times"], cut)
            key[pid] = dict(chart=name, vid=c["vid"], band=play["band"], video_t=round(T_, 3), chart_t=round(cut, 3), file_count=F, stretch=why)
        cap.release()
        print(name, "- %d frames" % len(picks))
    _write_json(keyf, key)
    print("frames in", outd, "- key (do not show the reviewer):", keyf)


# ---------------------------------------------------------------- the command line

def show(rec):
    print("== %s  %s  (%s)" % (rec["chart"], rec["verdict"], rec.get("reason", "")))
    if rec.get("play"):
        p = rec["play"]
        print("   play: band %s judged %d maxcombo %d%s" % (p["band"], p["judged"], p["maxcombo"], " (full combo)" if p["clean"] else " GOOD %s BAD %s MISS %s" % (p["good"], p["bad"], p["miss"])))
    if rec.get("clock"):
        cl = rec["clock"]
        print("   clock: offset %.3f clock %+.4f%% from %s, lag %.3f (%d taps)" % (cl["offset"], cl["clock"], cl["source"], cl["lag"], cl["lag_taps"]))
    if rec.get("reads"):
        print("   reads:", rec["reads"])
    if rec.get("whole"):
        w = rec["whole"]
        print("   whole: %s - %s (covered %s, blind %s rows)" % (w["verdict"], w.get("reason"), w.get("covered"), w.get("blind_rows")))
    for e in rec.get("edits", []):
        print("   edit %s-%s %s %s: %s - %s" % (e.get("lo"), e.get("hi"), e.get("basis", ""), (e.get("events") or {}).get("net", ""), e["verdict"], e["reason"]))


def main():
    if len(sys.argv) < 2:
        print(__doc__ or open(os.path.abspath(__file__), encoding="utf-8").read().split("import bisect")[0])
        return
    op = sys.argv[1]
    workers = int(arg("--workers", 6))
    sweep_overlays()
    try:
        _main(op, workers)
    finally:
        sweep_overlays()


def _main(op, workers):
    if op == "chart":
        c = resolve(sys.argv[2])
        clock = (float(arg("--offset")), float(arg("--clock", 0))) if arg("--offset") else None
        base = arg("--base")
        if arg("--base-rev"):
            base = blob_path(arg("--base-rev"), c["ssc_rel"])
        rec = audit_chart(c, new_path=arg("--file"), base_path=base, whole="--whole" in sys.argv, clock=clock)
        if "--json" in sys.argv:
            print(json.dumps(rec, indent=1, ensure_ascii=False, default=str))
        else:
            show(rec)
    elif op == "controls":
        controls(workers)
    elif op == "power":
        power(workers, int(arg("--per-chart", 8)), arg("--seed", "2026-09-27"))
    elif op == "corpus":
        corpus(workers, arg("--date", time.strftime("%Y-%m-%d")), arg("--out-dir"))
    elif op == "crops":
        names = [a for i, a in enumerate(sys.argv[2:], 2) if not a.startswith("--") and sys.argv[i - 1] != "--out"]
        crops(names or list(BLIND_REVIEW), arg("--out", "blind-35ms"))
    elif op == "version":
        print(AUDIT_VERSION)
    else:
        raise SystemExit("unknown op %r" % op)


if __name__ == "__main__":
    main()
