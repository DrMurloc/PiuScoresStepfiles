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
LABELS = ["perfect", "great", "good", "bad", "miss", "maxcombo"]

# Result screens come in more than one skin. Each is a different font AND a different layout -
# the Phoenix one sets the counts just left of the labels, the older one puts them far left -
# so a profile carries its own atlas and its own geometry, anchored on the MAX COMBO label:
#   pitch  rows apart          x0  digits' left edge, measured left from the anchor
#   cw/ch  digit cell          rx  the 2P column's right edge, right of the anchor (None: no 2P)
#   cy     anchor centre       cells  most digits a count can have
PROFILES = [
    dict(name="phoenix", atlas="atlas", pitch=31, cw=10, ch=18, x0=139, rx=330, cy=15, cells=6),
    dict(name="xx", atlas="atlas-xx", pitch=35, cw=16, ch=18, x0=358, rx=None, cy=15, cells=6),
]
ROW_PITCH, CELL_W, CELL_H, MAX_CELLS = 31, 10, 18, 6      # build_atlas still calibrates Phoenix
ANCHOR_TO_X0, ANCHOR_TO_RX, ANCHOR_CY = 139, 330, 15

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

PAD = 2  # px of slack each side; classify() searches the best alignment inside it

def _cell(band, x0, cw):
    lo, hi = max(0, x0 - PAD), min(band.shape[1], x0 + cw + PAD)
    return band[:, lo:hi]

def cells_left(band, cw, n):
    out = []
    for c in range(n):
        core = band[:, c * cw:(c + 1) * cw]
        if int(core.sum() / 255) < 35:
            break
        out.append(_cell(band, c * cw, cw))
    return out

def cells_right(band, cw, n):
    w = band.shape[1]
    out = []
    for c in range(n):
        x1 = w - c * cw
        core = band[:, x1 - cw:x1]
        if int(core.sum() / 255) < 35:
            break
        out.append(_cell(band, x1 - cw, cw))
    return list(reversed(out))

def load_atlas(name="atlas"):
    folder = os.path.join(ROOT, "tools", name)
    digits = {}
    for p in glob.glob(os.path.join(folder, "d?.png")):
        digits[os.path.basename(p)[1]] = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    anchor = cv2.imread(os.path.join(folder, "label_maxcombo.png"), cv2.IMREAD_GRAYSCALE)
    return digits, anchor

def load_profiles():
    out = []
    for prof in PROFILES:
        digits, anchor = load_atlas(prof["atlas"])
        if digits and anchor is not None:
            out.append({**prof, "digits": digits, "anchor": anchor})
    return out

def classify(cell, digits, tag):
    best, best_d = -1.0, "?"
    for d, tpl in digits.items():
        score = float(cv2.matchTemplate(cell, tpl, cv2.TM_CCOEFF_NORMED).max())
        if score > best:
            best, best_d = score, d
    if best < 0.55:
        os.makedirs(os.path.join(ROOT, "work", "unknown-glyphs"), exist_ok=True)
        cv2.imwrite(os.path.join(ROOT, "work", "unknown-glyphs", tag + ".png"), cell)
        return "?"
    return best_d

def read_side(frame, ax, ay_c, side, vid, prof):
    cw, ch, n = prof["cw"], prof["ch"], prof["cells"]
    if side == "2P" and prof["rx"] is None:            # this skin shows one side only
        return {k: "" for k in LABELS} | {"judged": None}
    out = {}
    for k, label in enumerate(LABELS):
        y0 = int(ay_c - prof["pitch"] * (5 - k) - ch / 2)
        if side == "1P":
            x0 = ax - prof["x0"]
            band = glyph_mask(frame[y0:y0 + ch, x0:x0 + cw * n])
            cells = cells_left(band, cw, n)
        else:
            rx = ax + prof["rx"]
            band = glyph_mask(frame[y0:y0 + ch, rx - cw * n:rx])
            cells = cells_right(band, cw, n)
        out[label] = "".join(classify(c, prof["digits"], f"{vid}_{side}_{label}_{i}")
                             for i, c in enumerate(cells))
    complete = all(out[k] != "" and out[k].isdigit() for k in LABELS)
    out["judged"] = sum(int(out[k]) for k in LABELS[:5]) if complete else None
    return out

