# Write an extraction back out as a stepfile's note grid.
#
# This is the last step of reading a chart off the screen: note_extract says which column and
# when, quantize turns "when" into a beat, and this turns beats into the measure-by-measure
# grid an .ssc actually stores. Nothing else in the file is touched - BPMS, STOPS, TICKCOUNTS,
# the description, the other difficulties - because none of that is what was wrong. A chart in
# this repo is wrong about its STEPS.
#
# Beats follow the SSC convention: 4 beats to a measure, row r of R being beat 4m + 4r/R. The
# subdivision is chosen per measure as the smallest that can represent every note in it, so a
# measure of straight 8ths stays 8 rows rather than being padded to 192 because a triplet
# happens elsewhere in the song.
#
# It refuses to write in place unless told to. The count gate that decides whether an authored
# chart is right runs on the CONVERTED file, so the order is: write beside the original, convert,
# compare to the catalog, and only then replace anything.
#
#   python -X utf8 tools/author_notes.py "<chart>" [--out <file.ssc>] [--in-place] [--cache]
import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_map      # noqa: E402
import edit_notes      # noqa: E402
import note_extract    # noqa: E402
import quantize as Q   # noqa: E402
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIVS = (4, 8, 12, 16, 24, 32, 48, 64, 96, 192)   # rows a measure may be written on

def rows_for(beats_in_measure):
    """The smallest subdivision that can hold every one of these beats exactly."""
    for R_ in DIVS:
        if all((Fraction(b).limit_denominator(192) * R_ / 4).denominator == 1
               for b in beats_in_measure):
            return R_
    return 192

def grid(notes, ncols):
    """The measures, as lists of note rows. Taps are 1, hold heads 2, hold tails 3."""
    events = []
    for n in notes:
        events.append((Fraction(n["beat"]).limit_denominator(192), n["col"],
                       "2" if n.get("beat_end") is not None else "1"))
        if n.get("beat_end") is not None:
            events.append((Fraction(n["beat_end"]).limit_denominator(192), n["col"], "3"))
    if not events:
        return []
    last = max(b for b, _, _ in events)
    n_meas = int(last // 4) + 1
    by_meas = [[] for _ in range(n_meas)]
    for b, c, ch in events:
        by_meas[int(b // 4)].append((b, c, ch))
    out = []
    for m, evs in enumerate(by_meas):
        R_ = rows_for([b for b, _, _ in evs]) if evs else 4
        rows = ["0" * ncols for _ in range(R_)]
        for b, c, ch in evs:
            r = int((b - 4 * m) * R_ / 4)
            row = list(rows[r])
            # two events on one row in one column cannot happen - a tail and the next head are
            # different rows by construction - but if the extraction produced it, the later
            # symbol would silently win, so it is caught rather than written
            if row[c] != "0":
                raise ValueError("two notes at beat %s in column %d" % (b, c))
            row[c] = ch
            rows[r] = "".join(row)
        out.append(rows)
    return out

def author(ssc_text, desc_tag, measures):
    sections, i = edit_notes.find_block(ssc_text, desc_tag)
    span, _ = edit_notes.parse_notes(sections[i])
    body = "\n" + "\n,\n".join("\n".join(rows) for rows in measures) + "\n"
    sections[i] = sections[i][:span[0]] + body + sections[i][span[1]:]
    return "#NOTEDATA:;".join(sections)

def main():
    note_extract.CACHE = "--cache" in sys.argv
    name = sys.argv[1]
    ncols = 10 if name.split()[-1][0] == "D" else 5
    entry = corpus_map.chart_map()[name]
    notes, meta = note_extract.extract(name, quiet="--quiet" in sys.argv)
    rows, taps, beat_at = R.chartstruct(entry["key"], ncols)
    times, beats = Q.tempo_map(rows)
    fnotes = {}
    for r in rows:
        for c, ch in enumerate(r["Line"].lstrip("`")[:ncols]):
            if ch in "12":
                fnotes.setdefault(c, []).append(float(r["Time"]))
    seed, _ = Q.anchor_offset(notes, fnotes, ncols)
    a, share, rate, g = Q.fit_offset(notes, times, beats, max(0.0, seed - 0.05), seed + 0.05)
    Q.quantise(notes, beat_at, a, g, rate=rate)
    off = [n for n in notes if n.get("grid_err", 9) >= Q.TOL]
    if off:
        raise SystemExit("%d of %d notes are off the 1/%d grid - not authoring an extraction "
                         "that does not fit the chart's own tempo map" % (len(off), len(notes), g))
    measures = grid(notes, ncols)
    ssc = os.path.join(ROOT, "simfiles", entry["ssc_rel"])
    text = open(ssc, encoding="utf-8", errors="replace").read()
    # the block is named by the chartstruct key's difficulty suffix, the same way finale_ticks
    # finds it
    import re
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9]+)*?)_(ARCADE|SHORTCUT|REMIX|FULLSONG)$", entry["key"])
    desc = "%s_%s" % (m.group(1).replace("_", " "), m.group(2))
    out = author(text, desc, measures)
    dest = (ssc if "--in-place" in sys.argv
            else sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
            else os.path.join(ROOT, "work", "authored", os.path.basename(ssc)))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "w", encoding="utf-8").write(out)
    heads = sum(1 for n in notes if n.get("beat_end") is not None)
    print("  %d measures, %d taps + %d holds, written on 1/%d of a beat" %
          (len(measures), len(notes) - heads, heads, g))
    print("  -> %s" % dest)
    print("  NOT verified: convert it and compare the implied count to the catalog before "
          "anything replaces the original")

if __name__ == "__main__":
    main()
