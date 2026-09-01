# Shared helpers for turning raw counter reads into a cumulative curve.
#
# continuity_repair: on a doubles chart the counter sits in the middle of the play field, so
# notes cross it constantly and the reader drops whichever digit is covered - 113 reads as 12,
# 110 as 10, 794 as 94. Every such read is the true value minus some multiple of 100 (or, for
# a covered hundreds AND tens digit, worse). Given the previous accepted value and the time
# since it, the true value is the candidate v + 100k that continues the run at a plausible
# rate; nothing fitting means a genuine reset (v below the estimate) or junk (v far above).
import bisect

def continuity_repair(pts, rate_max=60.0, cap=10**9, confirm=3):
    """pts: sorted [(t, v)] raw reads. Returns [(t, v_repaired)] with dropped hundreds restored.
    A read below the estimate that no candidate explains is a RESET only if the next few reads
    stay low as well; a lone low read (two digits covered at once) is skipped, so it cannot
    drag the estimate down and turn the following true reads into fake resets."""
    out, est = [], None
    for i, (t, v) in enumerate(pts):
        if est is None:
            out.append((t, v)); est = (t, v); continue
        dt = max(t - est[0], 1e-3)
        lo, hi = est[1] - 2, est[1] + rate_max * dt + 3
        cands = [v + 100 * k for k in range(0, 10) if v + 100 * k <= cap]
        ok = [c for c in cands if lo <= c <= hi]
        if ok:
            pick = min(ok); out.append((t, pick)); est = (t, pick)
        elif v < est[1]:
            # Reset or covered digits? Look at the next few reads: if they continue the run
            # modulo 100 (a sustained dropped-hundreds stretch, as on doubles charts where a
            # note parks over the leading digit), this is NOT a reset; skip the read.
            nxt = pts[i + 1:i + 1 + confirm]
            def continues(t2, w):
                hi2 = est[1] + rate_max * max(t2 - est[0], 1e-3) + 3
                return any(lo <= w + 100 * k <= hi2 for k in range(0, 10))
            fits = sum(1 for t2, w in nxt if continues(t2, w))
            if len(nxt) >= 2 and fits >= 2:
                continue                              # covered digits, run continues
            if len(nxt) >= 2 and all(w < est[1] * 0.6 for _, w in nxt):
                out.append((t, v)); est = (t, v)      # confirmed reset; segmentation decides
            # else: a lone unexplained drop - skip it
        else:
            out.append((t, v))                        # too fast to be continuity; leave it to LIS
    return out

def lis_chain(pp):
    """Longest non-decreasing subsequence of [(t, v)] - discards transient misreads."""
    tails, tidx, parent = [], [], [-1] * len(pp)
    for i, (t, v) in enumerate(pp):
        j = bisect.bisect_right(tails, v)
        if j == len(tails): tails.append(v); tidx.append(i)
        else: tails[j] = v; tidx[j] = i
        parent[i] = tidx[j - 1] if j > 0 else -1
    chain, k = [], (tidx[-1] if tidx else -1)
    while k != -1: chain.append(pp[k]); k = parent[k]
    return chain[::-1]

def build_anchors(pts, offsets, total):
    """Segment reads at reset boundaries, offset each segment by its prior peaks, LIS within,
    collapse plateaus. offsets: [(boundary_video_t, cum_offset)] descending, ending (-1, 0)."""
    def seg_off(t):
        for b, o in offsets:
            if t >= b: return o
    segs = {}
    for t, v in pts: segs.setdefault(seg_off(t), []).append((t, v))
    anchors = []
    for off, pp in sorted(segs.items()):
        cur = None
        for t, v in lis_chain(pp):
            cum = v + off
            if cum > total: continue
            if cur and cur[2] == cum: cur[1] = t
            else:
                if cur: anchors.append(cur)
                cur = [t, t, cum]
        if cur: anchors.append(cur)
    anchors.sort()
    assert all(a[2] <= b[2] for a, b in zip(anchors, anchors[1:])), "non-monotone"
    return anchors
