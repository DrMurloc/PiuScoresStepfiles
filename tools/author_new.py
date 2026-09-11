# Write a stepfile for a chart this repo has no file for, from its video alone.
#
# author_notes.py repairs a file the repo already holds: it borrows that file's tempo map and
# rewrites only the notes. A song Andamiro has just released has nothing to borrow - no BPMs, no
# song header, no block - so this supplies the three things a file would have:
#
#   the TEMPO, from the extraction itself. A chart sits on a lattice of the beat, so its tempo is
#   the one whose lattice the rows line up on, measured as how well every row aligns with a
#   twelfth-of-a-beat lattice - which holds 16ths, 8th-triplets and 16th-triplets at once. On L
#   (PIU Edit) D27 that is 0.805 at 155.005 BPM against 0.105 for the next tempo tried. A tempo
#   and its double align rows equally well (a twelfth of a 310bpm beat is a 24th of a 155bpm
#   one), so the search covers 100-200bpm first and widens only if nothing there aligns. A chart
#   whose two halves want different tempos is refused: this writes exactly one BPM.
#
#   the BEAT, from where rows land within it. The lattice fixes time only to a twelfth of a beat;
#   the beat is the twelfth that puts the most rows on the coarsest subdivisions, which also
#   settles the half-beat question in favour of more rows ON the beat. Which beat starts a
#   MEASURE is not in the footage at all: the chart is written with one empty measure before its
#   first row, and that is reported as the choice it is.
#
#   the COUNT, from the counter. On autoplay footage the combo's final value is the judged total,
#   and the authored file goes through the converter every other chart goes through; a file whose
#   implied count differs is still written, and the difference is printed beside it.
#
# The file's #OFFSET puts beat 0 at its VIDEO time, in StepMania's sense - there is no audio to
# align to. piu-annotate's converter does not apply #OFFSET at all: the times it reports start at
# beat 0, so laying a converted file against the counter means adding that offset back, which is
# how the first D27 comparison came out 1.467s early everywhere until it was.
#
#   python -X utf8 tools/author_new.py <videoId> --title "L (PIU Edit)" --level 27 --cols 10
#          [--artist ""] [--ticks 4] [--side 1p] [--band C] [--combo <combo.jsonl>] [--out f.ssc]
#          [--cache]
import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import author_notes    # noqa: E402
import combo_check     # noqa: E402
import note_extract    # noqa: E402
import quantize as Q   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = 0.025                                  # arrows nearer than this are one row
WEIGHT = {0: 4, 6: 3, 3: 2, 9: 2, 4: 2, 8: 2, 2: 1, 10: 1}   # twelfths of a beat, coarse to fine

def rows_of(notes):
    groups = []
    for t in sorted(n["t"] for n in notes):
        if groups and t - groups[-1][-1] <= ROW:
            groups[-1].append(t)
        else:
            groups.append([t])
    return np.array([float(np.mean(g)) for g in groups])

def retime(notes):
    """Every note's crossing of the judgement line, from the centroid of its streak at the scroll
    speed around it rather than at the streak's own slope.

    Where the judgement text covers the middle of the field, the lanes under it lose half of every
    streak. On L (PIU Edit) D27 columns 4 and 5 kept 8-11 frames of most notes where the outer
    columns kept 18 or more; those streaks fit 1.5-4% slow and crossed the line up to 10ms late,
    which put 49 notes off a twelfth-of-a-beat lattice - and every hold whose head was one of them
    was lost with it. What was seen is still where the arrow was; only the slope is wrong. At the
    local speed, 0 of those 49 are off the lattice.

    It is done here and not in the extractor. Replayed over the fifteen published charts at the
    floors they are read at, re-timing even only the SHORT streaks cost VANISH D22 four real notes
    and Brown Sky D26 and Shub Niggurath D26 5-6ms of median timing, against small gains elsewhere,
    and no variant avoided all of that. This path writes one tempo and is checked against its own
    counter, which is where the correction can be trusted."""
    notes.sort(key=lambda n: n["t"])
    sp = np.array([-n["v"] for n in notes])
    for i, n in enumerate(notes):
        med = float(np.median(sp[max(0, i - 25):i + 25]))
        if med > 0 and "mt" in n:
            n["t"] = n["mt"] + (n["yj"] - n["my"]) / -med
    notes.sort(key=lambda n: (n["t"], n["col"]))

