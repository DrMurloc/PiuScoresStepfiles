# Decide a play's run structure from its reads by CLOSURE. After a value like 95 the reads
# "4, 5, 6" are either a reset or a rollover with the hundreds covered (104, 105, 106), and
# the digits cannot tell them apart - but the result screen can: the run peaks must sum to
# P+G with at most B+M resets, and a tail resting at maxcombo is its own run. So every low
# restart is a candidate boundary, and the subset whose peaks close best on P+G wins; a
# candidate not chosen is treated as dropped hundreds and the run continues through it.
import itertools

def fix_digits(v, cap):
    """Reads of a 9 as a 5 and a rail's leading 1 give a few alternatives for one read."""
    s = str(v)
    fives = [i for i, ch in enumerate(s) if ch == "5"]
    out = {v}
    for mask in range(1, 1 << len(fives)):
        chars = list(s)
        for k, i in enumerate(fives):
            if mask >> k & 1:
                chars[i] = "9"
        out.add(int("".join(chars)))
    if v >= 100:
        out.add(v - 100)
    return {w for w in out if 0 <= w <= cap}

def repair_run(pts, cap, rate_max=60.0):
    """Within one run: pick each read's best alternative that continues the run (including
    dropped hundreds restored); skip a read nothing explains. Returns [(t, v)]."""
    out, est = [], None
    pts_after = {t: pts[i + 1:i + 3] for i, (t, _) in enumerate(pts)}
    for t, v in pts:
        if est is None:
            w = min(fix_digits(v, cap) or {v})
            out.append((t, w))
            est = (t, w)
            continue
        dt = max(t - est[0], 1e-3)
        lo, hi = est[1] - 2, est[1] + rate_max * dt + 3
        cands = {w + 100 * k for w in fix_digits(v, cap) for k in range(0, 10) if w + 100 * k <= cap}
        ok = [c for c in cands if lo <= c <= hi]
        if ok:
            pick = min(ok, key=lambda c: abs(c - est[1]))
            out.append((t, pick))
            est = (t, pick)
            continue
        # a finale bomb outruns any rate cap (Slam S18: 027 -> 300 in 0.2s). A value that
        # PERSISTS - the same read again within the next two, or maxcombo itself - is the
        # counter resting, not a misread, and is accepted at any rate
        alts = {w for w in fix_digits(v, cap) if w >= est[1] - 2}
        if alts:
            nxt = {w for _, nv in pts_after.get(t, []) for w in fix_digits(nv, cap)}
            keep = [w for w in alts if w == cap or w in nxt]
            if keep:
                pick = max(keep)
                out.append((t, pick))
                est = (t, pick)
    return out

def candidates(pts):
    """Indices where the counter re-emerges low (<= 12) and climbs slowly after a drop: the
    places a reset can be."""
    idx, peak = [], -1
    for i, (t, v) in enumerate(pts):
        if peak >= 0 and v <= 12 and v < peak - 3:
            nxt = [w for _, w in pts[i + 1:i + 3]]
            if len(nxt) == 2 and all(w <= v + 8 for w in nxt) and (i == 0 or t - pts[i - 1][0] < 4.0 or True):
                idx.append(i)
                peak = v
                continue
        peak = max(peak, v)
    return idx

def solve(pts, resets, pg, mc, max_candidates=14):
    """pts: raw reads [(t, v)] (v <= mc). Returns (runs, peaks, score) where runs is a list of
    repaired [(t, v)] lists, or None when no subset closes within tolerance."""
    cand = candidates(pts)
    if len(cand) > max_candidates:
        # keep the deepest drops
        depth = {i: (max(v for _, v in pts[:i]) - pts[i][1]) for i in cand}
        cand = sorted(sorted(cand, key=lambda i: -depth[i])[:max_candidates])
    best = None
    for k in range(0, min(resets, len(cand)) + 1):
        for subset in itertools.combinations(cand, k):
            bounds = [0] + list(subset) + [len(pts)]
            runs = [repair_run(pts[a:b], mc) for a, b in zip(bounds, bounds[1:])]
            runs = [r for r in runs if r]
            peaks = [max(v for _, v in r) for r in runs]
            rest = runs[-1][-1][1]
            score = abs(sum(peaks) - pg)
            if rest == mc:
                score += 0          # a tail at maxcombo is the expected shape
            elif peaks[-1] > mc:
                score += 50
            if best is None or score < best[0]:
                best = (score, runs, peaks)
    if best is None or best[0] > max(3, 0.02 * pg):
        if best is not None:
            print("  best attempt: peaks " + str(best[2]) + f" sum {sum(best[2])} vs P+G {pg}; runs "
                  + "  ".join(f"{r[0][0]:.1f}-{r[-1][0]:.1f}:{r[0][1]}->{max(v for _, v in r)}" for r in best[1]))
        return None
    return best[1], best[2], best[0]
