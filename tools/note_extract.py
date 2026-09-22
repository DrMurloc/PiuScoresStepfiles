# Read the chart off the screen: which column, when, and how long.
#
# A note is not an event at a line, it is a STREAK. Watch one column over time and the arrows
# are parallel diagonals in a time-by-height picture, rising as they scroll toward the receptors
# at the top of the screen. That framing solves the things a threshold at a fixed line cannot:
#
#   - the slope of a streak IS the local scroll speed, so tempo changes, speed mods and stops
#     need no assumption and no global lead - the streak simply bends;
#   - the crossing time comes from extrapolating the streak to the judgement line, which is
#     sub-frame accurate even when a fast chart only shows the arrow for two or three frames;
#   - two notes close together stay two parallel streaks, where one line would merge them;
#   - a hold is a streak that keeps arriving - its head and tail are the ends of one long run.
#
# WHAT an arrow is comes from sprites.py: the game draws its notes from five fixed pictures and
# hands them to us at the top of the screen as the receptors, so a note is found by MATCHING THE
# PICTURE. What came before was a shape statistic - a compact blob, bright and saturated, about
# one lane across - which bright art satisfies constantly and a dim arrow fails; it is deleted
# rather than kept as a fallback, because the sprite matcher beat it on five of six measured
# charts, took the worst of them from 62% recall to 100%, and needs no brightness threshold to
# tune, which is six decodes of the video it also does not need. Correlation reads structure and
# not colour, so a chart that recolours its notes matches the same template.
#
# ONE decode does everything: the sprite correlations, the receptor flashes that say which
# correlation to believe, and the lane rails that say which taps are holds.
#
#   python -X utf8 tools/note_extract.py "<chart>" [--dump <file.json>] [--quiet]
import bisect
import json
import os
import pickle
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_map      # noqa: E402
import receptors as R  # noqa: E402
import sprites            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP, BOTTOM = 20, 430     # the band under the receptors that is watched, in px below the band
MIN_TRACK = 3             # frames a streak must persist to be believed
# Measured across six charts: 0.44-0.52 is the sweet spot everywhere and a floor BELOW 0.36
# costs recall rather than buying it - the extra peaks drown the tracker, which then links
# runs to the wrong streaks and hands the speed filter a polluted median.
#
# But those six charts all came from ONE uploader, and a correlation is not comparable across
# footage of different contrast. Sampled over sixteen videos the two sources in this corpus do
# not overlap: NEVSISTER's templates average 70.9 and the official channel's 44.6. So the
# numbers above are read as belonging to footage of REFERENCE contrast, and scaled to whatever
# is in front of us - the templates' own standard deviation, which is known before a single
# frame of play is decoded. Footage as crisp as the charts these were tuned on keeps them
# exactly - and all fifteen published charts measure at full scale, so none of them can test it.
#
# The evidence that motivated it is WITHDRAWN. Andamiro's L (PIU Edit) D27 read 37 and found 152
# notes in thirty seconds at 0.36 against 612 at 0.18 - through lanes fitted 46px wrong. Through
# the corrected lanes its templates read 49, the extraction barely moves between 0.34 and 0.52
# (1,275-1,285 notes), and its own combo counter says every floor from 0.48 up is exact on each
# hold-free stretch: higher than the 0.42 this scaling lets it reach. It stays until a genuinely
# soft official video is measured, because removing it untested would be the same mistake again.
#
# The alternative - one adaptive rule for everyone, floors as quantiles of each video's own
# peaks - is in EXTRACTION.md as a measured failure. It cost Bee S17 four points of recall
# whether the quantiles replaced the old floors or were merely added to them, because both
# versions had to drop the DETECTION floor for everybody to compute a quantile at all.
FLOORS = (0.36, 0.44, 0.52, 0.60)
REFERENCE = 70.0          # template contrast the floors above were measured at
TIE = 0.005               # flash scores this close to the best are a tie, won by the strictest floor
SCALE = 0.5               # sprite matching runs at half resolution
SEP = 0.5                 # peaks nearer than this many sprite-heights are one arrow
ANCHOR = 50               # percentile over time the receptor picture is read at
HIPASS = 0.0              # rows, in sprite heights, the smooth-down-the-screen part is
                          # measured over and removed from both pictures
