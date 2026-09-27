# The extractor replay bench: grade a change to note_extract's post-decode step from the cached
# sprite passes alone, against a benchmark frozen before anyone looked, so a tuning loop can claim
# an extractor gain honestly (work/loop-buckets-2026-09-26.txt, bucket #5).
#
# WHAT IT REPLAYS. note_extract._read decodes a video once into a sprite pass and hands it to
# post_decode(): the floor the receptor flashes vouch for, the notes at it, the holds. The pass is
# cached (work/spritepass, 1,413 of them, ~7 hours of decoding), and post_decode is the ONE copy of
# that step - production and this bench call the same function, so a candidate graded here is the
# code that ships. Nothing is ever decoded: every frame read is refused (a missing pass is a FAIL
# that scores zero, never a silent decode), and nothing is written outside work/bench.
#
# WHAT IT GRADES AGAINST. Truth is a file that already derives the certified count (count-exact
# under the pinned converter) and whose block and song header are byte-identical to the import
# a23cee5 - untouched by any commit of ours, so no extractor- or footage-derived edit can be
# graded as its own truth. Exact charts our commits edited are a separate stratum ("repo-edited"),
# reported and never gated; so are the lane misfits (a field fit whose lane pitch is under 70 px,
# 36 charts, until bucket #4 refits them) - and the quarantined charts, owner-revisit charts and
# corrupt footage are out entirely. A certified play whose count cannot tell its block from a
# sibling (another block of the song deriving the same total, or an ORACLE_CONFLICT) is flagged
# identity_pending - bucket #2's identity verification is what would clear it.
#
# THE MANIFEST (sources/benchmark/manifest-<v>.json) pins, per chart, the block and header sha,
# the certified count, the footage (video, band, side, columns, duration), the sprite pass file and
# its sha256, and the floors the pass is cut at, plus the converter pin and the oracle hash; its
# three-way split (tune / validate / sealed) is by component - charts joined by title family, by
# video and by song file - so no song is on both sides, and every chart named in the docs or the
# code, every sentinel and every canary is tune-only. It is hashed and chained into
# sources/runs.jsonl before any baseline is recorded.
#
# THE GATE (sources/benchmark/gate-<v>.json) is fixed with the manifest. A held-out look is one
# `grade --split validate` of a registered candidate: logged in sources/runs.jsonl (hash-chained,
# keyed by the candidate's diff hash), capped at 20 per split and 3 per rule family, 40 candidates
# in all. The sealed split is opened once, at the stop.
#
#   python -X utf8 -B tools/bench.py identity --against <rev> [--shard i/n] [--limit N]
#   python -X utf8 -B tools/bench.py identity-summary --against <rev>
#   python -X utf8 -B tools/bench.py freeze [--version v1] [--salt S] [--workers N] [--dry-run]
#   python -X utf8 -B tools/bench.py replay --rule R [--set tune,validate,...] [--shard i/n] [--workers N]
#   python -X utf8 -B tools/bench.py register --rule R
#   python -X utf8 -B tools/bench.py grade --rule R --split tune|validate|sealed [--json F]
#   python -X utf8 -B tools/bench.py baseline [--json F]
#   python -X utf8 -B tools/bench.py chain
#   python -X utf8 -B tools/bench.py canary-fit --vid V / canary-select / canary-decode --vid V / canary-freeze
import argparse
import ast
import bisect
import contextlib
import gzip
import hashlib
import importlib.util
import json
import os
import pickle
import random
import re
import subprocess
import sys
import time
import unicodedata
from collections import Counter, defaultdict

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import numpy as np  # noqa: E402

import atomicio as A          # noqa: E402
import bench_rules as BR      # noqa: E402
import corpus_map             # noqa: E402
import extract_repair as X    # noqa: E402  (puts piu-annotate on the path; refuses a converter without the lattice)
import guards as G            # noqa: E402
import note_extract as NX     # noqa: E402
import quantize as Q          # noqa: E402
import receptors as R         # noqa: E402
from cachekey import code_stamp  # noqa: E402

BENCH_DIR = os.path.join(ROOT, "sources", "benchmark")
RUNS_LEDGER = os.path.join(ROOT, "sources", "runs.jsonl")
CACHE = os.path.join(ROOT, "work", "bench")
IMPORT_REV = "a23cee5"
BENCH = "extractor-replay"
TOLS = (0.030, 0.045, 0.060)
JACK_GAP = 0.25          # s: two notes in one column this close, the first a tap, are a jack
SHORT_HOLD = 0.25        # s: a hold this short is a short hold
PIN_TOL = 0.060          # s: a tail the count pins within this, both ways, is graded
MISFIT_PITCH = 70.0      # px: a field fit's lane pitch under this is a lane misfit (bucket #4's 36)
N_SENTINEL = 15          # charts in each density-ranked sentinel set
# Charts the proposal named as sentinels (work/loop-buckets-2026-09-26.txt and the 2026-09-26 research
# b3/gap_rule.py): jack-dense ones, and extracted notes the combo counter backs as real where the
# file lacks them (b3/sentinels.json: a +1/+2 step in the counter at the tap).
NAMED_JACK = ("Pumptris Quattro S18", "A Site De La Rue D24", "Xeroize S21", "Beat of The War 2 S21", "Moonlight D20",
              "Overblow S20", "WHISPER S19", "WHISPER D21")
BACKED = (("Betrayer S9", 80.703, 1), ("Get Up! D15", 7.839, 3),
          ("K.O.A \\: Alice in Wonderworld - SHORT CUT - S16", 15.091, 0), ("Phantom S18", 45.766, 2),
          ("Vook S10", 31.792, 1), ("Vook S10", 83.966, 1), ("Vook S10", 32.282, 4),
          ("We will meet again S13", 38.543, 2), ("We will meet again S13", 31.921, 3))
DOC_GLOBS = ("docs", "README.md", "CLAUDE.md", "tools", "work/loop-buckets-2026-09-26.txt")


def die(msg, code=2):
    print("bench: " + msg, file=sys.stderr)
    sys.exit(code)


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=repr)


