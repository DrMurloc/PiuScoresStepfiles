# Size what is wrong beyond the census: every corpus block through the converter (the same
# rule as tick_verify - taps are rows with a '1', ticks are the converter's per-hold list)
# against the catalog's Phoenix note count, matched through the PACK's own mix (a Rebirth-pack
# S13 block is Phoenix's S17), with the site's banked video for each chart.
#
# Needs two dumps from the local prod-synced SQL (container name drifts; sqlcmd flags per
# docs/TOOLS.md), one row per line, no headers:
#   catalog: s.Name|c.Type|cm.Level|cm.NoteCount|m.Name|c.Id|s.Type|m.SortOrder
#            FROM scores.ChartMix cm JOIN scores.Chart c .. JOIN scores.Song s .. JOIN scores.Mix m ..
#   videos:  ChartId|VideoUrl|ChannelName|Side   FROM scores.ChartVideo
#
#   python -X utf8 tools/catalog_sweep.py <release chart-json folder> <catalog.txt> <videos.txt> <out.json> [--pct 5]
import glob
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tick_verify import block_of                                                  # noqa: E402
from piu_annotate.formats.sscfile import StepchartSSC                             # noqa: E402
from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK_MIXES = {"1ST~3RD": {"1st", "2nd", "3rd"}, "S.E.~EXTRA": {"OBG SE", "Collection", "Perfect", "Extra"},
              "REBIRTH~PREX 3": {"Premiere", "Prex", "Rebirth", "Premiere 2", "Prex 2", "Premiere 3", "Prex 3"},
              "EXCEED~ZERO": {"Exceed", "Exceed 2", "Zero"}, "NX~NX2": {"NX", "NX2"}, "NX ABSOLUTE": {"NXA"},
              "FIESTA": {"Fiesta"}, "FIESTA EX": {"Fiesta EX"}, "FIESTA 2": {"Fiesta 2"}, "PRIME": {"Prime"},
              "PRIME 2": {"Prime 2"}, "XX": {"XX"}, "PHOENIX": {"Phoenix"}, "PHOENIX 2": {"Phoenix2"}}
SHAPES = ["hold-less", "single-region", "under-ticked", "over-ticked", "duplicate-block"]

def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())

def regions(holds):
    regs = []
    for t0, t1, _ in sorted(holds):
        if regs and t0 <= regs[-1][1] + 1e-6:
            regs[-1][1] = max(regs[-1][1], t1)
        else:
            regs.append([t0, t1])
    return len(regs)

def convert(chart_json_dir):
    out, t0 = [], time.time()
    for jf in sorted(glob.glob(os.path.join(chart_json_dir, "*.json"))):
        key = os.path.basename(jf)[:-5]
        dj = json.load(open(jf, encoding="utf-8"))
        if not (isinstance(dj, list) and len(dj) > 2 and isinstance(dj[2], dict)):
            continue                                                # __search-struct and friends
        meta = dj[2]
        rec = dict(key=key, title=meta["TITLE"], songtype=meta.get("SONGTYPE", ""), sord=meta.get("sord_chartlevel", ""),
                   pack=meta.get("pack", ""), ssc=meta["ssc_file"].replace("\\", "/").split("simfiles/")[-1])
        try:
            sc = StepchartSSC.from_song_ssc_file(meta["ssc_file"], block_of(key))
            df, holdticks, msg = stepchart_ssc_to_chartstruct(sc) if sc is not None else (None, None, "block not found")
            if df is None:
                rec["status"] = f"convert failed: {msg}"
                out.append(rec)
                continue
        except Exception as ex:
            rec["status"] = f"error: {ex!r}"[:200]
            out.append(rec)
            continue
        rec["taps"] = int(df["Line"].str.contains("1", regex=False).sum())
        rec["holds"] = [[round(float(a), 3), round(float(b), 3), int(round(t))] for a, b, t in holdticks]
        rec["ticks"] = sum(h[2] for h in rec["holds"])
        rec["implied"] = rec["taps"] + rec["ticks"]
        rec["status"] = "ok"
        out.append(rec)
        if len(out) % 500 == 0:
            print(f"  {len(out)} converted, {time.time() - t0:.0f}s", flush=True)
    return out

