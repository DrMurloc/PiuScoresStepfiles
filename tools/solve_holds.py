# Solves per-hold judged-event counts from cumulative pins as a linear system:
# each consecutive pin pair gives  dCum = taps_in + sum_j x_j * overlap_frac_j,
# assuming uniform event rate within a hold (which is how ticks get authored anyway).
# Bounded least squares (x >= 0) with the closure total as a heavily weighted
# equation; integers by largest-remainder preserving the exact total.
#
#   python tools/solve_holds.py <chartstructKey> <offset> <judged> <pins.json> <out-targets.json>
# pins.json: [[video_t, cumulative_judged], ...]  (caller already run/reset-adjusted)
import bisect
import csv
import json
import os
import sys

import numpy as np
from scipy.optimize import lsq_linear

CS = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
                t0, b0 = open_h.pop(c)
                spans.append((t0, t, b0, b))
    spans.sort()
    merged = []
    for s in spans:
        if merged and s[0] <= merged[-1][1] + 1e-6:
            m = merged[-1]
            merged[-1] = (m[0], max(m[1], s[1]), m[2], max(m[3], s[3]))
        else:
            merged.append(s)
    return sorted(taps), merged

def main():
    key, a, judged = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
    pins = json.load(open(sys.argv[4], encoding="utf-8"))
    out_path = sys.argv[5]
    taps, spans = load(key)
    total = judged - len(taps)
    # virtual pins: cumulative 0 before everything, `judged` after everything
    first = min(spans[0][0], taps[0]) - 1.0
    last = max(spans[-1][1], taps[-1]) + 1.0
    cpins = sorted([(first, 0), (last, judged)] + [(v - a, c) for v, c in pins])
    H = len(spans)
    rows_A, rows_b, w = [], [], []
    for (t0, c0), (t1, c1) in zip(cpins, cpins[1:]):
        if t1 <= t0:
            continue
        taps_in = bisect.bisect_right(taps, t1) - bisect.bisect_right(taps, t0)
        coef = np.zeros(H)
        for j, (h0, h1, _, _) in enumerate(spans):
            ov = max(0.0, min(t1, h1) - max(t0, h0))
            if ov > 0:
                coef[j] = ov / (h1 - h0)
        rows_A.append(coef)
        rows_b.append(c1 - c0 - taps_in)
        w.append(1.0)
    # closure equation, heavily weighted
    rows_A.append(np.ones(H))
    rows_b.append(total)
    w.append(50.0)
    A = np.array(rows_A) * np.array(w)[:, None]
    b = np.array(rows_b, dtype=float) * np.array(w)
    res = lsq_linear(A, b, bounds=(0, np.inf))
    x = res.x
    ints = np.floor(x).astype(int)
    rem = total - ints.sum()
    order = np.argsort(-(x - ints))
    for i in range(abs(int(rem))):
        ints[order[i % H]] += 1 if rem > 0 else -1
    ints = np.maximum(ints, 0)
    # print residuals per pin interval for honesty
    fit = (np.array(rows_A[:-1]) @ ints)
    print("interval residuals (obs - fit):",
          [int(rb - f) for rb, f in zip(rows_b[:-1], fit)])
    targets = []
    for (h0, h1, b0, b1), v in zip(spans, ints):
        targets.append(dict(b0=b0, b1=b1, t0=h0, t1=h1, target=int(v)))
    max(targets, key=lambda t: t["target"])["tuner"] = True
    json.dump(targets, open(out_path, "w"), indent=0)
    print(f"{H} holds, total {int(ints.sum())} (target {total}) -> {out_path}")
    for t in targets:
        print(f"  beat {t['b0']:7.2f}..{t['b1']:<7.2f} events {t['target']}{'  TUNER' if t.get('tuner') else ''}")

if __name__ == "__main__":
    main()
