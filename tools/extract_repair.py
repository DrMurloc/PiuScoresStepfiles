# Read each certified chart off its footage, diff it against the file, apply what the video
# shows, and ship only what lands EXACTLY on the game's count. The counter loop
# (batch_repair.py) priced hold regions from the combo counter and ran out of charts it could
# price; this reads the notes themselves, which is the other two thousand.
#
#   python -X utf8 tools/extract_repair.py survey [--shard i/n] [--only "<chart>"] [--limit N]
#          [--shapes under-ticked,hold-less,single-region,over-ticked] [--cache] [--redo] [--redo-verdict FAIL,PARK]
#          [--ssc <alt .ssc> --expected N]      (a proof: run against another file, ship nothing)
#   python -X utf8 tools/extract_repair.py commit [--dry-run] [--only "<chart>"]
#
# survey never touches simfiles/: every candidate is written under work/extract-loop/ and
# converted there. commit is a separate, serial pass over the SHIP verdicts of every shard's
# report, so shards can run side by side without contending for git.
#
# THE DIFF. The extraction is aligned to the file's own notes (anchor, then a straight line
# for the video's clock) and matched note for note in seconds, one to one per column within
# TOL. A file note the extraction did not find is "missing"; an extracted note the file lacks
# is an "addition"; a matched pair whose hold state differs is "tap->hold" or "hold->tap"; a
# matched hold whose release differs by more than TAIL_TOL is a "tail" move.
#
# WHAT IS APPLIED, and what is not, and why:
#   tap->hold   applied. The file's own tap at that instant plus a rail on screen is two
#               sensors agreeing; this is the shape of most repairs so far (holds written as
#               taps). The release is the rail's end, to a frame or two.
#   tail        applied. Same evidence, and the tick count depends on it.
#   add-hold,   applied only where the receptor FLASHED for it - the game lighting the panel is
#   add-tap     the second sensor, and art that moved at scroll speed never lights one - and
#               capped at ADD_SHARE of the file's notes: a real missing note is rare and a false
#               detection is not (2006. LOVE SONG S15, exact: 4 stray taps in 405, none flashed).
#   Every hold taken from a rail must be a rail worth believing: at least RAIL_LEN long and
#   read as held on at least RAIL_OCC of its frames. Two closely spaced arrows in one column
#   read as one short "rail" (Slam D22's drill), and bright art under one receptor reads as a
#   thin one (Smells Like A Chocolate S3: twelve, all in the centre lane, none over 0.10s).
#   An addition also needs a streak at least FRAMES_SHARE of the chart's typical one - the
#   false ones are short re-acquisitions - and no file note the extraction MISSED within
#   CONFUSION of it in any column, which is a drill note read in the neighbouring lane.
#   hold->tap   NOT applied. A rail the reader did not see is not a hold the game does not
#               draw - half of a dense chart's holds are under two frames long.
#   missing     NOT applied. A note the extractor did not find is far more often the
#               extractor's miss than the file's phantom.
# A chart whose file notes the extraction recalls below RECALL_BAR is parked unread: an
# extraction that cannot see the file's own notes cannot be trusted about what the file lacks.
#
# THE GATE is the one every repair here has passed: the candidate goes through piu-annotate's
# converter and its taps + ticks must equal the count the result screen certified. Not
# sufficient in general - a wrong distribution can close on the right total - which is why the
# diff is confined to the shapes above and every edit is written into the commit. commit runs
# tick_verify a second time on the file in place before anything is committed.
import bisect
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from fractions import Fraction

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
import corpus_map      # noqa: E402
import edit_notes      # noqa: E402
import note_extract    # noqa: E402
import quantize as Q   # noqa: E402
from piu_annotate.formats.sscfile import StepchartSSC                             # noqa: E402
from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct  # noqa: E402
from piu_annotate.formats import ssc_to_chartstruct as _C                          # noqa: E402

# Every repair is graded by the converter, so a converter that still counts hold ticks the old
# way would grade every repair against the wrong arithmetic (docs/EVIDENCE-RULES.md, "A
# staggered release is not a tick"). piu-annotate's piuscores-windows-port branch carries it.
if getattr(_C, "HOLD_TICK_MODEL", "legacy") != "lattice":
    sys.exit("piu-annotate's converter does not count hold ticks by the tick lattice - check out the "
             "piuscores-windows-port branch of https://github.com/DrMurloc/piu-annotate (HOLD_TICK_MODEL = 'lattice') before grading anything")
