# What the result-screen skins certify, and how it lands: the per-(video, side) gate, the blind
# contact sheets, the ledger (sources/certification-skins-<date>.json, merged by tools/corpus_map.py),
# the band manifest, the ERA staging file and the what-if grade. Bucket #12 of the 2026-09-26 loop
# proposal; the reads come from tools/cert_skins.py (base / step1 / new, same frames).
#
#   plan  --reads <dir> --out <plan.json> [--override <dir> ...]
#       Every (video, side) read the two profile changes add, and what it would do: certify a chart
#       (its total is the chart's catalog count, or its judged_alt), or move the reader band of a chart
#       the ledgers already certify (its video gains a read of the other side). Each carries the
#       on-screen checks (six digit cells, maxcombo <= P+G, no BAD or MISS -> maxcombo == P+G) and the
#       confirming second frame >= 1 s away. Also every video the bucket must account for - the XX
#       videos with no certified chart and the non-official videos the ledger read no screen on -
#       chart by chart: CERTIFY? / ERA (the screen total is our file's lattice count, not the catalog's)
#       / CORRUPT / REJECTED with a reason. Our files' counts come from corpus_grade's own converter
#       and cache. Seeds for the blind sheets: sides whose six cells are already known (a committed XX
#       certification the reader reproduces cell for cell; a bootstrap read whose total is the chart's
#       catalog count). --override names other read folders (<vid>.json): a cert_skins read there (all
#       three codes, e.g. on seek frames where the reads dir decoded forward) replaces the video's read;
#       a result_reader.read_one file (a later revision's) replaces its "new" read alone.
#   sheet --plan <plan.json> --batch <name> [--per-packet 24] [--seed-share 0.25] [--done-keys <keys.json> ...]
#       Blind packets (tools/blind_packets.py) for every candidate side that passed its on-screen
#       checks and its second frame: one enlarged crop of the side's six number rows each, seeds mixed
#       in, the key in work/blind-keys/skins-1/<batch>.json. --done-keys: earlier batches' keys; a side
#       one of them already holds as a real item is not asked again.
#   land  --plan <plan.json> --keys <keys.json> --answers <dir> [--keys ... --answers ...] --out <ledger.json> --bands <bands.json>
#       The gate, per (video, side): checks, second frame, and a blind transcription two readers agree
#       on that equals the reader's six cells. What passes is written as a certification ledger
#       ({vid: entry}, the corpus ledger's shape plus `evidence`), holding only the charts it newly
#       certifies (the per-chart merge keeps the rest); a band-only side lands with no chart. Bootstrap
#       and inspected videos never land (they built the profiles), nor does an official upload (benchmark
#       identity only, never a certification - the loops' cross-cutting rule). With several batches (--keys and
#       --answers in pairs), a side takes the first batch that holds it as a real item (never as a
#       diagnostic one, which only ever judges a profile).
#   era   --plan <plan.json> --out work/era/<file>.json  /  era-check <file>
#       The ERA rows, stamped with the converter pin and each chart's block and header sha; era-check
#       re-derives the stamps and names every row a change has made stale (such a row is void).
#       A staging file no loop reads; never a close, a skip or an exclusion.
#   whatif --extra <ledger.json> [--out <report.json>]
#       The corpus grade with the committed oracle, and again with <ledger.json> merged between the
#       corpus and census ledgers: certified and exact counts and the population set-diff on
#       (vid, chart, side, expected). Read-only apart from corpus_grade's conversion cache.
import argparse
import glob
import json
import os
import sys
from types import SimpleNamespace

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import atomicio       # noqa: E402
import blind_packets  # noqa: E402
import corpus_map     # noqa: E402

LABELS = ["perfect", "great", "good", "bad", "miss", "maxcombo"]
LEDGERS = {"corpus": "sources/certification-corpus-2026-09-10.json",
           "census": "sources/certification-2026-08-30.json"}
VIDEO_MAPS = ("work/corpus-video-map.json", "sources/video-map.json", "work/pilot-video-map.json")
LOOP = "skins-1"
# Footage a profile was built on (its anchor, its geometry): never counts toward yield.
BOOTSTRAP = {"prime": ["CetRYCDq8eE", "J6A2eZGu-yc"], "dancegrade": ["FsFAU37qmj4", "9waUMyMNqLM"]}
# Looked at (glyph extents only, never values) while choosing the column search: excluded from yield
# too. Prime's five take its footage used in building past the three-video cap; reported as such.
INSPECTED = {"prime": ["q9Tj8qYrisM", "rkhGTHyz28Q", "bNefB8CxLIg", "0qbKb2cWyFY", "Nywh-HyJhBI"],
             "dancegrade": ["Q-4XfqIiM1Q"]}
