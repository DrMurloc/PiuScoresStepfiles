# Which charts are pointing at footage older than what exists?
#
# The result-screen skin proved that a banked video can be a pre-Phoenix capture of a chart the
# game has since re-stepped (docs/EVIDENCE-RULES, "The footage has an era"). Nevsister re-shot
# most of what changed, so the fix for those charts is a NEWER VIDEO, not an edited stepfile.
#
# This reads a channel walk (videoId <tab> ? <tab> title - the census's cache at
# %USERPROFILE%\.piu-score-tracker\video-backfill\walks\), matches every title to a chart in the
# catalog, and reports, per chart, the newest era we have footage for against what the site has
# banked. Titles are the whole evidence: Nevsister stamps the mix on every one
# ("[PUMP IT UP PHOENIX] Slam(슬램) S18 & S20"), and a two-code title is a split-screen video
# whose lower level plays on the LEFT (the site's own rule, singles only).
#
# Three things the titles will trip you on:
#   - the rerate note is IN PARENTHESES and full of chart codes ("1949 D22 (pre D21 -> D22)"),
#     so parentheticals come out before any code is read;
#   - "8 6 - FULL SONG -" and the arcade "8 6" normalise to the same name, so the song type in
#     the title has to match the song type in the catalog or a full song takes an arcade video;
#   - the code in a Phoenix title is the PHOENIX level ("S16 & S20" where XX had S16 & S21), so
#     a chart is looked up at the level it holds in that video's own mix.
#
#   python -X utf8 tools/video_freshness.py <walk.tsv> <catalog.txt> <videos.txt> <out.json>
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# newest last; anything not here (RISE is a different game on 5K/6K pads, M, DOMINION APT) is
# not our catalog and is ignored outright
ERA_MIX = [("FIESTA", "Fiesta"), ("FIESTA 2", "Fiesta 2"), ("PRIME", "Prime"), ("PRIME 2", "Prime 2"),
           ("XX", "XX"), ("PHOENIX", "Phoenix"), ("PHOENIX 2", "Phoenix2")]
ERA_RANK = {e: i for i, (e, _) in enumerate(ERA_MIX)}
MIX_OF = dict(ERA_MIX)
TAG = re.compile(r"^\[PUMP IT UP ([A-Z0-9 ]+)\]\s*(.*)$")
CODE = re.compile(r"\b([SD])P?(\d{1,2})\b")
MARKER = re.compile(r"-?\s*\b(FULL SONG|SHORT CUT)\b\s*-?", re.I)

def norm(s):
    return re.sub(r"[^a-z0-9가-힣]", "", s.lower())

def song_type(text):
    m = MARKER.search(text)
    if not m:
        return None
    return "FullSong" if m.group(1).upper() == "FULL SONG" else "ShortCut"

def parse_walk(path):
    out = []
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3 or not parts[0]:
            continue
        m = TAG.match(parts[2].strip())
        if not m or m.group(1).strip() not in ERA_RANK:
            continue                          # untagged uploads are clips, not the chart series
        out.append(dict(vid=parts[0], era=m.group(1).strip(), title=parts[2].strip(), rest=m.group(2)))
    return out

def codes_and_name(rest):
    """The chart codes a title really claims, the song name in front of them, and its type."""
    body = rest.split("|")[0]
    stype = song_type(body)
    body = re.sub(r"\([^)]*\)", " ", body)             # the Korean gloss AND the rerate note
    codes = CODE.findall(body)
    if not codes:
        return None, [], stype
    name = MARKER.sub(" ", body[:CODE.search(body).start()])
    return norm(name), [(t, int(n)) for t, n in codes], stype

