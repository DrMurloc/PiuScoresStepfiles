# Chart identity: which block of the song's .ssc a certified play's notes actually match.
#
# A certification says "this video's side shows chart X at N judged notes", and the chart map says
# "chart X is block B of this .ssc". Either can be wrong while the other is right: the tail sweep
# matched site charts to blocks by name and level, and a chart the game re-rated since the pack's
# mix sits under another block's level (the site's "Witch Doctor D22" carries chartId b5cc8967,
# which the Phoenix 1 catalog lists as Double 23 with 1,162 notes - the pack's D23 INFOBAR block,
# not its D22 block). A repair loop pointed at the wrong block "fixes" a chart that was never
# broken, into the wrong shape.
#
# The notes decide. Every cached sprite pass is REPLAYED - the extractor's post-decode step run on
# the cached pass, no frame decoded - and scored by column+time F1 against every same-width block
# of the song, with blocks the converter cannot tell apart (identical note events: HIDDEN/INFOBAR
# twins) counted as one. A certified side whose extraction matches another block far better than
# its mapped block is a re-pair candidate; the rule and its references are in `decide`.
#
#   python -X utf8 -B tools/identity.py fingerprint <pass> [<pass> ...] [--out-dir D] [--force]
#   python -X utf8 -B tools/identity.py jobs <jobs.jsonl> [--shards N] [--only-missing]
#   python -X utf8 -B tools/identity.py decide [--out <report.json>] [--seed N]
#
# fingerprint writes one JSON per pass to work/identity/fp/ (atomic; keyed by the pass file, the
# song file's content and this module's code stamp, so a changed file or rule is re-scored). It
# runs read-only everywhere else (atomicio.forbid_writes) and refuses to open a video at all: the
# replay needs nothing but the pass.
import argparse
import bisect
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import defaultdict

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
import atomicio            # noqa: E402
import corpus_map          # noqa: E402
import guards              # noqa: E402
from cachekey import code_stamp  # noqa: E402

PASS_DIR = os.path.join(ROOT, "work", "spritepass")
FP_DIR = os.path.join(ROOT, "work", "identity", "fp")
# A pass name: <vid>.<band>.<side>.<ncols>.<scale>.<sep>.<anchor>.h<hp>.r<rest>.s<contrast>.<dur>.x<a>-<b>.pkl
# (note_extract.pass_path's legacy name). Older layouts lack the contrast and the lanes; they are
# fingerprinted too but flagged stale, and a side decides by its current-format pass.
_PASS = re.compile(r"^(?P<vid>.{11})\.(?P<band>[LCR])\.(?P<side>[12]p)\.(?P<ncols>5|10)\.(?P<rest>.*)\.pkl$")
_SCALE = re.compile(r"\.s(\d\.\d\d)\.")
_CURRENT = re.compile(r"\.h\d\.\d\d\.r\d\.\d\d\.s\d\.\d\d\.\d+\.\d\.x\d+-\d+\.pkl$")


def parse_pass(name):
    m = _PASS.match(name)
    if not m:
        return None
    s = _SCALE.search(name)
    return dict(vid=m.group("vid"), band=m.group("band"), side=m.group("side"), ncols=int(m.group("ncols")),
                scale=float(s.group(1)) if s else 1.0, current=bool(_CURRENT.search(name)))


# ---------------------------------------------------------------- the replay

def _no_video(*a, **k):
    raise RuntimeError("identity.py replays cached passes only: opening a video is refused")


def _import_extractor():
    import cv2
    cv2.VideoCapture = _no_video            # the replay decodes nothing; make that a guarantee
    import note_extract as N
    import receptors as R
    return N, R


def replay(pkl_path, ncols, scale):
    """The extraction a cached sprite pass stands for: note_extract._read's post-decode step, in its
    order - flashes from the receptor scan, the colour gate, every (colour, floor) candidate scored
    by flash agreement, the strictest floor within TIE of the best, the fallback when none scored,
    then the hold marks (which drop tail caps inside a rail). `scale` is the contrast scale the
    pass name records (two decimals; _read uses the unrounded value, so a pass cut at 0.87 may sit
    a thousandth off its production floors)."""
    N, R = _import_extractor()
    got = atomicio.load_pickle(pkl_path)
    if not (isinstance(got, tuple) and len(got) == 6):
        raise ValueError("not a sprite pass (%s)" % (type(got).__name__ if got is not None else "unloadable"))
    ts, scored, fps, y0, y1, scan = got
    floors = [round(f * scale, 3) for f in N.FLOORS]
    fl, _ = R.onsets(scan, 60.0)
    flashes = {c: sorted(v) for c, v in fl.items()}
    n_flash = sum(len(v) for v in flashes.values())
    gate = N.colour_floor(scored, floors[0])
    cands = []
    for sat in (0.0, gate):
        for floor in floors:
            cand = N._clean(N._cand(ts, N.at_floor(scored, floor, sat), ncols, y0, y1, fps))
            if len(cand) < 15:
                continue
            enough = len(cand) >= 0.6 * n_flash if n_flash else True
            cands.append((N.flash_agreement(cand, flashes, 0.0) * (1.0 if enough else 0.15), floor, sat, cand))
        if gate <= 0.0:
            break
    best = None
    if cands:
        top = max(c[0] for c in cands)
        best = max((c for c in cands if c[0] >= top - N.TIE), key=lambda c: (c[1], -c[2]))
    if best is None:
        best = (0.0, floors[1], 0.0, N._clean(N._cand(ts, N.at_floor(scored, floors[1]), ncols, y0, y1, fps)))
    sc, floor, sat, notes = best
    N.mark_holds(scan, notes)
    return notes, dict(floor=floor, colour=sat, flash_score=round(float(sc), 4), fallback=not cands)


# ---------------------------------------------------------------- aligning, fast and identical