# Prime revision 2 (rejected) cut a digit atlas from these three sides' cells and labelled the cells
# with batch b1's agreed blind transcriptions. That broke the loop plan's cross-cutting rule that
# agent eye-reads are never training labels, and it had no per-glyph provenance manifest either
# (docs/STATUS.md, "Result-screen skins"). So this footage is bootstrap footage too and never counts
# toward yield. No transcription from batch b1 or b2 may label an atlas.
REV2_BOOTSTRAP = {"prime": ["Nywh-HyJhBI", "Y1r3ZykiMjU", "Zqul1BBl1nk"]}
NOT_YIELD = {v for d in (BOOTSTRAP, INSPECTED, REV2_BOOTSTRAP) for vs in d.values() for v in vs}
INSTRUCTIONS = ("Each item is one image: a column of six numbers cut from a rhythm game's end-of-song result "
                "screen, enlarged. Read the six numbers from top to bottom exactly as they are drawn, keeping "
                "every leading zero. Do not add, correct or infer anything: if a digit is cut off, covered or "
                "cannot be made out, write ? in its place. Answer each item on its own.")
ASK = "Transcribe the six numbers in this column, top to bottom."
FORMAT = ("the six numbers separated by /, top to bottom, each written digit for digit as shown "
          "(leading zeros kept), ? for any digit you cannot read")


# ---------------------------------------------------------------- inputs

def load_reads(reads_dir):
    out, timeouts = {}, {}
    for p in glob.glob(os.path.join(reads_dir, "*.json")):
        d = atomicio.load_json(p)
        if not d:
            continue
        if p.endswith(".timeout.json"):
            timeouts[d["vid"]] = d
        elif "new" in d:
            out[d["vid"]] = d
    return out, timeouts


def ledgers():
    return {n: corpus_map.ledger_entries(json.load(open(os.path.join(ROOT, p), encoding="utf-8")))
            for n, p in LEDGERS.items()}


def video_maps():
    vm, chan = {}, {}
    for p in VIDEO_MAPS:
        path = os.path.join(ROOT, p)
        if os.path.exists(path):
            for e in json.load(open(path, encoding="utf-8")):
                chan.setdefault(e["vid"], e.get("channel") or "")
                for c in e["charts"]:
                    vm.setdefault((e["vid"], c["chart"]), c)
    return vm, chan


def total(read, side):
    return ((read or {}).get(side) or {}).get("judged")


def cells(read, side):
    s = (read or {}).get(side) or {}
    return "/".join(s.get(k, "") for k in LABELS)


def band(read, side):
    other = (read or {}).get("2p" if side == "1p" else "1p") or {}
    return "C" if not other.get("judged") else ("L" if side == "1p" else "R")


# ---------------------------------------------------------------- the what-if grade

class WhatIf:
    """corpus_grade's grade over the committed oracle, optionally with one more ledger merged."""

    def __init__(self, rev="HEAD", workers=4):
        import corpus_grade as CG
        self.CG = CG
        self.pin = CG.converter_pin()
        self.otree = CG.Tree(None)
        self.oracle = CG.Oracle(self.otree)
        CG.check_manifest(self.oracle, self.pin)
        self.blocks = CG.Tree(rev)
        self.g = CG.Grader(SimpleNamespace(workers=workers, cache_dir=CG.DEFAULT_CACHE, no_cache=False,
                                           stall_timeout=600), self.pin)
        raw = {p: self.otree.read_oracle(p) for p in CG.ORACLE_DATA}
        self.corpus = corpus_map.ledger_entries(CG._json(raw[LEDGERS["corpus"]], {}))
        self.census = corpus_map.ledger_entries(CG._json(raw[LEDGERS["census"]], {}))
        self.tail_sweep = CG._json(raw["sources/tail-2026-09-08.json"], {})
        self.census_final = CG._json(raw["sources/census-final.json"], [])

    def grade(self, extra=None):
        cert = corpus_map.merge_certification([self.corpus] + ([extra] if extra else []) + [self.census])
        o = self.oracle
        pop = corpus_map.certified_charts(cert, o.smap, self.tail_sweep, self.census_final)
        saved, o.population = o.population, pop
        try:
            rows, imp = self.g.grade(self.blocks, o)
        finally:
            o.population = saved
        return rows, self.CG.summarize(rows, imp), pop

    def lattice(self, charts):
        pop = {}
        for n in charts:
            m = self.oracle.smap.get(n)
            if m:
                pop[n] = dict(chart=n, key=m["key"], ssc_rel=m["ssc_rel"], vid=None, side=None, expected=None)
        return self.CG.grade_tree(self.blocks, SimpleNamespace(population=pop), self.g.conv)


