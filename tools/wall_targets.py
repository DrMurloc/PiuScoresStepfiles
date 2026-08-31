# Wall-class targets: when holds chain into giant merged spans, per-hold pinning
# collapses (one region swallows the chart) and beat-weight distribution erases the
# real temporal profile. This builds author_ticks targets by TILING each observed
# hold span into ~windowSec chart-time windows and reading each window's tick count
# straight off the cumulative anchor curve: ticks(w) = dCum(w) - taps_in(w).
# Zones before the first anchor (or between sparse anchors) ride the curve's linear
# interp; the head zone (chart start -> first anchor) becomes one window whose
# internal shape stays on the file's own relative profile via author_ticks' Newton.
#
#   python tools/wall_targets.py <videoId> <band> <key> <offset> <judged> <out.json> [windowSec]
import bisect
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def main():
    vid, band, key = sys.argv[1], sys.argv[2], sys.argv[3]
    a, judged, out = float(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
    win = float(sys.argv[7]) if len(sys.argv) > 7 else 2.0

    anchors = json.load(open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json")))
    holds = json.load(open(os.path.join(ROOT, "work", "combo", vid + ".holds.json")))
    rows = list(csv.DictReader(open(os.path.join(CS_DIR, key + ".csv"), encoding="utf-8")))

    # tempo map + tap schedule from the chartstruct
    times, beats, taps = [], [], []
    for r in rows:
        t, b = float(r["Time"]), float(r["Beat"])
        times.append(t); beats.append(b)
        n = sum(1 for ch in r["Line"].lstrip("`") if ch == "1")
        if n: taps.append((t, n))
    tap_t = [t for t, n in taps]
    tap_c = []
    s = 0
    for t, n in taps: s += n; tap_c.append(s)

    def taps_before(ct):
        i = bisect.bisect_right(tap_t, ct)
        return tap_c[i - 1] if i else 0

    def beat_at(ct):
        i = bisect.bisect_left(times, ct)
        if i <= 0: return beats[0] + (ct - times[0])  # pre-chart: 1 beat/s filler
        if i >= len(times): return beats[-1] + (ct - times[-1])
        t0, t1, b0, b1 = times[i-1], times[i], beats[i-1], beats[i]
        return b0 if t1 == t0 else b0 + (b1 - b0) * (ct - t0) / (t1 - t0)

    # cumulative curve in chart time (anchor midpoints)
    ct_pts = [((t0 + t1) / 2 - a, c) for t0, t1, c in anchors]
    ct_pts.sort()
    cx = [p[0] for p in ct_pts]; cy = [p[1] for p in ct_pts]

    def cum_at(ct):
        i = bisect.bisect_left(cx, ct)
        if i <= 0: return cy[0] * max(0.0, min(1.0, (ct - (times[0])) / max(1e-9, cx[0] - times[0])))
        if i >= len(cx): return cy[-1]
        t0, t1, c0, c1 = cx[i-1], cx[i], cy[i-1], cy[i]
        return c0 if t1 == t0 else c0 + (c1 - c0) * (ct - t0) / (t1 - t0)

    spans = [(p["t0"], p["t1"]) for p in holds.get("pinned", [])] + \
            [(u["t0"], u["t1"]) for u in holds.get("unpinned", [])]
    spans.sort()
    total_ticks = judged - tap_c[-1]

    targets = []
    first_anchor_ct = cx[0]
    for t0, t1 in spans:
        edges = [t0]
        # head zone: one window up to the first anchor if the span starts blind
        cur = t0
        if t0 < first_anchor_ct - 0.5 and t1 > first_anchor_ct:
            edges.append(first_anchor_ct)
            cur = first_anchor_ct
        while cur + win < t1 - 0.25:
            cur += win
            edges.append(cur)
        edges.append(t1)
        for e0, e1 in zip(edges, edges[1:]):
            dcum = cum_at(e1) - cum_at(e0)
            tk = dcum - (taps_before(e1) - taps_before(e0))
            targets.append(dict(b0=beat_at(e0), b1=beat_at(e1), t0=e0, t1=e1, raw=tk))

    # round + reconcile to the exact total
    for t in targets: t["target"] = max(0, round(t["raw"]))
    drift = total_ticks - sum(t["target"] for t in targets)
    # push drift onto the largest window (usually the head bomb)
    big = max(targets, key=lambda t: t["target"])
    big["target"] = max(0, big["target"] + drift)
    for t in targets: del t["raw"]
    big["tuner"] = True
    targets.sort(key=lambda t: t["b0"])
    json.dump(targets, open(out, "w"), indent=0)
    print(f"{len(targets)} window targets -> {out}; total {sum(t['target'] for t in targets)}"
          f" (expected {total_ticks}); drift absorbed {drift}; tuner {big['target']}")

if __name__ == "__main__":
    main()
