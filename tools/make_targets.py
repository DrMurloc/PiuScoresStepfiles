# Builds an author_ticks targets file from a hold_observe holds.json: pinned
# observations become targets (negatives clamped to 0 — boundary noise), the closure
# remainder distributes over unpinned holds by beat-weight, and the largest target
# becomes the tuner.
#   python tools/make_targets.py <videoId> <out.json>
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    vid, out = sys.argv[1], sys.argv[2]
    h = json.load(open(os.path.join(ROOT, "work", "combo", vid + ".holds.json")))
    targets = [dict(b0=p["b0"], b1=p["b1"], t0=p["t0"], t1=p["t1"], target=max(0, p["events"]))
               for p in h["pinned"]]
    un = h["unpinned"]
    rem = h["remainder"] + sum(p["events"] for p in h["pinned"] if p["events"] < 0)
    if un:
        wts = [u["b1"] - u["b0"] for u in un]
        alloc = [round(rem * w / sum(wts)) for w in wts]
        alloc[0] += rem - sum(alloc)
        for u, a in zip(un, alloc):
            targets.append(dict(b0=u["b0"], b1=u["b1"], t0=u["t0"], t1=u["t1"], target=max(0, a)))
    targets.sort(key=lambda t: t["b0"])
    max(targets, key=lambda t: t["target"])["tuner"] = True
    json.dump(targets, open(out, "w"), indent=0)
    print(f"{len(targets)} targets -> {out}; remainder {rem} over {len(un)} unpinned; "
          f"tuner {max(t['target'] for t in targets)}")

if __name__ == "__main__":
    main()