def digest(obj, n=64):
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()[:n]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if check and r.returncode != 0:
        die("git %s: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()[:300]))
    return r


def git_show(rev, path):
    r = git("show", "%s:%s" % (rev, path), check=False)
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else None


def rev_parse(rev):
    return git("rev-parse", rev).stdout.decode().strip()


def shard_of(items, spec):
    if not spec:
        return items
    i, n = (int(x) for x in spec.split("/"))
    return items[i::n]


def write_gz_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    A.write_bytes(path, gzip.compress(canon(obj).encode("utf-8"), mtime=0))


def read_gz_json(path):
    try:
        with open(path, "rb") as f:
            return json.loads(gzip.decompress(f.read()).decode("utf-8"))
    except (OSError, ValueError, EOFError):
        return None


# ---------------------------------------------------------------- nothing decoded, nothing written

class DecodeRefused(RuntimeError):
    """A frame read inside the bench: the pass it needed is not cached."""


_REAL_CAPTURE = []


class _NoFrames:
    """cv2.VideoCapture with every frame read refused: opening a video and asking its size is not a
    decode, reading a frame is (tools/trace_audit.py's frames_off, the same device)."""
    def __init__(self, *args, **kwargs):
        self._cap = _REAL_CAPTURE[0](*args, **kwargs)

    def read(self, *args, **kwargs):
        raise DecodeRefused("the bench decodes nothing: a frame read was refused")

    grab = retrieve = read

    def __getattr__(self, name):
        return getattr(self._cap, name)


def no_decode():
    """For the rest of this process, every frame read raises DecodeRefused."""
    import cv2
    if not _REAL_CAPTURE:
        _REAL_CAPTURE.append(cv2.VideoCapture)
    cv2.VideoCapture = _NoFrames


def read_only(*allow):
    """For the rest of this process, refuse every write outside work/bench and `allow`."""
    A.forbid_writes([CACHE] + list(allow))


_REAL_ONSETS = R.onsets


def _onsets_cached(sc, thresh=40.0):
    """receptors.onsets, cached by the content of the scan it reads (its frame times and receptor
    levels), the threshold and the function's own code stamp. It is two thirds of post_decode's time
    (a rolling percentile per frame per column) and a pure function of the pass, so a replay that
    does not change the scan computes it once per pass. Values round-trip exactly (JSON floats);
    `identity` proves it - its reference side computes, ours reads."""
    ts, arr = np.ascontiguousarray(sc["ts"]), np.ascontiguousarray(sc["flash"])
    h = hashlib.sha256(repr((ts.dtype.str, ts.shape, arr.dtype.str, arr.shape, float(thresh))).encode())
    h.update(ts.tobytes())
    h.update(arr.tobytes())
    key = h.hexdigest()[:24] + "." + code_stamp(_REAL_ONSETS)
    path = os.path.join(CACHE, "onsets", key[:2], key + ".json.gz")
    got = read_gz_json(path)
    if got is not None:
        return {int(c): got["out"][c] for c in sorted(got["out"], key=int)}, np.array(got["heights"], dtype=float)
    out, heights = _REAL_ONSETS(sc, thresh)
    write_gz_json(path, dict(out={str(c): v for c, v in out.items()}, heights=[float(x) for x in heights]))
    return out, heights


def cache_onsets():
    R.onsets = _onsets_cached


_REAL_ANCHOR = Q.anchor_offset


def fast_anchor_offset(notes, fnotes, ncols, lo=0.0, hi=60.0, tol=0.08):
    """quantize.anchor_offset, the same arithmetic over every offset at once: for each offset a, each
    extracted note's t - a is looked up with bisect_left against its column's file times at t - tol,
    and hits only that first candidate within tol (not the nearest - exactly as the original); the
    score is (hits, -median error), the first strict maximum in scan order winning, over the 0.01 s
    grid on [lo, hi) and then the 1 ms grid around it. Pure Python it is ~6,000 x notes bisects and
    most of a baseline replay's time; `verify-anchor` checks the two agree exactly."""
    cols = [(np.asarray(fnotes.get(c, []), dtype=float), np.array([n["t"] for n in notes if n["col"] == c], dtype=float))
            for c in range(ncols)]
    cols = [(f, t) for f, t in cols if len(f) and len(t)]

    def scan(offs):
        offs = np.asarray(offs, dtype=float)
        errs = []
        for f, t in cols:
            tt = t[None, :] - offs[:, None]
            j = np.searchsorted(f, tt - tol, side="left")
            ok = j < len(f)
            e = np.abs(f[np.minimum(j, len(f) - 1)] - tt)
            errs.append(np.where(ok & (e <= tol), e, np.inf))
        if not errs:
            return np.zeros(len(offs), dtype=int), np.full(len(offs), 9.9)
        e = np.concatenate(errs, axis=1)
        hits = np.isfinite(e).sum(axis=1)
        e.sort(axis=1)
        med = np.full(len(offs), 9.9)
        for i in np.nonzero(hits)[0]:
            h = int(hits[i])
            med[i] = float(np.median(e[i, :h]))
        return hits, med

    best = (0, 9.9, lo)
    offs = [k / 100.0 for k in range(int(lo * 100), int(hi * 100))]
    for i0 in range(0, len(offs), 400):
        chunk = offs[i0:i0 + 400]
        hits, med = scan(chunk)
        for a, h, m in zip(chunk, hits, med):
            if (int(h), -float(m)) > (best[0], -best[1]):
                best = (int(h), float(m), a)
    # sequentially, as the original: each fine offset is taken from the best AS IT STANDS, which an
    # earlier step of this same loop may have moved
    for k in range(-30, 31):
        a = best[2] + k / 1000.0
        hits, med = scan([a])
        if (int(hits[0]), -float(med[0])) > (best[0], -best[1]):
            best = (int(hits[0]), float(med[0]), a)
    return best[2], best[0]


def fast_anchor():
    Q.anchor_offset = fast_anchor_offset


# ---------------------------------------------------------------- stamps: what a cached record depends on

def extractor_stamp():
    """The post-decode step as it stands: its code and the constants it reads."""
    return code_stamp(NX.post_decode, NX._clean, NX._cand, NX.track, NX.notes_from_tracks, NX.flash_agreement,
                      NX.at_floor, NX.colour_floor, NX.mark_holds, _REAL_ONSETS, R.rails) + ":" + digest(
        dict(FLOORS=NX.FLOORS, TIE=NX.TIE, MERGE=NX.MERGE, MIN_TRACK=NX.MIN_TRACK, TOP=NX.TOP), 12)


def scorer_stamp():
    return code_stamp(X.align, X.match, X.plan, X.file_events, X.clocks, X.snap, X.flashed, Q.anchor_offset,
                      replay_chart, post_decoded, compact, prod_stats, truth_of, pinned_holds, fast_anchor_offset)


def truth_stamp():
    return code_stamp(truth_of, pinned_holds, X.load_block, X.file_events)


# ---------------------------------------------------------------- identity: post_decode against a reference revision

LEGACY_PASS = re.compile(r"^(?P<vid>.+)\.(?P<band>[LCR])\.(?P<side>[12]p)\.(?P<ncols>\d+)\.0\.50\.0\.50\.50\.h0\.00\.r0\.00"
                         r"\.s(?P<s>\d\.\d\d)\.(?P<dur>\d+\.\d)\.x(?P<x0>\d+)-(?P<x1>\d+)(?P<ref>\.ref)?\.pkl$")


def load_reference(rev):
    """tools/note_extract.py as it stands at `rev`, imported as a module of its own (the same
    receptors / sprites / atomicio objects as ours, so a stub on them applies to both), plus its
    post-decode step as a function: the statements of its _read from the first that reads the
    receptor flashes (R.onsets) to the end, compiled verbatim - mechanically cut, never retyped."""
    src = git_show(rev, "tools/note_extract.py")
    if src is None:
        die("tools/note_extract.py is not at %s" % rev)
    tag = hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]
    path = os.path.join(CACHE, "ref", "note_extract_%s.py" % tag)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        A.write_bytes(path, src.encode("utf-8"))
    saved = list(sys.path)
    spec = importlib.util.spec_from_file_location("nx_ref_" + tag, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.path[:] = saved
    mod.ROOT = NX.ROOT
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_read")
    lines = src.splitlines()
    k = next(st for st in fn.body if "R.onsets" in (ast.get_source_segment(src, st) or ""))
    body = "\n".join(lines[k.lineno - 1:fn.end_lineno])
    code = ("def _bench_post(ts, scored, fps, y0, y1, scan, floors, ncols, vid, band, side, sharp, quiet):\n" + body + "\n")
    exec(compile(code, "<%s:tools/note_extract.py _read, post-decode>" % rev, "exec"), mod.__dict__)
    return mod, tag


def outcome_digest(fn):
    """What a call returned (both a pickle and a canonical JSON of it), or the exception it raised."""
    try:
        out = fn()
    except DecodeRefused:
        raise
    except Exception as ex:
        return dict(raised="%s: %s" % (type(ex).__name__, str(ex)[:300]))
    return dict(pickle=hashlib.sha256(pickle.dumps(out, protocol=4)).hexdigest(),
                json=hashlib.sha256(canon(out).encode("utf-8")).hexdigest(),
                notes=len(out[0]), floor=out[1].get("floor"))


def ours_tag():
    """Which note_extract.py a proof is of: the sha256 of this checkout's file, as bytes."""
    return hashlib.sha256(open(os.path.join(TOOLS, "note_extract.py"), "rb").read()).hexdigest()[:12]


def cmd_identity(args):
    """Every cached pass through the reference revision's post-decode step and ours: byte-identical
    output, or the same exception. First the whole read (`_read`, which must load exactly this pass
    - proving the pass lookup too), and where the pass no longer resolves from today's caches, the
    step alone on the pass with the floors its name records."""
    no_decode()
    read_only()
    cache_onsets()
    ref, tag = load_reference(args.against)
    for M in (ref, NX):
        M.CACHE = True
    R.geometry = lambda *a, **k: (None, None, None)     # a read's side effect (sharing its scan), never its output
    R.save_scan = lambda *a, **k: None
    loaded = []
    real_load = A.load_pickle

    def spy(path, *a, **k):
        loaded.append(os.path.normcase(os.path.abspath(path)))
        return real_load(path, *a, **k)
    A.load_pickle = spy
    files = sorted(f for f in os.listdir(os.path.join(ROOT, "work", "spritepass")) if f.endswith(".pkl"))
    if args.stale:
        files = [f for f in files if not LEGACY_PASS.match(f)]
    files = shard_of(shard_of(files, args.shard), args.subshard)[:args.limit or None]
    out, t0 = [], time.time()
    for f in files:
        rec = dict(pass_file=f)
        m = LEGACY_PASS.match(f)
        full = os.path.normcase(os.path.join(ROOT, "work", "spritepass", f))
        if not m and args.stale:
            # a pass in an older key format (fsck's "stale key format"): no read resolves to it any
            # more, but it is a cached pass all the same - the step alone, on the columns its name
            # gives and the unscaled floors (the comparison needs the same inputs, not the original ones)
            tok = f[:-4].split(".")
            ncols = next((int(t) for t in tok[2:] if t in ("5", "10")), None)
            got = real_load(os.path.join(ROOT, "work", "spritepass", f))
            if ncols is None or not (isinstance(got, tuple) and len(got) == 6):
                rec.update(mode="skip", why="stale name without columns, or not a sprite pass")
                out.append(rec)
                continue
            ts, scored, fps, y0, y1, scan = got
            floors = list(NX.FLOORS)
            vid, band = tok[0], tok[1]
            a = outcome_digest(lambda: ref._bench_post(ts, scored, fps, y0, y1, pickle.loads(pickle.dumps(scan)), floors,
                                                       ncols, vid, band, None, None, True))
            b = outcome_digest(lambda: NX.post_decode(ts, scored, fps, y0, y1, pickle.loads(pickle.dumps(scan)), floors,
                                                      ncols, vid=vid, band=band, side=None, sharp=None, quiet=True))
            rec.update(mode="step-stale", vid=vid, band=band, ncols=ncols, ref=a, new=b, same=a == b)
            out.append(rec)
            continue
        if not m:
            rec.update(mode="skip", why="not a legacy pass name")
            out.append(rec)
            continue
        vid, band, side, ncols, dur = m["vid"], m["band"], m["side"], int(m["ncols"]), float(m["dur"])
        rec.update(vid=vid, band=band, side=side, ncols=ncols)
        try:
            del loaded[:]
            a = outcome_digest(lambda: ref._read(vid, band, ncols, side, dur, True))
            la = list(loaded)
            del loaded[:]
            b = outcome_digest(lambda: NX._read(vid, band, ncols, side, dur, True))
            lb = list(loaded)
            if la == lb == [full]:
                rec.update(mode="read", ref=a, new=b, same=a == b)
                out.append(rec)
                continue
            rec["read_loaded"] = [os.path.basename(p) for p in (la or lb)]
        except DecodeRefused:
            rec["read_loaded"] = "decode refused: the pass does not resolve from today's caches"
        got = real_load(os.path.join(ROOT, "work", "spritepass", f))
        if not (isinstance(got, tuple) and len(got) == 6):
            rec.update(mode="skip", why="not a sprite pass")
            out.append(rec)
            continue
        ts, scored, fps, y0, y1, scan = got
        s = float(m["s"])
        floors = [round(x * s, 3) for x in NX.FLOORS]
        # each side gets its own copy: post_decode marks holds on the notes it builds, and a pass's
        # scan dict is read, never written - but the comparison must not depend on that
        a = outcome_digest(lambda: ref._bench_post(ts, scored, fps, y0, y1, pickle.loads(pickle.dumps(scan)), floors,
                                                   ncols, vid, band, side, None, True))
        b = outcome_digest(lambda: NX.post_decode(ts, scored, fps, y0, y1, pickle.loads(pickle.dumps(scan)), floors,
                                                  ncols, vid=vid, band=band, side=side, sharp=None, quiet=True))
        rec.update(mode="step", ref=a, new=b, same=a == b)
        out.append(rec)
    dest = os.path.join(CACHE, "identity", tag, ours_tag(), "%s%s%s.jsonl" % (
        "stale-" if args.stale else "", (args.shard or "all").replace("/", "of"),
        ("-" + args.subshard.replace("/", "of")) if args.subshard else ""))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    A.write_text(dest, "".join(json.dumps(r, sort_keys=True) + "\n" for r in out))
    n_same = sum(1 for r in out if r.get("same"))
    print("identity vs %s (%s): %d passes, %d identical, %d different, %d skipped, %.0f s -> %s" % (
        args.against, tag, len(out), n_same, sum(1 for r in out if r.get("same") is False),
        sum(1 for r in out if r.get("mode") == "skip"), time.time() - t0, os.path.relpath(dest, ROOT)))
    if any(r.get("same") is False for r in out):
        print("VERDICT: DIFFERENT")
        return 1
    print("VERDICT: IDENTICAL")
    return 0


def cmd_identity_summary(args):
    src = git_show(args.against, "tools/note_extract.py")
    tag = hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]
    d = os.path.join(CACHE, "identity", tag, ours_tag())
    rows = [json.loads(l) for f in sorted(os.listdir(d)) if f.endswith(".jsonl") for l in open(os.path.join(d, f), encoding="utf-8")]
    rows = list({r["pass_file"]: r for r in rows}.values())
    c = Counter((r["mode"], r.get("same")) for r in rows)
    raised = Counter(r["ref"].get("raised") for r in rows if r.get("ref") and "raised" in r["ref"])
    diff = [r["pass_file"] for r in rows if r.get("same") is False]
    total = len(os.listdir(os.path.join(ROOT, "work", "spritepass")))
    out = dict(against=args.against, against_sha=rev_parse(args.against), reference=tag, ours=ours_tag(), passes=len(rows), on_disk=total,
               by_mode={"%s/%s" % k: v for k, v in sorted(c.items(), key=str)},
               identical=sum(1 for r in rows if r.get("same")), different=diff,
               raised_identically={k: v for k, v in raised.items()},
               new_stamp=extractor_stamp())
    print(json.dumps(out, indent=1))
    ext = extract_args_identity(args.against)
    print(json.dumps(ext, indent=1))
    if args.json:
        A.write_json(args.json, dict(out, extract_args=ext), indent=1)
    return 0 if not diff and not ext["different"] else 1


def extract_args_identity(rev):
    """note_extract.extract's chart -> footage lookup, ours (footage_of) against the reference's
    extract(), on every certified chart of both ledgers: the same (vid, band, ncols, side, dur)."""
    ref, _ = load_reference(rev)
    got = {}
    for M in (ref, NX):
        calls = []
        M._read = lambda *a, _c=calls: _c.append(a[:5]) or ([], {})
        for name in sorted(X.charts()):
            del calls[:]
            try:
                M.extract(name, quiet=True)
                got.setdefault(name, []).append(list(calls[0]))
            except Exception as ex:
                got.setdefault(name, []).append("%s: %s" % (type(ex).__name__, ex))
    diff = [n for n, v in got.items() if len(v) != 2 or v[0] != v[1]]
    return dict(charts=len(got), different=diff)


# ---------------------------------------------------------------- the file's own notes (truth)

def truth_path(row, pin):
    return os.path.join(CACHE, "truth", "%s.%s.%s.%s.json.gz" % (row["block_sha"][:16], row["header_sha"][:12], pin[:12],
                                                                 truth_stamp()))


def pinned_holds(text, tag, blk, holds):
    """Per hold: (state pinned, tail pinned). A hold whose interior holds no lattice point of its own
    counts exactly as a tap would, so the certified count says nothing about whether it is a hold;
    a tail that can slide PIN_TOL or more either way without crossing a lattice point is not placed
    by the count to within PIN_TOL. Only what the count pins is graded (tools/tick_model.py's lattice
    on the block's own #TICKCOUNTS)."""
    import tick_model as TM
    import tick_repair as T
    sched = T.schedule(text, tag)
    _, time_at = X.clocks(blk["rows"])
    rowset = {TM.snap(r["b"]) for r in blk["rows"] if any(ch in "12" for ch in r["line"][:blk["ncols"]])}
    hb = [(TM.snap(h["head_beat"]), TM.snap(h["tail_beat"])) for h in holds]
    out = []
    for k, h in enumerate(holds):
        b0, b1 = hb[k]
        pts = sorted(TM.lattice(sched, b0, b1))
        own = sum(1 for p in pts if p not in rowset and not any(j != k and hb[j][0] < p <= hb[j][1] for j in range(len(hb))))
        prev = pts[-1] if pts else b0
        nxt = sorted(TM.lattice(sched, b1, b1 + 8))
        early = time_at(float(b1)) - time_at(float(prev))
        late = (time_at(float(nxt[0])) - time_at(float(b1))) if nxt else 9.0
        out.append((own > 0, own > 0 and early < PIN_TOL and late < PIN_TOL))
    return out


