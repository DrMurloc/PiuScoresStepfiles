# Rough-assemble a chart's cumulative curve and ask grid_screen whether a tick repair
# is even possible, so effort goes to charts that can actually be fixed.
#
# The assembly here is deliberately crude: observed run peaks in order, the closure
# remainder spread evenly over the blind gaps, final segment locked so the curve ends
# at P+G. That is not good enough to author from, but it is good enough to tell a
# wrong note grid (slack goes and stays negative) from a merely under-observed one.
#
#   python -X utf8 tools/triage.py [chartName ...]
import bisect
import csv
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def assemble(vid, band, pg, mc):
    reads = [json.loads(l) for l in open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.jsonl"), encoding="utf-8")]
    pts = sorted((t, v) for t, v, c in reads if v is not None and c >= 0.8 and v <= mc)
    if len(pts) < 40:
        return None, None
    drops, prev = [], None
    for t, v in pts:
        if prev is not None and v < prev[1] - 2 and prev[1] > 12:
            drops.append((prev[0], prev[1], t))
        prev = (t, v)
    obs = [d[1] for d in drops]
    final = pts[-1][1]
    extra = pg - final - sum(obs)
    n = len(obs) + 1
    share = [extra // n] * n
    share[0] += extra - sum(share)
    offs, run = [], share[0]
    for i, pk in enumerate(obs):
        run += pk + share[i + 1]
        offs.append(run)
    bounds = [(d[2] + d[0]) / 2 for d in drops]
    OFF = list(zip(reversed(bounds), reversed(offs))) + [(-1, share[0])]
    def seg_off(t):
        for b, o in OFF:
            if t >= b:
                return o
        return share[0]
    segs = {}
    for t, v in pts:
        segs.setdefault(seg_off(t), []).append((t, v))
    anchors = []
    for off, pp in sorted(segs.items()):
        tails, tidx, parent = [], [], [-1] * len(pp)
        for i, (t, v) in enumerate(pp):
            j = bisect.bisect_right(tails, v)
            if j == len(tails):
                tails.append(v); tidx.append(i)
            else:
                tails[j] = v; tidx[j] = i
            parent[i] = tidx[j - 1] if j > 0 else -1
        chain, k = [], (tidx[-1] if tidx else -1)
        while k != -1:
            chain.append(pp[k]); k = parent[k]
        chain.reverse()
        cur = None
        for t, v in chain:
            cum = v + off
            if cum > pg:
                continue
            if cur and cur[2] == cum:
                cur[1] = t
            else:
                if cur:
                    anchors.append(cur)
                cur = [t, t, cum]
        if cur:
            anchors.append(cur)
    anchors.sort()
    return anchors, (len(obs), extra, pts[-1])

def main():
    census = {c["chart"]: c for c in json.load(open(os.path.join(ROOT, "sources", "census-final.json"), encoding="utf-8"))}
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    for name in sys.argv[1:]:
        c = census[name]
        vid = c["video"].split("/")[-1]
        ct = cert.get(vid) or {}
        side = (ct.get("charts") or {}).get(name, {}).get("side", "?")
        p = ct.get(side) or {}
        try:
            pg = int(p.get("perfect") or 0) + int(p.get("great") or 0)
            mc = int(p.get("maxcombo") or 0)
        except ValueError:
            print(f"{name[:40]:40} bad cert"); continue
        band = None
        for f in glob.glob(os.path.join(ROOT, "work", "combo", f"{vid}.*.jsonl")):
            b = os.path.basename(f).split(".")[-2]
            n = sum(1 for l in open(f, encoding="utf-8") if '"' not in l or True)
            band = b if band is None else band
        # pick the band with the most usable reads
        best = None
        for f in glob.glob(os.path.join(ROOT, "work", "combo", f"{vid}.*.jsonl")):
            b = os.path.basename(f).split(".")[-2]
            reads = [json.loads(l) for l in open(f, encoding="utf-8")]
            k = sum(1 for t, v, cf in reads if v is not None and cf >= 0.8 and v <= mc)
            if best is None or k > best[0]:
                best = (k, b)
        band = best[1]
        anchors, info = assemble(vid, band, pg, mc)
        if anchors is None:
            print(f"{name[:40]:40} too few reads"); continue
        json.dump(anchors, open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json"), "w"))
        # slack profile against the file's taps, using the end-anchored offset
        key = smap[name]["key"]
        rows = list(csv.DictReader(open(os.path.join(CS_DIR, key + ".csv"), encoding="utf-8")))
        last_ev = float(rows[-1]["Time"])
        a = anchors[-1][1] - last_ev
        taps = []
        for r in rows:
            if "1" in r["Line"]:
                taps.append(float(r["Time"]))
        def taps_before(ct):
            return bisect.bisect_right(taps, ct)
        zmin = {}
        for t0, _, cum in anchors:
            ct = t0 - a
            zmin.setdefault(int(ct // 15) * 15, []).append(cum - taps_before(ct))
        mins = [min(v) for _, v in sorted(zmin.items())]
        worst = min(mins + [0])
        head = max(1, len(mins) // 5)
        tail_worst = min(mins[head:]) if len(mins) > head else 0
        obsn, extra, tail = info
        # A negative remainder means the naive peaks already exceed P+G, so at least one
        # "reset" is a fused or truncated misread rather than a real break. The assembled
        # curve is then fiction and its slack says nothing -- these need frame forensics
        # to separate real resets from misreads before any verdict is possible.
        if extra < 0:
            verdict = "FORENSICS"
        elif tail_worst >= -35:
            verdict = "OK"
        else:
            verdict = "MISMATCH"
        print(f"{verdict:10} {name[:38]:38} a~{a:6.1f} runs {obsn+1:>3} unaccounted {extra:>5} "
              f"tail {tail[1]:>4}/{mc:<4} worst {worst:>5} past-head {tail_worst:>5}")

if __name__ == "__main__":
    main()
