# End-to-end check that a packaged release actually carries the tick fixes.
#
# For every chart in sources/repairs.json, three numbers must agree:
#   1. the .ssc in simfiles/ run through piu-annotate's own converter (tick_verify's math)
#   2. the "Hold ticks" metadata in the release's chart JSON
#   3. the judged note count from the certified video (sources/census-final.json)
# A disagreement means the release does not ship what this repo says is true.
#
#   python -X utf8 tools/verify_release.py <release_name> [--old <release_name>]
import json
import os
import re
import sys

sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
from piu_annotate.formats.sscfile import StepchartSSC                             # noqa: E402
from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANN = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs"

def block_of(key):
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9_]+?)?)_((?:HALFDOUBLE_)?(?:ARCADE|SHORTCUT|REMIX|FULLSONG))$", key)
    return f"{m.group(1).replace('_', ' ')}_{m.group(2)}"

def shipped_ticks(release, key):
    """Hold-tick total the release's chart JSON carries, or None when absent."""
    p = os.path.join(ANN, release, "lgbm-120524", "chart-json", key + ".json")
    if not os.path.isfile(p):
        return None
    meta = json.load(open(p, encoding="utf-8"))[2]
    return sum(int(round(t[2])) for t in (meta.get("Hold ticks") or []))

def main():
    release = sys.argv[1]
    old = sys.argv[sys.argv.index("--old") + 1] if "--old" in sys.argv else None
    repairs = json.load(open(os.path.join(ROOT, "sources", "repairs.json"), encoding="utf-8"))

    rows, bad, missing = [], 0, 0
    for r in repairs:
        path = os.path.join(ROOT, "simfiles", r["ssc_rel"].replace("/", os.sep))
        sc = StepchartSSC.from_song_ssc_file(path, block_of(r["key"]))
        df, ht, _ = stepchart_ssc_to_chartstruct(sc)
        taps = int(df["Line"].str.contains("1", regex=False).sum())
        file_ticks = sum(round(t[2]) for t in ht)
        rel_ticks = shipped_ticks(release, r["key"])
        old_ticks = shipped_ticks(old, r["key"]) if old else None
        if rel_ticks is None:
            missing += 1
        agree = rel_ticks == file_ticks and taps + file_ticks == r["judged"]
        if not agree:
            bad += 1
        rows.append((agree, r["chart"], taps, file_ticks, rel_ticks, old_ticks, r["judged"]))

    print(f"{'':2}{'chart':50} {'taps':>5} {'file':>6} {'shipped':>8} {'was':>7} {'judged':>7}")
    for agree, name, taps, ft, rt, ot, j in rows:
        print(f"{'OK' if agree else '!!':2}{name[:50]:50} {taps:5d} {ft:6d} {str(rt):>8} {str(ot):>7} {j:7d}")
    print(f"\n{len(rows) - bad}/{len(rows)} charts agree (file == shipped == judged)")
    if missing:
        print(f"{missing} charts absent from release {release}")
    if old:
        moved = sum(1 for r in rows if r[5] is not None and r[5] != r[4])
        print(f"{moved}/{len(rows)} hold-tick totals changed vs {old}")
    return 1 if (bad or missing) else 0

if __name__ == "__main__":
    sys.exit(main())
