# Reads the result screen at the end of a chart video and certifies each target chart
# against the game's judged note count: the judgment sum (P+G+Gd+B+M) of a completed
# pass equals ChartMix.NoteCount, so every video proves for itself that it shows the
# real chart. Result screens have TWO number columns — 1P (left-aligned at x0) and
# 2P (right-aligned at rx): a split-screen video fills both, a single play fills the
# side it was played on. Certification = the side whose judged total equals the
# chart's expected count.
#
#   --build-atlas <videoId> <t>   calibrate digit atlas from the known frame
#   --all [--force]               certify every downloaded worklist video (ledger-cached)
#   <videoId> [...]               certify specific videos
#
# Ledger: work/certification.json. Geometry (720p): rows y=311..466 pitch 31 anchored
# on the MAX COMBO label; 1P digits left-aligned at anchor-139, 2P right-aligned at
# anchor+330; monospace cells 10px, glyphs ~14px.
import glob
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATLAS = os.path.join(ROOT, "tools", "atlas")
LEDGER = os.path.join(ROOT, "work", "certification.json")
ROW_PITCH = 31
CELL_W, CELL_H = 10, 18
MAX_CELLS = 6
ANCHOR_TO_X0 = 139
ANCHOR_TO_RX = 330
ANCHOR_CY = 15
LABELS = ["perfect", "great", "good", "bad", "miss", "maxcombo"]

def video_path(vid):
    hits = [p for p in glob.glob(os.path.join(ROOT, "videos", vid + ".*"))
            if not p.endswith((".part", ".ytdl", ".txt"))]
    return hits[0] if hits else None

def frame_at(cap, t):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    return f if ok else None

def glyph_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return ((hsv[:, :, 2] > 175) & (hsv[:, :, 1] < 70)).astype(np.uint8) * 255

def cells_left(band):
    out = []
    for c in range(MAX_CELLS):
        cell = band[:, c * CELL_W:(c + 1) * CELL_W]
        if int(cell.sum() / 255) < 35:
            break
        out.append(cell)
    return out

def cells_right(band):
    w = band.shape[1]
    out = []
    for c in range(MAX_CELLS):
        x1 = w - c * CELL_W
        cell = band[:, x1 - CELL_W:x1]
        if int(cell.sum() / 255) < 35:
            break
        out.append(cell)
    return list(reversed(out))

def load_atlas():
    digits = {}
    for p in glob.glob(os.path.join(ATLAS, "d?.png")):
        digits[os.path.basename(p)[1]] = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    anchor = cv2.imread(os.path.join(ATLAS, "label_maxcombo.png"), cv2.IMREAD_GRAYSCALE)
    return digits, anchor

def classify(cell, digits, tag):
    best, best_d = -1.0, "?"
    for d, tpl in digits.items():
        score = cv2.matchTemplate(cell, tpl, cv2.TM_CCOEFF_NORMED)[0][0]
        if score > best:
            best, best_d = score, d
    if best < 0.55:
        os.makedirs(os.path.join(ROOT, "work", "unknown-glyphs"), exist_ok=True)
        cv2.imwrite(os.path.join(ROOT, "work", "unknown-glyphs", tag + ".png"), cell)
        return "?"
    return best_d

def read_side(frame, ax, ay_c, side, digits, vid):
    out = {}
    for k, label in enumerate(LABELS):
        y0 = int(ay_c - ROW_PITCH * (5 - k) - CELL_H / 2)
        if side == "1P":
            x0 = ax - ANCHOR_TO_X0
            band = glyph_mask(frame[y0:y0 + CELL_H, x0:x0 + CELL_W * MAX_CELLS])
            cells = cells_left(band)
        else:
            rx = ax + ANCHOR_TO_RX
            band = glyph_mask(frame[y0:y0 + CELL_H, rx - CELL_W * MAX_CELLS:rx])
            cells = cells_right(band)
        out[label] = "".join(classify(c, digits, f"{vid}_{side}_{label}_{i}")
                             for i, c in enumerate(cells))
    complete = all(out[k] != "" and out[k].isdigit() for k in LABELS)
    out["judged"] = sum(int(out[k]) for k in LABELS[:5]) if complete else None
    return out

