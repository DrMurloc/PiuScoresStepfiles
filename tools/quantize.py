# Put an extraction on the beat grid - and use the grid as a sensor in its own right.
#
# A stepfile is beats, not seconds, so an extraction has to be quantised before it can be
# written. That step is also the strongest false-positive filter available: a real note sits on
# a subdivision of the beat, and the art behind it does not. Nothing here reads the stepfile's
# NOTES - only its timing (BPMs and stops), which is the half of a broken file that is not
# broken; the notes are exactly what is being replaced.
#
# The offset between video time and chart time is fitted the same way, on the extraction alone:
# the right offset is the one that puts the most notes on grid lines. That matters because the
# obvious alternative - line the extraction up against the file's own notes - assumes the answer
# on a chart we already believe is wrong.
import bisect
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receptors as R  # noqa: E402

GRIDS = (4, 8, 12, 16, 24, 32)   # subdivisions per beat a chart may actually use

def grid_error(beat, grid):
    """How far off the nearest line of a 1/grid-of-a-beat lattice, in beats."""
    return abs(beat * grid - np.round(beat * grid)) / grid

def fit_offset(notes, beat_at, lo=0.0, hi=60.0, step=0.002, grid=48):
    """video = chart + a, from the extraction and the chart's tempo map alone.

    Scored on a fine lattice rather than the one the chart uses, because which subdivision a
    chart is written on is not known yet and a 12th-note chart scored on 16ths would be pushed
    onto the wrong phase.
    """
    best = (-1.0, 0.0)
    t = np.array([n["t"] for n in notes], dtype=float)
    for k in range(int(lo / step), int(hi / step)):
        a = k * step
        b = np.array([beat_at(x) for x in (t - a)])
        d = np.abs(b * grid - np.round(b * grid)) / grid
        hit = float(np.mean(d < 0.02))
        if hit > best[0]:
            best = (hit, a)
    return best[1], best[0]

def quantise(notes, beat_at, a, tol=0.03):
    """Snap to the coarsest grid the chart actually fits, and say who did not land on it."""
    b = [beat_at(n["t"] - a) for n in notes]
    for g in GRIDS:
        on = float(np.mean([grid_error(x, g) < tol for x in b]))
        if on > 0.97:
            break
    for n, x in zip(notes, b):
        n["beat_raw"] = float(x)
        n["beat"] = float(np.round(x * g) / g)
        n["grid_err"] = float(grid_error(x, g))
        if n.get("hold_end"):
            hb = beat_at(n["hold_end"] - a)
            n["beat_end"] = float(np.round(hb * g) / g)
    return g, on

def keep_on_grid(notes, tol=0.03):
    """The notes that landed on the grid. A streak that did not is art, not a note."""
    return [n for n in notes if n.get("grid_err", 9) < tol]

def main():
    import corpus_map
    import note_extract
    name = sys.argv[1]
    ncols = 10 if name.split()[-1][0] == "D" else 5
    notes, meta = note_extract.extract(name, quiet="--quiet" in sys.argv)
    key = corpus_map.chart_map()[name]["key"]
    rows, taps, beat_at = R.chartstruct(key, ncols)
    a, share = fit_offset(notes, beat_at)
    g, on = quantise(notes, beat_at, a)
    kept = keep_on_grid(notes)
    print("  offset %+.3fs from the grid alone (%.0f%% of notes on a 48th lattice)" % (a, 100 * share))
    print("  chart is written on 1/%d of a beat: %.1f%% of the extraction lands on it" % (g, 100 * on))
    print("  %d notes kept, %d discarded as off-grid" % (len(kept), len(notes) - len(kept)))
    # what the same grid says about the file we are replacing
    fb = [beat_at(float(r["Time"])) for r in rows]
    print("  (the file itself is %.1f%% on that grid)"
          % (100 * float(np.mean([grid_error(x, g) < 0.03 for x in fb]))))

if __name__ == "__main__":
    main()