C_MERGE = _C.merge_holdticks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe"
OUT = os.path.join(ROOT, "work", "extract-loop")
TOL = 0.045          # s: an extracted note and a file note this close are the same note
TAIL_TOL = 0.060     # s: a release this far from the file's is a different release (--tail-tol overrides)
SNAP_TOL = 0.020     # s: an added note snaps to the coarsest lattice line this close
RECALL_BAR = 0.93    # the extraction must see this share of the file's notes to be believed
PRECISION_BAR = 0.93 # and this share of what it extracted must be in the file
ADD_SHARE = 0.02     # additions beyond this share of the file's notes park the chart
RAIL_LEN = 0.15      # s: a rail shorter than this is not believed as a hold (real ones here ran 0.65-2.3s,
RAIL_OCC = 0.55      #    the false ones 0.07-0.10s; the lane read >=0.59 held on real ones, <=0.52 on false)
FRAMES_SHARE = 0.6   # an added note's streak must be this share of the chart's typical streak length
CONFUSION = 0.060    # s: an addition this close to a file note the extraction MISSED, in any column,
                     #    is that note read in the wrong lane
FLASH_TOL = 0.080    # s: a receptor flash this close to an added note says the game judged it
DUP_TOL = 0.035      # s: an addition this close to a file note in its column is that note seen twice
                     # (nothing in the corpus puts two notes in one column closer than 34ms)
GRIDS = (4, 8, 12, 16, 24, 32, 48)
SHAPE_ORDER = ["under-ticked", "hold-less", "single-region", "over-ticked", "census", "duplicate-block"]
TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


TAIL_TOL = float(arg("--tail-tol", TAIL_TOL))
PRECISION_BAR = float(arg("--precision-bar", PRECISION_BAR))


def block_tag(key):
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9]+)*?)_(ARCADE|SHORTCUT|REMIX|FULLSONG)$", key)
    return "%s_%s" % (m.group(1).replace("_", " "), m.group(2))


# ---------------------------------------------------------------- the worklist

def charts():
    """name -> what the loop needs, for every chart with a certified result screen."""
    tail = {r["key"]: r for r in json.load(open(os.path.join(ROOT, "sources", "tail-2026-09-08.json"), encoding="utf-8"))["charts"]}
    judged = {c["chart"]: int(c["judged"]) for c in json.load(open(os.path.join(ROOT, "sources", "census-final.json"), encoding="utf-8"))
              if str(c.get("judged", "")).strip().isdigit()}
    smap = corpus_map.chart_map()
    out = {}
    for vid, e in corpus_map.certification().items():
        for name, c in (e.get("charts") or {}).items():
            if c.get("verdict") != "CERTIFIED" or name not in smap:
                continue
            m = smap[name]
            row = tail.get(m["key"])
            expected = c.get("expected") or judged.get(name) or (row and row["implied"] - row["delta"])
            out[name] = dict(chart=name, key=m["key"], ssc_rel=m["ssc_rel"], vid=vid, side=c.get("side") or "1p",
                             expected=expected, shape=row["shape"] if row else "census", in_tail=bool(row))
    return out


# ---------------------------------------------------------------- the file's own notes

def load_block(ssc_path, tag, hold_ticks=None):
    """The block through the converter: rows in chart time, its counts, the raw grid width (in
    panels - a StepF2 cell is one panel), and its hold regions: the converter's hold segments
    merged wherever one runs into the next, each [start, end, ticks] in chart seconds.
    `hold_ticks="legacy"` counts the ticks the way the converter did before 2026-09-23."""
    sc = StepchartSSC.from_song_ssc_file(ssc_path, tag)
    if sc is None:
        return None
    ctx = {}
    try:
        df, ht, msg = stepchart_ssc_to_chartstruct(sc, context=ctx, **({"hold_ticks": hold_ticks} if hold_ticks else {}))
    except Exception as ex:
        return dict(error="convert failed: " + f"{ex}"[:100])
    if df is None:
        return dict(error="convert failed: " + msg)
    rows = [dict(t=float(t), b=float(b), line=str(l).replace("`", "")) for t, b, l in zip(df["Time"], df["Beat"], df["Line"])]
    width = max((edit_notes.width(r.strip()) for m in sc["NOTES"].split(",") for r in m.split("\n")
                 if r.strip() and not r.strip().startswith(("#", "//"))), default=len(rows[0]["line"]))
    taps = int(df["Line"].str.contains("1", regex=False).sum())
    ticks = sum(int(round(t[2])) for t in ht)
    regions, segments = [], sorted((float(t[0]), float(t[1]), int(round(t[2]))) for t in ht)
    for st, en, tk in segments:
        if regions and st <= regions[-1][1] + 1e-6:
            regions[-1][1] = max(regions[-1][1], en)
            regions[-1][2] += tk
        else:
            regions.append([st, en, tk])
    # each region's first and last beat, from the converter's own segments (a boundary is not
    # always a written row: a release inside a fake or warp range is not)
    region_beats = []
    for seg in sorted(C_MERGE(ctx.get("segments") or []), key=lambda s: s.start_time):
        st, en = round(float(seg.start_time), 4), round(float(seg.end_time), 4)
        if region_beats and st <= region_beats[-1][2] + 1e-6:
            region_beats[-1][1] = max(region_beats[-1][1], seg.end_beat)
            region_beats[-1][2] = max(region_beats[-1][2], en)
        else:
            region_beats.append([seg.start_beat, seg.end_beat, en])
    region_beats = [(a, b) for a, b, _ in region_beats] if len(region_beats) == len(regions) else None
    # The fakes: panels the game draws as arrows and never judges (a fake-flagged StepF2 cell, the
    # F letter), which the converter reads as empty. The extraction sees them on screen, so an
    # extracted note landing on one is the fake, not an addition. Kept by chartstruct column, in
    # chart seconds, so plan() can pair them the way it pairs the judged notes.
    ncols = len(rows[0]["line"])
    fakes = {}
    try:
        sections, i = edit_notes.find_block(open(ssc_path, encoding="utf-8", newline="").read(), tag)
        _, measures = edit_notes.parse_notes(sections[i])
        _, time_at = clocks(rows)
        pad = (ncols - width) // 2
        for mi, mrows in enumerate(measures):
            for r, row in enumerate(mrows):
                for col, cell in enumerate(edit_notes.cells(row)):
                    if edit_notes.drawn_fake(cell):
                        fakes.setdefault(col + pad, []).append(time_at(4 * mi + 4 * r / len(mrows)))
    except SystemExit:
        pass
    return dict(rows=rows, width=width, ncols=ncols, taps=taps, ticks=ticks, implied=taps + ticks, regions=regions, segments=segments,
                region_beats=region_beats, fakes={c: sorted(v) for c, v in fakes.items()})


