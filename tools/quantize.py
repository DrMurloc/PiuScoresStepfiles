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
TOL = 0.35                       # how far off a lattice line a note may sit, as a fraction of
                                 # half the spacing - so 1.0 is "anywhere at all"

def grid_error(beat, grid):
    """How far off the nearest line of a 1/grid-of-a-beat lattice, as a FRACTION of the spacing.

    In lattice units, not beats. A tolerance in beats has to be re-derived for every grid or it
    silently means nothing: 0.02 beats against a 48th lattice, whose lines are 0.0208 beats
    apart, accepts every possible time - which is exactly how the offset fit came back with
    "100% on the lattice" at an offset of zero.
    """
    return np.abs(beat * grid - np.round(beat * grid)) * 2.0

def tempo_map(rows):
    """The chart's time-to-beat curve as two arrays, for interpolation in bulk."""
    t = np.array([float(r["Time"]) for r in rows], dtype=float)
    b = np.array([float(r["Beat"]) for r in rows], dtype=float)
    keep = np.concatenate(([True], np.diff(t) > 0))     # np.interp needs a strictly rising x
    return t[keep], b[keep]

def anchor_offset(notes, fnotes, ncols, lo=0.0, hi=60.0, tol=0.08):
    """Roughly where in the video the chart starts, from the file's OWN notes.

    The grid cannot answer this on its own and it is not a flaw in the fit: a lattice repeats,
    so every offset a whole number of lattice steps away scores identically, and on a chart
    whose spacing is 39ms that is hundreds of equally good answers. Something has to say WHEN,
    not just how often.

    The file's notes are the only thing at hand that does - and using them here is not circular,
    because it is not their content that is borrowed. A file we are replacing is wrong in
    places; it is not wrong about which minute of the song it is. It fixes the clock to within a
    lattice step and the grid fit takes it from there, and a file so wrong that even that fails
    is a file whose extraction should be refused rather than authored.
    """
    def at(a):
        hit, err = 0, []
        for c in range(ncols):
            col = fnotes.get(c, [])
            if not col:
                continue
            for n in notes:
                if n["col"] != c:
                    continue
                t = n["t"] - a
                j = bisect.bisect_left(col, t - tol)
                if j < len(col) and abs(col[j] - t) <= tol:
                    hit += 1
                    err.append(abs(col[j] - t))
        return hit, (float(np.median(err)) if err else 9.9)

    best = (0, 9.9, lo)
    for k in range(int(lo * 100), int(hi * 100)):
        a = k / 100.0
        hit, err = at(a)
        if (hit, -err) > (best[0], -best[1]):
            best = (hit, err, a)
    # then to the millisecond, because this is the only thing that knows WHERE in the song the
    # chart starts and a lattice step of slack here is a whole chart written a step out of place
    for k in range(-30, 31):
        a = best[2] + k / 1000.0
        hit, err = at(a)
        if (hit, -err) > (best[0], -best[1]):
            best = (hit, err, a)
    return best[2], best[0]