def cmd_whatif(a):
    w = WhatIf()
    extra = corpus_map.ledger_entries(json.load(open(a.extra, encoding="utf-8")))
    r0, s0, p0 = w.grade()
    r1, s1, p1 = w.grade(extra)
    key = lambda p: {(c["vid"], n, c["side"], c["expected"]) for n, c in p.items()}  # noqa: E731
    added, removed = sorted(key(p1) - key(p0)), sorted(key(p0) - key(p1))
    gained = sorted(n for n in r1 if r1[n]["exact"] and not (n in r0 and r0[n]["exact"]))
    lost = sorted(n for n in r0 if r0[n]["exact"] and not (n in r1 and r1[n]["exact"]))
    rep = dict(before=s0, after=s1, population_added=added, population_removed=removed,
               exact_gained=gained, exact_lost=lost,
               added_rows={n: {k: r1[n].get(k) for k in ("vid", "side", "expected", "implied", "taps", "ticks", "exact",
                                                         "tier", "block_sha")} for (_v, n, _s, _e) in added})
    if a.out:
        atomicio.write_json(a.out, rep, encoding="utf-8", ensure_ascii=False, indent=1)
    print("before: %d certified, %d exact (%d PROTECTED, %d PROVISIONAL)" % (
        s0["certified"], s0["exact"], s0["protected"], s0["provisional"]))
    print("after:  %d certified, %d exact (%d PROTECTED, %d PROVISIONAL)" % (
        s1["certified"], s1["exact"], s1["protected"], s1["provisional"]))
    print("population: +%d -%d rows; exact +%d -%d" % (len(added), len(removed), len(gained), len(lost)))
    for v, n, s, e in added:
        r = r1[n]
        print("  + %-50s %s %s expected %s file %s%s" % (n, v, s, e, r.get("implied"), " EXACT" if r["exact"] else ""))
    for x in removed:
        print("  - %s" % (x,))


# ---------------------------------------------------------------- plan

def load_overrides(dirs):
    """{vid: doc} from other read folders, the last folder winning: a cert_skins read (base, step1 and
    new, e.g. taken on other frames) replaces the whole read; a result_reader.read_one file (a later
    revision's read) replaces the "new" read alone."""
    out = {}
    for d in dirs or []:
        for p in glob.glob(os.path.join(d, "*.json")):
            if p.endswith(".timeout.json"):
                continue
            doc = atomicio.load_json(p)
            if doc and doc.get("vid") and ("new" in doc or "read" in doc):
                out[doc["vid"]] = doc
    return out


