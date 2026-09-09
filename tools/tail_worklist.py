# Turns rows of the catalog sweep (sources/tail-*.json) into the two inputs the repair tools
# need for charts beyond the census, so the same pipeline runs on them unchanged:
#
#   work/ssc-map-tail.json     chart name -> key + .ssc path (what every tool looks a chart up by)
#   work/tail-video-map.json   video -> the charts it should certify, in video-map.json's shape
#
# The chart's target count comes from the catalog (Phoenix, else Phoenix 2), and that is also
# what certifies the footage: result_reader accepts a video only when a result screen's
# P+G+Gd+B+M equals it, so a video of the wrong revision certifies nothing and the chart parks.
#
#   python -X utf8 tools/tail_worklist.py <tail.json> [--shape single-region,hold-less]
#                                         [--min-pct 5] [--max-pct 100] [--limit N] [--out-tag pilot]
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

def chart_name(row):
    return f'{row["title"]} {row["chart"]}'

def select(rows):
    shapes = set((arg("--shape") or "").split(",")) - {""}
    lo, hi = float(arg("--min-pct", 0)), float(arg("--max-pct", 1e9))
    out = [r for r in rows
           if (not shapes or r["shape"] in shapes) and lo <= abs(r["pct"]) <= hi and r["video"]]
    out.sort(key=lambda r: -abs(r["pct"]))
    limit = arg("--limit")
    return out[:int(limit)] if limit else out

def main():
    src = json.load(open(sys.argv[1], encoding="utf-8"))
    # the chart map is ALWAYS the whole sweep - it is a lookup, and a later batch must not
    # erase the entries an earlier one wrote. Only the video map (the batch) is filtered.
    rows = src["charts"]
    batch = {r["key"] for r in select(src["charts"])}
    tag = arg("--out-tag", "tail")
    census = {o["chart"] for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    smap, vmap, skipped = [], {}, Counter()
    seen = set()
    for r in rows:
        name = chart_name(r)
        if name in census or name in seen:       # a census chart owns its name; never shadow it
            skipped["duplicate name"] += 1
            continue
        target = r["p1nc"] if r["p1nc"] is not None else r["p2nc"]
        if target is None:
            skipped["no catalog count"] += 1
            continue
        seen.add(name)
        smap.append(dict(chart=name, chartId=r["chartId"], key=r["key"], ssc_rel=r["ssc"],
                         source="tail", shape=r["shape"], file_implied=r["implied"], target=target))
        if r["key"] not in batch:
            continue
        vid = r["video"].rsplit("/", 1)[-1]
        e = vmap.setdefault(vid, dict(vid=vid, url=r["video"], channel=r["channel"], download=True, charts=[]))
        e["charts"].append(dict(chart=name, chartId=r["chartId"], judged=target,
                                judged_alt=r["p2nc"] if r["p2nc"] not in (None, target) else None,
                                side=r["side"], shape=r["shape"], delta=r["delta"]))
    os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)
    mp = os.path.join(ROOT, "work", "ssc-map-tail.json")
    vp = os.path.join(ROOT, "work", f"{tag}-video-map.json")
    json.dump(smap, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sorted(vmap.values(), key=lambda e: e["vid"]), open(vp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_batch = sum(len(e["charts"]) for e in vmap.values())
    print(f"map: {len(smap)} charts -> {os.path.relpath(mp, ROOT)}")
    print(f"batch: {n_batch} charts over {len(vmap)} videos -> {os.path.relpath(vp, ROOT)}")
    print("  batch by shape:", dict(Counter(c["shape"] for e in vmap.values() for c in e["charts"])))
    if skipped:
        print("  skipped:", dict(skipped))

if __name__ == "__main__":
    main()