REST = 0.0                # share of a column's own dimmest frames the receptor is read from
MERGE = 0.015             # two detections nearer than this in one column are one note
# The decode is the whole cost, and everything after it - which correlation to believe, the
# holds, the grid - is post-processing worth re-running many times over the same pass. Off by
# default: a corpus run of two thousand charts should not leave two thousand of these behind.
CACHE = False
# Sharpen the receptor into the note the game actually draws, from the notes a receptor
# pass was surest of. Costs a second decode, so it is a choice rather than the default.
REFINE = False

def sprite_frames(vid, band, ncols, t_end, tmpl, floor=0.30, t0=0.0, scale=SCALE,
                  collect=None, collect_floor=0.60, side="1p"):
    """Every frame, where each column's sprite correlates. Same shape as arrow_blobs' output,
    but each hit carries its correlation so one decode can be re-cut at several thresholds.

    Correlating at half resolution costs eight times less and loses nothing that matters: the
    peak lands within a pixel or two of where it would, which is a few milliseconds of scroll,
    and the crossing time is a line fitted through forty of them anyway."""
    cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
    y0, y1, xs = R.field(cap, vid, band, ncols, side)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60
    tw, th = sprites.size_for(float(np.median(np.diff(xs))))
    sc = float(scale)
    stw, sth = max(5, int(round(tw * sc))), max(5, int(round(th * sc)))
    small = [None if T is None else cv2.resize(T, (stw, sth), interpolation=cv2.INTER_AREA)
             for T in tmpl]
    by_col = [small[c % 5] for c in range(ncols)]
    sxs = [x * sc for x in xs]
    half = int(float(np.median(np.diff(xs))) * 0.28)
    cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
    frames, ts, t, i, flash, lane = [], [], t0, 0, [], []
    while t < t_end:
        # the container's own timestamp, not t += 1/fps: a dropped frame or a 59.94 stream that
        # reports 60 turns an accumulated count into drift, and drift is indistinguishable here
        # from the chart being wrong. Some containers report nothing, so counting is the floor.
        pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        count = t0 + i / (fps or 60.0)
        t = pos if (not ts and pos >= 0) or (ts and pos > ts[-1] + 1e-6) else count
        ok, f = cap.read()
        if not ok:
            break
        i += 1
        # the receptors and the lane under them come off the SAME decoded frame - reading the
        # judged events and the hold rails used to cost a second pass over the whole video
        # the channel minimum only inside the receptor boxes. Over the full width it was 4ms a
        # frame - more than decoding the frame - for pixels no column ever reads.
        row = []
        for x in xs:
            b = f[y0:y1, x - half:x + half]
            row.append(float(np.minimum(np.minimum(b[:, :, 0], b[:, :, 1]), b[:, :, 2]).mean()))
        flash.append(row)
        bar = cv2.cvtColor(f[y1 + 8:y1 + 88], cv2.COLOR_BGR2HSV)
        bar = (bar[:, :, 1] > 130) & (bar[:, :, 2] > 120)
        lane.append([float(bar[:, x - 20:x + 20].mean()) for x in xs])
        strip = f[y1 + TOP:y1 + BOTTOM]
        full = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(full, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA) if sc != 1.0 else full
        if HIPASS:
            gray = sprites.highpass(gray, HIPASS * sth)
        pk = []
        for c, col in enumerate(sprites.peaks(gray, sxs, by_col, stw, sth, floor,
                                              max(2, int(round(sth * SEP))))):
            row = []
            for a, _, q in col:
                yy = int(round(a / sc))
                row.append((yy, yy + th, q,
                            sprites.colourfulness(strip, yy, int(round(xs[c] - tw / 2.0)), th, tw)))
            pk.append(row)
        if collect is not None:
            # the notes THIS pass was surest of, at full resolution, to sharpen the template on
            for c, hits in enumerate(pk):
                for a, _, q, _s in hits:
                    if q >= collect_floor:
                        cp = sprites.crop(full, a + th / 2.0, xs[c], th, tw)
                        if cp is not None:
                            collect[c % 5].append(cp)
        frames.append(pk)
        ts.append(t)
    cap.release()
    scan = dict(ts=np.array(ts), flash=np.array(flash), lane=np.array(lane), xs=xs,
                fps=fps, y0=y0, y1=y1)
    return np.array(ts), frames, fps, y0, y1, scan

def at_floor(scored, floor, sat=0.0):
    """Cut a sprite pass at a correlation threshold, and optionally at a colour floor."""
    return [[[(a, b) for a, b, q, s in col if q >= floor and s >= sat]
             for col in fr] for fr in scored]

