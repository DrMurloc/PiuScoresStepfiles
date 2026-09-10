# Decide whether an extraction may be authored, using only things that are not the extractor.
#
# The extractor is good and it is not perfect, and the difference matters: a chart written from
# an extraction that quietly missed four notes is a NEW wrong chart, indistinguishable from the
# old wrong chart until someone plays it. So it has to be checked, and checked against something
# that did not produce it.
#
# Three checks are available BEFORE anything is authored:
#
#   1. every note lands on the beat grid. A real note sits on a subdivision; the art behind it
#      does not, so an off-grid streak is the detector's mistake and not the chart's.
#   2. the extraction does not claim more notes than the game judged. P+G+Gd+B+M off the result
#      screen is the number of things the game judged, and taps plus hold heads are a subset of
#      those - the rest are hold ticks, which cannot be negative.
#   3. on a chart with no holds, those two numbers are the SAME number, and any gap is real.
#
# The full count check belongs AFTER authoring, not here. A tick-rate model was tried first -
# judged minus taps minus heads, over the hold length in beats, ought to land on the 2, 4 or 8
# that TICKCOUNTS actually uses - and measured across real charts it lands anywhere from 1.05 to
# 15.6 per beat, so the converter's per-hold rule is not that. The repo already owns the
# authority: convert the authored .ssc and compare its implied count to the catalog, exactly as
# catalog_sweep and tick_verify do. This tool's job is to stop a bad extraction before it gets
# that far, cheaply.
#
# What none of this can prove is that a note is in the right COLUMN - a chart with two notes
# swapped between panels passes every count there is.
#
#   python -X utf8 tools/verify_extract.py "<chart>" [--cache]
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_map      # noqa: E402
import note_extract    # noqa: E402
import quantize as Q   # noqa: E402
import receptors as R  # noqa: E402

def verify(name, notes, off_grid):
    cert = corpus_map.certification()
    e = next((e for e in cert.values() if name in (e.get("charts") or {})), None)
    side = ((e or {}).get("charts", {}).get(name) or {}).get("side") or "1p"
    judged = ((e or {}).get(side) or {}).get("judged")
    heads = [n for n in notes if n.get("hold_end")]
    out = dict(judged=judged, taps=len(notes) - len(heads), heads=len(heads),
               off_grid=off_grid, verdict="REFUSE")
    if off_grid:
        out["why"] = "%d of %d notes do not sit on the grid" % (off_grid, len(notes))
        return out
    if not judged:
        out["why"] = "no certified result screen, so nothing independent to check the count against"
        return out
    if len(notes) > judged:
        out["why"] = "%d notes found where the game judged %d events" % (len(notes), judged)
        return out
    if not heads and len(notes) != judged:
        out["why"] = "no holds, so judged should equal notes: %d judged, %d found" % (judged, len(notes))
        return out
    out["verdict"] = "PASS"
    out["why"] = ("%d notes, all on the grid, inside the %d the game judged" % (len(notes), judged)
                  if heads else "%d notes, all on the grid, and the game judged exactly that many"
                  % len(notes))
    return out

def main():
    note_extract.CACHE = "--cache" in sys.argv
    name = sys.argv[1]
    ncols = 10 if name.split()[-1][0] == "D" else 5
    notes, meta = note_extract.extract(name, quiet="--quiet" in sys.argv)
    rows, taps, beat_at = R.chartstruct(corpus_map.chart_map()[name]["key"], ncols)
    times, beats = Q.tempo_map(rows)
    fnotes = {}
    for r in rows:
        for c, ch in enumerate(r["Line"].lstrip("`")[:ncols]):
            if ch in "12":
                fnotes.setdefault(c, []).append(float(r["Time"]))
    seed, _ = Q.anchor_offset(notes, fnotes, ncols)
    a, share, rate, g = Q.fit_offset(notes, times, beats, max(0.0, seed - 0.05), seed + 0.05)
    Q.quantise(notes, beat_at, a, g, rate=rate)
    off = sum(1 for n in notes if n.get("grid_err", 9) >= Q.TOL)
    v = verify(name, notes, off)
    print("  %s: %s" % (v["verdict"], v["why"]))
    print("     %s judged | %d taps + %d heads | 1/%d of a beat, %d off it"
          % (v["judged"], v["taps"], v["heads"], g, off))

if __name__ == "__main__":
    main()
