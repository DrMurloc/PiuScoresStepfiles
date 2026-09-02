# Read judged events and hold rails per column from the RECEPTORS. A judgement flashes its
# column's receptor white (far brighter than the receptors' beat pulse); a hold draws a rail -
# a saturated AND bright bar - down the lane beneath its receptor. The combo counter says how
# many; this says which column and when. This is the library; receptor_reader.py is the
# window survey CLI and extract_holds.py the per-chart driver.
import bisect
import csv
import json
import os

import cv2
import numpy as np

CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def geometry(cap, vid, band="C", ncols=None, n=64):
    """Receptor band + column centres, fitted once per video and cached. The receptors are the
    only static thing in the band, so the temporal median keeps them and washes out notes and
    BGA. Centres come from the field's EXTENT - the outermost strong profile peaks are the outer
    borders of the first and last receptor and ncols equal receptors fill the span - because
    every comb fit tried locked onto a harmonic of the receptors' inner ridges."""
    ncols = ncols or (5 if band in "LR" else 10)
    cache = os.path.join("work", "receptor", f"{vid}.{band}.geometry.json")
    if os.path.exists(cache):
        g = json.load(open(cache))
        return g["y0"], g["y1"], g["xs"]
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    frames = []
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_MSEC, (dur * (k + 0.5) / n) * 1000)
        ok, fr = cap.read()
        if ok:
            frames.append(fr)
    h, w = frames[0].shape[:2]
    y0, y1 = int(h * 0.07), int(h * 0.21)
    med = np.median(np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)[y0:y1, :] for f in frames]), axis=0)
    prof = cv2.GaussianBlur(med.astype(np.float32), (0, 0), 3).mean(axis=0)
    prof = cv2.GaussianBlur(prof.reshape(1, -1), (0, 0), 3).ravel()
    prof = prof - np.percentile(prof, 30)
    lo_x, hi_x = (0, w // 2) if band == "L" else (w // 2, w) if band == "R" else (0, w)
    top = prof[lo_x:hi_x].max()
    peaks = [x for x in range(max(8, lo_x), min(w - 8, hi_x))
             if prof[x] == prof[x - 8:x + 9].max() and prof[x] > 0.6 * top]
    lo, hi = min(peaks), max(peaks)
    p = (hi - lo) / ncols
    xs = [int(round(lo + (k + 0.5) * p)) for k in range(ncols)]
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(dict(y0=y0, y1=y1, xs=xs, pitch=round(p, 1), band=band), open(cache, "w"))
    return y0, y1, xs

def scan(vid, t0, t1, band="C", ncols=None):
    """Per frame: the white level in each receptor box (flash) and the fraction of saturated
    bright pixels in the lane beneath it (rail)."""
    cap = cv2.VideoCapture(os.path.join("videos", vid + ".mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS)
    y0, y1, xs = geometry(cap, vid, band, ncols)
    half = int(np.median(np.diff(xs)) * 0.28)
    cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
    ts, flash, lane = [], [], []
    t = t0
    while t < t1:
        ok, fr = cap.read()
        if not ok:
            break
        white = fr.min(axis=2)
        hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
        # a rail is saturated and bright; the value floor sits low enough for the blue rails
        # (dark by nature) and still above the dimmed BGA, whose saturated blues sit under 70
        bar = (hsv[:, :, 1] > 130) & (hsv[:, :, 2] > 120)
        ts.append(t)
        flash.append([float(white[y0:y1, x - half:x + half].mean()) for x in xs])
        # a rail is ~50px wide and can sit 15px off the receptor centre: a 40px box still
        # overlaps it by more than half
        lane.append([float(bar[y1 + 8:y1 + 88, x - 20:x + 20].mean()) for x in xs])
        t += 1.0 / fps
    return dict(ts=np.array(ts), flash=np.array(flash), lane=np.array(lane), xs=xs, fps=fps, y0=y0, y1=y1)

def onsets(sc, thresh=40.0):
    """Prominent peaks of each column's white level over its rolling floor: one per judgement,
    70ms apart at least (a 16th-note drill at 60fps still re-peaks 6+ frames apart)."""
    ts, arr = sc["ts"], sc["flash"]
    out, heights = {}, []
    for c in range(arr.shape[1]):
        v = arr[:, c]
        base = np.array([np.percentile(v[max(0, i - 30):i + 1], 30) for i in range(len(v))])
        rise = v - base
        for i in range(1, len(v) - 1):
            if rise[i] >= rise[i - 1] and rise[i] > rise[i + 1] and rise[i] > 5:
                heights.append(rise[i])
        out[c], last = [], -1.0
        for i in range(4, len(v) - 4):
            if rise[i] > thresh and rise[i] == rise[i - 4:i + 5].max() and ts[i] - last >= 0.07:
                out[c].append(float(ts[i]))
                last = float(ts[i])
    return out, np.array(heights)

def rails(sc, occ_th=0.40, min_len=0.30):
    """Stretches where the lane under a receptor stays occupied by a saturated bright bar."""
    ts, lane = sc["ts"], sc["lane"]
    out = {}
    for c in range(lane.shape[1]):
        on = lane[:, c] > occ_th
        out[c], i = [], 0
        while i < len(on):
            if on[i]:
                j = i
                while j + 1 < len(on) and (on[j + 1] or on[j + 2:j + 5].any()):
                    j += 1
                if ts[j] - ts[i] >= min_len:
                    out[c].append((float(ts[i]), float(ts[j])))
                i = j + 1
            else:
                i += 1
    return out

def chartstruct(key, ncols):
    """Rows, taps-by-column (tap or hold head), and a beat_at(chart_time) interpolator."""
    rows = list(csv.DictReader(open(os.path.join(CS_DIR, key + ".csv"), encoding="utf-8")))
    taps = {c: [] for c in range(ncols)}
    for r in rows:
        L = r["Line"].lstrip("`")
        for c, ch in enumerate(L[:ncols]):
            if ch in "12":
                taps[c].append(float(r["Time"]))
    times = [float(r["Time"]) for r in rows]
    beats = [float(r["Beat"]) for r in rows]
    def beat_at(ct):
        i = bisect.bisect_left(times, ct)
        if i <= 0:
            bps = (beats[1] - beats[0]) / max(times[1] - times[0], 1e-6) if len(times) > 1 else 2.0
            return beats[0] + (ct - times[0]) * bps
        if i >= len(times):
            bps = (beats[-1] - beats[-2]) / max(times[-1] - times[-2], 1e-6) if len(times) > 1 else 2.0
            return beats[-1] + (ct - times[-1]) * bps
        t0, t1, b0, b1 = times[i - 1], times[i], beats[i - 1], beats[i]
        return b0 if t1 == t0 else b0 + (b1 - b0) * (ct - t0) / (t1 - t0)
    return rows, taps, beat_at

def match_offset(ons, taps, tol=0.06, lo=0.0, hi=60.0):
    """The offset (video = chart + a) under which the most onsets sit on a file tap."""
    def score(a):
        hit = 0
        for c, ts_ in ons.items():
            col = taps.get(c, [])
            for t in ts_:
                i = bisect.bisect_left(col, t - a - tol)
                if i < len(col) and abs(col[i] - (t - a)) <= tol:
                    hit += 1
        return hit
    total = sum(len(v) for v in ons.values())
    best = max(((score(x / 100), x / 100) for x in range(int(lo * 100), int(hi * 100))), key=lambda p: p[0])
    return best[1], best[0], total

def snap_beat(b):
    """Nearest point on the 16th grid, or the 12th grid when that is clearly closer."""
    s16 = round(b * 16) / 16
    s12 = round(b * 12) / 12
    return s12 if abs(s12 - b) < abs(s16 - b) - 0.01 else s16