def colour_floor(scored, floor, strong=0.60, share=0.35):
    """How colourless a detection may be, learned from this chart's own confident ones.

    A chart is not asked what colour its notes are - only that a note looks like the notes this
    chart already showed us at a correlation nothing else reaches. On a monochrome BGA that
    single number removes almost every false positive; on a chart whose notes really are pale it
    learns a low bar and removes nothing, which is the correct behaviour rather than a failure.
    """
    sats = [s for fr in scored for col in fr for a, b, q, s in col if q >= strong]
    if len(sats) < 40:
        return 0.0
    return float(np.percentile(sats, 10)) * share

def anchor_set(vid, band, ncols, side="1p"):
    """The five receptor sprites for this video, plus the box they are read at."""
    path = os.path.join(ROOT, "videos", vid + ".mp4")
    cap = cv2.VideoCapture(path)
    y0, y1, xs = R.field(cap, vid, band, ncols, side)
    cap.release()
    tw, th = sprites.size_for(float(np.median(np.diff(xs))))
    return sprites.anchors(path, vid + "." + side, band, y0, y1, xs, th, tw,
                           pct=ANCHOR, hp=HIPASS, rest=REST), th, tw

def harvest(vid, band, ncols, t0, t1, side="1p"):
    """The five sprites: the receptors, sharpened by the notes a receptor pass was surest of.

    The bootstrap used to run off the blob detector, which meant inheriting its blind spots and
    paying for its tuning. A receptor pass is both better and free of that: it is already the
    detector, so its own confident hits are cleaner samples than the blob detector's best."""
    anc, th, tw = anchor_set(vid, band, ncols, side)
    bins = [[] for _ in range(5)]
    sprite_frames(vid, band, ncols, t1, anc, FLOORS[0], t0, collect=bins, side=side)
    return sprites.build(bins, anc, th, tw)


def track(ts, frames, col, fps):
    """Link a column's runs across frames into streaks. A run belongs to the streak whose
    predicted position it lands on; notes only ever move up, and always at the same speed."""
    live, done = [], []
    for i, per_col in enumerate(frames):
        runs = per_col[col]
        used = set()
        for tr in live:
            dt = 1
            pred = tr["y"][-1] + tr["v"] * dt if len(tr["y"]) > 1 else tr["y"][-1]
            best, bj = 26.0, -1
            for j, (a, b) in enumerate(runs):
                if j in used:
                    continue
                mid = a
                if abs(mid - pred) < best:
                    best, bj = abs(mid - pred), j
            if bj >= 0:
                a, b = runs[bj]
                used.add(bj)
                mid = a
                if len(tr["y"]) >= 1:
                    tr["v"] = 0.6 * tr["v"] + 0.4 * (mid - tr["y"][-1]) if len(tr["y"]) > 1 else mid - tr["y"][-1]
                tr["y"].append(mid); tr["t"].append(ts[i]); tr["run"].append((a, b))
                tr["miss"] = 0
            else:
                tr["miss"] += 1
        for tr in list(live):
            if tr["miss"] > 2:
                done.append(tr); live.remove(tr)
        for j, (a, b) in enumerate(runs):
            if j not in used:
                live.append(dict(y=[a], t=[ts[i]], run=[(a, b)], v=-8.0, miss=0))
    return done + live

def notes_from_tracks(tracks, y_judge_px, fps):
    """Where each streak reaches the judgement line, and how long it kept arriving."""
    out = []
    for tr in tracks:
        if len(tr["t"]) < MIN_TRACK:
            continue
        y = np.array(tr["y"], dtype=float)
        t = np.array(tr["t"], dtype=float)
        # a note rises; fit its line and read off when it reaches the judgement row
        A = np.vstack([t, np.ones_like(t)]).T
        v, c = np.linalg.lstsq(A, y, rcond=None)[0]
        if v > -60:                                  # not moving up: lane lighting, not a note
            continue
        t_hit = (y_judge_px - c) / v
        # a hold keeps feeding the column: the run stays tall long after the head goes by
        tall = max(b - a for a, b in tr["run"])
        # the streak's centroid and the line it is extrapolated to travel with it, so a note can be
        # re-timed at the scroll speed around it instead of its own slope - author_new.retime does
        # that for a chart it writes; the extractor itself does not (EXTRACTION.md says why)
        out.append(dict(t=float(t_hit), v=float(v), tall=int(tall),
                        frames=len(tr["t"]), first=float(t[0]), last=float(t[-1]),
                        mt=float(t.mean()), my=float(y.mean()), yj=float(y_judge_px), fps=float(fps)))
    return out

