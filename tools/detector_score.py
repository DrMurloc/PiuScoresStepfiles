# How good is the rail detector, measured against charts whose holds we KNOW are right?
#
# The repaired census charts are the oracle: their holds were derived from footage and verified
# against the game's own note count, so a rail the detector reports there either matches a real
# hold or is something else on screen pretending to be one.
#
# The first run of this (2026-09-09, eight charts, 32 real holds) is the number that matters for
# planning: RECALL 94% - it finds nearly every hold - but 179 of its 209 detections matched no
# hold at all, and the head it reports is a median 0.26s from the truth. A 16th note at 150bpm
# is 0.10s apart, so those edges cannot place a note on a beat grid.
#
# That is why the pipeline reads the combo counter instead of reading the chart: the detector
# knows roughly WHERE holds are but cannot say which of its candidates are real or exactly when
# they start. Transcribing a chart from footage - what a person does by hand - needs both, and
# both are ordinary engineering rather than missing information.
#
#   python -X utf8 tools/detector_score.py "<chart>" ["<chart>" ...]
import json, os, sys
sys.path.insert(0, r"C:\Users\jonec\repos\PiuScoresStepfiles\tools")
import receptors as R, corpus_map
ROOT = r"C:\Users\jonec\repos\PiuScoresStepfiles"
os.chdir(ROOT)
rep = {r["chart"]: r for r in json.load(open("sources/repairs.json", encoding="utf-8"))}
cert = corpus_map.certification()
smap = corpus_map.chart_map()
tot = dict(true=0, found=0, matched=0, extra=0)
print("%-40s %5s %5s %5s %5s  %s" % ("chart", "true", "seen", "hit", "miss", "median |head err|"))
for name in sys.argv[1:]:
    if name not in rep: print("  skip", name); continue
    ncols = 10 if name.split()[-1][0] == "D" else 5
    key = smap[name]["key"]
    rows, taps, beat_at = R.chartstruct(key, ncols)
    fh, op = [], {}
    for row in rows:
        tt = float(row["Time"])
        for i, ch in enumerate(row["Line"].lstrip("`")):
            if ch == "2": op[i] = tt
            elif ch == "3" and i in op: fh.append((i, op.pop(i), tt))
    vid, e = next((v, e) for v, e in cert.items() if name in (e.get("charts") or {}))
    side = e["charts"][name].get("side") or "1p"
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    # the offset the census recorded for this chart, via its flash match
    sc = R.scan(vid, 0.5, float(e.get("t") or 150) - 0.5, band, ncols)
    ons, _ = R.onsets(sc, 60.0)
    mo = R.match_offset(ons, taps)
    a = mo[0] if isinstance(mo, tuple) else mo
    if a is None: print("  %-40s (no offset)" % name[:40]); continue
    rl = R.rails(sc, occ_th=0.40, min_len=0.15)
    vh = sorted((c, s0 - a, e0 - a) for c in rl for s0, e0 in rl[c])
    used, errs = set(), []
    for col, t0, t1 in fh:
        best, bi = 0.45, -1
        for j, (c2, v0, v1) in enumerate(vh):
            if j in used or c2 != col: continue
            if abs(v0 - t0) < best: best, bi = abs(v0 - t0), j
        if bi >= 0: used.add(bi); errs.append(best)
    med = sorted(errs)[len(errs)//2] if errs else float("nan")
    print("%-40s %5d %5d %5d %5d  %.3fs" % (name[:40], len(fh), len(vh), len(errs), len(fh)-len(errs), med))
    tot["true"] += len(fh); tot["found"] += len(vh); tot["matched"] += len(errs); tot["extra"] += len(vh)-len(errs)
print()
if tot["true"]:
    print("RECALL  %d of %d true holds detected (%.0f%%)" % (tot["matched"], tot["true"], 100*tot["matched"]/tot["true"]))
    print("EXTRA   %d detected rails matched no real hold" % tot["extra"])