def cmd_plan(a):
    import result_reader as rr
    reads, timeouts = load_reads(a.reads)
    over = load_overrides(a.override)
    for vid, doc in over.items():
        if "new" in doc:
            reads[vid] = dict(doc, overridden=True)
        elif vid in reads:
            reads[vid] = dict(reads[vid], new=doc, overridden=True)
        if vid in reads:
            timeouts.pop(vid, None)
    L = ledgers()
    merged = corpus_map.merge_certification([L["corpus"], L["census"]])
    vm, chan = video_maps()
    certified = {}
    for vid, e in merged.items():
        for n, c in (e.get("charts") or {}).items():
            if c.get("verdict") == "CERTIFIED":
                certified.setdefault(n, []).append(vid)
    sides, seeds = [], []
    for vid, e in sorted(merged.items()):
        d = reads.get(vid)
        if not d:
            continue
        base, s1, nw = d["base"], d.get("step1") or {}, d["new"]["read"]
        checks = d["new"].get("checks") or {}
        same_as_new = all(s1.get(k) == nw.get(k) for k in ("status", "t", "skin", "scale", "1p", "2p"))
        if s1.get("status") == "ok" and s1.get("skin") == "xx":
            scope, read = "xx2p", s1
            added = [s for s in ("1p", "2p") if total(s1, s) is not None and total(base, s) is None]
        elif nw.get("status") == "ok" and nw.get("skin") in ("prime", "dancegrade") and s1.get("status") != "ok":
            scope, read = "newskins", nw
            added = [s for s in ("1p", "2p") if total(nw, s) is not None]
        else:
            added, scope, read = [], None, None
        for side in added:
            val = total(read, side)
            certs, bands = [], []
            for name, c in sorted((e.get("charts") or {}).items()):
                m = vm.get((vid, name), {})
                if c.get("verdict") == "CERTIFIED":
                    b0, b1 = band(base if scope == "xx2p" else e, c.get("side") or "1p"), band(read, c.get("side") or "1p")
                    if b0 != b1:
                        bands.append(dict(chart=name, side=c.get("side"), band_before=b0, band_after=b1))
                    continue
                expect = [c.get("expected")] + ([m["judged_alt"]] if m.get("judged_alt") else [])
                if val in expect:
                    certs.append(dict(chart=name, expected=c.get("expected"), matched=val,
                                      via="judged" if val == c.get("expected") else "judged_alt",
                                      map_side=m.get("side", ""), elsewhere=certified.get(name, [])))
            ck = checks.get(side) if (same_as_new or scope == "newskins") else None   # the checks are of the full code's read
            confirm = None if ck is None else ck.get("confirm_t")
            sides.append(dict(vid=vid, side=side, scope=scope, skin=read.get("skin"), t=read.get("t"),
                              scale=read.get("scale"), dx=(read.get(side) or {}).get("dx"), total=val,
                              cells=cells(read, side), read={k: read.get(k) for k in ("status", "t", "skin", "scale", "1p", "2p")},
                              certifies=certs, band_changes=bands, charts=sorted(e.get("charts") or {}),
                              checks=rr.side_checks(read.get(side)), confirm_t=confirm,
                              confirm_fail=None if ck is None else [f for f in ck["fails"] if f.startswith("unconfirmed")],
                              not_yield=vid in NOT_YIELD, channel=chan.get(vid, ""), code=d["new"].get("code")))
        # seeds: an XX 1P side the ledger certifies and this code reproduces cell for cell
        if e.get("skin") == "xx" and s1.get("skin") == "xx" and same_as_new:
            for n, c in (e.get("charts") or {}).items():
                sd = c.get("side")
                if c.get("verdict") == "CERTIFIED" and sd and cells(e, sd) == cells(s1, sd) == cells(base, sd) \
                        and total(e, sd) == c.get("expected") and not rr.side_checks(s1.get(sd)):
                    seeds.append(dict(vid=vid, side=sd, answer=cells(s1, sd), read={k: s1.get(k) for k in ("status", "t", "skin", "scale", "1p", "2p")},
                                      why="committed XX certification of %s, reproduced cell for cell" % n))
                    break
    # bootstrap seeds: a bootstrap read of a new skin whose total is the chart's catalog count
    for s in sides:
        if s["scope"] == "newskins" and s["vid"] in NOT_YIELD and any(c["via"] == "judged" for c in s["certifies"]) \
                and not s["checks"] and s["confirm_t"] is not None:
            seeds.append(dict(vid=s["vid"], side=s["side"], answer=s["cells"], read=s["read"],
                              why="bootstrap %s read totalling %s's catalog count" % (s["skin"], s["certifies"][0]["chart"])))
    # the population the bucket answers for
    pop = []
    for vid, e in sorted(merged.items()):
        cert_here = any(c.get("verdict") == "CERTIFIED" for c in (e.get("charts") or {}).values())
        if e.get("status") == "ok" and e.get("skin") == "xx" and not cert_here:
            pop.append((vid, "xx-mismatch"))
        elif e.get("status") != "ok" and "Official" not in chan.get(vid, ""):
            pop.append((vid, "no-screen, non-official"))
    lat = WhatIf().lattice(sorted({n for vid, _ in pop for n in (merged[vid].get("charts") or {})}))
    pin = None
    try:
        import corpus_grade as CG
        pin = CG.converter_pin()["pin"]
    except Exception:
        pass
    videos = []
    landable = {(s["vid"], s["side"]) for s in sides}
    for vid, group in pop:
        e = merged[vid]
        d = reads.get(vid)
        if d is None:
            videos.append(dict(vid=vid, group=group, verdict="TIMEOUT" if vid in timeouts else "NOT READ", charts=[]))
            continue
        s1, nw = d.get("step1") or {}, d["new"]["read"]
        read = s1 if (s1.get("status") == "ok" and s1.get("skin") == "xx") else nw
        tot = {s: total(read, s) for s in ("1p", "2p")}
        rows = []
        for name, c in sorted((e.get("charts") or {}).items()):
            m = vm.get((vid, name), {})
            exp, alt = c.get("expected"), m.get("judged_alt")
            hint = {"Left": "1p", "Right": "2p"}.get(m.get("side", ""))
            lr = lat.get(name)
            fc = (lr or {}).get("implied")
            ferr = (lr or {}).get("error") if lr else "no stepfile mapped"
            row = dict(chart=name, expected=exp, judged_alt=alt, map_side=m.get("side", ""), file=fc, file_error=ferr,
                       key=(lr or {}).get("key"), ssc_rel=(lr or {}).get("ssc_rel"),
                       block_sha=(lr or {}).get("block_sha"), header_sha=(lr or {}).get("header_sha"))
            cand = [hint] if hint else ["1p", "2p"]
            want = [exp] + ([alt] if alt else [])
            match = [s for s in cand if tot[s] is not None and tot[s] in want]
            era = [s for s in cand if tot[s] is not None and fc is not None and tot[s] == fc and tot[s] not in want]
            if match:
                row.update(verdict="CERTIFY?", side=match[0])
            elif era:
                row.update(verdict="ERA", side=era[0], screen=tot[era[0]], cells=cells(read, era[0]),
                           checks=rr.side_checks(read.get(era[0])), converter_pin=pin)
            elif read.get("status") == "corrupt-video":
                row.update(verdict="CORRUPT", why=read.get("reason"))
            elif read.get("status") != "ok":
                row.update(verdict="REJECTED", why="no result screen read (%s)" % read.get("status"))
            else:
                why = "screen %s matches neither the catalog %s%s nor our file %s" % (
                    {s: v for s, v in tot.items() if v is not None}, exp, " (alt %s)" % alt if alt else "",
                    fc if fc is not None else "(%s)" % ferr)
                other = [s for s in ("1p", "2p") if s not in cand and tot[s] is not None and tot[s] in want + ([fc] if fc else [])]
                if hint and other:
                    why += " on the %s side the video map names; the other side reads %s (side or identity to review)" % (
                        m.get("side"), tot[other[0]])
                elif fc is not None and any(tot[s] is not None for s in cand):
                    near = min((abs(tot[s] - fc), s) for s in cand if tot[s] is not None)
                    if near[0] <= 30:
                        why += " (%+d from our file: a repair candidate, not a certification)" % (tot[near[1]] - fc)
                row.update(verdict="REJECTED", why=why)
            rows.append(row)
        videos.append(dict(vid=vid, group=group, status=read.get("status"), skin=read.get("skin"), t=read.get("t"),
                           totals=tot, reason=read.get("reason"), charts=rows, not_yield=vid in NOT_YIELD,
                           channel=chan.get(vid, ""), landable=sorted(s for v, s in landable if v == vid)))
    out = dict(reads=a.reads, overrides=a.override or [], n_overridden=sum(1 for d in reads.values() if d.get("overridden")),
               n_reads=len(reads), timeouts=sorted(timeouts), converter_pin=pin, sides=sides, seeds=seeds, videos=videos)
    atomicio.write_json(a.out, out, encoding="utf-8", ensure_ascii=False, indent=1)
    certn = sum(len(s["certifies"]) for s in sides)
    print("%d reads; %d added sides (%d certify %d charts, %d move a band); %d seeds; %d videos accounted" % (
        len(reads), len(sides), sum(1 for s in sides if s["certifies"]), certn,
        sum(1 for s in sides if s["band_changes"]), len(seeds), len(videos)))
    print("-> %s" % a.out)