def flash_agreement(cand, flashes, lead, tol=0.07):
    """How well an extraction lines up with the judged events seen at the receptor."""
    if not flashes or len(cand) < 15:
        return 0.0
    best = 0.0
    for off in np.arange(lead - 0.25, lead + 0.25, 0.01):
        hit = 0
        for c, ts_ in flashes.items():
            got = sorted(n["t"] + off for n in cand if n["col"] == c)
            if not got:
                continue
            for t in ts_:
                i = bisect.bisect_left(got, t - tol)
                if i < len(got) and abs(got[i] - t) <= tol:
                    hit += 1
        n_f = sum(len(v) for v in flashes.values())
        if n_f:
            p, r = hit / len(cand), hit / n_f
            best = max(best, 2 * p * r / (p + r) if p + r else 0.0)
    return best

def _cand(ts, frames, ncols, y0, y1, fps):
    """Streaks to note events, for one detector's output over one window."""
    y_j = (y0 + y1) / 2 - (y1 + TOP)        # the judgement line, in the strip's coordinates
    out = []
    for c in range(ncols):
        for n in notes_from_tracks(track(ts, frames, c, fps), y_j, fps):
            n["col"] = c
            out.append(n)
    return out

def _clean(notes):
    """The two filters every detector's output goes through, in one place.

    One note can be tracked, lost behind an effect and re-acquired, arriving as two streaks that
    extrapolate to the same instant - so the nearer of two detections in one column is dropped.
    How near is MEASURED, not assumed. The assumption used to be "nothing in this game puts two
    notes in one column closer than a 16th at 300bpm", and across 2,326 charts that is false on
    11.5% of them; the 35ms this code actually used is false on 121 charts, 5.2%. Both were
    quietly deleting real notes on exactly the dense charts where every note is hardest to see.
    15ms is safe: two streaks that are the same arrow re-acquired share a trajectory and
    extrapolate to within a couple of milliseconds of each other, while the tightest real pair
    in the corpus is 34ms apart. Anything the time domain cannot separate is separated later on
    the beat grid, where a lattice line knows what a millisecond does not.

    Then: every real note falls at the scroll speed and the background does not, so a streak
    moving at a different rate is something in the art that happened to be arrow-shaped. The
    comparison is LOCAL - the median of the streaks around it - so a chart that changes tempo is
    judged against its own speed at that moment rather than the song's average.
    """
    notes = sorted(notes, key=lambda n: (n["t"], n["col"]))
    merged = {}
    for n in notes:
        prev = merged.get(n["col"])
        if prev and abs(n["t"] - prev[-1]["t"]) < MERGE:
            if n["frames"] > prev[-1]["frames"]:
                prev[-1] = n
            continue
        merged.setdefault(n["col"], []).append(n)
    notes = sorted((n for v in merged.values() for n in v), key=lambda n: (n["t"], n["col"]))
    if len(notes) > 30:
        sp = np.array([-n["v"] for n in notes])
        keep = []
        for i, n in enumerate(notes):
            med = float(np.median(sp[max(0, i - 25):i + 25]))
            if med > 0 and abs(-n["v"] - med) <= 0.40 * med:
                keep.append(n)
        notes = keep
    # A note lost behind an effect and re-acquired can also come back as a SHORT, SLOW streak
    # beside the long one: past the merge, because it extrapolates 30ms away rather than 2, and
    # past the speed filter, because 20% slow is inside 40%. On L (PIU Edit) D27 the combo counter
    # found exactly two false notes in its hold-free stretches and both were this - three frames,
    # 13-20% below scroll speed, 29 and 35ms behind a longer streak in the same column. Measured
    # across the fifteen published charts, dropping a streak of at most 4 frames that runs more
    # than 12% slow within 60ms of a longer one in its column deletes no real note, and 5 false.
    if len(notes) > 30:
        sp = np.array([-n["v"] for n in notes])
        cols = {}
        for i, n in enumerate(notes):
            cols.setdefault(n["col"], []).append(i)
        times = {c: [notes[i]["t"] for i in idx] for c, idx in cols.items()}
        drop = set()
        for i, n in enumerate(notes):
            if n["frames"] > 4:
                continue
            med = float(np.median(sp[max(0, i - 25):i + 25]))
            if med <= 0 or sp[i] > 0.88 * med:
                continue
            idx, tt = cols[n["col"]], times[n["col"]]
            for j in range(bisect.bisect_left(tt, n["t"] - 0.060), bisect.bisect_right(tt, n["t"] + 0.060)):
                if idx[j] != i and notes[idx[j]]["frames"] > n["frames"]:
                    drop.add(i)
                    break
        notes = [n for i, n in enumerate(notes) if i not in drop]
    return notes

