# Regenerate sources/repairs.json from the files themselves.
#
# The manifest used to be a hand-kept list, which drifts the moment a repair lands.
# Instead, derive it: every chart in the census is a chart we know was wrong, so any
# census chart whose .ssc now runs through piu-annotate's converter to exactly its
# judged note count is one we repaired. That is a property of the tree, not a list
# someone remembered to update.
#
# Since the converter counts hold ticks by the tick lattice (2026-09-23), "known wrong" was a
# verdict of the old arithmetic: a census chart can now be exact with its upstream block
# untouched (Conflict S22, Sarabande S20). Those are listed with upstream_exact true and no
# commit; every other entry names the last commit that changed its block (a revert counts).
#
#   python -X utf8 tools/rebuild_repairs.py
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lattice_reauthor                                                           # noqa: E402  (refuses an old converter)
from piu_annotate.formats.sscfile import StepchartSSC                             # noqa: E402
from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def block_of(key):
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9_]+?)?)_((?:HALFDOUBLE_)?(?:ARCADE|SHORTCUT|REMIX|FULLSONG))$", key)
    return f"{m.group(1).replace('_', ' ')}_{m.group(2)}"

def last_fix_commit(rel):
    out = subprocess.run(["git", "log", "--pretty=%h %s", "--", f"simfiles/{rel}"],
                         cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    for line in out:
        if line.split(" ", 1)[-1].startswith("Fix "):
            return line.split(" ", 1)[0]
    return ""

def main():
    census = json.load(open(os.path.join(ROOT, "sources", "census-final.json"), encoding="utf-8"))
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    out, unfixed = [], []
    for c in census:
        name = c["chart"]
        if name not in smap:
            continue
        o = smap[name]
        path = os.path.join(ROOT, "simfiles", o["ssc_rel"].replace("/", os.sep))
        if not os.path.isfile(path):
            continue
        try:
            sc = StepchartSSC.from_song_ssc_file(path, block_of(o["key"]))
            if sc is None:
                continue
            df, ht, _ = stepchart_ssc_to_chartstruct(sc)
            if df is None:
                continue
        except Exception:
            continue
        taps = int(df["Line"].str.contains("1", regex=False).sum())
        ticks = sum(round(t[2]) for t in ht)
        judged = int(c["judged"])
        if taps + ticks == judged:
            changed = lattice_reauthor.history("simfiles/" + o["ssc_rel"], block_of(o["key"]))
            seed = lattice_reauthor.block_section(lattice_reauthor.git("show", "%s:simfiles/%s" % (lattice_reauthor.SEED, o["ssc_rel"])), block_of(o["key"]))
            now = lattice_reauthor.block_section(open(path, encoding="utf-8", newline="").read(), block_of(o["key"]))
            upstream = lattice_reauthor.norm(seed) == lattice_reauthor.norm(now)
            out.append(dict(chart=name, key=o["key"], ssc_rel=o["ssc_rel"], video=c["video"],
                            judged=judged, taps=taps, ticks=ticks, upstream_exact=upstream,
                            commit="" if upstream else (changed[-1][0] if changed else last_fix_commit(o["ssc_rel"]))))
        else:
            unfixed.append((name, taps + ticks, judged))
    out.sort(key=lambda r: r["chart"])
    json.dump(out, open(os.path.join(ROOT, "sources", "repairs.json"), "w", encoding="utf-8"), indent=1)
    print(f"repairs.json: {len(out)} charts verified exact ({sum(1 for r in out if r['upstream_exact'])} of them "
          f"with the upstream block untouched); {len(unfixed)} census charts still wrong")
    for name, implied, judged in sorted(unfixed):
        print(f"  still wrong: {name}: {implied} against {judged}")

if __name__ == "__main__":
    main()
