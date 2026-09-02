# Per-chart driver for note extraction: scan the whole certified video, find the offset from
# the receptor flashes, list every hold rail with its head flash, convert to snapped beats,
# and propose the edit_notes add-hold commands - together with what the combo counter accrued
# across each rail, so the ticks can be priced. Prints; changes nothing.
#
#   python -X utf8 tools/extract_holds.py "<chart>" [offset]
#   env: RR_THRESH flash height (60), RR_OCC rail occupancy (0.45)
import bisect
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def lookup(chart):
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    for vid, e in cert.items():
        info = (e.get("charts") or {}).get(chart)
        if info:
            side = info["side"]
            s = e[side]
            other = e.get("2p" if side == "1p" else "1p") or {}
            full = not other.get("judged")
            return vid, side, s, full, float(e.get("t") or 0)
    raise SystemExit(f"{chart}: not in the certification ledger")

def main():
    chart = sys.argv[1]
    a_given = float(sys.argv[2]) if len(sys.argv) > 2 else None
    vid, side, s, full, t_end = lookup(chart)
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    key, ssc_rel = smap[chart]["key"], smap[chart]["ssc_rel"]
    typ = chart.split()[-1][0]
    band = "C" if full else ("L" if side == "1p" else "R")
    ncols = 10 if typ == "D" else 5
    judged, mc = int(s["judged"]), int(s["maxcombo"])
    print(f"{chart}: {vid} {side} {'full' if full else 'split'} -> band {band}, {ncols} columns; judged {judged}, maxcombo {mc}, "
          f"P{s['perfect']} G{s['great']} Gd{s['good']} B{s['bad']} M{s['miss']}")
    sc = R.scan(vid, 0.5, max(t_end - 0.5, 10.0), band, ncols)
    print(f"  receptors x {sc['xs']} (pitch {np.mean(np.diff(sc['xs'])):.1f}); {len(sc['ts'])} frames at {sc['fps']:.0f} fps")
    ons, hs = R.onsets(sc, float(os.environ.get("RR_THRESH", "60")))
    rl = R.rails(sc, float(os.environ.get("RR_OCC", "0.45")))
    rows, taps, beat_at = R.chartstruct(key, ncols)
    ntaps = sum(1 for r in rows if "1" in r["Line"])          # judged events are ROWS: a jump is one
    t_first, t_last = float(rows[0]["Time"]), float(rows[-1]["Time"])
    import re
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9]+)*?)_(ARCADE|SHORTCUT|REMIX|FULLSONG)$", key)   # desc words joined by spaces, suffix after the last underscore
    block = f"{m.group(1).replace('_', ' ')}_{m.group(2)}"
    if a_given is None:
        a, hit, total = R.match_offset(ons, taps)
        print(f"  offset {a:.2f}: {hit} of {total} flashes sit on a file tap (+/-60ms); file has {ntaps} tap/head events, "
              f"flash heights p50/p90/max {np.percentile(hs, 50):.0f}/{np.percentile(hs, 90):.0f}/{hs.max():.0f}")
    else:
        a = a_given
    # counter reads, for the accrual across each rail
    reads = []
    for b in (band, "C", "L", "R"):
        p = os.path.join(ROOT, "work", "combo", f"{vid}.{b}.jsonl")
        if os.path.exists(p):
            reads = sorted((t, v) for t, v, c in (json.loads(l) for l in open(p, encoding="utf-8")) if v is not None and c >= 0.6 and v <= mc)
            break
    rt = [t for t, _ in reads]
    all_taps = sorted(t for v in taps.values() for t in v)
    def taps_in(c0, c1):
        return bisect.bisect_right(all_taps, c1) - bisect.bisect_right(all_taps, c0)
    def accrual(v0, v1):
        i, j = bisect.bisect_left(rt, v0), bisect.bisect_right(rt, v1)
        if j - i < 2:
            return None
        vals = [v for _, v in reads[i:j]]
        return max(vals) - min(vals)
    print(f"  rails inside the chart ({sum(1 for c in rl for s0, e0 in rl[c] if t_first - 0.5 <= s0 - a <= t_last + 3.0)} of {sum(len(v) for v in rl.values())} detected):")
    cmds = []
    for c in sorted(rl):
        for s0, e0 in rl[c]:
            if s0 - a < t_first - 0.5 or s0 - a > t_last + 3.0:
                continue                                    # title card / result screen, not the chart
            heads = [o for o in ons[c] if s0 - 0.30 <= o <= s0 + 0.05]
            head_t = heads[-1] if heads else s0 - 0.10
            tail_t = e0 + 0.03
            ch, ct = head_t - a, tail_t - a
            bh, bt = R.snap_beat(beat_at(ch)), R.snap_beat(beat_at(ct))
            near = [t for t in taps[c] if abs(t - ch) <= 0.07]
            acc = accrual(head_t, tail_t)
            est = None if acc is None else acc - taps_in(ch, ct)
            print(f"    col {c}: video {head_t:6.2f}-{tail_t:6.2f}  chart {ch:6.2f}-{ct:6.2f} ({ct-ch:.2f}s)  beats {bh:.3f}-{bt:.3f}  "
                  f"head {'ON a file tap' if near else 'new note'}  counter +{acc if acc is not None else '?'} incl. {taps_in(ch, ct)} taps -> ~{est if est is not None else '?'} ticks")
            cmds.append(f'$PY tools/edit_notes.py add-hold "simfiles/{ssc_rel}" "{block}" {c} {bh} {bt}')
    if cmds:
        print("  proposed edits:")
        for cmd in cmds:
            print("    " + cmd)
    # grid check: file taps without a flash, flashes without a file tap
    tol = 0.09
    fo = {c: [t for t in taps[c] if not any(abs(o - a - t) <= tol for o in ons[c])] for c in taps}
    vo = {c: [o - a for o in ons[c] if not any(abs(o - a - t) <= tol for t in taps[c])] for c in ons}
    nfo, nvo = sum(len(v) for v in fo.values()), sum(len(v) for v in vo.values())
    print(f"  grid: {nfo} file events without a flash, {nvo} flashes without a file event (misses do not flash; drills under-count)")
    for c in taps:
        if fo[c] or vo[c]:
            print(f"    col {c}: file-only {' '.join(f'{t:.2f}' for t in fo[c][:10])}{' ...' if len(fo[c]) > 10 else ''} | "
                  f"video-only {' '.join(f'{t:.2f}' for t in vo[c][:10])}{' ...' if len(vo[c]) > 10 else ''}")
    print(f"  owed: judged {judged} - taps {ntaps} = {judged - ntaps} hold events")

if __name__ == "__main__":
    main()