def load_catalog(path):
    """(song, type letter, mix, song type) -> {level: chartId}, plus each chart's own levels."""
    by_song = defaultdict(dict)
    info = {}
    for line in open(path, encoding="utf-8"):
        p = line.rstrip("\n").split("|")
        if len(p) != 8:
            continue
        name, typ, lvl, nc, mix, cid, stype, _ = p
        cid = cid.upper()
        base = norm(MARKER.sub(" ", name.replace("-", " ")))
        by_song[(base, typ[0], mix, stype)][int(lvl)] = cid
        info.setdefault(cid, dict(name=name, type=typ, stype=stype, levels={}))
        info[cid]["levels"][mix] = int(lvl)
    return by_song, info

def main():
    walk_path, cat_path, vid_path, out_path = sys.argv[1:5]
    entries = parse_walk(walk_path)
    by_song, info = load_catalog(cat_path)
    banked = {}
    for line in open(vid_path, encoding="utf-8"):
        p = line.rstrip("\n").split("|")
        if len(p) == 4 and re.match(r"[0-9A-Fa-f-]{36}$", p[0]):
            banked[p[0].upper()] = dict(url=p[1], vid=p[1].rsplit("/", 1)[-1], channel=p[2], side=p[3])

    best, skipped = {}, Counter()
    for e in entries:
        song, codes, stype = codes_and_name(e["rest"])
        if not song:
            skipped["no chart code"] += 1
            continue
        mix = MIX_OF[e["era"]]
        want = [stype] if stype else ["Arcade", "Remix"]
        hits = []
        for typ, lvl in codes:
            for st in want:
                cid = by_song.get((song, typ, mix, st), {}).get(lvl)
                if cid and cid not in [h[0] for h in hits]:
                    hits.append((cid, typ, lvl))
                    break
        if not hits:
            skipped["song/level/type not in that mix"] += 1
            continue
        # a two-chart title is one split screen. SINGLES ONLY - doubles never split sides -
        # and only when the two are genuinely different charts at different levels.
        sides = {}
        if len(hits) == 2 and hits[0][1] == hits[1][1] == "S" and hits[0][2] != hits[1][2]:
            lo, hi = sorted(hits, key=lambda h: h[2])
            sides = {lo[0]: "Left", hi[0]: "Right"}
        for cid, typ, lvl in hits:
            cur = best.get(cid)
            if cur is None or ERA_RANK[e["era"]] > ERA_RANK[cur["era"]]:
                best[cid] = dict(vid=e["vid"], era=e["era"], title=e["title"], side=sides.get(cid, ""))

    walk_era = {e["vid"]: e["era"] for e in entries}
    rows = []
    for cid, b in sorted(best.items(), key=lambda kv: info[kv[0]]["name"]):
        have = banked.get(cid)
        cur_era = walk_era.get(have["vid"]) if have else None
        i = info[cid]
        name = f'{i["name"]} {i["type"][0]}{i["levels"].get("Phoenix2", i["levels"].get("Phoenix", "?"))}'
        if have is None:
            action = "no banked video"
        elif have["vid"] == b["vid"]:
            action = "current"
        elif cur_era is None:
            action = "banked era unknown"         # another channel, or a title the walk missed
        elif ERA_RANK[b["era"]] > ERA_RANK[cur_era]:
            action = "upgrade"
        else:
            action = "banked is as new or newer"
        rows.append(dict(chartId=cid, chart=name, songtype=i["stype"], action=action,
                         best_vid=b["vid"], best_era=b["era"], best_side=b["side"], best_title=b["title"],
                         banked_vid=have["vid"] if have else None, banked_era=cur_era,
                         banked_side=have["side"] if have else None,
                         banked_channel=have["channel"] if have else None))
    doc = dict(generated="2026-09-09", walk=os.path.basename(walk_path),
               counts=dict(titles=len(entries), matched_charts=len(best), skipped=dict(skipped),
                           by_best_era=dict(Counter(r["best_era"] for r in rows)),
                           by_action=dict(Counter(r["action"] for r in rows)),
                           upgrades_by_era=dict(Counter(f'{r["banked_era"]} -> {r["best_era"]}'
                                                        for r in rows if r["action"] == "upgrade"))),
               charts=rows)
    json.dump(doc, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(doc["counts"], indent=1))

if __name__ == "__main__":
    main()
