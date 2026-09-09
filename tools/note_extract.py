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
# The arrow test is saturation AND brightness, never hue: the dimmed BGA is neither, and a chart
# that recolours its notes reads the same as any other.
#
#   python -X utf8 tools/note_extract.py "<chart>" [--dump <file.json>] [--quiet]
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_map      # noqa: E402
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP, BOTTOM = 20, 430     # the band under the receptors that is watched, in px below the band
MIN_RUN = 14              # a run of lit pixels shorter than this is not an arrow
MIN_TRACK = 3             # frames a streak must persist to be believed

def arrow_blobs(vid, band, ncols, t_end):
    """Every frame, the arrows on screen: which column, and where vertically.

    Colour alone cannot find an arrow. A bright BGA - and plenty of them are bright - passes any
    saturation test across whole regions of the screen, which is what drowned the first attempt.
    What separates an arrow from the art behind it is SHAPE: it is a compact blob about one lane
    wide and as tall as it is wide, with a light outline, and it is the same size every time.
    Connected components with a size and fill filter say that directly; a row profile cannot.
    """
    cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
    y0, y1, xs = R.geometry(cap, vid, band, ncols)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60
    pitch = float(np.median(np.diff(xs)))
    lo, hi = pitch * 0.55, pitch * 1.25          # an arrow is about one lane across
    cap.set(cv2.CAP_PROP_POS_MSEC, 0)
    frames, ts, t = [], [], 0.0
    while t < t_end:
        ok, f = cap.read()
        if not ok:
            break
        strip = f[y1 + TOP:y1 + BOTTOM]
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        # the arrow body is coloured, its outline is near-white; either way it is BRIGHT, and
        # taking both keeps the sprite whole so its outline does not cut it into pieces
        lit = ((hsv[:, :, 2] > 110) & ((hsv[:, :, 1] > 80) | (hsv[:, :, 2] > 190))).astype(np.uint8)
        lit = cv2.morphologyEx(lit, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, lab, st, cent = cv2.connectedComponentsWithStats(lit, 8)
        per_col = [[] for _ in range(ncols)]
        for k in range(1, n):
            x, y, w, h, area = st[k]
            if not (lo <= w <= hi and lo * 0.6 <= h <= hi):
                continue
            if area < 0.35 * w * h:              # an arrow fills its box; a wisp of BGA does not
                continue
            c = int(np.argmin([abs(cent[k][0] - v) for v in xs]))
            if abs(cent[k][0] - xs[c]) > pitch * 0.5:
                continue
            per_col[c].append((int(y), int(y + h)))
        frames.append([sorted(v) for v in per_col]); ts.append(t)
        t += 1.0 / fps
    cap.release()
    return np.array(ts), frames, fps, y0, y1

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

def extract(name, quiet=False):
    smap, cert = corpus_map.chart_map(), corpus_map.certification()
    ncols = 10 if name.split()[-1][0] == "D" else 5
    vid, e = next((v, e) for v, e in cert.items() if name in (e.get("charts") or {}))
    side = e["charts"][name].get("side") or "1p"
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    ts, frames, fps, y0, y1 = arrow_blobs(vid, band, ncols, float(e.get("t") or 150))
    # the judgement line is the middle of the receptor band, in the strip's own coordinates
    y_judge = (y0 + y1) / 2 - (y1 + TOP)
    notes, speeds = [], []
    for c in range(ncols):
        for n in notes_from_tracks(track(ts, frames, c, fps), y_judge, fps):
            n["col"] = c
            notes.append(n)
            speeds.append(-n["v"])
    notes.sort(key=lambda n: (n["t"], n["col"]))
    # One note can be tracked, lost behind an effect and re-acquired, arriving as two streaks
    # that extrapolate to the same instant. Nothing in this game puts two notes in ONE column
    # closer than a 16th at 300bpm (50ms), so anything nearer than that is one note counted
    # twice. The longer-lived streak is the one kept - it saw more of the arrow.
    merged = {}
    for n in notes:
        k = n["col"]
        prev = merged.get(k)
        if prev and abs(n["t"] - prev[-1]["t"]) < 0.035:
            if n["frames"] > prev[-1]["frames"]:
                prev[-1] = n
            continue
        merged.setdefault(k, []).append(n)
    notes = sorted((n for v in merged.values() for n in v), key=lambda n: (n["t"], n["col"]))
    # Every real note falls at the scroll speed; the background does not. A streak moving at a
    # different rate is something in the art that happened to be arrow-shaped. The comparison is
    # LOCAL - the median of the streaks around it - so a chart that changes tempo is judged
    # against its own speed at that moment rather than the song's average.
    if len(notes) > 30:
        sp = np.array([-n["v"] for n in notes])
        keep = []
        for i, n in enumerate(notes):
            med = float(np.median(sp[max(0, i - 25):i + 25]))
            if med > 0 and abs(-n["v"] - med) <= 0.40 * med:
                keep.append(n)
        notes = keep
    if not quiet:
        print(f"{name}: {vid} band {band}, {len(ts)} frames at {fps:.0f}fps")
        if speeds:
            print(f"  scroll {np.median(speeds):.0f} px/s "
                  f"({np.percentile(speeds, 5):.0f}-{np.percentile(speeds, 95):.0f})")
        print(f"  extracted {len(notes)} note events")
    return notes, dict(vid=vid, band=band, fps=fps, y_judge=y_judge)

def main():
    notes, meta = extract(sys.argv[1], quiet="--quiet" in sys.argv)
    if "--dump" in sys.argv:
        json.dump(notes, open(sys.argv[sys.argv.index("--dump") + 1], "w"), indent=0)

if __name__ == "__main__":
    main()
