# Candidate changes to note_extract's post-decode step, as tools/bench.py grades them.
#
# A candidate is a Rule: module constants of note_extract patched while post_decode runs
# (`patches`), and/or a function applied to post_decode's output (`post`). Each has a FAMILY (the
# bench caps held-out looks per family) and a code hash - the syntax tree of its function
# (tools/cachekey.py code_stamp: comments and docstrings do not count) plus its parameters - which
# `bench.py register` records in sources/benchmark/rules.jsonl BEFORE the rule is graded, and which
# `bench.py grade` checks again, so a rule cannot be adjusted after it has been looked at without
# becoming a new candidate that counts against the caps.
#
# A rule the gate accepts moves into note_extract.post_decode itself (one tools-only commit per
# rule) and stays here with accepted=<commit>, as the record of what was graded; the bench's
# baseline is then the production code, and the next candidate is measured against it.
#
# The DRILLS are sabotage the gate must reject (work/loop-buckets-2026-09-26.txt, bucket #5): each
# looks like an improvement on some number and destroys real information on another.
import bisect
import json

import numpy as np

from cachekey import code_stamp


class Rule:
    def __init__(self, name, family, doc, post=None, params=None, patches=None, drill=False, accepted=None, wants_pass=False):
        self.name, self.family, self.doc = name, family, doc
        self.post, self.params, self.patches = post, dict(params or {}), dict(patches or {})
        self.drill, self.accepted, self.wants_pass = drill, accepted, wants_pass

    @property
    def code_hash(self):
        """What the rule does, not what it is called: its function's syntax tree and its settings."""
        helpers = (rail_lag, lane_occupancy, by_column) + ((note_qmax,) if self.wants_pass else ())
        body = code_stamp(self.post, *helpers) if self.post else "none"
        return code_stamp_text(json.dumps(dict(post=body, params=self.params, patches=self.patches),
                                          sort_keys=True, separators=(",", ":")))

    def apply(self, notes, meta, scan):
        if not self.post:
            return notes
        if self.wants_pass:
            got = LAST_PASS[0]
            if got is None or got[5] is not scan:
                raise RuntimeError("the pass this rule reads is not the one being replayed")
            return self.post(notes, meta, scan, got, **self.params)
        return self.post(notes, meta, scan, **self.params)


LAST_PASS = [None]     # the sprite pass tools/bench.py's worker loaded last (a wants_pass rule reads it)


