# Turn window targets (window_targets.py) into per-region targets for author_ticks. Holds that
# overlap or share a tail are merged into one region FIRST, globally - a chain of overlapping
# holds (Desaparecer's 26.9-31.5s ladder) is one converter span, and merging it per window
# left regions the converter's segments never mapped to, so one authored 0 and the tuner ate
# its ticks. Each window's ticks are then split over the regions inside it by overlap length,
# so a region spanning two windows collects from both. author_ticks converges far more
# reliably on regions than on multi-hold windows, whose integer ticks-per-beat grid can cycle.
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
    regs = []
    for h0, h1 in holds:
        if regs and h0 <= regs[-1][1] + 1e-6: regs[-1][1] = max(regs[-1][1], h1)
        else: regs.append([h0, h1])
    def beat_at(ct):
        i = bisect.bisect_left(times, ct)
        if i <= 0: return beats[0] + (ct - times[0])
        if i >= len(times): return beats[-1] + (ct - times[-1])
        t0, t1, b0, b1 = times[i-1], times[i], beats[i-1], beats[i]
        return b0 if t1 == t0 else b0 + (b1 - b0) * (ct - t0) / (t1 - t0)
    wins = json.load(open(win_path))
    share = [0.0] * len(regs)
    tuner_regs = set()
    for w in wins:
        ov = [(max(0.0, min(r1, w["t1"]) - max(r0, w["t0"])), i) for i, (r0, r1) in enumerate(regs)]
        L = sum(o for o, _ in ov)
        if L <= 0:
            print(f"  WARNING window {w['t0']:.2f}-{w['t1']:.2f} ({w['target']}) covers no hold - ticks dropped"); continue
        for o, i in ov:
            if o > 0:
                share[i] += w["target"] * o / L
                if w.get("tuner"): tuner_regs.add(i)
    out = []
    for (r0, r1), s in zip(regs, share):
        out.append(dict(t0=r0, t1=r1, b0=beat_at(r0), b1=beat_at(r1), raw=s, target=int(s)))
    rem = round(sum(o["raw"] for o in out)) - sum(o["target"] for o in out)
    for o in sorted(out, key=lambda o: -(o["raw"] - o["target"]))[:max(rem, 0)]: o["target"] += 1
    for o in out: o.pop("raw")
    cands = [out[i] for i in sorted(tuner_regs)] or out
    big = max(cands, key=lambda o: o["target"]); big["tuner"] = True
    json.dump(out, open(out_path, "w"), indent=0)
    print(f"{len(out)} regions from {len(holds)} holds -> {out_path}; total {sum(o['target'] for o in out)} "
          f"(windows {sum(w['target'] for w in wins)}); tuner {big['t0']:.1f}-{big['t1']:.1f}:{big['target']}")

if __name__ == "__main__":
    main()
