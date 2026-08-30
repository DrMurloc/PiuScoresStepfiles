# Runs the piu-annotate converter (the same code the annotation pipeline uses) over a
# block in OUR simfiles/ tree and reports what the pipeline would derive: tap rows,
# per-hold tick list, and the implied judged total. This is the acceptance check for
# every tick fix — the authored file must make THIS function produce the target.
#
#   python -X utf8 tools/tick_verify.py "<chart name from census>" [expectedJudged]
#   python -X utf8 tools/tick_verify.py --file <path> --block S13_ARCADE [expected]
import json
import os
import sys

sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
from piu_annotate.formats.sscfile import StepchartSSC              # noqa: E402
from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def block_of(key):
    # chartstruct key "Come_to_Me_-_Banya_S13_ARCADE" -> "S13_ARCADE"-style block id,
    # tolerating markers like INFOBAR_TITLE between code and songtype
    import re
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9_]+?)?)_((?:HALFDOUBLE_)?(?:ARCADE|SHORTCUT|REMIX|FULLSONG))$", key)
    code = m.group(1).replace("_", " ")
    return f"{code}_{m.group(2)}"

def run(path, desc_songtype, expected=None):
    sc = StepchartSSC.from_song_ssc_file(path, desc_songtype)
    if sc is None:
        print("BLOCK NOT FOUND"); return None
    df, holdticks, msg = stepchart_ssc_to_chartstruct(sc)
    if df is None:
        print("CONVERT FAILED:", msg); return None
    taps = int(df["Line"].str.contains("1", regex=False).sum())
    tick_sum = sum(round(t[2]) for t in holdticks)
    implied = taps + tick_sum
    print(f"taps {taps} + ticks {tick_sum} = implied {implied}" +
          (f"  (expected {expected}: {'MATCH' if implied == expected else f'off {implied - expected:+d}'})" if expected else ""))
    for st, en, tk in holdticks:
        print(f"  hold {st:7.2f}..{en:7.2f}s  ticks {round(tk)}")
    return taps, holdticks

if __name__ == "__main__":
    args = sys.argv[1:]
    if args[0] == "--file":
        run(args[1], args[3], int(args[4]) if len(args) > 4 else None)
    else:
        name = args[0]
        expected = int(args[1]) if len(args) > 1 else None
        smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
        o = smap[name]
        path = os.path.join(ROOT, "simfiles", o["ssc_rel"].replace("/", os.sep))
        print(f"{name} -> {o['ssc_rel']} block {block_of(o['key'])}")
        run(path, block_of(o["key"]), expected)
