# Turn window targets (window_targets.py) into per-hold targets for author_ticks: each window's
# ticks split over the holds inside it by hold length (largest remainder), holds that share a
# tail merged into one region. author_ticks converges far more reliably on per-hold regions than
# on multi-hold windows, whose integer ticks-per-beat grid can cycle without ever landing.
#
#   python tools/windows_to_holds.py <key> <windows.json> <out.json>
import bisect
import csv
import json
import os
import sys

CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def main():
    key, win_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    rows = list(csv.DictReader(open(os.path.join(CS_DIR, key + ".csv"), encoding="utf-8")))
    times = [float(r["Time"]) for r in rows]; beats = [float(r["Beat"]) for r in rows]
    holds, op = [], {}
    for r in rows:
        t = float(r["Time"]); L = r["Line"].lstrip("`")
        for i, ch in enumerate(L):
            if ch == "2": op[i] = t
            if ch == "3" and i in op: holds.append((op.pop(i), t))
    holds.sort()
    def beat_at(ct):
        i = bisect.bisect_left(times, ct)
        if i <= 0: return beats[0] + (ct - times[0])
        if i >= len(times): return beats[-1] + (ct - times[-1])
        t0, t1, b0, b1 = times[i-1], times[i], beats[i-1], beats[i]
        return b0 if t1 == t0 else b0 + (b1 - b0) * (ct - t0) / (t1 - t0)
    wins = json.load(open(win_path))
    out, tuner_win = [], None
    for w in wins:
        hs = [h for h in holds if h[0] >= w["t0"] - 1e-6 and h[1] <= w["t1"] + 1e-6]
        if not hs:
            print(f"  WARNING window {w['t0']:.2f}-{w['t1']:.2f} ({w['target']}) covers no hold - ticks dropped"); continue
        # holds sharing a tail (or overlapping) collapse into one region: the converter ticks them as one span
        regs = []
        for h0, h1 in hs:
            if regs and h0 <= regs[-1][1] + 1e-6: regs[-1][1] = max(regs[-1][1], h1)
            else: regs.append([h0, h1])
        L = sum(h1 - h0 for h0, h1 in regs); raw = [w["target"] * (h1 - h0) / L for h0, h1 in regs]
        tk = [int(x) for x in raw]; rem = w["target"] - sum(tk)
        for i in sorted(range(len(regs)), key=lambda i: -(raw[i] - tk[i]))[:rem]: tk[i] += 1
        made = [dict(t0=h0, t1=h1, target=n) for (h0, h1), n in zip(regs, tk)]
        if w.get("tuner"): tuner_win = made
        out += made
    for o in out: o["b0"], o["b1"] = beat_at(o["t0"]), beat_at(o["t1"])
    big = max(tuner_win or out, key=lambda o: o["target"]); big["tuner"] = True
    json.dump(out, open(out_path, "w"), indent=0)
    print(f"{len(out)} per-hold targets -> {out_path}; total {sum(o['target'] for o in out)} (windows {sum(w['target'] for w in wins)}); "
          f"tuner {big['t0']:.1f}-{big['t1']:.1f}:{big['target']}")

if __name__ == "__main__":
    main()
