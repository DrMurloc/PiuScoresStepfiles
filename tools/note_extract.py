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

def column_masks(vid, band, ncols, t_end):
    """For every frame and column, the lit runs under the receptors: (top, bottom) in px."""
    cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
    y0, y1, xs = R.geometry(cap, vid, band, ncols)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60
    half = int(np.median(np.diff(xs)) * 0.34)
    cap.set(cv2.CAP_PROP_POS_MSEC, 0)
    frames, ts, t = [], [], 0.0
    while t < t_end:
        ok, f = cap.read()
        if not ok:
            break
        strip = f[y1 + TOP:y1 + BOTTOM]
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        lit = (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 120)
        per_col = []
        for x in xs:
            col = lit[:, max(0, int(x) - half):int(x) + half]
            prof = col.mean(axis=1) > 0.5          # this row of this column is covered
            runs, s = [], None
            for i, v in enumerate(prof):
                if v and s is None:
                    s = i
                elif not v and s is not None:
                    if i - s >= MIN_RUN:
                        runs.append((s, i))
                    s = None
            if s is not None and len(prof) - s >= MIN_RUN:
                runs.append((s, len(prof)))
            per_col.append(runs)
        frames.append(per_col); ts.append(t)
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
    ts, frames, fps, y0, y1 = column_masks(vid, band, ncols, float(e.get("t") or 150))
    # the judgement line is the middle of the receptor band, in the strip's own coordinates
    y_judge = (y0 + y1) / 2 - (y1 + TOP)
    notes, speeds = [], []
    for c in range(ncols):
        for n in notes_from_tracks(track(ts, frames, c, fps), y_judge, fps):
            n["col"] = c
            notes.append(n)
            speeds.append(-n["v"])
    notes.sort(key=lambda n: (n["t"], n["col"]))
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
