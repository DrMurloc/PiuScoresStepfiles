# Lane-fit rules over the median-band cache (laneband.py): the frozen census, partitions and
# per-template pitch bands they are judged against, and the rules themselves.
#
# Bucket #4 of the 2026-09-26 loop proposal (work/loop-buckets-2026-09-26.txt). The lanes are what
# every reader looks through, and the largest measured extractor bug class is a fit whose lanes do
# not sit on the receptors: 36 certified charts fit at a 49-67px pitch where the footage has 75.5.
# A rule here is pure arithmetic over each video's cached median band, so a candidate over every
# cached video costs minutes rather than a 35 CPU-hour re-decode.
#
# What is frozen before any rule is graded (sources/lanes/, committed):
#   partitions   which charts are held out. Held out: the PHOENIX 2 official pack (count-exact files
#                on Andamiro's uploads) plus the 36 certified misfits. Held-out charts named anywhere
#                in docs, tools or the research notes are moved to 'seen' (tune-only); the rest are
#                grouped by song family and video and split into a validation half and a sealed test
#                half. Quarantined and owner-revisit charts are excluded from every benchmark.
#                v2 (partitions-2026-09-27.v2.json) corrects v1's scan before any F1: a chart named by
#                title and level token in one phrase, and every held-out chart on a video carrying a
#                named chart, is 'seen' (see build_partitions_v2); the correction is in the looks ledger.
#   census       every fit the corpus asks for (certified charts, official charts, every cached .inset
#                fit), with its template, partition and the BEFORE fit stamped with the rule that
#                made it (receptors._fit_field's code stamp). v2 is v1's rows relabelled under
#                partitions v2 ('seen' outranks both halves); nothing in a row but its partition moves.
#   bands        per-template pitch bands, from tune-partition fits only. A template is assigned from
#                metadata - channel and layout (band, columns) - never from pitch.
#   rules        each rule's id and code stamp, registered before it is run; with the effect the
#                held-out validation gate must show, written before any held-out look.
#
#   lanefit.py partitions [--write] [--v1] build (and freeze) partitions v2 from v1 (--v1: v1's builder)
#   lanefit.py census [--write] [--v1]     census v2: v1 relabelled under partitions v2 (--v1: v1's builder)
#   lanefit.py recompute                   BEFORE fits recomputed from the cache: every cached .inset
#                                          fit must come back byte for byte; zero recomputed = exit 1
#   lanefit.py sample [--write] [--missing F]  the band sample (frozen before any band is computed)
#   lanefit.py bands [--write]             per-template pitch bands and the receptor library, from the sample
#   lanefit.py sensitivity [--out F]       the bands and library without the band-sample videos that
#                                          carry a held-out song family (never writes a band)
#   lanefit.py register r1-oob-sym-respan  register a rule's code stamp and pre-registered effect
#   lanefit.py rule1 [--partitions P]      rule 1 over the finished part of the cache: the tune side by
#                   [--heldout-look WHAT]  default; a held-out half only with --heldout-look (logged,
#                                          output under work/lanes/heldout/, never a development input)
#   lanefit.py split <rule output>         move the held-out rows of an older rule output out of the
#                                          development files (computes nothing)
#   lanefit.py look --kind look|correction the hash-chained held-out looks ledger
import argparse
import bisect
import hashlib
import io
import json
import os
import re
import sys
import time
import contextlib
from collections import Counter, defaultdict

import cv2
import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import atomicio as A                                  # noqa: E402
import cachekey                                       # noqa: E402
import corpus_map                                     # noqa: E402
import laneband as LB                                 # noqa: E402
import receptors as R                                 # noqa: E402

DATE = "2026-09-27"
SRC = os.path.join(ROOT, "sources", "lanes")
WORK = os.path.join(ROOT, "work", "lanes")
PARTITIONS_V1 = os.path.join(SRC, "partitions-%s.json" % DATE)
CENSUS_V1 = os.path.join(SRC, "census-before-%s.json" % DATE)
# v2 (verification round 1): the partition correction; everything reads these from now on, and the
# v1 tables stay committed as the record of what was frozen first
PARTITIONS = os.path.join(SRC, "partitions-%s.v2.json" % DATE)
CENSUS = os.path.join(SRC, "census-before-%s.v2.json" % DATE)
BANDS = os.path.join(SRC, "pitch-bands-%s.json" % DATE)
RULES = os.path.join(SRC, "rules.jsonl")
LOOKS = os.path.join(SRC, "heldout-looks.jsonl")
SALT = "lanes-1/2026-09-27/validate-vs-sealed"
BEFORE_RULE = "field.inset@" + R.FIELD_CODE_LEGACY          # the rule that made every cached .inset fit