def truth_of(row, pin):
    """The block through the pinned converter, as the grader needs it: the judged notes by column
    (chart seconds, beat, symbol), the drawn fakes, every hold (and whether the count pins it), the
    jack notes and the short-hold heads. Cached by block, header, converter pin and this code."""
    path = truth_path(row, pin)
    got = read_gz_json(path)
    if got is not None:
        return got
    ssc = os.path.join(ROOT, "simfiles", *row["ssc_rel"].split("/"))
    text = open(ssc, encoding="utf-8", newline="").read()
    if G.block_sha_text(text, row["tag"]) != row["block_sha"] or G.header_sha_text(text) != row["header_sha"]:
        raise RuntimeError("%s: the file is not the block the manifest pinned" % row["chart"])
    blk = X.load_block(ssc, row["tag"])
    if not blk or blk.get("error"):
        raise RuntimeError("%s: %s" % (row["chart"], (blk or {}).get("error") or "block not found"))
    fnotes, holds = X.file_events(blk["rows"], blk["ncols"])
    pins = pinned_holds(text, row["tag"], blk, holds)
    index = {(c, round(x[0], 9)): k for c, v in fnotes.items() for k, x in enumerate(v)}
    hl = []
    for h, (ps, pt) in zip(holds, pins):
        hl.append([h["col"], h["head"], h["tail"], index[(h["col"], round(h["head"], 9))], ps, pt])
    jack = set()
    for c, v in fnotes.items():
        for k in range(len(v) - 1):
            if v[k][2] == "1" and v[k + 1][0] - v[k][0] < JACK_GAP:
                jack.update(((c, k), (c, k + 1)))
    short = sorted((h[0], h[3]) for h in hl if h[2] - h[1] < SHORT_HOLD)
    out = dict(chart=row["chart"], ncols=blk["ncols"], implied=blk["implied"],
               fnotes={str(c): [[x[0], x[1], x[2]] for x in v] for c, v in fnotes.items()},
               fakes={str(c): v for c, v in (blk.get("fakes") or {}).items()},
               holds=hl, jack=sorted([list(x) for x in jack]), short_heads=[list(x) for x in short],
               rows=[[r["t"], r["b"], r["line"]] for r in blk["rows"]], width=blk["width"])
    write_gz_json(path, out)
    return out


def fnotes_of(truth):
    return {int(c): [tuple(x) for x in v] for c, v in truth["fnotes"].items()}


def blk_of(truth):
    return dict(rows=[dict(t=t, b=b, line=l) for t, b, l in truth["rows"]], ncols=truth["ncols"],
                fakes={int(c): v for c, v in truth["fakes"].items()}, width=truth["width"])


# ---------------------------------------------------------------- the manifest

def manifest_path(version):
    return os.path.join(BENCH_DIR, "manifest-%s.json" % version)


def load_manifest(version=None):
    version = version or current_version()
    m = A.load_json(manifest_path(version))
    if m is None:
        die("no benchmark manifest %s: run `bench.py freeze` first" % version)
    body = dict(m)
    body.pop("sha256", None)
    if digest(body) != m.get("sha256"):
        die("sources/benchmark/manifest-%s.json does not hash to the sha256 it records: edited after the freeze" % version)
    return m


def current_version():
    vs = sorted(f[len("manifest-"):-len(".json")] for f in os.listdir(BENCH_DIR) if f.startswith("manifest-")) \
        if os.path.isdir(BENCH_DIR) else []
    if not vs:
        die("no benchmark manifest: run `bench.py freeze` first")
    return vs[-1]


def family_of(chart):
    """The title family: the song title without its chart token, its SHORT CUT / FULL SONG / REMIX
    and PIU Edit markers, folded to ASCII, cut to its first two words - so a song, its cuts and its
    sequels (Beat of The War / Beat of The War 2, Final Audition / Final Audition 2) are one family.
    Coarse on purpose: a family too wide only makes the split coarser; one too narrow leaks a song."""
    title = chart.rsplit(" ", 1)[0]
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"-\s*(short cut|full song|remix)\s*-", " ", t)
    t = re.sub(r"\(\s*piu edit\s*\)", " ", t)
    toks = re.findall(r"[a-z0-9]+", t)
    return " ".join(toks[:2]) if toks else title


def named_in_docs(names):
    """Every chart name that appears in the docs, the code or the loop plan (whole-name matches)."""
    text = []
    for g in DOC_GLOBS:
        p = os.path.join(ROOT, g)
        if os.path.isfile(p):
            text.append(open(p, encoding="utf-8", errors="replace").read())
        elif os.path.isdir(p):
            for base, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "atlas-combo", "atlas-combo-p2")]
                for f in files:
                    if f.endswith((".md", ".py", ".txt")) and not f.startswith("bench"):
                        text.append(open(os.path.join(base, f), encoding="utf-8", errors="replace").read())
    blob = "\n".join(text)
    out = {}
    for n in names:
        for form in {n, n.replace("\\:", ":")}:
            if form in blob and re.search(r"(?<![\w])" + re.escape(form) + r"(?![\w])", blob):
                out[n] = True
    return sorted(out)


_CERT = []


def committed_certification():
    """The committed ledgers only (never work/certification-tail.json, which result_reader appends to)."""
    if not _CERT:
        _CERT.append(corpus_map.certification(sources_only=True))
    return _CERT[0]


def _freeze_one(row):
    """Per chart, what the freeze needs from the file and the caches (a worker)."""
    no_decode()
    out = dict(chart=row["chart"])
    try:
        vid, band, ncols, side, dur = NX.footage_of(row["chart"], committed_certification())
        out.update(vid=vid, band=band, ncols=ncols, side=side, dur=dur)
        fit = A.load_json(R.field_path(vid, band, ncols, side), quiet=True)
        out["pitch"] = fit.get("pitch") if fit else None
        try:
            anc, sharp, floors, params, ck = NX._pass_for(vid, band, ncols, side, dur)
            out.update(sharp=sharp, floors=floors)
            if os.path.exists(ck) and os.path.getsize(ck) > 0:
                out.update(pass_file=os.path.relpath(ck, ROOT).replace(os.sep, "/"), pass_sha=sha256_file(ck))
            else:
                out["no_pass"] = "no cached sprite pass at %s" % os.path.relpath(ck, ROOT).replace(os.sep, "/")
        except DecodeRefused:
            out["no_pass"] = "its receptor templates or field fit are not cached"
        except Exception as ex:
            out["no_pass"] = "%s: %s" % (type(ex).__name__, str(ex)[:160])
    except Exception as ex:
        out["no_footage"] = "%s: %s" % (type(ex).__name__, str(ex)[:160])
    return out


def _twins(args):
    """Other blocks of the same file and width deriving `expected`: a count that cannot tell them apart."""
    ssc_rel, tag, expected, ncols = args
    ssc = os.path.join(ROOT, "simfiles", *ssc_rel.split("/"))
    text = open(ssc, encoding="utf-8", newline="").read()
    tags = G.block_tags(text)
    out = []
    for t in sorted(set(tags)):
        if t == tag:
            continue
        try:
            b = X.load_block(ssc, t)
        except Exception:
            continue
        if b and not b.get("error") and b.get("ncols") == ncols and b["implied"] == expected:
            out.append(t)
    return out


def _truth_job(args):
    row, pin = args
    no_decode()
    try:
        t = truth_of(row, pin)
        return row["chart"], dict(file_notes=sum(len(v) for v in t["fnotes"].values()), jack=len(t["jack"]),
                                  short=len(t["short_heads"]), holds=len(t["holds"]),
                                  pinned_state=sum(1 for h in t["holds"] if h[4]), pinned_tail=sum(1 for h in t["holds"] if h[5]))
    except Exception as ex:
        return row["chart"], dict(error="%s: %s" % (type(ex).__name__, str(ex)[:160]))


def converter_pin():
    import supervise as S
    fz = S.frozen_converter_pin(S.converter_dir())
    if not fz.get("ok"):
        die("the converter is not the frozen pin: %s" % fz.get("why"))
    return json.load(open(os.path.join(ROOT, "sources", "oracle-manifest.json"), encoding="utf-8"))["converter"]["pin"]