def read_result(vid, digits, anchor):
    path = video_path(vid)
    if not path:
        return dict(vid=vid, status="no-video")
    cap = cv2.VideoCapture(path)
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    hit = None
    for back in np.arange(1.5, 45, 1.0):
        f = frame_at(cap, dur - back)
        if f is None or f.shape[0] != 720:
            continue
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(g, anchor, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx >= 0.75:
            sides = {s: read_side(f, loc[0], loc[1] + ANCHOR_CY, s, digits, vid) for s in ("1P", "2P")}
            if any(sides[s]["judged"] is not None for s in sides):
                hit = dict(vid=vid, status="ok", t=round(dur - back, 1), **{s.lower(): sides[s] for s in sides})
                break
    cap.release()
    return hit or dict(vid=vid, status="no-result-screen")

def build_atlas(vid, t):
    TRUTH = [(311, "1103"), (342, "018"), (373, "001"), (404, "000"), (435, "003"), (466, "609")]
    X0 = 406
    cap = cv2.VideoCapture(video_path(vid))
    frame = frame_at(cap, t)
    os.makedirs(ATLAS, exist_ok=True)
    got = {}
    for y, truth in TRUTH:
        band = glyph_mask(frame[int(y - CELL_H / 2):int(y + CELL_H / 2), X0:X0 + CELL_W * MAX_CELLS])
        cells = cells_left(band)
        print(f"y={y} truth={truth}: {len(cells)} cells")
        if len(cells) == len(truth):
            for ch, cell in zip(truth, cells):
                got.setdefault(ch, cell)
    for ch, cell in got.items():
        cv2.imwrite(os.path.join(ATLAS, f"d{ch}.png"), cell)
    y0 = 466 - ANCHOR_CY
    cv2.imwrite(os.path.join(ATLAS, "label_maxcombo.png"),
                cv2.cvtColor(frame[y0:y0 + 2 * ANCHOR_CY, X0 + ANCHOR_TO_X0:X0 + ANCHOR_TO_X0 + 190],
                             cv2.COLOR_BGR2GRAY))
    print("atlas digits:", sorted(got))

def main():
    if sys.argv[1] == "--build-atlas":
        build_atlas(sys.argv[2], float(sys.argv[3]))
        return
    digits, anchor = load_atlas()
    vmap = json.load(open(os.path.join(ROOT, "sources", "video-map.json"), encoding="utf-8"))
    ledger = {}
    if os.path.exists(LEDGER):
        ledger = json.load(open(LEDGER, encoding="utf-8"))
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    entries = [e for e in vmap if e.get("download")]
    if args:
        entries = [e for e in entries if e["vid"] in args]
    n_cert = n_open = 0
    for e in entries:
        vid = e["vid"]
        if not video_path(vid):
            continue
        if force or vid not in ledger or ledger[vid].get("status") != "ok":
            ledger[vid] = read_result(vid, digits, anchor)
        r = ledger[vid]
        totals = {s: r.get(s, {}).get("judged") for s in ("1p", "2p")} if r["status"] == "ok" else {}
        for ch in e["charts"]:
            side = next((s for s, j in totals.items() if j == ch["judged"]), None)
            if side:
                n_cert += 1
                verdict = f"CERTIFIED {side}"
            else:
                n_open += 1
                verdict = f"OPEN ({r['status']}; totals {totals})"
            print(f"{verdict:<44} {ch['chart']:<50} exp {ch['judged']:>5}  {vid}")
            ch_led = ledger[vid].setdefault("charts", {})
            ch_led[ch["chart"]] = dict(expected=ch["judged"], side=side,
                                       verdict="CERTIFIED" if side else "OPEN")
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(ledger, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\ncertified {n_cert} charts; open {n_open}")

if __name__ == "__main__":
    main()
