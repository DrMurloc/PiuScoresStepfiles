# Which of our stepfiles does The Resistance's CURRENT file disagree with, and where the
# catalog can judge, whose is right? Their packs are the upstream of the mirror this corpus
# was seeded from, and a fix they make to a chart already published reaches only the packs.
#
#   python -X utf8 tools/pack_census.py fetch      (SYSTEM python: pyzipper; needs RESISTANCE_PACK_PASSWORD)
#   <venv python> -X utf8 tools/pack_census.py compare [--out sources/resistance-diff-<date>.json]
#
# fetch reads, out of every pack on the hub, only the .ssc entries whose file name is one of
# ours (range requests, nothing else downloaded), into work/packs/<PACK>/<entry path> with an
# index of dates and hashes. It is resumable. compare runs on the piu-annotate venv because it
# converts every differing block with the pipeline's own converter.
#
# What compare calls a difference: a block is the set of its judged events - (beat, row) with
# rows in the pipeline's 0123 vocabulary, a half-double padded to ten columns - plus the six
# tags the converter reads (BPMS, WARPS, STOPS, DELAYS, FAKES, TICKCOUNTS) parsed as numbers.
# How finely a measure is written, the slot label, the visual tags (SPEEDS, SCROLLS, LABELS)
# and the mirror's own additions (CHARTSTYLE, LASTSECONDHINT) are not differences. Blocks are
# paired identical-first, then same events, then same meter, then nearest meter within two,
# so a Phoenix 2 re-rate still meets its own chart. Where a song sits in several packs the
# newest copy is "current" and the others are checked against it.
#
# Where the catalog can judge - the 2026-09-08 sweep's reference count, a census chart's
# judged count, or the certification ledger's expected count - each differing pair gets a
# verdict: theirs exact / ours exact / both exact / theirs closer / ours closer. Where it
# cannot, the two implied totals are reported side by side and nothing is claimed.
import datetime
import hashlib
import json
import os
import re
import sys
from collections import Counter
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
WORK = os.path.join(ROOT, "work", "packs")
INDEX = os.path.join(WORK, "index.json")
PACKS = [("PHOENIX2", "PHOENIX2 songpack"), ("PHOENIX", "PHOENIX songpack"), ("XX", "XX songpack"),
         ("PRIME2", "PRIME2 songpack"), ("STEPP1", "Compilation")]
TIMING = ("BPMS", "WARPS", "STOPS", "DELAYS", "FAKES", "TICKCOUNTS")
VERDICTS = ["theirs exact", "theirs closer", "both exact", "same distance", "same count, no reference",
            "differs, no reference", "ours closer", "ours exact, theirs off", "not converted",
            "pack-only block", "ours-only block"]


def corpus_files():
    """lower-cased file name -> [simfiles-relative path]; every name is unique today."""
    out = {}
    sim = os.path.join(ROOT, "simfiles")
    for root, _, files in os.walk(sim):
        for f in files:
            if f.lower().endswith(".ssc"):
                out.setdefault(f.lower(), []).append(os.path.relpath(os.path.join(root, f), sim).replace(os.sep, "/"))
    return out


# ---------------------------------------------------------------- fetch

