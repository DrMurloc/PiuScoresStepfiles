# Price each visible rail LOCALLY from the counter, without a run structure: the combo read
# just before the rail's head and the read just after its tail bracket the hold, and the
# difference minus the file's taps inside the span is that hold's ticks. Works whenever the
# counter is readable at both ends and no reset falls inside the hold (a drop between the
# two reads is reported, not priced). Where a bracket read is missing, the two frames are
# written to work/frames/rails/<vid>/ for eye reading.
#
#   python -X utf8 tools/rail_ticks.py "<chart>" <offset> [--lag 0.2]
import bisect
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    chart, a = sys.argv[1], float(sys.argv[2])
    lag = float(sys.argv[sys.argv.index("--lag") + 1]) if "--lag" in sys.argv else 0.2
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    vid, e = next((v, e) for v, e in cert.items() if chart in (e.get("charts") or {}))
    side = e["charts"][chart]["side"]
    s = e[side]
    judged, mc = int(s["judged"]), int(s["maxcombo"])
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    ncols = 10 if chart.split()[-1][0] == "D" else 5
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    key = smap[chart]["key"]
    rows, taps, beat_at = R.chartstruct(key, ncols)
    all_taps = sorted({float(r["Time"]) for r in rows if "1" in r["Line"]})
    t_first, t_last = float(rows[0]["Time"]), float(rows[-1]["Time"])
    sc = R.scan(vid, 0.5, float(e.get("t") or 150) - 0.5, band, ncols)
    ons, _ = R.onsets(sc, 60.0)
    rl = R.rails(sc)
    path = os.path.join(ROOT, "work", "combo", f"{vid}.{band}.jsonl")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "work", "combo", f"{vid}.C.jsonl")
    reads = sorted((t, v) for t, v, c in (json.loads(l) for l in open(path, encoding="utf-8")) if v is not None and c >= 0.6 and v <= mc)
    rt = [t for t, _ in reads]
    def read_before(t, span=0.6):
        i = bisect.bisect_right(rt, t) - 1
        return reads[i] if i >= 0 and t - reads[i][0] <= span else None
    def read_after(t, span=0.6):
        i = bisect.bisect_left(rt, t)
        return reads[i] if i < len(reads) and reads[i][0] - t <= span else None
    cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
    outdir = os.path.join(ROOT, "work", "frames", "rails", vid)
    os.makedirs(outdir, exist_ok=True)
    print(f"{chart}: {vid} band {band}, offset {a}, judged {judged}, owed {judged - len(all_taps)} hold events")
    rails = sorted((s0, e0, c) for c in rl for s0, e0 in rl[c] if t_first - 0.5 <= s0 - a <= t_last + 3.0)
    total = 0
    for s0, e0, c in rails:
        flashes = [o for o in ons[c] if s0 - 0.35 <= o <= s0 + 0.10]
        head = flashes[-1] if flashes else s0 + lag
        tail = e0 + lag
        ch, ct = head - a, tail - a
        rb, ra = read_before(head - 0.05), read_after(tail + 0.05)
        near = [t for t in taps[c] if abs(t - ch) <= 0.07]
        # a reset between the before-read and the tail hides when the bomb outruns it
        # (Naissance S20: 110 before a MISS, 457 after the finale) - any read in between that
        # sits well below the before-read is that reset
        dropped = rb and ra and any(v < rb[1] - 3 for t, v in reads if rb[0] < t < ra[0])
        if rb and ra and ra[1] >= rb[1] and not dropped:
            # every file tap judged between the two READS is in the difference, not just the
            # taps inside the rail's span (a read 0.5s before the head has the taps of that
            # half second in front of it); the head's own row is the hold's first tick when
            # the old file wrote it as a tap, so it stays in the count
            lo_t, hi_t = rb[0] - a - 0.12, ra[0] - a - 0.12
            between = [t for t in all_taps if lo_t < t <= hi_t]
            if near:
                between = [t for t in between if abs(t - ch) > 0.07]
            inside = len(between)
            ticks = ra[1] - rb[1] - inside
            total += max(ticks, 0)
            what = f"counter {rb[1]}@{rb[0]:.2f} -> {ra[1]}@{ra[0]:.2f}: +{ra[1]-rb[1]} incl. {inside} taps -> {ticks} ticks"
        elif rb and ra:
            what = f"counter DROPS between the reads ({rb[1]}@{rb[0]:.2f} -> {ra[1]}@{ra[0]:.2f}) - a reset inside or just before, frames needed"
        else:
            tiles = []
            for t in (head - 0.05, tail + 0.15):
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ok, fr = cap.read()
                if ok:
                    h, w = fr.shape[:2]
                    x0, x1 = (0, w // 2) if band == "L" else (w // 2, w) if band == "R" else (int(w * 0.25), int(w * 0.75))
                    tile = cv2.resize(fr[int(h * 0.30):int(h * 0.62), x0:x1], None, fx=0.5, fy=0.5)
                    cv2.putText(tile, f"{t:.2f}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    tiles.append(tile)
            fn = os.path.join(outdir, f"c{c}_{head:.2f}.png")
            if tiles:
                cv2.imwrite(fn, np.vstack(tiles))
            what = f"no bracket read ({'before' if not rb else ''}{' and ' if not rb and not ra else ''}{'after' if not ra else ''}) - frames {os.path.relpath(fn, ROOT)}"
        print(f"  col {c}: video {head:6.2f}-{tail:6.2f}  chart {ch:6.2f}-{ct:6.2f}  beats {R.snap_beat(beat_at(ch)):.3f}-{R.snap_beat(beat_at(ct)):.3f}  "
              f"head {'ON a file tap' if near else 'new note'} | {what}")
    print(f"  priced from brackets: {total} of {judged - len(all_taps)} owed")

if __name__ == "__main__":
    main()