def file_events(rows, ncols):
    """taps-or-heads by column (chart time); holds as (col, head, tail) with beats; row beats."""
    notes, holds, opened = {c: [] for c in range(ncols)}, [], {}
    for r in rows:
        for c, ch in enumerate(r["line"][:ncols]):
            if ch in "12":
                notes[c].append((r["t"], r["b"], ch))
            if ch == "2":
                opened[c] = (r["t"], r["b"])
            elif ch == "3" and c in opened:
                ht, hb = opened.pop(c)
                holds.append(dict(col=c, head=ht, head_beat=hb, tail=r["t"], tail_beat=r["b"]))
    for c in notes:
        notes[c].sort()
    return notes, holds


def clocks(rows):
    t = np.array([r["t"] for r in rows]); b = np.array([r["b"] for r in rows])
    kt = np.concatenate(([True], np.diff(t) > 0)); kb = np.concatenate(([True], np.diff(b) > 0))
    ct, cb = t[kt], b[kt]
    bt, bb = t[kb], b[kb]
    bps0 = (cb[1] - cb[0]) / max(ct[1] - ct[0], 1e-6) if len(ct) > 1 else 2.0
    bps1 = (cb[-1] - cb[-2]) / max(ct[-1] - ct[-2], 1e-6) if len(ct) > 1 else 2.0

    def beat_at(x):
        if x <= ct[0]:
            return float(cb[0] + (x - ct[0]) * bps0)
        if x >= ct[-1]:
            return float(cb[-1] + (x - ct[-1]) * bps1)
        return float(np.interp(x, ct, cb))

    def time_at(beat):
        if beat <= bb[0]:
            return float(bt[0] + (beat - bb[0]) / bps0)
        if beat >= bb[-1]:
            return float(bt[-1] + (beat - bb[-1]) / bps1)
        return float(np.interp(beat, bb, bt))
    return beat_at, time_at


def snap(t, beat_at, time_at):
    """The coarsest lattice line within SNAP_TOL of this instant, else the nearest 48th."""
    b = beat_at(t)
    for g in GRIDS:
        cand = round(b * g) / g
        if abs(time_at(cand) - t) <= SNAP_TOL:
            return Fraction(round(b * g), g), g
    return Fraction(round(b * 48), 48), 0


# ---------------------------------------------------------------- aligning and matching

def align(notes, fnotes, ncols):
    """chart_time = a + b * video_time: the anchor from the file's own notes, then a line."""
    seed, hit = Q.anchor_offset(notes, {c: [x[0] for x in v] for c, v in fnotes.items()}, ncols)
    a, b = -seed, 1.0
    n_fit = 0
    for _ in range(3):
        xs, ys = [], []
        for n in notes:
            col = fnotes.get(n["col"], [])
            if not col:
                continue
            u = a + b * n["t"]
            ts = [x[0] for x in col]
            j = bisect.bisect_left(ts, u - 0.06)
            if j < len(ts) and abs(ts[j] - u) <= 0.06:
                xs.append(n["t"]); ys.append(ts[j])
        n_fit = len(xs)
        if n_fit < 20:
            break
        b, a = np.polyfit(xs, ys, 1)
        b = float(min(1.01, max(0.99, b))); a = float(a)
    return a, b, n_fit, seed


