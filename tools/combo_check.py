# Check an extraction against the combo counter, one quiet stretch at a time.
#
# On autoplay footage - every official upload - nothing is missed and nothing breaks the combo,
# so the counter moves by exactly one for every judged event. A judged event is a ROW, not an
# arrow: a jump is one judgement (EVIDENCE-RULES.md). Counted as arrows, L (PIU Edit) D27's
# extraction came to 206 across the stretches where its counter moved 180; counted as rows, 183.
# So between two instants where the counter sat still, the rows an extraction found must equal
# how far the counter moved, and a stretch where they do not is a place for a reviewer to look.
#
# The stretches come from the COUNTER, not from the extraction: a quiet instant is one where the
# counter was read without a gap and did not move for a quarter of a second. That makes them the
# same for every extraction of a video, so two correlation floors are judged on the same evidence
# rather than each on the boundaries its own notes happened to leave.
#
# A stretch that any extraction puts a hold in is reported and not judged. The counter there
# includes the hold's ticks, and how many ticks a beat of hold is worth belongs to the chart, not
# to the footage.
#
#   python -X utf8 tools/combo_check.py <combo.jsonl> <notes.json> [<notes.json> ...]
#          [--conf 0.7] [--still 0.25] [--span 3.0] [--list]
import bisect
import json
import os
import sys

import numpy as np

ROW = 0.025   # arrows nearer than this in time are one row, one judgement

def curve(path, conf=0.7):
    """The counter as (times, values): confident reads, then the longest run of them that never
    goes down - a misread is almost never consistent with the reads on both sides of it."""
    pts = []
    for line in open(path, encoding="utf-8"):
        t, v, c = json.loads(line)
        if v is not None and c >= conf:
            pts.append((t, v))
    tails, tidx, prev = [], [], [-1] * len(pts)
    for i, (t, v) in enumerate(pts):
        j = bisect.bisect_right(tails, v)
        if j == len(tails):
            tails.append(v)
            tidx.append(i)
        else:
            tails[j] = v
            tidx[j] = i
        prev[i] = tidx[j - 1] if j > 0 else -1
    seq, k = [], tidx[-1] if tidx else -1
    while k >= 0:
        seq.append(pts[k])
        k = prev[k]
    seq.reverse()
    return np.array([t for t, _ in seq]), np.array([v for _, v in seq])

def quiet(T, V, still=0.15):
    """(instant, value) midway between two reads of the same value at least `still` apart.

    The reads need not be continuous. The counter never goes down, so the same value at both
    ends means nothing was judged in between, however many frames went unread - and on a dense
    chart they are most of them: the digits pulse and notes scroll across them, and L (PIU Edit)
    D27 reads on 55% of its frames. Asking for an unbroken run of reads found one quiet instant
    in the whole song. The distance between the two reads is the margin a note's extracted time
    has to be wrong by before it lands in the wrong stretch."""
    out, i = [], 0
    while i < len(T):
        j = i
        while j + 1 < len(T) and V[j + 1] == V[i]:
            j += 1
        if T[j] - T[i] >= still:
            out.append(((T[i] + T[j]) / 2.0, int(V[i])))
        i = j + 1
    return out

def stretches(qs, span=3.0):
    picked = []
    for q in qs:
        if not picked or q[0] - picked[-1][0] >= span:
            picked.append(q)
    return list(zip(picked, picked[1:]))

def row_starts(notes):
    starts, last = [], None
    for t in sorted(n["t"] for n in notes):
        if last is None or t - last > ROW:
            starts.append(t)
        last = t
    return starts

def judge(notes, spans, rails=None):
    """Per stretch: how far the counter moved, how many rows the extraction put there, and how
    many holds overlap it - the lane rails if they were given, the extraction's own holds if not."""
    rs = row_starts(notes)
    holds = rails if rails is not None else [(n["t"], n["hold_end"]) for n in notes if n.get("hold_end")]
    out = []
    for (a, va), (b, vb) in spans:
        out.append(dict(a=a, b=b, moved=vb - va,
                        rows=bisect.bisect_right(rs, b) - bisect.bisect_right(rs, a),
                        holds=sum(1 for h0, h1 in holds if h0 < b and h1 > a)))
    return out

def main():
    args = sys.argv[1:]
    valued = {"--conf", "--still", "--span", "--pass"}
    opt = lambda k, d: float(args[args.index(k) + 1]) if k in args else d
    files = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in valued)]
    T, V = curve(files[0], opt("--conf", 0.7))
    qs = quiet(T, V, opt("--still", 0.15))
    spans = stretches(qs, opt("--span", 2.0))
    print("counter: %d reads kept, %d -> %d (reached at %.2fs); %d quiet instants, %d stretches"
          % (len(T), V[0], V[-1], T[int(np.argmax(V))], len(qs), len(spans)))
    # --pass <sprite pass .pkl>: which stretches hold something is read off the lane rails, which
    # the pass measured once for every correlation floor. An extraction's own holds are a poor
    # stand-in when comparing floors: a low floor invents holds, and a stretch any floor put a
    # hold in could not be judged for any of them - on L (PIU Edit) D27 that left 4 of 20.
    rails = None
    if "--pass" in args:
        import pickle
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import receptors as R
        scan = pickle.load(open(args[args.index("--pass") + 1], "rb"))[5]
        rails = [s for col in R.rails(scan, 0.40, 0.065).values() for s in col]
        print("hold rails from the pass: %d" % len(rails))
    results = {f: judge(json.load(open(f)), spans, rails) for f in files[1:]}
    free = [i for i in range(len(spans)) if all(r[i]["holds"] == 0 for r in results.values())]
    moved = sum(spans[i][1][1] - spans[i][0][1] for i in free)
    print("%d stretches have no hold in any extraction; the counter moved %d across them" % (len(free), moved))
    for f, res in results.items():
        exact = sum(1 for i in free if res[i]["rows"] == res[i]["moved"])
        found = sum(res[i]["rows"] for i in free)
        off = sum(abs(res[i]["rows"] - res[i]["moved"]) for i in free)
        print("  %-36s %3d of %d exact   rows %d (%+d)   %d off in total"
              % (os.path.basename(f), exact, len(free), found, found - moved, off))
    if "--list" in args or len(results) == 1:
        for f, res in results.items():
            print(os.path.basename(f))
            for w in res:
                flag = ("held (%d)" % w["holds"]) if w["holds"] else (
                    "ok" if w["rows"] == w["moved"] else "LOOK %+d" % (w["rows"] - w["moved"]))
                print("  %7.2f-%7.2f  counter +%-4d rows %-4d %s" % (w["a"], w["b"], w["moved"], w["rows"], flag))

if __name__ == "__main__":
    main()