def code_stamp_text(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- shared measurements

def rail_lag(scan, notes):
    """note_extract.mark_holds' constant: the rail box sits 8px below the receptor band, so a rail
    is early by that distance over the scroll speed. The same arithmetic, so a rule reads the lane
    at the instant mark_holds would."""
    speeds = [-n["v"] for n in notes if n.get("v")]
    return ((scan["y1"] - scan["y0"]) / 2.0 + 8.0) / float(np.median(speeds)) if speeds else 0.06


def lane_occupancy(scan, col, t0, t1, lag):
    """Share of frames between two instants on which the lane under `col` read as held (the rail
    reader's own lane signal), or None when fewer than two frames fall between them."""
    i0, i1 = np.searchsorted(scan["ts"], t0 - lag), np.searchsorted(scan["ts"], t1 - lag)
    if i1 - i0 < 2:
        return None
    return float(np.mean(scan["lane"][i0:i1, col]))


def by_column(notes):
    cols = {}
    for k, n in enumerate(notes):
        cols.setdefault(n["col"], []).append(k)
    for idx in cols.values():
        idx.sort(key=lambda k: notes[k]["t"])
    return cols


def note_qmax(n, pass_, floor):
    """The strongest sprite correlation on this note's own streak: the pass's hits in its column, on
    the frames it was tracked over, within 6 px of the line it was fitted to (y = v t + c in the
    strip, c from where that line reaches the judgement row at the note's time)."""
    ts, scored = pass_[0], pass_[1]
    cst = n["yj"] - n["v"] * n["t"]
    i0, i1 = np.searchsorted(ts, n["first"] - 1e-6), np.searchsorted(ts, n["last"] + 1e-6)
    best = None
    for i in range(i0, i1):
        y = n["v"] * ts[i] + cst
        for a, b, q, s in scored[i][n["col"]]:
            if q >= floor and abs(a - y) <= 6 and (best is None or q > best):
                best = q
    return best


# ---------------------------------------------------------------- the drills

def naive_gap(notes, meta, scan, gap):
    """Drop the later of two notes in one column nearer than `gap` when the first is not a hold head:
    every tail cap of a short hold goes, and so does the second note of every fast jack."""
    drop = set()
    for idx in by_column(notes).values():
        for u, v in zip(idx, idx[1:]):
            if notes[v]["t"] - notes[u]["t"] < gap and notes[u].get("hold_end") is None and u not in drop:
                drop.add(v)
    return [n for k, n in enumerate(notes) if k not in drop]


def shift_hold_end(notes, meta, scan, dt):
    """Every release `dt` seconds later than the rail says."""
    for n in notes:
        if n.get("hold_end") is not None:
            n["hold_end"] = n["hold_end"] + dt
    return notes


# ---------------------------------------------------------------- candidates

def tail_cap(notes, meta, scan, max_hold, occ):
    """A hold's tail cap is the head's own sprite and arrives as a second note; mark_holds swallows it
    only inside a rail some note CLAIMED. On a short hold the rail often opens too late or too
    briefly for the head to claim it, and the cap survives as an extra. Drop the later of two notes
    in one column when the first opened no rail, they are under `max_hold` apart, and the lane read
    as held on at least `occ` of the frames between them - a panel held down, which a jack's two
    taps do not leave behind."""
    lag = rail_lag(scan, notes)
    drop = set()
    for c, idx in by_column(notes).items():
        for u, v in zip(idx, idx[1:]):
            nu, nv = notes[u], notes[v]
            if nu.get("hold_end") is not None or u in drop or not (0.0 < nv["t"] - nu["t"] < max_hold):
                continue
            o = lane_occupancy(scan, c, nu["t"], nv["t"], lag)
            if o is not None and o >= occ:
                drop.add(v)
    return [n for k, n in enumerate(notes) if k not in drop]


def loose_rail_cap(notes, meta, scan, got, dist, rail_len, rail_max, reach, occ_th, rail_min, qa, max_hold):
    """A short hold's tail cap, found by what the hold leaves on the lane rather than by the gap
    alone. The game lights the lane under a held panel, but under a hold of a quarter second or
    less the lit bar is faint and brief - under the 0.40 occupancy and 0.065 s mark_holds reads
    rails at - so the head claims nothing and the cap, the head's own sprite, survives as an
    extra. Read the lane looser (`occ_th`, `rail_min`) and that bar is there: it opens as the head
    arrives and it ENDS as the cap goes by, where a jack's first tap leaves a flash that does not
    wait for the second (measured on the tune split). And both sprites of a short hold correlate
    weaker than the chart's taps (the body runs through the matching window). Drop the later of two
    notes in one column under `max_hold` apart when the first opened no rail, a loose bar of
    `rail_len`..`rail_max` seconds opens within `dist` of the first and closes within `reach` of the
    second (the rail's lag taken out, as mark_holds does), and both notes' strongest correlation is
    under `qa` times the chart's median."""
    import receptors as R
    lag = rail_lag(scan, notes)
    rails = R.rails(scan, occ_th, rail_min)
    qs = [note_qmax(n, got, meta["floor"]) for n in notes]
    known = [q for q in qs if q is not None]
    if not known:
        return notes
    med = float(np.median(known))
    drop = set()
    for c, idx in by_column(notes).items():
        spans = rails.get(c, [])
        for u, v in zip(idx, idx[1:]):
            nu, nv = notes[u], notes[v]
            if nu.get("hold_end") is not None or u in drop or not (0.0 < nv["t"] - nu["t"] < max_hold):
                continue
            if qs[u] is None or qs[v] is None or qs[u] >= qa * med or qs[v] >= qa * med:
                continue
            if any(abs(a + lag - nu["t"]) <= dist and rail_len <= b - a <= rail_max and abs(b + lag - nv["t"]) <= reach
                   for a, b in spans):
                drop.add(v)
    return [n for k, n in enumerate(notes) if k not in drop]


def loose_rail_cap2(notes, meta, scan, got, dist, rail_len, rail_max, reach, occ_th, rail_min, qu_min, qu_max, qv_max,
                    speed_tol, min_gap, max_gap):
    """loose_rail_cap with the shape of a head and its cap held tighter, from what tailcap-b took on
    the tune split (15 real notes of 2,931): the two sprites belong to ONE object, so they scroll at
    one speed (`speed_tol`; the three it took on Vulcan S22 ran 42% apart); a head is a real arrow,
    so it is not the weakest detection on the chart (`qu_min`; Life is PIANO D21's six were 0.61-0.69
    of the median, no cap under 0.73); a cap sits within a hold of the head (`min_gap`..`max_gap`;
    no cap it removed was over 0.107 s); and a cap is weaker than a clean tap (`qv_max`)."""
    import receptors as R
    lag = rail_lag(scan, notes)
    rails = R.rails(scan, occ_th, rail_min)
    qs = [note_qmax(n, got, meta["floor"]) for n in notes]
    known = [q for q in qs if q is not None]
    if not known:
        return notes
    med = float(np.median(known))
    drop = set()
    for c, idx in by_column(notes).items():
        spans = rails.get(c, [])
        for u, v in zip(idx, idx[1:]):
            nu, nv = notes[u], notes[v]
            gap = nv["t"] - nu["t"]
            if nu.get("hold_end") is not None or u in drop or not (min_gap <= gap <= max_gap):
                continue
            if qs[u] is None or qs[v] is None or not (qu_min * med <= qs[u] < qu_max * med) or qs[v] >= qv_max * med:
                continue
            if not nu.get("v") or abs(nv["v"] / nu["v"] - 1.0) > speed_tol:
                continue
            if any(abs(a + lag - nu["t"]) <= dist and rail_len <= b - a <= rail_max and abs(b + lag - nv["t"]) <= reach
                   for a, b in spans):
                drop.add(v)
    return [n for k, n in enumerate(notes) if k not in drop]


RULES = {r.name: r for r in (
    Rule("baseline", "baseline", "note_extract.post_decode as it stands."),
    Rule("drill-gap80", "drill", "SABOTAGE: the naive < 80 ms same-column gap rule.", post=naive_gap,
         params=dict(gap=0.080), drill=True),
    Rule("drill-merge35", "drill", "SABOTAGE: MERGE = 0.035 (the pre-2026 merge that deleted real 34 ms jacks).",
         patches=dict(MERGE=0.035), drill=True),
    Rule("drill-holdend50", "drill", "SABOTAGE: every hold's release 50 ms later.", post=shift_hold_end,
         params=dict(dt=0.050), drill=True),
    Rule("tailcap-a", "tail-cap", "Suppress a tail cap on a hold under 0.25 s whose head the rail did not claim, "
         "lane occupancy >= 0.55 between them.", post=tail_cap, params=dict(max_hold=0.25, occ=0.55)),
    Rule("tailcap-b", "tail-cap", "Suppress a short hold's tail cap when a loose lane bar (occupancy 0.25, 0.03 s) of "
         "0.067-0.20 s opens within 20 ms of the head, which claimed no rail, and closes within 20 ms of the cap, and both "
         "notes correlate under 0.97 of the chart's median.", post=loose_rail_cap, wants_pass=True,
         params=dict(dist=0.020, rail_len=0.067, rail_max=0.20, reach=0.020, occ_th=0.25, rail_min=0.03, qa=0.97, max_hold=0.25)),
    Rule("tailcap-c", "tail-cap", "tailcap-b, and the pair scrolls at one speed (4%), the head correlates at 0.72-0.97 of the "
         "median and the cap under 0.92, 0.06-0.115 s apart.", post=loose_rail_cap2, wants_pass=True,
         params=dict(dist=0.020, rail_len=0.067, rail_max=0.20, reach=0.020, occ_th=0.25, rail_min=0.03, qu_min=0.72, qu_max=0.97,
                     qv_max=0.92, speed_tol=0.04, min_gap=0.060, max_gap=0.115)),
    Rule("tailcap-d", "tail-cap", "tailcap-c with every guard held to the central 90% (5th-95th percentile) of what tailcap-c "
         "removed on the tune split: bar 5-7 frames, opening within 19 ms, closing within 12 ms, speeds within 2%, head at "
         "0.78-0.945 and cap under 0.91 of the median, 0.065-0.100 s apart.", post=loose_rail_cap2, wants_pass=True,
         params=dict(dist=0.019, rail_len=0.075, rail_max=0.125, reach=0.012, occ_th=0.25, rail_min=0.03, qu_min=0.78, qu_max=0.945,
                     qv_max=0.91, speed_tol=0.02, min_gap=0.065, max_gap=0.100),
         accepted="note_extract.drop_short_caps (post_decode); held-out look 2026-09-27 17:24"),
    Rule("tailcap-e", "tail-cap", "tailcap-d with the bar allowed to open up to 35 ms from the head (the caps tailcap-d left on "
         "the tune split that failed only its bar test opened a median 24 ms from the head, and closed within 8 ms of the cap).",
         post=loose_rail_cap2, wants_pass=True,
         params=dict(dist=0.035, rail_len=0.075, rail_max=0.125, reach=0.012, occ_th=0.25, rail_min=0.03, qu_min=0.78, qu_max=0.945,
                     qv_max=0.91, speed_tol=0.02, min_gap=0.065, max_gap=0.100)),
)}