def match(notes, fnotes, ncols, a, b):
    """One-to-one nearest matching per column within TOL. Returns pairs (note index, file
    entry), the unmatched extracted notes, the unmatched file entries, and the errors."""
    by_col = {c: [] for c in range(ncols)}
    for i, n in enumerate(notes):
        if 0 <= n["col"] < ncols:
            by_col[n["col"]].append((a + b * n["t"], i))
    pairs, extra, missing, errs = [], [], [], []
    for c in range(ncols):
        col = fnotes.get(c, [])
        ts = [x[0] for x in col]
        used = set()
        for u, i in sorted(by_col[c]):
            j = bisect.bisect_left(ts, u - TOL)
            best = None
            for k in (j - 1, j, j + 1, j + 2):
                if 0 <= k < len(ts) and k not in used and abs(ts[k] - u) <= TOL and (best is None or abs(ts[k] - u) < best[0]):
                    best = (abs(ts[k] - u), k)
            if best:
                used.add(best[1]); pairs.append((i, c, col[best[1]])); errs.append(best[0])
            else:
                extra.append(i)
        missing += [(c, x) for k, x in enumerate(col) if k not in used]
    return pairs, extra, missing, errs


# ---------------------------------------------------------------- the diff, and applying it

def flashed(flashes, col, t):
    ts = (flashes or {}).get(col) or []
    j = bisect.bisect_left(ts, t - FLASH_TOL)
    return j < len(ts) and abs(ts[j] - t) <= FLASH_TOL


def plan(notes, blk, a, b, flashes=None):
    """Every difference between what the screen showed and what the file says, classified."""
    ncols = blk["ncols"]
    fnotes, fholds = file_events(blk["rows"], ncols)
    beat_at, time_at = clocks(blk["rows"])
    pairs, extra, missing, errs = match(notes, fnotes, ncols, a, b)
    n_file = sum(len(v) for v in fnotes.values())
    tail_of = {(h["col"], round(h["head_beat"], 6)): h for h in fholds}
    edits, seen = [], Counter()
    typical = float(np.median([notes[i]["frames"] for i, _, _ in pairs])) if pairs else 0.0
    missed_t = sorted(a_ + 0 for a_ in (x[0] for _, x in missing))

    def solid(n):
        ok = n.get("rail_len", 0) >= RAIL_LEN and n.get("rail_occ", 0) >= RAIL_OCC
        if not ok:
            seen["thin rail"] += 1
        return ok

    for i, c, (ft, fb, sym) in pairs:
        n = notes[i]
        ext_hold = n.get("hold_end") is not None and solid(n)
        if sym == "1" and ext_hold:
            tb, g = snap(a + b * n["hold_end"], beat_at, time_at)
            hb = Fraction(fb).limit_denominator(192)
            if tb <= hb:
                tb = hb + Fraction(1, 48)
            edits.append(dict(kind="tap->hold", col=c, head=str(hb), tail=str(tb), grid=g, head_t=round(ft, 3), tail_t=round(a + b * n["hold_end"], 3)))
        elif sym == "2" and ext_hold:
            h = tail_of.get((c, round(fb, 6)))
            if h is None:
                continue
            new_t = a + b * n["hold_end"]
            if abs(new_t - h["tail"]) > TAIL_TOL:
                tb, g = snap(new_t, beat_at, time_at)
                hb = Fraction(h["head_beat"]).limit_denominator(192)
                if tb <= hb:
                    tb = hb + Fraction(1, 48)
                old = Fraction(h["tail_beat"]).limit_denominator(192)
                if tb != old:
                    edits.append(dict(kind="tail", col=c, head=str(hb), old=str(old), tail=str(tb), grid=g, old_t=round(h["tail"], 3), tail_t=round(new_t, 3)))
        elif sym == "2" and not ext_hold:
            seen["hold->tap"] += 1
    fakes = blk.get("fakes") or {}
    for i in extra:
        n = notes[i]
        t = a + b * n["t"]
        # a fake is drawn and never judged: an extracted note on one is that fake, and it is
        # neither an addition nor a miss of the reader's (the 49 StepF2 charts park on precision
        # without this, at 83% on Club Night D18 with its 11 fake hold pairs seen exactly)
        ft = fakes.get(n["col"], [])
        j = bisect.bisect_left(ft, t - TOL)
        if j < len(ft) and abs(ft[j] - t) <= TOL:
            seen["fake on screen"] += 1
            continue
        if flashes is not None and not flashed(flashes, n["col"], n["t"]):
            seen["unflashed addition"] += 1
            continue
        near = [x[0] for x in fnotes.get(n["col"], [])]
        j = bisect.bisect_left(near, t - DUP_TOL)
        if j < len(near) and abs(near[j] - t) <= DUP_TOL:
            seen["duplicate of a file note"] += 1
            continue
        if typical and n["frames"] < FRAMES_SHARE * typical:
            seen["short streak"] += 1
            continue
        j = bisect.bisect_left(missed_t, t - CONFUSION)
        if j < len(missed_t) and abs(missed_t[j] - t) <= CONFUSION:
            seen["column confusion"] += 1
            continue
        hb, g = snap(t, beat_at, time_at)
        if n.get("hold_end") is not None and solid(n):
            tb, g2 = snap(a + b * n["hold_end"], beat_at, time_at)
            if tb <= hb:
                tb = hb + Fraction(1, 48)
            edits.append(dict(kind="add-hold", col=n["col"], head=str(hb), tail=str(tb), grid=g, head_t=round(t, 3), tail_t=round(a + b * n["hold_end"], 3)))
        else:
            edits.append(dict(kind="add-tap", col=n["col"], head=str(hb), grid=g, head_t=round(t, 3)))
    seen["missing"] = len(missing)
    stats = dict(file_notes=n_file, extracted=len(notes), matched=len(pairs),
                 recall=round(len(pairs) / max(n_file, 1), 4), precision=round(len(pairs) / max(len(notes) - seen["fake on screen"], 1), 4),
                 err_median_ms=round(1000 * float(np.median(errs)), 1) if errs else None,
                 err_p90_ms=round(1000 * float(np.percentile(errs, 90)), 1) if errs else None,
                 file_holds=len(fholds), extracted_holds=sum(1 for n in notes if n.get("hold_end") is not None),
                 unseen=dict(seen), missing=[dict(col=c, t=round(x[0], 3), beat=round(x[1], 4), sym=x[2]) for c, x in missing][:200])
    return edits, stats


