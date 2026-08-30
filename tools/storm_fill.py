# Storm mode: recover cumulative combo inside fast-ticking windows where values never
# persist across frames (rate > ~30/s beats the strict-persistence anchor path).
# Takes single-frame reads (conf floor), bounds them by the surrounding cumulative
# anchors, keeps the maximal isotonic subset, and emits synthetic pins at a regular
# spacing through the window — ready to merge into the anchors file.
#
#   python tools/storm_fill.py <videoId> <band> <w0> <w1> [runOffset] [confFloor]
# runOffset: add to raw combo to get cumulative (prior peaks + resets), default 0.
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    vid, band = sys.argv[1], sys.argv[2]
    w0, w1 = float(sys.argv[3]), float(sys.argv[4])
    off = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    floor = float(sys.argv[6]) if len(sys.argv) > 6 else 0.82
    reads = [json.loads(l) for l in open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.jsonl"), encoding="utf-8")]
    anchors = [tuple(x) for x in json.load(open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json")))]
    lo_b = max((a[2] for a in anchors if a[1] <= w0), default=0)
    hi_b = min((a[2] for a in anchors if a[0] >= w1), default=10 ** 9)
    win = [(t, v + off) for t, v, c in reads
           if w0 <= t <= w1 and v is not None and c >= floor and lo_b <= v + off <= hi_b]
    win.sort()
    # maximal isotonic subset (longest non-decreasing subsequence, O(n log n))
    import bisect as bs
    tails, tails_idx, parent = [], [], [-1] * len(win)
    for i, (t, v) in enumerate(win):
        j = bs.bisect_right(tails, v)
        if j == len(tails):
            tails.append(v); tails_idx.append(i)
        else:
            tails[j] = v; tails_idx[j] = i
        parent[i] = tails_idx[j - 1] if j > 0 else -1
    chain = []
    k = tails_idx[-1] if tails_idx else -1
    while k != -1:
        chain.append(win[k]); k = parent[k]
    chain.reverse()
    print(f"window {w0}..{w1}: {len(win)} candidate reads -> {len(chain)} isotonic")
    if not chain:
        return
    # synthetic pins every ~0.5s (last value at or before each grid point)
    pins = []
    t = w0
    while t <= w1:
        before = [c for c in chain if c[0] <= t]
        if before:
            pins.append([round(before[-1][0], 3), before[-1][1]])
        t += 0.5
    # dedupe
    seen, out = set(), []
    for p in pins:
        if tuple(p) not in seen:
            seen.add(tuple(p)); out.append(p)
    path = os.path.join(ROOT, "work", "combo", f"{vid}.{band}.stormpins.json")
    json.dump(out, open(path, "w"))
    print(f"{len(out)} synthetic pins -> {path}")
    print("  span:", out[0], "...", out[-1])

if __name__ == "__main__":
    main()
