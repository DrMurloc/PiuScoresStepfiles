# Price a chart's hold regions by closure and author them, for charts whose holds were just
# added from footage: taps come from the regenerated chartstruct, every hold region in the
# file becomes a target, and judged - taps is spread over them by length (one region gets
# it all when there is one). Then author_ticks + tick_verify. With --burst <beat>, rewrite
# the block's schedule afterwards as a tail burst - rate 2 up to that beat, then a high rate
# tuned against the converter to land exactly - for finales the counter shows firing in
# the last stretch of the hold (Slam: 009 -> 463 in 0.2s).
#
#   python -X utf8 tools/finale_ticks.py "<chart>" [--burst <beat>]
import csv
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe"
CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def run(args):
    return subprocess.run([PY, "-X", "utf8"] + args, cwd=ROOT, capture_output=True, text=True).stdout

def main():
    chart = sys.argv[1]
    burst = float(sys.argv[sys.argv.index("--burst") + 1]) if "--burst" in sys.argv else None
    pre = int(sys.argv[sys.argv.index("--pre") + 1]) if "--pre" in sys.argv else 2    # rate before the burst
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    key, ssc_rel = smap[chart]["key"], smap[chart]["ssc_rel"]
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    judged = next(int(e[(e["charts"][chart])["side"]]["judged"]) for e in cert.values() if chart in (e.get("charts") or {}))
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9]+)*?)_(ARCADE|SHORTCUT|REMIX|FULLSONG)$", key)   # desc words joined by spaces, suffix after the last underscore
    block = f"{m.group(1).replace('_', ' ')}_{m.group(2)}"
    ssc = os.path.join(ROOT, "simfiles", ssc_rel)
    rows = list(csv.DictReader(open(os.path.join(CS_DIR, key + ".csv"), encoding="utf-8")))
    taps = sum(1 for r in rows if "1" in r["Line"])
    holds, op = [], {}
    for r in rows:
        t, b = float(r["Time"]), float(r["Beat"])
        L = r["Line"].lstrip("`")
        for i, ch in enumerate(L):
            if ch == "2":
                op[i] = (t, b)
            if ch == "3" and i in op:
                (t0, b0) = op.pop(i)
                holds.append([t0, t, b0, b])
    holds.sort()
    regs = []
    for t0, t1, b0, b1 in holds:
        if regs and t0 <= regs[-1][1] + 1e-6:
            regs[-1][1] = max(regs[-1][1], t1)
            regs[-1][3] = max(regs[-1][3], b1)
        else:
            regs.append([t0, t1, b0, b1])
    owed = judged - taps
    if not regs:
        raise SystemExit(f"{chart}: no holds in the file - nothing to price")
    L = sum(r[1] - r[0] for r in regs)
    targets = [dict(t0=r[0], t1=r[1], b0=r[2], b1=r[3], target=int(owed * (r[1] - r[0]) / L)) for r in regs]
    big = max(targets, key=lambda t: t["t1"] - t["t0"])
    big["target"] += owed - sum(t["target"] for t in targets)
    big["tuner"] = True
    tpath = os.path.join(ROOT, "work", f"{key}-finale-targets.json")
    json.dump(targets, open(tpath, "w"))
    print(f"{chart}: taps {taps}, judged {judged}, owed {owed} over {len(regs)} hold region(s): "
          + "  ".join(f"b{t['b0']:.3f}-{t['b1']:.3f}:{t['target']}" for t in targets))
    out = run(["tools/author_ticks.py", ssc, block, tpath, str(judged)])
    print("  " + "\n  ".join(l for l in out.splitlines() if l.startswith(("CONVERGED", "DID NOT", "  authored", "  regions", "    region"))))
    if "CONVERGED" not in out:
        return
    if burst is not None:
        text = open(ssc, encoding="utf-8", newline="").read()
        sections = text.split("#NOTEDATA:;")
        code = block.rsplit("_", 1)[0]
        i = next(k for k in range(1, len(sections)) if re.search(rf"#DESCRIPTION:{re.escape(code)};", sections[k]))
        b0, b1 = big["b0"], big["b1"]
        def write(rate):
            tc = f"0.000000=4,\n{b0:.6f}={pre},\n{burst:.6f}={rate},\n{b1:.6f}=4"
            sec = re.sub(r"#TICKCOUNTS:.*?;", f"#TICKCOUNTS:{tc};", sections[i], count=1, flags=re.S)
            open(ssc, "w", encoding="utf-8", newline="").write("#NOTEDATA:;".join(sections[:i] + [sec] + sections[i + 1:]))
        def implied():
            o = run(["tools/tick_verify.py", chart, str(judged)])
            mm = re.search(r"implied (\d+)", o)
            return int(mm.group(1)) if mm else None
        span = b1 - burst
        lo, hi = 1, int(2 * big["target"] / max(span, 0.05)) + 50
        v = None
        for _ in range(24):
            rate = (lo + hi) // 2
            write(rate)
            v = implied()
            if v == judged or lo >= hi:
                break
            if v < judged:
                lo = rate + 1
            else:
                hi = rate - 1
        print(f"  tail burst: rate {pre} from b{b0:.3f}, {rate} from b{burst:.3f} to b{b1:.3f} -> implied {v}")
    out = run(["tools/tick_verify.py", chart, str(judged)])
    print("  " + " ".join(l for l in out.splitlines() if "implied" in l))

if __name__ == "__main__":
    main()
