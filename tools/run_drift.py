# Does the file's tap grid match the game's, WITHOUT reconstructing the run structure?
#
# grid_screen answers that from a cumulative curve, which needs every reset placed correctly.
# On a play with many resets - or a video where the rails cross the counter and the reads go
# to junk - that curve cannot be built, and its verdict reports the reconstruction's failure
# rather than the file's. Mr. Larpus D16 screened as "MISMATCH, -116, the file carries ~116
# taps the game never judged" on a play with only 11 misses, which is arithmetically impossible.
#
# This measures the same thing locally and needs no structure: inside one rising stretch of the
# counter the delta must equal the file's tap rows over the same span (plus that stretch's hold
# ticks). A file carrying taps the game does not judge shows a persistent NEGATIVE drift; a run
# holding a hold the file lacks shows a large positive one.
#
# Read the small numbers as noise, not evidence: a covered hundred reads as +10, and each miss
# costs one.
#
#   python -X utf8 tools/run_drift.py "<chart>" <offset> [--conf 0.85] [--gap 2.0]
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    chart, a = sys.argv[1], float(sys.argv[2])
    conf = float(sys.argv[sys.argv.index("--conf") + 1]) if "--conf" in sys.argv else 0.85
    gap = float(sys.argv[sys.argv.index("--gap") + 1]) if "--gap" in sys.argv else 2.0
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    vid, e = next((v, e) for v, e in cert.items() if chart in (e.get("charts") or {}))
    side = e["charts"][chart].get("side") or "1p"
    s = e[side]
    judged, mc = int(s["judged"]), int(s["maxcombo"])
    miss, bad = int(s["miss"]), int(s["bad"])
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    ncols = 10 if chart.split()[-1][0] == "D" else 5
    rows, _, _ = R.chartstruct(smap[chart]["key"], ncols)
    taps = sorted(float(r["Time"]) for r in rows if "1" in r["Line"])
    holds = sorted(float(r["Time"]) for r in rows if "2" in r["Line"])
    path = os.path.join(ROOT, "work", "combo", f"{vid}.{band}.jsonl")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "work", "combo", f"{vid}.C.jsonl")
    # the counter is BLANK below 4, so any read under 4 is the reader inventing a number from
    # an empty box - and one of those opens a bogus run that double-counts the climb before it
    good = [(t, v) for t, v, c in (json.loads(l) for l in open(path, encoding="utf-8"))
            if v is not None and c >= conf and 4 <= v <= mc]
    pers = [(t, v) for i, (t, v) in enumerate(good) if any(v2 == v for _, v2 in good[i + 1:i + 3])]
    # A drop only starts a new run if what FOLLOWS continues from it. A lone low read is junk
    # and would otherwise open a bogus run whose delta counts the whole previous climb again:
    # one spurious 0 in Vook D15 turned a +38 stretch into +88.
    runs, cur = [], []
    for i, (t, v) in enumerate(pers):
        if cur and (v < cur[-1][1] or t - cur[-1][0] > gap):
            nxt = pers[i + 1][1] if i + 1 < len(pers) else None
            confirmed = nxt is None or nxt <= v + 12
            if not confirmed:
                continue
            runs.append(cur)
            cur = []
        cur.append((t, v))
    runs.append(cur)
    print(f"{chart}: {vid} band {band}, judged {judged}, file taps {len(taps)}, file holds {len(holds)}, "
          f"play has {miss} miss / {bad} bad")
    print("  run (video)      counter   file taps   drift   holds in span")
    tot_c = tot_t = 0
    for r in runs:
        if len(r) < 5 or r[-1][1] - r[0][1] < 5:
            continue
        dc = r[-1][1] - r[0][1]
        lo, hi = r[0][0] - a - 0.12, r[-1][0] - a - 0.12
        dt = bisect.bisect_right(taps, hi) - bisect.bisect_right(taps, lo)
        nh = bisect.bisect_right(holds, hi) - bisect.bisect_right(holds, lo)
        print(f"  {r[0][0]:6.1f}-{r[-1][0]:6.1f}   +{dc:5d}      +{dt:5d}   {dc - dt:+5d}   {nh if nh else '-'}")
        if not nh:
            tot_c += dc
            tot_t += dt
    print(f"  across runs with NO hold: counter +{tot_c}, taps +{tot_t}, drift {tot_c - tot_t:+d}")
    print(f"  a file short of taps drifts POSITIVE; a file carrying taps the game does not judge "
          f"drifts NEGATIVE past -{miss} (its misses).")

if __name__ == "__main__":
    main()
