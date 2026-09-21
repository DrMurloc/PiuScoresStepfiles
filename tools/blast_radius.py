# Which charts did a new release actually change? Runs as soon as the pipeline's ingest stage
# has written its chartstruct CSVs - minutes into a ninety-minute run - so a surprise costs
# five minutes instead of the whole rebuild.
#
# For every chart in both releases it compares the step grid and timing (the Time / Beat /
# Line columns) and the hold-tick list. Then it holds the answer against git: every chart
# that moved must sit in a stepfile changed since the previous snapshot's commit, and every
# changed stepfile must account for at least one moved chart or one added chart. A chart
# that moved with no edit behind it is the pipeline or the corpus drifting; an edit that
# moved nothing is a repair the release did not pick up (a stale CSV - both ingest and limb
# prediction skip a chart whose output already exists).
#
#   python -X utf8 tools/blast_radius.py <new_release> <old_release> <previous snapshot commit>
#   e.g.  python -X utf8 tools/blast_radius.py p2-092126 p2-090326 7aa8429
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANN = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs"
COLS = ("Time", "Beat", "Line", "Line with active holds")


def signature(path):
    df = pd.read_csv(path, usecols=lambda c: c in COLS + ("Metadata",), dtype=str)
    meta = json.loads(df["Metadata"].iloc[0])
    grid = hashlib.sha1(df[[c for c in COLS if c in df.columns]].to_csv(index=False).encode()).hexdigest()
    ssc = meta["ssc_file"].replace("\\", "/").split("simfiles/")[-1]
    taps = int(df["Line"].str.contains("1", regex=False).sum())
    ticks = [int(round(t[2])) for t in (meta.get("Hold ticks") or [])]
    return grid, ssc, taps, ticks


def main():
    new_rel, old_rel, since = sys.argv[1:4]
    out = subprocess.run(["git", "-C", ROOT, "-c", "core.quotepath=false", "diff", "--name-only", since, "HEAD",
                          "--", "simfiles"], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    edited = {p[len("simfiles/"):] for p in out.split("\n") if p.lower().endswith(".ssc")}

    old = {f for f in os.listdir(os.path.join(ANN, old_rel)) if f.endswith(".csv")}
    new = {f for f in os.listdir(os.path.join(ANN, new_rel)) if f.endswith(".csv")}
    print(f"{old_rel}: {len(old)} charts   {new_rel}: {len(new)} charts   dropped {len(old - new)}   added {len(new - old)}")
    for f in sorted(old - new):
        print(f"   DROPPED  {f[:-4]}")

    accounted, moved, stray = defaultdict(int), [], []
    for f in sorted(new - old):
        accounted[signature(os.path.join(ANN, new_rel, f))[1]] += 1
    for f in sorted(old & new):
        a, b = signature(os.path.join(ANN, old_rel, f)), signature(os.path.join(ANN, new_rel, f))
        if a[0] == b[0] and a[3] == b[3]:
            continue
        kind = "grid" if a[0] != b[0] else "ticks"
        moved.append((kind, f[:-4], a[2], sum(a[3]), b[2], sum(b[3])))
        accounted[b[1]] += 1
        if b[1] not in edited:
            stray.append(f[:-4])

    print(f"\n{len(moved)} of {len(old & new)} shared charts moved:")
    for kind, key, t0, k0, t1, k1 in moved:
        print(f"   {kind:<5} {key:<64} taps {t0}->{t1}   ticks {k0}->{k1}")
    silent = sorted(e for e in edited if e not in accounted)
    print(f"\nmoved with NO stepfile edit behind it: {len(stray)}")
    for k in stray:
        print(f"   !! {k}")
    print(f"stepfiles edited since {since} that moved and added nothing: {len(silent)}")
    for e in silent:
        print(f"   !! {e}")
    added_songs = defaultdict(int)
    for f in new - old:
        added_songs[f.split("_-_")[0]] += 1
    if added_songs:
        print("\nadded, by song: " + ", ".join(f"{k} {v}" for k, v in sorted(added_songs.items())))
    return 1 if (old - new or stray or silent) else 0


if __name__ == "__main__":
    sys.exit(main())