def mark_holds(scan, notes, tol=0.15):
    """Which extracted taps are hold HEADS, and when each hold lets go.

    Nothing new has to see the hold body scrolling: the game already reports a held hold at the
    receptor, as a saturated bright rail down the lane, and receptors.rails reads it. A tap is a
    hold head when a rail opens on its column as it arrives; the rail's end is the tail.

    The rail is read in a box that starts a few pixels BELOW the receptor, so it opens a frame
    or so before the head is judged and closes after the tail has gone by. The lag is one
    constant per video - the box height over the scroll speed - and is taken out here.
    """
    # min_len is 0.065s, not the 0.30 the repair pipeline uses. That default is right there - it
    # prices long hold REGIONS - and catastrophic here: 78% of Bad Apple D20's 232 holds run for
    # 0.11s, so at 0.30 the rail reader saw 14 of them. Swept against both a hold-heavy chart
    # and a hold-free one: 0.065 keeps 220 of Bad Apple's 232 while cutting Bee S17, which has
    # ONE hold, from 29 rails to 8. Below that the floor itself is what most rails are - three
    # frames of a bright lane, which any number of things can be.
    rails = R.rails(scan, 0.40, 0.065)
    speeds = [-n["v"] for n in notes if n.get("v")]
    # The rail is read in a box 8px BELOW the receptor band, and the judgement line is the
    # middle of that band - so the box sees the hold while it is still short of being judged,
    # and BOTH edges of a rail are early by the same distance over the scroll speed. Getting
    # this wrong is not a small error: measured against Bad Apple D20's hold ends, subtracting
    # the box height instead of adding the gap put 99% of them outside a 120ms tolerance.
    d = ((scan["y1"] - scan["y0"]) / 2.0 + 8.0) / float(np.median(speeds)) if speeds else 0.06
    # A rail is claimed by exactly ONE note - the one nearest its start. Letting every note in
    # range claim it made the hold's own tail a second HEAD (on a 0.11s hold the tail is inside
    # any tolerance wide enough to catch the head), which then protected it from the suppression
    # below: 232 real holds came back as 400.
    n_hold, claimed = 0, {}
    for c, spans in rails.items():
        col = [n for n in notes if n["col"] == c]
        for k, (a, b) in enumerate(spans):
            win = min(tol, max(0.05, 0.6 * (b - a)))
            near = [n for n in col if abs(a + d - n["t"]) <= win]
            if not near:
                continue
            head = min(near, key=lambda n: abs(a + d - n["t"]))
            head["hold_end"] = b + d
            # what the rail looked like, for whoever has to decide whether to believe it: how
            # long it ran and how solidly the lane read as held over that time. A hold the game
            # draws fills the lane; a bright patch of art under one receptor does not.
            i0, i1 = np.searchsorted(scan["ts"], a), max(np.searchsorted(scan["ts"], b), np.searchsorted(scan["ts"], a) + 1)
            head["rail_len"] = float(b - a)
            head["rail_occ"] = float(np.mean(scan["lane"][i0:i1, c])) if i1 > i0 else 0.0
            claimed[(c, k)] = head
            n_hold += 1
    # A hold is drawn head, body, TAIL CAP - and the cap is the head's own sprite, so it
    # correlates exactly as well and arrives as a second note. It is not one: while a hold runs,
    # its panel is held down, so the game cannot put another note in that lane. Anything inside
    # the rail but not opening it is the hold's own artwork. On Bad Apple D20 - 232 holds
    # against 420 taps, where every other chart measured has nine or fewer - this was 260 extra
    # "notes" on its own.
    #
    # Only a rail some extracted note OPENED is trusted to swallow notes. A short bar of bright
    # saturated art in a lane also reads as a rail, and a rail nobody arrived at is exactly what
    # that looks like; deleting real notes inside one would be a silent, unrecoverable loss,
    # where keeping a tail is a false positive the count gate will catch.
    keep = []
    for n in notes:
        if any(claimed.get((n["col"], k)) is not n and a + d + 0.02 < n["t"] < b + d + 0.08
               for k, (a, b) in enumerate(rails.get(n["col"], [])) if (n["col"], k) in claimed):
            continue
        keep.append(n)
    notes[:] = keep
    return n_hold

