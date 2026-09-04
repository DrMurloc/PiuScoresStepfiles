# Compare the game's judged events against the file's notes, one for one.
#
# Every judged hit flashes its column's receptor; a MISS does not (no input happened). So on
# a play with few misses the flashes ARE the game's tap grid, and matching them against the
# file's rows says exactly which notes the file has that the game does not (file-only) and
# which the game plays that the file lacks (video-only). That is what a re-step needs.
#
# Read it honestly:
#   - expect about `miss` unmatched file notes even on a correct file - those are the misses.
#   - through a drill the receptor's white level clips and hits merge, so the video
#     UNDER-counts fast streams; a video-only deficit inside a dense run is the reader's
#     blindness, not the file's. Clusters are printed with their local note density.
#   - holds flash only at the head.
#
#   python -X utf8 tools/flash_grid.py "<chart>" <offset>|--sweep [--tol 0.08] [--from T] [--to T]
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(chart):
    raw = json.load(open(os.path.join(ROOT, "sources", "certification-2026-08-30.json"), encoding="utf-8"))
    cert = raw if isinstance(raw, dict) else {c["vid"]: c for c in raw if isinstance(c, dict)}
    vid, e = next((v, e) for v, e in cert.items() if chart in (e.get("charts") or {}))
    side = e["charts"][chart].get("side") or "1p"
    s = e[side]
    other = e.get("2p" if side == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
    ncols = 10 if chart.split()[-1][0] == "D" else 5
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    rows, _, beat_at = R.chartstruct(smap[chart]["key"], ncols)
    notes = []
    for r in rows:
        for c, ch in enumerate(r["Line"].lstrip("`")):
            if ch in "12":
                notes.append((float(r["Time"]), c, float(r["Beat"])))
    return vid, e, s, band, ncols, sorted(notes), beat_at, float(rows[-1]["Time"])

def match(notes, flashes, a, tol):
    """Greedy nearest match per column between file notes (chart time) and flashes (video)."""
    by_col = {}
    for t, c in flashes:
        by_col.setdefault(c, []).append(t - a)
    for c in by_col:
        by_col[c].sort()
    used = {c: [False] * len(v) for c, v in by_col.items()}
    file_only, matched = [], 0
    for t, c, b in notes:
        arr = by_col.get(c, [])
        i = bisect.bisect_left(arr, t)
        best, bi = tol + 1, -1
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(arr) and not used[c][j] and abs(arr[j] - t) < best:
                best, bi = abs(arr[j] - t), j
        if bi >= 0:
            used[c][bi] = True
            matched += 1
        else:
            file_only.append((t, c, b))
    video_only = [(arr[j], c) for c, arr in by_col.items() for j in range(len(arr)) if not used[c][j]]
    return matched, file_only, sorted(video_only)

def main():
    chart = sys.argv[1]
    tol = float(sys.argv[sys.argv.index("--tol") + 1]) if "--tol" in sys.argv else 0.08
    vid, e, s, band, ncols, notes, beat_at, t_last = load(chart)
    judged, mc = int(s["judged"]), int(s["maxcombo"])
    miss, bad, good = int(s["miss"]), int(s["bad"]), int(s["good"])
    t_end = float(e.get("t") or 150)
    sc = R.scan(vid, 0.5, t_end - 0.5, band, ncols)
    ons, _ = R.onsets(sc, 60.0)
    flashes = [(t, c) for c in range(ncols) for t in ons[c]]
    print(f"{chart}: {vid} band {band}, judged {judged} (miss {miss}, bad {bad}, good {good}), "
          f"file notes {len(notes)}, flashes {len(flashes)}")

    if sys.argv[2] == "--sweep":
        best = []
        for a100 in range(0, int(t_end * 100) - int(t_last * 100), 5):
            a = a100 / 100
            m, _, _ = match(notes, flashes, a, tol)
            best.append((m, a))
        best.sort(reverse=True)
        print("  best offsets (matched of %d file notes):" % len(notes))
        for m, a in best[:6]:
            print(f"    a = {a:6.2f}   matched {m:5d}  ({100 * m / len(notes):.1f}%)")
        return
    a = float(sys.argv[2])
    lo = float(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else -1e9
    hi = float(sys.argv[sys.argv.index("--to") + 1]) if "--to" in sys.argv else 1e9
    matched, file_only, video_only = match(notes, flashes, a, tol)
    print(f"  at a = {a}: matched {matched}/{len(notes)} file notes; "
          f"file-only {len(file_only)} (expect ~{miss} from misses), video-only {len(video_only)}")

    def clusters(items, gap=0.6):
        out = []
        for it in items:
            if out and it[0] - out[-1][-1][0] <= gap:
                out[-1].append(it)
            else:
                out.append([it])
        return out

    fo = [x for x in file_only if lo <= x[0] <= hi]
    vo = [x for x in video_only if lo <= x[0] <= hi]
    print(f"\n  FILE-ONLY (the file has these, the game did not judge them) - {len(fo)} in window:")
    for cl in clusters(fo):
        n = bisect.bisect_right([x[0] for x in notes], cl[-1][0]) - bisect.bisect_left([x[0] for x in notes], cl[0][0])
        span = cl[-1][0] - cl[0][0]
        dens = f"{n / span:.1f}/s" if span > 0.05 else "single"
        print(f"    {cl[0][0]:7.2f}-{cl[-1][0]:7.2f}  b{cl[0][2]:8.3f}  {len(cl):3d} notes  cols {sorted({x[1] for x in cl})}  local {dens}")
    print(f"\n  VIDEO-ONLY (the game judged these, the file lacks them) - {len(vo)} in window:")
    for cl in clusters(vo):
        print(f"    {cl[0][0]:7.2f}-{cl[-1][0]:7.2f}  b{beat_at(cl[0][0]):8.3f}  {len(cl):3d} events  cols {sorted({x[1] for x in cl})}")

if __name__ == "__main__":
    main()