def match(recs, rows):
    share = defaultdict(list)
    for r in recs:
        if r["status"] != "ok":
            r["match"] = "not converted"
            continue
        m = re.match(r"([SDC])P?(\d+)", r["sord"] or "")
        if not m:
            r["match"] = "no level"
            continue
        t, lvl = ("D" if m.group(1) == "C" else m.group(1)), int(m.group(2))
        suffix = {"SHORTCUT": " - SHORT CUT -", "FULLSONG": " - FULL SONG -"}.get(r["songtype"], "")
        pool = rows.get((norm(r["title"] + suffix), t)) or rows.get((norm(r["title"]), t)) or []
        own = {c for mix, l, nc, c in pool if mix in PACK_MIXES.get(r["pack"], set()) and l == lvl}
        anym = {c for mix, l, nc, c in pool if l == lvl}
        cands, how = (own, "pack-mix") if own else (anym, "any-mix") if anym else (set(), "none")
        if len(cands) > 1:
            # several charts of this song/type sat at this level in some mix: keep the one alive in Phoenix
            alive = {c for c in cands if any(mix == "Phoenix" and c2 == c for mix, l, nc, c2 in pool)}
            if len(alive) == 1:
                cands, how = alive, how + "/alive"
        if not pool:
            r["match"] = "unmatched song"
        elif not cands:
            r["match"] = "unmatched level"
        elif len(cands) > 1:
            r["match"] = "ambiguous"
            r["cands"] = sorted(cands)
        else:
            cid = next(iter(cands))
            p1 = next((nc for mix, l, nc, c in pool if c == cid and mix == "Phoenix"), None)
            p2 = next((nc for mix, l, nc, c in pool if c == cid and mix == "Phoenix2"), None)
            r.update(match=how, chartId=cid, p1nc=p1, p2nc=p2,
                     p1_level=next((l for mix, l, nc, c in pool if c == cid and mix == "Phoenix"), None))
            share[cid].append(r["key"])
            ref = p1 if p1 is not None else p2
            if ref is None:
                r["verdict"] = "no count"
            elif r["implied"] in (p1, p2):
                r["verdict"] = "exact"
            else:
                r["verdict"] = "mismatch"
                r["delta"] = r["implied"] - ref
                r["pct"] = round(100 * r["delta"] / ref, 1)
    return share

def main():
    cj, cat_path, vid_path, out_path = sys.argv[1:5]
    pct_floor = float(sys.argv[sys.argv.index("--pct") + 1]) if "--pct" in sys.argv else 5.0
    rows = defaultdict(list)                     # (norm name, type letter) -> [(mix, level, notecount, chartId)]
    for line in open(cat_path, encoding="utf-8"):
        p = line.rstrip("\n").split("|")
        if len(p) == 8:
            rows[(norm(p[0]), p[1][0])].append((p[4], int(p[2]), int(p[3]) if p[3] else None, p[5].upper()))
    vids = {}
    for line in open(vid_path, encoding="utf-8"):
        p = line.rstrip("\n").split("|")
        if len(p) == 4 and re.match(r"[0-9A-Fa-f-]{36}$", p[0]):
            vids[p[0].upper()] = dict(url=p[1].replace("https://www.youtube.com/embed/", "https://youtu.be/"), channel=p[2], side=p[3])
    smap = {o["key"] for o in json.load(open(os.path.join(ROOT, "sources", "ssc-map.json"), encoding="utf-8"))}
    recs = convert(cj)
    share = match(recs, rows)
    tail = []
    for r in recs:
        if r.get("verdict") != "mismatch" or r["key"] in smap or abs(r["pct"]) <= pct_floor:
            continue
        others = [k for k in share[r["chartId"]] if k != r["key"]]
        shape = ("duplicate-block" if others else "hold-less" if not r["holds"] else "single-region" if regions(r["holds"]) == 1
                 else "over-ticked" if r["delta"] > 0 else "under-ticked")
        v = vids.get(r["chartId"], {})
        tail.append(dict(key=r["key"], chartId=r["chartId"], title=r["title"], chart=r["sord"], pack=r["pack"], ssc=r["ssc"],
                         match=r["match"], p1_level=r["p1_level"], p1nc=r["p1nc"], p2nc=r["p2nc"], file_taps=r["taps"],
                         file_ticks=r["ticks"], file_holds=len(r["holds"]), hold_regions=regions(r["holds"]), implied=r["implied"],
                         delta=r["delta"], pct=r["pct"], shape=shape, duplicate_of=others or None, video=v.get("url", ""),
                         channel=("NEVSISTER" if "NEVSISTER" in v.get("channel", "").upper() else v.get("channel", "")),
                         side=v.get("side", "")))
    tail.sort(key=lambda r: (SHAPES.index(r["shape"]), -abs(r["pct"])))
    beyond = [r for r in recs if r.get("verdict") == "mismatch" and r["key"] not in smap]
    counts = dict(blocks=len(recs), converted=sum(1 for r in recs if r["status"] == "ok"),
                  match=dict(Counter(r.get("match") for r in recs)),
                  verdict=dict(Counter(r.get("verdict") for r in recs if r.get("verdict"))),
                  beyond_census=dict(Counter("within 1%" if abs(r["pct"]) <= 1 else "within 5%" if abs(r["pct"]) <= 5 else "beyond 5%"
                                             for r in beyond)),
                  tail=len(tail), by_shape=dict(Counter(r["shape"] for r in tail)), with_video=sum(1 for r in tail if r["video"]),
                  by_pack=dict(Counter(r["pack"] for r in tail).most_common()))
    json.dump(dict(generated=time.strftime("%Y-%m-%d"), source="tools/catalog_sweep.py",
                   rule=f"beyond the census; |implied - catalog| > {pct_floor}%", counts=counts, charts=tail),
              open(out_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(counts, indent=1))

if __name__ == "__main__":
    main()