def match_anchor(frame, anchor):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(g, anchor, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    return mx, loc

def read_frame(f, vid, prof, scale=1.0):
    """Read both sides off a result frame, rescaled so the panel sits at the atlas's size."""
    if scale != 1.0:
        f = cv2.resize(f, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_AREA)
    mx, loc = match_anchor(f, prof["anchor"])
    if mx < 0.75:
        return None
    sides = {s: read_side(f, loc[0], loc[1] + prof["cy"], s, vid, prof) for s in ("1P", "2P")}
    return sides if any(sides[s]["judged"] is not None for s in sides) else None

def read_result(vid, profiles):
    path = video_path(vid)
    if not path:
        return dict(vid=vid, status="no-video")
    cap = cv2.VideoCapture(path)
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    hit, best = None, (0.0, None, None, None)
    for back in np.arange(1.5, 45, 1.0):
        f = frame_at(cap, dur - back)
        if f is None or f.shape[0] != 720:
            continue
        for prof in profiles:
            mx, _ = match_anchor(f, prof["anchor"])
            if mx > best[0]:
                best = (mx, f, back, prof)
            if mx >= 0.75:
                sides = read_frame(f, vid, prof)
                if sides:
                    hit = dict(vid=vid, status="ok", t=round(dur - back, 1), skin=prof["name"],
                               **{s.lower(): sides[s] for s in sides})
                    break
        if hit:
            break
    # Some captures render the whole panel larger - the same skin, ~13% bigger - and a
    # fixed-size template tops out near 0.70 on them. Rescale until it sits at atlas size.
    if hit is None and best[1] is not None:
        for scale in np.arange(0.80, 1.36, 0.02):
            sides = read_frame(best[1], vid, best[3], float(scale))
            if sides:
                hit = dict(vid=vid, status="ok", t=round(dur - best[2], 1), skin=best[3]["name"],
                           scale=round(float(scale), 2), **{s.lower(): sides[s] for s in sides})
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
                got.setdefault(ch, cell[:, PAD:PAD + CELL_W])  # templates stay tight
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
    profiles = load_profiles()
    # --map/--ledger let a batch beyond the census certify into its own files; the census
    # ledger and its worklist stay untouched.
    vmap_path = sys.argv[sys.argv.index("--map") + 1] if "--map" in sys.argv         else os.path.join(ROOT, "sources", "video-map.json")
    ledger_path = sys.argv[sys.argv.index("--ledger") + 1] if "--ledger" in sys.argv else LEDGER
    vmap = json.load(open(vmap_path, encoding="utf-8"))
    ledger = {}
    if os.path.exists(ledger_path):
        ledger = json.load(open(ledger_path, encoding="utf-8"))
    force = "--force" in sys.argv
    flagged = {sys.argv[i + 1] for i, a in enumerate(sys.argv) if a in ("--map", "--ledger")}
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a not in flagged]
    entries = [e for e in vmap if e.get("download")]
    if args:
        entries = [e for e in entries if e["vid"] in args]
    n_cert = n_open = 0
    for e in entries:
        vid = e["vid"]
        if not video_path(vid):
            continue
        if force or vid not in ledger or ledger[vid].get("status") != "ok":
            ledger[vid] = read_result(vid, profiles)
        r = ledger[vid]
        totals = {s: r.get(s, {}).get("judged") for s in ("1p", "2p")} if r["status"] == "ok" else {}
        for ch in e["charts"]:
            # a re-rated chart can carry a different Phoenix 2 count; either certifies
            expect = {ch["judged"]} | ({ch["judged_alt"]} if ch.get("judged_alt") else set())
            side = next((s for s, j in totals.items() if j in expect), None)
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
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    json.dump(ledger, open(ledger_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\ncertified {n_cert} charts; open {n_open}")

if __name__ == "__main__":
    main()
