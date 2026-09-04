# Turn a list of rails read off the footage into the file: for each rail, the head goes on the
# file's own row for that column when one sits within 120ms of the head time (the old files
# wrote hold heads as taps), else on the snapped beat; the tail on the snapped beat; then
# regenerate the chartstruct and price with finale_ticks, pinning the rails whose ticks were
# read locally from the counter and leaving the rest to closure.
#
#   python -X utf8 tools/apply_rails.py "<chart>" <offset> <rails.json> [--burst <beat> [--pre <rate>]]
#   rails.json: [{"col": 8, "head": 31.57, "tail": 31.93, "ticks": 20}, {"col": 3, ..., "ticks": null}, ...]
#   (head/tail in VIDEO seconds; ticks null = by closure)
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receptors as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\jonec\repos\piu-annotate\.venv\Scripts\python.exe"

def run(args):
    r = subprocess.run([PY, "-X", "utf8"] + args, cwd=ROOT, capture_output=True, text=True)
    return r.stdout + r.stderr

def main():
    chart, a, spec = sys.argv[1], float(sys.argv[2]), json.load(open(sys.argv[3]))
    extra = sys.argv[4:]
    smap = {o["chart"]: o for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    key, ssc_rel = smap[chart]["key"], smap[chart]["ssc_rel"]
    m = re.search(r"_([SD]P?\d+(?:_[A-Z0-9]+)*?)_(ARCADE|SHORTCUT|REMIX|FULLSONG)$", key)
    block = f"{m.group(1).replace('_', ' ')}_{m.group(2)}"
    ncols = 10 if chart.split()[-1][0] == "D" else 5
    ssc = os.path.join(ROOT, "simfiles", ssc_rel)
    # the rows come from the chartstruct, which only mirrors the .ssc after a regen - so
    # regenerate first, or a reverted file is read through the previous edit (Winter D17)
    run(["tools/regen_chartstruct.py", ssc, block, key])
    rows, taps, beat_at = R.chartstruct(key, ncols)
    row_beats = {}
    for r in rows:
        L = r["Line"].lstrip("`")
        for c, ch in enumerate(L[:ncols]):
            if ch in "12":
                row_beats.setdefault(c, []).append((float(r["Time"]), float(r["Beat"])))
    # the chartstruct pads a narrow style (half-double is 6 wide) to the full pad with equal
    # zeros on both sides, so its column indices sit PAST the file's. Map back before editing.
    body = open(ssc, encoding="utf-8", newline="").read()
    width = ncols
    for blk in body.split("#NOTEDATA:;")[1:]:
        d = re.search(r"#DESCRIPTION:([^;]*);", blk)
        if d and d.group(1) == block.rsplit("_", 1)[0]:
            widths = {len(l.strip()) for l in blk.split("#NOTES:")[-1].splitlines()
                      if re.fullmatch(r"[0-9MFLXW]+", l.strip())}
            if len(widths) == 1:
                width = widths.pop()
            break
    pad = (ncols - width) // 2
    if pad:
        print(f"  block is {width} panels wide: chartstruct column - {pad} = file column")
    pins = []
    for rail in spec:
        c, ch, ct = rail["col"] - pad, rail["head"] - a, rail["tail"] - a
        near = [(abs(t - ch), b) for t, b in row_beats.get(rail["col"], []) if abs(t - ch) <= 0.12]
        b0 = min(near)[1] if near else R.snap_beat(beat_at(ch))
        b1 = R.snap_beat(beat_at(ct))
        if b1 <= b0:
            b1 = b0 + 0.25
        out = run(["tools/edit_notes.py", "add-hold", ssc, block, str(c), f"{b0}", f"{b1}"])
        print(f"  col {c}: head {'on row' if near else 'new'} b{b0:.3f} -> b{b1:.3f} ({ct-ch:.2f}s)  ticks {rail.get('ticks')}  | {out.strip().splitlines()[-1]}")
        if rail.get("ticks") is not None:
            pins.append((b0, b1, rail["ticks"]))
    print("  " + run(["tools/regen_chartstruct.py", ssc, block, key]).strip().splitlines()[-1][:160])
    # merge pins that share a region (a jump-hold pair is one converter region)
    merged = {}
    for b0, b1, n in pins:
        k = (round(b0, 3), round(b1, 3))
        merged[k] = max(merged.get(k, 0), n)
    args = ["tools/finale_ticks.py", chart]
    for (b0, b1), n in merged.items():
        args += ["--pin", f"{b0}-{b1}={n}"]
    args += extra
    out = run(args)
    print("  " + "\n  ".join(l for l in out.splitlines() if not l.startswith("WARNING") and l.strip()))

if __name__ == "__main__":
    main()
