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
    overlapping jump-holds differs from union-merged spans, so indexes never zip)."""
    sc = StepchartSSC.from_song_ssc_file(path, tag)
    df, holdticks, msg = stepchart_ssc_to_chartstruct(sc)
    taps = int(df["Line"].str.contains("1", regex=False).sum())
    segs = [(t[0], t[1], round(t[2])) for t in holdticks]
    if regions is None:
        return taps, [s[2] for s in segs]
    sums = [0] * len(regions)
    for s0, s1, tk in segs:
        mid = (s0 + s1) / 2
        best, bi = None, None
        for i, r in enumerate(regions):
            if r["t0"] - 0.1 <= mid <= r["t1"] + 0.1:
                bi = i
                break
            d = min(abs(mid - r["t0"]), abs(mid - r["t1"]))
            if best is None or d < best:
                best, bi = d, i
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
            sections[i] = re.sub(r"#TICKCOUNTS:.*?;", f"#TICKCOUNTS:{new_tc};", sections[i],
                                 count=1, flags=re.S)
            return "#NOTEDATA:;".join(sections), True
    return text, False

def main():
    path, tag = sys.argv[1], sys.argv[2]
    targets = json.load(open(sys.argv[3], encoding="utf-8"))
    judged = int(sys.argv[4])
    original = open(path, encoding="utf-8", newline="").read()
    tuner_idx = next(i for i, t in enumerate(targets) if t.get("tuner"))

    rates = [max(0, round(t["target"] / max(t["b1"] - t["b0"], 0.5))) for t in targets]
    text = original
    for it in range(16):
        tc = build_tickcounts(targets, rates, None)
        text, ok = patch(original, tag, tc)
        assert ok, "block not found"
        open(path, "w", encoding="utf-8", newline="").write(text)
        taps, ticks = derive(path, tag, regions=targets)
        implied = taps + sum(ticks)
        print(f"iter {it}: rates {rates} -> per-hold {ticks}, implied {implied} (target {judged})")
        if implied == judged and all(
                abs(tk - t["target"]) <= (10**9 if i == tuner_idx else 1)
                for i, (tk, t) in enumerate(zip(ticks, targets))):
            print("CONVERGED")
            for (tk, t) in zip(ticks, targets):
                print(f"  hold beat {t['b0']:>7.2f}..{t['b1']:<7.2f} target {t['target']:>4} -> authored {tk}")
            return
        # per-hold nudge (non-tuner): rate += sign(target - derived) when off by > 1
        for i, (tk, t) in enumerate(zip(ticks, targets)):
            if i == tuner_idx:
                continue
            if abs(tk - t["target"]) > 1:
                span = max(t["b1"] - t["b0"], 0.5)
                step = round((t["target"] - tk) / span)
                step = max(-25, min(25, step))
                rates[i] = max(0, rates[i] + step)
            # within +/-1 of target: freeze — that is inside observation noise, and
            # chasing it across many holds swamps the tuner's exact correction
        # tuner absorbs the global residue: adjust its uniform rate, then split beats
        t = targets[tuner_idx]
        span = t["b1"] - t["b0"]
        resid = judged - implied
        whole = round(resid / span)
        if whole:
            rates[tuner_idx] = max(0, rates[tuner_idx] + whole)
        else:
            # sub-beat correction: split the tuner span into 1-beat segments and
            # raise/lower the first k segments by 1
            k = abs(resid)
            base = rates[tuner_idx]
            step = 1 if resid > 0 else -1
            segs = []
            b = t["b0"]
            while b < t["b1"] - 1e-9:
                segs.append((b, base + (step if len(segs) < k else 0)))
                b += 1.0
            t["split"] = segs
    print("DID NOT CONVERGE — file restored")
    open(path, "w", encoding="utf-8", newline="").write(original)

if __name__ == "__main__":
    main()
