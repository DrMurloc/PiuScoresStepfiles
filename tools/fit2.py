# Two-sided offset fit for tick-dominated charts: scores candidate offsets ONLY
# inside tap-only windows (no file hold active), where observed combo deltas must
# equal tap counts exactly — extra or missing events both penalize, so wrong
# offsets cannot hide in tick slack the way they do under the one-sided bound.
#   python tools/fit2.py <videoId> <band> <chartstructKey> [lo hi]
import bisect
import csv
import json
import os
import sys

CS = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(key):
    rows = list(csv.DictReader(open(os.path.join(CS, key + ".csv"), encoding="utf-8")))
    taps, spans, open_h = [], [], {}
    for r in rows:
        t = float(r["Time"])
        line = r["Line"].lstrip("`")
        if "1" in line:
            taps.append(t)
        for c, ch in enumerate(line):
            if ch == "2":
                open_h[c] = t
            elif ch == "3" and c in open_h:
                spans.append((open_h.pop(c), t))
    spans.sort()
    merged = []
    for s in spans:
        if merged and s[0] <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], s[1]))
        else:
            merged.append(s)
    return sorted(taps), merged

def main():
    vid, band, key = sys.argv[1], sys.argv[2], sys.argv[3]
    lo = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
    hi = float(sys.argv[5]) if len(sys.argv) > 5 else 40.0
    taps, holds = load(key)
    anchors = [tuple(x) for x in json.load(open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json")))]
    pts = [(a[0], a[2]) for a in anchors]
    hold_starts = [h[0] for h in holds]
    hold_ends = [h[1] for h in holds]

    def hold_free(c0, c1):
        # no hold overlaps [c0, c1]
        i = bisect.bisect_left(hold_ends, c0)
        return i >= len(hold_starts) or hold_starts[i] >= c1

    best = None
    a = lo
    while a <= hi:
        pen = n = 0
        for (t1, v1), (t2, v2) in zip(pts, pts[1:]):
            if not (0.3 <= t2 - t1 <= 6.0) or v2 < v1:
                continue
            c0, c1 = t1 - a, t2 - a
            if c0 < 0 or not hold_free(c0 - 0.15, c1 + 0.15):
                continue
            ti = bisect.bisect_right(taps, c1) - bisect.bisect_right(taps, c0)
            pen += abs((v2 - v1) - ti)
            n += 1
        if n >= 8:
            score = pen / n
            if best is None or score < best[1]:
                best = (a, score, n)
        a = round(a + 0.02, 3)
    if best:
        print(f"fit2: a = {best[0]:.2f}, mean tap-window error {best[1]:.2f} over {best[2]} windows")
    else:
        print("fit2: not enough tap-only windows")

if __name__ == "__main__":
    main()
