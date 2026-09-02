# Phantom hunt on a (near-)perfect play: taps the file has that the game never judged.
# Uses only raw high-confidence counter reads (no run repair, which is where junk gets in):
# at each read, the taps judged at least 150ms earlier must already be in the counter, so
#   n_lo(t) - counter(t) <= 0 always, and == 0 through a stretch with no misses;
# a phantom makes it +1 for good from the phantom's time on (a miss makes it drop by the
# reset instead). Prints the persistent segments and, with --fit, first searches the offset
# that zeroes the most reads (on an exact counter the true offset is the only one that does).
#
#   python -X utf8 tools/phantom_scan.py "<chart>" <offset>|--fit [--conf 0.85] [--tail]
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    chart = sys.argv[1]
    conf = float(sys.argv[sys.argv.index("--conf") + 1]) if "--conf" in sys.argv else 0.85
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    vid, e = next((v, e) for v, e in cert.items() if chart in (e.get("charts") or {}))
    side = e["charts"][chart]["side"]
    s = e[side]
    judged, mc = int(s["judged"]), int(s["maxcombo"])
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    ncols = 10 if chart.split()[-1][0] == "D" else 5
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    rows, _, beat_at = R.chartstruct(smap[chart]["key"], ncols)
    taps = sorted({float(r["Time"]) for r in rows if "1" in r["Line"]})
    path = os.path.join(ROOT, "work", "combo", f"{vid}.{band}.jsonl")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "work", "combo", f"{vid}.C.jsonl")
    reads = [(t, v) for t, v, c in (json.loads(l) for l in open(path, encoding="utf-8")) if v is not None and c >= conf and v <= mc]
    print(f"{chart}: {vid} band {band}, judged {judged}, maxcombo {mc}, file taps {len(taps)} ({len(taps) - judged:+d}), {len(reads)} reads at conf>={conf}")

    def diffs(a):
        return [(t, v, bisect.bisect_right(taps, t - a - 0.15) - v) for t, v in reads]

    if sys.argv[2] == "--fit":
        # --until <video s>: fit only on reads before the first hold, where the counter must
        # equal the tap count exactly (holds make the counter run ahead and spoil the fit)
        until = float(sys.argv[sys.argv.index("--until") + 1]) if "--until" in sys.argv else 1e9
        best = max(((sum(1 for t, _, d in diffs(a / 100) if d == 0 and t <= until), a / 100) for a in range(0, 6000, 5)))
        a = best[1]
        print(f"  offset fit: a = {a:.2f} zeroes {best[0]} of {len(reads)} reads")
    else:
        a = float(sys.argv[2])
    seg, cur = [], None
    for t, v, d in diffs(a):
        if cur and cur[2] == d:
            cur[1] = t
        else:
            if cur:
                seg.append(cur)
            cur = [t, t, d]
    seg.append(cur)
    print(f"  (n_lo - counter) segments lasting >= 0.3s at a = {a:.2f}:")
    for t0, t1, d in seg:
        if t1 - t0 >= 0.3:
            print(f"    {t0:7.2f}-{t1:7.2f}  {d:+d}")
    if "--tail" in sys.argv:
        last, out = None, []
        for t, v in reads:
            if v != last:
                out.append(f"{t:.2f}:{v}")
                last = v
        print("  counter changes (last 40):", "  ".join(out[-40:]))
        print("  last file taps (video):", " ".join(f"{t + a:.2f}" for t in taps[-12:]))

if __name__ == "__main__":
    main()