def fit_offset(notes, times, beats, lo=0.0, hi=60.0, step=0.002):
    """video = chart + a, and which subdivision the chart is written on, from the extraction and
    the chart's tempo map alone.

    Both at once, because neither is knowable without the other. Fitting on one fine lattice was
    tried first and is not stable: at a 48th of a beat the lines are a few milliseconds apart, so
    a chart dense enough to matter has many offsets that score alike, and the winner came back a
    quarter of a second out. Fitted per grid and then read coarsest-first, the answer is the
    coarsest lattice the whole extraction fits - which is what "the chart is written on 16ths"
    actually means.
    """
    t = np.array([n["t"] for n in notes], dtype=float)

    def fit(a, rate, grid):
        # Scored on how FAR off the lattice the extraction sits, not on how many notes are
        # within a tolerance of it. Counting stops discriminating as soon as everything is
        # inside the window, so it happily picks an offset a whole lattice step off the truth;
        # the median distance has one minimum and it is at the right place.
        #
        # np.interp CLAMPS outside its range, so an offset that pushes the whole extraction off
        # the front of the chart maps every note to beat zero - perfectly on any lattice. Notes
        # outside the tempo map are not evidence for the offset that put them there.
        ct = (t - a) * (1.0 + rate)
        inside = (ct >= times[0]) & (ct <= times[-1])
        if inside.mean() < 0.5:
            return -1.0
        e = grid_error(np.interp(ct[inside], times, beats), grid)
        return float(inside.mean() * (1.0 - np.median(e)))

    per_grid = {}
    for g in GRIDS:
        best = (-1.0, 0.0, 0.0)
        for k in range(int(lo / step), int(hi / step)):
            a = k * step
            h = fit(a, 0.0, g)
            if h > best[0]:
                best = (h, a, 0.0)
        # A video's clock and a stepfile's tempo map are not the same clock. Measured against the
        # file on charts whose extraction is otherwise exact, the residual is a CONSTANT to about
        # a millisecond on Bee S17 and drifts 13ms a minute on Dr. M D18 - small against a 16th
        # note, but a straight line, so it costs one parameter to remove rather than to carry.
        for rate in np.arange(-0.0025, 0.00251, 0.00025):
            h = fit(best[1], float(rate), g)
            if h > best[0]:
                best = (h, best[1], float(rate))
        per_grid[g] = best
    for g in GRIDS:
        if per_grid[g][0] >= 0.90:
            return per_grid[g][1], per_grid[g][0], per_grid[g][2], g
    g = max(GRIDS, key=lambda k: per_grid[k][0])
    return per_grid[g][1], per_grid[g][0], per_grid[g][2], g

def quantise(notes, beat_at, a, g, tol=TOL, rate=0.0):
    """Snap to the grid the fit chose, and say who did not land on it."""
    b = [beat_at((n["t"] - a) * (1.0 + rate)) for n in notes]
    on = float(np.mean([grid_error(x, g) < tol for x in b]))
    for n, x in zip(notes, b):
        n["beat_raw"] = float(x)
        n["beat"] = float(np.round(x * g) / g)
        n["grid_err"] = float(grid_error(x, g))
        if n.get("hold_end"):
            hb = beat_at((n["hold_end"] - a) * (1.0 + rate))
            n["beat_end"] = float(np.round(hb * g) / g)
    return g, on

def keep_on_grid(notes, tol=TOL):
    """The notes that landed on the grid. A streak that did not is art, not a note."""
    return [n for n in notes if n.get("grid_err", 9) < tol]

def main():
    import corpus_map
    import note_extract
    note_extract.CACHE = "--cache" in sys.argv
    name = sys.argv[1]
    ncols = 10 if name.split()[-1][0] == "D" else 5
    notes, meta = note_extract.extract(name, quiet="--quiet" in sys.argv)
    key = corpus_map.chart_map()[name]["key"]
    rows, taps, beat_at = R.chartstruct(key, ncols)
    times, beats = tempo_map(rows)
    fnotes = {}
    for r in rows:
        for c, ch in enumerate(r["Line"].lstrip("`")[:ncols]):
            if ch in "12":
                fnotes.setdefault(c, []).append(float(r["Time"]))
    seed, hit = anchor_offset(notes, fnotes, ncols)
    # +-50ms around the anchor, not +-500. The grid cannot tell one lattice step from the next,
    # so a wide window lets it walk a step away from the only evidence that knows where the song
    # starts - and a chart written one step out of place is wrong in every single row.
    a, share, rate, g = fit_offset(notes, times, beats, max(0.0, seed - 0.05), seed + 0.05)
    print("  anchored at %+.2fs by the file's own notes (%d of %d land on one)" % (seed, hit, len(notes)))
    _, on = quantise(notes, beat_at, a, g, rate=rate), None
    on = share
    kept = keep_on_grid(notes)
    print("  offset %+.3fs, clock %+.3f%%, from the grid alone" % (a, 100 * rate))
    print("  chart is written on 1/%d of a beat: %.1f%% of the extraction lands on it" % (g, 100 * share))
    print("  %d notes kept, %d discarded as off-grid" % (len(kept), len(notes) - len(kept)))
    # what the same grid says about the file we are replacing
    fb = [beat_at(float(r["Time"])) for r in rows]
    print("  (the file itself is %.1f%% on that grid)"
          % (100 * float(np.mean([grid_error(x, g) < TOL for x in fb]))))

if __name__ == "__main__":
    main()