def apply(text, tag, edits, pad, width):
    """The edits on the block's note grid, in memory. Returns the new text and what happened."""
    sections, i = edit_notes.find_block(text, tag)
    span, measures = edit_notes.parse_notes(sections[i])
    cols = edit_notes.width(measures[0][0])
    done, skipped, cleared = [], [], 0
    # every look at a panel goes through edit_notes.get/put: a StepF2 cell is one panel, and a
    # fake-flagged one reads as empty here exactly as the converter reads it

    def covers(measures, col, b1, b2):
        return any(edit_notes.get(row, col) != "0" and b1 + 1e-6 < 4 * mi + 4 * r / len(rows) < b2 - 1e-6
                   for mi, rows in enumerate(measures) for r, row in enumerate(rows))

    def clear_between(col, b1, b2):
        n = 0
        for mi, rows in enumerate(measures):
            for r, row in enumerate(rows):
                beat = 4 * mi + 4 * r / len(rows)
                if b1 + 1e-6 < beat < b2 - 1e-6 and edit_notes.get(row, col) != "0":
                    measures[mi][r] = edit_notes.put(row, col, "0")
                    n += 1
        return n

    def sound(col):
        """A column reads 2 ... 3 with nothing inside, and no 3 without a 2 before it."""
        open_ = False
        for rows in measures:
            for row in rows:
                ch = edit_notes.get(row, col)
                if ch == "3":
                    if not open_:
                        return False
                    open_ = False
                elif ch in "12":
                    if open_:
                        return False
                    open_ = ch == "2"
        return not open_

    for e in edits:
        col = e["col"] - pad
        if col < 0 or col >= width:
            skipped.append({**e, "why": "outside the file's panels"}); continue
        head = float(Fraction(e["head"]))
        before = [list(rows) for rows in measures]
        try:
            if e["kind"] in ("tap->hold", "add-hold"):
                tail = float(Fraction(e["tail"]))
                if covers(measures, col, head, tail):
                    skipped.append({**e, "why": "the rail spans notes the file has in that column"}); continue
                edit_notes.set_char(measures, head, col, "2", cols)
                edit_notes.set_char(measures, tail, col, "3", cols)
                cleared += clear_between(col, head, tail)
            elif e["kind"] == "tail":
                old = float(Fraction(e["old"])); tail = float(Fraction(e["tail"]))
                mi, r = edit_notes.beat_to_pos(measures, old, cols)
                row = measures[mi][r]
                if edit_notes.get(row, col) != "3":
                    skipped.append({**e, "why": "no release at the old beat"}); continue
                measures[mi][r] = edit_notes.put(row, col, "0")
                edit_notes.set_char(measures, tail, col, "3", cols)
                cleared += clear_between(col, head, tail)
            elif e["kind"] == "add-tap":
                mi, r = edit_notes.beat_to_pos(measures, head, cols)
                if edit_notes.width(measures[mi][r]) <= col or edit_notes.get(measures[mi][r], col) != "0":
                    skipped.append({**e, "why": "the row is taken or narrower than the column"}); continue
                edit_notes.set_char(measures, head, col, "1", cols)
            if not sound(col):
                measures[:] = before
                skipped.append({**e, "why": "would leave the column's holds inconsistent"}); continue
            done.append(e)
        except SystemExit as ex:
            measures[:] = before
            skipped.append({**e, "why": str(ex)[:80]})
    body = "\n,\n".join("\n".join(rows) for rows in measures)
    sections[i] = sections[i][:span[0]] + body + sections[i][span[1]:]
    return "#NOTEDATA:;".join(sections), done, skipped, cleared


# ---------------------------------------------------------------- one chart

