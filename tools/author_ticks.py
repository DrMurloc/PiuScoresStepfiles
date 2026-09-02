# Authors a block's #TICKCOUNTS so the annotation pipeline derives target per-hold
# tick counts, with one designated "tuner" hold absorbing rounding residue via
# beat-granular rate splits so the implied judged total lands EXACTLY on target.
#
#   python -X utf8 tools/author_ticks.py <sscPath> <descriptionTag> <targetsJson> <judged>
#
# targetsJson: [{"b0": 8.0, "b1": 12.0, "target": 0}, ...] in hold order; exactly one
# entry may carry "tuner": true. Writes the file in place (LF preserved) and verifies
# by running the piu-annotate converter until implied == judged.
import json
import re
import sys

sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
from piu_annotate.formats.sscfile import StepchartSSC              # noqa: E402
from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct  # noqa: E402

def derive(path, tag, regions=None):
    """taps + per-hold ticks; when `regions` (list of {t0,t1}) is given, their hold
    segments are aggregated into those time regions (converter segmentation of
    overlapping jump-holds differs from union-merged spans, so indexes never zip).

    Segments are assigned by MAXIMUM OVERLAP, not by midpoint. On drill charts the
    converter emits more segments than there are regions (165 vs 145 on Witch Doctor
    S19) and they are ~0.1s long, so a midpoint can land just outside its own region:
    the neighbour then absorbs two segments while the true owner reads 0. A region
    stuck at 0 can never respond to its own rate, so the nudge loop raises it forever
    and the whole schedule diverges. Overlap has no such blind spot, and a segment
    that overlaps nothing still falls back to the nearest region rather than vanishing."""
    sc = StepchartSSC.from_song_ssc_file(path, tag)
    df, holdticks, msg = stepchart_ssc_to_chartstruct(sc)
    taps = int(df["Line"].str.contains("1", regex=False).sum())
    segs = [(t[0], t[1], round(t[2])) for t in holdticks]
    if regions is None:
        return taps, [s[2] for s in segs]
    sums = [0] * len(regions)
    for s0, s1, tk in segs:
        best_ov, bi = 0.0, None
        for i, r in enumerate(regions):
            ov = min(s1, r["t1"]) - max(s0, r["t0"])
            if ov > best_ov:
                best_ov, bi = ov, i
        if bi is None:                      # touches no region: nearest edge wins
            mid = (s0 + s1) / 2
            bi = min(range(len(regions)),
                     key=lambda i: min(abs(mid - regions[i]["t0"]), abs(mid - regions[i]["t1"])))
        sums[bi] += tk
    return taps, sums

def build_tickcounts(holds, rates, splits):
    entries = [(0.0, 0)]
    for h, r in zip(holds, rates):
        if h.get("split"):
            for b, rr in h["split"]:
                entries.append((b, rr))
        else:
            entries.append((h["b0"], r))
        entries.append((h["b1"], 0))
    entries.sort()
    # collapse duplicates (chained holds share a beat: later entry wins)
    out = {}
    for b, r in entries:
        out[b] = r
    return ",\n".join(f"{b:.6f}={r}" for b, r in sorted(out.items()))

def patch(text, desc_tag, new_tc):
    desc = desc_tag.split("_")[0].replace(" ", "_")
    # find the NOTEDATA section whose DESCRIPTION is exactly the code (e.g. S13)
    code = desc_tag.rsplit("_", 1)[0]
    sections = text.split("#NOTEDATA:;")
    for i in range(1, len(sections)):
        if re.search(rf"#DESCRIPTION:{re.escape(code)};", sections[i]):
            if re.search(r"#TICKCOUNTS:", sections[i]):
                sections[i] = re.sub(r"#TICKCOUNTS:.*?;", f"#TICKCOUNTS:{new_tc};", sections[i],
                                     count=1, flags=re.S)
            else:
                # a block with no schedule of its own inherits the song header's (All I Want
                # For X-mas S5 rode a song-level "0.000=2"); give it one, after the description
                sections[i] = re.sub(rf"(#DESCRIPTION:{re.escape(code)};)(\r?\n)", rf"\1\2#TICKCOUNTS:{new_tc};\2", sections[i], count=1)
            return "#NOTEDATA:;".join(sections), True
    return text, False