def extract_video(vid, ncols, side="1p", band="C", dur=None, quiet=False):
    """Read a chart off a video this repo knows nothing else about.

    Everything else here starts from a chart NAME and works back to footage through the
    certification ledger, because it exists to repair files we already hold. This goes the other
    way, and it is the direction that matters most: Andamiro post an official video of a chart
    the day it ships, long before anyone writes a stepfile for it. Those uploads are AUTOPLAY -
    the game steps exactly on every arrow, so there are no misses, no mis-steps and no note that
    nobody hit - which is the best footage this detector will ever be given. They also carry NO
    RESULT SCREEN, all 477 of them in the corpus, so the certification gate that guards the
    repair path can never pass one. Identity comes from Andamiro's own title on the upload
    instead, which is the publisher naming their own chart.
    """
    if dur is None:
        cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
        dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 60)
        cap.release()
    return _read(vid, band, ncols, side, float(dur), quiet)

def extract(name, quiet=False):
    """Every tap the screen shows, as (video time, column), for a chart we already hold.

    ONE decode of the video. The sprite matcher needs no brightness threshold to tune, so the
    six extra passes the blob detector cost are gone; what is left to choose is how strong a
    correlation to believe, and that is re-cut from the one pass at no further cost.
    """
    cert = corpus_map.certification()
    ncols = 10 if name.split()[-1][0] == "D" else 5
    vid, e = next((v, e) for v, e in cert.items() if name in (e.get("charts") or {}))
    # An UNCERTIFIED video has not been shown to be this chart, and worse, nothing says WHICH
    # PAD was played - so the field to read is a guess, and on a two-player video a guess is
    # the wrong half of the screen. Five of the ten edge-case charts scored 17-69% this way and
    # every one of them was OPEN; the four certified ones scored 94-99%. Refusing is not
    # caution, it is the difference between a measurement and a number. extract_video is the
    # way in for footage that carries its identity some other way.
    if e["charts"][name].get("verdict") != "CERTIFIED":
        raise RuntimeError("%s is %s on %s - no certified result screen, so neither the chart "
                           "nor the pad is established" % (name, e["charts"][name].get("verdict"), vid))
    side = e["charts"][name].get("side") or "1p"
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    return _read(vid, band, ncols, side, float(e.get("t") or 150), quiet)