def clock(notes, a, bpm, half=10.0):
    """Take out a video clock that drifts against the song, measured on the chart's own lattice.

    The video's time is not the song's time everywhere. On L (PIU Edit) D27 every row in the first
    twenty seconds lands 11.3ms late against the lattice the rest of the song sits on, easing to
    5.6ms by thirty and under 1ms from forty - taps and hold heads alike (+11.0 and +11.2 in the
    first ten seconds), at an unchanged scroll speed, so it is the recording's clock and not
    anything the extractor did. fit_offset models an offset and a constant rate, and cannot follow
    a drift that settles; 24 notes of the intro, and 15 of its holds with them, fell off the grid.

    Each note's distance from its nearest lattice line, the median of it over +-half seconds, is
    that drift at that moment - the lattice is known to the millisecond from a thousand rows, so it
    is the reference, and the median ignores the one note in a window that is wrong. Subtracted,
    the D27 has 0 notes off the grid and keeps all 68 holds. Ten seconds is not arbitrary: at two
    and a half or five, the intro's few rows make the correction noisy enough that the grid choice
    downstream flipped. A drift of half a lattice step or more cannot be seen this way - a note
    that late is nearer the next line - so the largest correction is returned, to be looked at."""
    step = 60.0 / bpm / 12.0
    ts = np.array(sorted(n["t"] for n in notes))
    res = (ts - a) - np.round((ts - a) / step) * step

    def at(x):
        lo, hi = np.searchsorted(ts, x - half), np.searchsorted(ts, x + half)
        return float(np.median(res[lo:hi])) if hi > lo else 0.0

    worst = 0.0
    for n in notes:
        d = at(n["t"])
        worst = max(worst, abs(d))
        n["t"] -= d
        if n.get("hold_end"):
            n["hold_end"] -= at(n["hold_end"])
    return worst

