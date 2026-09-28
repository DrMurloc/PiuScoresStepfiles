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
#   --read-one <videoId> --out <file.json> [--unknown-dir <dir>]
#                                 read one video's result screen, plus a confirming second
#                                 frame, into its own file - never into a ledger (the loops'
#                                 way in: one supervised subprocess per video)
#
# Ledger: work/certification.json. Geometry (720p): rows y=311..466 pitch 31 anchored
# on the MAX COMBO label; 1P digits left-aligned at anchor-139, 2P right-aligned at
# anchor+330; monospace cells 10px, glyphs ~14px.
import glob
import json
import os
import sys
import atomicio  # noqa: E402  (atomic writes: tools/atomicio.py)

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATLAS = os.path.join(ROOT, "tools", "atlas")
LEDGER = os.path.join(ROOT, "work", "certification.json")
LABELS = ["perfect", "great", "good", "bad", "miss", "maxcombo"]
# where a glyph no atlas digit matches is dumped for atlas work (--unknown-dir moves it, so a
# loop's reads never write into the shared folder)
UNKNOWN_DIR = os.path.join(ROOT, "work", "unknown-glyphs")

# Result screens come in more than one skin. Each is a different font AND a different layout -
# the Phoenix one sets the counts just left of the labels, the older one puts them far left -
# so a profile carries its own atlas and its own geometry, anchored on the MAX COMBO label:
#   pitch  rows apart          x0  digits' left edge, measured left from the anchor
#   cw/ch  digit cell          rx  the 2P column's right edge, right of the anchor (None: no 2P)
#   cy     anchor centre       cells  most digits a count can have
# The XX skin has a 2P column too, right-aligned 500 px right of its MAX COMBO label. Until
# 2026-09-27 the profile said it showed one side only (rx=None), so every XX play on the 2P side
# read as a 1P total that matched nothing, or as no result screen at all when 1P was empty.
PROFILES = [
    dict(name="phoenix", atlas="atlas", pitch=31, cw=10, ch=18, x0=139, rx=330, cy=15, cells=6),
    dict(name="xx", atlas="atlas-xx", pitch=35, cw=16, ch=18, x0=358, rx=500, cy=15, cells=6),
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

def frame_pos(cap, t):
    """frame_at, plus where the decoder says that frame is (s): a broken stream seeks short of t."""
    f = frame_at(cap, t)
    return f, (cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 if f is not None else None)

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
        os.makedirs(UNKNOWN_DIR, exist_ok=True)
        cv2.imwrite(os.path.join(UNKNOWN_DIR, tag + ".png"), cell)
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
    """The first result screen found stepping back from the end of the video. A video the decoder
    cannot open, or whose last 45 s do not decode (a download cut short, a stream that stops
    decoding mid-file), is `corrupt-video` with a reason - never `no-result-screen`, which says
    the footage was read and holds no result screen."""
    path = video_path(vid)
    if not path:
        return dict(vid=vid, status="no-video")
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return dict(vid=vid, status="corrupt-video", reason="the decoder cannot open it")
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    hit, best = None, (0.0, None, None, None)
    on_target = 0          # frames that decoded where they were asked for (a broken stream seeks short)
    for back in np.arange(1.5, 45, 1.0):
        f, pos = frame_pos(cap, dur - back)
        if f is not None and abs(pos - (dur - back)) <= 2.0:
            on_target += 1
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
    if hit:
        return hit
    if not on_target:
        return dict(vid=vid, status="corrupt-video",
                    reason="no frame decodes in the last 45 s of the %.1f s it declares" % dur)
    import guards                                  # the recorded list of unusable footage
    bad = guards.footage_corrupt_reason(vid)
    if bad:
        return dict(vid=vid, status="corrupt-video", reason=bad)
    return dict(vid=vid, status="no-result-screen")


# ---------------------------------------------------------------- the certification gate
# A read certifies a (video, side) only when it passes every check here: all six cells are digits;
# maxcombo <= P+G (a GOOD neither breaks nor extends the combo, so no combo can outrun P+G); a
# play with no BAD and no MISS has maxcombo == P+G; and a second frame at least 1 s from the
# first reads the same six cells. (Checked on the 1,648 committed reads on 2026-09-27: every read
# of a certified side passes the two combo rules.) The blind transcription the loops add on top
# lives in tools/cert_skins.py.

CONFIRM_OFFSETS = (-1.1, -1.5, -2.0, -2.5, -3.0, -4.0, 1.1, 1.5)

def side_checks(s):
    """[failure, ...] for one side's read (empty = it passes the on-screen checks)."""
    if not s or s.get("judged") is None:
        return ["not all six cells are digits"]
    fails = []
    cells = [s.get(k, "") for k in LABELS]
    if not all(c.isdigit() for c in cells):
        return ["not all six cells are digits"]
    P, G, Gd, B, M, MC = (int(c) for c in cells)
    if MC > P + G:
        fails.append("maxcombo %d > P+G %d" % (MC, P + G))
    if B == 0 and M == 0 and MC != P + G:
        fails.append("no BAD or MISS but maxcombo %d != P+G %d" % (MC, P + G))
    return fails

def confirm_read(vid, hit, profiles):
    """Re-read the result screen of `hit` (a read_result() answer) on other frames at least 1.1 s
    from it - the hit's own profile and scale - and return every read tried, in order:
    [{t, dt, 1p, 2p}] (a side that reads nothing is None). It stops once every side the hit read
    has a second read with the same six cells; confirmed() judges the list."""
    prof = next((p for p in profiles if p["name"] == hit.get("skin")), None)
    path = video_path(vid)
    if prof is None or not path:
        return []
    cap = cv2.VideoCapture(path)
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    wanted = [s for s in ("1p", "2p") if (hit.get(s) or {}).get("judged") is not None]
    out = []
    for dt in CONFIRM_OFFSETS:
        t = float(hit["t"]) + dt
        if t < 0 or t > dur:
            continue
        f = frame_at(cap, t)
        if f is None or f.shape[0] != 720:
            continue
        sides = read_frame(f, vid, prof, hit.get("scale", 1.0)) or {}
        out.append(dict(t=round(t, 2), dt=dt, **{s.lower(): sides.get(s) for s in ("1P", "2P")}))
        if all(confirmed(hit, out, s)[0] for s in wanted):
            break
    cap.release()
    return out

def confirmed(hit, reads, side):
    """(True, t) when some read at least 1 s from the hit gives `side` the same six cells; else
    (False, why) - the first complete read that differs, or that no other frame read the side."""
    first = hit.get(side) or {}
    differ = None
    for r in reads:
        s = r.get(side) or {}
        if s.get("judged") is None:
            continue
        if all(s.get(k) == first.get(k) for k in LABELS):
            return True, r["t"]
        differ = differ or "the frame at %.2f s reads %s" % (r["t"], "/".join(s.get(k, "") for k in LABELS))
    return False, differ or "no second frame at least 1 s away reads this side"

def read_one(vid, out_path=None, confirm=True):
    """The loops' reader: one video, its confirming reads and the per-side checks (unless
    `confirm` is False: a read wanted only for comparison), written to its own file (atomically)
    when `out_path` is given, never into a ledger."""
    import hashlib
    profiles = load_profiles()
    hit = read_result(vid, profiles)
    doc = dict(vid=vid, read=hit, code=hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:16])
    if hit.get("status") == "ok" and confirm:
        reads = confirm_read(vid, hit, profiles)
        doc["confirm"] = reads
        doc["checks"] = {}
        for side in ("1p", "2p"):
            if (hit.get(side) or {}).get("judged") is None:
                continue
            ok, why = confirmed(hit, reads, side)
            fails = side_checks(hit[side]) + ([] if ok else ["unconfirmed: " + why])
            doc["checks"][side] = dict(fails=fails, confirm_t=why if ok else None)
    if out_path:
        atomicio.write_json(out_path, doc, encoding="utf-8", ensure_ascii=False, indent=1)
    return doc

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
    global UNKNOWN_DIR
    if sys.argv[1] == "--build-atlas":
        build_atlas(sys.argv[2], float(sys.argv[3]))
        return
    if sys.argv[1] == "--read-one":
        if "--unknown-dir" in sys.argv:
            UNKNOWN_DIR = sys.argv[sys.argv.index("--unknown-dir") + 1]
        doc = read_one(sys.argv[2], sys.argv[sys.argv.index("--out") + 1])
        r = doc["read"]
        print("VERDICT: %s" % r["status"].upper().replace("-", "_"))
        print(json.dumps({k: r.get(k) for k in ("status", "t", "skin", "scale", "reason") if k in r}),
              {s: (r.get(s) or {}).get("judged") for s in ("1p", "2p")}, doc.get("checks"))
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
    atomicio.write_json(ledger_path, ledger, encoding="utf-8", ensure_ascii=False, indent=1)
    print(f"\ncertified {n_cert} charts; open {n_open}")

if __name__ == "__main__":
    main()