def fetch():
    import resistance_packs as rp
    password = os.environ.get("RESISTANCE_PACK_PASSWORD") or sys.exit("set RESISTANCE_PACK_PASSWORD")
    ours = corpus_files()
    index = json.load(open(INDEX, encoding="utf-8")) if os.path.isfile(INDEX) else {}
    for label, part in PACKS:
        f, rf, z = rp.open_pack(part, password)
        wanted = sorted((i for i in z.infolist() if i.filename.lower().endswith(".ssc")
                         and os.path.basename(i.filename).lower() in ours), key=lambda i: i.header_offset)
        done = 0
        for n, i in enumerate(wanted, 1):
            key = f"{label}/{i.filename}"
            out = os.path.join(WORK, label, *i.filename.split("/"))
            if key in index and os.path.isfile(out) and os.path.getsize(out) == i.file_size:
                continue
            try:
                data = z.read(i)
            except Exception as ex:            # a stale direct link: resolve it again, once
                print(f"   retry after {type(ex).__name__}: {ex}", flush=True)
                f, rf, z = rp.open_pack(part, password)
                data = z.read(i)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(data)
            index[key] = dict(pack=f["filename"], label=label, entry=i.filename, size=i.file_size,
                              date=datetime.datetime(*i.date_time).isoformat(sep=" "),
                              sha1=hashlib.sha1(data).hexdigest(), ours=ours[os.path.basename(i.filename).lower()][0])
            done += 1
            if done % 25 == 0:
                json.dump(index, open(INDEX, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
                print(f"   {label}: {n}/{len(wanted)} ({rf.fetched:,} bytes so far)", flush=True)
        json.dump(index, open(INDEX, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"{f['filename']}: {len(wanted)} of ours, {done} fetched now, {rf.fetched:,} bytes over the network", flush=True)
    print(f"index: {len(index)} entries")


# ---------------------------------------------------------------- compare

def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def official(sc):
    sc.data.setdefault("DESCRIPTION", "")       # a few upstream blocks carry no label at all
    try:
        return (sc.standard_stepstype() and sc.standard_songtype() and not sc.has_99_meter()
                and not any(f() for f in (sc.is_ucs, sc.is_coop, sc.is_hidden, sc.is_quest, sc.is_infinity,
                                          sc.is_train, sc.is_pro, sc.is_performance, sc.is_jump_edition)))
    except KeyError:
        return False


def events(sc):
    """The chart as the set of its judged events, independent of how finely each measure is written."""
    from piu_annotate.formats import notelines
    out = set()
    for mi, measure in enumerate(sc["NOTES"].split(",")):
        rows = [notelines.parse_line(t) for l in measure.split("\n")
                if (t := l.split("//")[0].strip()) and not t.startswith("#")]
        for k, r in enumerate(rows):
            if r.strip("0"):
                if len(r) == 6:
                    r = "00" + r + "00"
                out.add((mi * 4 + Fraction(4 * k, len(rows)), r))
    return frozenset(out)


def timing(sc):
    out = {}
    for tag in TIMING:
        vals = []
        for e in re.sub(r"\s+", "", sc.get(tag, "") or "").split(","):
            if "=" in e:
                b, v = e.split("=", 1)
                try:
                    vals.append((round(float(b), 6), round(float(v), 6)))
                except ValueError:
                    vals.append((b, v))
        out[tag] = tuple(vals)
    return out


def info(sc):
    fam = "S" if sc["STEPSTYPE"] == "pump-single" else "D"
    meter = int(sc["METER"]) if str(sc["METER"]).strip().isdigit() else -1
    try:
        ev, bad = events(sc), ""
    except Exception as ex:
        ev, bad = None, f"{type(ex).__name__}: {ex}"[:80]
    return dict(sc=sc, fam=fam, meter=meter, code=f"{fam}{sc['METER']}", events=ev, timing=timing(sc), bad=bad,
                key=sc.shortname(), pair=None)


def signature(blocks):
    return sorted((b["fam"], hash(b["events"]), hash(tuple(sorted(b["timing"].items())))) for b in blocks)


def convert(sc):
    from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct
    try:
        df, ht, msg = stepchart_ssc_to_chartstruct(sc)
    except Exception as ex:
        return None, None, None, f"error {type(ex).__name__}"
    if df is None:
        return None, None, None, msg
    taps = int(df["Line"].str.contains("1", regex=False).sum())
    ticks = sum(int(round(t[2])) for t in ht)
    return taps, ticks, taps + ticks, "ok"


def pair_blocks(ours, pack):
    used, pairs = set(), []

    def take(score, how):
        for o in ours:
            if o["pair"] is not None or o["events"] is None:
                continue
            best = None
            for j, p in enumerate(pack):
                if j in used or p["events"] is None or o["fam"] != p["fam"]:
                    continue
                s = score(o, p)
                if s is not None and (best is None or s < best[0]):
                    best = (s, j)
            if best is not None:
                o["pair"] = best[1]
                used.add(best[1])
                pairs.append((o, pack[best[1]], how))

    take(lambda o, p: 0 if o["events"] == p["events"] and o["timing"] == p["timing"] else None, "identical")
    take(lambda o, p: 0 if o["events"] == p["events"] else None, "same events")
    take(lambda o, p: 0 if o["meter"] == p["meter"] else None, "same meter")

    def overlap(o, p):      # the same steps under another meter: an old-mix label, a Phoenix 2 re-rate
        union = len(o["events"] | p["events"])
        j = len(o["events"] & p["events"]) / union if union else 0
        return 1 - j if j >= 0.5 else None
    take(overlap, "same steps, other meter")
    take(lambda o, p: abs(o["meter"] - p["meter"]) if abs(o["meter"] - p["meter"]) <= 2 else None, "nearest meter")
    return pairs, [o for o in ours if o["pair"] is None], [p for j, p in enumerate(pack) if j not in used]


def verdict(ours_i, theirs_i, ref):
    if ours_i is None or theirs_i is None:
        return "not converted"
    if ref is None:
        return "same count, no reference" if ours_i == theirs_i else "differs, no reference"
    do, dt = abs(ours_i - ref), abs(theirs_i - ref)
    if do == 0 and dt == 0:
        return "both exact"
    if dt == 0:
        return "theirs exact"
    if do == 0:
        return "ours exact, theirs off"
    return "theirs closer" if dt < do else "ours closer" if do < dt else "same distance"


def load_refs():
    def src(n):
        return json.load(open(os.path.join(ROOT, "sources", n), encoding="utf-8"))
    tail = {r["key"]: r for r in src("tail-2026-09-08.json")["charts"]}
    judged = {c["chart"]: int(c["judged"]) for c in src("census-final.json") if str(c.get("judged", "")).strip().isdigit()}
    census = {m["key"]: judged.get(m["chart"]) for m in src("ssc-map.json")}
    repaired = {r["key"] for r in src("repairs.json")}
    cert = {}
    for v in src("certification-corpus-2026-09-10.json").values():
        for name, c in (v.get("charts") or {}).items():
            if c.get("expected"):
                cert.setdefault(norm(name), int(c["expected"]))
    p1cat = {}
    for c in src("p1-note-counts-2026-07-04.json")["charts"]:
        if c["p1_notes"]:
            p1cat.setdefault((norm(c["song"]), c["type"][0], c["p1_level"]), c["p1_notes"])
    return tail, census, repaired, cert, p1cat


def compare(out_path):
    from piu_annotate.formats.sscfile import SongSSC
    tail, census, repaired, cert, p1cat = load_refs()
    index = json.load(open(INDEX, encoding="utf-8"))
    by_ours = {}
    for e in index.values():
        by_ours.setdefault(e["ours"], []).append(e)

    def parse(path, label):
        try:
            return SongSSC(path, label), ""
        except Exception as ex:
            return None, f"{type(ex).__name__}: {ex}"[:100]

    def reference(o):
        key = o["key"]
        if key in tail:
            r = tail[key]
            return r["implied"] - r["delta"], "catalog (sweep 2026-09-08)", r
        if census.get(key):
            return census[key], "judged (census video)", None
        n = norm(f"{o['sc']['TITLE']} {o['code']}")
        if n in cert:
            return cert[n], "catalog (certification ledger)", None
        k = (norm(o["sc"]["TITLE"]), o["fam"], o["meter"])
        if k in p1cat:
            return p1cat[k], "catalog (Phoenix 1 note count, chart list 2026-07-04)", None
        return None, None, None

    rows, disagree, errors = [], [], []
    n_files = n_ident_files = n_blocks = n_ident = 0
    for rel in sorted(set(p for ps in corpus_files().values() for p in ps)):
        copies = sorted(by_ours.get(rel, []), key=lambda e: e["date"], reverse=True)
        if not copies:
            errors.append((rel, "no pack copy fetched"))
            continue
        song_o, err = parse(os.path.join(ROOT, "simfiles", *rel.split("/")), "ours")
        if err:
            errors.append((rel, "ours: " + err))
            continue
        parsed = []
        for c in copies:
            s, err = parse(os.path.join(WORK, c["label"], *c["entry"].split("/")), c["label"])
            if err:
                errors.append((f"{c['label']}/{c['entry']}", err))
            else:
                parsed.append((c, s))
        if not parsed:
            continue
        cur, song_p = parsed[0]
        ours_b = [info(sc) for sc in song_o.stepcharts if official(sc)]
        pack_b = [info(sc) for sc in song_p.stepcharts if official(sc)]
        others = [dict(label=c["label"], date=c["date"],
                       same=signature([info(sc) for sc in s.stepcharts if official(sc)]) == signature(pack_b))
                  for c, s in parsed[1:]]
        if any(not o["same"] for o in others):
            disagree.append(dict(ours=rel, current=dict(label=cur["label"], date=cur["date"]), others=others))
        pairs, ours_only, pack_only = pair_blocks(ours_b, pack_b)
        n_files += 1
        n_blocks += len(ours_b)
        file_rows = []
        for o, p, how in pairs:
            if how == "identical":
                n_ident += 1
                continue
            tags = [t for t in TIMING if o["timing"][t] != p["timing"][t]]
            changed = len(o["events"] ^ p["events"])
            kind = ("notes+timing" if changed and tags else "notes" if changed
                    else "ticks" if tags == ["TICKCOUNTS"] else "timing")
            ot, ok, oi, om = convert(o["sc"])
            pt, pk, pi, pm = convert(p["sc"])
            ref, ref_src, trow = reference(o)
            file_rows.append(dict(
                key=o["key"], chart=f"{o['sc']['TITLE']} {o['code']}", ours_ssc=rel, pack=cur["label"], pack_entry=cur["entry"],
                pack_date=cur["date"], paired_by=how, meter_theirs=p["meter"], desc_theirs=p["sc"]["DESCRIPTION"],
                kind=kind, events_changed=changed, tags_changed=tags,
                ours=dict(taps=ot, ticks=ok, implied=oi, status=om), theirs=dict(taps=pt, ticks=pk, implied=pi, status=pm),
                ref=ref, ref_src=ref_src, verdict=verdict(oi, pi, ref), in_tail=o["key"] in tail, repaired=o["key"] in repaired,
                tail_shape=trow["shape"] if trow else None, tail_pct=trow["pct"] if trow else None,
                chartId=trow["chartId"] if trow else None, credit=(p["sc"].get("CREDIT") or "").strip(),
                packs_disagree=any(not x["same"] for x in others)))
        for p in pack_only:
            file_rows.append(dict(key=None, chart=f"{p['sc']['TITLE']} {p['code']}", ours_ssc=rel, pack=cur["label"],
                                  pack_entry=cur["entry"], pack_date=cur["date"], paired_by="pack only", meter_theirs=p["meter"],
                                  desc_theirs=p["sc"]["DESCRIPTION"], kind="pack-only block", verdict="pack-only block",
                                  credit=(p["sc"].get("CREDIT") or "").strip()))
        for o in ours_only:
            file_rows.append(dict(key=o["key"], chart=f"{o['sc']['TITLE']} {o['code']}", ours_ssc=rel, pack=cur["label"],
                                  pack_entry=cur["entry"], pack_date=cur["date"], paired_by="ours only", kind="ours-only block",
                                  verdict="ours-only block", in_tail=o["key"] in tail))
        if not file_rows:
            n_ident_files += 1
        rows += file_rows

    def gain(r):
        return abs(r["ours"]["implied"] - r["ref"]) if r.get("ref") is not None and r.get("ours", {}).get("implied") is not None else 0
    rows.sort(key=lambda r: (VERDICTS.index(r["verdict"]), -gain(r), r["chart"]))

    verdicts = Counter(r["verdict"] for r in rows)
    seen = {r["key"]: r["verdict"] for r in rows if r.get("key")}
    tail_state = Counter(seen.get(k, "identical to ours") for k in tail)
    counts = dict(files=n_files, files_identical=n_ident_files, official_blocks_ours=n_blocks, blocks_identical=n_ident,
                  pairs_differing=sum(1 for r in rows if r.get("key") and r["paired_by"] != "ours only"),
                  by_kind=dict(Counter(r["kind"] for r in rows)), verdicts={v: verdicts[v] for v in VERDICTS if verdicts[v]},
                  tail_charts=dict(tail_state.most_common()), packs_disagree=len(disagree), parse_errors=len(errors))
    out = dict(generated=datetime.date.today().isoformat(), source="tools/pack_census.py compare (rule in its header)",
               packs={lab: sorted({e["pack"] for e in index.values() if e["label"] == lab}) for lab, _ in PACKS},
               counts=counts, charts=rows, packs_disagree=disagree, errors=[dict(what=a, error=b) for a, b in errors])
    out_path = out_path or os.path.join(ROOT, "sources", f"resistance-diff-{datetime.date.today().isoformat()}.json")
    json.dump(out, open(out_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(counts, indent=1))
    print(f"\nwrote {out_path}")
    for r in rows[:40]:
        if r.get("key") and r.get("ours"):
            print(f"  {r['verdict']:<24} {r['chart']:<44} ours {r['ours']['implied']!s:>5}  theirs {r['theirs']['implied']!s:>5}  "
                  f"ref {r['ref']!s:>5}  {r['kind']:<12} {r['events_changed']:>4} ev  {r['pack']}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["fetch"]:
        fetch()
    elif sys.argv[1:2] == ["compare"]:
        compare(sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None)
    else:
        sys.exit("usage: pack_census.py fetch | compare [--out <json>]")
