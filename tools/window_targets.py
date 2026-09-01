# Window targets for drill charts: hundreds of tenth-second holds that the combo curve cannot
# resolve one at a time. Per-hold brackets on those are noise (a 0.1s hold "observes" 0 or 38
# depending on which anchor happens to sit next to it), while a two-second window holds enough
# anchors to be read honestly. So: cluster the file's holds (gap under clusterGap), tile each
# cluster into ~windowSec windows, read each window's ticks straight off the cumulative curve
# (dCum - taps), pin any window the frames settled, and spread the closure remainder over the
# unpinned windows in proportion to what the curve saw there. The largest unpinned window is the
# tuner author_ticks needs for rounding.
#
#   python tools/window_targets.py <vid> <band> <key> <offset> <judged> <out.json>
#                                  [windowSec=2.0] [clusterGap=1.0] [pin t0-t1=N ...]
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
    gap = float(sys.argv[8]) if len(sys.argv) > 8 else 1.0
    pins, spread = [], "observed"
    for p in sys.argv[9:]:
        if p.startswith("spread="):
            spread = p.split("=")[1]; continue        # observed (default) | length: the file's own profile
        span, n = p.split("="); t0, t1 = span.split("-"); pins.append((float(t0), float(t1), int(n)))

    anchors = json.load(open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json")))
    rows = list(csv.DictReader(open(os.path.join(CS_DIR, key + ".csv"), encoding="utf-8")))
    times, beats, taps, holds, open_h = [], [], [], [], {}
    for r in rows:
        t, b = float(r["Time"]), float(r["Beat"]); L = r["Line"].lstrip("`")
        times.append(t); beats.append(b)
        if "1" in L: taps.append(t)                      # one judged event per step row
        for i, ch in enumerate(L):
            if ch == "2": open_h[i] = t
            if ch == "3" and i in open_h: holds.append((open_h.pop(i), t))
    holds.sort()
    def taps_in(c0, c1): return bisect.bisect_right(taps, c1) - bisect.bisect_right(taps, c0)
    def beat_at(ct):
        i = bisect.bisect_left(times, ct)
        if i <= 0: return beats[0] + (ct - times[0])
        if i >= len(times): return beats[-1] + (ct - times[-1])
        t0, t1, b0, b1 = times[i-1], times[i], beats[i-1], beats[i]
        return b0 if t1 == t0 else b0 + (b1 - b0) * (ct - t0) / (t1 - t0)
    pts = sorted(((t0 + t1) / 2 - a, c) for t0, t1, c in anchors)
    cx, cy = [p[0] for p in pts], [p[1] for p in pts]
    def cum_at(ct):
        i = bisect.bisect_left(cx, ct)
        if i <= 0: return cy[0] * max(0.0, min(1.0, (ct - times[0]) / max(1e-9, cx[0] - times[0])))
        if i >= len(cx): return cy[-1]
        t0, t1, c0, c1 = cx[i-1], cx[i], cy[i-1], cy[i]
        return c0 if t1 == t0 else c0 + (c1 - c0) * (ct - t0) / (t1 - t0)

    # clusters of holds
    clusters = []
    for h0, h1 in holds:
        if clusters and h0 - clusters[-1][1] <= gap: clusters[-1][1] = max(clusters[-1][1], h1)
        else: clusters.append([h0, h1])
    # pinned spans are their own windows; carve them out of the clusters
    targets = []
    for c0, c1 in clusters:
        edges = [c0]
        cur = c0
        while cur + win < c1 - 0.25: cur += win; edges.append(cur)
        edges.append(c1)
        for e0, e1 in zip(edges, edges[1:]):
            targets.append(dict(t0=e0, t1=e1))
    for p0, p1, n in pins:
        targets = [t for t in targets if t["t1"] <= p0 + 1e-6 or t["t0"] >= p1 - 1e-6] + [dict(t0=p0, t1=p1, pinned=n)]
    targets.sort(key=lambda t: t["t0"])
    for t in targets:
        t["b0"], t["b1"] = beat_at(t["t0"]), beat_at(t["t1"])
        raw = cum_at(t["t1"]) - cum_at(t["t0"]) - taps_in(t["t0"], t["t1"])
        t["target"] = t["pinned"] if "pinned" in t else max(0, round(raw))
    total_ticks = judged - len(taps)
    unp = [t for t in targets if "pinned" not in t]
    delta = total_ticks - sum(t["target"] for t in targets)
    # the remainder goes where the curve saw ticks (observed) or where the file has hold
    # length (length) - the latter when a player dropped holds, since a window that read
    # zero because of a BAD still owes the ticks the chart would have judged there
    weight = (lambda t: t["target"]) if spread == "observed" else (lambda t: t["t1"] - t["t0"])
    S = sum(weight(t) for t in unp) or 1
    for t in unp: t["target"] = max(0, t["target"] + round(delta * weight(t) / S))
    big = max(unp, key=lambda t: t["target"])
    big["target"] += total_ticks - sum(t["target"] for t in targets); big["tuner"] = True
    for t in targets: t.pop("pinned", None)
    json.dump(targets, open(out, "w"), indent=0)
    rates = sorted((((t["target"] / max(t["t1"] - t["t0"], 1e-6)), t) for t in targets), key=lambda x: x[0])
    print(f"{len(targets)} windows over {len(clusters)} clusters -> {out}; total {sum(t['target'] for t in targets)} "
          f"(expected {total_ticks}); closure spread {delta:+d}; tuner {big['t0']:.1f}-{big['t1']:.1f}:{big['target']}")
    print("windows:", "  ".join(f"{t['t0']:.1f}-{t['t1']:.1f}:{t['target']}{'*' if t.get('tuner') else ''}" for t in targets))
    print("fastest:", "  ".join(f"{t['t0']:.1f}-{t['t1']:.1f}:{r:.0f}/s" for r, t in rates[-4:]))

if __name__ == "__main__":
    main()
