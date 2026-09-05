# Where does the counter outrun the file's taps? Structure-free: between consecutive
# reliable reads inside one run (no drop, gap <= 1.5s) the counter's increase minus the file's
# taps in that span is tick accrual (or, negative, taps the game did not judge). Clusters of
# excess are hold ticks the file has no hold for; the receptors then say which column.
#
#   python -X utf8 tools/excess_scan.py "<chart>" <offset> [--conf 0.8] [--min 2]
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    chart, a = sys.argv[1], float(sys.argv[2])
    conf = float(sys.argv[sys.argv.index("--conf") + 1]) if "--conf" in sys.argv else 0.8
    mn = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 2
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    vid, e = next((v, e) for v, e in cert.items() if chart in (e.get("charts") or {}))
    side = e["charts"][chart].get("side") or "1p"
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
    # the counter is BLANK below 4, so a sub-4 read is the reader inventing a number from an
    # empty box. One of those ends a segment and charges the whole climb after it as accrual:
    # a lone "3" invented a 37-tick mid-chart hold on Bee S17 and parked the chart for days.
    allr = [(t, v) for t, v, c in (json.loads(l) for l in open(path, encoding="utf-8")) if v is not None and c >= conf and 4 <= v <= mc]
    # a value has to PERSIST (seen again within the next two reads) - single-frame reads are
    # where the covered digits and the blank-counter "0/1" live (WotW D16: "1" then 131 = +130)
    reads = [(t, v) for i, (t, v) in enumerate(allr) if any(v2 == v for _, v2 in allr[i + 1:i + 3])]
    # collapse repeats: keep the first time each value appears in a monotone stretch
    print(f"{chart}: {vid} band {band}, offset {a}, judged {judged}, file taps {len(taps)}, owed {judged - len(taps)}")
    total_ex = 0
    clusters, cur = [], None
    prev = None
    for t, v in reads:
        if prev is None:
            prev = (t, v)
            continue
        t0, v0 = prev
        if v < v0 or t - t0 > 1.5:
            prev = (t, v)
            if cur:
                clusters.append(cur)
                cur = None
            continue
        if v == v0:
            continue
        n = bisect.bisect_right(taps, t - a - 0.15) - bisect.bisect_right(taps, t0 - a - 0.15)
        ex = (v - v0) - n
        if ex >= 1:
            if cur and t0 - cur[1] <= 0.6:
                cur[1] = t
                cur[2] += ex
            else:
                if cur:
                    clusters.append(cur)
                cur = [t0, t, ex]
        elif ex <= -1 and cur:
            cur[2] += ex
        prev = (t, v)
    if cur:
        clusters.append(cur)
    for t0, t1, ex in clusters:
        if ex >= mn:
            total_ex += ex
            print(f"  video {t0:7.2f}-{t1:7.2f}  chart {t0 - a:7.2f}-{t1 - a:7.2f}  beats {beat_at(t0 - a):8.3f}-{beat_at(t1 - a):8.3f}  excess {ex:+d}")
    print(f"  clustered excess (>= {mn}): {total_ex}")

if __name__ == "__main__":
    main()
