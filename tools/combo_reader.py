# Reads the in-game combo counter through a chart video, producing the judged-event
# curve that drives tick repair: combo increments on every PERFECT/GREAT — including
# each hold tick — so within a clean combo run, cumulative combo vs time IS the
# judgment schedule. The display pulses on each increment, so glyphs are segmented
# by connected component and normalized to a fixed height before template matching.
#
#   --bootstrap <videoId> <t=value> [...]   harvest digit templates from frames with
#                                           known combo values (e.g. 96.0=545)
#   --scan <videoId> [--side C|L|R] [--from T] [--to T]
#                                           read every frame; write work/combo/<id>.jsonl
#
# Region: the combo digits sit in a fixed band below the judgment text — X depends on
# where the chart renders (C = doubles/full-width center, L/R = singles by side).
import glob
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATLAS = os.path.join(ROOT, "tools", "atlas-combo")
GLYPH_H = 32          # normalized glyph height
Y_BAND = (370, 450)   # digit row band at 720p (below the pulsing COMBO label)
X_BAND = {"C": (470, 810), "L": (150, 490), "R": (790, 1130)}
DIGIT_W = 51          # single glyph width at rest scale; wider components get split

def video_path(vid):
    hits = [p for p in glob.glob(os.path.join(ROOT, "videos", vid + ".*"))
            if not p.endswith((".part", ".ytdl", ".txt"))]
    return hits[0] if hits else None

def digit_boxes(frame, side):
    x0, x1 = X_BAND[side]
    band = frame[Y_BAND[0]:Y_BAND[1], x0:x1]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] > 170) & (hsv[:, :, 1] < 65)).astype(np.uint8) * 255
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 26 <= h <= 78 and 10 <= w <= 170 and area >= 140:
            boxes.append((x, y, w, h))
    if not boxes:
        return mask, []
    # dominant row by y-center, then height consistency (kills label/ribbon fragments)
    med = float(np.median([y + h / 2 for x, y, w, h in boxes]))
    row = [b for b in boxes if abs(b[1] + b[3] / 2 - med) < 26]
    hmed = float(np.median([h for _, _, _, h in row]))
    row = [b for b in row if abs(b[3] - hmed) <= hmed * 0.45]
    row.sort()
    # split merged multi-digit components (per-box scale from its own height)
    final = []
    for x, y, w, h in row:
        scale = h / 42.0
        if w <= DIGIT_W * 1.25 * scale:
            final.append((x, y, w, h))
            continue
        k = max(2, int(round(w / (DIGIT_W * scale))))
        prof = mask[y:y + h, x:x + w].sum(axis=0)
        cuts = [0]
        for j in range(1, k):
            c0 = int(w * j / k)
            lo, hi = max(1, c0 - 12), min(w - 1, c0 + 12)
            cuts.append(lo + int(np.argmin(prof[lo:hi])))
        cuts.append(w)
        for a, b in zip(cuts, cuts[1:]):
            if b - a >= 8:
                final.append((x + a, y, b - a, h))
    # digits form one tight run; drop isolated fragments (gap > ~60% of a digit width)
    if len(final) > 1:
        runs, cur = [], [final[0]]
        for prev, nxt in zip(final, final[1:]):
            gap = nxt[0] - (prev[0] + prev[2])
            if gap > 0.6 * DIGIT_W * (prev[3] / 42.0):
                runs.append(cur); cur = []
            cur.append(nxt)
        runs.append(cur)
        final = max(runs, key=lambda r: sum(b[2] for b in r))
    return mask, final

def norm_glyph(mask, box):
    x, y, w, h = box
    g = mask[y:y + h, x:x + w]
    scale = GLYPH_H / h
    return cv2.resize(g, (max(6, int(round(w * scale))), GLYPH_H))

def load_atlas():
    out = {}
    for p in glob.glob(os.path.join(ATLAS, "d*.png")):
        d = os.path.basename(p)[1]
        out.setdefault(d, []).append(cv2.imread(p, cv2.IMREAD_GRAYSCALE))
    return out

def classify(glyph, atlas):
    best, best_d = -1.0, None
    for d, tpls in atlas.items():
        for tpl in tpls:
            a, b = glyph, tpl
            if a.shape[1] < b.shape[1]:
                a, b = b, a
            score = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED).max())
            if score > best:
                best, best_d = score, d
    return (best_d, best) if best >= 0.5 else (None, best)

def read_frame(frame, side, atlas):
    mask, row = digit_boxes(frame, side)
    if not row:
        return None, 1.0
    val, worst = "", 1.0
    for b in row:
        d, conf = classify(norm_glyph(mask, b), atlas)
        worst = min(worst, conf)
        if d is None:
            return None, worst
        val += d
    return (int(val) if val else None), worst

def bootstrap(vid, pairs):
    os.makedirs(ATLAS, exist_ok=True)
    cap = cv2.VideoCapture(video_path(vid))
    counts = {}
    for t, truth, side in pairs:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        mask, row = digit_boxes(frame, side)
        print(f"t={t}: {len(row)} boxes for truth {truth} ({[b[2:] for b in row]})")
        if len(row) != len(truth):
            continue
        for ch, b in zip(truth, row):
            counts[ch] = counts.get(ch, 0) + 1
            cv2.imwrite(os.path.join(ATLAS, f"d{ch}_{counts[ch]}.png"), norm_glyph(mask, b))
    print("atlas now:", sorted({os.path.basename(p)[1] for p in glob.glob(os.path.join(ATLAS, 'd*.png'))}))

def scan(vid, side, t0, t1):
    atlas = load_atlas()
    cap = cv2.VideoCapture(video_path(vid))
    fps = cap.get(cv2.CAP_PROP_FPS)
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    t1 = min(t1, dur)
    cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
    os.makedirs(os.path.join(ROOT, "work", "combo"), exist_ok=True)
    out_path = os.path.join(ROOT, "work", "combo", f"{vid}.jsonl")
    n_read = n_none = 0
    unk = 0
    with open(out_path, "w", encoding="utf-8") as out:
        t = t0
        while t < t1:
            ok, frame = cap.read()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            val, conf = read_frame(frame, side, atlas)
            if val is None and conf > -1 and conf < 0.5 and unk < 40:
                mask, row = digit_boxes(frame, side)
                for i, b in enumerate(row):
                    d, c = classify(norm_glyph(mask, b), load_atlas())
                    if d is None:
                        os.makedirs(os.path.join(ROOT, "work", "combo-unknown"), exist_ok=True)
                        cv2.imwrite(os.path.join(ROOT, "work", "combo-unknown",
                                                 f"{vid}_{t:.2f}_{i}.png"), norm_glyph(mask, b))
                        unk += 1
            out.write(json.dumps([round(t, 4), val, round(conf, 3)]) + "\n")
            n_read += val is not None
            n_none += val is None
    print(f"{out_path}: {n_read} read, {n_none} none, {unk} unknown glyph dumps")

if __name__ == "__main__":
    if sys.argv[1] == "--bootstrap":
        vid = sys.argv[2]
        pairs = []
        side = "C"
        for a in sys.argv[3:]:
            if a.startswith("side="):
                side = a[5:]
            else:
                t, v = a.split("=")
                pairs.append((float(t), v, side))
        bootstrap(vid, pairs)
    elif sys.argv[1] == "--scan":
        vid = sys.argv[2]
        side = "C"
        t0, t1 = 0.0, 1e9
        for a in sys.argv[3:]:
            if a.startswith("side="): side = a[5:]
            if a.startswith("from="): t0 = float(a[5:])
            if a.startswith("to="): t1 = float(a[3:])
        scan(vid, side, t0, t1)