# ---------------------------------------------------------------- sheet

def crop_frame(f, read, side, pad=6, zoom=3):
    """PNG bytes: one side's six number rows on a result frame, enlarged - positions from the
    profile, the anchor and the side's column offset, never from the values."""
    import cv2
    import result_reader as rr
    prof = next(p for p in rr.load_profiles() if p["name"] == read["skin"])
    if (read.get("scale") or 1.0) != 1.0:
        f = cv2.resize(f, None, fx=1 / read["scale"], fy=1 / read["scale"], interpolation=cv2.INTER_AREA)
    _mx, loc = rr.match_anchor(f, prof["anchor"])
    ax, ay_c = loc[0], loc[1] + prof["cy"]
    s = read.get(side) or {}
    dx = s.get("dx") or 0
    nd = max(len(s.get(k, "")) for k in LABELS)
    cw, ch = prof["cw"], prof["ch"]
    if side == "1p":
        xa = ax - prof["x0"] + dx
        xb = xa + cw * nd
    else:
        xb = ax + prof["rx"] + dx
        xa = xb - cw * nd
    ya, yb = int(ay_c - prof["pitch"] * 5 - ch / 2), int(ay_c + ch / 2)
    c = f[max(0, ya - pad):yb + pad, max(0, xa - pad):xb + pad]
    c = cv2.resize(c, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", c)
    return png.tobytes() if ok else None


def crop_path(reads_dir, vid, skin, side):
    return os.path.join(reads_dir, "crops", "%s.%s.%s.png" % (vid, skin, side))


def crop_side(vid, read, side, reads_dir=None):
    """The side's crop: the one the read saved from its own frame (cert_skins' worker), else decoded
    again at the read's time (the caller holds a decode slot)."""
    if reads_dir:
        p = crop_path(reads_dir, vid, read["skin"], side)
        if os.path.exists(p):
            return open(p, "rb").read()
    import cv2
    import result_reader as rr
    cap = cv2.VideoCapture(rr.video_path(vid))
    f = rr.frame_at(cap, float(read["t"]))
    cap.release()
    return None if f is None else crop_frame(f, read, side)


def cmd_sheet(a):
    import supervise
    plan = json.load(open(a.plan, encoding="utf-8"))
    real = [s for s in plan["sides"] if not s["checks"] and s["confirm_t"] is not None and not s["not_yield"]
            and (s["certifies"] or s["band_changes"])]
    # diagnostic items: reads that cannot land (a failed check, a near miss) but whose true cells say
    # whether the profile misreads the font - for deciding a next revision, never for landing
    diag = {tuple(x.split(":")) for x in (a.diagnose.split(",") if a.diagnose else [])}
    real += [dict(s, diagnostic=True) for s in plan["sides"] if (s["vid"], s["side"]) in diag]
    done = set()
    for kp in a.done_keys or []:
        for pk in json.load(open(kp, encoding="utf-8"))["packets"].values():
            for it in pk["items"].values():
                if it["kind"] == "real" and not it["meta"].get("diagnostic"):
                    done.add((it["meta"]["vid"], it["meta"]["side"]))
    real = [s for s in real if s.get("diagnostic") or (s["vid"], s["side"]) not in done]
    items, seeds = [], []
    rd = plan["reads"]
    need = [x for x in real + plan["seeds"] if not os.path.exists(crop_path(rd, x["vid"], x["read"]["skin"], x["side"]))]
    import contextlib
    with (supervise.decode_slot(job="cert_land sheet") if need else contextlib.nullcontext()):
        for s in real:
            png = crop_side(s["vid"], s["read"], s["side"], rd)
            if png:
                items.append(dict(images=[("c", png)], ask=ASK, answer_format=FORMAT,
                                  meta=dict(vid=s["vid"], side=s["side"], cells=s["cells"], scope=s["scope"],
                                            diagnostic=bool(s.get("diagnostic")))))
        for s in plan["seeds"]:
            png = crop_side(s["vid"], s["read"], s["side"], rd)
            if png:
                seeds.append(dict(images=[("c", png)], ask=ASK, answer_format=FORMAT, answer=s["answer"],
                                  meta=dict(vid=s["vid"], side=s["side"], why=s["why"])))
    dirs, kpath = blind_packets.make(LOOP, a.batch, items, seeds, INSTRUCTIONS, per_packet=a.per_packet,
                                     seed_share=a.seed_share, rng_seed=a.seed)
    print("%d items + %d seeds available -> %d packets; key %s" % (len(items), len(seeds), len(dirs), kpath))
    for pid, d in dirs:
        print("  %s %s" % (pid, d))


# ---------------------------------------------------------------- land

def cmd_land(a):
    plan = json.load(open(a.plan, encoding="utf-8"))
    if len(a.keys) != len(a.answers):
        raise SystemExit("--keys and --answers come in pairs")
    blind, readers = {}, {}
    for kp, ap_ in zip(a.keys, a.answers):
        keys = json.load(open(kp, encoding="utf-8"))
        rep = blind_packets.score(keys, blind_packets.load_answers(ap_))
        readers[keys["batch"]] = rep["readers"]
        for iid, it in sorted(rep["items"].items()):
            k = (it["meta"]["vid"], it["meta"]["side"])
            cur = blind.get(k)
            if cur is None or (cur["meta"].get("diagnostic") and not it["meta"].get("diagnostic")):
                blind[k] = dict(item=iid, batch=keys["batch"], **it)
    L = ledgers()
    merged = corpus_map.merge_certification([L["corpus"], L["census"]])
    ledger, bands, verdicts = {}, [], []
    for s in plan["sides"]:
        why = []
        if s["not_yield"]:
            why.append("bootstrap or inspected footage (a profile or a revision was built on it)")
        if "Official" in (s.get("channel") or ""):
            why.append("official upload: benchmark identity only, never a certification")
        if s["checks"]:
            why += s["checks"]
        if s["confirm_t"] is None:
            why += s.get("confirm_fail") or ["no confirming second frame"]
        if not (s["certifies"] or s["band_changes"]):
            why.append("certifies nothing and moves no band")
        b = blind.get((s["vid"], s["side"]))
        if b and b["meta"].get("diagnostic"):
            why.append("diagnostic item: transcribed to judge the profile, never landed")
        if not why:
            if b is None:
                why.append("not in the blind batch")
            elif b["verdict"] != "AGREED":
                why.append("blind: %s" % b["why"])
            elif b["answer"] != blind_packets.normalize(s["cells"]):
                why.append("blind: the readers agree on %s, the reader read %s" % (b["answer"], s["cells"]))
        certs = [c for c in s["certifies"] if not c["elsewhere"]]
        dup = [c["chart"] for c in s["certifies"] if c["elsewhere"]]
        verdicts.append(dict(vid=s["vid"], side=s["side"], scope=s["scope"], landed=not why, why=why,
                             certifies=[c["chart"] for c in certs], already_certified_elsewhere=dup,
                             band_changes=s["band_changes"]))
        if why:
            continue
        e = merged[s["vid"]]
        entry = ledger.setdefault(s["vid"], dict(vid=s["vid"], **{k: v for k, v in s["read"].items() if v is not None},
                                                 charts={}, evidence=dict(sides={})))
        for c in certs:
            entry["charts"][c["chart"]] = dict(expected=c["expected"], side=s["side"], verdict="CERTIFIED",
                                               matched=c["matched"], via=c["via"])
        entry["evidence"]["sides"][s["side"]] = dict(
            skin=s["skin"], code=s["code"], checks="six digit cells; maxcombo <= P+G; no BAD/MISS -> maxcombo == P+G",
            confirm_t=s["confirm_t"], blind=dict(batch=b["batch"], packet=b["packet"], item=b["item"],
                                                  readers=sorted(b["votes"]), answer=b["answer"]))
        for bc in s["band_changes"]:
            bands.append(dict(vid=s["vid"], **bc, other_side=s["side"], other_total=s["total"]))
        assert all(n in (e.get("charts") or {}) for n in entry["charts"])
    atomicio.write_json(a.out, ledger, encoding="utf-8", ensure_ascii=False, indent=1)
    atomicio.write_json(a.bands, dict(
        purpose=("Certified charts whose reader band moves when %s merges: their video gained a read of the other "
                 "side, so every tool that picks a band from the certification (C for a one-sided screen, L/R for "
                 "a split one) now reads the chart's own half. Anything keyed on the old band - a counter scan, a "
                 "sprite pass, a trace-audit verdict - is re-baselined on this list." % os.path.basename(a.out)),
        bands=bands), encoding="utf-8", ensure_ascii=False, indent=1)
    atomicio.write_json(a.report, dict(blind=readers, verdicts=verdicts), encoding="utf-8",
                        ensure_ascii=False, indent=1)
    n_c = sum(len(e["charts"]) for e in ledger.values())
    print("landed %d videos, %d charts newly certified, %d band moves; %d sides refused" % (
        len(ledger), n_c, len(bands), sum(1 for v in verdicts if not v["landed"])))


# ---------------------------------------------------------------- ERA

def cmd_era(a):
    plan = json.load(open(a.plan, encoding="utf-8"))
    rows = []
    for v in plan["videos"]:
        for c in v["charts"]:
            if c["verdict"] == "ERA":
                rows.append(dict(vid=v["vid"], chart=c["chart"], side=c["side"], skin=v["skin"], t=v["t"],
                                 screen=c["screen"], cells=c["cells"], checks=c["checks"], catalog=c["expected"],
                                 judged_alt=c["judged_alt"], file=c["file"], key=c["key"], ssc_rel=c["ssc_rel"],
                                 block_sha=c["block_sha"], header_sha=c["header_sha"], converter_pin=c["converter_pin"]))
    doc = dict(purpose=("ERA staging (bucket #12): the result screen's total equals OUR file's lattice count while the "
                        "catalog says otherwise - the footage shows an older revision of the chart, which the file "
                        "copies faithfully. Staged only: no loop reads this file, and a row is never a close, a skip or "
                        "an exclusion. A row is void the moment its block_sha, header_sha or converter_pin no longer "
                        "matches (cert_land.py era-check). Whether ERA rows may be committed under sources/ is the "
                        "owner's call."), rows=rows)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    atomicio.write_json(a.out, doc, encoding="utf-8", ensure_ascii=False, indent=1)
    print("%d ERA rows on %d videos -> %s" % (len(rows), len({r["vid"] for r in rows}), a.out))


def cmd_era_check(a):
    import corpus_grade as CG
    import guards
    doc = json.load(open(a.file, encoding="utf-8"))
    pin = CG.converter_pin()["pin"]
    stale = []
    for r in doc["rows"]:
        path = os.path.join(ROOT, "simfiles", r["ssc_rel"]) if r.get("ssc_rel") else None
        data = open(path, "rb").read() if path and os.path.exists(path) else None
        if data is None:
            stale.append((r["chart"], "file gone"))
            continue
        tag = guards.tag_of(r["key"])
        now = (guards.block_sha_text(data, tag), guards.header_sha_text(data), pin)
        was = (r["block_sha"], r["header_sha"], r["converter_pin"])
        if now != was:
            stale.append((r["chart"], "changed: %s" % ", ".join(n for n, x, y in zip(("block", "header", "converter"), now, was) if x != y)))
    print("%d rows, %d void" % (len(doc["rows"]), len(stale)))
    for s in stale:
        print("  VOID %s: %s" % s)
    sys.exit(1 if stale else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--reads", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--override", action="append", help="a later revision's read_one files (repeatable)")
    p = sub.add_parser("sheet")
    p.add_argument("--plan", required=True)
    p.add_argument("--batch", required=True)
    p.add_argument("--per-packet", type=int, default=24)
    p.add_argument("--seed-share", type=float, default=0.25, help="seeds per real item in a packet (a small batch wants more)")
    p.add_argument("--seed", type=int)
    p.add_argument("--diagnose", help="vid:side,... reads to transcribe that cannot land (never landed)")
    p.add_argument("--done-keys", action="append", help="an earlier batch's keys: its real sides are not asked again")
    p = sub.add_parser("land")
    p.add_argument("--plan", required=True)
    p.add_argument("--keys", required=True, action="append")
    p.add_argument("--answers", required=True, action="append")
    p.add_argument("--out", required=True)
    p.add_argument("--bands", required=True)
    p.add_argument("--report", required=True)
    p = sub.add_parser("era")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("era-check")
    p.add_argument("file")
    p = sub.add_parser("whatif")
    p.add_argument("--extra", required=True)
    p.add_argument("--out")
    a = ap.parse_args()
    {"plan": cmd_plan, "sheet": cmd_sheet, "land": cmd_land, "era": cmd_era, "era-check": cmd_era_check,
     "whatif": cmd_whatif}[a.cmd](a)


if __name__ == "__main__":
    main()
