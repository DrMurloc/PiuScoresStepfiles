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
HALF = {"L": (0, 640), "R": (640, 1280), "C": (0, 1280)}  # label found within the half; digits hang off it
DIGIT_W = 51          # single glyph width at rest scale; wider components get split

def video_path(vid):
    hits = [p for p in glob.glob(os.path.join(ROOT, "videos", vid + ".*"))
            if not p.endswith((".part", ".ytdl", ".txt"))]
    return hits[0] if hits else None

def digit_boxes(frame, x0, x1, y0, y1, cx_local=None):
    """Digit glyphs in the window below the COMBO label. Scrolling notes fuse with
    digit BOTTOMS (inflating component height), so boxes are filtered to those
    top-aligned with the row and cropped to the row's minimum height — the digit
    portion survives, the fused note tail is discarded."""
    band = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] > 170) & (hsv[:, :, 1] < 70)).astype(np.uint8) * 255
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = [(x, y, w, h) for x, y, w, h, a in (s for s in stats[1:])
             if h >= 26 and w >= 8 and a >= 140]
    if cx_local is not None:
        boxes = [b for b in boxes if abs(b[0] + b[2] / 2 - cx_local) <= 118]
    if not boxes:
        return mask, []
    anchored = [b for b in boxes if b[1] >= 2] or boxes
    row_top = min(y for _, y, _, _ in anchored)
    boxes = [b for b in boxes if b[1] <= row_top + 6]
    hmed = float(np.median([h for _, _, _, h in boxes]))
    boxes = [b for b in boxes if b[3] >= 0.7 * hmed]
    h_ref = min(h for _, _, _, h in boxes)
    boxes = [(x, y, w, h_ref) for x, y, w, h in boxes]
    boxes.sort()
    final = []
    scale = h_ref / 42.0
    for x, y, w, h in boxes:
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
        for a2, b2 in zip(cuts, cuts[1:]):
            if b2 - a2 >= 8:
                final.append((x + a2, y, b2 - a2, h))
    if len(final) > 1:
        runs, cur = [], [final[0]]
        for prev, nxt in zip(final, final[1:]):
            gap = nxt[0] - (prev[0] + prev[2])
            if gap > 0.6 * DIGIT_W * scale:
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

LABEL_BAND = (310, 400)

def load_atlas():
    out = {}
    for p in glob.glob(os.path.join(ATLAS, "d*.png")):
        d = os.path.basename(p)[1]
        out.setdefault(d, []).append(cv2.imread(p, cv2.IMREAD_GRAYSCALE))
    labels = [cv2.imread(p, cv2.IMREAD_GRAYSCALE)
              for p in glob.glob(os.path.join(ATLAS, "label_*.png"))]
    return out, labels

def find_label(frame, side, labels):
    """The real counter always carries the COMBO label above its digits; the BGA's
    own numbers (e.g. Tales of Pumpnia's RPG damage popups) don't. The counter's
    x position varies by layout (split halves ~400/880, full-screen singles ~320/960,
    doubles ~640), so the label is searched across the whole requested half and the
    digit window hangs off wherever it is. Returns (center_x, label_top_y) in frame
    coords, or None when the counter is hidden."""
    hx0, hx1 = HALF[side]
    g = cv2.cvtColor(frame[LABEL_BAND[0]:LABEL_BAND[1], hx0:hx1], cv2.COLOR_BGR2GRAY)
    best, where = -1.0, None
    for tpl in labels:
        if g.shape[0] < tpl.shape[0] or g.shape[1] < tpl.shape[1]:
            continue
        res = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx > best:
            best = mx
            where = (hx0 + loc[0] + tpl.shape[1] / 2, LABEL_BAND[0] + loc[1])
    return where if best >= 0.55 else None

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

def read_frame(frame, side, atlas, labels):
    hit = find_label(frame, side, labels)
    if hit is None:
        return None, -1.0  # counter hidden
    cx, ly = hit
    x0 = max(0, int(cx - 185)); x1 = min(frame.shape[1], int(cx + 185))
    y0 = int(ly + 26); y1 = min(frame.shape[0], int(ly + 102))
    mask, row = digit_boxes(frame, x0, x1, y0, y1, cx_local=cx - x0)
    if not row:
        return None, 1.0
    reads = []
    worst = 1.0
    for b in row:
        d, conf = classify(norm_glyph(mask, b), atlas)
        worst = min(worst, conf)
        reads.append((d, b))
    # tolerate an unknown at either edge ONLY when it is a sub-digit-width fragment
    # (clipped note remnant) — a digit-sized unknown voids the read, never truncates it
    scale = row[0][3] / 42.0 if row else 1.0
    frag_w = 0.55 * DIGIT_W * scale
    if reads and reads[0][0] is None and reads[0][1][2] < frag_w:
        reads = reads[1:]
    if reads and reads[-1][0] is None and reads[-1][1][2] < frag_w:
        reads = reads[:-1]
    if not reads or any(d is None for d, _ in reads):
        return None, worst
    return int("".join(d for d, _ in reads)), worst

def bootstrap(vid, pairs):
    os.makedirs(ATLAS, exist_ok=True)
    cap = cv2.VideoCapture(video_path(vid))
    counts = {}
    for t, truth, side in pairs:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        _, labels = load_atlas()
        hit = find_label(frame, side, labels)
        if hit is None:
            print(f"t={t}: NO LABEL"); continue
        cx, ly = hit
        mask, row = digit_boxes(frame, max(0, int(cx - 185)), min(frame.shape[1], int(cx + 185)),
                                int(ly + 24), min(frame.shape[0], int(ly + 100)))
        print(f"t={t}: {len(row)} boxes for truth {truth} ({[b[2:] for b in row]})")
        if len(row) != len(truth):
            continue
        for ch, b in zip(truth, row):
            counts[ch] = counts.get(ch, 0) + 1
            cv2.imwrite(os.path.join(ATLAS, f"d{ch}_{counts[ch]}.png"), norm_glyph(mask, b))
    print("atlas now:", sorted({os.path.basename(p)[1] for p in glob.glob(os.path.join(ATLAS, 'd*.png'))}))

def scan(vid, side, t0, t1):
    atlas, labels = load_atlas()
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
            val, conf = read_frame(frame, side, atlas, labels)
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