def _read(vid, band, ncols, side, dur, quiet):
    anc, th, tw = anchor_set(vid, band, ncols, side)
    if not any(A is not None for A in anc):
        raise RuntimeError("no receptor sprites for %s band %s" % (vid, band))
    # how sharp this footage is, before anything is decoded, capped so a crisper-than-reference
    # video is never asked for a HIGHER floor than the one that was measured
    sharp = float(np.mean([A.std() for A in anc if A is not None]))
    scale = min(1.0, sharp / REFERENCE)
    floors = [round(f * scale, 3) for f in FLOORS]
    if REFINE:
        anc, kept = harvest(vid, band, ncols, 0.5, min(60.0, dur), side)
    # the lanes are in the key for the reason they are in the template cache's: a pass read through
    # the wrong lanes is a different pass, and a key without them hands it back after a refit
    cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
    fxs = R.field(cap, vid, band, ncols, side)[2]
    cap.release()
    ck = os.path.join(ROOT, "work", "spritepass",
                      "%s.%s.%s.%d.%.2f.%.2f.%d.h%.2f.r%.2f.s%.2f.%.1f.x%d-%d%s.pkl" % (vid, band, side, ncols, SCALE, SEP,
                                          ANCHOR, HIPASS, REST, scale, dur, fxs[0], fxs[-1], ".ref" if REFINE else ""))
    if CACHE and os.path.exists(ck):
        ts, scored, fps, y0, y1, scan = pickle.load(open(ck, "rb"))
    else:
        ts, scored, fps, y0, y1, scan = sprite_frames(vid, band, ncols, dur, anc, floors[0], side=side)
        if CACHE:
            os.makedirs(os.path.dirname(ck), exist_ok=True)
            pickle.dump((ts, scored, fps, y0, y1, scan), open(ck, "wb"))
    # only shared with the other tools when this video's field agrees with what geometry() would
    # have said - on a two-player video it does not, and their thresholds are tuned to its boxes
    cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
    same = R.geometry(cap, vid, band, ncols)[2] == list(scan["xs"])
    cap.release()
    if same:
        R.save_scan(vid, band, ncols, 0.5, dur, scan)

    # Which correlation to believe is settled by a SECOND, unrelated sensor: the receptor
    # flashes, judged events read at the top of the screen by completely different means. A
    # floor is good when the two agree in both directions. Neither sensor sees the stepfile.
    # A floor also stops it collapsing to a handful of perfect notes: every judged event
    # flashed, so an extraction finding far fewer notes than there were flashes has thrown real
    # ones away however tidy the rest looks.
    # The flashes cover the WHOLE song, not a 45-second probe: they come off the same frames the
    # sprites did, so there is nothing to save by looking at less. A chart whose art changes
    # halfway through was picking a correlation for its first half.
    fl, _ = R.onsets(scan, 60.0)
    flashes = {c: sorted(v) for c, v in fl.items()}
    n_flash = sum(len(v) for v in flashes.values())
    gate = colour_floor(scored, floors[0])
    cands = []
    for sat in (0.0, gate):
        for floor in floors:
            cand = _clean(_cand(ts, at_floor(scored, floor, sat), ncols, y0, y1, fps))
            if len(cand) < 15:
                continue
            enough = len(cand) >= 0.6 * n_flash if n_flash else True
            cands.append((flash_agreement(cand, flashes, 0.0) * (1.0 if enough else 0.15), floor, sat, cand))
        if gate <= 0.0:
            break
    # Among the floors the flashes cannot tell apart, the STRICTEST. A lower floor only ever adds
    # detections, so when those do not make the extraction agree measurably better with the
    # second sensor, they are not evidence of notes. Through the inset lanes Bee S17 scored 0.514
    # at 0.36 and 0.512 at 0.44, 0.52 and 0.60 - and 0.36 was the one carrying 13 false notes,
    # 100/97.3 where the other three are 100/100. Replayed over the fifteen published charts,
    # taking the highest floor within TIE of the best score lifts mean F1 from 94.98 to 95.07 and
    # puts Bee back at 100/100; a margin of 0.01 does no better on average and costs The End of
    # the World its precision (98.6/96.1 against 98.6/98.6).
    best = None
    if cands:
        top = max(c[0] for c in cands)
        best = max((c for c in cands if c[0] >= top - TIE), key=lambda c: (c[1], -c[2]))
    if best is None:
        best = (0.0, floors[1], 0.0, _clean(_cand(ts, at_floor(scored, floors[1]), ncols, y0, y1, fps)))
    sc, floor, sat, notes = best
    if not quiet:
        speeds = [-n["v"] for n in notes]
        print("%s band %s/%s, %d frames at %.0ffps, sharpness %.0f, correlation %.2f%s (flash F1 %.2f)"
              % (vid, band, side, len(ts), fps, sharp, floor,
                 (", colour %.3f" % sat) if sat > 0 else "", sc))
        if speeds:
            print("  scroll %.0f px/s (%.0f-%.0f)" % (np.median(speeds), np.percentile(speeds, 5),
                                                     np.percentile(speeds, 95)))
        print("  extracted %d note events" % len(notes))
    n_hold = mark_holds(scan, notes)
    if not quiet:
        print("  %d of them hold" % n_hold)
    # the receptor flashes ride along: they are the second sensor, and a caller deciding whether
    # to believe a note the file lacks can ask whether the game lit the receptor for it
    return notes, dict(vid=vid, band=band, fps=fps, floor=floor, colour=sat, holds=n_hold,
                       y_judge=(y0 + y1) / 2 - (y1 + TOP),
                       flashes={c: [float(t) for t in v] for c, v in flashes.items()})

def main():
    notes, meta = extract(sys.argv[1], quiet="--quiet" in sys.argv)
    if "--dump" in sys.argv:
        json.dump(notes, open(sys.argv[sys.argv.index("--dump") + 1], "w"), indent=0)

if __name__ == "__main__":
    main()