def cmd_freeze(args):
    from multiprocessing import Pool
    version = args.version
    dest = manifest_path(version)
    if os.path.exists(dest) and not args.dry_run:
        die("%s exists: a frozen manifest is never rewritten - freeze a new version" % os.path.relpath(dest, ROOT))
    pin = converter_pin()
    oracle = json.load(open(os.path.join(ROOT, "sources", "oracle-manifest.json"), encoding="utf-8"))["oracle_hash"]
    grade = json.load(open(os.path.join(ROOT, "sources", "corpus-grade.json"), encoding="utf-8"))
    head = rev_parse("HEAD")
    imp = rev_parse(IMPORT_REV)
    quarantine = {c["chart"] for c in json.load(open(os.path.join(ROOT, "sources", "quarantine.json"), encoding="utf-8"))["charts"]}
    conflict = {c["chart"]: [r["kind"] + ": " + r["detail"] for r in c["reasons"]]
                for c in json.load(open(os.path.join(ROOT, "sources", "oracle-conflict.json"), encoding="utf-8"))["charts"]}
    rows = []
    for g in grade["charts"]:
        text = open(os.path.join(ROOT, "simfiles", *g["ssc_rel"].split("/")), encoding="utf-8", newline="").read()
        if G.block_sha_text(text, g["tag"]) != g["block_sha"] or G.header_sha_text(text) != g["header_sha"]:
            die("%s: the working tree is not what sources/corpus-grade.json graded - regrade before freezing" % g["chart"])
        old = git_show(imp, "simfiles/" + g["ssc_rel"])
        try:
            ib, ih = (G.block_sha_text(old, g["tag"]), G.header_sha_text(old)) if old is not None else (None, None)
        except LookupError:
            ib, ih = None, None
        rows.append(dict(chart=g["chart"], key=g["key"], ssc_rel=g["ssc_rel"], tag=g["tag"], expected=g["expected"],
                         implied=g["implied"], exact=g["exact"], tier=g.get("tier"), flags=g.get("flags") or [],
                         block_sha=g["block_sha"], header_sha=g["header_sha"], import_block_sha=ib, import_header_sha=ih))
    names = [r["chart"] for r in rows]
    with Pool(args.workers, initializer=_worker_init) as P:
        foot = {r["chart"]: r for r in P.map(_freeze_one, rows, chunksize=8)}
    for r in rows:
        f = foot[r["chart"]]
        for k in ("vid", "band", "ncols", "side", "dur", "pitch", "sharp", "floors", "pass_file", "pass_sha"):
            if k in f:
                r[k] = f[k]
        why = []
        if r["chart"] in quarantine:
            why.append("quarantine")
        if G.is_owner_revisit(r["chart"]):
            why.append("owner-revisit")
        if f.get("no_footage"):
            why.append("no footage: " + f["no_footage"])
        elif G.footage_corrupt_reason(r["vid"], r["band"]):
            why.append("footage-corrupt")
        if not r["exact"]:
            why.append("not count-exact")
        if not r.get("pass_file"):
            why.append("no pass: " + (f.get("no_pass") or "unknown"))
        if r.get("pitch") is not None and r["pitch"] < MISFIT_PITCH:
            why.append("lane misfit (pitch %.1f)" % r["pitch"])
        edited = (r["block_sha"], r["header_sha"]) != (r["import_block_sha"], r["import_header_sha"])
        if not why:
            r["stratum"] = "repo-edited" if edited else "truth"
        elif why[0].startswith("lane misfit") and len(why) == 1:
            r["stratum"] = "lane-misfit"
        else:
            r["stratum"] = "excluded"
        r["excluded_why"] = why
        r["edited_since_import"] = edited
        ident = list(conflict.get(r["chart"], []))
        r["identity"] = dict(pending=bool(ident), why=ident)
    # count twins: siblings of the same width deriving the same total, for the charts that are graded
    graded = [r for r in rows if r["stratum"] in ("truth", "repo-edited", "lane-misfit")]
    with Pool(args.workers, initializer=_worker_init) as P:
        tw = P.map(_twins, [(r["ssc_rel"], r["tag"], r["expected"], r["ncols"]) for r in graded], chunksize=4)
    for r, t in zip(graded, tw):
        if t:
            r["identity"]["pending"] = True
            r["identity"]["why"].append("count twin: %s derives the same %d" % (", ".join(t), r["expected"]))
    # the truth each graded chart is scored against, built now so the freeze can pick sentinels from it
    with Pool(args.workers, initializer=_worker_init) as P:
        tstats = dict(P.map(_truth_job, [(r, pin) for r in graded], chunksize=4))
    for r in graded:
        r["truth"] = tstats[r["chart"]]
        if "error" in r["truth"]:
            r["stratum"] = "excluded"
            r["excluded_why"].append("truth: " + r["truth"]["error"])
    truth = [r for r in rows if r["stratum"] == "truth"]
    # sentinels, chosen from the files alone: the densest jacks and short holds among the truth charts,
    # the proposal's named jack charts, and the counter-backed notes the files lack
    jack = sorted(truth, key=lambda r: (-r["truth"]["jack"], r["chart"]))[:N_SENTINEL]
    jack_set = sorted({r["chart"] for r in jack} | {n for n in NAMED_JACK if any(t["chart"] == n for t in truth)})
    short_set = sorted(r["chart"] for r in sorted(truth, key=lambda r: (-r["truth"]["short"], r["chart"]))[:N_SENTINEL])
    byname = {r["chart"]: r for r in rows}
    backed = []
    for n, t, c in BACKED:
        r = byname.get(n)
        backed.append(dict(chart=n, t=t, col=c, in_population=bool(r), pass_file=(r or {}).get("pass_file"),
                           usable=bool(r and r.get("pass_file") and "footage-corrupt" not in r["excluded_why"])))
    for r in rows:
        r["sentinel"] = [s for s, members in (("jack", jack_set), ("short-hold", short_set)) if r["chart"] in members]
        if any(b["chart"] == r["chart"] for b in backed):
            r["sentinel"].append("backed")
            if r["stratum"] == "excluded" and r.get("pass_file") and "footage-corrupt" not in r["excluded_why"]:
                r["stratum"] = "sentinel-only"
    named = set(named_in_docs(names))
    for r in rows:
        r["named"] = r["chart"] in named
    # components: charts joined by title family, video and song file
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for key in ("family", "vid", "ssc_rel"):
        first = {}
        for r in rows:
            k = family_of(r["chart"]) if key == "family" else r.get(key)
            if k is None:
                continue
            if k in first:
                parent[find(r["chart"])] = find(first[k])
            else:
                first[k] = r["chart"]
    comp = defaultdict(list)
    for r in rows:
        r["family"] = family_of(r["chart"])
        comp[find(r["chart"])].append(r)
    salt = args.salt
    for members in comp.values():
        cid = digest(sorted({m["family"] for m in members}), 16)
        pinned = [m["chart"] for m in members if m["named"] or m["sentinel"]]
        u = int(hashlib.sha256(("%s\0%s" % (salt, cid)).encode()).hexdigest()[:12], 16) / float(16 ** 12)
        split = "tune" if pinned or u < 1 / 3.0 else ("validate" if u < 2 / 3.0 else "sealed")
        for m in members:
            m["component"], m["split"] = cid, split
            m["split_pinned"] = "tune-only: " + ", ".join(sorted(pinned)[:3]) + (" ..." if len(pinned) > 3 else "") if pinned else None
    strata = Counter(r["stratum"] for r in rows)
    splits = {s: Counter(r["stratum"] for r in rows if r["split"] == s) for s in ("tune", "validate", "sealed")}
    body = dict(bench=BENCH, version=version, frozen=time.strftime("%Y-%m-%d %H:%M"), head=head, import_rev=imp,
                converter_pin=pin, oracle_hash=oracle, note_extract=dict(extractor_stamp=extractor_stamp(),
                                                                         blob=git("hash-object", "tools/note_extract.py").stdout.decode().strip()),
                truth_stamp=truth_stamp(), salt=salt,
                split_rule="components joined by title family (bench.family_of), video and song file; a component holding a "
                           "chart named in the docs/code/loop plan or a sentinel is tune; the rest by u = sha256(salt NUL "
                           "component id) -> tune < 1/3 <= validate < 2/3 <= sealed (thirds, because the pinned components "
                           "already make tune the largest)",
                strata=dict(strata), splits={s: dict(c) for s, c in splits.items()},
                identity_pending=sorted(r["chart"] for r in rows if r["stratum"] in ("truth", "repo-edited") and r["identity"]["pending"]),
                sentinels=dict(jack=jack_set, short_hold=short_set, backed=backed),
                params=dict(TOLS=TOLS, JACK_GAP=JACK_GAP, SHORT_HOLD=SHORT_HOLD, PIN_TOL=PIN_TOL, MISFIT_PITCH=MISFIT_PITCH,
                            N_SENTINEL=N_SENTINEL),
                charts=sorted(rows, key=lambda r: r["chart"]))
    body["split_sha"] = digest(sorted((r["chart"], r["split"]) for r in rows))
    manifest = dict(body, sha256=digest(body))
    print("strata %s" % dict(strata))
    for s, c in splits.items():
        print("  %-8s %s" % (s, dict(c)))
    print("identity pending (graded strata): %d; sentinels: jack %d, short-hold %d, backed %d usable of %d; named in docs %d" % (
        len(body["identity_pending"]), len(jack_set), len(short_set), sum(b["usable"] for b in backed), len(backed), len(named)))
    print("manifest sha256 %s, split sha %s" % (manifest["sha256"], body["split_sha"]))
    if args.dry_run:
        return 0
    os.makedirs(BENCH_DIR, exist_ok=True)
    A.write_json(dest, manifest, indent=1, sort_keys=True, ensure_ascii=False)
    gate = gate_spec(version)
    A.write_json(gate_path(version), gate, indent=1, sort_keys=True)
    append_ledger(dict(kind="freeze", bench=BENCH, version=version, manifest_sha256=manifest["sha256"],
                       split_sha=body["split_sha"], gate_sha256=digest(gate), salt=salt, head=head,
                       note="frozen and hashed before any baseline"))
    print("wrote %s, %s and a freeze row in sources/runs.jsonl" % (os.path.relpath(dest, ROOT), os.path.relpath(gate_path(version), ROOT)))
    return 0


# ---------------------------------------------------------------- the gate, as data

def gate_path(version):
    return os.path.join(BENCH_DIR, "gate-%s.json" % version)


def gate_spec(version):
    return dict(bench=BENCH, version=version, criteria=[
        dict(id="f1_gain", on="split", rule="pooled note F1 at 45 ms rises by at least 0.20 points"),
        dict(id="bootstrap", on="split", rule="the 2.5th percentile of the pooled F1 gain over 2000 resamples of the split's "
                                              "components (with replacement, seed from the candidate's diff hash) is above 0"),
        dict(id="top5", on="split", rule="the pooled F1 gain stays above 0 with the 5 charts that gained most removed"),
        dict(id="tolerances", on="split", rule="the pooled F1 gain is above 0 at 30 ms and at 60 ms as well"),
        dict(id="timing_p90", on="split", rule="the p90 of |timing error| over matched notes at 45 ms does not rise by more "
                                               "than 0.1 ms (read of 'the gain shows in p90': not bought with looser matches)"),
        dict(id="real_lost", on="split+tune", rule="file notes the baseline matched and the candidate does not: at most "
                                                   "max(3, 0.02% of the file notes) in all, and at most 1 on any chart"),
        dict(id="removed_extras", on="split+tune", rule="of the baseline's notes the candidate removed, at least 99% were extras"),
        dict(id="additions", on="split+tune", rule="planned add-tap + add-hold edits on these count-exact files (frozen "
                                                   "alignment) do not rise"),
        dict(id="hold_edits", on="split+tune", rule="planned tail + tap->hold edits on these count-exact files do not rise"),
        dict(id="pinned_holds", on="split+tune", rule="on holds the count pins: hold-state recall does not fall, and the share of "
                                                      "pinned tails read within 60 ms does not fall"),
        dict(id="jack_sentinel", on="sentinel", rule="recall of jack notes on the jack sentinels does not fall"),
        dict(id="short_hold_sentinel", on="sentinel", rule="recall of short-hold heads on the short-hold sentinels does not fall"),
        dict(id="backed_sentinel", on="sentinel", rule="every counter-backed note the baseline extracts is still extracted"),
        dict(id="canary", on="canary", rule="official-canary pooled recall does not fall and no canary loses more than 1 real "
                                            "note (N/A until the canary is frozen: such accepts carry 'NEVSISTER-validated only')"),
    ], caps=dict(candidates=40, looks_per_split=20, looks_per_family=3, sealed_looks=1),
        fixed="with the manifest, before any baseline")


# ---------------------------------------------------------------- the hash-chained ledger

def read_ledger():
    rows = []
    if os.path.exists(RUNS_LEDGER):
        for i, line in enumerate(open(RUNS_LEDGER, encoding="utf-8")):
            if line.strip():
                rows.append(json.loads(line))
    prev = "0" * 64
    for i, r in enumerate(rows):
        body = {k: v for k, v in r.items() if k != "hash"}
        if r.get("prev") != prev or digest(body) != r.get("hash"):
            die("sources/runs.jsonl is broken at row %d: the hash chain does not hold" % (i + 1))
        prev = r["hash"]
    return rows, prev


def append_ledger(row):
    rows, prev = read_ledger()
    row = dict(row, prev=prev, at=time.strftime("%Y-%m-%d %H:%M:%S"))
    row["hash"] = digest(row)
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows + [row])
    A.write_text(RUNS_LEDGER, text)
    return row


def cmd_chain(args):
    rows, prev = read_ledger()
    print("sources/runs.jsonl: %d rows, chain holds, head %s" % (len(rows), prev[:16]))
    for r in rows:
        print("  %s %-7s %s %s %s" % (r["at"], r["kind"], r.get("split", ""), r.get("rule", r.get("version", "")), r.get("verdict", "")))
    return 0


# ---------------------------------------------------------------- rules: registration

RULES_LEDGER = os.path.join(BENCH_DIR, "rules.jsonl")


