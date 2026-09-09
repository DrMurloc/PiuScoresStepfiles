# Score an extraction against a chart whose notes we know are right.
#
# The oracle is large: every chart that already converts EXACTLY to the catalog's note count has
# correct notes, and the repaired ones were derived from footage and verified the same way. So
# extraction accuracy can be measured on thousands of charts before a single note is authored.
#
# Reported per chart: how many of the file's notes the extraction found (recall), how much of
# what it extracted was real (precision), and the timing spread of the matches. A perfect run
# would be 100/100 with a spread inside a 16th note.
#
#   python -X utf8 tools/extract_score.py "<chart>" ["<chart>" ...] [--tol 0.05] [--offset-scan]
import bisect
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_map        # noqa: E402
import note_extract      # noqa: E402
import receptors as R    # noqa: E402

def file_notes(name):
    ncols = 10 if name.split()[-1][0] == "D" else 5
    key = corpus_map.chart_map()[name]["key"]
    rows, taps, beat_at = R.chartstruct(key, ncols)
    notes, holds = {}, {}
    op = {}
    for r in rows:
        t = float(r["Time"])
        for c, ch in enumerate(r["Line"].lstrip("`")):
            if ch in "12":
                notes.setdefault(c, []).append(t)
            if ch == "2":
                op[c] = t
            elif ch == "3" and c in op:
                holds.setdefault(c, []).append((op.pop(c), t))
    for c in notes:
        notes[c].sort()
    return notes, holds, ncols

def match(ext, notes, ncols, tol, a):
    used, errs, hit = set(), [], 0
    by_col = {}
    for i, n in enumerate(ext):
        by_col.setdefault(n["col"], []).append((n["t"] - a, i))
    for c in range(ncols):
        col = notes.get(c, [])
        cand = sorted(by_col.get(c, []))
        for t, i in cand:
            j = bisect.bisect_left(col, t - tol)
            best, bj = tol, -1        # a match must be INSIDE the tolerance, not near it
            for k in (j - 1, j, j + 1):
                if 0 <= k < len(col) and (c, k) not in used and abs(col[k] - t) < best:
                    best, bj = abs(col[k] - t), k
            if bj >= 0:
                used.add((c, bj)); hit += 1; errs.append(best)
    return hit, errs

def main():
    tol = float(sys.argv[sys.argv.index("--tol") + 1]) if "--tol" in sys.argv else 0.05
    names = [a for a in sys.argv[1:] if not a.startswith("--")
             and a not in {sys.argv[sys.argv.index("--tol") + 1] if "--tol" in sys.argv else None}]
    print("%-34s %6s %6s %7s %7s  %s" % ("chart", "file", "found", "recall", "prec", "median err"))
    for name in names:
        try:
            ext, meta = note_extract.extract(name, quiet=True)
        except Exception as ex:
            print("%-34s  extraction failed: %r" % (name[:34], ex)); continue
        notes, holds, ncols = file_notes(name)
        n_file = sum(len(v) for v in notes.values())
        # a residual constant offset (capture lag, where the strip sits in the sprite) is fitted
        # once per chart; anything tempo-shaped has already been handled by the speed curve
        # extracted times are VIDEO time and the file's are CHART time - the chart starts ten
        # or more seconds in, so the search has to cover the whole lead-in before it refines
        best = (0, 0.0, [])
        for k in range(0, 6001, 5):                       # 0-60s in 25ms steps
            a = k / 100.0
            hit, errs = match(ext, notes, ncols, 0.08, a)
            if hit > best[0]:
                best = (hit, a, errs)
        coarse = best[1]
        best = (0, coarse, [])
        for k in range(-30, 31):
            a = coarse + k / 500.0
            hit, errs = match(ext, notes, ncols, tol, a)
            if hit > best[0]:
                best = (hit, a, errs)
        hit, a, errs = best
        print("%-34s %6d %6d %6.1f%% %6.1f%%  %.3fs (lead %+.3f)"
              % (name[:34], n_file, len(ext), 100.0 * hit / max(n_file, 1),
                 100.0 * hit / max(len(ext), 1), float(np.median(errs)) if errs else float("nan"), a))

if __name__ == "__main__":
    main()