def lattice(notes, a, rate, bpm):
    """The coarsest subdivision that holds as many notes, TIGHTLY, as the best one does.

    Not fit_offset's choice. It judges a lattice by the 75th percentile of how far notes sit from
    it, which cannot see a minority under a quarter of the chart - and 26% of the D27's rows are
    16th-triplets. With its intro clock corrected, fit_offset picked quarter-beats, and the snap
    that follows accepts a triplet 1/12 of a beat from a 16th line (0.67 of half a spacing, under
    SNAP's 0.70): 303 notes were written on the wrong line and not one was refused. Counting the
    notes within TOL - the fitting tolerance, where a triplet on a 16th grid scores 0.67 and fails
    - gives 1/4 0.76 and 1/12 1.00, and no chart can be put on a lattice that cannot hold it."""
    beats = np.array([(n["t"] - a) * (1.0 + rate) * bpm / 60.0 for n in notes])
    cover = {g: float(np.mean(Q.grid_error(beats, g) < Q.TOL)) for g in Q.GRIDS}
    top = max(cover.values())
    g = next(k for k in Q.GRIDS if cover[k] >= top - 0.005)
    # Coverage is not proof on its own. Its tolerance shrinks with the lattice, so where the timing
    # is only as good as a fine lattice's spacing, a coarse one still wins: on the repair path Bad
    # Apple!! D20 (written in 12ths, 16 triplet rows) and VVV S23 (24ths) both read as quarter-beats
    # by this very test. So a finer lattice that puts a real share of notes tightly BETWEEN this
    # one's lines is reported - it is a subdivision the footage half-sees, and a reviewer decides.
    finer = []
    for g2 in Q.GRIDS:
        if g2 <= g or g2 % g:
            continue
        between = (Q.grid_error(beats, g2) < Q.TOL) & (np.round(beats * g2).astype(int) % (g2 // g) != 0)
        if between.mean() >= 0.01:
            finer.append((g2, float(between.mean())))
    return g, cover, finer

def alignment(t, bpm):
    return float(abs(np.exp(2j * np.pi * t * bpm * 12.0 / 60.0).mean()))

def tempo(t, lo=100.0, hi=200.0):
    """(bpm, alignment, best alignment elsewhere) - the coarse search, then a fine one."""
    grid = np.arange(lo, hi, 0.01)
    scores = np.array([alignment(t, b) for b in grid])
    b0 = float(grid[int(np.argmax(scores))])
    fine = np.arange(b0 - 0.02, b0 + 0.02, 0.0005)
    b1 = float(fine[int(np.argmax([alignment(t, b) for b in fine]))])
    rest = scores[np.abs(grid - b0) > 0.5]
    return b1, alignment(t, b1), float(rest.max()) if len(rest) else 0.0

def beat_origin(t, bpm):
    """A time at which a beat falls: the twelfth of the lattice that puts rows on the coarsest
    subdivisions."""
    step = 60.0 / bpm / 12.0
    z = np.exp(2j * np.pi * t / step).mean()
    t0 = (np.angle(z) / (2 * np.pi)) * step
    pos = np.round((t - t0) / step).astype(int)
    k = max(range(12), key=lambda k: sum(WEIGHT.get(int(p - k) % 12, 0) for p in pos))
    return t0 + k * step

def header(title, artist, bpm, a, ticks, source):
    return "\n".join([
        "#VERSION:0.81;", "#TITLE:%s;" % title, "#SUBTITLE:;", "#ARTIST:%s;" % artist,
        "#TITLETRANSLIT:;", "#SUBTITLETRANSLIT:;", "#ARTISTTRANSLIT:;", "#GENRE:;", "#ORIGIN:;",
        "#CREDIT:read off %s by tools/author_new.py;" % source, "#BANNER:;", "#BACKGROUND:;",
        "#CDTITLE:;", "#MUSIC:;", "#OFFSET:%.6f;" % -a, "#SAMPLESTART:0.000000;",
        "#SAMPLELENGTH:10.000000;", "#SELECTABLE:YES;", "#SONGTYPE:ARCADE;", "#SONGCATEGORY:;",
        "#VOLUME:100;", "#DISPLAYBPM:%.6f;" % bpm, "#BPMS:0.000=%.3f;" % bpm,
        "#TIMESIGNATURES:0.000=4=4;", "#TICKCOUNTS:0.000=%d;" % ticks, "#COMBOS:0.000=1;",
        "#SPEEDS:0.000=1.000=0.000=0;", "#SCROLLS:0.000=1.000;", "#LABELS:0.000=Song Start;", ""])

def block(ncols, desc, level, bpm, a, ticks, measures):
    body = "\n,\n".join("\n".join(rows) for rows in measures)
    return "\n".join([
        "#NOTEDATA:;", "#STEPSTYPE:pump-%s;" % ("double" if ncols == 10 else "single"),
        "#DESCRIPTION:%s;" % desc, "#DIFFICULTY:Edit;", "#METER:%d;" % level, "#CREDIT:;",
        "#OFFSET:%.6f;" % -a, "#BPMS:0.000000=%.6f\n;" % bpm, "#STOPS:;", "#DELAYS:;", "#WARPS:;",
        "#TIMESIGNATURES:0.000000=4=4\n;", "#TICKCOUNTS:0.000000=%d\n;" % ticks,
        "#COMBOS:0.000000=1\n;", "#SPEEDS:0.000000=1.000000=0.000000=0\n;",
        "#SCROLLS:0.000000=1.000000\n;", "#FAKES:;", "#LABELS:0.000000=Song Start\n;",
        "#NOTES:", body, ";", ""])

def main():
    args = sys.argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    vid = args[0]
    ncols = int(opt("--cols", "10"))
    level = int(opt("--level"))
    title = opt("--title")
    ticks = int(opt("--ticks", "4"))
    desc = "%s%d" % ("D" if ncols == 10 else "S", level)
    note_extract.CACHE = "--cache" in args
    notes, meta = note_extract.extract_video(vid, ncols, opt("--side", "1p"), opt("--band", "C"))
    retime(notes)
    t = rows_of(notes)

    bpm, al, other = tempo(t)
    if al < 0.5:
        bpm, al, other = tempo(t, 60.0, 300.0)
    half = float(np.median(t))
    b_a = tempo(t[t < half], bpm - 0.2, bpm + 0.2)[0]
    b_b = tempo(t[t >= half], bpm - 0.2, bpm + 0.2)[0]
    print("  tempo %.3f bpm: alignment %.3f, next best %.3f; halves %.3f / %.3f"
          % (bpm, al, other, b_a, b_b))
    if al < 0.5 or abs(b_a - b_b) > 0.1:
        raise SystemExit("  REFUSED: no single tempo explains this chart")
    if abs(bpm - round(bpm)) < 0.02:
        bpm = float(round(bpm))
    beat = 60.0 / bpm

    tb = beat_origin(t, bpm)
    a = tb + math.floor((t[0] - tb) / beat) * beat - 4 * beat   # one empty measure first
    drift = clock(notes, a, bpm)
    times, beats = np.array([0.0, 1.0e4]), np.array([0.0, 1.0e4 * bpm / 60.0])
    # +-8ms, a quarter of a twelfth: the lattice repeats every twelfth, so a wider window can
    # slide the whole chart one step and still fit it perfectly
    a, share, rate, g_fit = Q.fit_offset(notes, times, beats, a - 0.008, a + 0.008)
    g, cover, finer = lattice(notes, a, rate, bpm)
    print("  video clock corrected by up to %.1fms; lattice 1/%d (notes held within TOL: %s)%s"
          % (1000 * drift, g, " ".join("1/%d %.2f" % (k, v) for k, v in cover.items()),
             "" if g == g_fit else "; fit_offset alone would have chosen 1/%d" % g_fit))
    for g2, part in finer:
        print("  REVIEW: 1/%d would put %.1f%% of notes between 1/%d lines - a finer subdivision "
              "the footage only half resolves" % (g2, 100 * part, g))
    Q.quantise(notes, lambda ct: ct * bpm / 60.0, a, g, rate=rate)
    kept = Q.dedupe(Q.keep_on_grid(notes))
    T = V = None
    if opt("--combo"):
        T, V = combo_check.curve(opt("--combo"))
        # A video that fades out on a hold never shows where the hold ends, but the game credits
        # every tick left in it at once, as one jump of the counter in the last frames - on the
        # D27, 1436 to 1500 between two frames 33ms apart. That jump IS the rest of the hold, so the
        # last hold still running at it is lengthened by the jump, at the file's tick rate.
        j = len(V) - 1
        while j > 0 and V[j - 1] == V[j]:
            j -= 1
        jump = int(V[j] - V[j - 1]) if j > 0 else 0
        if j > 0 and jump >= 2 * ticks and T[j] - T[j - 1] <= 0.05:
            live = [n for n in kept if n.get("beat_end") is not None and n.get("hold_end", 0) >= T[j] - 1.0]
            if live:
                last = max(live, key=lambda n: n["beat_end"])
                last["beat_end"] += jump / float(ticks)
                print("  the counter jumps +%d at %.2fs, the video's end: column %d's last hold lengthened "
                      "by %.1f beats" % (jump, T[j], last["col"], jump / float(ticks)))
    heads = sum(1 for n in kept if n.get("beat_end") is not None)
    print("  beat 0 at %.3fs of video; written on 1/%d of a beat; clock %+.4f%%; %d of %d notes kept"
          % (a, g, 100 * rate, len(kept), len(notes)))
    print("  measure alignment is a CHOICE: one empty measure, then the first row")
    measures = author_notes.grid(kept, ncols, g)

    out = opt("--out") or os.path.join(ROOT, "work", "authored-new",
                                        re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") + ".ssc")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    source = "https://youtu.be/%s" % vid
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(header(title, opt("--artist", ""), bpm, a, ticks, source) + "\n")
        f.write(block(ncols, desc, level, bpm, a, ticks, measures))
    print("  %d measures, %d taps + %d holds -> %s" % (len(measures), len(kept) - heads, heads, out))

    target = None
    if opt("--combo"):
        T, V = combo_check.curve(opt("--combo"))
        target = int(V[-1])
        print("  counter's final value: %d" % target)
    import tick_verify
    tick_verify.run(out, "%s_ARCADE" % desc, target)

if __name__ == "__main__":
    main()