def survey_chart(entry, ssc_override=None, expected_override=None):
    name, key, tag = entry["chart"], entry["key"], block_tag(entry["key"])
    ssc = ssc_override or os.path.join(ROOT, "simfiles", *entry["ssc_rel"].split("/"))
    expected = expected_override or entry["expected"]
    rec = dict(chart=name, key=key, ssc_rel=entry["ssc_rel"], vid=entry["vid"], side=entry["side"],
               shape=entry["shape"], expected=expected, verdict="PARK")
    if not expected:
        return {**rec, "reason": "no certified count"}
    if entry["shape"] == "duplicate-block":
        return {**rec, "reason": "duplicate old-pack block of a re-rated chart"}
    blk = load_block(ssc, tag)
    if not blk or blk.get("error"):
        return {**rec, "reason": "file: " + ((blk or {}).get("error") or "block not found")}
    rec["file"] = dict(taps=blk["taps"], ticks=blk["ticks"], implied=blk["implied"], width=blk["width"])
    if "--exact-first" in sys.argv and blk["implied"] == expected:
        # a re-grade, not a census of the reader: an exact file needs no footage read
        return {**rec, "verdict": "EXACT", "reason": "already exact at %d (not read: --exact-first)" % expected}
    try:
        notes, meta = note_extract.extract(name, quiet=True)
    except Exception as ex:
        return {**rec, "verdict": "FAIL", "reason": "extraction: " + f"{type(ex).__name__}: {ex}"[:120]}
    rec["footage"] = dict(band=meta["band"], fps=round(meta["fps"], 2), correlation=meta["floor"], colour=meta["colour"])
    ncols = blk["ncols"]
    fnotes, _ = file_events(blk["rows"], ncols)
    a, b, n_fit, seed = align(notes, fnotes, ncols)
    rec["alignment"] = dict(offset=round(-a / b if b else -a, 3), clock=round(100 * (b - 1), 4), anchor=round(seed, 3), fitted_on=n_fit)
    edits, stats = plan(notes, blk, a, b, meta.get("flashes"))
    rec["extraction"] = stats
    rec["diff"] = dict(Counter(e["kind"] for e in edits))
    rec["diff"].update({k: v for k, v in stats["unseen"].items()})
    rec["edits"] = edits
    if blk["implied"] == expected:
        return {**rec, "verdict": "EXACT", "reason": "already exact at %d; %d edit(s) the loop would have tried" % (expected, len(edits))}
    if stats["recall"] < RECALL_BAR or stats["precision"] < PRECISION_BAR:
        return {**rec, "reason": "extraction recall %.1f%% / precision %.1f%% against the file - below the bar" % (100 * stats["recall"], 100 * stats["precision"])}
    adds = [e for e in edits if e["kind"].startswith("add")]
    if len(adds) > ADD_SHARE * stats["file_notes"]:
        return {**rec, "reason": "%d additions against %d notes - more than %.0f%% of the chart, not believed" % (len(adds), stats["file_notes"], 100 * ADD_SHARE)}
    if not edits:
        return {**rec, "reason": "the screen shows the file's notes exactly, yet the count is %+d - ticks, not notes" % (blk["implied"] - expected)}
    text = open(ssc, encoding="utf-8", newline="").read()
    pad = (ncols - blk["width"]) // 2
    new_text, done, skipped, cleared = apply(text, tag, edits, pad, blk["width"])
    os.makedirs(OUT, exist_ok=True)
    cand = os.path.join(OUT, ("proof-" if ssc_override else "") + key + ".ssc")
    open(cand, "w", encoding="utf-8", newline="").write(new_text)
    after = load_block(cand, tag)
    rec.update(candidate=os.path.relpath(cand, ROOT), applied=len(done), skipped=skipped, cleared=cleared,
               after=dict(taps=after["taps"], ticks=after["ticks"], implied=after["implied"]) if after and not after.get("error") else dict(error=(after or {}).get("error", "no block")))
    if not after or after.get("error"):
        return {**rec, "reason": "candidate did not convert: " + rec["after"].get("error", "")}
    if after["implied"] == expected:
        return {**rec, "verdict": "SHIP", "reason": "%s -> taps %d + ticks %d = %d, exact" % (summary(done), after["taps"], after["ticks"], after["implied"])}
    return {**rec, "reason": "%s -> %d, off %+d from %d" % (summary(done), after["implied"], after["implied"] - expected, expected)}


def summary(edits):
    c = Counter(e["kind"] for e in edits)
    parts = []
    if c["tap->hold"]:
        parts.append("%d hold%s the file wrote as taps" % (c["tap->hold"], "" if c["tap->hold"] == 1 else "s"))
    if c["tail"]:
        parts.append("%d release%s moved" % (c["tail"], "" if c["tail"] == 1 else "s"))
    if c["add-hold"]:
        parts.append("%d hold%s added" % (c["add-hold"], "" if c["add-hold"] == 1 else "s"))
    if c["add-tap"]:
        parts.append("%d tap%s added" % (c["add-tap"], "" if c["add-tap"] == 1 else "s"))
    return ", ".join(parts) or "no edit"