def sha_obj(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_frozen(path, obj):
    """Write a frozen table with its own sha256 over everything else in it. A frozen table is written
    once: a correction is a new version beside it, never an overwrite."""
    if os.path.exists(path):
        raise SystemExit("%s is frozen already - a correction is a new version, never an overwrite"
                         % os.path.relpath(path, ROOT))
    obj = dict(obj)
    obj.pop("sha256", None)
    obj["sha256"] = sha_obj(obj)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    A.write_text(path, json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8",
                 newline="\n")
    return obj["sha256"]


def read_frozen(path):
    obj = load_json(path)
    want = obj.pop("sha256", None)
    got = sha_obj(obj)
    if want != got:
        raise SystemExit("%s: sha256 %s does not match its content (%s) - a frozen table was edited"
                         % (path, want, got))
    obj["sha256"] = want
    return obj


# ---------------------------------------------------------------- metadata

def ncols_of(name):
    return 10 if name.split()[-1][0] == "D" else 5


def family(name):
    """A chart's song family: its title without the level, cut, remix or full-song marker."""
    t = name.rsplit(" ", 1)[0] if re.match(r"^[SD]P?\d+$", name.split()[-1]) else name
    t = re.sub(r"\s*-\s*(FULL SONG|SHORT CUT|REMIX)\s*-\s*", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def chgroup(channel):
    if channel is None:
        return "NOT_IN_MAP"
    if "Official" in channel:
        return "OFFICIAL"
    if channel == "NEVSISTER":
        return "NEVSISTER"
    return "OTHER"


def template_of(group, band, ncols):
    return "%s:%s:%d" % (group, band, ncols)


class Meta:
    """Everything the partitions and the census are built from, read once."""

    def __init__(self):
        self.vids = sorted(f[:-4] for f in os.listdir(os.path.join(ROOT, "videos")) if f.endswith(".mp4"))
        self.have = set(self.vids)
        self.cert = corpus_map.certification()
        self.vmap = {e["vid"]: e for e in load_json(os.path.join(ROOT, "work", "corpus-video-map.json"))}
        self.smap = corpus_map.chart_map()
        g = load_json(os.path.join(ROOT, "sources", "corpus-grade.json"))
        self.grade = {c["chart"]: c for c in g["charts"]}
        self.tail = {r["chartId"]: r for r in load_json(os.path.join(ROOT, "sources", "tail-2026-09-08.json"))["charts"]}
        self.quarantine = {c["chart"] for c in load_json(os.path.join(ROOT, "sources", "quarantine.json")).get("charts", [])}
        self.revisit = {c["chart"] for c in load_json(os.path.join(ROOT, "sources", "owner-revisit.json")).get("charts", [])}
        self.corrupt = {e["vid"]: e for e in load_json(os.path.join(ROOT, "sources", "footage-corrupt.json"))["videos"]}
        self.extract = load_json(os.path.join(ROOT, "sources", "extract-loop-2026-09-23.json"))["charts"]

    def group_of(self, vid):
        return chgroup((self.vmap.get(vid) or {}).get("channel"))

    def certified_spec(self, vid, name):
        """(band, ncols, side) note_extract.extract reads a certified chart through."""
        e = self.cert[vid]
        ce = e["charts"][name]
        side = ce.get("side") or "1p"
        other = e.get("2p" if side == "1p" else "1p") or {}
        band = "C" if not other.get("judged") else ("L" if side == "1p" else "R")
        return band, ncols_of(name), side


def official_exact(meta):
    """{(vid, chart): {pack, judged, implied, exact}} for every chart on a cached official upload:
    the file converted by the pinned converter against the count the map carries (official_bench,
    2026-09-26 research, which found 565 of 581 exact)."""
    import tick_verify
    out = {}
    for vid, e in meta.vmap.items():
        if "Official" not in (e.get("channel") or "") or vid not in meta.have:
            continue
        for c in e["charts"]:
            t = meta.tail.get(c.get("chartId"), {})
            o = meta.smap.get(c["chart"])
            implied = None
            if o:
                path = os.path.join(ROOT, "simfiles", o["ssc_rel"].replace("/", os.sep))
                with contextlib.redirect_stdout(io.StringIO()):
                    try:
                        res = tick_verify.run(path, tick_verify.block_of(o["key"]))
                        if res:
                            implied = res[0] + sum(round(x[2]) for x in res[1])
                    except Exception:
                        implied = None
            out[(vid, c["chart"])] = dict(pack=t.get("pack"), judged=c.get("judged"), implied=implied,
                                          exact=implied is not None and implied == c.get("judged"),
                                          stored_side=c.get("side") or "", n_charts=len(e["charts"]))
    return out


def misfits(meta):
    """The 36 certified misfits: charts of the extraction loop's population (sources/extract-loop-
    2026-09-23.json) whose cached .inset fit sits outside a 74-77px pitch (research b2_join)."""
    out = {}
    for c in meta.extract:
        name, vid = c["chart"], c.get("vid")
        if not vid or vid not in meta.cert or name not in (meta.cert[vid].get("charts") or {}):
            continue
        band, ncols, side = meta.certified_spec(vid, name)
        t = LB.inset_text(vid, band, ncols, side)
        if t is None:
            continue
        p = json.loads(t)["pitch"]
        if not (74 <= p <= 77):
            out[name] = dict(vid=vid, band=band, ncols=ncols, side=side, pitch=p)
    return out


# ---------------------------------------------------------------- partitions

RESEARCH_LIST_MAX = 10     # a research file naming more corpus charts than this is a listing, not an inspection
RESEARCH_EXTS = (".py", ".txt", ".json")
RESEARCH_JSON_MAX = 20000  # bytes: a larger research file is a script's output, never read
# The revision whose tracked docs and tools the freeze scanned: the v1 freeze commit. The scan reads
# that revision through git, never the working tree, so text written after a held-out look (this
# bucket's own STATUS section names a sealed chart) cannot move a chart out of the held-out halves.
SEEN_REV = "9f8baf6"
RESEARCH = os.path.join(ROOT, "work", "research-2026-09-26")


def _git(*args):
    import subprocess
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return r.stdout


def tracked_texts(rev):
    """{path: text} for the docs (*.md under docs/), the tools (*.py under tools/, this file and
    childsite excluded) and the root *.md, as committed at `rev`."""
    out = {}
    for p in _git("ls-tree", "-r", "--name-only", rev).decode("utf-8").split("\n"):
        if not p:
            continue
        top = p.split("/")[0]
        if (top == "docs" and p.endswith(".md")) or ("/" not in p and p.endswith(".md")) or \
                (top == "tools" and p.endswith(".py") and "childsite" not in p and "__pycache__" not in p
                 and p != "tools/lanefit.py"):
            out[p] = _git("show", "%s:%s" % (rev, p)).decode("utf-8", "replace")
    return out


def research_files(all_charts):
    """Every file under the research notes: (relpath, file name, text or None, charts named, size,
    read?, why not). A file is read when it is a script, text or JSON of at most RESEARCH_JSON_MAX
    bytes naming at most RESEARCH_LIST_MAX corpus charts."""
    out = []
    for dp, dn, fn in os.walk(RESEARCH):
        for f in sorted(fn):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, ROOT)
            size = os.path.getsize(p)
            if f.endswith((".png", ".jpg", ".npz", ".npy", ".pkl", ".pyc", ".mp4")):
                out.append(dict(rel=rel, name=f, text=None, named=[], size=size, read=False, why="binary"))
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                t = fh.read()
            named = [c for c in all_charts if c in t]
            why = None
            if not f.endswith(RESEARCH_EXTS):
                why = "extension"
            elif size > RESEARCH_JSON_MAX:
                why = "size"
            elif len(named) > RESEARCH_LIST_MAX:
                why = "listing"
            out.append(dict(rel=rel, name=f, text=t, named=named, size=size, read=why is None, why=why))
    return out


def seen_corpus(all_charts, rev=SEEN_REV, research=None):
    """The text in which a chart counts as 'previously inspected': the docs, the tools (this bucket's
    own included - its preflight videos are named in code) and the root *.md as committed at `rev`,
    the loop proposal, and those research notes (scripts, texts, JSON under 20 KB) that name at most
    RESEARCH_LIST_MAX corpus charts: a file listing dozens of charts is a script's output over a
    population, not a look at any one of them. File names anywhere under the research notes count
    too - an image or a notes file named after a video is a video someone looked at. Returns (text,
    file names, research files used, skipped listings, {source: text})."""
    by_src = dict(tracked_texts(rev))
    by_src["work/loop-buckets-2026-09-26.txt"] = open(os.path.join(ROOT, "work", "loop-buckets-2026-09-26.txt"),
                                                      encoding="utf-8").read()
    research = research if research is not None else research_files(all_charts)
    used, skipped = [], []
    for r in research:
        if r["read"]:
            used.append(r["rel"])
            by_src[r["rel"].replace("\\", "/")] = r["text"]
        elif r["why"] == "listing":
            skipped.append((r["rel"], len(r["named"])))
    return ("\n".join(by_src.values()), "\n".join(r["name"] for r in research), used, skipped, by_src)


# ---- v2: a chart named by its title and its level token in one phrase ("Legendary Dominion S20
# and S16", "DESTRUCIMATE S21 (...), D23 (...)"), not only as the exact string 'Title Level'.

LEVEL_TOKEN = re.compile(r"(?<![\w])[SD]P?\d{1,2}(?![\w])")
PHRASE_CHARS = 120             # a phrase runs at most this far past its title
PHRASE_STOPS = (". ", "; ")    # and ends at a sentence or clause end


def title_variants(title):
    """The spellings a title is written in: as the corpus has it, without its '- FULL SONG -' /
    '- SHORT CUT -' / '- REMIX -' marker, and without the simfile's backslash escapes."""
    out = {title, title.replace("\\", "")}
    bare = re.sub(r"\s*-\s*(FULL SONG|SHORT CUT|REMIX)\s*-\s*$", "", title, flags=re.I).strip()
    out |= {bare, bare.replace("\\", "")}
    return {v for v in out if v}


def _occurrences(text, variants):
    """Every word-bounded occurrence of every variant in `text`: [(start, end, variant)], sorted,
    with occurrences inside a longer one dropped ('Dominion' inside 'Legendary Dominion')."""
    def w(ch):
        return ch.isalnum() or ch == "_"
    occ = []
    n = len(text)
    for v in variants:
        i = text.find(v)
        while i >= 0:
            j = i + len(v)
            if (i == 0 or not (w(text[i - 1]) and w(v[0]))) and (j == n or not (w(text[j]) and w(v[-1]))):
                occ.append((i, j, v))
            i = text.find(v, i + 1)
    occ.sort(key=lambda o: (o[0], -(o[1] - o[0])))
    kept, reach = [], -1
    for o in occ:
        if o[1] <= reach:
            continue
        kept.append(o)
        reach = max(reach, o[1])
    return kept


def phrase_named(by_src, all_charts):
    """{chart: (source, excerpt)} for every corpus chart whose title is followed, within one phrase,
    by its level token. The phrase starts at the end of the title, runs at most PHRASE_CHARS, and
    ends at a sentence or clause end or where another title followed by a level token starts
    ('QUATTUORUX D24 ..., OVERNIGHT FLOWER D26': D26 is OVERNIGHT FLOWER's). Whitespace, line
    breaks included, is one space. Case-sensitive, as the corpus writes its titles."""
    charts = set(all_charts)
    of = defaultdict(set)
    for c in all_charts:
        t = c.rsplit(" ", 1)[0]
        for v in title_variants(t):
            of[v].add(t)
    variants = sorted(of, key=len, reverse=True)
    out = {}
    for src, raw in sorted(by_src.items()):
        text = re.sub(r"\s+", " ", raw)
        occ = _occurrences(text, variants)
        starts = [o[0] for o in occ]
        for i, j, v in occ:
            end = min(len(text), j + PHRASE_CHARS)
            for s in PHRASE_STOPS:
                x = text.find(s, j, end)
                if x >= 0:
                    end = x
            for m in range(bisect.bisect_left(starts, j), len(occ)):
                i2, j2, _ = occ[m]
                if i2 >= end:
                    break
                if re.match(r"\s+" + LEVEL_TOKEN.pattern, text[j2:j2 + 8]):
                    end = i2
                    break
            for tok in LEVEL_TOKEN.findall(text[j:end]):
                for t in of[v]:
                    name = "%s %s" % (t, tok)
                    if name in charts and name not in out:
                        out[name] = (src, text[i:end][:160])
    return out


def build_partitions(meta):
    """The v1 partitions (frozen at 9f8baf6; superseded by build_partitions_v2, kept so v1 can be
    re-derived: its scan reads the tracked text at SEEN_REV, which is what v1 read)."""
    off = official_exact(meta)
    mis = misfits(meta)
    text, names, used, skipped, _ = seen_corpus(list(meta.smap))
    charts = {}
    excluded = meta.quarantine | meta.revisit
    # held-out candidates
    cand = {}
    for (vid, name), o in off.items():
        if o["pack"] == "PHOENIX 2" and o["exact"]:
            cand.setdefault(name, dict(stratum="p2-official", vids=set()))["vids"].add(vid)
    for name, m in mis.items():
        cand.setdefault(name, dict(stratum="misfit36", vids=set()))["vids"].add(m["vid"])
        cand[name]["stratum"] = "misfit36" if cand[name]["stratum"] == "misfit36" else "both"
    seen = {}
    for name, c in cand.items():
        why = []
        if name in text:
            why.append("named")
        for v in sorted(c["vids"]):
            if v in text or v in names:
                why.append("video %s named" % v)
        if why:
            seen[name] = why
    # group the rest by song family and video, then split into halves stratum by stratum
    rest = sorted(n for n in cand if n not in seen and n not in excluded)
    parent = {n: n for n in rest}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_key = defaultdict(list)
    for n in rest:
        by_key["f:" + family(n)].append(n)
        for v in cand[n]["vids"]:
            by_key["v:" + v].append(n)
    for members in by_key.values():
        for m in members[1:]:
            parent[find(m)] = find(members[0])
    groups = defaultdict(list)
    for n in rest:
        groups[find(n)].append(n)
    order = sorted(groups.values(), key=lambda g: hashlib.sha256((SALT + "|" + min(g)).encode()).hexdigest())
    fill = defaultdict(lambda: {"validate": 0, "sealed": 0})
    half = {}
    for g in order:
        strat = Counter(cand[n]["stratum"] for n in g).most_common(1)[0][0]
        f = fill[strat]
        h = "validate" if f["validate"] <= f["sealed"] else "sealed"
        f[h] += len(g)
        for n in g:
            half[n] = (h, min(g))
    for name, c in cand.items():
        if name in excluded:
            part = "excluded"
        elif name in seen:
            part = "seen"
        else:
            part = half[name][0]
        charts[name] = dict(partition=part, stratum=c["stratum"], vids=sorted(c["vids"]),
                            group=half.get(name, (None, None))[1], seen=seen.get(name))
    scorable = {}
    for name, c in charts.items():
        if c["stratum"] == "p2-official":
            scorable[name] = True
        else:
            g = meta.grade.get(name)
            scorable[name] = bool(g and g.get("exact"))
        c["scorable"] = scorable[name]
    counts = Counter((c["partition"], c["stratum"]) for c in charts.values())
    return dict(
        what="bucket #4 lane partitions: held-out charts (PHOENIX 2 official pack, count-exact, plus the 36 "
             "certified misfits); held-out charts named in docs/tools/research moved to 'seen' (tune-only); "
             "the rest grouped by song family and video and split validate/sealed per stratum; quarantined "
             "and owner-revisit charts excluded. Every chart not listed here is 'tune'.",
        date=DATE, salt=SALT,
        rules=dict(heldout_p2="official upload, tail pack 'PHOENIX 2', file converts to the map's count",
                   misfit36="extract-loop-2026-09-23 chart whose cached .inset fit pitch is outside 74-77",
                   seen="chart name, or one of its videos, appears in docs/*.md, tools/*.py, the root *.md, "
                        "work/loop-buckets-2026-09-26.txt, or a research script/text/<=20KB json or file name",
                   scorable="p2-official: count-exact by construction; misfit36: exact in sources/corpus-grade.json",
                   split="union of song family and video; groups ordered by sha256(salt|min member); each goes "
                         "to the half with fewer charts of its stratum"),
        counts={"%s/%s" % k: v for k, v in sorted(counts.items())},
        n_misfit36=len(mis), charts=charts,
        seen_sources=dict(research_files_read=sorted(used),
                          research_listings_skipped=sorted("%s (%d charts)" % s for s in skipped)),
        official=[dict(vid=v, chart=n, **{k: o[k] for k in ("pack", "judged", "implied", "exact", "stored_side",
                                                               "n_charts")}) for (v, n), o in sorted(off.items())],
        misfit36=mis)


def partition_of(parts, name):
    c = parts["charts"].get(name)
    return c["partition"] if c else "tune"


# ---- v2 (2026-09-27, verification round 1). v1's scan matched only the exact string 'Title Level'
# and never carried 'seen' across a shared video, so a sealed chart named in docs as "Legendary
# Dominion S20 and S16" stayed sealed, and a census row carrying it with its seen sibling stayed
# sealed too. v2 re-reads the same text (SEEN_REV, the loop proposal, the same research files) and
# moves held-out charts to 'seen' - never the other way, never reshuffling the halves:
#   (a) a chart named in one phrase by its title and its level token (phrase_named);
#   (b) every held-out chart on a video that carries a chart named in the scan (any corpus chart,
#       held out or not: a named chart's video is a video someone looked at) or whose id is named.
# A census row takes the strictest of its charts' partitions, and 'seen' now outranks both halves.

def video_charts(meta, census, parts):
    """{vid: charts} from every source the census and the partitions know: certified charts, the
    corpus video map, the census rows, the held-out candidates' videos."""
    v2c = defaultdict(set)
    for r in census["rows"]:
        v2c[r["vid"]].update(r["charts"])
    for vid, e in meta.cert.items():
        v2c[vid].update(e.get("charts") or {})
    for vid, e in meta.vmap.items():
        v2c[vid].update(c["chart"] for c in e.get("charts", []))
    for n, c in parts["charts"].items():
        for v in c["vids"]:
            v2c[v].add(n)
    return v2c


def heldout_families(parts):
    return {family(n) for n, c in parts["charts"].items() if c["partition"] in ("validate", "sealed")}


def split_overlap(parts, census, sample):
    """What the validate/sealed grouping does not cover: song families shared between the tune side
    (tune and seen) and the held-out halves, and the band-sample videos carrying a held-out family
    (the frozen bands and the receptor library were computed from them)."""
    held = heldout_families(parts)
    seen_f = {family(n) for n, c in parts["charts"].items() if c["partition"] == "seen"}
    tune_charts = {c for r in census["rows"] for c in r["charts"] if partition_of(parts, c) == "tune"}
    tune_shared = sorted(c for c in tune_charts if family(c) in held)
    want = {(t, v) for t, vs in sample["templates"].items() for v in vs}
    band_vids = defaultdict(set)
    for r in census["rows"]:
        if (r["template"], r["vid"]) in want:
            for c in r["charts"]:
                if family(c) in held:
                    band_vids[r["vid"]].add(family(c))
    return dict(families_seen_and_heldout=sorted(seen_f & held),
                tune_census_charts_sharing_a_heldout_family=len(tune_shared),
                tune_families_shared=len({family(c) for c in tune_shared}),
                band_sample_videos_carrying_a_heldout_family={v: sorted(f) for v, f in sorted(band_vids.items())})


def build_partitions_v2(meta, v1, census_v1, sample):
    allc = list(meta.smap)
    research = research_files(allc)
    text, names, used, skipped, by_src = seen_corpus(allc, research=research)
    phrase = phrase_named(by_src, allc)
    v1_seen = {n for n, c in v1["charts"].items() if c["partition"] == "seen"}
    named = set(phrase) | v1_seen
    v2c = video_charts(meta, census_v1, v1)
    c2v = defaultdict(set)
    for v, cs in v2c.items():
        for c in cs:
            c2v[c].add(v)
    seen_vids = {v: "video id named" for v in v2c if v in text or v in names}
    for c in sorted(named):
        for v in sorted(c2v.get(c, ())):
            seen_vids.setdefault(v, "carries %s, named" % c)
    charts, moved = {}, []
    for n, c in sorted(v1["charts"].items()):
        c = dict(c)
        if c["partition"] in ("validate", "sealed"):
            why = []
            if n in phrase:
                why.append("named in a phrase: %s: %s" % phrase[n])
            why += ["video %s: %s" % (v, seen_vids[v]) for v in sorted(c2v.get(n, ())) if v in seen_vids]
            if why:
                c.update(partition_v1=c["partition"], partition="seen", seen=why)
                moved.append(n)
        charts[n] = c
    lost = [n for n in v1_seen if charts[n]["partition"] != "seen"]
    if lost:
        raise SystemExit("v2 would move a v1-seen chart back into a held-out half: %s" % lost)
    parts = dict(charts=charts)
    held = {n for n, c in charts.items() if c["partition"] in ("validate", "sealed")}
    unread = []
    for r in research:
        if r["read"] or r["why"] == "binary":
            continue
        h = sorted(c for c in r["named"] if c in held)
        if h:
            unread.append(dict(file=r["rel"].replace("\\", "/"), why=r["why"], charts_named=len(r["named"]),
                               bytes=r["size"], heldout=h))
    smallest = {}
    for u in unread:
        for c in u["heldout"]:
            smallest[c] = min(smallest.get(c, 10 ** 9), u["charts_named"])
    counts = Counter((c["partition"], c["stratum"]) for c in charts.values())
    scorable = Counter((c["partition"], c["stratum"]) for c in charts.values() if c["scorable"])
    return dict(
        what="bucket #4 lane partitions, v2: v1 with its 'seen' scan corrected before any F1 was scored. "
             "Held-out charts named by title and level token in one phrase, and held-out charts on a video that "
             "carries a named chart, move to 'seen'; nothing moves the other way and the halves are not reshuffled.",
        date=DATE, version=2, salt=SALT,
        supersedes=dict(path=os.path.relpath(PARTITIONS_V1, ROOT).replace("\\", "/"), sha256=v1["sha256"]),
        rules=dict(v1["rules"], seen_v2=(
            "v1's rule, plus: a held-out chart whose title is followed within one phrase by its level token (the "
            "phrase starts at the title, runs at most %d characters, ends at '. ' or '; ' or where another title "
            "followed by a level token starts; the title as the corpus writes it, or without its FULL SONG / "
            "SHORT CUT / REMIX marker or backslash escapes; case-sensitive), plus every held-out chart on a video "
            "that carries a chart named in the scan (any corpus chart) or whose id is named. The scan reads the "
            "tracked docs/*.md, tools/*.py and root *.md at %s (the v1 freeze commit, which is what v1 read), the "
            "loop proposal, and the same research files as v1." % (PHRASE_CHARS, SEEN_REV)),
                   research_scan=(
            "a research file is read when it is a %s file of at most %d bytes naming at most %d corpus charts "
            "(the exact string 'Title Level'); every other file is not read: a listing naming more is a script's "
            "output over a population. File names count for video ids." % ("/".join(RESEARCH_EXTS),
                                                                             RESEARCH_JSON_MAX, RESEARCH_LIST_MAX)),
                   census_row="a row takes the strictest of its charts' partitions: excluded > seen > sealed > "
                              "validate > tune (v1 ranked the halves above seen)"),
        counts={"%s/%s" % k: v for k, v in sorted(counts.items())},
        scorable_counts={"%s/%s" % k: v for k, v in sorted(scorable.items())},
        scorable_denominators={h: sum(1 for c in charts.values() if c["partition"] == h and c["scorable"])
                               for h in ("validate", "sealed")},
        moved_to_seen=sorted(moved),
        n_misfit36=v1["n_misfit36"], charts=charts,
        seen_sources=dict(scan_rev=SEEN_REV, research_files_read=sorted(used),
                          research_listings_skipped=sorted("%s (%d charts)" % s for s in skipped),
                          heldout_in_unread_research=unread,
                          heldout_in_unread_research_summary=dict(
                              charts=len(smallest),
                              smallest_file_names_at_most_10=sum(1 for v in smallest.values() if v <= 10),
                              smallest_file_names_11_to_30=sum(1 for v in smallest.values() if 10 < v <= 30),
                              smallest_file_names_over_30=sum(1 for v in smallest.values() if v > 30))),
        split_overlap=split_overlap(dict(charts=charts), census_v1, sample),
        official=v1["official"], misfit36=v1["misfit36"])


RANK_V2 = {"excluded": 6, "seen": 5, "sealed": 4, "validate": 3, "tune": 1}


def relabel_census(census_v1, parts, sample):
    """Census v2: v1's rows and BEFORE fits unchanged (nothing is recomputed or re-read), each row's
    partition the strictest of its charts' under the v2 partitions."""
    rows, changed = [], Counter()
    for r in census_v1["rows"]:
        r = dict(r)
        ps = [partition_of(parts, c) for c in r["charts"]] or ["tune"]
        p = max(ps, key=lambda x: RANK_V2[x])
        if any(q == "seen" for q in ps) and any(q in ("validate", "sealed") for q in ps):
            raise SystemExit("row %s carries a seen and a held-out chart under v2" % row_key(r))
        if p != r["partition"]:
            changed[(r["partition"], p)] += 1
            r["partition_v1"] = r["partition"]
            r["partition"] = p
        rows.append(r)
    want = {(t, v) for t, vs in sample["templates"].items() for v in vs}
    bad = [row_key(r) for r in rows if (r["template"], r["vid"]) in want and r["partition"] not in ("tune", "seen")
           and r.get("partition_v1") in ("tune", "seen")]
    if bad:
        raise SystemExit("a band-sample row left the tune side under v2: %s" % bad[:5])
    out = {k: v for k, v in census_v1.items() if k not in ("rows", "counts", "sha256")}
    counts = Counter((r["template"], r["partition"]) for r in rows)
    out.update(version=2, partitions_sha256=parts["sha256"],
               derived_from=dict(path=os.path.relpath(CENSUS_V1, ROOT).replace("\\", "/"), sha256=census_v1["sha256"]),
               relabel="v1's rows, BEFORE fits and templates unchanged; each row's partition re-taken as the strictest "
                       "of its charts' under partitions v2, ranking excluded > seen > sealed > validate > tune",
               relabelled={"%s->%s" % k: v for k, v in sorted(changed.items())},
               counts={"%s/%s" % k: v for k, v in sorted(counts.items())}, rows=rows)
    return out


# ---------------------------------------------------------------- census

RANK = {"sealed": 5, "validate": 4, "excluded": 3, "seen": 2, "tune": 1}


def build_census(meta, parts):
    rows = {}

    def add(vid, band, ncols, side, chart, source):
        k = "%s.%s.%d.%s" % (vid, band, ncols, side)
        r = rows.setdefault(k, dict(vid=vid, band=band, ncols=ncols, side=side, charts=[], sources=[]))
        if chart and chart not in r["charts"]:
            r["charts"].append(chart)
        if source not in r["sources"]:
            r["sources"].append(source)
    for vid, e in meta.cert.items():
        if vid not in meta.have:
            continue
        for name, ce in (e.get("charts") or {}).items():
            if ce.get("verdict") == "CERTIFIED":
                band, ncols, side = meta.certified_spec(vid, name)
                add(vid, band, ncols, side, name, "certified")
    for vid, e in meta.vmap.items():
        if "Official" not in (e.get("channel") or "") or vid not in meta.have:
            continue
        for c in e["charts"]:
            n = ncols_of(c["chart"])
            # the pad is not known from the map (never taken from stored sides): a singles upload shows
            # two fields, so both are fitted; a doubles field is one field, whichever side asks
            for side in (("1p",) if n == 10 else ("1p", "2p")):
                add(vid, "C", n, side, c["chart"], "official")
    for f in os.listdir(LB.FIELD_DIR):
        if f.endswith(".inset.field.json"):
            vid, band, ncols, side = f[:-len(".inset.field.json")].rsplit(".", 3)
            if vid in meta.have:
                add(vid, band, int(ncols), side, None, "inset-cache")
    out = []
    for k in sorted(rows):
        r = rows[k]
        r["charts"].sort()
        grp = meta.group_of(r["vid"])
        r["template"] = template_of(grp, r["band"], r["ncols"])
        ps = [partition_of(parts, c) for c in r["charts"]] or ["tune"]
        r["partition"] = max(ps, key=lambda p: RANK[p])
        t = LB.inset_text(r["vid"], r["band"], r["ncols"], r["side"])
        if t is not None:
            f = json.loads(t)
            r["before"] = dict(rule=BEFORE_RULE, pitch=f["pitch"], xs=f["xs"], y0=f["y0"], y1=f["y1"],
                               symmetry=f.get("symmetry"), fields=f.get("fields"), axis=f.get("axis"),
                               sha=hashlib.sha256(t.encode("utf-8")).hexdigest()[:16])
        else:
            r["before"] = dict(rule=BEFORE_RULE, pitch=None, note="no cached fit (never asked, or the fit raised)")
        if r["vid"] in meta.corrupt:
            r["footage_corrupt"] = meta.corrupt[r["vid"]].get("problem")
        out.append(r)
    counts = Counter((r["template"], r["partition"]) for r in out)
    return dict(what="bucket #4 BEFORE census: every lane fit the corpus asks for, with its template (channel group:"
                     "band:columns, from metadata), partition (the strictest of its charts') and the fit on disk "
                     "stamped with the rule that made it",
                date=DATE, before_rule=BEFORE_RULE, partitions_sha256=parts["sha256"],
                medband=dict(params=LB.params(), digest=cachekey.digest(LB.params())),
                n_rows=len(out), n_with_fit=sum(1 for r in out if r["before"]["pitch"] is not None),
                counts={"%s/%s" % k: v for k, v in sorted(counts.items())}, rows=out)


# ---------------------------------------------------------------- recompute

WORKERS = 3                    # outside the supervisor: this process plus three at most


def _pool_init():
    import supervise
    supervise.lower_own_priority()
    cv2.setNumThreads(1)


def by_video(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["vid"]].append(r)
    return sorted(out.items())


def pmap(fn, items, workers=WORKERS):
    if workers <= 1:
        return [fn(x) for x in items]
    from multiprocessing import Pool
    with Pool(workers, initializer=_pool_init) as p:
        return list(p.imap(fn, items, chunksize=2))


def row_key(r):
    return "%s.%s.%d.%s" % (r["vid"], r["band"], r["ncols"], r["side"])


def recompute_row(r, mb):
    """The BEFORE fit from the cache: (fit or None, error or None, identical-to-cache or None)."""
    try:
        fit = LB.fit_from_cache(mb, r["band"], r["ncols"], r["side"])
        err = None
    except Exception as ex:
        fit, err = None, "%s: %s" % (type(ex).__name__, ex)
    t = LB.inset_text(r["vid"], r["band"], r["ncols"], r["side"])
    same = None if t is None else (fit is not None and LB.fit_bytes(fit) == t)
    return fit, err, same


def _w_recompute(item):
    vid, rows = item
    mb = LB.load(vid)
    if mb is None:
        return [(row_key(r), "not-cached", None) for r in rows]
    out = []
    for r in rows:
        fit, err, same = recompute_row(r, mb)
        out.append((row_key(r), "raised" if err else ("same" if same else "differs" if same is False else "no-cache-file"),
                    err))
    return out


def cmd_recompute(a):
    census = read_frozen(CENSUS)
    res = [x for xs in pmap(_w_recompute, by_video(census["rows"]), a.workers) for x in xs]
    c = Counter(v for _, v, _ in res)
    n = sum(v for k, v in c.items() if k != "not-cached")
    print("recomputed %d fits from the cache (%d rows not cached yet): %d cached .inset fits byte-identical, "
          "%d differ, %d raised, %d with no .inset file to compare" % (
              n, c["not-cached"], c["same"], c["differs"], c["raised"], c["no-cache-file"]))
    for k, v, _ in res:
        if v == "differs":
            print("  DIFFERS", k)
    if n == 0:
        print("FAIL: zero fits recomputed - a census run that recomputes nothing proves nothing")
        return 1
    return 1 if c["differs"] else 0


# ---------------------------------------------------------------- bands and the receptor library
#
# A band is the pitch cluster of a template's tune fits that pass the independent invariant for
# their layout: twin agreement for doubles, receptor-library NCC for singles. The library is the
# mean receptor crop per lane of the channel group's tune doubles fits that pass twin agreement.
# Measured on the tune fits cached on 2026-09-27 before this was fixed: twin 0.96-0.98 on fits at
# 75.2-75.5 against 0.31-0.59 on fits at 51-72; library NCC 0.87-0.99 on singles fits at 74.4-75.8
# against 0.35-0.61 at 51-58. Pad twin (one field against the other) does NOT separate: both
# fields of an official singles upload misfit the same way, and agree with each other at 0.97-0.999.
#
# Pre-registered before any band was computed:
BAND_INVARIANT_MIN = 0.80      # twin (doubles) / library NCC (singles) a tune fit must reach
BAND_MIN_FITS = 8              # fewer passing sample fits: the channel group's pooled band for the column count
BAND_PAD = 0.5                 # px added each side of the passing fits' 1st..99th percentile
LIB_MIN_FITS = 8               # a channel group needs this many twin-passing doubles fits for a library
SAMPLE_SALT = "lanes-1/band-sample"
SAMPLE_PER_TEMPLATE = 40       # non-official templates: the first 40 tune videos in hash order
LIBRARY = os.path.join(SRC, "receptor-library-%s.npz" % DATE)
SAMPLE = os.path.join(SRC, "band-sample-%s.json" % DATE)


def build_sample(census, codecs):
    """The videos the bands are computed from, chosen before any band is: per template, its tune and
    seen videos that are not AV1 (codec is metadata); all of them for an OFFICIAL template (their
    fits are mostly misfits, so a band needs the lot), the first SAMPLE_PER_TEMPLATE in
    sha256(salt|vid) order for any other."""
    by = defaultdict(set)
    for r in census["rows"]:
        if r["partition"] in ("tune", "seen") and codecs.get(r["vid"], {}).get("fourcc") != "AV01":
            by[r["template"]].add(r["vid"])
    out = {}
    for t, vids in sorted(by.items()):
        order = sorted(vids, key=lambda v: hashlib.sha256((SAMPLE_SALT + "|" + v).encode()).hexdigest())
        out[t] = order if t.startswith("OFFICIAL:") else order[:SAMPLE_PER_TEMPLATE]
    return out


def _w_sample(item):
    """Phase 1 of the bands: each sample row's BEFORE fit, its twin, and the canonical crops of a
    doubles fit that passes twin (the library's sources)."""
    vid, rows = item
    mb = LB.load(vid)
    if mb is None:
        return [dict(key=row_key(r), template=r["template"], cached=False) for r in rows]
    out = []
    for r in rows:
        fit, err, same = recompute_row(r, mb)
        d = dict(key=row_key(r), template=r["template"], cached=True, ncols=r["ncols"],
                 pitch=fit["pitch"] if fit else None, error=err)
        if fit is not None and r["ncols"] == 10:
            d["twin"] = LB.twin(mb["field"], fit["xs"], fit["pitch"])
            if d["twin"] is not None and d["twin"] >= BAND_INVARIANT_MIN:
                d["canon"] = [c.astype(np.float32) for c in (LB.canon(mb["field"], fit["xs"], fit["pitch"]) or [])]
        out.append(d)
    return out


def _w_ncc(item):
    vid, rows, libs = item
    mb = LB.load(vid)
    out = {}
    for r in rows:
        fit, err, same = recompute_row(r, mb)
        lib = libs.get(r["template"].split(":")[0])
        out[row_key(r)] = None if fit is None or lib is None else LB.ncc(mb["field"], fit["xs"], fit["pitch"], lib)
    return out


def load_library():
    z = A.load_npz(LIBRARY, quiet=True)
    if z is None:
        return {}
    return {k: [z[k][i] for i in range(5)] for k in z}


def cmd_sample(a):
    census = read_frozen(CENSUS_V1)          # the sample was frozen from census v1
    codecs = load_json(os.path.join(ROOT, "work", "research-2026-09-26", "b2", "codecs.json"))
    s = build_sample(census, codecs)
    vids = sorted({v for vs in s.values() for v in vs})
    missing = [v for v in vids if not os.path.exists(LB.medband_path(v))]
    for t, vs in s.items():
        print("  %-18s %4d videos" % (t, len(vs)))
    print("band sample: %d videos, %d not cached yet" % (len(vids), len(missing)))
    if a.write:
        sha = write_frozen(SAMPLE, dict(what="bucket #4 band sample: the videos each template's pitch band is computed "
                                              "from, chosen from metadata before any band was computed",
                                         date=DATE, census_sha256=census["sha256"], salt=SAMPLE_SALT,
                                         per_template=SAMPLE_PER_TEMPLATE,
                                         codecs="work/research-2026-09-26/b2/codecs.json", templates=s))
        print("froze %s (sha256 %s)" % (os.path.relpath(SAMPLE, ROOT), sha[:16]))
    if a.missing:
        A.write_text(a.missing, "".join(v + "\n" for v in missing), encoding="utf-8", newline="\n")
    return 0


def compute_bands(census, sample, workers, exclude=frozenset(), verbose=True):
    """The bands and the library from the band sample, less any video in `exclude` (a sensitivity
    check: with nothing excluded this is exactly what cmd_bands froze)."""
    want = {(t, v) for t, vs in sample["templates"].items() for v in vs if v not in exclude}
    rows = [r for r in census["rows"] if (r["template"], r["vid"]) in want and r["partition"] in ("tune", "seen")]
    res = [x for xs in pmap(_w_sample, by_video(rows), workers) for x in xs]
    uncached = sum(1 for x in res if not x["cached"])
    libs, lib_n = {}, {}
    for g in sorted({x["template"].split(":")[0] for x in res}):
        src = [x["canon"] for x in res if x.get("canon") and x["template"].split(":")[0] == g]
        lib_n[g] = len(src)
        if len(src) >= LIB_MIN_FITS:
            lanes = []
            for k in range(5):
                m = np.mean([c[k] for c in src] + [c[k + 5] for c in src], axis=0)
                lanes.append(((m - m.mean()) / (m.std() + 1e-6)).astype(np.float32))
            libs[g] = lanes
    singles = [r for r in rows if r["ncols"] == 5]
    nccs = {}
    for d in pmap(_w_ncc, [(v, rs, libs) for v, rs in by_video(singles)], workers):
        nccs.update(d)
    for x in res:
        if x.get("ncols") == 5:
            x["ncc"] = nccs.get(x["key"])
    vals = defaultdict(list)
    for x in res:
        if x["cached"] and x["pitch"] is not None:
            inv = x.get("twin") if x["ncols"] == 10 else x.get("ncc")
            vals[x["template"]].append((x["pitch"], inv))
    bands, pooled = {}, defaultdict(list)
    for t, xs in vals.items():
        g, _, n = t.split(":")
        pooled["%s:*:%s" % (g, n)] += [p for p, inv in xs if inv is not None and inv >= BAND_INVARIANT_MIN]
    for t in sorted(sample["templates"]):
        xs = vals.get(t, [])
        ok = [p for p, inv in xs if inv is not None and inv >= BAND_INVARIANT_MIN]
        b = dict(n_sample_videos=len([v for v in sample["templates"][t] if v not in exclude]), n_fits=len(xs),
                 n_passing=len(ok), invariant="twin" if t.endswith(":10") else "library-ncc",
                 pitch_pct_all=[round(float(v), 1) for v in np.percentile([p for p, _ in xs], [5, 25, 50, 75, 95])]
                 if xs else None)
        g, _, n = t.split(":")
        src = ok if len(ok) >= BAND_MIN_FITS else pooled["%s:*:%s" % (g, n)]
        if len(src) >= BAND_MIN_FITS:
            lo, hi = np.percentile(src, [1, 99])
            b.update(lo=round(float(lo) - BAND_PAD, 2), hi=round(float(hi) + BAND_PAD, 2),
                     centre=round(float(np.median(src)), 2),
                     source="own" if src is ok else "pooled %s:*:%s (%d fits)" % (g, n, len(src)))
        else:
            b.update(source="none: fewer than %d passing sample fits, own or pooled" % BAND_MIN_FITS)
        bands[t] = b
        if verbose:
            print("%-18s videos %4d fits %4d passing %4d  band %-20s all-pitch pct5/25/50/75/95 %s  (%s)" % (
                t, b["n_sample_videos"], b["n_fits"], b["n_passing"],
                "%.2f-%.2f c%.2f" % (b["lo"], b["hi"], b["centre"]) if "lo" in b else "-", b["pitch_pct_all"],
                b["source"]))
    if verbose:
        print("library: %s" % ", ".join("%s %d fits%s" % (g, n, "" if g in libs else " (none)")
                                        for g, n in sorted(lib_n.items())))
        print("sample rows %d, not cached yet %d" % (len(res), uncached))
    return dict(bands=bands, libs=libs, lib_n=lib_n, uncached=uncached, rows=len(res))


def libs_sha(libs):
    """library_sha() over in-memory lanes, as the npz would store them."""
    h = hashlib.sha256()
    for k in sorted(libs):
        z = np.stack(libs[k])
        h.update(k.encode() + b"\0" + str(z.shape).encode() + b"\0" + np.ascontiguousarray(z).tobytes())
    return h.hexdigest()


def cmd_sensitivity(a):
    """Finding 4 of verification round 1: the frozen bands and library recomputed without the
    band-sample videos that carry a held-out song family. Never writes a band. First recomputes
    with nothing excluded, which must give the frozen bands and library exactly. The bands were
    computed over census v1, so the recompute reads census v1; the exclusion is taken under the
    current partitions (v2)."""
    census = read_frozen(CENSUS_V1)
    sample = read_frozen(SAMPLE)
    bf = read_frozen(BANDS)
    parts = read_frozen(PARTITIONS)
    ex = set(split_overlap(parts, read_frozen(CENSUS), sample)["band_sample_videos_carrying_a_heldout_family"])
    if a.also_v1:
        ex |= set(split_overlap(read_frozen(PARTITIONS_V1), read_frozen(CENSUS_V1), sample)
                  ["band_sample_videos_carrying_a_heldout_family"])
    print("excluding %d band-sample videos: %s" % (len(ex), sorted(ex)))
    base = compute_bands(census, sample, a.workers, verbose=False)
    same = {t: all(base["bands"][t].get(k) == bf["bands"][t].get(k) for k in ("lo", "hi", "centre", "n_passing"))
            for t in bf["bands"]}
    lib_same = libs_sha(base["libs"]) == bf["library"]["sha256"]
    print("recompute with nothing excluded: bands %s, library %s" % (
        "identical" if all(same.values()) else "DIFFER %s" % [t for t, s in same.items() if not s],
        "identical" if lib_same else "DIFFERS"))
    if not all(same.values()) or not lib_same or base["uncached"]:
        print("FAIL: the baseline does not reproduce the frozen bands - the comparison would mean nothing")
        return 1
    got = compute_bands(census, sample, a.workers, exclude=ex, verbose=False)
    moved = []
    print("%-18s %-26s %-26s %s" % ("template", "frozen lo-hi (centre)", "without them", "passing fits"))
    for t in sorted(bf["bands"]):
        f, g = bf["bands"][t], got["bands"][t]
        fs = "%.2f-%.2f (%.2f)" % (f["lo"], f["hi"], f["centre"]) if "lo" in f else "-"
        gs = "%.2f-%.2f (%.2f)" % (g["lo"], g["hi"], g["centre"]) if "lo" in g else "-"
        d = [k for k in ("lo", "hi", "centre") if f.get(k) != g.get(k)]
        if d:
            moved.append((t, {k: (f.get(k), g.get(k)) for k in d}))
        print("%-18s %-26s %-26s %d -> %d%s" % (t, fs, gs, f["n_passing"], g["n_passing"],
                                                "  MOVED " + ",".join(d) if d else ""))
    print("library sources: %s -> %s" % (dict(bf["library"]["sources"]), dict(got["lib_n"])))
    out = dict(what="sensitivity of the frozen pitch bands and receptor library to the band-sample videos that "
                    "carry a held-out song family (verification round 1, finding 4); nothing refrozen",
               date=time.strftime("%Y-%m-%dT%H:%M:%S"), bands_sha256=bf["sha256"], partitions_sha256=parts["sha256"],
               excluded=sorted(ex), baseline_reproduces_frozen=True,
               moved={t: {k: list(v) for k, v in d.items()} for t, d in moved},
               bands_without=got["bands"], library_sources_without=got["lib_n"],
               library_sha256_without=libs_sha(got["libs"]))
    if a.out:
        A.write_json(a.out, out, encoding="utf-8", indent=1)
        print("wrote", a.out)
    print("band edges or centres that move: %d of %d templates" % (len(moved), len(bf["bands"])))
    return 0


def cmd_bands(a):
    """Compute (and with --write, freeze once) the bands and the library from the band sample. They
    were frozen from census v1, whose tune-side rows census v2 leaves unchanged."""
    census = read_frozen(CENSUS_V1)
    sample = read_frozen(SAMPLE)
    got = compute_bands(census, sample, a.workers)
    bands, libs, lib_n = got["bands"], got["libs"], got["lib_n"]
    if a.write:
        if got["uncached"]:
            print("REFUSED: %d sample rows are not cached yet - the bands are frozen from the whole sample or not "
                  "at all" % got["uncached"])
            return 2
        if os.path.exists(BANDS) or os.path.exists(LIBRARY):
            print("REFUSED: the bands and the library are frozen already")
            return 2
        os.makedirs(SRC, exist_ok=True)
        A.write_npz(LIBRARY, compressed=True, **{g: np.stack(l) for g, l in libs.items()})
        sha = write_frozen(BANDS, dict(
            what="bucket #4 per-template pitch bands from the band sample's tune fits, each recomputed from the "
                 "median-band cache by the BEFORE rule",
            date=DATE, census_sha256=census["sha256"], sample_sha256=sample["sha256"],
            invariant_min=BAND_INVARIANT_MIN, min_fits=BAND_MIN_FITS, pad_px=BAND_PAD, lib_min_fits=LIB_MIN_FITS,
            library=dict(path=os.path.relpath(LIBRARY, ROOT).replace("\\", "/"), sha256=library_sha(),
                         sources={g: n for g, n in lib_n.items()}, width=LB.LIB_W),
            method="a template's band is the 1st..99th percentile of the pitches of its sample fits whose independent "
                   "invariant (twin for doubles; NCC against the channel group's receptor library for singles) "
                   "reaches %.2f, widened by %.1fpx each side; fewer than %d such fits: the channel group's pooled "
                   "passing fits for that column count" % (BAND_INVARIANT_MIN, BAND_PAD, BAND_MIN_FITS),
            bands=bands))
        print("froze %s (sha256 %s) and %s" % (os.path.relpath(BANDS, ROOT), sha[:16], os.path.relpath(LIBRARY, ROOT)))
    return 0


def library_sha():
    """sha256 over the library's arrays (name, shape, bytes) - not over the npz file, whose zip
    headers carry a timestamp."""
    z = A.load_npz(LIBRARY, quiet=True)
    if z is None:
        return None
    h = hashlib.sha256()
    for k in sorted(z):
        h.update(k.encode() + b"\0" + str(z[k].shape).encode() + b"\0" + np.ascontiguousarray(z[k]).tobytes())
    return h.hexdigest()


# ---------------------------------------------------------------- rule 1

RULE1 = "r1-oob-sym-respan"
R1_SYM = 0.8                   # the fit's own mirror symmetry for the rule to apply (receptors' guard)
R1_THRESHOLDS = (0.35, 0.25, 0.15)   # loose-peak floors tried in turn, as shares of the profile's top
R1_INVARIANT_MIN = 0.80        # twin (doubles) / library NCC (singles) a re-fit must reach
R1_INVARIANT_GAIN = 0.10       # and by how much it must beat the BEFORE fit's


def _profile(med, w, band):
    prof = cv2.GaussianBlur(med.astype(np.float32), (0, 0), 3).mean(axis=0)
    prof = cv2.GaussianBlur(prof.reshape(1, -1), (0, 0), 3).ravel()
    prof = prof - np.percentile(prof, 30)
    lo_x, hi_x = (0, w // 2) if band == "L" else (w // 2, w) if band == "R" else (0, w)
    return prof, lo_x, hi_x, prof[lo_x:hi_x].max()


def _axis(med, w, band, side):
    """For a fit that raised: the field's mirror axis and symmetry as receptors._fit_field finds
    them before its pitch check (the same peaks, groups and span)."""
    prof, lo_x, hi_x, top = _profile(med, w, band)
    peaks = [x for x in range(max(8, lo_x), min(w - 8, hi_x))
             if prof[x] == prof[x - 8:x + 9].max() and prof[x] > 0.6 * top]
    if not peaks:
        return None, None
    groups = [[peaks[0]]]
    gaps = np.diff(peaks)
    wide = 2.5 * float(np.median(gaps)) if len(gaps) else 1e9
    for x, g in zip(peaks[1:], gaps):
        (groups[-1] if g <= wide else groups.append([]) or groups[-1]).append(x)
    groups = [g for g in groups if len(g) >= 3]
    if len(groups) >= 2:
        groups.sort(key=lambda g: g[0])
        pick = groups[0] if side == "1p" else groups[-1]
    else:
        pick = peaks
    lo, hi = min(pick), max(pick)
    return R._mirror_axis(med, (lo + hi) / 2.0, (hi - lo) / 2.0, w)


def respan(med, w, band, ncols, axis, pband):
    """Rule 1's search: pairs of profile peaks standing symmetric about the field's mirror axis whose
    span puts the lane pitch inside the template's band, from the strongest floor that yields one.
    The pair whose pitch is nearest the band's centre wins; a tie goes to the stronger pair. Failing
    any pair, a single peak mirrored about the axis. Returns (lo, hi, pitch, floor, mode) or None. It
    never looks at twin agreement, the library or any invariant."""
    prof, lo_x, hi_x, top = _profile(med, w, band)
    lo_b, hi_b, centre = pband
    for th in R1_THRESHOLDS:
        peaks = [x for x in range(max(8, lo_x), min(w - 8, hi_x))
                 if prof[x] == prof[x - 8:x + 9].max() and prof[x] > th * top]
        cands = []
        for i, a in enumerate(peaks):
            for b in peaks[i + 1:]:
                if not a < axis < b or abs((a + b) / 2.0 - axis) > 2.0:
                    continue
                p = (b - a) / (ncols - 2 * R.INSET)
                if lo_b <= p <= hi_b:
                    cands.append((abs(p - centre), -min(prof[a], prof[b]), a, b, p))
        if cands:
            _, _, a, b, p = min(cands)
            return a, b, p, th, "pair"
    # One outer ridge can fail to stand as a peak of its own (on a split screen it runs into the
    # frame's art): the axis is known to half a pixel, so a single peak and its mirror image about it
    # say the same span. Tried only when no pair reaches the band at any floor.
    for th in R1_THRESHOLDS:
        peaks = [x for x in range(max(8, lo_x), min(w - 8, hi_x))
                 if prof[x] == prof[x - 8:x + 9].max() and prof[x] > th * top]
        cands = []
        for x in peaks:
            half = abs(x - axis)
            a, b = axis - half, axis + half
            if half == 0 or a < max(8, lo_x) or b > min(w - 8, hi_x):
                continue
            p = 2 * half / (ncols - 2 * R.INSET)
            if lo_b <= p <= hi_b:
                cands.append((abs(p - centre), -prof[x], a, b, p))
        if cands:
            _, _, a, b, p = min(cands)
            return a, b, p, th, "mirror"
    return None


def rule1_fit(med, w, band, ncols, side, y0, y1, before, pband):
    """(verdict, fit). In band: the BEFORE fit, untouched. Out of band (or raised) and symmetric: a
    re-searched span, or None when no symmetric pair reaches the band (the band is never widened)."""
    lo_b, hi_b, _ = pband
    if before is not None and lo_b <= before["pitch"] <= hi_b:
        return "in-band", before
    if before is None:
        axis, sym = _axis(med, w, band, side)
        kind = "raise-"
        if axis is None:
            return "raise-no-peaks", None
    else:
        axis, sym, kind = before["axis"], before["symmetry"], ""
    if sym < R1_SYM:
        return kind + "asymmetric", None
    got = respan(med, w, band, ncols, axis, pband)
    if got is None:
        return kind + "no-pair-in-band", None
    a, b, p, th, mode = got
    xs = [int(round(a + (k + 0.5 - R.INSET) * p)) for k in range(ncols)]
    fit = dict(y0=y0, y1=y1, xs=xs, pitch=round(p, 1), band=band, side=side,
               fields=before["fields"] if before else None, axis=axis, symmetry=round(sym, 3), rule=RULE1, floor=th,
               mode=mode)
    return kind + "re-fit", fit


def r1_code():
    """The registered stamp of rule 1: its search, and the acceptance with the invariants it grades by."""
    return cachekey.code_stamp(respan, rule1_fit, _profile, _axis, _w_rule1, invariant,
                               LB.twin, LB.ncc, LB.canon, LB.crops, LB._corr)


def derived_key(fit, rule):
    return cachekey.digest(dict(xs=[int(x) for x in fit["xs"]], y0=int(fit["y0"]), y1=int(fit["y1"]), rule=rule))


def invariant(mb, ncols, template, fit, libs):
    if fit is None:
        return None, None
    if ncols == 10:
        return "twin", LB.twin(mb["field"], fit["xs"], fit["pitch"])
    return "library-ncc", LB.ncc(mb["field"], fit["xs"], fit["pitch"], libs.get(template.split(":")[0]))


def _w_rule1(item):
    vid, rows, bands, libs = item
    mb = LB.load(vid)
    out = []
    for r in rows:
        row = dict(key=row_key(r), partition=r["partition"], template=r["template"], charts=r["charts"])
        if mb is None:
            row["verdict"] = "not-cached"
            out.append(row)
            continue
        before, err, same = recompute_row(r, mb)
        row.update(before_pitch=before["pitch"] if before else None, before_error=err, before_same_as_cache=same,
                   recomputed=True)
        b = bands.get(r["template"]) or {}
        if "lo" not in b:
            row["verdict"] = "no-band"
            out.append(row)
            continue
        verdict, fit = rule1_fit(mb["field"], mb["w"], r["band"], r["ncols"], r["side"], mb["y0"], mb["y1"],
                                 before, (b["lo"], b["hi"], b["centre"]))
        row["verdict"] = verdict
        if verdict == "in-band":
            row["identical"] = LB.fit_bytes(fit) == LB.fit_bytes(before)
            row["invariant"], row["inv_before"] = invariant(mb, r["ncols"], r["template"], before, libs)
        elif verdict.endswith("re-fit"):
            kind, vb = invariant(mb, r["ncols"], r["template"], before, libs)
            kind, va = invariant(mb, r["ncols"], r["template"], fit, libs)
            row.update(after_pitch=fit["pitch"], xs_before=before["xs"] if before else None, xs_after=fit["xs"],
                       floor=fit["floor"], mode=fit["mode"], invariant=kind, inv_before=vb, inv_after=va,
                       derived_key=derived_key(fit, RULE1))
            pre = "rescued-raise:" if verdict.startswith("raise-") else ""
            if va is None:
                row["verdict"] = pre + "ledger:no-invariant"
            elif va >= R1_INVARIANT_MIN and (vb is None or va >= vb + R1_INVARIANT_GAIN):
                row["verdict"] = pre + "accepted"
            else:
                row["verdict"] = pre + "ledger:invariant-not-met"
        elif before is not None:
            row["inv_before"] = invariant(mb, r["ncols"], r["template"], before, libs)[1]
        out.append(row)
    return out


HELDOUT_DIR = os.path.join(WORK, "heldout")      # rule output on held-out rows: never a development input
DEV_PARTITIONS = ("tune", "seen")


def _exceptions(rows):
    """The exceptions ledger: every fit out of band that the rule did not bring in, with why; the band
    is never widened for them."""
    return [dict(key=x["key"], partition=x["partition"], template=x["template"], charts=x["charts"],
                 verdict=x["verdict"], before_pitch=x.get("before_pitch"), before_error=x.get("before_error"),
                 inv_before=x.get("inv_before"), inv_after=x.get("inv_after"), after_pitch=x.get("after_pitch"))
            for x in rows if x["verdict"] not in ("in-band", "accepted", "not-cached")]


def _write_rule_output(out, head, rows):
    summary = defaultdict(dict)
    for (p, v), n in sorted(Counter((x["partition"], x["verdict"]) for x in rows).items()):
        summary[p][v] = n
    os.makedirs(os.path.dirname(out), exist_ok=True)
    A.write_json(out, dict(head, summary={p: dict(v) for p, v in summary.items()}, rows=rows),
                 encoding="utf-8", indent=1)
    exc = _exceptions(rows)
    A.write_text(out[:-len(".json")] + ".exceptions.jsonl",
                 "".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n" for e in exc),
                 encoding="utf-8", newline="\n")
    return summary, exc


def cmd_rule1(a):
    """Rule 1 over the census. By default over the tune side only (tune, seen): that output and its
    exceptions ledger are what a later rule is developed on. Held-out rows run only with
    --heldout-look, which writes under work/lanes/heldout/ and logs the look (counts only, no chart
    named) in the hash-chained looks ledger."""
    census = read_frozen(CENSUS)
    bf = read_frozen(BANDS)
    bands = bf["bands"]
    libs = load_library()
    if library_sha() != bf["library"]["sha256"]:
        print("the receptor library does not match the frozen bands' record of it")
        return 2
    reg = registered(RULE1)
    if reg is None or reg["code"] != r1_code():
        print("rule %s with code %s is not registered in %s - register it (lanefit.py register) before it runs"
              % (RULE1, r1_code(), os.path.relpath(RULES, ROOT)))
        return 2
    want = (a.partitions or ",".join(DEV_PARTITIONS)).split(",")
    held = [p for p in want if p not in DEV_PARTITIONS]
    if held and not a.heldout_look:
        print("REFUSED: %s are held out - pass --heldout-look '<what this look is for>' to run them (it is logged)"
              % ",".join(held))
        return 2
    t0 = time.time()
    rows = [r for r in census["rows"] if r["partition"] in want]
    items = [(v, rs, bands, libs) for v, rs in by_video(rows)]
    rows_out = [x for xs in pmap(_w_rule1, items, a.workers) for x in xs]
    recomputed = sum(1 for x in rows_out if x.get("recomputed"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    head = dict(rule=RULE1, code=r1_code(), census_sha256=census["sha256"], bands_sha256=bf["sha256"],
                recomputed=recomputed, partitions=",".join(want))
    dev = [x for x in rows_out if x["partition"] in DEV_PARTITIONS]
    ho = [x for x in rows_out if x["partition"] not in DEV_PARTITIONS]
    outs = []
    if dev:
        out = a.out or os.path.join(WORK, "rule1-%s.json" % stamp)
        summary, exc = _write_rule_output(out, head, dev)
        outs.append((out, summary, exc))
    if ho:
        out = os.path.join(HELDOUT_DIR, "rule1-%s.heldout.json" % stamp)
        summary, exc = _write_rule_output(out, head, ho)
        outs.append((out, summary, exc))
        for h in sorted({x["partition"] for x in ho}):
            c = Counter(x["verdict"] for x in ho if x["partition"] == h)
            append_chained(LOOKS, dict(date=time.strftime("%Y-%m-%dT%H:%M:%S"), rule=RULE1, half=h, kind="look",
                                       what="rule 1 (%s) on the %s half: %s" % (r1_code(), h, a.heldout_look),
                                       result=", ".join("%s %d" % kv for kv in sorted(c.items()))))
    for out, summary, exc in outs:
        for p in sorted(summary, key=lambda p: -RANK_V2.get(p, 0)):
            print("%-9s %s" % (p, "  ".join("%s %d" % kv for kv in sorted(summary[p].items()))))
        print("wrote", os.path.relpath(out, ROOT), "and its exceptions ledger (%d rows)" % len(exc))
    # An in-band fit is returned as the BEFORE fit object itself, so 'identical' is true by
    # construction and proves nothing; the evidence is that every BEFORE fit with a cached .inset
    # recomputes to its bytes. (When the rule is promoted, in-band identity is checked through the
    # promoted receptors.field() against the .inset bytes.)
    inband = [x for x in rows_out if x["verdict"] == "in-band"]
    print("in band %d (returned as the BEFORE fit itself - identical by construction, not evidence); BEFORE fits "
          "recomputed from the cache: %d equal their cached .inset bytes, %d differ, %d have no cached .inset"
          % (len(inband), sum(1 for x in rows_out if x.get("before_same_as_cache") is True),
             sum(1 for x in rows_out if x.get("before_same_as_cache") is False),
             sum(1 for x in rows_out if x.get("recomputed") and x.get("before_same_as_cache") is None)))
    print("recomputed %d fits in %.1fs" % (recomputed, time.time() - t0))
    if recomputed == 0:
        print("FAIL: zero fits recomputed")
        return 1
    if any(x.get("before_same_as_cache") is False for x in rows_out):
        print("FAIL: a BEFORE fit did not recompute to its cached .inset bytes")
        return 1
    return 0


def cmd_split(a):
    """Take the held-out rows out of a rule output written before --heldout-look existed: relabel its
    rows with the current census's partitions, move the original file (and its exceptions ledger)
    untouched into work/lanes/heldout/, write the held-out rows there, and leave only tune-side rows
    (and a tune-side exceptions ledger) at the original path. Computes nothing."""
    census = read_frozen(CENSUS)
    part = {row_key(r): r["partition"] for r in census["rows"]}
    src = a.path
    if not src.endswith(".json") or not os.path.exists(src):
        print("no rule output at", src)
        return 2
    d = load_json(src)
    rows = d.pop("rows")
    d.pop("summary", None)
    moved = Counter()
    for x in rows:
        p = part[x["key"]]
        if p != x["partition"]:
            moved["%s->%s" % (x["partition"], p)] += 1
            x["partition_at_run"] = x["partition"]
            x["partition"] = p
    base = os.path.basename(src)[:-len(".json")]
    os.makedirs(HELDOUT_DIR, exist_ok=True)
    keep = os.path.join(HELDOUT_DIR, base + ".original.json")
    if os.path.exists(keep):
        print("REFUSED: %s exists - this output was split already" % os.path.relpath(keep, ROOT))
        return 2
    os.replace(src, keep)
    exc_src = src[:-len(".json")] + ".exceptions.jsonl"
    if os.path.exists(exc_src):
        os.replace(exc_src, os.path.join(HELDOUT_DIR, base + ".original.exceptions.jsonl"))
    d.update(split=dict(date=time.strftime("%Y-%m-%dT%H:%M:%S"), census_sha256=census["sha256"],
                        relabelled=dict(moved), original=os.path.relpath(keep, ROOT).replace("\\", "/")))
    dev = [x for x in rows if x["partition"] in DEV_PARTITIONS]
    ho = [x for x in rows if x["partition"] not in DEV_PARTITIONS]
    _, e1 = _write_rule_output(src, d, dev)
    _, e2 = _write_rule_output(os.path.join(HELDOUT_DIR, base + ".heldout.json"), d, ho)
    print("relabelled %s; tune side %d rows (%d exceptions) at %s; held-out %d rows (%d exceptions) and the original "
          "moved to %s" % (dict(moved), len(dev), len(e1), os.path.relpath(src, ROOT), len(ho), len(e2),
                           os.path.relpath(HELDOUT_DIR, ROOT)))
    return 0


# ---------------------------------------------------------------- the rule registry and held-out looks

def registered(rule):
    if not os.path.exists(RULES):
        return None
    got = None
    with open(RULES, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                x = json.loads(ln)
                if x["rule"] == rule:
                    got = x
    return got


def append_chained(path, obj):
    prev = "0" * 64
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        if lines:
            prev = hashlib.sha256(lines[-1].rstrip("\n").encode("utf-8")).hexdigest()
    obj = dict(obj, prev=prev)
    text = (open(path, encoding="utf-8").read() if os.path.exists(path) else "") + \
        json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    A.write_text(path, text, encoding="utf-8", newline="\n")


def cmd_register(a):
    if a.rule != RULE1:
        print("unknown rule", a.rule)
        return 2
    if registered(RULE1) and registered(RULE1)["code"] == r1_code():
        print("already registered:", RULE1, r1_code())
        return 0
    append_chained(RULES, dict(
        rule=RULE1, code=r1_code(), date=time.strftime("%Y-%m-%dT%H:%M:%S"),
        params=dict(sym=R1_SYM, thresholds=list(R1_THRESHOLDS), invariant_min=R1_INVARIANT_MIN,
                    invariant_gain=R1_INVARIANT_GAIN),
        statement="A fit whose pitch is outside its template's frozen band and whose band is mirror-symmetric "
                  "(>= %.1f) re-searches its span: pairs of profile peaks symmetric about the mirror axis (within "
                  "2px) whose implied pitch is inside the band, from the strongest floor of %s that yields one; "
                  "the pitch nearest the band's centre wins. A re-fit is accepted only when its independent "
                  "invariant (twin agreement for doubles; NCC against the channel group's frozen receptor library "
                  "for singles) reaches %.2f and beats the BEFORE fit's by %.2f. In-band fits are returned byte-"
                  "identical; a fit that cannot reach the band, or has no invariant, goes to the exceptions "
                  "ledger; the band is never widened." % (R1_SYM, list(R1_THRESHOLDS), R1_INVARIANT_MIN,
                                                         R1_INVARIANT_GAIN),
        preregistered_effect=PREREG_EFFECT))
    print("registered", RULE1, r1_code())
    return 0


PREREG_EFFECT = (
    "Validation half only, scorable charts only (denominator fixed by the partitions file; a chart the "
    "rule cannot read scores 0 and never leaves the set). Metric: per-chart F1 of the extraction (column "
    "and time, 45 ms) against the count-exact file, through the rule's lanes and through the BEFORE lanes, "
    "same extractor, same floors. The rule passes when (1) among charts whose F1 changes, those that rise "
    "outnumber those that fall with a one-sided sign-test p <= 0.01, (2) the median F1 change over the "
    "charts the rule re-fitted is >= +0.05, and (3) no chart whose fit was in band changes at all. Rescued "
    "raises (a BEFORE fit that raised and a re-fit that reads) are reported separately and never count as "
    "gains. The sealed half is scored once, after the validation pass, with the same metric.")


def cmd_look(a):
    """Record a held-out look, or a partition correction (hash-chained)."""
    append_chained(LOOKS, dict(date=time.strftime("%Y-%m-%dT%H:%M:%S"), rule=a.rule, half=a.half, kind=a.kind,
                               what=a.what, result=a.result))
    print("recorded", a.kind)
    return 0


# ---------------------------------------------------------------- CLI

def cmd_partitions(a):
    meta = Meta()
    if a.v1:
        parts = build_partitions(meta)
    else:
        parts = build_partitions_v2(meta, read_frozen(PARTITIONS_V1), read_frozen(CENSUS_V1), read_frozen(SAMPLE))
        print("moved to seen: %s" % parts["moved_to_seen"])
        for n in parts["moved_to_seen"]:
            print("  %-45s %s" % (n, "; ".join(parts["charts"][n]["seen"])[:200]))
        print("scorable denominators: %s" % parts["scorable_denominators"])
        print("held-out charts in research files the scan does not read: %s"
              % parts["seen_sources"]["heldout_in_unread_research_summary"])
        print("split overlap: %s" % {k: (v if not isinstance(v, dict) else len(v)) for k, v in parts["split_overlap"].items()})
    print("misfits: %d" % parts["n_misfit36"])
    for k, v in parts["counts"].items():
        print("  %-28s %d" % (k, v))
    sc = Counter((c["partition"], c["scorable"]) for c in parts["charts"].values())
    print("  scorable:", dict(sc))
    if a.write:
        sha = write_frozen(PARTITIONS_V1 if a.v1 else PARTITIONS, parts)
        print("froze %s (sha256 %s)" % (os.path.relpath(PARTITIONS_V1 if a.v1 else PARTITIONS, ROOT), sha[:16]))
    return 0


def cmd_census(a):
    if a.v1:
        c = build_census(Meta(), read_frozen(PARTITIONS_V1))
    else:
        c = relabel_census(read_frozen(CENSUS_V1), read_frozen(PARTITIONS), read_frozen(SAMPLE))
        print("relabelled: %s" % c["relabelled"])
    print("census rows %d, with a cached fit %d" % (c["n_rows"], c["n_with_fit"]))
    for k, v in c["counts"].items():
        print("  %-32s %d" % (k, v))
    if a.write:
        sha = write_frozen(CENSUS_V1 if a.v1 else CENSUS, c)
        print("froze %s (sha256 %s)" % (os.path.relpath(CENSUS_V1 if a.v1 else CENSUS, ROOT), sha[:16]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("partitions")
    p.add_argument("--write", action="store_true")
    p.add_argument("--v1", action="store_true", help="the v1 builder (frozen already; for re-derivation)")
    p = sub.add_parser("census")
    p.add_argument("--write", action="store_true")
    p.add_argument("--v1", action="store_true", help="the v1 builder (frozen already; for re-derivation)")
    p = sub.add_parser("recompute")
    p.add_argument("--workers", type=int, default=WORKERS)
    p = sub.add_parser("sample")
    p.add_argument("--write", action="store_true")
    p.add_argument("--missing", help="write the sample videos not cached yet to this file, one per line")
    p = sub.add_parser("bands")
    p.add_argument("--write", action="store_true")
    p.add_argument("--workers", type=int, default=WORKERS)
    p = sub.add_parser("sensitivity")
    p.add_argument("--workers", type=int, default=WORKERS)
    p.add_argument("--also-v1", action="store_true", help="also exclude the videos v1's partitions name")
    p.add_argument("--out")
    p = sub.add_parser("register")
    p.add_argument("rule")
    p = sub.add_parser("rule1")
    p.add_argument("--out")
    p.add_argument("--partitions", help="comma-separated partitions to run on (default: tune,seen)")
    p.add_argument("--heldout-look", help="required to run a held-out partition: what the look is for (logged)")
    p.add_argument("--workers", type=int, default=WORKERS)
    p = sub.add_parser("split")
    p.add_argument("path")
    p = sub.add_parser("look")
    p.add_argument("--rule", required=True)
    p.add_argument("--half", required=True, choices=("validate", "sealed", "both"))
    p.add_argument("--kind", default="look", choices=("look", "correction"))
    p.add_argument("--what", required=True)
    p.add_argument("--result", required=True)
    a = ap.parse_args(argv)
    return {"partitions": cmd_partitions, "census": cmd_census, "recompute": cmd_recompute, "bands": cmd_bands,
            "sensitivity": cmd_sensitivity, "register": cmd_register, "rule1": cmd_rule1, "split": cmd_split,
            "look": cmd_look, "sample": cmd_sample}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
