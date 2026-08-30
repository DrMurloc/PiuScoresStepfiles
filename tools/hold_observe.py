# Per-hold observed judgment counts from a video's combo reads.
# For each hold span (chart time), estimates the combo value just before the head
# and just after the release — strict anchors when one sits close, else isotonic-
# filtered single-frame reads — and reports observed events = delta - taps inside.
# Holds whose edges can't be pinned (counter hidden, e.g. before combo 4) are
# reported as a GROUP with the remainder implied by closure.
#
#   python tools/hold_observe.py <videoId> <chartstructKey> <offset> <judged>
import bisect
import csv
import json
import os
import sys

CS = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = 0.22   # seconds clear of the hold edge

def load(key):
    rows = list(csv.DictReader(open(os.path.join(CS, key + ".csv"), encoding="utf-8")))
    taps, spans, open_h = [], [], {}
    for r in rows:
        t, b = float(r["Time"]), float(r["Beat"])
        line = r["Line"].lstrip("`")
        if "1" in line:
            taps.append(t)
        for c, ch in enumerate(line):
            if ch == "2":
                open_h[c] = (t, b)
            elif ch == "3" and c in open_h:
                (t0, b0) = open_h.pop(c)
                spans.append((t0, t, b0, b, c))
    spans.sort()
    return sorted(taps), spans

def combo_at(tv, anchors, reads):
    # strict anchor covering or near tv
    near = [a for a in anchors if a[0] - 0.45 <= tv <= a[1] + 0.45]
    if near:
        best = min(near, key=lambda a: min(abs(tv - a[0]), abs(tv - a[1])))
        return best[2], "anchor"
    # isotonic single reads in +/-1.2s: value bounded by surrounding anchors
    lo_b = max((a[2] for a in anchors if a[1] <= tv), default=0)
    hi_b = min((a[2] for a in anchors if a[0] >= tv), default=10**9)
    win = [(t, v) for t, v, c in reads if abs(t - tv) <= 1.2 and v is not None and c >= 0.85 and lo_b <= v <= hi_b]
    if not win:
        return None, "none"
    # keep the largest monotone subset, then interpolate
    win.sort()
    keep = []
    for t, v in win:
        while keep and keep[-1][1] > v:
            keep.pop()
        keep.append((t, v))
    before = [v for t, v in keep if t <= tv]
    after = [v for t, v in keep if t > tv]
    if before and after:
        return (before[-1] + after[0]) // 2 if after[0] - before[-1] > 1 else before[-1], "iso"
    return (before[-1] if before else after[0]), "iso-edge"

def main():
    vid, key, a, judged = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4])
    taps, spans = load(key)
    anchors = [tuple(x) for x in json.load(open(os.path.join(ROOT, "work", "combo", vid + ".anchors.json")))]
    reads = [json.loads(l) for l in open(os.path.join(ROOT, "work", "combo", vid + ".jsonl"), encoding="utf-8")]
    total_ticks = judged - len(taps)
    print(f"taps {len(taps)}, holds {len(spans)}, target total hold events {total_ticks}")
    observed, unpinned = [], []
    for t0, t1, b0, b1, col in spans:
        v0, how0 = combo_at(t0 - EDGE + a, anchors, reads)
        v1, how1 = combo_at(t1 + EDGE + a, anchors, reads)
        taps_in = bisect.bisect_right(taps, t1 + EDGE) - bisect.bisect_right(taps, t0 - EDGE)
        if v0 is None or v1 is None:
            unpinned.append((t0, t1, b0, b1))
            print(f"  hold {t0:7.2f}..{t1:7.2f}s (beat {b0:6.2f}..{b1:6.2f})  UNPINNED ({how0}/{how1})")
            continue
        ev = v1 - v0 - taps_in
        observed.append((t0, t1, b0, b1, ev))
        print(f"  hold {t0:7.2f}..{t1:7.2f}s (beat {b0:6.2f}..{b1:6.2f})  observed {ev:4d}  (combo {v0}->{v1}, taps_in {taps_in}, {how0}/{how1})")
    pinned_sum = sum(e for *_, e in observed)
    rem = total_ticks - pinned_sum
    print(f"pinned sum {pinned_sum}; remainder for {len(unpinned)} unpinned hold(s): {rem}")
    json.dump(dict(offset=a, judged=judged, taps=len(taps),
                   pinned=[dict(t0=t0, t1=t1, b0=b0, b1=b1, events=e) for t0, t1, b0, b1, e in observed],
                   unpinned=[dict(t0=t0, t1=t1, b0=b0, b1=b1) for t0, t1, b0, b1 in unpinned],
                   remainder=rem),
              open(os.path.join(ROOT, "work", "combo", vid + ".holds.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
