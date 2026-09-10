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
FLOORS = (0.36, 0.44, 0.52, 0.60)
SCALE = 0.5               # sprite matching runs at half resolution

def sprite_frames(vid, band, ncols, t_end, tmpl, floor=0.30, t0=0.0, scale=SCALE,
                  collect=None, collect_floor=0.60):
    """Every frame, where each column's sprite correlates. Same shape as arrow_blobs' output,
    but each hit carries its correlation so one decode can be re-cut at several thresholds.

    Correlating at half resolution costs eight times less and loses nothing that matters: the
    peak lands within a pixel or two of where it would, which is a few milliseconds of scroll,
    and the crossing time is a line fitted through forty of them anyway."""
    cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
    y0, y1, xs = R.geometry(cap, vid, band, ncols)
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
        t = pos if (i == 0 and pos >= 0) or pos > ts[-1] + 1e-6 else count
        ok, f = cap.read()
        if not ok:
            break
        i += 1
        # the receptors and the lane under them come off the SAME decoded frame - reading the
        # judged events and the hold rails used to cost a second pass over the whole video
        white = f[y0:y1].min(axis=2)
        bar = cv2.cvtColor(f[y1 + 8:y1 + 88], cv2.COLOR_BGR2HSV)
        bar = (bar[:, :, 1] > 130) & (bar[:, :, 2] > 120)
        flash.append([float(white[:, x - half:x + half].mean()) for x in xs])
        lane.append([float(bar[:, x - 20:x + 20].mean()) for x in xs])
        strip = f[y1 + TOP:y1 + BOTTOM]
        full = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(full, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA) if sc != 1.0 else full
        pk = []
        for c, col in enumerate(sprites.peaks(gray, sxs, by_col, stw, sth, floor)):
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

def anchor_set(vid, band, ncols):
    """The five receptor sprites for this video, plus the box they are read at."""
    path = os.path.join(ROOT, "videos", vid + ".mp4")
    cap = cv2.VideoCapture(path)
    y0, y1, xs = R.geometry(cap, vid, band, ncols)
    cap.release()
    tw, th = sprites.size_for(float(np.median(np.diff(xs))))
    return sprites.anchors(path, vid, band, y0, y1, xs, th, tw), th, tw

def harvest(vid, band, ncols, t0, t1):
    """The five sprites: the receptors, sharpened by the notes a receptor pass was surest of.

    The bootstrap used to run off the blob detector, which meant inheriting its blind spots and
    paying for its tuning. A receptor pass is both better and free of that: it is already the
    detector, so its own confident hits are cleaner samples than the blob detector's best."""
    anc, th, tw = anchor_set(vid, band, ncols)
    bins = [[] for _ in range(5)]
    sprite_frames(vid, band, ncols, t1, anc, FLOORS[0], t0, collect=bins)
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
        out.append(dict(t=float(t_hit), v=float(v), tall=int(tall),
                        frames=len(tr["t"]), first=float(t[0]), last=float(t[-1])))
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
    extrapolate to the same instant. Nothing in this game puts two notes in ONE column closer
    than a 16th at 300bpm, so anything nearer is one note counted twice; the longer-lived streak
    is kept, because it saw more of the arrow.

    Then: every real note falls at the scroll speed and the background does not, so a streak
    moving at a different rate is something in the art that happened to be arrow-shaped. The
    comparison is LOCAL - the median of the streaks around it - so a chart that changes tempo is
    judged against its own speed at that moment rather than the song's average.
    """
    notes = sorted(notes, key=lambda n: (n["t"], n["col"]))
    merged = {}
    for n in notes:
        prev = merged.get(n["col"])
        if prev and abs(n["t"] - prev[-1]["t"]) < 0.035:
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
    rails = R.rails(scan)
    speeds = [-n["v"] for n in notes if n.get("v")]
    lag = 88.0 / float(np.median(speeds)) if speeds else 0.12
    n_hold = 0
    for n in notes:
        for a, b in rails.get(n["col"], []):
            if abs(a - n["t"]) <= tol and b - a >= 0.12:
                n["hold_end"] = b - lag
                n_hold += 1
                break
    return n_hold

def extract(name, quiet=False):
    """Every tap the screen shows, as (video time, column).

    ONE decode of the video. The sprite matcher needs no brightness threshold to tune, so the
    six extra passes the blob detector cost are gone; what is left to choose is how strong a
    correlation to believe, and that is re-cut from the one pass at no further cost.
    """
    cert = corpus_map.certification()
    ncols = 10 if name.split()[-1][0] == "D" else 5
    vid, e = next((v, e) for v, e in cert.items() if name in (e.get("charts") or {}))
    side = e["charts"][name].get("side") or "1p"
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    dur = float(e.get("t") or 150)
    anc, th, tw = anchor_set(vid, band, ncols)
    if not any(A is not None for A in anc):
        raise RuntimeError("no receptor sprites for %s band %s" % (vid, band))
    ts, scored, fps, y0, y1, scan = sprite_frames(vid, band, ncols, dur, anc, FLOORS[0])
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
    gate = colour_floor(scored, FLOORS[0])
    best = None
    for sat in (0.0, gate):
        for floor in FLOORS:
            cand = _clean(_cand(ts, at_floor(scored, floor, sat), ncols, y0, y1, fps))
            if len(cand) < 15:
                continue
            enough = len(cand) >= 0.6 * n_flash if n_flash else True
            sc = flash_agreement(cand, flashes, 0.0) * (1.0 if enough else 0.15)
            if best is None or sc > best[0]:
                best = (sc, floor, sat, cand)
        if gate <= 0.0:
            break
    if best is None:
        best = (0.0, 0.44, 0.0, _clean(_cand(ts, at_floor(scored, 0.44), ncols, y0, y1, fps)))
    sc, floor, sat, notes = best
    if not quiet:
        speeds = [-n["v"] for n in notes]
        print("%s: %s band %s, %d frames at %.0ffps, correlation %.2f%s (flash F1 %.2f)"
              % (name, vid, band, len(ts), fps, floor,
                 (", colour %.3f" % sat) if sat > 0 else "", sc))
        if speeds:
            print("  scroll %.0f px/s (%.0f-%.0f)" % (np.median(speeds), np.percentile(speeds, 5),
                                                     np.percentile(speeds, 95)))
        print("  extracted %d note events" % len(notes))
    n_hold = mark_holds(scan, notes)
    if not quiet:
        print("  %d of them hold" % n_hold)
    return notes, dict(vid=vid, band=band, fps=fps, floor=floor, colour=sat, holds=n_hold,
                       y_judge=(y0 + y1) / 2 - (y1 + TOP))

def main():
    notes, meta = extract(sys.argv[1], quiet="--quiet" in sys.argv)
    if "--dump" in sys.argv:
        json.dump(notes, open(sys.argv[sys.argv.index("--dump") + 1], "w"), indent=0)

if __name__ == "__main__":
    main()
