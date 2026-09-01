# Re-audit a shipped repair without trusting how it was made.
#
# Independently re-derives the offset with the two-sided fitter, screens the note grid, and
# then asks the question that actually matters: does the tick schedule now in the file agree,
# hold by hold, with what the combo curve says happened there? A repair can hit the right
# TOTAL with a wrong interior, and the total is already guaranteed by tick_verify - so this
# checks the distribution instead.
#
# Reports per chart:
#   fit2      independently re-derived offset, with its window count and error
#   grid      grid_screen verdict at that offset
#   cover     observed ticks / ticks owed
#   worst     the hold region where the file and the curve disagree most (ticks)
#
#   python -X utf8 tools/audit_repair.py [chartName ...]      (default: every repaired chart)
import bisect
import csv
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
from piu_annotate.formats.sscfile import StepchartSSC                             # noqa: E402
from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe"
CS_DIR = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs\p2-082626"

def block_of(key):
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9_]+?)?)_((?:HALFDOUBLE_)?(?:ARCADE|SHORTCUT|REMIX|FULLSONG))$", key)
    return f"{m.group(1).replace('_', ' ')}_{m.group(2)}"

def band_for(vid, chart):
    """The band this CHART was read on, not merely whichever anchors file exists first.
    A split-screen video carries two different charts (Hyperion SC S16 on 1P and S20 on 2P),
    so picking by glob silently audits one chart against the other's curve."""
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    side = ((cert.get(vid) or {}).get("charts") or {}).get(chart, {}).get("side")
    want = {"1p": "L", "2p": "R"}.get(side)
    have = [os.path.basename(p).split(".")[-3]
            for p in glob.glob(os.path.join(ROOT, "work", "combo", f"{vid}.*.anchors.json"))]
    if want and want in have:
        return want
    if "C" in have:
        return "C"
    return have[0] if have else None

def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout

def audit(r):
    vid = r["video"].split("/")[-1]
    band = band_for(vid, r["chart"])
    if band is None:
        return dict(chart=r["chart"], note="no anchors banked - cannot re-audit")

    out = run([PY, "-X", "utf8", "tools/fit2.py", vid, band, r["key"]])
    m = re.search(r"a = ([\d.]+), mean tap-window error ([\d.]+) over (\d+) windows", out)
    if not m:
        return dict(chart=r["chart"], note="fit2 produced no fit")
    a, err, nwin = float(m.group(1)), float(m.group(2)), int(m.group(3))

    grid = run([PY, "-X", "utf8", "tools/grid_screen.py", r["chart"], vid, band, f"{a}"])
    gm = re.search(r"=>\s+(GRID [A-Z ]+)", grid)
    verdict = gm.group(1).strip() if gm else "?"

    # the file's own per-hold ticks, straight from the converter
    path = os.path.join(ROOT, "simfiles", r["ssc_rel"].replace("/", os.sep))
    sc = StepchartSSC.from_song_ssc_file(path, block_of(r["key"]))
    df, holdticks, _ = stepchart_ssc_to_chartstruct(sc)

    # what the curve says happened over each of those spans
    anchors = json.load(open(os.path.join(ROOT, "work", "combo", f"{vid}.{band}.anchors.json"), encoding="utf-8"))
    mids = sorted(((t0 + t1) / 2 - a, c) for t0, t1, c in anchors)
    mx, my = [p[0] for p in mids], [p[1] for p in mids]
    def cum_at(ct):
        i = bisect.bisect_left(mx, ct)
        if i <= 0: return my[0]
        if i >= len(mx): return my[-1]
        t0, t1, c0, c1 = mx[i-1], mx[i], my[i-1], my[i]
        return c0 if t1 == t0 else c0 + (c1 - c0) * (ct - t0) / (t1 - t0)
    rows = list(csv.DictReader(open(os.path.join(CS_DIR, r["key"] + ".csv"), encoding="utf-8")))
    taps = [float(x["Time"]) for x in rows if "1" in x["Line"]]
    def tb(ct): return bisect.bisect_right(taps, ct)

    worst, worst_at = 0, None
    covered = 0
    for st, en, tk in holdticks:
        # Only compare a hold the curve actually resolves. Interpolating cum across a 0.1s
        # span between anchors seconds apart invents a number, so require anchors INSIDE the
        # span (and at both ends) before believing the comparison - the same guard
        # hold_observe needs for the same reason.
        inside = sum(1 for x in mx if st <= x <= en)
        if inside < 2 or not (mx[0] <= st and en <= mx[-1]):
            continue
        obs = cum_at(en) - cum_at(st) - (tb(en) - tb(st))
        covered += 1
        d = round(tk) - round(obs)
        if abs(d) > abs(worst):
            worst, worst_at = d, (round(st, 1), round(en, 1))
    return dict(chart=r["chart"], band=band, a=a, err=err, nwin=nwin, verdict=verdict,
                holds=len(holdticks), compared=covered, worst=worst, at=worst_at)

def main():
    rep = json.load(open(os.path.join(ROOT, "sources", "repairs.json"), encoding="utf-8"))
    want = set(sys.argv[1:])
    todo = [r for r in rep if not want or r["chart"] in want]
    print(f"{'chart':46} {'band':4} {'fit2 a':>7} {'err':>5} {'win':>4} {'grid':<22} {'cmp':>4} {'worst':>6} where")
    for r in todo:
        d = audit(r)
        if "note" in d:
            print(f"{d['chart'][:46]:46} {d['note']}")
            continue
        print(f"{d['chart'][:46]:46} {d['band']:4} {d['a']:7.2f} {d['err']:5.2f} {d['nwin']:4d} "
              f"{d['verdict'][:22]:<22} {d['compared']:>3}/{d['holds']:<3} {d['worst']:+6d} {d['at']}")

if __name__ == "__main__":
    main()
