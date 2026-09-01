# Fixed-cell combo reader for captures whose digits the general atlas cannot segment.
#
# Some videos render the counter in a font the atlas does not know, with a hold rail running
# through the digits, so connected-component segmentation fuses or splits them (Imagination
# S18: 4/4/2/2 boxes for 3-digit values). But the counter is ALWAYS three monospace digits at
# a fixed position under the COMBO label - so skip segmentation: cut three fixed cells, and
# classify each against a per-video atlas bootstrapped from a handful of eye-read frames.
#
#   python tools/cell_reader.py --bootstrap <vid> <side> <t>=<digits> ...   (builds the atlas)
#   python tools/cell_reader.py --scan <vid> <side>                          (writes the jsonl)
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import combo_reader as cr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_GEOM = dict(x0=-90, gap=60, w=50, y0=40, h=76)   # Imagination S18 (big 1P font)

def atlas_dir(vid): return os.path.join(ROOT, "tools", "atlas-cell", vid)

def geometry(vid):
    p = os.path.join(atlas_dir(vid), "geometry.json")
    return json.load(open(p)) if os.path.exists(p) else DEFAULT_GEOM

def calibrate(vid, side, times):
    """Try each candidate time until one frame segments cleanly into three digits."""
    for t in times:
        try:
            _calibrate_at(vid, side, t); return
        except (AssertionError, TypeError) as e:
            print(f"  t={t}: {e}")
    raise SystemExit("no clean frame among the candidates")

def _calibrate_at(vid, side, t):
    """Measure the three cells off ONE clean frame (no note over the counter) with the
    general reader's segmentation, and pin them relative to the COMBO label. Every other
    frame is then read at these fixed positions, so an occluding note blanks a cell instead
    of quietly deleting a digit."""
    cap = cv2.VideoCapture(cr.video_path(vid)); _, labels = cr.load_atlas()
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, fr = cap.read()
    hit = cr.find_label(fr, side, labels)
    assert hit is not None, "label not found"
    cx, ly = hit
    wx0 = max(0, int(cx - 185)); wy0 = int(ly + 26)
    _, row = cr.digit_boxes(fr, wx0, min(fr.shape[1], int(cx + 185)), wy0, min(fr.shape[0], int(ly + 102)), cx_local=cx - wx0)
    assert len(row) == 3, f"need a clean 3-digit frame, got {len(row)} boxes"
    xs = [wx0 + b[0] for b in row]; ws = [b[2] for b in row]; ys = [wy0 + b[1] for b in row]; hs = [b[3] for b in row]
    gap = int(round((xs[2] - xs[0]) / 2))
    # a cell must not reach into its neighbour: width from the MEDIAN box (a fused box inflates max), clamped under the gap
    g = dict(x0=int(round(xs[0] - cx - 2)), gap=gap, w=int(min(sorted(ws)[1] + 4, gap - 2)), y0=int(round(min(ys) - ly - 2)), h=int(max(hs) + 4))
    os.makedirs(atlas_dir(vid), exist_ok=True)
    json.dump(g, open(os.path.join(atlas_dir(vid), "geometry.json"), "w"))
    print(f"geometry for {vid}: {g}")

def cells(frame, cx, ly, g=DEFAULT_GEOM):
    out = []
    for i in range(3):
        x0 = int(cx + g["x0"] + i * g["gap"]); y0 = int(ly + g["y0"])
        band = frame[y0:y0 + g["h"], x0:x0 + g["w"]]
        if band.size == 0 or band.shape[0] < g["h"] // 2: return None
        hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
        mask = ((hsv[:, :, 2] > 170) & (hsv[:, :, 1] < 70)).astype(np.uint8) * 255
        out.append(cv2.resize(mask, (24, 36)))
    return out

def bootstrap(vid, side, pairs):
    os.makedirs(atlas_dir(vid), exist_ok=True)
    cap = cv2.VideoCapture(cr.video_path(vid)); _, labels = cr.load_atlas()
    n = 0
    for t, digits in pairs:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, fr = cap.read()
        hit = cr.find_label(fr, side, labels)
        if not hit: print(f"  t={t}: no label"); continue
        cs = cells(fr, *hit, geometry(vid))
        for i, d in enumerate(digits):
            if d == "?": continue          # that cell is occluded in this frame - skip it
            cv2.imwrite(os.path.join(atlas_dir(vid), f"d{d}_{t}_{i}.png"), cs[i]); n += 1
    print(f"bootstrapped {n} cell glyphs -> {atlas_dir(vid)}")

def load(vid):
    out = {}
    for f in os.listdir(atlas_dir(vid)):
        if not f.endswith(".png"): continue
        out.setdefault(f[1], []).append(cv2.imread(os.path.join(atlas_dir(vid), f), cv2.IMREAD_GRAYSCALE))
    return out

def classify(cell, atlas):
    best, bd = -1.0, None
    for d, tpls in atlas.items():
        for tpl in tpls:
            s = float(cv2.matchTemplate(cell, tpl, cv2.TM_CCOEFF_NORMED).max())
            if s > best: best, bd = s, d
    return bd, best

def scan(vid, side):
    atlas = load(vid); g = geometry(vid); _, labels = cr.load_atlas()
    cap = cv2.VideoCapture(cr.video_path(vid)); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    out = os.path.join(ROOT, "work", "combo", f"{vid}.{side}.jsonl")
    n = read = 0
    with open(out, "w", encoding="utf-8") as fh:
        while True:
            ok, fr = cap.read()
            if not ok: break
            t = n / fps; n += 1
            hit = cr.find_label(fr, side, labels)
            if not hit:
                fh.write(json.dumps([round(t, 4), None, -1.0]) + "\n"); continue
            cs = cells(fr, *hit, g)
            if cs is None:
                fh.write(json.dumps([round(t, 4), None, 0.0]) + "\n"); continue
            ds, conf = [], 1.0
            for c in cs:
                d, s = classify(c, atlas); ds.append(d); conf = min(conf, s)
            if conf >= 0.5 and all(ds):
                fh.write(json.dumps([round(t, 4), int("".join(ds)), round(conf, 3)]) + "\n"); read += 1
            else:
                fh.write(json.dumps([round(t, 4), None, round(conf, 3)]) + "\n")
    print(f"{out}: {read} read of {n} frames")

if __name__ == "__main__":
    if sys.argv[1] == "--calibrate":
        calibrate(sys.argv[2], sys.argv[3], [float(x) for x in sys.argv[4:]])
    elif sys.argv[1] == "--bootstrap":
        bootstrap(sys.argv[2], sys.argv[3], [(float(a.split("=")[0]), a.split("=")[1]) for a in sys.argv[4:]])
    elif sys.argv[1] == "--scan":
        scan(sys.argv[2], sys.argv[3])
