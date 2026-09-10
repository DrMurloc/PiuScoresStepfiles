# Compare an authored note grid against the one already in the stepfile, in BEATS.
#
# This is the acceptance test for reading a chart off a video: not "how many notes did the
# detector find" but "is the file it produced the file we wanted". Comparing in beats rather
# than rows means a measure written on 16ths and the same measure written on 48ths compare
# equal, which they should - they are the same chart.
#
# It is a diff, not a verdict. On a chart the repo believes, a clean diff says the pipeline
# reproduces a known chart from footage alone. On a chart the repo does NOT believe - which is
# every chart this project exists for - the diff is the proposed repair, and what decides
# whether it ships is the count against the catalog, not this.
#
#   python -X utf8 tools/diff_notes.py "<chart>" <authored.ssc>
import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_map  # noqa: E402
import edit_notes  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def block_tag(key):
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9]+)*?)_(ARCADE|SHORTCUT|REMIX|FULLSONG)$", key)
    return "%s_%s" % (m.group(1).replace("_", " "), m.group(2))

def events(path, desc):
    """Every note in the block as (beat, column, symbol), independent of subdivision."""
    text = open(path, encoding="utf-8", errors="replace").read()
    sections, i = edit_notes.find_block(text, desc)
    _, measures = edit_notes.parse_notes(sections[i])
    out = set()
    for mi, rows in enumerate(measures):
        n = len(rows) or 1
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch in "123":
                    out.add((Fraction(4 * mi) + Fraction(4 * r, n), c, ch))
    return out

def main():
    name, authored = sys.argv[1], sys.argv[2]
    entry = corpus_map.chart_map()[name]
    desc = block_tag(entry["key"])
    A = events(os.path.join(ROOT, "simfiles", entry["ssc_rel"]), desc)
    B = events(authored, desc)
    same = A & B
    print("%s: file %d events, authored %d, identical %d (%.1f%% of the file)"
          % (name, len(A), len(B), len(same), 100.0 * len(same) / max(len(A), 1)))
    only_a, only_b = sorted(A - B), sorted(B - A)
    print("  only in the file: %d    only in the extraction: %d" % (len(only_a), len(only_b)))
    for tag, s in (("file", only_a), ("extraction", only_b)):
        for b, c, ch in s[:8]:
            print("     %-10s beat %8s col %d '%s'" % (tag, b, c, ch))
        if len(s) > 8:
            print("     %-10s ... and %d more" % (tag, len(s) - 8))
    # a note in the right place but the wrong SYMBOL is a hold read as a tap, which is a
    # different kind of wrong from a note in the wrong place, and worth separating
    pos_a = {(b, c) for b, c, _ in A}
    pos_b = {(b, c) for b, c, _ in B}
    print("  positions identical: %d; symbol-only differences: %d"
          % (len(pos_a & pos_b), len({(b, c) for b, c, _ in A - B} & {(b, c) for b, c, _ in B - A})))

if __name__ == "__main__":
    main()
