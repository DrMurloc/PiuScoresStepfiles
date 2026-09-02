# Prototype: read judged events per column from the RECEPTOR FLASH. When a note is judged the
# receptor at the top of its column bursts white for a few frames; a hold keeps it lit. That is
# a per-column, per-frame signal the combo counter cannot give (the counter only says HOW MANY).
#
#   python tools/receptor_reader.py <vid> <t0> <t1> [key] [offset]
# Prints the receptor geometry it found, the onsets per column, and - with a key - how they
# line up against the file's tap rows at the given offset (video = chart + offset).
import bisect
import json
import csv
import os
import sys

import cv2
import numpy as np

CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def geometry(cap, vid, n=64):
    """Receptor row + 10 column centres, fitted ONCE per video over its whole length and cached.
    The receptors are the only thing in the band that never moves, so the per-pixel temporal
    median of the band keeps them and washes out notes and BGA. Ten evenly spaced teeth are
    fitted to the median's column profile; a tooth only scores when it sits on a local maximum,
    which is what stops a BGA-heavy stretch from selling a 53px comb on bright edges."""
    cache = os.path.join("work", "receptor", vid + ".geometry.json")
    if os.path.exists(cache):
        g = json.load(open(cache)); return g["y0"], g["y1"], g["xs"], None
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    frames = []
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_MSEC, (dur * (k + 0.5) / n) * 1000)
        ok, fr = cap.read()
        if ok: frames.append(fr)
    h, w = frames[0].shape[:2]
    y0, y1 = int(h * 0.07), int(h * 0.21)
    med = np.median(np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)[y0:y1, :] for f in frames]), axis=0)
    # Each receptor carries several bright ridges, so any comb fit can lock onto a harmonic.
    # What is unambiguous is the field's EXTENT: the outermost strong peaks of the profile are
    # the outer borders of the first and last receptor, and ncols equal receptors fill the
    # span between them, so the pitch is that span over ncols.
    ncols = int(os.environ.get("RR_COLS", "10"))
    prof = cv2.GaussianBlur(med.astype(np.float32), (0, 0), 3).mean(axis=0)
    prof = cv2.GaussianBlur(prof.reshape(1, -1), (0, 0), 3).ravel()
    prof = prof - np.percentile(prof, 30)
    peaks = [x for x in range(8, w - 8) if prof[x] == prof[x - 8:x + 9].max() and prof[x] > 0.6 * prof.max()]
    lo, hi = min(peaks), max(peaks)
    p = (hi - lo) / ncols
    xs = [int(round(lo + (k + 0.5) * p)) for k in range(ncols)]
    p = int(round(p)); onmax = len(peaks)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(dict(y0=y0, y1=y1, xs=xs, pitch=p, teeth_on_maxima=onmax), open(cache, "w"))
    return y0, y1, xs, med