def registered():
    out = {}
    if os.path.exists(RULES_LEDGER):
        for line in open(RULES_LEDGER, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                out.setdefault(r["rule"], []).append(r)
    return out


def rule_of(name):
    if name not in BR.RULES:
        die("no rule %r in tools/bench_rules.py (%s)" % (name, ", ".join(BR.RULES)))
    return BR.RULES[name]


def chain_registration(rule):
    """The registration as a row of the hash-chained ledger too, so the chain itself shows a rule was
    registered before any look at it (once per rule and code hash)."""
    rows, _ = read_ledger()
    if not any(r.get("kind") == "register" and r.get("rule") == rule.name and r.get("code_hash") == rule.code_hash for r in rows):
        append_ledger(dict(kind="register", bench=BENCH, rule=rule.name, family=rule.family, drill=rule.drill,
                           code_hash=rule.code_hash, params=rule.params, patches=rule.patches))


def cmd_register(args):
    rule = rule_of(args.rule)
    have = registered()
    if any(r["code_hash"] == rule.code_hash for r in have.get(rule.name, [])):
        chain_registration(rule)
        print("%s is registered at %s" % (rule.name, rule.code_hash))
        return 0
    if have.get(rule.name):
        die("%s is registered with another code hash (%s): a changed rule is a new candidate under a new name" % (
            rule.name, have[rule.name][-1]["code_hash"]))
    n = sum(1 for k, v in have.items() if BR.RULES.get(k) is None or BR.RULES[k].family != "baseline")
    if rule.family != "baseline" and n >= 40:
        die("the candidate cap (40) is reached")
    row = dict(rule=rule.name, family=rule.family, drill=rule.drill, code_hash=rule.code_hash, params=rule.params,
               patches=rule.patches, doc=rule.doc, extractor_stamp=extractor_stamp(), registered=time.strftime("%Y-%m-%d %H:%M:%S"))
    lines = open(RULES_LEDGER, encoding="utf-8").read() if os.path.exists(RULES_LEDGER) else ""
    os.makedirs(BENCH_DIR, exist_ok=True)
    A.write_text(RULES_LEDGER, lines + json.dumps(row, sort_keys=True) + "\n")
    chain_registration(rule)
    print("registered %s (%s) at code hash %s" % (rule.name, rule.family, rule.code_hash))
    return 0


# ---------------------------------------------------------------- replay

def rule_key(rule, manifest):
    return digest(dict(rule=rule.code_hash, extractor=extractor_stamp(), scorer=scorer_stamp(), manifest=manifest["sha256"]), 16)


def record_path(key, chart):
    return os.path.join(CACHE, "replay", key, hashlib.sha1(chart.encode("utf-8")).hexdigest()[:16] + ".json.gz")


@contextlib.contextmanager
def patched(module, patches):
    saved = {k: getattr(module, k) for k in patches}
    try:
        for k, v in patches.items():
            setattr(module, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(module, k, v)


def compact(notes):
    return [[n["col"], n["t"], n.get("hold_end"), n.get("frames"), n.get("rail_len"), n.get("rail_occ")] for n in notes]


def as_notes(rows):
    return [dict(col=c, t=t, hold_end=h, frames=f, **({"rail_len": rl, "rail_occ": ro} if rl is not None else {}))
            for c, t, h, f, rl, ro in rows]


def prod_stats(notes, blk, a, b, flashes):
    edits, st = X.plan(notes, blk, a, b, flashes)
    return dict(recall=st["recall"], precision=st["precision"], err_median_ms=st["err_median_ms"], err_p90_ms=st["err_p90_ms"],
                extracted=st["extracted"], file_notes=st["file_notes"], matched=st["matched"],
                edits=dict(Counter(e["kind"] for e in edits)))


_PASS_SHA = {}


def post_decoded(row, got):
    """note_extract.post_decode over this pinned pass, cached by the pass's sha256 and the
    extractor's stamp as it stands at the call (code and constants, so a rule's patched constant
    keys its own copy): a rule that only acts on post_decode's output then costs a pickle load, not
    a post-decode. The pickle is the exact objects post_decode returned; each load is a fresh copy,
    so a rule that edits notes in place cannot reach the cache."""
    key = "%s.%s" % (row["pass_sha"][:24], digest(dict(stamp=extractor_stamp(), floors=row["floors"], ncols=row["ncols"]), 16))
    path = os.path.join(CACHE, "post", key[:2], key + ".pkl")
    hit = A.load_pickle(path, quiet=True) if os.path.exists(path) else None
    if isinstance(hit, tuple) and len(hit) == 2:
        return hit
    ts, scored, fps, y0, y1, scan = got
    out = NX.post_decode(ts, scored, fps, y0, y1, scan, row["floors"], row["ncols"], vid=row["vid"], band=row["band"],
                         side=row["side"], sharp=row.get("sharp"), quiet=True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    A.write_pickle(path, out)
    return pickle.loads(pickle.dumps(out))


def replay_chart(row, rule, pin, base=None):
    """One chart under one rule: the pinned pass through post_decode (the rule's patches on) and the
    rule's post step, then what the grader needs. The alignment is the baseline's (`base`), frozen, so
    a rule cannot win by moving the clock; `prod` is what extract_repair itself would report, the
    extraction aligned on its own."""
    rec = dict(chart=row["chart"], rule=rule.name, status="FAIL")
    try:
        ck = os.path.join(ROOT, *row["pass_file"].split("/"))
        if not os.path.exists(ck):
            return dict(rec, why="the pinned pass is gone (never decoded here)")
        st = os.stat(ck)
        sig = (ck, st.st_size, st.st_mtime_ns)
        if sig not in _PASS_SHA:
            _PASS_SHA[sig] = sha256_file(ck)
        if _PASS_SHA[sig] != row["pass_sha"]:
            return dict(rec, why="the pinned pass changed since the freeze")
        got = A.load_pickle(ck, quiet=True)
        if not (isinstance(got, tuple) and len(got) == 6):
            return dict(rec, why="the pinned pass does not load")
        ts, scored, fps, y0, y1, scan = got
        with patched(NX, rule.patches):
            notes, meta = post_decoded(row, got)
        notes = rule.apply(notes, meta, scan)
        truth = truth_of(row, pin) if row["stratum"] != "sentinel-only" else None
        rec.update(status="OK", notes=compact(notes), floor=meta["floor"], colour=meta["colour"], holds=meta["holds"])
        flashes = {int(c): v for c, v in meta["flashes"].items()}
        if truth is not None:
            fn, blk = fnotes_of(truth), blk_of(truth)
            if base:
                # a candidate is held to the baseline's clock; aligning it again (quantize's anchor
                # search, most of a replay's time) would only measure what the frozen clock rules out
                a, b = base["align_own"][0], base["align_own"][1]
                rec["align_own"] = None
            else:
                a, b, n_fit, _ = X.align(notes, fn, truth["ncols"])
                rec["align_own"] = [a, b, n_fit]
            rec["align"] = [a, b]
            rec["prod"] = prod_stats(notes, blk, a, b, flashes)
            rec["plan_frozen"] = rec["prod"]["edits"]
        if "backed" in row.get("sentinel", []):
            if "align" not in rec:
                # a sentinel-only chart is not count-exact, so it has no truth record: align the
                # extraction to its file for the baseline, and hold every candidate to that clock
                if base and base.get("align"):
                    rec["align"] = list(base["align"])
                else:
                    ssc = os.path.join(ROOT, "simfiles", *row["ssc_rel"].split("/"))
                    blk = X.load_block(ssc, row["tag"])
                    fn, _ = X.file_events(blk["rows"], blk["ncols"])
                    a0, b0, n_fit, _ = X.align(notes, fn, blk["ncols"])
                    rec["align_own"] = [a0, b0, n_fit]
                    rec["align"] = [a0, b0]
            rec["backed"] = backed_check(row, notes, rec["align"])
    except Exception as ex:
        rec["why"] = "%s: %s" % (type(ex).__name__, str(ex)[:200])
    return rec


def backed_check(row, notes, align):
    """Each counter-backed note of this chart: is there an extracted note within 45 ms of it in its
    column (chart time, through the frozen alignment)."""
    a, b = align
    return [any(x["col"] == c and abs(a + b * x["t"] - t) <= 0.045 for x in notes) for n, t, c in BACKED if n == row["chart"]]


def _replay_job(args):
    row, rule_name, key, base_key, pin = args
    path = record_path(key, row["chart"])
    if os.path.exists(path) and read_gz_json(path) is not None:
        return row["chart"], "cached"
    base = read_gz_json(record_path(base_key, row["chart"])) if base_key else None
    if base_key and base is None:
        return row["chart"], "no baseline record"
    rec = replay_chart(row, BR.RULES[rule_name], pin, base)
    write_gz_json(path, rec)
    return row["chart"], rec["status"]


def _remember_passes():
    """A rule that reads the pass itself (bench_rules.Rule.wants_pass) gets the one this worker
    loaded last; the rule checks it is the pass whose scan it was handed."""
    real = A.load_pickle

    def load(path, *a, **k):
        got = real(path, *a, **k)
        if isinstance(got, tuple) and len(got) == 6:
            BR.LAST_PASS[0] = got
        return got
    A.load_pickle = load


def _worker_init():
    no_decode()
    read_only()
    cache_onsets()
    fast_anchor()
    _remember_passes()


def charts_for(manifest, sets):
    rows = [r for r in manifest["charts"] if r["stratum"] in ("truth", "repo-edited", "lane-misfit", "sentinel-only")]
    want = set(sets)
    out = []
    for r in rows:
        if r["stratum"] == "sentinel-only":
            if "sentinel" in want:
                out.append(r)
        elif r["split"] in want or ("sentinel" in want and r["sentinel"]):
            out.append(r)
    canary = os.path.join(BENCH_DIR, "canary-v1.json")
    if "canary" in want and os.path.exists(canary):
        out += json.load(open(canary, encoding="utf-8"))["charts"]
    return out


def baseline_key(manifest):
    return rule_key(BR.RULES["baseline"], manifest)


def cmd_replay(args):
    from multiprocessing import Pool
    manifest = load_manifest()
    rule = rule_of(args.rule)
    if rule.name != "baseline" and not any(r["code_hash"] == rule.code_hash for r in registered().get(rule.name, [])):
        die("%s is not registered at its current code hash (%s): `bench.py register --rule %s` before it is replayed" % (
            rule.name, rule.code_hash, rule.name))
    sets = args.set.split(",")
    if "sealed" in sets and rule.name != "baseline":
        die("the sealed split is replayed for a candidate only at the stop (`grade --split sealed --final`)")
    pin = converter_pin()
    key = rule_key(rule, manifest)
    bkey = None if rule.name == "baseline" else baseline_key(manifest)
    rows = shard_of(sorted(charts_for(manifest, sets), key=lambda r: r["chart"]), args.shard)
    t0 = time.time()
    jobs = [(r, rule.name, key, bkey, pin) for r in rows]
    c = Counter()
    if args.workers <= 1:
        _worker_init()
        for j in jobs:
            c[_replay_job(j)[1]] += 1
    else:
        with Pool(args.workers, initializer=_worker_init) as P:
            for _, s in P.imap_unordered(_replay_job, jobs, chunksize=2):
                c[s] += 1
    print("replay %s (key %s) over %s%s: %d charts, %s, %.0f s" % (rule.name, key, args.set,
                                                                     " shard " + args.shard if args.shard else "", len(rows), dict(c), time.time() - t0))
    return 0 if not c.get("no baseline record") else 3


# ---------------------------------------------------------------- scoring

def match_at(notes, fnotes, ncols, a, b, tol):
    saved = X.TOL
    X.TOL = tol
    try:
        return X.match(notes, fnotes, ncols, a, b)
    finally:
        X.TOL = saved


def score_chart(rec, truth, align):
    """Counts under the frozen alignment at each tolerance, plus the ids the comparisons need."""
    fn = fnotes_of(truth)
    ncols = truth["ncols"]
    fakes = {int(c): v for c, v in truth["fakes"].items()}
    n_file = sum(len(v) for v in fn.values())
    if rec is None or rec.get("status") != "OK":
        z = dict(tp=0, ext=0, fake=0, file=n_file, errs=[])
        return {t: z for t in TOLS}, dict(matched_file=set(), matched_note=set(), notes=[], fail=True)
    notes = as_notes(rec["notes"])
    a, b = align
    index = {(c, x[0]): k for c, v in fn.items() for k, x in enumerate(v)}
    out, extra_info = {}, {}
    for tol in TOLS:
        pairs, extra, missing, errs = match_at(notes, fn, ncols, a, b, tol)
        fake = 0
        for i in extra:
            n = notes[i]
            ft = fakes.get(n["col"], [])
            u = a + b * n["t"]
            if any(abs(x - u) <= tol for x in ft):
                fake += 1
        out[tol] = dict(tp=len(pairs), ext=len(notes), fake=fake, file=n_file, errs=errs)
        if tol == 0.045:
            extra_info = dict(matched_file={(c, index[(c, x[0])]) for _, c, x in pairs},
                              matched_note={i for i, _, _ in pairs},
                              pair_of={index[(c, x[0])] + 1000000 * c: i for i, c, x in pairs},
                              notes=notes, fail=False)
    return out, extra_info


def f1(tp, den_ext, n_file):
    return 2.0 * tp / (den_ext + n_file) if den_ext + n_file else 0.0


def pooled(per, charts, tol):
    tp = sum(per[c][tol]["tp"] for c in charts)
    ext = sum(per[c][tol]["ext"] - per[c][tol]["fake"] for c in charts)
    fl = sum(per[c][tol]["file"] for c in charts)
    return dict(tp=tp, ext=ext, file=fl, recall=tp / fl if fl else 0.0, precision=tp / ext if ext else 0.0, f1=f1(tp, ext, fl))


def hold_metrics(truth, info, align):
    """Pinned holds: state hit (the matched head carries a release) and tail hit (within 60 ms)."""
    a, b = align
    st_n = st_hit = tl_n = tl_hit = 0
    for col, head, tail, k, ps, pt in truth["holds"]:
        if not ps:
            continue
        st_n += 1
        tl_n += 1 if pt else 0
        i = info.get("pair_of", {}).get(k + 1000000 * col) if not info.get("fail") else None
        if i is None:
            continue
        he = info["notes"][i].get("hold_end")
        if he is None:
            continue
        st_hit += 1
        if pt and abs(a + b * he - tail) <= PIN_TOL:
            tl_hit += 1
    return st_n, st_hit, tl_n, tl_hit


def load_records(key, rows):
    return {r["chart"]: read_gz_json(record_path(key, r["chart"])) for r in rows}


def evaluate(manifest, rows, base_recs, cand_recs, pin):
    """Everything the gate reads, over one set of charts."""
    per_b, per_c, detail = {}, {}, {}
    for r in rows:
        truth = truth_of(r, pin)
        br = base_recs.get(r["chart"])
        align = tuple(br["align_own"][:2]) if br and br.get("status") == "OK" else (0.0, 1.0)
        sb, ib = score_chart(br, truth, align)
        sc, ic = score_chart(cand_recs.get(r["chart"]), truth, align)
        per_b[r["chart"]], per_c[r["chart"]] = sb, sc
        lost = ib["matched_file"] - ic["matched_file"]
        gained = ic["matched_file"] - ib["matched_file"]
        bkeys = {(n["col"], n["t"]) for n in ib["notes"]}
        ckeys = [(n["col"], n["t"]) for n in ic["notes"]]
        cset = defaultdict(list)
        for c, t in ckeys:
            cset[c].append(t)
        for v in cset.values():
            v.sort()

        def kept(n):
            v = cset.get(n["col"], [])
            j = bisect.bisect_left(v, n["t"] - 0.001)
            return j < len(v) and v[j] <= n["t"] + 0.001
        removed = [i for i, n in enumerate(ib["notes"]) if not kept(n)]
        removed_extra = sum(1 for i in removed if i not in ib["matched_note"])
        added = sum(1 for c, t in ckeys if (c, t) not in bkeys)
        hb, hc = hold_metrics(truth, ib, align), hold_metrics(truth, ic, align)
        jack = {tuple(x) for x in truth["jack"]}
        short = {tuple(x) for x in truth["short_heads"]}
        cr = cand_recs.get(r["chart"]) or {}
        detail[r["chart"]] = dict(
            lost=len(lost), gained=len(gained), removed=len(removed), removed_extra=removed_extra, added=added,
            holds_b=hb, holds_c=hc,
            jack=(len(jack), len(jack & ib["matched_file"]), len(jack & ic["matched_file"])),
            short=(len(short), len(short & ib["matched_file"]), len(short & ic["matched_file"])),
            plan_b=(br or {}).get("plan_frozen") or {}, plan_c=cr.get("plan_frozen") or {},
            prod_b=(br or {}).get("prod"), prod_c=cr.get("prod"), fail_c=ic["fail"], fail_b=ib["fail"],
            component=r["component"])
    return per_b, per_c, detail


def p90(per, charts, tol=0.045):
    errs = [e for c in charts for e in per[c][tol]["errs"]]
    return 1000.0 * float(np.percentile(errs, 90)) if errs else 0.0


def summarize_set(per_b, per_c, detail, charts):
    s = {}
    for tol in TOLS:
        pb, pc = pooled(per_b, charts, tol), pooled(per_c, charts, tol)
        s["f1_%d" % round(tol * 1000)] = (pb["f1"], pc["f1"])
        if tol == 0.045:
            s["recall"], s["precision"] = (pb["recall"], pc["recall"]), (pb["precision"], pc["precision"])
            s["file_notes"] = pb["file"]
    s["p90_ms"] = (p90(per_b, charts), p90(per_c, charts))
    d = [detail[c] for c in charts]
    s["lost"] = sum(x["lost"] for x in d)
    s["lost_max_chart"] = max((x["lost"] for x in d), default=0)
    s["gained"] = sum(x["gained"] for x in d)
    s["removed"] = sum(x["removed"] for x in d)
    s["removed_extra"] = sum(x["removed_extra"] for x in d)
    s["added"] = sum(x["added"] for x in d)
    kinds = ("add-tap", "add-hold"), ("tail", "tap->hold")
    s["additions"] = tuple(sum(sum(x[k].get(q, 0) for q in kinds[0]) for x in d) for k in ("plan_b", "plan_c"))
    s["hold_edits"] = tuple(sum(sum(x[k].get(q, 0) for q in kinds[1]) for x in d) for k in ("plan_b", "plan_c"))
    hb = [sum(x["holds_b"][i] for x in d) for i in range(4)]
    hc = [sum(x["holds_c"][i] for x in d) for i in range(4)]
    s["pinned_state"] = (hb[1] / hb[0] if hb[0] else 1.0, hc[1] / hc[0] if hc[0] else 1.0, hb[0])
    s["pinned_tail"] = (hb[3] / hb[2] if hb[2] else 1.0, hc[3] / hc[2] if hc[2] else 1.0, hb[2])
    j = [sum(x["jack"][i] for x in d) for i in range(3)]
    sh = [sum(x["short"][i] for x in d) for i in range(3)]
    s["jack_recall"] = (j[1] / j[0] if j[0] else 1.0, j[2] / j[0] if j[0] else 1.0, j[0])
    s["short_recall"] = (sh[1] / sh[0] if sh[0] else 1.0, sh[2] / sh[0] if sh[0] else 1.0, sh[0])
    pb = [x["prod_b"] for x in d if x["prod_b"]]
    pc = [x["prod_c"] for x in d if x["prod_c"]]
    s["bar_pass"] = (sum(1 for p in pb if p["recall"] >= 0.93 and p["precision"] >= 0.93),
                     sum(1 for p in pc if p["recall"] >= 0.93 and p["precision"] >= 0.93), len(d))
    s["median_err_ms"] = (float(np.median([p["err_median_ms"] for p in pb if p["err_median_ms"] is not None])) if pb else None,
                          float(np.median([p["err_median_ms"] for p in pc if p["err_median_ms"] is not None])) if pc else None)
    s["failed"] = (sum(1 for x in d if x["fail_b"]), sum(1 for x in d if x["fail_c"]))
    s["charts"] = len(charts)
    return s


def bootstrap_lb(per_b, per_c, detail, charts, seed, reps=2000):
    comps = sorted({detail[c]["component"] for c in charts})
    idx = {k: i for i, k in enumerate(comps)}
    sums = np.zeros((len(comps), 5))
    for c in charts:
        pb, pc = per_b[c][0.045], per_c[c][0.045]
        sums[idx[detail[c]["component"]]] += (pb["tp"], pb["ext"] - pb["fake"], pc["tp"], pc["ext"] - pc["fake"], pb["file"])
    rng = np.random.default_rng(seed)
    w = np.stack([np.bincount(rng.integers(0, len(comps), len(comps)), minlength=len(comps)) for _ in range(reps)])
    t = w @ sums
    fb = 2 * t[:, 0] / (t[:, 1] + t[:, 4])
    fc = 2 * t[:, 2] / (t[:, 3] + t[:, 4])
    return float(np.percentile(100 * (fc - fb), 2.5)), len(comps)


def top5_drop(per_b, per_c, charts):
    def f(p):
        return f1(p["tp"], p["ext"] - p["fake"], p["file"])
    gain = sorted(charts, key=lambda c: -(f(per_c[c][0.045]) - f(per_b[c][0.045])))
    keep = gain[5:]
    return 100 * (pooled(per_c, keep, 0.045)["f1"] - pooled(per_b, keep, 0.045)["f1"]), gain[:5]


def judge(split_s, tune_s, sent, canary, lb, top5, n_file_split, n_file_tune):
    """The gate's criteria (sources/benchmark/gate-<v>.json), each PASS / FAIL with its numbers."""
    res = []

    def add(cid, ok, text):
        res.append(dict(id=cid, ok=bool(ok) if ok is not None else None, text=text))
    d45 = 100 * (split_s["f1_45"][1] - split_s["f1_45"][0])
    add("f1_gain", d45 >= 0.20, "pooled F1@45 %+.3f pt (%.3f -> %.3f)" % (d45, 100 * split_s["f1_45"][0], 100 * split_s["f1_45"][1]))
    add("bootstrap", lb > 0, "2.5th percentile of the component bootstrap %+.3f pt" % lb)
    add("top5", top5[0] > 0, "gain without the top 5 gainers %+.3f pt (dropped %s)" % (top5[0], ", ".join(top5[1])))
    d30 = 100 * (split_s["f1_30"][1] - split_s["f1_30"][0])
    d60 = 100 * (split_s["f1_60"][1] - split_s["f1_60"][0])
    add("tolerances", d30 > 0 and d60 > 0, "F1@30 %+.3f pt, F1@60 %+.3f pt" % (d30, d60))
    add("timing_p90", split_s["p90_ms"][1] - split_s["p90_ms"][0] <= 0.1, "p90 |err| %.2f -> %.2f ms" % split_s["p90_ms"])
    for name, s, nf in (("split", split_s, n_file_split), ("tune", tune_s, n_file_tune)):
        cap = max(3, 0.0002 * nf)
        add("real_lost/" + name, s["lost"] <= cap and s["lost_max_chart"] <= 1,
            "%d real notes lost (cap %.1f), at most %d on one chart" % (s["lost"], cap, s["lost_max_chart"]))
        add("removed_extras/" + name, s["removed"] == 0 or s["removed_extra"] >= 0.99 * s["removed"],
            "%d of %d removed notes were extras" % (s["removed_extra"], s["removed"]))
        add("additions/" + name, s["additions"][1] <= s["additions"][0], "planned additions %d -> %d" % s["additions"])
        add("hold_edits/" + name, s["hold_edits"][1] <= s["hold_edits"][0], "planned tail/tap->hold %d -> %d" % s["hold_edits"])
        add("pinned_holds/" + name, s["pinned_state"][1] >= s["pinned_state"][0] and s["pinned_tail"][1] >= s["pinned_tail"][0],
            "pinned state %.4f -> %.4f (of %d), tail within 60 ms %.4f -> %.4f (of %d)" % (
                s["pinned_state"] + s["pinned_tail"]))
    add("jack_sentinel", sent["jack_recall"][1] >= sent["jack_recall"][0],
        "jack-note recall %.4f -> %.4f (%d notes)" % sent["jack_recall"])
    add("short_hold_sentinel", sent["short_recall"][1] >= sent["short_recall"][0],
        "short-hold head recall %.4f -> %.4f (%d heads)" % sent["short_recall"])
    add("backed_sentinel", sent["backed"][1] >= sent["backed"][0] and sent["backed"][1] == sent["backed_b_set"],
        "counter-backed notes extracted %d -> %d of %d" % (sent["backed"][0], sent["backed"][1], sent["backed"][2]))
    if canary is None:
        add("canary", None, "N/A: the official canary is not frozen yet (NEVSISTER-validated only)")
    else:
        add("canary", canary["recall"][1] >= canary["recall"][0] and canary["lost_max_chart"] <= 1,
            "canary recall %.4f -> %.4f, at most %d real notes lost on one canary" % (canary["recall"] + (canary["lost_max_chart"],)))
    return res


def sentinel_summary(manifest, base_key, cand_key, pin):
    rows = [r for r in manifest["charts"] if r["sentinel"] and r["stratum"] in ("truth", "repo-edited", "lane-misfit", "sentinel-only")]
    jack = [r for r in rows if "jack" in r["sentinel"] and r["stratum"] == "truth"]
    short = [r for r in rows if "short-hold" in r["sentinel"] and r["stratum"] == "truth"]
    b_recs, c_recs = load_records(base_key, rows), load_records(cand_key, rows)
    _, _, dj = evaluate(manifest, jack, b_recs, c_recs, pin)
    _, _, ds = evaluate(manifest, short, b_recs, c_recs, pin)
    j = [sum(dj[r["chart"]]["jack"][i] for r in jack) for i in range(3)]
    s = [sum(ds[r["chart"]]["short"][i] for r in short) for i in range(3)]
    bb = bc = n = bset = 0
    for r in rows:
        if "backed" not in r["sentinel"]:
            continue
        xb = (b_recs.get(r["chart"]) or {}).get("backed") or []
        xc = (c_recs.get(r["chart"]) or {}).get("backed") or []
        n += len(xb)
        bb += sum(xb)
        bc += sum(1 for k, v in enumerate(xb) if v and k < len(xc) and xc[k])
        bset += sum(xb)
    return dict(jack_recall=(j[1] / j[0] if j[0] else 1.0, j[2] / j[0] if j[0] else 1.0, j[0]),
                short_recall=(s[1] / s[0] if s[0] else 1.0, s[2] / s[0] if s[0] else 1.0, s[0]),
                backed=(bb, bc, n), backed_b_set=bset)


def canary_summary(base_key, cand_key, pin):
    path = os.path.join(BENCH_DIR, "canary-v1.json")
    if not os.path.exists(path):
        return None
    cm = json.load(open(path, encoding="utf-8"))
    rows = cm["charts"]
    b_recs, c_recs = load_records(base_key, rows), load_records(cand_key, rows)
    per_b, per_c, d = evaluate(cm, rows, b_recs, c_recs, pin)
    charts = [r["chart"] for r in rows]
    pb, pc = pooled(per_b, charts, 0.045), pooled(per_c, charts, 0.045)
    return dict(recall=(pb["recall"], pc["recall"]), lost_max_chart=max((d[c]["lost"] for c in charts), default=0), charts=len(charts))


def fmt_summary(name, s):
    return ("%-9s %3d charts %6d notes | F1@45 %.3f -> %.3f (%+.3f) | R %.3f -> %.3f | P %.3f -> %.3f | F1@30 %+.3f F1@60 %+.3f | "
            "lost %d gained %d removed %d (%d extras) | bar %d -> %d | fail %d -> %d" % (
                name, s["charts"], s["file_notes"], 100 * s["f1_45"][0], 100 * s["f1_45"][1], 100 * (s["f1_45"][1] - s["f1_45"][0]),
                100 * s["recall"][0], 100 * s["recall"][1], 100 * s["precision"][0], 100 * s["precision"][1],
                100 * (s["f1_30"][1] - s["f1_30"][0]), 100 * (s["f1_60"][1] - s["f1_60"][0]),
                s["lost"], s["gained"], s["removed"], s["removed_extra"], s["bar_pass"][0], s["bar_pass"][1],
                s["failed"][0], s["failed"][1]))


def cmd_grade(args):
    manifest = load_manifest()
    rule = rule_of(args.rule)
    regs = registered().get(rule.name, [])
    if rule.name != "baseline" and not any(r["code_hash"] == rule.code_hash for r in regs):
        die("%s is not registered at its current code hash %s" % (rule.name, rule.code_hash))
    pin = converter_pin()
    no_decode()
    bkey, ckey = baseline_key(manifest), rule_key(rule, manifest)
    split = args.split
    held_out = split in ("validate", "sealed")
    diff_hash = digest(dict(rule=rule.code_hash, extractor=extractor_stamp()), 32)
    if held_out and rule.name != "baseline":
        rows_l, _ = read_ledger()
        looks = [r for r in rows_l if r.get("kind") == "look" and r.get("bench") == BENCH and r.get("manifest_sha256") == manifest["sha256"]]
        if split == "sealed" and not args.final:
            die("the sealed split opens once, at the stop: `grade --split sealed --final`")
        if sum(1 for r in looks if r["split"] == split) >= (20 if split == "validate" else 1):
            die("the held-out look cap for %s is reached" % split)
        if split == "validate" and sum(1 for r in looks if r["split"] == split and r.get("family") == rule.family) >= 3:
            die("rule family %s has had its 3 held-out looks" % rule.family)
        if any(r.get("diff_hash") == diff_hash and r["split"] == split for r in looks):
            die("this exact change (diff %s) has already been looked at on %s" % (diff_hash[:12], split))
    rows = [r for r in manifest["charts"] if r["stratum"] == "truth" and r["split"] == split]
    tune_rows = [r for r in manifest["charts"] if r["stratum"] == "truth" and r["split"] == "tune"]
    need = rows + (tune_rows if split != "tune" else [])
    b_recs, c_recs = load_records(bkey, need), load_records(ckey, need)
    missing = [c for c, v in list(b_recs.items()) + list(c_recs.items()) if v is None]
    if missing:
        die("%d records missing (replay the baseline and the rule over %s%s first): %s" % (
            len(missing), split, ",tune" if split != "tune" else "", ", ".join(sorted(set(missing))[:5])))
    per_b, per_c, detail = evaluate(manifest, rows, b_recs, c_recs, pin)
    charts = [r["chart"] for r in rows]
    s_split = summarize_set(per_b, per_c, detail, charts)
    if split != "tune":
        tb, tc, td = evaluate(manifest, tune_rows, b_recs, c_recs, pin)
        s_tune = summarize_set(tb, tc, td, [r["chart"] for r in tune_rows])
    else:
        s_tune = s_split
    seed = int(diff_hash[:8], 16)
    lb, n_comp = bootstrap_lb(per_b, per_c, detail, charts, seed)
    t5 = top5_drop(per_b, per_c, charts)
    sent = sentinel_summary(manifest, bkey, ckey, pin)
    can = canary_summary(bkey, ckey, pin)
    res = judge(s_split, s_tune, sent, can, lb, t5, s_split["file_notes"], s_tune["file_notes"])
    verdict = "ACCEPT" if all(r["ok"] is not False for r in res) else "REJECT"
    print("%s on %s (manifest %s, baseline %s, candidate %s, diff %s)" % (rule.name, split, manifest["version"], bkey, ckey, diff_hash[:12]))
    print(fmt_summary(split, s_split))
    if split != "tune":
        print(fmt_summary("tune", s_tune))
    for r in res:
        print("  %-4s %-26s %s" % ({True: "ok", False: "FAIL", None: "n/a"}[r["ok"]], r["id"], r["text"]))
    print("VERDICT: %s%s" % (verdict, "" if can is not None else " (NEVSISTER-validated only)"))
    report = dict(rule=rule.name, family=rule.family, split=split, manifest=manifest["sha256"], baseline_key=bkey, candidate_key=ckey,
                  diff_hash=diff_hash, split_summary=s_split, tune_summary=s_tune, bootstrap=dict(lb=lb, components=n_comp, seed=seed),
                  top5=t5, sentinels=sent, canary=can, criteria=res, verdict=verdict)
    if args.json:
        A.write_json(args.json, report, indent=1, default=list)
    if held_out and rule.name != "baseline":
        append_ledger(dict(kind="look", bench=BENCH, manifest_sha256=manifest["sha256"], split=split, rule=rule.name,
                           family=rule.family, drill=rule.drill, code_hash=rule.code_hash, diff_hash=diff_hash,
                           baseline_key=bkey, candidate_key=ckey, verdict=verdict,
                           failed=[r["id"] for r in res if r["ok"] is False],
                           numbers=dict(f1_45=s_split["f1_45"], f1_30=s_split["f1_30"], f1_60=s_split["f1_60"], lost=s_split["lost"],
                                        lost_tune=s_tune["lost"], removed=s_split["removed"], removed_extra=s_split["removed_extra"],
                                        bootstrap_lb=lb, top5=t5[0], canary=bool(can))))
    return 0 if verdict == "ACCEPT" else 1


def cmd_baseline(args):
    """The baseline's own numbers per split and stratum (no candidate: F1 is the baseline's both ways)."""
    manifest = load_manifest()
    pin = converter_pin()
    no_decode()
    bkey = baseline_key(manifest)
    out = {}
    for stratum in ("truth", "repo-edited", "lane-misfit"):
        # the sealed split is never shown on its own before the stop; "all" pools it in once its records exist
        for split in ("tune", "validate", "tune+validate", "all"):
            rows = [r for r in manifest["charts"] if r["stratum"] == stratum and (split == "all" or r["split"] in split.split("+"))]
            if not rows:
                continue
            recs = load_records(bkey, rows)
            if any(v is None for v in recs.values()):
                print("%s/%s: %d records missing" % (stratum, split, sum(1 for v in recs.values() if v is None)))
                continue
            per_b, _, detail = evaluate(manifest, rows, recs, recs, pin)
            charts = [r["chart"] for r in rows]
            p = pooled(per_b, charts, 0.045)
            pb = [detail[c]["prod_b"] for c in charts if detail[c]["prod_b"]]
            errs = [e for c in charts for e in per_b[c][0.045]["errs"]]
            plan = Counter()
            for c in charts:
                plan.update(detail[c]["plan_b"])
            s = summarize_set(per_b, per_b, detail, charts)
            out["%s/%s" % (stratum, split)] = dict(
                charts=len(charts), file_notes=p["file"], recall=round(100 * p["recall"], 2), precision=round(100 * p["precision"], 2),
                f1=round(100 * p["f1"], 2), f1_30=round(100 * s["f1_30"][0], 2), f1_60=round(100 * s["f1_60"][0], 2),
                bar_pass=sum(1 for x in pb if x["recall"] >= 0.93 and x["precision"] >= 0.93),
                median_chart_err_ms=round(float(np.median([x["err_median_ms"] for x in pb if x["err_median_ms"] is not None])), 2) if pb else None,
                pooled_median_err_ms=round(1000 * float(np.median(errs)), 2) if errs else None,
                p90_err_ms=round(1000 * float(np.percentile(errs, 90)), 2) if errs else None,
                failed=sum(1 for c in charts if detail[c]["fail_b"]), planned_edits=dict(plan),
                pinned_state=s["pinned_state"][0], pinned_holds=s["pinned_state"][2], pinned_tail=s["pinned_tail"][0],
                pinned_tails=s["pinned_tail"][2], jack_recall=s["jack_recall"][0], short_recall=s["short_recall"][0])
            print("%-22s %s" % (stratum + "/" + split, json.dumps(out["%s/%s" % (stratum, split)], sort_keys=True)))
    sent = sentinel_summary(manifest, bkey, bkey, pin)
    out["sentinels"] = sent
    print("sentinels", json.dumps(sent))
    if args.json:
        A.write_json(args.json, dict(manifest=manifest["sha256"], baseline_key=bkey, extractor_stamp=extractor_stamp(), numbers=out),
                     indent=1, sort_keys=True)
    return 0


def cmd_verify_anchor(args):
    """fast_anchor_offset against quantize.anchor_offset: every replay record whose alignment the
    original computed (align_own), re-aligned from the same notes with the fast search - the whole
    of extract_repair.align, not just the seed - must agree to the bit; --slow N also runs both
    searches side by side on N more charts' records."""
    manifest = load_manifest()
    pin = converter_pin()
    no_decode()
    byname = {r["chart"]: r for r in manifest["charts"]}
    seen, same, diff = 0, 0, []
    for d in sorted(os.listdir(os.path.join(CACHE, "replay"))):
        for f in sorted(os.listdir(os.path.join(CACHE, "replay", d))):
            rec = read_gz_json(os.path.join(CACHE, "replay", d, f))
            if not rec or rec.get("status") != "OK" or not rec.get("align_own") or rec["chart"] not in byname:
                continue
            row = byname[rec["chart"]]
            if row["stratum"] == "sentinel-only":
                continue
            truth = truth_of(row, pin)
            fn = fnotes_of(truth)
            notes = as_notes(rec["notes"])
            Q.anchor_offset = fast_anchor_offset
            try:
                a, b, n_fit, _ = X.align(notes, fn, truth["ncols"])
            finally:
                Q.anchor_offset = _REAL_ANCHOR
            seen += 1
            if [a, b, n_fit] == rec["align_own"]:
                same += 1
            else:
                diff.append((rec["chart"], rec["align_own"], [a, b, n_fit]))
    print("align with the fast anchor search: %d records the original aligned, %d identical, %d different" % (seen, same, len(diff)))
    for x in diff[:10]:
        print("  DIFF", x)
    n = 0
    for r in sorted((r for r in manifest["charts"] if r["stratum"] == "truth"), key=lambda r: digest(r["chart"]))[:args.slow]:
        recs = [read_gz_json(os.path.join(CACHE, "replay", d, os.path.basename(record_path("x", r["chart"]))))
                for d in os.listdir(os.path.join(CACHE, "replay"))]
        rec = next((x for x in recs if x and x.get("status") == "OK"), None)
        if not rec:
            continue
        fn = fnotes_of(truth_of(r, pin))
        notes = as_notes(rec["notes"])
        slow = _REAL_ANCHOR(notes, {c: [x[0] for x in v] for c, v in fn.items()}, r["ncols"])
        fast = fast_anchor_offset(notes, {c: [x[0] for x in v] for c, v in fn.items()}, r["ncols"])
        n += 1
        if slow != fast:
            diff.append((r["chart"], slow, fast))
            print("  DIFF seed", r["chart"], slow, fast)
    print("seed search side by side: %d charts, %d different" % (n, sum(1 for x in diff if len(x) == 3 and isinstance(x[1], tuple))))
    print("VERDICT: %s" % ("IDENTICAL" if not diff else "DIFFERENT"))
    return 0 if not diff else 1


# ---------------------------------------------------------------- the official canary
#
# Out-of-distribution footage the benchmark has none of: Andamiro's own autoplay uploads, one chart
# on screen, of charts whose file already derives the published count. Doubles only (one field in
# the middle of the screen, band C - bucket #6's phase-1 population), so no pad has to be guessed.
# Each is decoded ONCE, in its own overlay under work/bench/canary/ov/<vid> (the video hard-linked
# in, every cache the read writes kept there), so nothing lands in the shared receptor or sprite
# caches the other loops read. Chosen blind to any extraction: candidates in a salted-hash order,
# field fits first, and only fits in the official skin's own band (its modal lane pitch, +-3%, with
# a clean single field) are decoded, the first CANARY_N of them.

CANARY_DIR = os.path.join(CACHE, "canary")
CANARY_N = 15
CANARY_SALT = "bench-canary-v1"


def canary_overlay(vid):
    ov = os.path.join(CANARY_DIR, "ov", vid)
    for sub in ("videos", os.path.join("work", "receptor"), os.path.join("work", "spritepass")):
        os.makedirs(os.path.join(ov, sub), exist_ok=True)
    dst = os.path.join(ov, "videos", vid + ".mp4")
    if not os.path.exists(dst):
        os.link(os.path.join(ROOT, "videos", vid + ".mp4"), dst)     # a hard link: removing it never touches the footage
    return ov


@contextlib.contextmanager
def in_overlay(vid):
    ov = canary_overlay(vid)
    saved = (NX.ROOT, os.getcwd())
    NX.ROOT = ov
    os.chdir(ov)
    try:
        yield ov
    finally:
        NX.ROOT = saved[0]
        os.chdir(saved[1])


def cmd_canary_candidates(args):
    manifest = load_manifest()
    split_of = {r["chart"]: r["split"] for r in manifest["charts"]}
    smap = corpus_map.chart_map()
    quarantine = {c["chart"] for c in json.load(open(os.path.join(ROOT, "sources", "quarantine.json"), encoding="utf-8"))["charts"]}
    cm = json.load(open(os.path.join(ROOT, "work", "corpus-video-map.json"), encoding="utf-8"))
    import cv2
    out = []
    for e in cm:
        if "Official" not in (e.get("channel") or "") or len(e.get("charts") or []) != 1:
            continue
        c = e["charts"][0]
        name, vid = c["chart"], e["vid"]
        if name.split()[-1][0] != "D" or name not in smap or name in quarantine or G.is_owner_revisit(name):
            continue
        if split_of.get(name) in ("validate", "sealed") or G.footage_corrupt_reason(vid):
            continue
        if not os.path.exists(os.path.join(ROOT, "videos", vid + ".mp4")) or not c.get("judged"):
            continue
        m = smap[name]
        ssc = os.path.join(ROOT, "simfiles", *m["ssc_rel"].split("/"))
        tag = X.block_tag(m["key"])
        blk = X.load_block(ssc, tag)
        if not blk or blk.get("error") or blk["implied"] != int(c["judged"]) or blk["ncols"] != 10:
            continue
        cap = cv2.VideoCapture(os.path.join(ROOT, "videos", vid + ".mp4"))
        dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 60)
        cap.release()
        text = open(ssc, encoding="utf-8", newline="").read()
        out.append(dict(chart=name, vid=vid, key=m["key"], ssc_rel=m["ssc_rel"], tag=tag, expected=int(c["judged"]),
                        implied=blk["implied"], block_sha=G.block_sha_text(text, tag), header_sha=G.header_sha_text(text),
                        dur=dur, order=hashlib.sha256(("%s\0%s" % (CANARY_SALT, vid)).encode()).hexdigest()))
    out.sort(key=lambda r: r["order"])
    os.makedirs(CANARY_DIR, exist_ok=True)
    A.write_json(os.path.join(CANARY_DIR, "candidates.json"), out, indent=1)
    print("%d official single-chart doubles uploads whose file derives the published count (not validate/sealed)" % len(out))
    return 0


def cmd_canary_fit(args):
    """One candidate's field fit, in its overlay (a decode of 64 frames: run it in a slot)."""
    import cv2
    with in_overlay(args.vid):
        cap = cv2.VideoCapture(os.path.join(NX.ROOT, "videos", args.vid + ".mp4"))
        R.field(cap, args.vid, "C", 10, "1p")
        cap.release()
        fit = A.load_json(R.field_path(args.vid, "C", 10, "1p"))
    print("VERDICT: FIT pitch %s symmetry %s fields %s" % (fit.get("pitch"), fit.get("symmetry"), fit.get("fields")))
    return 0


def cmd_canary_select(args):
    cands = json.load(open(os.path.join(CANARY_DIR, "candidates.json"), encoding="utf-8"))
    fits = []
    for c in cands[:args.pool]:
        p = os.path.join(CANARY_DIR, "ov", c["vid"], *R.field_path(c["vid"], "C", 10, "1p").replace("\\", "/").split("/"))
        f = A.load_json(p, quiet=True)
        if f is None:
            break           # only the fitted prefix of the hash order: a later fit can never displace a choice
        fits.append((c, f))
    ok = [f["pitch"] for c, f in fits if f.get("fields") == 1 and (f.get("symmetry") or 0) >= 0.95]
    if not ok:
        die("no field fits yet")
    mode = Counter(round(p) for p in ok).most_common(1)[0][0]
    chosen = [c for c, f in fits if f and f.get("fields") == 1 and (f.get("symmetry") or 0) >= 0.95
              and abs(f["pitch"] - mode) <= 0.03 * mode][:CANARY_N]
    A.write_json(os.path.join(CANARY_DIR, "chosen.json"), dict(mode_pitch=mode, fitted=len([f for _, f in fits if f]),
                                                             in_band=len(chosen), chosen=chosen), indent=1)
    print("modal pitch %d over %d clean fits of %d; chosen %d: %s" % (mode, len(ok), len(fits), len(chosen),
                                                                    ", ".join(c["chart"] for c in chosen)))
    return 0


def cmd_canary_decode(args):
    """One chosen canary's sprite pass, decoded once in its overlay (run it in a slot)."""
    c = next(c for c in json.load(open(os.path.join(CANARY_DIR, "chosen.json"), encoding="utf-8"))["chosen"] if c["vid"] == args.vid)
    with in_overlay(args.vid):
        NX.CACHE = True
        notes, meta = NX.extract_video(args.vid, 10, "1p", "C", dur=c["dur"], quiet=True)
    print("VERDICT: DECODED %d notes at floor %s" % (len(notes), meta["floor"]))
    return 0


def cmd_canary_freeze(args):
    """sources/benchmark/canary-v1.json: each decoded canary pinned like a manifest chart."""
    dest = os.path.join(BENCH_DIR, "canary-v1.json")
    if os.path.exists(dest):
        die("sources/benchmark/canary-v1.json exists: a frozen canary is never rewritten")
    no_decode()
    chosen = json.load(open(os.path.join(CANARY_DIR, "chosen.json"), encoding="utf-8"))
    rows = []
    for c in chosen["chosen"]:
        with in_overlay(c["vid"]):
            try:
                anc, sharp, floors, params, ck = NX._pass_for(c["vid"], "C", 10, "1p", c["dur"])
            except DecodeRefused:
                print("%s: not decoded yet" % c["chart"])
                continue
            if not os.path.exists(ck):
                print("%s: no pass yet" % c["chart"])
                continue
            fit = A.load_json(R.field_path(c["vid"], "C", 10, "1p"))
        rows.append(dict(c, band="C", side="1p", ncols=10, floors=floors, sharp=sharp, pitch=fit.get("pitch"),
                         pass_file=os.path.relpath(ck, ROOT).replace(os.sep, "/"), pass_sha=sha256_file(ck),
                         stratum="canary", split="canary", sentinel=[], component="canary-" + c["vid"]))
    if len(rows) < len(chosen["chosen"]) and not args.partial:
        die("%d of %d canaries decoded: wait, or --partial" % (len(rows), len(chosen["chosen"])))
    pin = converter_pin()
    body = dict(bench=BENCH, version="canary-v1", frozen=time.strftime("%Y-%m-%d %H:%M"), converter_pin=pin,
                mode_pitch=chosen["mode_pitch"], rule="official single-chart doubles uploads (corpus-video-map channel "
                "Official), file derives the published count, not validate/sealed; salted-hash order; field fit single, "
                "symmetry >= 0.95, pitch within 3%% of the modal pitch; first %d" % CANARY_N,
                charts=sorted(rows, key=lambda r: r["chart"]))
    A.write_json(dest, dict(body, sha256=digest(body)), indent=1, sort_keys=True, ensure_ascii=False)
    append_ledger(dict(kind="canary-freeze", bench=BENCH, canary_sha256=digest(body), charts=len(rows)))
    print("wrote %s: %d canaries" % (os.path.relpath(dest, ROOT), len(rows)))
    return 0


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(prog="bench.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("identity")
    p.add_argument("--against", required=True)
    p.add_argument("--stale", action="store_true", help="the passes in older key formats, step alone")
    p.add_argument("--shard")
    p.add_argument("--subshard", help="a shard of the shard (i/n): to split a slow shard across more jobs")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("identity-summary")
    p.add_argument("--against", required=True)
    p.add_argument("--json")
    p = sub.add_parser("freeze")
    p.add_argument("--version", default="v1")
    p.add_argument("--salt", default="bench-v1-2026-09-27")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("replay")
    p.add_argument("--rule", required=True)
    p.add_argument("--set", default="tune,validate,sentinel")
    p.add_argument("--shard")
    p.add_argument("--workers", type=int, default=4)
    p = sub.add_parser("register")
    p.add_argument("--rule", required=True)
    p = sub.add_parser("grade")
    p.add_argument("--rule", required=True)
    p.add_argument("--split", required=True, choices=("tune", "validate", "sealed"))
    p.add_argument("--final", action="store_true")
    p.add_argument("--json")
    p = sub.add_parser("baseline")
    p.add_argument("--json")
    sub.add_parser("chain")
    sub.add_parser("canary-candidates")
    p = sub.add_parser("canary-fit")
    p.add_argument("--vid", required=True)
    p = sub.add_parser("canary-select")
    p.add_argument("--pool", type=int, default=40)
    p = sub.add_parser("canary-decode")
    p.add_argument("--vid", required=True)
    p = sub.add_parser("verify-anchor")
    p.add_argument("--slow", type=int, default=0)
    p = sub.add_parser("canary-freeze")
    p.add_argument("--partial", action="store_true")
    args = ap.parse_args()
    os.chdir(ROOT)      # receptors keeps its caches under relative paths
    return dict(identity=cmd_identity, freeze=cmd_freeze, replay=cmd_replay, register=cmd_register, grade=cmd_grade,
                baseline=cmd_baseline, chain=cmd_chain, **{"identity-summary": cmd_identity_summary,
                                                           "canary-candidates": cmd_canary_candidates, "canary-fit": cmd_canary_fit,
                                                           "canary-select": cmd_canary_select, "canary-decode": cmd_canary_decode,
                                                           "canary-freeze": cmd_canary_freeze, "verify-anchor": cmd_verify_anchor})[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
