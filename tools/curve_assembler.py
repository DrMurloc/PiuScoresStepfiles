# Assembles the combo curve from a combo_reader scan: ultra-strict anchor extraction
# (>=3-frame persistence, conf >= 0.8) chained by a rate-capped DP that allows
# resets, weighted toward value continuity so leading-prefix truncation shadows
# ("5" read from "5xx") lose to the real curve.
#
#   python tools/curve_assembler.py <videoId> [expectedPG] [expectedMaxCombo]
#
# Known limits (measured on Tales of Pumpnia D21 — worst case: RPG-damage-number
# BGA + ~14 ticks/s): fast cluttered stretches go anchor-sparse and truncation
# chains can win locally. The planned fix is chart-informed tracking: with the
# .ssc schedule aligned to video time the expected rate at every moment is known,
# and shadows cannot follow it. Global closure: sum of run peaks == certified P+G.
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RATE = 25.0

def assemble(vid):
    pts = [json.loads(l) for l in open(os.path.join(ROOT, "work", "combo", vid + ".jsonl"), encoding="utf-8")]
    vals = [(t, v, c) for t, v, c in pts if v is not None]
    cands = []
    i = 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j+1][1] == vals[i][1] and vals[j+1][0] - vals[j][0] < 0.1:
            j += 1
        if j - i + 1 >= 3 and min(c for _, _, c in vals[i:j+1]) >= 0.8:
            cands.append((vals[i][0], vals[j][0], vals[i][1]))
        i = j + 1
    n = len(cands)
    best = [1.0] * n
    prev = [-1] * n
    for k in range(n):
        for m in range(k):
            t0, tl0, v0 = cands[m]
            t1, _, v1 = cands[k]
            dt = t1 - tl0
            if dt <= 0:
                continue
            mono = v1 >= v0 and v1 - v0 <= RATE * dt + 3
            reset = v1 <= 8 and v0 > 20 and dt > 0.3
            if not (mono or reset):
                continue
            gain = 1.0 + (0.002 * min(v1 - v0, 60) if mono else -2.0)
            if best[m] + gain > best[k]:
                best[k] = best[m] + gain
                prev[k] = m
    k = max(range(n), key=lambda i: best[i])
    chain = []
    while k != -1:
        chain.append(cands[k])
        k = prev[k]
    chain.reverse()
    runs, cur = [], []
    for a in chain:
        if cur and a[2] < cur[-1][2] - 2:
            runs.append(cur)
            cur = []
        cur.append(a)
    runs.append(cur)
    return chain, runs

if __name__ == "__main__":
    vid = sys.argv[1]
    chain, runs = assemble(vid)
    tot = 0
    for r in runs:
        tot += r[-1][2]
        print(f"  {r[0][0]:7.2f}s -> {r[-1][1]:7.2f}s  combo {r[0][2]}..{r[-1][2]}  anchors {len(r)}")
    print(f"runs {len(runs)}, sum of run-final {tot}", sys.argv[2:] and f"(target P+G {sys.argv[2]})" or "")
    out = os.path.join(ROOT, "work", "combo", vid + ".anchors.json")
    json.dump([[round(a[0], 3), round(a[1], 3), a[2]] for a in chain], open(out, "w"))
    print("anchors ->", out)