def main():
    vid, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    key = sys.argv[4] if len(sys.argv) > 4 else None
    a = float(sys.argv[5]) if len(sys.argv) > 5 else None
    cap = cv2.VideoCapture(os.path.join("videos", vid + ".mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS)
    y0, y1, xs, med = geometry(cap, vid)
    print(f"fps {fps:.0f}; receptor band y {y0}-{y1}; columns x {xs}" + (f" pitch {np.mean(np.diff(xs)):.1f}" if xs else ""))
    if len(xs) != 10:
        print("did not find 10 evenly spaced receptors - stop"); return
    half = int(np.median(np.diff(xs)) * 0.28)
    cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
    series = []
    t = t0
    while t < t1:
        ok, fr = cap.read()
        if not ok: break
        # a judgement flash is WHITE; note sprites are coloured, so the min channel separates them
        white = fr.min(axis=2)
        # a hold's rail is a coloured bar filling the lane under the receptor; a tap sprite only
        # passes through it for a few frames. Saturation picks the bar out of a dimmed BGA.
        hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
        bar = (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 170)      # saturated AND bright: a rail, not a dark BGA
        lane = [float(bar[y1 + 8:y1 + 88, x - 14:x + 14].mean()) for x in xs]
        series.append((t, [float(white[y0:y1, x - half:x + half].mean()) for x in xs], lane))
        t += 1.0 / fps
    arr = np.array([s[1] for s in series]); ts = np.array([s[0] for s in series]); lane = np.array([s[2] for s in series])
    onsets = {c: [] for c in range(10)}
    heights = []
    thresh = float(os.environ.get("RR_THRESH", "40"))
    for c in range(10):
        v = arr[:, c]
        base = np.array([np.percentile(v[max(0, i - 30):i + 1], 30) for i in range(len(v))])
        rise = v - base
        # every local maximum's height, to see the two populations: the beat pulse and the hit flash
        for i in range(1, len(v) - 1):
            if rise[i] >= rise[i - 1] and rise[i] > rise[i + 1] and rise[i] > 5: heights.append(rise[i])
        # onsets are PEAKS of the rise, not threshold crossings: in a drill the flashes overlap
        # and the glow never drops, but every hit re-peaks; 70ms apart at least (debounce)
        last = -1.0
        for i in range(4, len(v) - 4):
            # a prominent maximum: the top of its own +/-4-frame neighbourhood (a flash's noisy
            # decay has several small maxima; a 16th-note drill at 60fps still re-peaks 6+ frames apart)
            if rise[i] > thresh and rise[i] == rise[i - 4:i + 5].max() and ts[i] - last >= 0.07:
                onsets[c].append(float(ts[i])); last = float(ts[i])
    # a hold = the lane under the receptor stays occupied by a saturated bar for 0.3s or more
    occ_th = float(os.environ.get("RR_OCC", "0.45"))
    holds_v = {c: [] for c in range(10)}
    for c in range(10):
        on = lane[:, c] > occ_th
        i = 0
        while i < len(on):
            if on[i]:
                j = i
                while j + 1 < len(on) and (on[j + 1] or on[j + 2:j + 5].any()): j += 1
                if ts[j] - ts[i] >= 0.30: holds_v[c].append((float(ts[i]), float(ts[j])))
                i = j + 1
            else: i += 1
    hs = np.array(heights)
    print("peak heights over the rolling floor - percentiles 50/75/90/95/99/max:",
          " ".join(f"{np.percentile(hs, q):.0f}" for q in (50, 75, 90, 95, 99, 100)), f"| threshold {thresh:.0f}")
    print("onsets per column:", [len(onsets[c]) for c in range(10)], "total", sum(len(o) for o in onsets.values()))
    if not key: 
        for c in range(10): print(f"  col {c}: " + " ".join(f"{t:.2f}" for t in onsets[c][:25]))
        return
    rows = list(csv.DictReader(open(os.path.join(CS_DIR, key + ".csv"), encoding="utf-8")))
    taps = {c: [] for c in range(10)}
    for r in rows:
        L = r["Line"].lstrip("`")
        for c, ch in enumerate(L[:10]):
            if ch in "12": taps[c].append(float(r["Time"]))
    def score(a):
        hit = 0
        for c in range(10):
            for t in onsets[c]:
                ct = t - a
                i = bisect.bisect_left(taps[c], ct - 0.06)
                if i < len(taps[c]) and abs(taps[c][i] - ct) <= 0.06: hit += 1
        return hit
    if a is None:
        best = max(((score(x / 100), x / 100) for x in range(0, 6000)), key=lambda p: p[0])
        print(f"best offset {best[1]:.2f} matches {best[0]} of {sum(len(o) for o in onsets.values())} onsets")
        a = best[1]
    tot = sum(len(o) for o in onsets.values())
    print(f"at offset {a:.2f}: {score(a)} of {tot} onsets sit on a file tap/hold-head (+/-60ms)")
    tol = 0.09
    print("hold candidates (video t, chart t at offset):")
    for c in range(10):
        if holds_v[c]: print(f"  col {c}: " + "  ".join(f"{s:.2f}-{e:.2f} (chart {s-a:.2f}-{e-a:.2f}, {e-s:.2f}s)" for s, e in holds_v[c]))
    for c in range(10):
        ft = [t for t in taps[c] if t0 - a <= t <= t1 - a]
        unmatched_file = [t for t in ft if not any(abs(o - a - t) <= tol for o in onsets[c])]
        unmatched_video = [o for o in onsets[c] if not any(abs(o - a - t) <= tol for t in ft)]
        print(f"  col {c}: file {len(ft):3d} video {len(onsets[c]):3d} | file-only {' '.join(f'{t:.2f}' for t in unmatched_file[:8])} | video-only {' '.join(f'{o-a:.2f}' for o in unmatched_video[:8])}")

if __name__ == "__main__":
    main()