# ---------------------------------------------------------------- survey and commit

def report_path(shard):
    return os.path.join(ROOT, "work", "extract-loop-report%s.json" % (("." + shard.split("/")[0]) if shard else ""))


def survey():
    note_extract.CACHE = "--cache" in sys.argv
    only, limit, shard = arg("--only"), arg("--limit"), arg("--shard")
    shapes = (arg("--shapes") or ",".join(SHAPE_ORDER)).split(",")
    allc = charts()
    jobs = [c for c in allc.values() if c["shape"] in shapes and (not only or c["chart"] == only)]
    jobs.sort(key=lambda c: (SHAPE_ORDER.index(c["shape"]) if c["shape"] in SHAPE_ORDER else 99, c["chart"]))
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        jobs = jobs[i::n]
    if limit:
        jobs = jobs[:int(limit)]
    path = report_path(shard)
    prior = {r["chart"]: r for r in json.load(open(path, encoding="utf-8"))} if os.path.exists(path) and "--redo" not in sys.argv else {}
    if arg("--redo-verdict"):           # e.g. --redo-verdict FAIL: those charts run again, the rest keep their record
        prior = {k: v for k, v in prior.items() if v.get("verdict") not in arg("--redo-verdict").split(",")}
    if arg("--redo-reason"):            # e.g. --redo-reason stepf2: the charts parked for that reason run again
        prior = {k: v for k, v in prior.items() if arg("--redo-reason") not in (v.get("reason") or "")}
    ssc_override, expected_override = arg("--ssc"), arg("--expected")
    if ssc_override:
        prior = {}
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    for i, entry in enumerate(jobs, 1):
        if entry["chart"] in prior:
            continue
        t1 = time.time()
        try:
            rec = survey_chart(entry, ssc_override, int(expected_override) if expected_override else None)
        except Exception as ex:
            rec = dict(chart=entry["chart"], key=entry["key"], verdict="FAIL", reason=f"{type(ex).__name__}: {ex}"[:160])
        rec["seconds"] = round(time.time() - t1, 1)
        prior[entry["chart"]] = rec
        print("[%d/%d] %-5s %-46s %s (%ss)" % (i, len(jobs), rec["verdict"], entry["chart"][:46], rec.get("reason", "")[:90], rec["seconds"]), flush=True)
        if not ssc_override:
            json.dump(list(prior.values()), open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if ssc_override:
        for r in prior.values():
            json.dump(r, open(os.path.join(OUT, "proof-" + r["key"] + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n%d charts in %.0fs; verdicts %s" % (len(jobs), time.time() - t0, dict(Counter(r["verdict"] for r in prior.values()))))


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout


def applied(rec):
    """The edits that went in: the plan minus what the applier skipped (a skipped entry is the
    edit plus a `why`, so it matches on every field the edit has)."""
    skipped = rec.get("skipped", [])
    return [d for d in rec["edits"] if not any(all(sk.get(k) == v for k, v in d.items()) for sk in skipped)]


def edit_line(d):
    """One applied edit, as a commit message states it."""
    if d["kind"] == "tap->hold":
        return "col %d beat %s: the tap is a hold, rail to beat %s (%.2f-%.2fs)" % (d["col"], d["head"], d["tail"], d["head_t"], d["tail_t"])
    if d["kind"] == "tail":
        return "col %d beat %s: release moved %s -> %s (%.2f -> %.2fs)" % (d["col"], d["head"], d["old"], d["tail"], d["old_t"], d["tail_t"])
    if d["kind"] == "add-hold":
        return "col %d: hold added at beat %s to %s (%.2f-%.2fs)" % (d["col"], d["head"], d["tail"], d["head_t"], d["tail_t"])
    return "col %d: tap added at beat %s (%.2fs)" % (d["col"], d["head"], d["head_t"])


def message(rec, note=None):
    e = applied(rec)
    x, al, ft = rec["extraction"], rec["alignment"], rec["footage"]
    lines = ["Fix %s from the footage: %s" % (rec["chart"], summary(e)), ""]
    lines.append("Evidence: the certified chart video %s (%s, band %s), result screen judged %d, read by" % (rec["vid"], rec["side"], ft["band"], rec["expected"]))
    lines.append("tools/note_extract.py and diffed against the file by tools/extract_repair.py. The extraction")
    lines.append("found %d of the file's %d notes (%.1f%%; %d extracted, %.1f%% of them in the file), median timing" % (x["matched"], x["file_notes"], 100 * x["recall"], x["extracted"], 100 * x["precision"]))
    lines.append("error %s ms, offset %+.3fs, clock %+.4f%%. Every edit is something the screen showed:" % (x["err_median_ms"], al["offset"], al["clock"]))
    for d in e:
        lines.append("  " + edit_line(d))
    if rec.get("cleared"):
        lines.append("  (%d tap(s) the file wrote inside those holds cleared)" % rec["cleared"])
    if rec.get("skipped"):
        lines.append("Proposed by the diff but not applied: " + "; ".join(
            "%s col %d beat %s (%s)" % (d["kind"], d["col"], d["head"], d["why"]) for d in rec["skipped"]))
    un = rec["extraction"]["unseen"]
    if un.get("missing") or un.get("hold->tap"):
        lines.append("Not applied: %d file note(s) the extraction did not find and %d hold(s) it read as taps -" % (un.get("missing", 0), un.get("hold->tap", 0)))
        lines.append("a reader's miss is not evidence against the file.")
    lines.append("")
    lines.append("Before: taps %d + ticks %d = %d. After: taps %d + ticks %d = %d, the judged count exactly" % (rec["file"]["taps"], rec["file"]["ticks"], rec["file"]["implied"], rec["after"]["taps"], rec["after"]["ticks"], rec["after"]["implied"]))
    lines.append("(tick_verify). No frame was read by eye.")
    if note:
        lines += ["", note]
    return "\n".join(lines) + TRAILER


def same_outside(text_a, text_b, tag):
    """Whether two versions of a song file agree everywhere except inside one block.

    A candidate is a whole-file copy made from the file as it stood when the survey ran. When
    two charts of ONE song file both ship, the second candidate still carries the first block
    as it was before its fix, and copying it in silently undoes that fix - Higgledy Piggledy
    S15's commit (9e281f7) put S16 back to its +8 state minutes after 32c0ca9 had fixed it,
    and the in-place check, which only reads the block being committed, said MATCH. So a
    candidate is only copied in when the file has not changed outside its own block."""
    def norm(t):
        return t.replace("\r\n", "\n")
    sa, ia = edit_notes.find_block(norm(text_a), tag)
    sb, ib = edit_notes.find_block(norm(text_b), tag)
    return ia == ib and len(sa) == len(sb) and all(x == y for k, (x, y) in enumerate(zip(sa, sb)) if k != ia)


def commit():
    only, dry, note = arg("--only"), "--dry-run" in sys.argv, arg("--note")
    recs = []
    for f in sorted(os.listdir(os.path.join(ROOT, "work"))):
        if f.startswith("extract-loop-report") and f.endswith(".json"):
            recs += json.load(open(os.path.join(ROOT, "work", f), encoding="utf-8"))
    ships = [r for r in recs if r.get("verdict") == "SHIP" and not r.get("commit") and (not only or r["chart"] == only)]
    print("%d SHIP verdict(s) to commit" % len(ships))
    if git("status", "--short", "--", "simfiles").strip():
        sys.exit("simfiles/ has uncommitted changes - refusing")
    for r in ships:
        ssc = os.path.join(ROOT, "simfiles", *r["ssc_rel"].split("/"))
        cand = os.path.join(ROOT, r["candidate"])
        if not os.path.exists(cand):
            print("  %s: candidate missing, skipped" % r["chart"]); continue
        if not same_outside(open(ssc, encoding="utf-8", newline="").read(), open(cand, encoding="utf-8", newline="").read(), block_tag(r["key"])):
            print("  %s: the file changed outside this block since the candidate was written (another chart of the same "
                  "song was repaired) - re-run the survey for it and commit again" % r["chart"]); continue
        shutil.copyfile(cand, ssc)
        out = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "tools", "tick_verify.py"), "--file", ssc, "--block", block_tag(r["key"]), str(r["expected"])],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        if "MATCH" not in out:
            git("checkout", "HEAD", "--", ssc)
            print("  %s: tick_verify did not agree in place (%s) - reverted" % (r["chart"], out.strip().splitlines()[0] if out.strip() else "no output")); continue
        if dry:
            git("checkout", "HEAD", "--", ssc)
            print("  would commit %s: %s" % (r["chart"], r["reason"])); continue
        git("add", "--", ssc)
        subprocess.run(["git", "commit", "-q", "-F", "-"], cwd=ROOT, input=message(r, note), text=True, encoding="utf-8")
        sha = git("rev-parse", "--short", "HEAD").strip()
        r["commit"] = sha
        print("  %s %s: %s" % (sha, r["chart"], r["reason"]))
    if not dry:
        # write the commits back so a re-run does not commit them twice
        by_file = {}
        for f in sorted(os.listdir(os.path.join(ROOT, "work"))):
            if f.startswith("extract-loop-report") and f.endswith(".json"):
                p = os.path.join(ROOT, "work", f)
                rows = json.load(open(p, encoding="utf-8"))
                done = {r["chart"]: r for r in ships if r.get("commit")}
                rows = [done.get(x["chart"], x) for x in rows]
                json.dump(rows, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["survey"]:
        survey()
    elif sys.argv[1:2] == ["commit"]:
        commit()
    else:
        sys.exit("usage: extract_repair.py survey [...] | commit [--dry-run]")