def anchor_offset(notes, fcols, ncols, lo=0.0, hi=60.0, tol=0.08):
    """quantize.anchor_offset, vectorized: the same offsets in the same order, the same hit test
    (the first file note at or after t - tol, within tol), the same median error, the same
    first-best tie rule - the identical answer about fifty times faster. `fcols` is
    {col: sorted chart times}. Checked against the original in `selfcheck`."""
    by_col = []
    for c in range(ncols):
        col = np.asarray(fcols.get(c, []), dtype=float)
        if not len(col):
            continue
        nt = np.asarray([n["t"] for n in notes if n["col"] == c], dtype=float)
        if len(nt):
            by_col.append((col, nt))

    def scores(offs):
        hits = np.zeros(len(offs), dtype=int)
        errs = []
        for col, nt in by_col:
            t = nt[None, :] - offs[:, None]
            j = np.searchsorted(col, t - tol, side="left")
            ok = j < len(col)
            d = np.abs(col[np.minimum(j, len(col) - 1)] - t)
            ok &= d <= tol
            hits += ok.sum(axis=1)
            errs.append(np.where(ok, d, np.nan))
        med = np.full(len(offs), 9.9)
        if errs:
            # the median of each row's hits, as np.median takes it: NaN sorts last, so a row's n
            # hits are its first n sorted values; the middle one, or the mean of the middle two
            # computed as (a + b) / 2 exactly as np.mean of two values is
            e = np.sort(np.concatenate(errs, axis=1), axis=1)
            rows = np.nonzero(hits > 0)[0]
            n = hits[rows]
            lo = e[rows, (n - 1) // 2]
            hi = e[rows, n // 2]
            med[rows] = np.where(n % 2 == 1, lo, (lo + hi) / 2)
        return hits, med

    def first_best(offs, hits, med, best):
        for k in range(len(offs)):            # the original's strict, in-order comparison
            if (hits[k], -med[k]) > (best[0], -best[1]):
                best = (int(hits[k]), float(med[k]), float(offs[k]))
        return best

    best = (0, 9.9, lo)
    ks = np.arange(int(lo * 100), int(hi * 100))
    offs = ks / 100.0
    for i in range(0, len(offs), 500):
        o = offs[i:i + 500]
        h, m = scores(o)
        best = first_best(o, h, m, best)
    # the fine search walks from the CURRENT best, which moves as it improves (the original's
    # `a = best[2] + k / 1000.0` re-reads best every step), so it is evaluated one offset at a time
    for k in range(-30, 31):
        o = np.array([best[2] + k / 1000.0])
        h, m = scores(o)
        best = first_best(o, h, m, best)
    return best[2], best[0]


def align(notes, fnotes, ncols, X):
    """extract_repair.align with the vectorized anchor: chart_time = a + b * video_time."""
    seed, hit = anchor_offset(notes, {c: [x[0] for x in v] for c, v in fnotes.items()}, ncols)
    a, b = -seed, 1.0
    n_fit = 0
    for _ in range(3):
        xs, ys = [], []
        for n in notes:
            col = fnotes.get(n["col"], [])
            if not col:
                continue
            u = a + b * n["t"]
            ts = [x[0] for x in col]
            j = bisect.bisect_left(ts, u - 0.06)
            if j < len(ts) and abs(ts[j] - u) <= 0.06:
                xs.append(n["t"]); ys.append(ts[j])
        n_fit = len(xs)
        if n_fit < 20:
            break
        b, a = np.polyfit(xs, ys, 1)
        b = float(min(1.01, max(0.99, b))); a = float(a)
    return a, b, n_fit, seed


def score(notes, fnotes, ncols, X):
    """Column+time F1 of an extraction against one block's judged note events."""
    a, b, n_fit, seed = align(notes, fnotes, ncols, X)
    pairs, extra, missing, errs = X.match(notes, fnotes, ncols, a, b)
    fn = sum(len(v) for v in fnotes.values())
    rec = len(pairs) / max(1, fn)
    pre = len(pairs) / max(1, len(notes))
    f1 = 2 * rec * pre / max(1e-9, rec + pre)
    return dict(f1=round(f1, 4), recall=round(rec, 4), precision=round(pre, 4), matched=len(pairs),
                file_notes=fn, a=round(a, 4), b=round(b, 5), n_fit=n_fit)


# ---------------------------------------------------------------- the song's blocks

def _event_sig(fnotes):
    h = hashlib.sha256()
    for c in sorted(fnotes):
        for t, b, ch in fnotes[c]:
            h.update(("%d %.6f %s\n" % (c, t, ch)).encode())
    return h.hexdigest()[:16]


_BLOCKS = {}


def song_blocks(rel, X):
    """Every block of simfiles/<rel> the converter reaches by tag (the first block carrying a tag:
    a later duplicate is unreachable by any key and is listed as such), with its width, its
    implied count, its note events and a signature of them - blocks with equal signatures are
    one block to this fingerprint."""
    path = os.path.join(ROOT, "simfiles", *rel.split("/"))
    data = open(path, "rb").read()
    csha = hashlib.sha256(guards.normalize(data).encode("utf-8")).hexdigest()
    if (rel, csha) in _BLOCKS:
        return _BLOCKS[(rel, csha)]
    tags = guards.block_tags(data)
    out, seen = [], set()
    for i, tag in enumerate(tags):
        if tag in seen:
            out.append(dict(index=i, tag=tag, unreachable=True))
            continue
        seen.add(tag)
        blk = X.load_block(path, tag)
        if not blk or blk.get("error"):
            out.append(dict(index=i, tag=tag, error=(blk or {}).get("error", "block not found")))
            continue
        fnotes, _ = X.file_events(blk["rows"], blk["ncols"])
        out.append(dict(index=i, tag=tag, ncols=blk["ncols"], implied=blk["implied"], fnotes=fnotes,
                        sig=_event_sig(fnotes), block_sha=guards.block_sha_text(data, i)))
    _BLOCKS[(rel, csha)] = (csha, out)
    return csha, out


def songs_for(vid, cert, smap):
    """The .ssc files a video's result screen names: every chart the ledgers list for it."""
    e = cert.get(vid) or {}
    rels = []
    for name in (e.get("charts") or {}):
        m = smap.get(name)
        if m and m["ssc_rel"] not in rels:
            rels.append(m["ssc_rel"])
    return rels


# ---------------------------------------------------------------- one pass

def _code():
    return code_stamp(replay, anchor_offset, align, score, _event_sig, song_blocks, fingerprint_pass)


def fp_path(pass_name, out_dir=FP_DIR):
    return os.path.join(out_dir, pass_name[:-len(".pkl")] + ".json")


def fingerprint_pass(pass_name, cert, smap, X):
    info = parse_pass(pass_name)
    if info is None:
        return dict(pass_name=pass_name, error="not a sprite-pass name")
    rels = songs_for(info["vid"], cert, smap)
    res = dict(info, pass_name=pass_name, songs=[])
    if not rels:
        res["error"] = "no chart of this video is in the chart map"
        return res
    try:
        notes, meta = replay(os.path.join(PASS_DIR, pass_name), info["ncols"], info["scale"])
    except Exception as ex:
        res["error"] = "replay: %s: %s" % (type(ex).__name__, str(ex)[:160])
        return res
    res.update(meta, notes=len(notes))
    for rel in rels:
        csha, blocks = song_blocks(rel, X)
        rows = []
        for b in blocks:
            row = {k: b[k] for k in ("index", "tag") if k in b}
            if b.get("unreachable") or b.get("error"):
                row.update(unreachable=bool(b.get("unreachable")), error=b.get("error"))
            elif b["ncols"] != info["ncols"]:
                continue
            else:
                row.update(implied=b["implied"], sig=b["sig"], block_sha=b["block_sha"],
                           **score(notes, b["fnotes"], info["ncols"], X))
            rows.append(row)
        res["songs"].append(dict(ssc_rel=rel, content_sha=csha, blocks=rows))
    return res


def cmd_fingerprint(args):
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    atomicio.forbid_writes([out_dir])
    import extract_repair as X
    cert, smap = corpus_map.certification(overlays=[]), corpus_map.chart_map(overlays=[])
    code = _code()
    names = []
    for p in args.passes:
        if p.startswith("@"):
            names += [l.strip() for l in open(p[1:], encoding="utf-8") if l.strip()]
        else:
            names.append(os.path.basename(p))
    done = bad = 0
    for name in names:
        out = fp_path(name, out_dir)
        prev = atomicio.load_json(out, quiet=True)
        t0 = time.time()
        if prev and not args.force and prev.get("code") == code:
            rels = [s["ssc_rel"] for s in prev.get("songs", [])]
            fresh = all(song_blocks(r, X)[0] == s["content_sha"] for r, s in zip(rels, prev["songs"]))
            if fresh and rels == songs_for(prev["vid"], cert, smap):
                done += 1
                continue
        res = fingerprint_pass(name, cert, smap, X)
        res["code"] = code
        res["seconds"] = round(time.time() - t0, 2)
        atomicio.write_json(out, res, indent=0, sort_keys=True)
        done += 1
        bad += "error" in res
        print("%s %s %.1fs%s" % (name, "ERR " + res["error"] if "error" in res else "ok", time.time() - t0,
                                 "" if "error" in res else " (%d notes)" % res["notes"]), flush=True)
    print("VERDICT: %s" % ("OK" if not bad else "PARTIAL"))
    print("fingerprinted %d passes, %d with an error" % (done, bad))


# ---------------------------------------------------------------- deciding

# The re-pair rule (loop bucket #2, 2026-09-26): a certified side is re-paired to another block only
# when its extraction matches that block with F1 >= BEST_F1, by MARGIN or more over both the mapped
# block and the runner-up (blocks with identical note events are one block), AND a second,
# independent reference agrees: the block converts to the certified result-screen total (count
# agreement), or a blind read of the result screen's level ball does. Round-hundred totals, a
# total more than one catalog chart of the song carries, and anything that would contradict an
# eye-verified census row go to the owner instead.
BEST_F1 = 0.8
MARGIN = 0.3


def load_fps(fp_dir=FP_DIR, any_code=False):
    """Every fingerprint this code wrote (another stamp's result is not this rule's evidence)."""
    out, stale = {}, 0
    code = _code()
    for f in sorted(os.listdir(fp_dir)):
        if f.endswith(".json"):
            d = atomicio.load_json(os.path.join(fp_dir, f), quiet=True)
            if d and d.get("pass_name"):
                if d.get("code") != code and not any_code:
                    stale += 1
                    continue
                out[d["pass_name"]] = d
    if stale:
        print("[identity] %d fingerprints carry another code stamp and are left out" % stale, file=sys.stderr)
    return out


def by_side(fps):
    """(vid, side, ncols) -> fingerprints of that pad, current-format passes first."""
    out = defaultdict(list)
    for d in fps.values():
        if "error" in d or not d.get("songs"):
            continue
        out[(d["vid"], d["side"], d["ncols"])].append(d)
    for k in out:
        out[k].sort(key=lambda d: (not d.get("current"), d["pass_name"]))
    return out


def groups_of(song):
    """A song's scored blocks grouped into what the notes can tell apart, best first: blocks with one
    note-event signature (byte-identical twins), and blocks the extraction matched identically - the
    same F1, recall, precision, match count, file note count and fitted clock, which is what two
    blocks give when they differ only in whether a note is a tap or a hold head (a HIDDEN variant).
    Each group: {sig, f1, members: [block rows]}."""
    g = {}
    for b in song["blocks"]:
        if b.get("f1") is None:
            continue
        k = (b["f1"], b.get("recall"), b.get("precision"), b.get("matched"), b.get("file_notes"), b.get("a"), b.get("b"))
        grp = next((x for x in g.values() if x["sig"] == b["sig"] or x["key"] == k), None)
        if grp is None:
            grp = g.setdefault(len(g), dict(sig=b["sig"], key=k, f1=b["f1"], members=[]))
        grp["members"].append(b)
    return sorted(g.values(), key=lambda x: (-x["f1"], x["members"][0]["index"]))


def key_for(key, tag):
    """The chartstruct key of another block of the same file: the mapped key's song prefix plus the
    tag, spelled the way guards.tag_of reads it back - or None when the tag cannot be spelled as a
    key (a tag with no S/D level: UCS, QUEST, COOP)."""
    m = guards._TAG.search(key)
    if not m:
        return None
    desc, stype = tag.rsplit("_", 1)
    new = key[:m.start()] + "_" + desc.replace(" ", "_") + "_" + stype
    try:
        return new if guards.tag_of(new) == tag else None
    except ValueError:
        return None


def assess(name, entry, fp):
    """One certified chart against one fingerprint of its pad: where its mapped block stands."""
    song = next((s for s in fp["songs"] if s["ssc_rel"] == entry["ssc_rel"]), None)
    if song is None:
        return dict(chart=name, status="no-song", pass_name=fp["pass_name"])
    try:
        tag = guards.tag_of(entry["key"])
    except ValueError:
        tag = None
    gs = groups_of(song)
    mapped = next((b for b in song["blocks"] if b.get("tag") == tag), None)
    res = dict(chart=name, pass_name=fp["pass_name"], current=fp.get("current"), mapped_tag=tag, notes=fp.get("notes"))
    if not gs:
        return dict(res, status="no-blocks")
    if mapped is None or mapped.get("f1") is None:
        res.update(status="mapped-block-unscored", mapped_error=(mapped or {}).get("error") or "tag not in file")
    best = gs[0]
    runner = gs[1]["f1"] if len(gs) > 1 else 0.0
    mf1 = mapped.get("f1") if mapped else None
    own = mapped is not None and any(m is mapped for m in best["members"])
    res.update(best_f1=best["f1"], best_tags=[m["tag"] for m in best["members"]],
               best_implied=sorted({m["implied"] for m in best["members"]}), runner_f1=runner,
               mapped_f1=mf1, own=own, groups=len(gs),
               margin_mapped=round(best["f1"] - (mf1 or 0.0), 4) if not own else 0.0,
               margin_runner=round(best["f1"] - runner, 4),
               table=[[m["tag"] for m in g["members"]] + [g["f1"], sorted({m["implied"] for m in g["members"]})]
                      for g in gs[:6]])
    if "status" in res:
        pass
    elif own:
        res["status"] = "own" if best["f1"] >= BEST_F1 else "own-low"
    elif best["f1"] < BEST_F1:
        res["status"] = "unmatched"
    elif mapped.get("implied") is not None and mapped["implied"] == entry.get("expected"):
        # the mapped block converts to the certified total: the count, an independent reference,
        # sides with the map, so the notes alone never move it (a jack chart the extractor
        # under-reads can match a sparser sibling better than its own block)
        res["status"] = "exact-notes-disagree"
    elif res["margin_mapped"] >= MARGIN and res["margin_runner"] >= MARGIN:
        res["status"] = "candidate"
    else:
        res["status"] = "ambiguous"
    res["_best"] = best
    return res


def choose(name, entry, a, expected, catalog_row):
    """The target block of a candidate: the best group's member whose count is the certified total
    (when the twins' counts differ), else the one whose tag level is the chart's catalog level,
    else the first in file order. -> (member row, why)."""
    members = a["_best"]["members"]
    agree = [m for m in members if m["implied"] == expected]
    if len(agree) == 1 or (agree and len({m["implied"] for m in members}) > 1):
        pool, why = agree, "count"
    else:
        pool, why = members, "twins"
    if len(pool) > 1 and catalog_row:
        lvl = [m for m in pool if re.match(r"^[SD]%d(\D|$)" % catalog_row["p1_level"], m["tag"])]
        if lvl:
            pool, why = lvl, why + "+catalog-level"
    return pool[0], why


def cmd_decide(args):
    fps = load_fps(args.fp_dir, args.any_code)
    sides = by_side(fps)
    smap = corpus_map.chart_map(overlays=[])
    cert = corpus_map.certification(sources_only=True, overlays=[])
    pop = corpus_map.charts(sources_only=True, overlays=[])
    census_names = {r["chart"] for r in corpus_map._load(corpus_map.CENSUS_MAP, [])}
    census_cert = corpus_map.ledger_entries(corpus_map._load(corpus_map.CENSUS_CERT, {}))
    census_certified = {(vid, n) for vid, e in census_cert.items() for n, c in (e.get("charts") or {}).items()
                        if c.get("verdict") == "CERTIFIED"}
    catalog = corpus_map._load(os.path.join(ROOT, "sources", "p1-note-counts-2026-07-04.json"), {}).get("charts", [])
    by_id = {c["chartId"].lower(): c for c in catalog if c.get("chartId")}
    by_song_type = defaultdict(list)
    for c in catalog:
        by_song_type[(c["song"].lower(), c["type"][0])].append(c)
    grade = {r["chart"]: r for r in corpus_map._load(os.path.join(ROOT, "sources", "corpus-grade.json"), {}).get("charts", [])}
    conflict = {c["chart"]: c for c in corpus_map._load(os.path.join(ROOT, "sources", "oracle-conflict.json"), {}).get("charts", [])}
    revisit = {c["chart"] for c in corpus_map._load(os.path.join(ROOT, "sources", "owner-revisit.json"), {}).get("charts", [])}
    quarantine = {c["chart"] for c in corpus_map._load(os.path.join(ROOT, "sources", "quarantine.json"), {}).get("charts", [])}
    cvm = {e["vid"]: e for e in (corpus_map._load(os.path.join(ROOT, "work", "corpus-video-map.json"), []) or [])}
    keys_in_file = defaultdict(dict)
    for n, e in smap.items():
        keys_in_file[e["ssc_rel"]][e["key"]] = n

    def owner_reasons(name, vid, expected, key):
        """Why the rule may not move this chart on its own (an empty list: it may)."""
        reasons = []
        if expected and int(expected) % 100 == 0:
            reasons.append("round-hundred total %s" % expected)
        song = re.sub(r"\s+[SD]\d+$", "", name).lower()
        same = [c for c in by_song_type.get((song, name.split()[-1][0]), []) if c.get("p1_notes") == expected]
        if len(same) > 1:
            reasons.append("%d catalog charts of the song carry %s notes (%s)" % (
                len(same), expected, ", ".join("%s%d" % (c["type"][0], c["p1_level"]) for c in same)))
        if name in census_names:
            reasons.append("the chart map's census row (eye-verified) says %s" % key)
        if (vid, name) in census_certified:
            reasons.append("the census certification (eye-verified) names this video's side")
        if name in revisit:
            reasons.append("owner-revisit chart")
        if name in quarantine:
            reasons.append("quarantined chart")
        return reasons

    def assess_all(the_map, names=None):
        out = {}
        for name in sorted(pop if names is None else names):
            c = pop[name]
            e = the_map.get(name, c)
            entry = dict(c, key=e["key"], ssc_rel=e["ssc_rel"])
            ncols = 10 if name.split()[-1][0] == "D" else 5
            cands = sides.get((c["vid"], c["side"], ncols), [])
            if not cands:
                out[name] = dict(chart=name, status="no-pass", vid=c["vid"], side=c["side"])
                continue
            rs = [assess(name, entry, fp) for fp in cands]
            cur = [r for r in rs if r.get("current")] or rs
            r = max(cur, key=lambda r: (r.get("best_f1") or 0.0))
            bests = {tuple(sorted(x.get("best_tags") or [])) for x in cur if x.get("best_f1", 0) >= BEST_F1}
            if len(bests) > 1:
                r = dict(r, status="passes-disagree", disagree=sorted(bests))
            out[name] = dict(r, vid=c["vid"], side=c["side"], expected=c["expected"], key=entry["key"],
                             ssc_rel=entry["ssc_rel"], passes=len(rs))
        return out

    def propose(ass, the_map):
        """Candidates -> re-key rows, owner-list rows and pending (need a blind ball read)."""
        rows, owner, pending = [], [], []
        keys = defaultdict(dict)
        for n, e in the_map.items():
            keys[e["ssc_rel"]][e["key"]] = n
        for name, a in sorted(ass.items()):
            if a.get("status") != "candidate":
                continue
            e = the_map[name]
            cat = by_id.get((e.get("chartId") or smap.get(name, {}).get("chartId") or "").lower())
            m, why = choose(name, e, a, a["expected"], cat)
            to_key = key_for(e["key"], m["tag"])
            row = dict(kind="rekey", chart=name, ssc_rel=e["ssc_rel"], from_key=e["key"], to_key=to_key,
                       to_tag=m["tag"], vid=a["vid"], side=a["side"], expected=a["expected"],
                       evidence=dict(pass_name=a["pass_name"], f1_best=a["best_f1"], f1_mapped=a["mapped_f1"],
                                     f1_runner=a["runner_f1"], margin_mapped=a["margin_mapped"],
                                     margin_runner=a["margin_runner"], to_implied=m["implied"],
                                     count_agrees=m["implied"] == a["expected"], chosen_by=why,
                                     twins=[x["tag"] for x in a["_best"]["members"] if x["tag"] != m["tag"]],
                                     table=a["table"]))
            cv = [x for x in (cvm.get(a["vid"]) or {}).get("charts", []) if x.get("chart") == name]
            if cv:
                row["evidence"]["chartvideo_side"] = cv[0].get("side")
            if name in conflict:
                row["evidence"]["oracle_conflict"] = [r["kind"] for r in conflict[name].get("reasons", [])]
            if cat:
                row["evidence"]["catalog"] = dict(chartId=cat["chartId"], type=cat["type"], p1_level=cat["p1_level"],
                                                  p2_level=cat.get("p2_level"), p1_notes=cat.get("p1_notes"))
            reasons = owner_reasons(name, a["vid"], a["expected"], e["key"])
            if to_key is None:
                reasons.insert(0, "the target block %s cannot be spelled as a chartstruct key" % m["tag"])
            holder = keys[e["ssc_rel"]].get(to_key) if to_key else None
            if holder and holder != name:
                row["crosses"] = holder
            if reasons:
                owner.append(dict(chart=name, reason="; ".join(reasons), row=row))
            elif row["evidence"]["count_agrees"]:
                rows.append(row)
            else:
                pending.append(row)
        # a target another chart holds: fine only when that chart moves too (a crossed pair or a
        # chain), and never two charts left on one key. A pair moves together: when one half waits
        # on a ball read, so does the other.
        moving = {r["chart"]: r for r in rows + pending}
        final = {n: (moving[n]["to_key"] if n in moving else e["key"]) for n, e in the_map.items()}
        by_key = defaultdict(list)
        for n, k in final.items():
            by_key[(the_map[n]["ssc_rel"], k)].append(n)
        stuck = set()
        for names in by_key.values():
            if len(names) > 1:
                stuck |= {n for n in names if n in moving}
        # a chart whose target is held by a chart that stays put, or by one that is itself stuck
        changed = True
        while changed:
            changed = False
            for n, r in moving.items():
                h = r.get("crosses")
                if n not in stuck and h and (h not in moving or h in stuck):
                    stuck.add(n); changed = True
        keep, wait = [], []
        pend = {r["chart"] for r in pending}
        for r in rows + pending:
            n = r["chart"]
            if n in stuck:
                h = r.get("crosses")
                owner.append(dict(chart=n, reason="the target block %s is %s's, which %s" % (
                    r["to_tag"], h or "another chart", "does not move" if h not in moving else "cannot move either"), row=r))
                continue
            partner = r.get("crosses")
            if n in pend or (partner and partner in pend):
                if n not in pend:
                    r = dict(r, waits_on=partner)
                wait.append(r)
            else:
                keep.append(r)
        pending = wait
        return keep, owner, pending

    ass = assess_all(smap)
    rows, owner, pending = propose(ass, smap)

    # ---- one side, two names: a result screen shows one total per side, so at most one of them is
    # the play. The census ledger (eye-verified) decides where it certifies one of them; otherwise
    # the pad's own extraction does, by the same rule as a re-key (the winner's mapped block is the
    # best by MARGIN over the other names' blocks and the runner-up, and converts to the total).
    withdraw = []
    doubles = []
    for vid in sorted(cert):
        by = defaultdict(list)
        for n, c in sorted((cert[vid].get("charts") or {}).items()):
            if c.get("verdict") == "CERTIFIED":
                by[c.get("side") or "1p"].append(n)
        for side, names in sorted(by.items()):
            if len(names) > 1:
                doubles.append((vid, side, names))
    for vid, side, names in doubles:
        verified = sorted(n for n in names if (vid, n) in census_certified)
        ev = {}
        for n in names:
            a = ass.get(n) or {}
            if a.get("vid") == vid:
                ev[n] = {k: a.get(k) for k in ("status", "pass_name", "mapped_tag", "mapped_f1", "best_f1", "best_tags",
                                               "runner_f1", "table")}
        base = dict(kind="withdraw", vid=vid, side=side, names=names)
        if verified:
            for n in names:
                if n not in verified:
                    withdraw.append(dict(base, chart=n, evidence=dict(census_verified=verified, fingerprint=ev,
                                                                      why="the census ledger (eye-verified) certifies %s on "
                                                                          "this side" % " + ".join(verified))))
            continue
        scored = [n for n in names if n in ev and ev[n].get("mapped_f1") is not None]
        winners = [n for n in scored if ass[n]["own"] and ass[n]["best_f1"] >= BEST_F1]
        if not scored:
            # no cached pass of this pad: the level ball alone can say which name is the play
            for n in names:
                pending.append(dict(base, chart=n, expected=(cert[vid].get(side) or {}).get("judged"), to_tag=None,
                                    from_key=smap[n]["key"], evidence=dict(why="no cached pass of this pad: a ball read "
                                                                               "decides which name is the play")))
            continue
        if len(winners) != 1:
            owner.append(dict(chart=" + ".join(names), reason="one side certifies %d charts and the extraction %s" % (
                len(names), "matches none of their blocks" if not winners else "matches more than one"),
                row=dict(base, evidence=ev)))
            continue
        w = winners[0]
        others = [ass[n]["mapped_f1"] for n in scored if n != w]
        margin = min([ass[w]["best_f1"] - f for f in others] + [ass[w]["margin_runner"]])
        wimp = ass[w]["best_implied"]
        count_ok = ass[w]["expected"] in wimp
        row_ev = dict(winner=w, margin=round(margin, 4), count_agrees=count_ok, winner_implied=wimp, fingerprint=ev)
        losers = [n for n in names if n != w]
        if margin < MARGIN:
            owner.append(dict(chart=" + ".join(names), reason="the extraction prefers %s by only %.3f" % (w, margin),
                              row=dict(base, evidence=row_ev)))
        elif count_ok:
            for n in losers:
                withdraw.append(dict(base, chart=n, evidence=dict(row_ev, why="the pad's notes are %s's block (F1 %.3f, "
                                     "margin %.3f), which converts to the certified total" % (w, ass[w]["best_f1"], margin))))
        else:
            for n in losers:
                pending.append(dict(base, chart=n, evidence=dict(row_ev, why="the notes prefer %s but its block does not "
                                    "convert to the certified total: a ball read decides" % w), expected=ass[w]["expected"],
                                    to_tag=None, from_key=smap[n]["key"]))

    # ---- controls: exact charts with a strong own match must each pick their own block
    rng = random.Random(args.seed)
    exact_own = sorted(n for n, a in ass.items() if grade.get(n, {}).get("exact") and a.get("mapped_f1") is not None
                       and a["mapped_f1"] >= 0.9 and n not in quarantine)
    sample = rng.sample(exact_own, min(args.controls, len(exact_own)))
    ctrl = [dict(chart=n, status=ass[n]["status"], own=ass[n]["own"], mapped_f1=ass[n]["mapped_f1"],
                 runner_f1=ass[n]["runner_f1"], margin_runner=ass[n]["margin_runner"]) for n in sample]
    ctrl_ok = sum(1 for c in ctrl if c["own"])
    ctrl_margin = sum(1 for c in ctrl if c["own"] and c["margin_runner"] >= MARGIN)
    all_exact = [n for n, a in ass.items() if grade.get(n, {}).get("exact") and a.get("best_f1") is not None]
    all_exact_own = sum(1 for n in all_exact if ass[n]["own"])
    all_exact_repair = sorted(n for n in all_exact if ass[n]["status"] == "candidate")

    # ---- the swap drill: two exact, confidently-own charts of one file swap keys in a copy of the
    # map; the rule must put both back, with count agreement, and touch nothing else
    eligible = defaultdict(list)
    for n in exact_own:
        a = ass[n]
        if a["own"] and a["margin_runner"] >= MARGIN and not owner_reasons(n, a["vid"], a["expected"], smap[n]["key"]):
            eligible[(smap[n]["ssc_rel"], n.split()[-1][0])].append(n)
    pairs = []
    for k in sorted(eligible):
        ns = sorted(eligible[k])
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                if ass[ns[i]]["best_tags"] != ass[ns[j]]["best_tags"]:
                    pairs.append((ns[i], ns[j]))
    rng.shuffle(pairs)
    drill = []
    used = set()
    for a_, b_ in pairs:
        if len(drill) >= args.swaps:
            break
        if a_ in used or b_ in used:
            continue
        used |= {a_, b_}
        m2 = dict(smap)
        m2[a_] = dict(smap[a_], key=smap[b_]["key"])
        m2[b_] = dict(smap[b_], key=smap[a_]["key"])
        ass2 = assess_all(m2, (a_, b_))
        r2, o2, p2 = propose(ass2, m2)
        got = {r["chart"]: r["to_key"] for r in r2}
        ok = got == {a_: smap[a_]["key"], b_: smap[b_]["key"]} and not o2 and not p2
        drill.append(dict(pair=[a_, b_], recovered=ok, rows=got, owner=[o["reason"] for o in o2],
                          pending=[p["chart"] for p in p2]))

    # ---- the rest of the picture
    status_n = defaultdict(int)
    for a in ass.values():
        status_n[a["status"]] += 1
    sibling_exact = []
    for name, a in sorted(ass.items()):
        if grade.get(name, {}).get("exact") or a.get("status") in ("no-pass",):
            continue
        fp = next((d for d in sides.get((a["vid"], a["side"], 10 if name.split()[-1][0] == "D" else 5), [])
                   if d["pass_name"] == a.get("pass_name")), None)
        song = next((s for s in (fp or {}).get("songs", []) if s["ssc_rel"] == pop[name]["ssc_rel"]), None)
        ex = [b["tag"] for b in (song or {}).get("blocks", []) if b.get("implied") == a["expected"]]
        if ex:
            sibling_exact.append(dict(chart=name, blocks=ex, status=a["status"]))
    report = dict(tool="identity decide", code=_code(), fp_dir=os.path.abspath(args.fp_dir), fingerprints=len(fps),
                  rule=dict(best_f1=BEST_F1, margin=MARGIN),
                  population=len(pop), status=dict(status_n),
                  controls=dict(sample=len(ctrl), picked_own=ctrl_ok, picked_own_by_margin=ctrl_margin, seed=args.seed, rows=ctrl,
                                all_exact_scored=len(all_exact), all_exact_own=all_exact_own,
                                all_exact_would_repair=all_exact_repair),
                  swap_drill=dict(pairs=len(drill), recovered=sum(d["recovered"] for d in drill), rows=drill),
                  rekey=rows, withdraw=withdraw, pending_ball=pending, owner=owner, sibling_exact=sibling_exact,
                  assessments={n: {k: v for k, v in a.items() if not k.startswith("_")} for n, a in ass.items()})
    atomicio.write_json(args.out, report, indent=1, sort_keys=True, ensure_ascii=False)
    print("fingerprints %d, population %d: %s" % (len(fps), len(pop), ", ".join("%s %d" % kv for kv in sorted(status_n.items()))))
    print("controls: %d of %d random exact charts (own F1 >= 0.9) pick their own block (%d of them by the %.1f margin); "
          "all exact scored: %d of %d own, %d would re-pair" % (ctrl_ok, len(ctrl), ctrl_margin, MARGIN, all_exact_own,
                                                               len(all_exact), len(all_exact_repair)))
    print("swap drill: %d of %d pairs recovered" % (sum(d["recovered"] for d in drill), len(drill)))
    print("re-key rows (count agrees): %d; withdrawals: %d; pending a ball read: %d; owner list: %d" % (
        len(rows), len(withdraw), len(pending), len(owner)))
    for w in withdraw:
        print("  WITHDRAW %-37s on %s %s: %s" % (w["chart"], w["vid"], w["side"], w["evidence"]["why"]))
    for r in rows:
        print("  REKEY %-40s %s -> %s (%s) F1 %.3f vs mapped %.3f, runner %.3f; %s" % (
            r["chart"], guards.tag_of(r["from_key"]), r["to_tag"], r["to_implied"] if "to_implied" in r else r["evidence"]["to_implied"],
            r["evidence"]["f1_best"], r["evidence"]["f1_mapped"] or 0, r["evidence"]["f1_runner"], r["evidence"]["chosen_by"]))
    for r in pending:
        if r["kind"] == "rekey":
            print("  PENDING %-38s %s -> %s (%s vs certified %s) F1 %.3f" % (
                r["chart"], guards.tag_of(r["from_key"]), r["to_tag"], r["evidence"]["to_implied"], r["expected"],
                r["evidence"]["f1_best"]))
        else:
            print("  PENDING %-38s withdraw from %s %s: %s" % (r["chart"], r["vid"], r["side"], r["evidence"]["why"]))
    for o in owner:
        print("  OWNER %-40s %s" % (o["chart"], o["reason"]))
    print("wrote " + args.out)


# ---------------------------------------------------------------- blind reads of the result screen

# Where the level ball and the title sit on a 720p result screen, relative to the MAX COMBO label
# result_reader anchors on (measured on -CgjGjTCzNs, Phoenix, and 4dUjYYaPCRs, XX): (dx, dy) of
# the crop's top-left and its size. XX shows one player only.
CROPS = {
    "phoenix": dict(ball={"1p": (-180, -272, 140, 112), "2p": (230, -272, 140, 112)}, title=(-235, -345, 660, 56)),
    "xx": dict(ball={"1p": (-190, 110, 184, 190)}, title=(-250, -236, 640, 64)),
}
BALL_ASK = ("This is a crop of a dance game's result screen, where a round badge (the 'ball') shows the chart "
            "played: a word or words printed across its top and a number in its middle. What does it say?")
BALL_FORMAT = ("WORD/NUMBER in capitals, the word(s) exactly as printed with spaces kept, e.g. 'SINGLE/16' or "
               "'DOUBLE/21'. 'NONE' if no ball is in the crop, 'UNSURE' if any part cannot be read.")
TITLE_ASK = ("Two crops, each the song-title strip of a dance game's result screen (the title may be in any "
             "language or script, and a faint background may show through). Do both show the SAME song title?")
TITLE_FORMAT = "'SAME', 'DIFFERENT' or 'UNSURE'"
INSTRUCTIONS = ("Answer each item from the images alone. Do not guess: say UNSURE when you cannot read it. "
                "Answer every item in the exact format it asks for. Items are independent of each other.")


def _frame(vid, t):
    import cv2
    import result_reader as RR
    cap = cv2.VideoCapture(RR.video_path(vid))
    f = RR.frame_at(cap, float(t))
    cap.release()
    return f


def _anchor(f, skin):
    import result_reader as RR
    best = None
    for p in RR.load_profiles():
        if skin and p["name"] != skin:
            continue
        mx, loc = RR.match_anchor(f, p["anchor"])
        if best is None or mx > best[0]:
            best = (mx, loc, p["name"])
    return best


def _crop(f, loc, box):
    x0, y0 = loc[0] + box[0], loc[1] + box[1]
    h, w = f.shape[:2]
    return f[max(0, y0):min(h, y0 + box[3]), max(0, x0):min(w, x0 + box[2])]


def ball_answer(name):
    kind = name.split()[-1][0]
    return "%s/%s" % ({"S": "SINGLE", "D": "DOUBLE"}[kind], re.sub(r"\D", "", name.split()[-1]))


def norm_answer(s):
    return re.sub(r"\s+", " ", str(s or "").strip().upper().replace(" ", " "))


def cmd_packets(args):
    """Blind packets for the reads the rule cannot settle from the notes and the count: level balls
    (and, for song-level mismaps, a title SAME/DIFFERENT against a reference video of the named
    song), seeded with known answers. No expected value, chart name or count is written into a
    packet; the key (seeds, and what each item stands for) goes to --keys, outside the packets."""
    import cv2
    import supervise
    rep = json.load(open(args.report, encoding="utf-8"))
    cert = corpus_map.certification(overlays=[])
    smap = corpus_map.chart_map(overlays=[])
    grade = {r["chart"]: r for r in corpus_map._load(os.path.join(ROOT, "sources", "corpus-grade.json"), {}).get("charts", [])}
    catalog = corpus_map._load(os.path.join(ROOT, "sources", "p1-note-counts-2026-07-04.json"), {}).get("charts", [])
    by_id = {c["chartId"].lower(): c for c in catalog if c.get("chartId")}
    conflict = corpus_map._load(os.path.join(ROOT, "sources", "oracle-conflict.json"), {})
    # the uploader's channel: one machine shows its titles in one language, so a title pair is only
    # compared (and a SAME seed only drawn) within a channel where possible
    chan = {e["vid"]: e.get("channel") for e in (corpus_map._load(os.path.join(ROOT, "work", "corpus-video-map.json"), []) or [])}
    rng = random.Random(args.seed)
    ass = rep["assessments"]

    # ---- what needs reading
    balls, titles = [], []
    for r in rep.get("pending_ball", []):
        balls.append(dict(vid=r["vid"], side=r["side"], chart=r["chart"], from_tag=guards.tag_of(r["from_key"]),
                          to_tag=r.get("to_tag"), purpose="pending re-key" if r["kind"] == "rekey"
                          else "same-side double certification (no cached pass)"))
    for v in conflict.get("videos", []):
        balls.append(dict(vid=v["vid"], side=v["side"], purpose="same-side double certification", charts=v["charts"],
                          census_verified=v["census_verified"]))
    # a certified side whose notes match no block of the named song at all: a song-level mismap the
    # count cannot see looks exactly like this, so its ball and title are read too
    extra = [v for v in (args.extra_videos or "").split(",") if v]
    for n, a in sorted(ass.items()):
        if a.get("status") == "unmatched" and (a.get("best_f1") or 0) < args.unmatched_below and a["vid"] not in extra \
                and not guards.footage_corrupt_reason(a["vid"]):        # a truncated pass explains itself
            extra.append(a["vid"])
    for vid in extra:
        e = cert.get(vid) or {}
        named = sorted(e.get("charts") or {})
        for side in ("1p", "2p"):
            if (e.get(side) or {}).get("judged"):
                balls.append(dict(vid=vid, side=side, purpose="song-level mismap (%s)" % (
                    "pre-registered" if vid in (args.extra_videos or "") else "notes match no block"), charts=named,
                    judged=e[side]["judged"]))
        # a reference video of each named song, same skin, whose own notes prove the song: its pad's
        # extraction matches a block of that song's file at F1 >= BEST_F1 (an exact, own-block
        # certification first)
        for n in named:
            rel = (smap.get(n) or {}).get("ssc_rel")
            refs = sorted((m for m, a in ass.items() if (a.get("best_f1") or 0) >= BEST_F1
                           and (smap.get(m) or {}).get("ssc_rel") == rel and a["vid"] != vid
                           and (cert.get(a["vid"]) or {}).get("skin") == e.get("skin")),
                          key=lambda m: (chan.get(ass[m]["vid"]) != chan.get(vid),
                                         not (ass[m].get("status") == "own" and grade.get(m, {}).get("exact")), m))
            if refs:
                titles.append(dict(vid=vid, ref_vid=ass[refs[0]]["vid"], ref_chart=refs[0], named=n,
                                   purpose="song-level mismap (%s)" % (
                                       "pre-registered" if vid in (args.extra_videos or "") else "notes match no block")))
            else:
                titles.append(dict(vid=vid, ref_vid=None, named=n, purpose="no reference video of the named song"))
    seen = set()
    balls = [b for b in balls if not ((b["vid"], b["side"]) in seen or seen.add((b["vid"], b["side"])))]

    # ---- seeds: exact, own-block charts whose name level, catalog level and block level agree
    seedable = []
    for n, a in sorted(ass.items()):
        e = smap.get(n) or {}
        cat = by_id.get((e.get("chartId") or "").lower())
        lvl = re.sub(r"\D", "", n.split()[-1])
        if (a.get("status") == "own" and (a.get("mapped_f1") or 0) >= 0.9 and grade.get(n, {}).get("exact") and cat
                and str(cat["p1_level"]) == lvl and re.match(r"^[SD]%s_" % lvl, a.get("mapped_tag") or "")
                and n.split()[-1][0] in "SD" and "HALFDOUBLE" not in (e.get("key") or "")
                and (cert.get(a["vid"]) or {}).get("skin") in ("phoenix", "xx")
                and a["vid"] not in {b["vid"] for b in balls}):
            seedable.append(n)
    rng.shuffle(seedable)
    by_song_vid = defaultdict(list)
    for n in seedable:
        if (cert.get(ass[n]["vid"]) or {}).get("skin") == "phoenix":
            by_song_vid[smap[n]["ssc_rel"]].append(n)
    same = [(a_, b_) for v in by_song_vid.values() for i, a_ in enumerate(v) for b_ in v[i + 1:]
            if ass[a_]["vid"] != ass[b_]["vid"] and chan.get(ass[a_]["vid"]) and chan.get(ass[a_]["vid"]) == chan.get(ass[b_]["vid"])]
    rels = sorted(by_song_vid)
    rng.shuffle(same)

    # ---- frames (one decode each, in a machine-wide slot)
    need = sorted({b["vid"] for b in balls} | {t["vid"] for t in titles} | {t["ref_vid"] for t in titles if t.get("ref_vid")}
                  | {ass[n]["vid"] for n in seedable[:args.seed_pool]}
                  | {ass[n]["vid"] for p in same[:args.seed_pool] for n in p}
                  | {ass[by_song_vid[r][0]]["vid"] for r in rels[:args.seed_pool]})
    frames, anchors = {}, {}
    with supervise.decode_slot():
        for vid in need:
            e = cert.get(vid) or {}
            if not e.get("t"):
                continue
            f = _frame(vid, e["t"])
            if f is None:
                continue
            a = _anchor(f, e.get("skin"))
            if a and a[0] >= 0.75:
                frames[vid], anchors[vid] = f, a
    print("frames: %d of %d videos anchored" % (len(frames), len(need)))

    def ball_img(vid, side):
        mx, loc, skin = anchors[vid]
        box = CROPS[skin]["ball"].get(side)
        return None if box is None else _crop(frames[vid], loc, box)

    def title_img(vid):
        mx, loc, skin = anchors[vid]
        return _crop(frames[vid], loc, CROPS[skin]["title"])

    out_root = os.path.abspath(os.path.join(args.out_root, args.batch))
    os.makedirs(out_root, exist_ok=True)
    key = dict(batch=args.batch, seed=args.seed, packets={}, skipped=[])

    def opaque():
        return "%012x" % rng.getrandbits(48)

    ball_items = []
    for b in balls:
        if b["vid"] not in frames:
            key["skipped"].append(dict(b, why="no anchored result frame"))
            continue
        img = ball_img(b["vid"], b["side"])
        if img is None:
            key["skipped"].append(dict(b, why="this skin shows no %s ball" % b["side"]))
            continue
        ball_items.append((b, img))
    ball_seeds = []
    for n in seedable:
        vid = ass[n]["vid"]
        if vid in frames and len(ball_seeds) < args.seed_pool:
            img = ball_img(vid, ass[n]["side"])
            if img is not None:
                ball_seeds.append((n, img))
    title_items = [(t, title_img(t["vid"]), title_img(t["ref_vid"])) for t in titles
                   if t.get("ref_vid") and t["vid"] in frames and t["ref_vid"] in frames]
    key["skipped"] += [dict(t, why="no reference or no frame") for t in titles
                       if not (t.get("ref_vid") and t["vid"] in frames and t["ref_vid"] in frames)]
    tseeds = []
    for a_, b_ in same:
        va, vb = ass[a_]["vid"], ass[b_]["vid"]
        if va in frames and vb in frames:
            tseeds.append(("SAME", (a_, b_), title_img(va), title_img(vb)))
    for i in range(0, len(rels) - 1, 2):
        a_, b_ = by_song_vid[rels[i]][0], by_song_vid[rels[i + 1]][0]
        va, vb = ass[a_]["vid"], ass[b_]["vid"]
        if va in frames and vb in frames:
            tseeds.append(("DIFFERENT", (a_, b_), title_img(va), title_img(vb)))
    rng.shuffle(tseeds)

    packets = []
    rng.shuffle(ball_items)
    per = args.images_per_packet - args.seeds_per_packet
    for i in range(0, len(ball_items), per):
        packets.append(("ball", ball_items[i:i + per]))
    # a title packet: two pairs to decide and two seed pairs, one SAME and one DIFFERENT (8 images)
    t_per = max(1, (args.images_per_packet - 4) // 2)
    for i in range(0, len(title_items), t_per):
        packets.append(("title", title_items[i:i + t_per]))
    tsame = [t for t in tseeds if t[0] == "SAME"]
    tdiff = [t for t in tseeds if t[0] == "DIFFERENT"]
    si = ti = 0
    for kind, items in packets:
        pid = "%s-%s" % (args.batch, opaque()[:8])
        pdir = os.path.join(out_root, pid)
        os.makedirs(pdir, exist_ok=True)
        q, kp = [], []
        entries = [("item", it) for it in items]
        if kind == "ball":
            for _ in range(args.seeds_per_packet):
                if ball_seeds:
                    entries.append(("seed", ball_seeds[si % len(ball_seeds)])); si += 1
        else:
            for pool in (tsame, tdiff):
                if pool:
                    entries.append(("seed", pool[ti % len(pool)]))
            ti += 1
        rng.shuffle(entries)
        for role, it in entries:
            iid = opaque()
            if kind == "ball":
                if role == "item":
                    meta, img = it
                else:
                    meta, img = dict(seed_chart=it[0], vid=ass[it[0]]["vid"], side=ass[it[0]]["side"],
                                     answer=ball_answer(it[0])), it[1]
                fn = opaque() + ".png"
                cv2.imwrite(os.path.join(pdir, fn), img)
                q.append(dict(item=iid, images=[fn], ask=BALL_ASK, answer_format=BALL_FORMAT))
                kp.append(dict(meta, item=iid, role=role, images=[fn]))
            else:
                if role == "item":
                    meta, ia, ib = it
                else:
                    ans, (a_, b_), ia, ib = it
                    meta = dict(seed_pair=[a_, b_], vids=[ass[a_]["vid"], ass[b_]["vid"]], answer=ans)
                fa, fb = opaque() + ".png", opaque() + ".png"
                cv2.imwrite(os.path.join(pdir, fa), ia)
                cv2.imwrite(os.path.join(pdir, fb), ib)
                q.append(dict(item=iid, images=[fa, fb], ask=TITLE_ASK, answer_format=TITLE_FORMAT))
                kp.append(dict(meta, item=iid, role=role, images=[fa, fb]))
        atomicio.write_json(os.path.join(pdir, "question.json"), dict(id=pid, instructions=INSTRUCTIONS, items=q), indent=1)
        key["packets"][pid] = dict(kind=kind, dir=pdir, items=kp)
    os.makedirs(os.path.dirname(os.path.abspath(args.keys)), exist_ok=True)
    atomicio.write_json(args.keys, key, indent=1, sort_keys=True, ensure_ascii=False)
    n_items = sum(1 for p in key["packets"].values() for i in p["items"] if i["role"] == "item")
    n_seeds = sum(1 for p in key["packets"].values() for i in p["items"] if i["role"] == "seed")
    print("%d packets (%d items, %d seeds) under %s; key %s; %d skipped" % (
        len(packets), n_items, n_seeds, out_root, args.keys, len(key["skipped"])))
    for pid, p in key["packets"].items():
        print("  %s %s %d items" % (pid, p["kind"], len(p["items"])))


# ---------------------------------------------------------------- the overlay, and what it is worth

OVERLAY_PURPOSE = (
    "Chart identity overlay (tools/identity.py): corrections to WHICH block of its song's .ssc a certified chart is "
    "(kind rekey), and to whether a video's side shows a chart at all (kind withdraw), from the extraction's "
    "column+time F1 against every same-width block of the song, checked against the certified result-screen total "
    "(count agreement), the eye-verified census ledger, or a blind read of the result screen's level ball. It never "
    "edits the chart map, the certification ledgers or the census: corpus_map applies it LAST, over their merge, and "
    "only once sources/oracle-manifest.json lists this file (the owner's freeze), so that the loops' populations and "
    "the corpus grade's change together. A rekey row applies only while the chart still maps to its from_key.")


def _slim(row):
    out = {k: v for k, v in row.items() if k not in ("evidence", "crosses", "waits_on")}
    ev = dict(row.get("evidence") or {})
    if "table" in ev:
        ev["table"] = ev["table"][:4]
    fp = ev.pop("fingerprint", None)
    if fp:
        ev["fingerprint"] = {n: {k: v for k, v in (d or {}).items() if k != "table"} for n, d in fp.items()}
    out["evidence"] = ev
    if row.get("crosses"):
        out["crosses"] = row["crosses"]
    return out


def _classes(row):
    ev = row.get("evidence") or {}
    out = []
    if "f1_best" in ev or ev.get("fingerprint"):
        out.append("extraction F1 (cached sprite pass, replayed)")
    if ev.get("count_agrees"):
        out.append("result-screen total (certification ledger)")
    if ev.get("census_verified"):
        out.append("census ledger (eye-verified)")
    if ev.get("catalog"):
        out.append("Phoenix 1 catalog row (chartId)")
    if ev.get("ball"):
        out.append("blind level-ball read")
    return out


def cmd_overlay(args):
    rep = json.load(open(args.report, encoding="utf-8"))
    rows = [_slim(r) for r in rep.get("rekey", [])] + [_slim(r) for r in rep.get("withdraw", [])]
    for extra in args.extra or []:
        rows += [_slim(r) for r in json.load(open(extra, encoding="utf-8")).get("rows", [])]
    rows.sort(key=lambda r: (r["kind"], r["chart"], r.get("vid", "")))
    doc = dict(purpose=OVERLAY_PURPOSE, date=args.date, tool="tools/identity.py", code=rep.get("code"),
               rule=dict(best_f1=BEST_F1, margin=MARGIN,
                         rekey="best block F1 >= best_f1, by >= margin over the mapped block and the runner-up (blocks "
                               "with identical note events are one block), and the block converts to the certified "
                               "total or a blind level-ball read agrees; never a census chart, a round-hundred total, "
                               "a total two catalog charts of the song carry, or a target another chart keeps",
                         withdraw="one side certifies two charts: the census ledger (eye-verified) names one, or the "
                                  "pad's notes are one name's block by the rekey rule's margin and it converts to the "
                                  "total, or a blind ball read picks one"),
               evidence_classes=sorted({c for r in rows for c in _classes(r)}),
               rows=rows)
    atomicio.write_json(args.out, doc, indent=1, sort_keys=True, ensure_ascii=False)
    print("wrote %s: %d rows (%s)" % (args.out, len(rows), ", ".join(
        "%s %d" % (k, sum(1 for r in rows if r["kind"] == k)) for k in ("rekey", "withdraw"))))


def cmd_grade_delta(args):
    """The corpus grade with and without an overlay, both under the pinned converter and the
    working tree's oracle: what the overlay is worth as ORACLE GROWTH (not repairs - no block
    changes). corpus_grade reads no overlay today, so its Oracle is built as the grade builds it and
    the overlay applied to the copy, the way the staged corpus_grade change would."""
    import corpus_grade as CG
    pin = CG.converter_pin()
    tree = CG.Tree(None)
    base = CG.Oracle(tree)
    CG.check_manifest(base, pin)
    head = CG.Oracle(tree)
    ov = [(args.overlay_rel, json.load(open(args.overlay, encoding="utf-8")))]
    head.cert = corpus_map.overlay_certification(head.cert, ov)
    head.smap = corpus_map.overlay_chart_map(head.smap, ov)
    head.population = corpus_map.certified_charts(head.cert, head.smap,
                                                  CG._json(tree.read_oracle("sources/tail-2026-09-08.json"), {}),
                                                  CG._json(tree.read_oracle("sources/census-final.json"), []))
    ns = argparse.Namespace(workers=args.workers, cache_dir=CG.DEFAULT_CACHE, no_cache=False, stall_timeout=600)
    g = CG.Grader(ns, pin)
    rows0, imp0 = g.grade(tree, base)
    rows1, imp1 = g.grade(tree, head)
    conf1 = CG.build_conflicts(head, rows1, tree)
    conf1_names = {c["chart"] for c in conf1["charts"]}
    s0, s1 = CG.summarize(rows0, imp0), CG.summarize(rows1, imp1)
    keep = ("key", "vid", "side", "expected", "implied", "exact", "tier")
    trans = []
    for n in sorted(set(rows0) | set(rows1)):
        a, b = rows0.get(n), rows1.get(n)
        if a is None or b is None or any(a.get(k) != b.get(k) for k in ("exact", "key", "vid", "tier")):
            trans.append(dict(chart=n, before=a and {k: a.get(k) for k in keep}, after=b and {k: b.get(k) for k in keep},
                              oracle_conflict_before=n in base.conflict, oracle_conflict_rebuilt=n in conf1_names))
    out = dict(tool="identity grade-delta", overlay=os.path.abspath(args.overlay), converter_pin=pin["pin"],
               oracle_hash=base.hash, before=s0, after=s1,
               growth=dict(exact=s1["exact"] - s0["exact"], protected=s1["protected"] - s0["protected"],
                           provisional=s1["provisional"] - s0["provisional"], certified=s1["certified"] - s0["certified"]),
               transitions=trans,
               conflicts_rebuilt=dict(charts=len(conf1["charts"]), videos=len(conf1["videos"]),
                                      exact=sorted(n for n in conf1_names if rows1.get(n, {}).get("exact")), doc=conf1))
    atomicio.write_json(args.out, out, indent=1, sort_keys=True, ensure_ascii=False)
    for label, s in (("before", s0), ("after ", s1)):
        print("%s: %d certified, %d exact (%d PROTECTED, %d PROVISIONAL)" % (
            label, s["certified"], s["exact"], s["protected"], s["provisional"]))
    gr = out["growth"]
    print("ORACLE GROWTH: %+d exact (%+d PROTECTED, %+d PROVISIONAL), %+d certified" % (
        gr["exact"], gr["protected"], gr["provisional"], gr["certified"]))

    def say(r):
        if not r:
            return "(not in the population)"
        return "%s %s/%s %s" % (guards.tag_of(r["key"]), r["implied"], r["expected"], r["tier"] or "-")
    for t in trans:
        print("  %-42s %s -> %s%s" % (t["chart"][:42], say(t["before"]), say(t["after"]),
                                      "  [ORACLE_CONFLICT after a rebuild]" if t["oracle_conflict_rebuilt"] else ""))
    print("conflicts rebuilt under the overlay: %d charts, %d videos; exact among them: %s" % (
        len(conf1["charts"]), len(conf1["videos"]), ", ".join(out["conflicts_rebuilt"]["exact"]) or "none"))
    print("wrote " + args.out)


def cmd_selfcheck(args):
    """The vectorized anchor against quantize.anchor_offset, and align() against extract_repair's,
    on random (pass, block) pairs: the same offset, the same hit count, the same fitted clock."""
    import extract_repair as X
    import quantize as Q
    cert, smap = corpus_map.certification(overlays=[]), corpus_map.chart_map(overlays=[])
    rng = random.Random(args.seed)
    names = sorted(f for f in os.listdir(PASS_DIR) if _CURRENT.search(f))
    rng.shuffle(names)
    n = bad = 0
    t_orig = t_fast = 0.0
    for p in names:
        if n >= args.pairs:
            break
        info = parse_pass(p)
        rels = songs_for(info["vid"], cert, smap) if info else []
        if not rels:
            continue
        notes, _ = replay(os.path.join(PASS_DIR, p), info["ncols"], info["scale"])
        csha, blocks = song_blocks(rels[0], X)
        blocks = [b for b in blocks if not b.get("unreachable") and not b.get("error") and b["ncols"] == info["ncols"]]
        for b in rng.sample(blocks, min(2, len(blocks))):
            fc = {c: [x[0] for x in v] for c, v in b["fnotes"].items()}
            t0 = time.time()
            o1 = Q.anchor_offset(notes, fc, info["ncols"])
            a1 = X.align(notes, b["fnotes"], info["ncols"])
            t1 = time.time()
            o2 = anchor_offset(notes, fc, info["ncols"])
            a2 = align(notes, b["fnotes"], info["ncols"], X)
            t2 = time.time()
            t_orig += t1 - t0
            t_fast += t2 - t1
            n += 1
            same = o1 == o2 and a1 == a2
            bad += not same
            print("%s %-30s %s" % (p[:11], b["tag"][:30], "same" if same else "DIFF %r %r" % ((o1, a1), (o2, a2))), flush=True)
    print("VERDICT: %s" % ("OK" if n and not bad else "FAIL"))
    print("%d pairs, %d differ; original %.1fs, vectorized %.1fs" % (n, bad, t_orig, t_fast))
    sys.exit(0 if n and not bad else 1)


def cmd_owner_list(args):
    """The rows the rule may not settle on its own, one line of reason each, for the owner: round-hundred
    totals, totals more than one catalog chart of the song carries, anything that would contradict an
    eye-verified census row, a target another chart keeps, a side whose notes match none of its names."""
    rep = json.load(open(args.report, encoding="utf-8"))
    items = []
    for o in rep.get("owner", []):
        row = o.get("row") or {}
        ev = row.get("evidence") or {}
        items.append(dict(chart=o["chart"], reason=o["reason"], vid=row.get("vid"), side=row.get("side"),
                          proposed=dict(kind=row.get("kind"), from_tag=guards.tag_of(row["from_key"]) if row.get("from_key") else None,
                                        to_tag=row.get("to_tag"), to_key=row.get("to_key")),
                          evidence={k: ev.get(k) for k in ("f1_best", "f1_mapped", "f1_runner", "to_implied", "count_agrees",
                                                           "catalog", "table", "winner", "margin") if k in ev}))
    # exact by count, but the notes match another block by the margin: the count vetoed a re-key, and
    # whether the certified total is a coincidence is the owner's to judge
    for n, a in sorted(rep["assessments"].items()):
        if a.get("status") == "exact-notes-disagree" and (a.get("best_f1") or 0) - (a.get("mapped_f1") or 0) >= MARGIN:
            items.append(dict(chart=n, vid=a.get("vid"), side=a.get("side"),
                              reason="exact at its mapped block (%s, %s notes) but the pad's notes match %s at F1 %.3f "
                                     "against %.3f: the count vetoed a re-key%s" % (
                                         a.get("mapped_tag"), a.get("expected"), "/".join(a.get("best_tags") or []),
                                         a["best_f1"], a.get("mapped_f1") or 0,
                                         "; round-hundred total" if a.get("expected") and int(a["expected"]) % 100 == 0 else ""),
                              proposed=None, evidence=dict(table=a.get("table"), pass_name=a.get("pass_name"))))
    for extra in args.extra_items or []:
        items += json.load(open(extra, encoding="utf-8")).get("items", [])
    doc = dict(bucket="#2 chart identity (loops/identity-1)", date=args.date, report=os.path.abspath(args.report),
               items=items, staged=[dict(what=s.split("::", 1)[0], detail=s.split("::", 1)[1]) for s in (args.staged or [])])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    atomicio.write_json(args.out, doc, indent=1, sort_keys=True, ensure_ascii=False)
    print("wrote %s: %d items, %d staged" % (args.out, len(items), len(doc["staged"])))
    if args.conflicts_out:
        # ORACLE_CONFLICT additions, proposed: a certified chart that is not exact and whose pad's notes
        # match ANOTHER block of its file far better than its own (a re-key waiting on a ball read or the
        # owner), or match two blocks alike, is not a chart any loop should make exact by editing its
        # mapped block - that is re-ticking the wrong block. In the conflict set the gate halts instead.
        conflict = {c["chart"] for c in corpus_map._load(os.path.join(ROOT, "sources", "oracle-conflict.json"), {}).get("charts", [])}
        grade = {r["chart"]: r for r in corpus_map._load(os.path.join(ROOT, "sources", "corpus-grade.json"), {}).get("charts", [])}
        settled = {r["chart"] for r in rep.get("rekey", [])} | {r["chart"] for r in rep.get("withdraw", [])}
        charts = []
        for n, a in sorted(rep["assessments"].items()):
            if n in conflict or n in settled or grade.get(n, {}).get("exact"):
                continue
            if a.get("status") in ("candidate", "ambiguous", "passes-disagree"):
                detail = ("the pad's notes (%s) match %s at F1 %.3f against the mapped %s at %s; runner-up %.3f" % (
                    a.get("pass_name", "")[:11], "/".join(a.get("best_tags") or []), a.get("best_f1") or 0, a.get("mapped_tag"),
                    "%.3f" % a["mapped_f1"] if a.get("mapped_f1") is not None else "-", a.get("runner_f1") or 0))
                charts.append(dict(chart=n, in_population=True, reasons=[dict(kind="identity", detail=detail,
                                                                             status=a["status"])]))
        prop = dict(purpose="PROPOSED additions to sources/oracle-conflict.json (loop bucket #2, tools/identity.py): certified "
                            "charts, not exact, whose pad's notes match another block of their file far better than their "
                            "mapped block, or two blocks alike. Not read by the gate: the owner folds them into "
                            "sources/oracle-conflict.json (owner-only) and refreezes, after which a loop that makes one "
                            "exact by editing its mapped block halts for review instead of taking the credit.",
                    rule=dict(identity="not exact; the pad's extraction matches another block at F1 >= %.1f by >= %.1f over the "
                                       "mapped block (candidate), or its best two blocks lie within %.1f (ambiguous), or two "
                                       "cached passes of the pad disagree on the best block" % (BEST_F1, MARGIN, MARGIN)),
                    date=args.date, report=os.path.abspath(args.report), charts=charts)
        atomicio.write_json(args.conflicts_out, prop, indent=1, sort_keys=True, ensure_ascii=False)
        print("wrote %s: %d proposed ORACLE_CONFLICT additions" % (args.conflicts_out, len(charts)))


def cmd_jobs(args):
    """A supervise.py jobs file over every cached pass: shards grouped by song, so a shard converts
    each song's blocks once. No job decodes, so none takes a decode slot."""
    cert, smap = corpus_map.certification(overlays=[]), corpus_map.chart_map(overlays=[])
    names = sorted(f for f in os.listdir(PASS_DIR) if f.endswith(".pkl"))
    by_song = defaultdict(list)
    for n in names:
        info = parse_pass(n)
        rels = songs_for(info["vid"], cert, smap) if info else []
        by_song[rels[0] if rels else ""].append(n)
    list_dir = os.path.abspath(args.list_dir)
    os.makedirs(list_dir, exist_ok=True)
    shards, cur = [], []
    for rel in sorted(by_song):
        cur += by_song[rel]
        if len(cur) >= args.shard_size:
            shards.append(cur); cur = []
    if cur:
        shards.append(cur)
    lines = []
    for i, sh in enumerate(shards):
        lp = os.path.join(list_dir, "fp-%03d.txt" % i)
        atomicio.write_text(lp, "\n".join(sh) + "\n")
        lines.append(json.dumps(dict(id="fp-%03d" % i, cmd=["{py}", "{tools}/identity.py", "fingerprint", "@" + lp,
                                                             "--out-dir", os.path.abspath(args.out_dir)],
                                     slot=False, timeout=3600, meta=dict(passes=len(sh)))))
    atomicio.write_text(args.jobs, "\n".join(lines) + "\n")
    print("%d passes in %d shards over %d songs -> %s" % (len(names), len(shards), len(by_song), args.jobs))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fingerprint")
    f.add_argument("passes", nargs="+", help="pass file names, or @<list file>")
    f.add_argument("--out-dir", default=FP_DIR)
    f.add_argument("--force", action="store_true")
    d = sub.add_parser("decide")
    d.add_argument("--out", required=True)
    d.add_argument("--fp-dir", default=FP_DIR)
    d.add_argument("--seed", type=int, default=20260927)
    d.add_argument("--controls", type=int, default=25)
    d.add_argument("--swaps", type=int, default=20)
    d.add_argument("--any-code", action="store_true", help="read fingerprints of any code stamp (testing)")
    k = sub.add_parser("packets")
    k.add_argument("--report", required=True)
    k.add_argument("--batch", required=True)
    k.add_argument("--out-root", required=True)
    k.add_argument("--keys", required=True)
    k.add_argument("--extra-videos", default="")
    k.add_argument("--seed", type=int, default=926)
    k.add_argument("--seed-pool", type=int, default=24)
    k.add_argument("--unmatched-below", type=float, default=0.5,
                   help="also read the ball and title of certified sides whose best F1 is under this")
    k.add_argument("--images-per-packet", type=int, default=8)
    k.add_argument("--seeds-per-packet", type=int, default=2)
    o = sub.add_parser("overlay")
    o.add_argument("--report", required=True)
    o.add_argument("--out", required=True)
    o.add_argument("--extra", action="append", help="a JSON {rows: [...]} of rows settled since (ball reads)")
    o.add_argument("--date", default="2026-09-27")
    gd = sub.add_parser("grade-delta")
    gd.add_argument("--overlay", required=True)
    gd.add_argument("--overlay-rel", default=corpus_map.IDENTITY_OVERLAYS[0])
    gd.add_argument("--out", required=True)
    gd.add_argument("--workers", type=int, default=4)
    sc = sub.add_parser("selfcheck")
    sc.add_argument("--pairs", type=int, default=20)
    sc.add_argument("--seed", type=int, default=7)
    ol = sub.add_parser("owner-list")
    ol.add_argument("--report", required=True)
    ol.add_argument("--out", required=True)
    ol.add_argument("--date", default="2026-09-27")
    ol.add_argument("--staged", action="append", help="'<what>::<detail>' of something staged for the owner")
    ol.add_argument("--conflicts-out", help="write the proposed ORACLE_CONFLICT additions here")
    ol.add_argument("--extra-items", action="append", help="a JSON {items: [...]} of further owner items")
    j = sub.add_parser("jobs")
    j.add_argument("jobs")
    j.add_argument("--list-dir", required=True)
    j.add_argument("--out-dir", default=FP_DIR)
    j.add_argument("--shard-size", type=int, default=20)
    args = ap.parse_args()
    {"fingerprint": cmd_fingerprint, "jobs": cmd_jobs, "decide": cmd_decide, "packets": cmd_packets,
     "overlay": cmd_overlay, "grade-delta": cmd_grade_delta, "selfcheck": cmd_selfcheck,
     "owner-list": cmd_owner_list}[args.cmd](args)


if __name__ == "__main__":
    main()