def main():
    path, tag = sys.argv[1], sys.argv[2]
    targets = json.load(open(sys.argv[3], encoding="utf-8"))
    judged = int(sys.argv[4])
    original = open(path, encoding="utf-8", newline="").read()
    tuner_idx = next(i for i, t in enumerate(targets) if t.get("tuner"))

    def report(ticks):
        # A converged TOTAL says nothing about the interior: the tuner can swallow whatever the
        # other regions could not reach (a 0.2s hold once took 182 ticks that way). Say how far
        # each region landed from its target, and name the ones that are clearly off.
        devs = [tk - t["target"] for tk, t in zip(ticks, targets)]
        worst = max(range(len(devs)), key=lambda i: abs(devs[i]))
        print(f"  regions under target: {sum(1 for d in devs if d < 0)} (sum {sum(d for d in devs if d < 0)}), "
              f"over: {sum(1 for d in devs if d > 0)} (sum {sum(d for d in devs if d > 0)})")
        print(f"  authored vs target: max deviation {devs[worst]:+d} at beat {targets[worst]['b0']:.2f}; "
              f"tuner authored {ticks[tuner_idx]} (target {targets[tuner_idx]['target']})")
        off = [(tk, t) for tk, t in zip(ticks, targets) if tk != t["target"]]
        for tk, t in off:
            if abs(tk - t["target"]) > 2 or len(off) <= 25:
                print(f"    region beat {t['b0']:.2f}..{t['b1']:.2f} ({t['t0']:.1f}-{t['t1']:.1f}s) target {t['target']} -> authored {tk}")

    rates = [max(0, round(t["target"] / max(t["b1"] - t["b0"], 0.5))) for t in targets]
    text = original
    stall = 0
    prev_resid = None
    best = None            # (|resid|, rates, tuner split) - the state the finisher starts from
    resids = []
    hist = [[] for _ in targets]   # per-region (rate, deviation) so an oscillating region can be
    frozen = set()                 # locked at its better neighbour instead of stalling everyone
    for it in range(28):
        tc = build_tickcounts(targets, rates, None)
        text, ok = patch(original, tag, tc)
        assert ok, "block not found"
        open(path, "w", encoding="utf-8", newline="").write(text)
        taps, ticks = derive(path, tag, regions=targets)
        implied = taps + sum(ticks)
        print(f"iter {it}: rates {rates} -> per-hold {ticks}, implied {implied} (target {judged})")
        if implied == judged:
            print("CONVERGED")
            for (tk, t) in zip(ticks, targets):
                print(f"  hold beat {t['b0']:>7.2f}..{t['b1']:<7.2f} target {t['target']:>4} -> authored {tk}")
            report(ticks)
            return
        resid = judged - implied
        if best is None or abs(resid) < best[0]:
            best = (abs(resid), list(rates), targets[tuner_idx].get("split"))
        resids.append(resid)
        # a two-cycle (two regions flipping a rate back and forth) never settles on its own;
        # stop chasing it and hand the best state seen to the finisher
        if len(resids) >= 6 and resids[-1] == resids[-3] and resids[-2] == resids[-4] and resids[-1] != resids[-2]:
            print("  two-cycle detected; handing the best state to the finisher")
            break
        # per-hold nudge (non-tuner): rate += sign(target - derived) when off by > 1
        for i, (tk, t) in enumerate(zip(ticks, targets)):
            if i == tuner_idx or i in frozen:
                continue
            dev = tk - t["target"]
            hist[i].append((rates[i], dev))
            d = [x[1] for x in hist[i][-3:]]
            if len(d) == 3 and d[0] * d[1] < 0 and d[1] * d[2] < 0:
                # flipping sign on every step: the target sits between two grid values this
                # region can reach, so lock the closer one and stop shaking the others
                rates[i] = min(hist[i], key=lambda x: abs(x[1]))[0]
                frozen.add(i)
                continue
            # a small target has to be exact: a 0.1s hold asked for 1 tick that gets 0 is
            # not "within noise", it is a whole hold gone, and a drill chart has hundreds
            # ...and so does every region whose rate grid can reach it: under two beats a
            # one-rate step moves the count by at most a tick or two, so "within +/-1" is
            # not noise there, it is drift - and a hundred regions each a tick short pooled
            # 41 ticks onto one tuner hold. Only a long region (two beats and up) keeps the
            # slack, because its grid genuinely skips values.
            span = max(t["b1"] - t["b0"], 0.5)
            thresh = 1 if (t["b1"] - t["b0"]) >= 2.0 else 0
            if abs(tk - t["target"]) > thresh:
                step = round((t["target"] - tk) / span)
                step = max(-25, min(25, step)) or (1 if t["target"] > tk else -1)
                rates[i] = max(0, rates[i] + step)
            # within +/-1 of target: freeze - that is inside observation noise, and
            # chasing it across many holds swamps the tuner's exact correction
        # tuner absorbs the global residue: adjust its uniform rate, then split beats
        t = targets[tuner_idx]
        t.pop("split", None)  # rebuild fresh - a stale split freezes the tuner
        span = t["b1"] - t["b0"]
        whole = int(0.7 * resid / span)
        if whole:
            rates[tuner_idx] = max(0, rates[tuner_idx] + whole)
        else:
            # sub-beat correction: split the tuner span into segments and
            # raise/lower the first k segments by 1
            base = rates[tuner_idx]
            step_len = max((t["b1"] - t["b0"]) / 8.0, 0.05)
            n_seg = int(round((t["b1"] - t["b0"]) / step_len))
            stall = stall + 1 if resid == prev_resid else 0
            prev_resid = resid
            bump_mag = 1 if step_len >= 0.5 else 8
            per_seg = max(bump_mag * step_len, 0.4)
            k = min(n_seg, int(round(abs(resid) / per_seg)) + stall)
            bump = bump_mag if resid > 0 else -bump_mag
            segs = []
            b = t["b0"]
            for j in range(n_seg):
                segs.append((round(b, 4), max(0, base + (bump if j < k else 0))))
                b += step_len
            t["split"] = segs
    # last resort: brute-force a two-segment schedule on the tuner around the best rates
    # seen - the converter's per-segment rounding creates plateaus the incremental loop
    # cannot always cross. The search width follows the residue it has to cover.
    import itertools
    rates = list(best[1])
    t = targets[tuner_idx]
    t.pop("split", None)
    base = rates[tuner_idx]
    b0, b1 = t["b0"], t["b1"]
    width = max(2, int(best[0] / max(b1 - b0, 0.5)) + 2)
    print(f"  finisher: best residue {best[0]}, tuner base rate {base}, search +/-{width}")
    for k in [x / 2 for x in range(0, int((b1 - b0) * 2) + 1)]:
        for r1, r2 in itertools.product(range(max(0, base - width), base + width + 1), repeat=2):
            if k == 0 and r2 != r1:
                continue
            t2 = dict(t)
            if k > 0:
                t2["split"] = [(b0, r1), (min(b0 + k, b1 - 0.25), r2)]
            tgts = targets[:tuner_idx] + [t2] + targets[tuner_idx + 1:]
            rr = list(rates)
            rr[tuner_idx] = r2 if k > 0 else r1
            tc = build_tickcounts(tgts, rr, None)
            text, ok = patch(original, tag, tc)
            open(path, "w", encoding="utf-8", newline="").write(text)
            taps, ticks = derive(path, tag, regions=targets)
            if taps + sum(ticks) == judged:
                print(f"CONVERGED (brute tuner r1={r1} r2={r2} k={k})")
                report(ticks)
                return
    print("DID NOT CONVERGE - file restored")
    open(path, "w", encoding="utf-8", newline="").write(original)

if __name__ == "__main__":
    main()
