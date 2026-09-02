# Build a chart's combo anchors automatically from its scan and result screen, then screen
# the grid at a given offset. Resets are drops that PERSIST (the next two reads within 1.5s
# stay below the run's peak), read peaks are scaled to close on P+G, and a read that would
# exceed its own run's peak is dropped. Rough by design: it exists so the grid verdict for a
# chart whose holds were just added from footage does not wait on hand forensics. If the read
# peaks sum ABOVE P+G, a "reset" is a misread - it says so and stops; read the frames.
#
#   python -X utf8 tools/auto_anchors.py "<chart>" <offset>
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from curve_tools import build_anchors  # noqa: E402
import run_structure  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe"

def main():
    chart, a = sys.argv[1], float(sys.argv[2])
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    vid, e = next((v, e) for v, e in cert.items() if chart in (e.get("charts") or {}))
    side = e["charts"][chart]["side"]
    s = e[side]
    judged, mc = int(s["judged"]), int(s["maxcombo"])
    pg = int(s["perfect"]) + int(s["great"])
    resets = int(s["bad"]) + int(s["miss"])
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    key = smap[chart]["key"]
    path = os.path.join(ROOT, "work", "combo", f"{vid}.{band}.jsonl")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "work", "combo", f"{vid}.C.jsonl")
    pts = sorted((t, v) for t, v, c in (json.loads(l) for l in open(path, encoding="utf-8")) if v is not None and c >= 0.6 and v <= mc)
    # reads before the chart starts are title-card junk (We will meet again read "5" at 2.0s
    # on a PUMP TO NX splash); the chart's first row at the offset is the earliest real one
    import csv
    cs_dir = "C:/Users/jonec/repos/piu-annotate/artifacts/chartstructs/p2-082626"
    first_row = float(next(csv.DictReader(open(os.path.join(cs_dir, key + ".csv"), encoding="utf-8")))["Time"])
    pts = [(t, v) for t, v in pts if t >= a + first_row - 0.5]
    # the run structure by closure: every low restart is a candidate reset, and the subset of
    # at most B+M of them whose peaks close on P+G wins (a candidate not chosen is a rollover
    # with the hundreds covered, and the run continues through it)
    solved = run_structure.solve(pts, resets, pg, mc)
    if solved is None:
        print(f"{chart}: {vid} band {band}; P+G {pg}, maxcombo {mc}, resets {resets}: no run structure closes on P+G - frames needed, stopping")
        return
    runs, peaks, score = solved
    tail_rest = runs[-1][-1][1]
    print(f"{chart}: {vid} band {band}; P+G {pg}, maxcombo {mc}, resets {resets}; {len(runs)} runs, peaks sum {sum(peaks)} (off by {score})"
          f" (last run rests at {tail_rest}{' = maxcombo' if tail_rest == mc else ''})")
    print("  runs (start-end: first->peak): " + "  ".join(f"{r[0][0]:.1f}-{r[-1][0]:.1f}:{r[0][1]}->{max(x[1] for x in r)}" for r in runs))
    # scale the inexact peaks to close on P+G; a final run resting at maxcombo is exact
    exact = [False] * len(peaks)
    if tail_rest == mc:
        exact[-1] = True
    inexact = sum(p for p, ex in zip(peaks, exact) if not ex)
    fixed = sum(p for p, ex in zip(peaks, exact) if ex)
    scale = (pg - fixed) / inexact if inexact else 1.0
    scaled = [p if ex else round(p * scale) for p, ex in zip(peaks, exact)]
    idx = max((i for i, ex in enumerate(exact) if not ex), default=len(scaled) - 1)
    scaled[idx] += pg - sum(scaled)
    print(f"  peaks {peaks} -> scaled {scaled} (x{scale:.3f})")
    off, cum = [(-1, 0)], 0
    for r, pk in zip(runs, scaled):
        if r is not runs[0]:
            prev_end = runs[runs.index(r) - 1][-1][0]
            off.append(((prev_end + r[0][0]) / 2, cum))
        cum += pk
    off.sort(reverse=True)
    # cap each read at its own run's peak, then build
    capped = []
    for r, pk in zip(runs, scaled):
        capped += [(t, min(v, pk)) for t, v in r]
    anchors = build_anchors(sorted(capped), off, pg)
    out = os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json")
    json.dump(anchors, open(out, "w"))
    print(f"  {len(anchors)} anchors -> {out}")
    al = subprocess.run([PY, "tools/align_schedule.py", vid, key, str(judged), band, str(a)], cwd=ROOT, capture_output=True, text=True).stdout
    print("  " + " | ".join(l.strip() for l in al.splitlines() if "violation" in l or "total obs" in l))
    gs = subprocess.run([PY, "-X", "utf8", "tools/grid_screen.py", chart, vid, band, str(a)], cwd=ROOT, capture_output=True, text=True).stdout
    print("  " + " ".join(l.strip() for l in gs.splitlines() if "worst slack" in l)[:120])

if __name__ == "__main__":
    main()
