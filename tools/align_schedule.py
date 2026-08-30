# Aligns a chart's event schedule (from its chartstruct) to a video's combo-anchor
# curve, then maps where hold ticks actually accrue. The fit needs no tick model:
# with the right offset, cumulative_ticks(t) = combo(t) - taps_so_far(t) must be
# non-negative and non-decreasing — wrong offsets misattribute taps and violate both.
#
#   python tools/align_schedule.py <videoId> <chartstructKey> [expectedJudged]
#
# Output: offset fit + the tick-accrual map vs the file's hold-active intervals —
# ticks accruing OUTSIDE the file's holds mean the hold PLACEMENT is wrong (missing
# or shortened holds), not just the authored rates.
import bisect
import csv
import json
import os
import sys

CS = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_schedule(key):
    rows = list(csv.DictReader(open(os.path.join(CS, key + ".csv"), encoding="utf-8")))
    taps, heads, spans = [], [], []
    open_holds = {}
    for r in rows:
        t = float(r["Time"])
        line = r["Line"].lstrip("`")
        if "1" in line:
            taps.append(t)
        for c, ch in enumerate(line):
            if ch == "2":
                open_holds[c] = t
                heads.append(t)
            elif ch == "3" and c in open_holds:
                spans.append((open_holds.pop(c), t, c))
    return taps, heads, spans

def fit_offset(taps, anchors, lo, hi, step=0.01):
    tap_ts = sorted(taps)
    best = None
    for i in range(int((hi - lo) / step)):
        a = lo + i * step
        prev = -1
        neg = dec = 0.0
        for t0, t1, v in anchors:
            ticks = v - bisect.bisect_right(tap_ts, t0 - a)
            if ticks < 0:
                neg += -ticks
            if ticks < prev:
                dec += prev - ticks
            prev = max(prev, ticks)
        score = neg + dec
        if best is None or score < best[1]:
            best = (a, score)
    return best

def main():
    vid, key = sys.argv[1], sys.argv[2]
    expected = int(sys.argv[3]) if len(sys.argv) > 3 else None
    band = sys.argv[4] if len(sys.argv) > 4 else "C"
    forced = float(sys.argv[5]) if len(sys.argv) > 5 else None
    taps, heads, spans = load_schedule(key)
    anchors = [tuple(x) for x in json.load(open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json")))]
    print(f"schedule: {len(taps)} taps, {len(spans)} holds; anchors: {len(anchors)}")

    # the offset cannot push the chart's last event past the video's end (the result
    # screen needs a moment too) — an unconstrained grid can find false minima there
    reads_path = os.path.join(ROOT, "work", "combo", f"{vid}.{band}.jsonl")
    last_t = 0.0
    with open(reads_path, encoding="utf-8") as f:
        for line in f:
            pass
        last_t = json.loads(line)[0]
    last_event = max(taps[-1] if taps else 0, max((s[1] for s in spans), default=0))
    hi = min(45.0, last_t - last_event - 1.0)
    if hi <= 2.0:
        print(f"IMPOSSIBLE: video too short for schedule (video {last_t:.1f}s, chart end {last_event:.1f}s)")
        return
    if forced is not None:
        a, score = fit_offset(taps, anchors, forced, forced + 0.011)
        print(f"offset FORCED: a = {a:.2f}s, violation score {score:.1f}")
    else:
        a, score = fit_offset(taps, anchors, 2.0, hi)
        print(f"offset fit: a = {a:.2f}s (video = chart + a), violation score {score:.1f} (grid 2..{hi:.1f})")

    tap_ts = sorted(taps)
    print("\n cumulative ticks at each anchor (chart-time):")
    prev_ticks, prev_ct = 0, None
    accrual = []
    for t0, t1, v in anchors:
        ct = t0 - a
        ticks = v - bisect.bisect_right(tap_ts, ct)
        if prev_ct is not None and ticks > prev_ticks:
            accrual.append((prev_ct, ct, ticks - prev_ticks))
        prev_ticks, prev_ct = max(prev_ticks, ticks), ct
    for t0, t1, d in accrual:
        # does the file think a hold is active anywhere in this window?
        infile = any(not (h1 < t0 or h0 > t1) for h0, h1, _ in spans)
        rate = d / (t1 - t0) if t1 > t0 else 0
        print(f"  {t0:7.2f}..{t1:7.2f}s  +{d:4d} ticks ({rate:5.1f}/s)  file-hold-here: {'YES' if infile else 'NO'}")
    total = prev_ticks
    print(f"\nfile hold spans (chart-time): {[(round(h0,1), round(h1,1)) for h0, h1, _ in spans]}")
    print(f"total observed ticks: {total}", f"(expected {expected - len(tap_ts)} = judged - taps)" if expected else "")

if __name__ == "__main__":
    main()
