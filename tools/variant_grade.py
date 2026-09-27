# The converter variant grader: "what if the game judged hold events this way" questions, graded
# over the whole corpus in a few minutes, REPORT-ONLY. It never edits the converter, its clone, or a
# stepfile; a rule that clears the gate becomes a proposed patch and a draft EVIDENCE-RULES
# section for the owner, under work/variant-grade/proposals/, and nothing more.
#
#   python -X utf8 -B tools/variant_grade.py jobs --out <jobs.jsonl> [--shards N]   (supervise.py dump jobs)
#   python -X utf8 -B tools/variant_grade.py dump [--shard I/N]      convert every block into the ctx cache
#   python -X utf8 -B tools/variant_grade.py index                   seal the dump (its manifest)
#   python -X utf8 -B tools/variant_grade.py selftest                the base model against the converter
#   python -X utf8 -B tools/variant_grade.py freeze                  freeze the evidence tiers + the split
#   python -X utf8 -B tools/variant_grade.py family-begin <hyp.py>   re-check the dump, reach precheck
#   python -X utf8 -B tools/variant_grade.py register <hyp.py> [<variant> ...]
#   python -X utf8 -B tools/variant_grade.py grade <hyp.py> [<variant> ...]    tune split only
#   python -X utf8 -B tools/variant_grade.py reveal <hyp.py> <variant>          the sealed hold-out (3 in all)
#   python -X utf8 -B tools/variant_grade.py family-end <hyp.py>     close a family; the zero-net stop
#   python -X utf8 -B tools/variant_grade.py null [--seed S] [--triples N]      random predicates, must pass 0
#   python -X utf8 -B tools/variant_grade.py stage2 <hyp.py>|BASE <variant> --patch <p.py> [--clean-room <c.py>]
#   python -X utf8 -B tools/variant_grade.py status | stop <why>
#   common: [--work <dir>] (default work/variant-grade)  [--workers N] (default 3, at most 4)
#
# THE MODEL. `dump` runs piu-annotate's converter (the pinned clone, read-only) over every block of
# every .ssc at HEAD, and over the import commit a23cee5's copy of every file changed since, with
# the converter's own `context=` hook: its hold segments, judged holds, rows, TICKCOUNTS, WARPS and
# FAKES, plus the raw timing and scroll tags of the block. The base model recounts each segment
# from those inputs exactly as lattice_hold_ticks does - lattice points of the TICKCOUNT in effect,
# held, not inside a WARP or FAKES range (overlapping ranges MERGED, which is what the converter
# does and what the research copy did not), less the points a judged row already sits on, plus one
# event per head row that is not a tap row - and must reproduce the converter's taps + ticks on
# every block, segment for segment. Every command that grades checks that first, on every dumped
# block in the worker pool (the startup self-test), and exits 1 on any mismatch.
#
# A HYPOTHESIS is a Python file (work/variant-grade/hypotheses/<family>.py) holding FAMILY, TITLE,
# KIND ("count" when the rule reads only what the converter already parses, "parse" when it reads
# a tag the converter does not - then only the stage-2 scratch copy grades it for real), a
# feature(block) predicate (which blocks the family can touch at all: the reach precheck), and
# VARIANTS = {name: (rule text, transform)}; a transform edits a copy of the base inputs (rates,
# held spans, excluded ranges, heads, row points, explicit event adjustments). A variant is graded
# only under the code hash it was REGISTERED with before any grade: sha256 over the rule text and
# the syntax tree of its transform and every module-level name it reaches. At most 40 variants
# and 6 testable families; a family the reach precheck finds UNTESTABLE spends nothing (it cannot
# pass: fewer than 3 notes-confirmed near misses in 2 packs carry its feature, none in the tune
# split, or no sealed chart off its count does).
#
# THE TIERS (frozen once, before any hypothesis; the file's sha256 is in the ledger and every
# command checks it). The population is the committed oracle's certified charts less the ORACLE_
# CONFLICT, quarantine and owner-revisit charts (reported, never scored).
#   pristine exact  exact now, block and song header unchanged since the import a23cee5
#   fitted exact    exact now, block or header edited since: also graded on its upstream block;
#                   a break is excused only when the variant makes that upstream block exact
#   near miss       0 < |implied - certified| <= 10
#   notes-confirmed a near miss the extraction loop's 2026-09-23 run parked as "the screen shows
#                   the file's notes exactly" whose file has not changed since that report
#   tier A          (ideas only) not exact, |diff| < 30, notes-confirmed, clean play (maxcombo =
#                   judged, no GOOD/BAD/MISS), file unchanged since the reports; tier-A CLUSTERS
#                   are the tick loop's priced clusters on tier-A charts whose two cuts were
#                   unanimous (every frame in each cut window agreed) and whose segments still
#                   count what the report counted
#   catalog exact   an UNcertified chart of the merged map whose file converts to its Phoenix 1
#                   catalog count: a second must-not-break set
# The SPLIT: song families (the title less its level, SHORT CUT/FULL SONG/REMIX markers,
# parentheticals and a trailing sequel number), joined with every chart sharing a video or a
# file, go to the SEALED hold-out with probability 0.3 under a salt drawn at freeze; a group
# holding a chart named in docs/, the tools, README/CLAUDE.md or the loop-bucket spec is tune-only.
#
# THE GATE (pre-registered here; the null run uses the same function):
#   tune (every `grade`; the only numbers printed before a reveal): no pristine break, no
#     unexcused fitted break, no catalog break, no tier-A cluster the base agrees with lost, at
#     least 1 notes-confirmed near-miss fix, and fixes > breaks (blast radius: sealed blocks moved,
#     never how they fared);
#   reveal (at most 3 for the whole bucket; hash-chained in the ledger): the sealed split has no
#     break of any kind and at least 1 fix, and over tune + sealed: no pristine break, no
#     unexcused fitted break, no catalog break, >= 3 notes-confirmed near-miss fixes across >= 2
#     packs, no tier-A cluster lost. Every reveal also writes the whole-corpus blast radius (every
#     block the variant changes, by what it is). A parse-level rule wins only when stage 2 - the
#     rule written into a patched SCRATCH copy of the converter module (never the clone) and a
#     clean-room implementation written from the rule's text alone - reproduces the model's
#     totals on every block.
#   null: random 1-3-condition predicates over structural hold features, +/-1 event per matching
#     hold, through the same full gate, must pass 0.
# Stops: the first winner; 3 families in a row with zero net fixes; 40 variants, 6 families or
# 12 hours from the freeze. A null is worded "no rule found at evidence tier X (n charts)".
#
# GUARDS: tools/tick_model.py is never imported or touched. Every run uses -B (refused
# otherwise). The dump manifest records the simfiles tree, the oracle hash, the converter pin and
# the fork's HEAD / .py source hash / .py git-status hash; every command re-checks them and refuses
# (exit 2) when any moved ("re-dump"); `family-begin` re-checks the dump at every family boundary.
# The ledger (ledger.jsonl) is append-only and hash-chained, written under a lock file.
#
# EXIT CODES: 0 done; 1 a result that fails (a self-test mismatch, a gate that fails is NOT an
# error - it is recorded and exits 0); 2 refused (drift, a stale or incomplete dump, an unregistered
# or re-edited variant, a cap, a fourth reveal, a converter without the lattice); 75 the machine
# stopped it (MemoryError / OSError), retry later.
import os  # noqa: E401
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import ast
import bisect
import hashlib
import importlib.util
import inspect
import itertools
import json
import math
import random
import re
import subprocess
import time
from collections import Counter, defaultdict
from fractions import Fraction

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
CONVERTER = os.environ.get("PIU_ANNOTATE_ROOT", r"C:\Users\jonec\repos\piu-annotate")
IMPORT_COMMIT = "a23cee5"
REPORT_COMMIT = "efe483c"          # committed sources/extract-loop-2026-09-23.json + tick-loop-2026-09-23.json
EXTRACT_REPORT = "sources/extract-loop-2026-09-23.json"
TICK_REPORT = "sources/tick-loop-2026-09-23.json"
NOTES_OK = "the screen shows the file's notes exactly"
SPEC = "work/loop-buckets-2026-09-26.txt"
DEFAULT_WORK = os.path.join(ROOT, "work", "variant-grade")
DUMP_VERSION = 2                   # bump when what a ctx holds changes
TIMING_TAGS = ("BPMS", "STOPS", "DELAYS", "WARPS", "FAKES", "TICKCOUNTS", "SCROLLS", "SPEEDS", "TIMESIGNATURES",
               "COMBOS", "LABELS", "OFFSET", "DISPLAYBPM", "METER", "STEPSTYPE", "DESCRIPTION", "SONGTYPE", "TITLE")
TEMPFAIL = 75

GATE = dict(near=10, tier_a_diff=30, min_fixes=3, min_packs=2, max_reveals=3, sealed_min_fixes=1,
            sealed_share=30, max_variants=40, max_families=6, max_hours=12.0, stop_streak=3, max_workers=4)


def log(msg):
    print("[variant_grade] " + msg, file=sys.stderr, flush=True)


def refuse(msg, code=2):
    print("REFUSED: " + msg, file=sys.stderr, flush=True)
    sys.exit(code)


def sha_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def git(*args, cwd=ROOT, binary=False):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=not binary,
                       **({} if binary else dict(encoding="utf-8", errors="replace")))
    return r.returncode, r.stdout, r.stderr


# ================================================================ the model (pure, no converter)

def frac(x):
    """The converter's _frac: the nearest fraction with a denominator of at most 10000."""
    return Fraction(x).limit_denominator(10000)


class Spans:
    """TICKCOUNTS as the converter's _Spans: [(start, end|None, rate)], rate 1 before the first
    entry; entries sorted by beat, negative beats dropped, two entries a hair apart are one beat
    and the later one holds."""

    def __init__(self, entries):
        exact = {}
        for b, r in sorted(entries):
            if b >= 0:
                exact[frac(b)] = frac(r)
        start, rate = Fraction(0), Fraction(1)
        self.items = []
        for b, r in sorted(exact.items()):
            if b == 0:
                rate = r
                continue
            self.items.append((start, b, rate))
            start, rate = b, r
        self.items.append((start, None, rate))
        self.starts = [a for a, _, _ in self.items]

    def index(self, p):
        return max(0, bisect.bisect_right(self.starts, p) - 1)

    def rate_at(self, p):
        return self.items[self.index(p)][2]

    def on_lattice(self, p):
        r = self.rate_at(p)
        return r > 0 and (p * r).denominator == 1


def count_multiples(r, lo, lo_incl, hi, hi_incl):
    L, U = lo * r, hi * r
    kmin = math.ceil(L) if lo_incl else math.floor(L) + 1
    kmax = math.floor(U) if hi_incl else math.ceil(U) - 1
    return max(0, kmax - kmin + 1)


def count_lattice(spans, lo, lo_incl, hi, hi_incl):
    n = 0
    for a, b, r in spans.items[spans.index(lo):]:
        if b is not None and b <= lo:
            continue
        if a > hi:
            break
        if r <= 0:
            continue
        L, Li = (a, True) if a > lo else (lo, lo_incl)
        U, Ui = (hi, hi_incl) if b is None or b > hi else (b, False)
        if L < U or (L == U and Li and Ui):
            n += count_multiples(r, L, Li, U, Ui)
    return n


def merge_ranges(ranges):
    out = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(x) for x in out]


class Inputs:
    """What one block's hold events are counted from. A transform edits a copy: `tick` (TICKCOUNTS
    entries [(beat, rate)]), `held` (disjoint (head, tail] intervals), `excl` ([start, end) ranges
    never judged; merged before counting), `tap_rows` / `head_rows` (the judged rows: one on a
    lattice point inside a hold is that point's event), `heads` (head rows that are not tap rows:
    one event each, in the segment they open), `extra` ([(beat, n)]: n events added in the segment
    that beat falls in, the way a head is), `taps_delta` (added to the tap count)."""
    __slots__ = ("tick", "held", "excl", "tap_rows", "head_rows", "heads", "extra", "taps_delta", "segs", "taps")

    def copy(self):
        o = Inputs()
        o.tick, o.held, o.excl = list(self.tick), [list(x) for x in self.held], list(self.excl)
        o.tap_rows, o.head_rows, o.heads = set(self.tap_rows), set(self.head_rows), list(self.heads)
        o.extra, o.taps_delta, o.segs, o.taps = list(self.extra), self.taps_delta, self.segs, self.taps
        return o

    # helpers a transform may use
    def rate_entries_between(self, a, b, rate):
        """Make the TICKCOUNT `rate` over [a, b) (b None: to the end), restoring what held at b."""
        sp = Spans(self.tick)
        after = sp.rate_at(b) if b is not None else None
        keep = [(x, r) for x, r in self.tick if not (frac(x) >= a and (b is None or frac(x) < b))]
        if b is not None:
            keep = [(x, r) for x, r in keep if frac(x) != b]
            keep.append((b, after))
        keep.append((a, rate))
        self.tick = keep


def base_inputs(blk):
    """The converter's own inputs for one dumped block."""
    inp = Inputs()
    inp.tick = [(b, r) for b, r in blk["holdticks"]]
    held = []
    for h, t in sorted((frac(h), frac(t)) for h, t in blk["real_holds"]):
        if held and h <= held[-1][1]:
            held[-1][1] = max(held[-1][1], t)
        else:
            held.append([h, t])
    inp.held = held
    excl = []
    for s0, length in list(blk["warps"]) + list(blk["fakes"]):
        if length > 0:
            excl.append((frac(s0), frac(s0) + frac(length)))
    inp.excl = excl
    beats, lines = blk["row_beats"], blk["row_lines"]
    inp.tap_rows = {frac(b) for b, l in zip(beats, lines) if "1" in l}
    inp.head_rows = {frac(b) for b, l in zip(beats, lines) if "2" in l}
    inp.heads = sorted({frac(h) for h, _ in blk["real_holds"]} - inp.tap_rows)
    inp.extra, inp.taps_delta = [], 0
    inp.segs = [(frac(s), frac(e)) for s, e, _ in blk["segments"]]
    inp.taps = blk["taps"]
    return inp


def seg_counts(inp):
    """Per-segment judged hold events: lattice_hold_ticks, line for line, on (possibly edited)
    inputs. Returns (counts per segment in the converter's order, taps)."""
    segs = inp.segs
    taps = inp.taps + inp.taps_delta
    if not segs:
        return [], taps
    spans = Spans(inp.tick)
    held = sorted([list(x) for x in inp.held])
    merged = []
    for h, t in held:                                    # a transform may leave overlaps: merge
        if merged and h <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], t)
        else:
            merged.append([h, t])
    held = merged
    held_starts = [h for h, _ in held]

    def held_at(p):
        i = bisect.bisect_left(held_starts, p) - 1
        return i >= 0 and p <= held[i][1]

    excl = merge_ranges(inp.excl)

    def excluded(p):
        return any(a <= p < b for a, b in excl)

    row_points = sorted(x for x in inp.tap_rows | inp.head_rows
                        if held_at(x) and not excluded(x) and spans.on_lattice(x))
    counts = []
    for s, e in segs:
        n = 0
        i = max(0, bisect.bisect_right(held_starts, s) - 1)
        while i < len(held) and held[i][0] < e:
            lo, hi = max(s, held[i][0]), min(e, held[i][1])
            if lo < hi:
                n += count_lattice(spans, lo, False, hi, True)
                for a, b in excl:
                    L, Li = (a, True) if a > lo else (lo, False)
                    U, Ui = (b, False) if b <= hi else (hi, True)
                    if L < U or (L == U and Li and Ui):
                        n -= count_lattice(spans, L, Li, U, Ui)
            i += 1
        n -= bisect.bisect_right(row_points, e) - bisect.bisect_right(row_points, s)
        counts.append(n)
    starts = sorted((s, k) for k, (s, _) in enumerate(segs))
    start_beats = [x for x, _ in starts]
    for h in sorted(set(inp.heads)):
        j = max(0, bisect.bisect_right(start_beats, h) - 1)
        counts[starts[j][1]] += 1
    for beat, k in inp.extra:
        j = max(0, bisect.bisect_right(start_beats, beat) - 1)
        counts[starts[j][1]] += k
    return counts, taps


def total(inp):
    counts, taps = seg_counts(inp)
    return taps + sum(counts)


def window(inp, counts, b0, b1):
    """Hold events of the segments lying inside [b0, b1] (a tick-loop cluster's beats)."""
    return sum(c for (s, e), c in zip(inp.segs, counts) if s >= b0 and e <= b1)


# ---------------------------------------------------------------- a block, as a hypothesis sees it

def parse_pairs(raw, width=2):
    """'b=v,b=v,...' (or b=v=d=m for SPEEDS) -> [(Fraction beat, Fraction v, ...)] sorted, later
    duplicate beats winning. Whitespace and the parser's doubled newlines are ignored."""
    out = {}
    for part in (raw or "").split(","):
        f = [x.strip() for x in part.split("=")]
        if len(f) < 2 or not f[0]:
            continue
        try:
            vals = [frac(float(x)) for x in f[:width]]
        except ValueError:
            continue
        out[vals[0]] = tuple(vals)
    return [out[k] for k in sorted(out)]


class Block:
    """Read-only view of one dumped block for feature() and transforms."""

    def __init__(self, blk, rel=None):
        self.d = blk
        self.rel = rel
        self.tags = blk["tags"]
        self._cache = {}

    def pairs(self, tag, width=2):
        k = (tag, width)
        if k not in self._cache:
            self._cache[k] = parse_pairs(self.tags.get(tag, ""), width)
        return self._cache[k]

    def spans_of(self, tag, pred):
        """[(start, end|None)] where the tag's value (in effect from its entry to the next) satisfies
        pred; before the first entry nothing is in effect."""
        ps = self.pairs(tag)
        out = []
        for i, (b, v) in enumerate(ps):
            if pred(v):
                e = ps[i + 1][0] if i + 1 < len(ps) else None
                if out and out[-1][1] == b:
                    out[-1] = (out[-1][0], e)
                else:
                    out.append((b, e))
        return out

    @property
    def real_holds(self):
        return [(frac(h), frac(t)) for h, t in self.d["real_holds"]]

    @property
    def rows(self):
        return list(zip((frac(b) for b in self.d["row_beats"]), self.d["row_lines"]))


def in_spans(p, spans, closed_end=False):
    return any(a <= p and (b is None or p < b or (closed_end and p == b)) for a, b in spans)


# ================================================================ state, pins and tripwires

class Work:
    def __init__(self, path):
        self.dir = path
        self.ctx = os.path.join(path, "ctx")
        self.manifest = os.path.join(path, "dump-manifest.json")
        self.tiers = os.path.join(path, "tiers.json")
        self.ledger = os.path.join(path, "ledger.jsonl")
        self.hyp = os.path.join(path, "hypotheses")
        self.grades = os.path.join(path, "grades")
        self.proposals = os.path.join(path, "proposals")
        for d in (self.dir, self.ctx, self.hyp, self.grades, self.proposals):
            os.makedirs(d, exist_ok=True)


def atomic():
    import atomicio
    return atomicio


def load_converter():
    if CONVERTER not in sys.path:
        sys.path.insert(0, CONVERTER)
    from piu_annotate.formats import ssc_to_chartstruct as C
    if getattr(C, "HOLD_TICK_MODEL", None) != "lattice":
        refuse("the converter does not count hold ticks by the lattice")
    return C


def fork_state():
    """The converter clone's HEAD, the sha256 over its piu_annotate/*.py (supervise.py's
    py_sha256) and a hash of `git status` over those .py files (the tracked __pycache__ is left
    out: any import rewrites it)."""
    import supervise
    pkg = os.path.join(CONVERTER, "piu_annotate")
    digest, n = supervise.converter_hash(pkg)
    _, head, _ = git("rev-parse", "HEAD", cwd=CONVERTER)
    rc, st, _ = git("status", "--porcelain", "--", ":(glob)piu_annotate/**/*.py", cwd=CONVERTER)
    return dict(head=head.strip(), py_sha256=digest, py_files=n, status_sha=sha_text(st if rc == 0 else "ERR"))


def repo_state():
    """What the dump depends on in this checkout: the simfiles tree at HEAD, whether the working
    tree's simfiles/ and oracle are clean, the oracle hash, the converter pin."""
    import corpus_grade as CG
    _, head, _ = git("rev-parse", "HEAD")
    _, tree, _ = git("rev-parse", "HEAD:simfiles")
    rc, dirty, _ = git("status", "--porcelain", "--", "simfiles", *CG.ORACLE_DATA, *CG.ORACLE_POLICY)
    oracle = CG.Oracle(CG.Tree(None))
    pin = CG.converter_pin()
    CG.check_manifest(oracle, pin)                        # refuses on oracle or converter drift
    return dict(head=head.strip(), simfiles_tree=tree.strip(), dirty=dirty.strip(), oracle_hash=oracle.hash,
                converter_pin=pin["pin"]), oracle


def dump_code_hash():
    src = "\n".join(inspect.getsource(f) for f in (dump_block, dump_file_job)) + "\nv%d" % DUMP_VERSION
    return sha_text(src)


def model_code_hash():
    src = "\n".join(inspect.getsource(f) for f in (Spans, count_multiples, count_lattice, merge_ranges, Inputs,
                                                    base_inputs, seg_counts, total, window))
    return sha_text(src)


def tool_hash():
    return sha_file(os.path.abspath(__file__))


# ================================================================ the dump

def dump_block(sc, C):
    """One StepchartSSC through the converter with its context hook -> a picklable dict of plain
    floats and strings (exactness is restored with frac() on load, as the converter does)."""
    ctx = {}
    d = dict(tags={t: str(sc.get(t, "")) for t in TIMING_TAGS})
    try:
        out = C.stepchart_ssc_to_chartstruct(sc, context=ctx)
    except (MemoryError, OSError):
        raise
    except Exception as ex:
        d["error"] = ("%s: %s" % (type(ex).__name__, ex))[:200]
        return d
    if out[0] is None:
        d["error"] = ("convert failed: %s" % out[-1])[:200]
        return d
    df, ht, _ = out
    d["taps"] = int(df["Line"].str.contains("1", regex=False).sum())
    d["ticks"] = int(sum(round(x[2]) for x in ht))
    d["segments"] = [(float(s.start_beat), float(s.end_beat), int(s.ticks)) for s in ctx["segments"]]
    d["real_holds"] = [(float(h), float(t)) for h, t in ctx["real_holds"]]
    d["holdticks"] = [(float(b), float(r)) for b, r in ctx["holdticks"].items()]
    d["warps"] = [(float(b), float(v)) for b, v in ctx["warps"].items()]
    d["fakes"] = [(float(b), float(v)) for b, v in ctx["fakes"].items()]
    d["row_beats"] = [float(b) for b in df["Beat"]]
    d["row_times"] = [float(t) for t in df["Time"]]
    d["row_lines"] = [str(x) for x in df["Line"]]
    return d


def dump_file_job(content):
    """Every block of one file's content -> [{tag, index, reachable, ...block}]."""
    import tempfile
    C = load_converter()
    from piu_annotate.formats.sscfile import SongSSC
    fd, path = tempfile.mkstemp(suffix=".ssc", prefix="vg-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        song = SongSSC(path, "PLACEHOLDER_PACK_DONOTUSE")
        out, seen = [], set()
        for i, sc in enumerate(song.stepcharts):
            tag = "%s_%s" % (sc.data.get("DESCRIPTION", ""), sc.data.get("SONGTYPE", ""))
            blk = dump_block(sc, C)
            blk.update(index=i, tag=tag, reachable=tag not in seen)
            seen.add(tag)
            out.append(blk)
        return out
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def content_sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def dump_files():
    """[(rel, content sha, which, bytes)] for every .ssc at HEAD and every file changed since the
    import as the import has it, sorted, deduplicated by content in the dump itself."""
    import corpus_grade as CG
    head = CG.Tree("HEAD")
    rels = sorted(p for p in head._index() if p.startswith("simfiles/") and p.lower().endswith(".ssc"))
    rc, changed, _ = git("diff", "--name-only", "-z", IMPORT_COMMIT, "HEAD", "--", "simfiles")
    changed = sorted(p for p in changed.split("\0") if p.lower().endswith(".ssc"))
    imp = CG.Tree(IMPORT_COMMIT)
    out = []
    data = head.read_many(rels)
    for p in rels:
        out.append((p, content_sha(data[p]), "head", data[p]))
    idata = imp.read_many(changed)
    for p in changed:
        if idata.get(p) is not None:
            out.append((p, content_sha(idata[p]), "import", idata[p]))
    return out


def ctx_path(work, key, csha):
    return os.path.join(work.ctx, key[:16], csha[:2], csha + ".pkl")


def dump_key():
    import corpus_grade as CG
    return sha_text("%s\n%s" % (CG.converter_pin()["pin"], dump_code_hash()))


def cmd_jobs(args, work):
    n = args.shards
    rows = []
    for i in range(n):
        rows.append(dict(id="dump-%d-of-%d" % (i, n), slot=False, timeout=7200,
                         cmd=["{py}", "{tools}/variant_grade.py", "--work", work.dir, "dump", "--shard", "%d/%d" % (i, n)]))
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print("wrote %d jobs to %s" % (len(rows), args.out))


def cmd_dump(args, work):
    key = dump_key()
    files = dump_files()
    uniq = {}
    for rel, csha, which, data in files:
        uniq.setdefault(csha, (rel, data))
    todo = sorted(uniq)
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        todo = todo[i::n]
    A = atomic()
    done = conv = 0
    t0 = time.time()
    for csha in todo:
        path = ctx_path(work, key, csha)
        if A.load_pickle(path, quiet=True) is not None:
            done += 1
            continue
        rel, data = uniq[csha]
        blocks = dump_file_job(data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        A.write_pickle(path, dict(key=key, csha=csha, rel=rel, blocks=blocks))
        conv += 1
        if conv % 20 == 0:
            log("dumped %d files (%d cached) in %.0fs" % (conv, done, time.time() - t0))
    print("VERDICT: OK dumped %d files, %d already cached, %.0fs" % (conv, done, time.time() - t0))


def cmd_index(args, work):
    key = dump_key()
    state, _ = repo_state()
    if state["dirty"]:
        refuse("simfiles/ or the oracle has uncommitted changes:\n" + state["dirty"][:800])
    files = dump_files()
    A = atomic()
    missing = [rel for rel, csha, which, _ in files if A.load_pickle(ctx_path(work, key, csha), quiet=True) is None]
    if missing:
        refuse("%d file(s) are not in the ctx cache yet (run the dump jobs): %s" % (len(missing), ", ".join(missing[:5])))
    man = dict(dump_key=key, dump_code=dump_code_hash(), dump_version=DUMP_VERSION, repo=state, fork=fork_state(),
               files=[dict(rel=rel, csha=csha, which=which) for rel, csha, which, _ in files],
               indexed=time.strftime("%Y-%m-%d %H:%M:%S"))
    A.write_json(work.manifest, man, indent=0)
    print("indexed %d files (%d head, %d import) under dump key %s" % (
        len(files), sum(1 for f in files if f[2] == "head"), sum(1 for f in files if f[2] == "import"), key[:12]))


def check_dump(work):
    """Refuse unless the dump is complete and describes this checkout, this oracle and this
    converter - and the fork has not moved."""
    A = atomic()
    man = A.load_json(work.manifest, quiet=True)
    if not man:
        refuse("no dump manifest (%s): run the dump jobs and `index`" % work.manifest)
    state, oracle = repo_state()
    moved = []
    for k in ("simfiles_tree", "oracle_hash", "converter_pin"):
        if man["repo"].get(k) != state.get(k):
            moved.append("%s %s -> %s" % (k, str(man["repo"].get(k))[:12], str(state.get(k))[:12]))
    if state["dirty"]:
        moved.append("uncommitted changes under simfiles/ or the oracle")
    if man.get("dump_code") != dump_code_hash():
        moved.append("the dump code changed")
    fs = fork_state()
    for k in ("head", "py_sha256", "status_sha"):
        if man["fork"].get(k) != fs.get(k):
            moved.append("converter fork %s %s -> %s" % (k, str(man["fork"].get(k))[:12], str(fs.get(k))[:12]))
    if moved:
        refuse("the repo has moved since the ctx dump - re-dump: " + "; ".join(moved))
    return man, oracle


# ================================================================ loading and the startup self-test

class Corpus:
    """The dumped blocks: by (content sha, tag) for the reachable block of each tag, and all of
    them for the blast radius."""

    def __init__(self, work, man):
        A = atomic()
        self.man = man
        self.files = {}                                   # csha -> {rel, blocks}
        self.head_rel = {}                                # rel -> csha at HEAD
        self.import_rel = {}                              # rel -> csha at the import (changed files)
        for f in man["files"]:
            if f["csha"] not in self.files:
                d = A.load_pickle(ctx_path(work, man["dump_key"], f["csha"]), quiet=True)
                if d is None:
                    refuse("ctx cache entry for %s is missing or unreadable - re-run the dump" % f["rel"])
                self.files[f["csha"]] = d
            (self.head_rel if f["which"] == "head" else self.import_rel)[f["rel"]] = f["csha"]

    def block(self, csha, tag):
        for b in self.files[csha]["blocks"]:
            if b["tag"] == tag and b["reachable"]:
                return b
        return None

    def head_block(self, ssc_rel, tag):
        csha = self.head_rel.get("simfiles/" + ssc_rel)
        return (csha, self.block(csha, tag)) if csha else (None, None)



def selftest_blocks(corpus):
    """Every dumped block: the base model == the converter, total and segment by segment."""
    bad = []
    n = 0
    for csha, f in corpus.files.items():
        for b in f["blocks"]:
            if "error" in b:
                continue
            n += 1
            inp = base_inputs(b)
            counts, taps = seg_counts(inp)
            conv = [t for _, _, t in b["segments"]]
            if taps != b["taps"] or counts != conv or taps + sum(counts) != b["taps"] + b["ticks"]:
                bad.append((f["rel"], b["tag"], b["index"], taps + sum(counts) - b["taps"] - b["ticks"],
                            sum(1 for x, y in zip(counts, conv) if x != y)))
    return n, bad


# ================================================================ the tiers and the split

_NAME = re.compile(r"^(.*) ([SD])(\d+)$")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def family_key(name):
    m = _NAME.match(name)
    t = (m.group(1) if m else name).lower()
    t = re.sub(r"-\s*(short cut|full song|remix)\s*-", " ", t)
    t = re.sub(r"\b(short cut|full song|remix)\b", " ", t)
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)
    t = re.sub(r"\s(\d+|ii|iii|iv|pt\.?\s*\d+|ep\.?\s*\d+)\s*$", " ", t.strip())
    return norm(t) or norm(name)


def named_charts(names):
    """Population charts named in the docs, the tools, README/CLAUDE.md or the loop-bucket spec."""
    texts = []
    for base, dirs, files in os.walk(os.path.join(ROOT, "docs")):
        texts += [os.path.join(base, f) for f in files if f.endswith(".md")]
    texts += [os.path.join(TOOLS, f) for f in os.listdir(TOOLS) if f.endswith(".py") and f != "variant_grade.py"]
    texts += [os.path.join(ROOT, f) for f in ("README.md", "CLAUDE.md", SPEC)]
    blob = []
    for p in texts:
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                blob.append(f.read())
    blob = "\n".join(blob)
    out = set()
    for n in names:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![0-9A-Za-z])", blob):
            out.add(n)
    return out


def side_cells(cert, vid, side):
    e = (cert.get(vid) or {}).get(side) or {}
    try:
        judged = int(e.get("judged"))
        mc = int(e.get("maxcombo"))
        gbm = sum(int(e.get(k) or 0) for k in ("good", "bad", "miss"))
    except (TypeError, ValueError):
        return None
    return dict(judged=judged, maxcombo=mc, clean=mc == judged and gbm == 0)


def cmd_freeze(args, work):
    A = atomic()
    if os.path.exists(work.tiers) and not args.force:
        refuse("the tiers are already frozen (%s): a second freeze would re-draw them after looking" % work.tiers)
    man, oracle, corpus, _ = startup(work, need_tiers=False, workers=args.workers)
    import corpus_grade as CG
    import guards
    pop = oracle.population
    excluded = {}
    for n in pop:
        why = []
        if n in oracle.conflict:
            why.append("oracle_conflict")
        if n in oracle.quarantine:
            why.append("quarantine")
        if any(n == e.get("chart") or pop[n]["key"] == e.get("key") for e in oracle.owner_revisit):
            why.append("owner_revisit")
        if why:
            excluded[n] = why
    imp_tree, head_tree = CG.Tree(IMPORT_COMMIT), CG.Tree("HEAD")
    rels = sorted({"simfiles/" + c["ssc_rel"] for c in pop.values()})
    head_data, imp_data = head_tree.read_many(rels), imp_tree.read_many(rels)
    X = json.load(open(os.path.join(ROOT, EXTRACT_REPORT), encoding="utf-8"))
    xrep = {c["chart"]: c for c in X["charts"]}
    T = json.load(open(os.path.join(ROOT, TICK_REPORT), encoding="utf-8"))
    trep = {c["chart"]: c for c in T["charts"]}
    charts = {}
    for n, c in sorted(pop.items()):
        tag = guards.tag_of(c["key"])
        rel = "simfiles/" + c["ssc_rel"]
        csha, b = corpus.head_block(c["ssc_rel"], tag)
        row = dict(chart=n, pack=c["ssc_rel"].split("/")[0], ssc_rel=c["ssc_rel"], tag=tag, vid=c["vid"], side=c["side"],
                   expected=int(c["expected"]), csha=csha)
        if b is None or "error" in b:
            row["error"] = "no block" if b is None else b["error"]
            charts[n] = row
            continue
        row["implied"] = b["taps"] + b["ticks"]
        row["gap"] = row["implied"] - row["expected"]
        hb = guards.block_sha_text(head_data[rel], tag) if head_data.get(rel) else None
        hh = guards.header_sha_text(head_data[rel]) if head_data.get(rel) else None
        try:
            ib = guards.block_sha_text(imp_data[rel], tag) if imp_data.get(rel) else None
        except LookupError:
            ib = None
        ih = guards.header_sha_text(imp_data[rel]) if imp_data.get(rel) else None
        row["pristine"] = ib is not None and ib == hb and ih == hh
        if not row["pristine"] and imp_data.get(rel) is not None:
            icsha = content_sha(imp_data[rel])
            if icsha not in corpus.files:
                refuse("the import copy of %s is not in the dump" % rel)
            ublk = corpus.block(icsha, tag)
            row["upstream"] = dict(csha=icsha, implied=(ublk["taps"] + ublk["ticks"]) if ublk and "error" not in ublk else None)
        cells = side_cells(oracle.cert, c["vid"], c["side"])
        row["clean_play"] = bool(cells and cells["clean"])
        x = xrep.get(n)
        row["report_current"] = bool(x and x.get("file", {}).get("implied") == row["implied"]
                                     and x.get("file", {}).get("taps") == b["taps"])
        row["notes_ok"] = bool(x and x.get("verdict") == "PARK" and (x.get("reason") or "").startswith(NOTES_OK)
                               and row["report_current"])
        g = row["gap"]
        row["cls"] = ("pristine_exact" if row["pristine"] else "fitted_exact") if g == 0 else (
            "near" if abs(g) <= GATE["near"] else "far")
        row["notes_confirmed_near"] = row["cls"] == "near" and row["notes_ok"]
        row["tier_a"] = g != 0 and abs(g) < GATE["tier_a_diff"] and row["notes_ok"] and row["clean_play"]
        charts[n] = row
    # tier-A clusters
    clusters = []
    for n, row in charts.items():
        if not row.get("tier_a") or n in excluded:
            continue
        t = trep.get(n)
        if not t or t.get("file", {}).get("implied") != row["implied"]:
            continue
        b = corpus.head_block(row["ssc_rel"], row["tag"])[1]
        inp = base_inputs(b)
        counts, _ = seg_counts(inp)
        for k, cl in enumerate(t.get("clusters") or []):
            if cl.get("price") is None or not cl.get("before") or not cl.get("after"):
                continue
            if cl["before"]["frames"] != cl["before"]["of"] or cl["after"]["frames"] != cl["after"]["of"]:
                continue
            b0, b1 = frac(cl["b0"]), frac(cl["b1"])
            wc = window(inp, counts, b0, b1)
            if wc != cl["ticks"]:
                continue
            clusters.append(dict(chart=n, k=k, b0=str(b0), b1=str(b1), ticks=cl["ticks"], price=cl["price"]))
    # the catalog must-not-break set: uncertified mapped charts whose file converts to the P1 count
    cat = {}
    for c in oracle.catalog:
        if c.get("p1_notes") and c.get("type", "")[:1] in "SD":
            for lk in ("p1_level", "p2_level"):
                cat.setdefault((lk, norm(c["song"]), c["type"][0], c.get(lk)), []).append(c)
    catalog = {}
    for n, m in sorted(oracle.smap.items()):
        if n in pop:
            continue
        mm = _NAME.match(n)
        if not mm:
            continue
        k = (norm(mm.group(1)), mm.group(2), int(mm.group(3)))
        hits = cat.get(("p1_level",) + k) or cat.get(("p2_level",) + k) or []
        if len(hits) != 1:
            continue
        try:
            tag = guards.tag_of(m["key"])
        except ValueError:
            continue
        csha, b = corpus.head_block(m["ssc_rel"], tag)
        if b is None or "error" in b:
            continue
        if b["taps"] + b["ticks"] == hits[0]["p1_notes"]:
            catalog[n] = dict(chart=n, pack=m["ssc_rel"].split("/")[0], ssc_rel=m["ssc_rel"], tag=tag, csha=csha,
                              expected=hits[0]["p1_notes"])
    # the split
    names = sorted(charts)
    named = named_charts(set(names) | set(catalog))
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    everything = dict(charts)
    everything.update(catalog)
    for n, r in everything.items():
        union("c:" + n, "f:" + family_key(n))
        union("c:" + n, "s:" + r["ssc_rel"])
        if r.get("vid"):
            union("c:" + n, "v:" + r["vid"])
    salt = args.salt or os.urandom(8).hex()
    groups = defaultdict(list)
    for n in everything:
        groups[find("c:" + n)].append(n)
    split = {}
    for g, members in groups.items():
        if any(m in named for m in members):
            s = "tune"
        else:
            s = "sealed" if int(sha_text(salt + "|" + g)[:8], 16) % 100 < GATE["sealed_share"] else "tune"
        for m in members:
            split[m] = s
    for n in charts:
        charts[n]["split"] = split[n]
    for n in catalog:
        catalog[n]["split"] = split[n]
    doc = dict(frozen=time.strftime("%Y-%m-%d %H:%M:%S"), gate=GATE, salt=salt, dump_key=man["dump_key"],
               repo=man["repo"], tool=tool_hash(), definitions=dict(
                   pristine_exact="exact now; block and song header unchanged since the import %s" % IMPORT_COMMIT,
                   fitted_exact="exact now; block or header edited since the import",
                   near="0 < |implied - certified| <= %d" % GATE["near"],
                   notes_confirmed_near="a near miss parked by %s as '%s', file unchanged since that report" % (EXTRACT_REPORT, NOTES_OK),
                   tier_a="not exact, |diff| < %d, notes-confirmed, clean play (maxcombo = judged, no GOOD/BAD/MISS), "
                          "file unchanged since the reports" % GATE["tier_a_diff"],
                   tier_a_cluster="a %s priced cluster on a tier-A chart, both cuts unanimous, its segments still "
                                  "counting what the report counted" % TICK_REPORT,
                   catalog_exact="an uncertified chart of the merged map whose file converts to its Phoenix 1 catalog count",
                   split="song families joined by shared video or file; sealed with probability %d%% under the salt; "
                         "a group holding a named chart is tune-only" % GATE["sealed_share"]),
               excluded=excluded, named=sorted(named), charts=charts, catalog=catalog, clusters=clusters)
    A.write_json(work.tiers, doc, indent=0, sort_keys=True)
    h = sha_file(work.tiers)
    ledger_append(work, dict(kind="freeze", tiers_sha=h, salt_sha=sha_text(salt), dump_key=man["dump_key"],
                             tool=tool_hash(), model=model_code_hash()))
    summary = tiers_summary(doc)
    print(json.dumps(summary, indent=1))


def tiers_summary(doc):
    ch = doc["charts"]
    ex = doc["excluded"]
    inpop = {n: r for n, r in ch.items() if n not in ex and "error" not in r}
    c = Counter((r["cls"], r["split"]) for r in inpop.values())
    return dict(population=len(ch), excluded=len(ex), errors=sum(1 for r in ch.values() if "error" in r),
                classes={"%s/%s" % k: v for k, v in sorted(c.items())},
                notes_confirmed_near=sum(1 for r in inpop.values() if r["notes_confirmed_near"]),
                notes_confirmed_near_sealed=sum(1 for r in inpop.values() if r["notes_confirmed_near"] and r["split"] == "sealed"),
                tier_a=sorted(n for n, r in inpop.items() if r["tier_a"]),
                tier_a_clusters=len(doc["clusters"]),
                tier_a_clusters_disagreeing=[(c["chart"], c["b0"], c["b1"], c["ticks"], c["price"])
                                             for c in doc["clusters"] if c["ticks"] != c["price"]],
                catalog_exact=len(doc["catalog"]),
                catalog_exact_sealed=sum(1 for r in doc["catalog"].values() if r["split"] == "sealed"),
                named=len(doc["named"]))


def load_tiers(work):
    A = atomic()
    doc = A.load_json(work.tiers, quiet=True)
    if not doc:
        refuse("the tiers are not frozen: run `freeze` first")
    frozen = [r for r in ledger_rows(work) if r["kind"] == "freeze"]
    if not frozen or frozen[-1]["tiers_sha"] != sha_file(work.tiers):
        refuse("tiers.json does not hash to what the ledger's freeze row recorded - it was edited")
    return doc


# ================================================================ the ledger (append-only, hash-chained)

def ledger_rows(work):
    if not os.path.exists(work.ledger):
        return []
    rows = []
    with open(work.ledger, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.strip():
                rows.append(json.loads(line))
    prev = "0" * 64
    for i, r in enumerate(rows):
        body = dict(r)
        h = body.pop("hash")
        if body.get("prev") != prev or sha_text(json.dumps(body, sort_keys=True)) != h:
            refuse("the ledger's hash chain breaks at row %d - it was edited" % (i + 1))
        prev = h
    return rows


def ledger_append(work, row):
    """Append one row under an exclusive lock file (two commands writing at once would otherwise
    each rewrite the file and one row would be lost with the chain still intact)."""
    lock = work.ledger + ".lock"
    t0 = time.time()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - t0 > 120:
                refuse("the ledger lock %s has been held for 2 minutes - check that no variant_grade command is "
                       "running, then remove it" % lock)
            time.sleep(0.5)
    try:
        rows = ledger_rows(work)
        body = dict(row)
        body["prev"] = rows[-1]["hash"] if rows else "0" * 64
        body["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        body["hash"] = sha_text(json.dumps(body, sort_keys=True))
        text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows) + json.dumps(body, sort_keys=True) + "\n"
        atomic().write_text(work.ledger, text, encoding="utf-8", newline="\n")
        return body
    finally:
        os.remove(lock)


# ================================================================ hypotheses and their code hashes

def load_hyp(path):
    path = os.path.abspath(path)
    name = "vg_hyp_" + re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(os.path.basename(path))[0])
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    for k in ("FAMILY", "TITLE", "KIND", "feature", "VARIANTS"):
        if not hasattr(mod, k):
            refuse("%s defines no %s" % (path, k))
    if mod.KIND not in ("count", "parse"):
        refuse("KIND must be 'count' or 'parse'")
    mod.__vg_path__ = path
    return mod


def _strip_doc(node):
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and n.body and \
                isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant) and \
                isinstance(n.body[0].value.value, str):
            n.body = n.body[1:] or [ast.Pass()]
    return node


def closure_hash(mod, fn_name, extra=""):
    """sha256 over the syntax tree (docstrings and comments dropped) of a module-level function
    and of every module-level definition it reaches by name, transitively, plus `extra`."""
    with open(mod.__vg_path__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    defs = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defs[t.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                defs[(a.asname or a.name).split(".")[0]] = node
    seen, todo, parts = set(), [fn_name], []
    while todo:
        n = todo.pop()
        if n in seen or n not in defs:
            continue
        seen.add(n)
        node = defs[n]
        parts.append(ast.dump(_strip_doc(ast.parse(ast.unparse(node)))))
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                todo.append(sub.id)
            elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                todo.append(sub.value.id)
    return sha_text("\n".join(sorted(parts)) + "\n" + extra)


def variant_fn_name(mod, vname):
    text, fn = mod.VARIANTS[vname]
    return fn.__name__


def variant_hash(mod, vname):
    text, fn = mod.VARIANTS[vname]
    return closure_hash(mod, fn.__name__, "%s\n%s\n%s\n%s" % (mod.FAMILY, mod.KIND, vname, text))


def feature_hash(mod):
    return closure_hash(mod, "feature", "%s\n%s" % (mod.FAMILY, mod.TITLE))


def registrations(work):
    rows = ledger_rows(work)
    fam = {r["family"]: r for r in rows if r["kind"] == "family"}
    var = {(r["family"], r["variant"]): r for r in rows if r["kind"] == "register"}
    return rows, fam, var


def check_caps(work, adding_variants=0, adding_family=False):
    rows, fam, var = registrations(work)
    freeze = [r for r in rows if r["kind"] == "freeze"]
    if freeze:
        t0 = time.mktime(time.strptime(freeze[0]["at"], "%Y-%m-%d %H:%M:%S"))
        if (time.time() - t0) / 3600 > GATE["max_hours"]:
            refuse("the 12-hour cap from the freeze is spent")
    tested = [f for f in fam.values() if f.get("reach") == "TESTABLE"]
    if adding_family and len(tested) >= GATE["max_families"]:
        refuse("the family cap (%d) is spent" % GATE["max_families"])
    if len(var) + adding_variants > GATE["max_variants"]:
        refuse("the variant cap (%d) would be exceeded (%d registered)" % (GATE["max_variants"], len(var)))
    stops = [r for r in rows if r["kind"] == "stop"]
    if stops:
        refuse("the bucket stopped: %s" % stops[-1]["why"])


# ================================================================ grading (a worker pool over files)

_G = {}


def _grade_init(hyp_paths, want_all):
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)       # BelowNormal
    _G["mods"] = {p: load_hyp(p) for p in hyp_paths}
    _G["all"] = want_all


def _grade_file(job):
    """One ctx file -> {(tag, index): {"base": total, variant key: total, "_counts": {...}}} for the
    blocks asked for (reachable ones, or every one when grading the blast radius)."""
    path, variants, windows = job
    A = atomic()
    d = A.load_pickle(path, quiet=True)
    out = {}
    for b in d["blocks"]:
        if "error" in b:
            continue
        inp = base_inputs(b)
        counts, taps = seg_counts(inp)
        res = dict(base=taps + sum(counts))
        # the startup self-test, block by block: the base model is the converter, segment by segment
        res["_ok"] = taps == b["taps"] and counts == [t for _, _, t in b["segments"]] and             res["base"] == b["taps"] + b["ticks"]
        wins = windows.get(b["tag"]) if b["reachable"] else None
        if wins:
            res["_w_base"] = [window(inp, counts, frac(Fraction(b0)), frac(Fraction(b1))) for b0, b1 in wins]
        blk = Block(b, d["rel"])
        for vkey, (hp, vname) in variants.items():
            mod = _G["mods"][hp]
            text, fn = mod.VARIANTS[vname]
            try:
                if not mod.feature(blk):
                    res[vkey] = res["base"]
                    if wins:
                        res["_w_" + vkey] = res["_w_base"]
                    continue
                v = inp.copy()
                fn(blk, v)
                c2, t2 = seg_counts(v)
                res[vkey] = t2 + sum(c2)
                if wins:
                    res["_w_" + vkey] = [window(v, c2, frac(Fraction(b0)), frac(Fraction(b1))) for b0, b1 in wins]
            except (MemoryError, OSError):
                raise
            except Exception as ex:
                res[vkey] = "ERR %s: %s" % (type(ex).__name__, str(ex)[:120])
        out[(b["tag"], b["index"], b["reachable"])] = res
    return d["csha"], out


def run_grade(work, man, hyps, variants, windows_by_csha, workers):
    """variants: {vkey: (hyp path, variant name)}; returns {csha: {(tag, index, reachable): res}}."""
    from multiprocessing import Pool
    workers = max(1, min(workers, GATE["max_workers"]))
    jobs = []
    for csha in sorted({f["csha"] for f in man["files"]}):
        jobs.append((ctx_path(work, man["dump_key"], csha), variants, windows_by_csha.get(csha, {})))
    t0 = time.time()
    out = {}
    try:
        with Pool(workers, initializer=_grade_init, initargs=(sorted({p for p, _ in variants.values()}), True)) as pool:
            for csha, res in pool.imap_unordered(_grade_file, jobs, chunksize=4):
                out[csha] = res
    except (MemoryError, OSError) as ex:
        refuse("the machine stopped the grade: %s" % ex, TEMPFAIL)
    log("graded %d files, %d variant(s), in %.1fs on %d workers" % (len(jobs), len(variants), time.time() - t0, workers))
    return out


def chart_value(res_by_csha, csha, tag, key):
    for (t, i, reach), r in (res_by_csha.get(csha) or {}).items():
        if t == tag and reach:
            return r.get(key)
    return None


# ================================================================ the gate

def evaluate(tiers, vals, uvals, cvals, clvals, scope):
    """vals: {chart: variant total} for population charts; uvals: {chart: variant total on its
    upstream block}; cvals: {catalog chart: variant total}; clvals: {cluster index: variant window}.
    scope: a set of splits ("tune", "sealed"). -> result dict."""
    ch, ex = tiers["charts"], tiers["excluded"]
    r = dict(pristine_breaks=[], fitted_breaks_excused=[], fitted_breaks=[], catalog_breaks=[], fixes=[],
             notes_fixes=[], worse=[], better=[], errors=[], upstream_newly_exact=[], clusters_lost=[], clusters_gained=[],
             cluster_base_agree=0, cluster_variant_agree=0, touched=0)
    for n, row in ch.items():
        if n in ex or "error" in row or row["split"] not in scope:
            continue
        v = vals.get(n)
        if isinstance(v, str) or v is None:
            r["errors"].append(n)
            continue
        base, want = row["implied"], row["expected"]
        if v != base:
            r["touched"] += 1
        if base == want and v != want:
            if row["pristine"]:
                r["pristine_breaks"].append(n)
            else:
                u = uvals.get(n)
                if row.get("upstream") and u == want:
                    r["fitted_breaks_excused"].append(n)
                else:
                    r["fitted_breaks"].append(n)
        elif base != want and v == want:
            r["fixes"].append(n)
            if row["notes_confirmed_near"]:
                r["notes_fixes"].append(n)
        elif base != want:
            if abs(v - want) > abs(base - want):
                r["worse"].append(n)
            elif abs(v - want) < abs(base - want):
                r["better"].append(n)
        if not row["pristine"] and row.get("upstream") and row["upstream"].get("implied") is not None:
            u = uvals.get(n)
            if row["upstream"]["implied"] != want and u == want:
                r["upstream_newly_exact"].append(n)
    for n, row in tiers["catalog"].items():
        if row["split"] not in scope:
            continue
        v = cvals.get(n)
        if v != row["expected"]:
            r["catalog_breaks"].append(n)
    for k, cl in enumerate(tiers["clusters"]):
        if ch[cl["chart"]]["split"] not in scope:
            continue
        v = clvals.get(k)
        b = cl["ticks"] == cl["price"]
        a = v == cl["price"]
        r["cluster_base_agree"] += b
        r["cluster_variant_agree"] += a
        if b and not a:
            r["clusters_lost"].append("%s [%s, %s]" % (cl["chart"], cl["b0"], cl["b1"]))
        if a and not b:
            r["clusters_gained"].append("%s [%s, %s]" % (cl["chart"], cl["b0"], cl["b1"]))
    r["notes_fix_packs"] = sorted({ch[n]["pack"] for n in r["notes_fixes"]})
    breaks = len(r["pristine_breaks"]) + len(r["fitted_breaks"]) + len(r["fitted_breaks_excused"])
    r["net"] = len(r["fixes"]) - breaks
    return r


def tune_pass(r):
    why = []
    if r["errors"]:
        why.append("%d charts errored" % len(r["errors"]))
    if r["pristine_breaks"]:
        why.append("%d pristine breaks" % len(r["pristine_breaks"]))
    if r["fitted_breaks"]:
        why.append("%d unexcused fitted breaks" % len(r["fitted_breaks"]))
    if r["catalog_breaks"]:
        why.append("%d catalog breaks" % len(r["catalog_breaks"]))
    if r["clusters_lost"]:
        why.append("%d tier-A clusters lost" % len(r["clusters_lost"]))
    if len(r["notes_fixes"]) < 1:
        why.append("no notes-confirmed near-miss fix")
    if len(r["fixes"]) <= len(r["pristine_breaks"]) + len(r["fitted_breaks"]) + len(r["fitted_breaks_excused"]):
        why.append("fixes do not exceed breaks")
    return not why, why


def full_pass(sealed, whole):
    why = []
    if sealed["errors"] or whole["errors"]:
        why.append("errors")
    for k in ("pristine_breaks", "fitted_breaks", "catalog_breaks", "clusters_lost"):
        if sealed[k]:
            why.append("sealed %s: %d" % (k, len(sealed[k])))
        if whole[k]:
            why.append("%s: %d" % (k, len(whole[k])))
    if sealed["fitted_breaks_excused"]:
        why.append("sealed excused fitted breaks: %d (the sealed split admits no break)" % len(sealed["fitted_breaks_excused"]))
    if len(sealed["fixes"]) < GATE["sealed_min_fixes"]:
        why.append("sealed fixes %d < %d" % (len(sealed["fixes"]), GATE["sealed_min_fixes"]))
    if len(whole["notes_fixes"]) < GATE["min_fixes"]:
        why.append("notes-confirmed near-miss fixes %d < %d" % (len(whole["notes_fixes"]), GATE["min_fixes"]))
    if len(whole["notes_fix_packs"]) < GATE["min_packs"]:
        why.append("notes-confirmed fixes span %d pack(s) < %d" % (len(whole["notes_fix_packs"]), GATE["min_packs"]))
    return not why, why


def collect(tiers, res, vkey):
    """Per-chart variant values from a grade result."""
    ch = tiers["charts"]
    vals, uvals, cvals, clvals = {}, {}, {}, {}
    for n, row in ch.items():
        if "error" in row:
            continue
        vals[n] = chart_value(res, row["csha"], row["tag"], vkey)
        if row.get("upstream"):
            uvals[n] = chart_value(res, row["upstream"]["csha"], row["tag"], vkey)
    for n, row in tiers["catalog"].items():
        cvals[n] = chart_value(res, row["csha"], row["tag"], vkey)
    for k, cl in enumerate(tiers["clusters"]):
        row = ch[cl["chart"]]
        for (t, i, reach), r in (res.get(row["csha"]) or {}).items():
            if t == row["tag"] and reach:
                wl = r.get("_w_" + vkey)
                idx = cluster_windows(tiers).get(row["csha"], {}).get(t, []).index((cl["b0"], cl["b1"]))
                clvals[k] = wl[idx] if wl else None
    return vals, uvals, cvals, clvals


def cluster_windows(tiers):
    """{csha: {tag: [(b0, b1), ...]}} for the tier-A clusters (plain dicts: they travel to workers)."""
    out = {}
    for cl in tiers["clusters"]:
        row = tiers["charts"][cl["chart"]]
        w = out.setdefault(row["csha"], {}).setdefault(row["tag"], [])
        if (cl["b0"], cl["b1"]) not in w:
            w.append((cl["b0"], cl["b1"]))
    return out


def blast_radius(tiers, res, vkey, sealed_detail):
    """Every block the variant changes, by what it is. Before a reveal only what does not say how
    a sealed chart fared: changed blocks by kind, and exactness on tune charts."""
    idx = {}
    for n, row in tiers["charts"].items():
        if "error" not in row:
            idx[(row["csha"], row["tag"])] = ("certified", n, row)
    for n, row in tiers["catalog"].items():
        idx[(row["csha"], row["tag"])] = ("catalog", n, row)
    out = Counter()
    for csha, blocks in res.items():
        for (tag, i, reach), r in blocks.items():
            v, b = r.get(vkey), r.get("base")
            if v == b:
                continue
            kind = idx.get((csha, tag)) if reach else None
            if kind is None:
                out["other block" + ("" if reach else " (shadowed tag)")] += 1
                continue
            k, n, row = kind
            if k == "certified":
                sp = row["split"]
                if sp == "sealed" and not sealed_detail:
                    out["certified (sealed)"] += 1
                else:
                    was = row["implied"] == row["expected"]
                    now = v == row["expected"]
                    out["certified %s: %s -> %s" % (sp, "exact" if was else "off", "exact" if now else "off")] += 1
            else:
                sp = row["split"]
                if sp == "sealed" and not sealed_detail:
                    out["catalog-exact (sealed)"] += 1
                else:
                    out["catalog-exact %s: broken" % sp] += 1
    return dict(sorted(out.items()))


# ================================================================ commands

def startup(work, need_tiers=True, need_corpus=True, workers=4):
    """Every tripwire, then the startup self-test (the base model against the converter on every
    dumped block, segment by segment, in the worker pool), before anything is graded."""
    if not sys.flags.dont_write_bytecode:
        refuse("run with -B (and PYTHONDONTWRITEBYTECODE=1)")
    if not sys.flags.utf8_mode:
        refuse("run with -X utf8")
    man, oracle = check_dump(work)
    tiers = load_tiers(work) if need_tiers else None
    res = run_grade(work, man, [], {}, {}, workers)
    n = sum(len(v) for v in res.values())
    bad = [(csha, k) for csha, v in res.items() for k, r in v.items() if not r["_ok"]]
    if bad:
        refuse("the base model disagrees with the converter on %d of %d blocks, e.g. %s" % (len(bad), n, bad[:5]), 1)
    log("startup self-test: the base model reproduces the converter on all %d dumped blocks, segment by segment" % n)
    corpus = Corpus(work, man) if need_corpus else None
    return man, oracle, corpus, tiers


def cmd_selftest(args, work):
    man, oracle, corpus, _ = startup(work, need_tiers=False, workers=args.workers)
    n, bad = selftest_blocks(corpus)                     # the same check again, serially, in this process
    print("serial re-check: the base model reproduces the converter on %d of %d blocks" % (n - len(bad), n))
    import corpus_grade as CG
    import guards
    # the dump against the gate's own grade: every certified chart's implied as corpus_grade has it
    g = json.load(open(os.path.join(ROOT, "sources", "corpus-grade.json"), encoding="utf-8"))
    rows = {r["chart"]: r for r in g["charts"]}
    mism, n = [], 0
    for name, c in oracle.population.items():
        tag = guards.tag_of(c["key"])
        csha, b = corpus.head_block(c["ssc_rel"], tag)
        r = rows.get(name)
        if r is None or b is None or "error" in b:
            mism.append((name, "missing"))
            continue
        n += 1
        if b["taps"] != r["taps"] or b["taps"] + b["ticks"] != r["implied"]:
            mism.append((name, b["taps"] + b["ticks"], r["implied"]))
    if g.get("converter_pin") != CG.converter_pin()["pin"]:
        mism.append(("corpus-grade.json converter pin", g.get("converter_pin")))
    print("certified charts: %d; the dump's taps + ticks equal sources/corpus-grade.json on %d (mismatches %d)" % (
        len(oracle.population), n - len([m for m in mism if len(m) == 3]), len(mism)))
    for m in mism[:10]:
        print("  MISMATCH", m)
    # planted checks on the model: an identity edit changes nothing; one extra head event moves
    # exactly one block by one; an exclusion over a whole block's holds removes its lattice points
    some = [b for f in list(corpus.files.values())[:40] for b in f["blocks"] if "error" not in b and b["real_holds"]]
    planted = []
    for b in some[:60]:
        inp = base_inputs(b)
        t0 = total(inp)
        v = inp.copy()
        planted.append(total(v) == t0)
        v = inp.copy()
        v.extra.append((frac(b["real_holds"][0][0]), 1))
        planted.append(total(v) == t0 + 1)
        v = inp.copy()
        v.excl.append((Fraction(-1), Fraction(10 ** 6)))
        v.heads = []
        planted.append(total(v) == b["taps"])          # nothing judged inside the range, no heads
    ok = all(planted) and not mism and not bad
    print("planted model checks: %d of %d as intended" % (sum(planted), len(planted)))
    print("VERDICT: %s" % ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


def cmd_family_begin(args, work):
    """A family boundary: re-check the dump (it must describe the repo as it is now), then the
    reach precheck. An UNTESTABLE family is recorded and spends nothing."""
    man, oracle, corpus, tiers = startup(work, workers=args.workers)
    mod = load_hyp(args.hyp)
    rows, fam, var = registrations(work)
    if mod.FAMILY in fam:
        print("family %s already begun: %s" % (mod.FAMILY, fam[mod.FAMILY]["reach"]))
        return
    check_caps(work, adding_family=True)
    ch, ex = tiers["charts"], tiers["excluded"]
    carriers = {}
    for n, row in ch.items():
        if n in ex or "error" in row:
            continue
        b = corpus.block(row["csha"], row["tag"])
        try:
            carriers[n] = bool(mod.feature(Block(b)))
        except Exception as e:
            refuse("feature() raised on %s: %s" % (n, e))
    ncn = [n for n, row in ch.items() if carriers.get(n) and row["notes_confirmed_near"]]
    packs = sorted({ch[n]["pack"] for n in ncn})
    tune_ncn = [n for n in ncn if ch[n]["split"] == "tune"]
    sealed_off = [n for n, row in ch.items() if carriers.get(n) and row["split"] == "sealed" and row["cls"] in ("near", "far")]
    must = Counter(row["cls"] for n, row in ch.items() if carriers.get(n))
    why = []
    if len(ncn) < GATE["min_fixes"]:
        why.append("only %d notes-confirmed near miss(es) carry the feature (the gate needs %d fixes)" % (len(ncn), GATE["min_fixes"]))
    if len(packs) < GATE["min_packs"]:
        why.append("they span %d pack(s) (the gate needs %d)" % (len(packs), GATE["min_packs"]))
    if not tune_ncn:
        why.append("none of them is in the tune split")
    if not sealed_off:
        why.append("no sealed chart off its count carries it (the hold-out cannot show a fix)")
    verdict = "UNTESTABLE" if why else "TESTABLE"
    row = ledger_append(work, dict(kind="family", family=mod.FAMILY, title=mod.TITLE, feature_hash=feature_hash(mod),
                                   reach=verdict, why=why, carriers=dict(must), notes_confirmed_carriers=sorted(ncn),
                                   packs=packs, dump_key=man["dump_key"], tiers_sha=sha_file(work.tiers)))
    print("family %s (%s): %s" % (mod.FAMILY, mod.TITLE, verdict))
    print("  carriers by class: %s" % dict(must))
    print("  notes-confirmed near misses carrying it: %d %s, packs %s" % (len(ncn), sorted(ncn), packs))
    for w in why:
        print("  - " + w)


def cmd_register(args, work):
    load_tiers(work)
    mod = load_hyp(args.hyp)
    rows, fam, var = registrations(work)
    if mod.FAMILY not in fam:
        refuse("begin the family first (family-begin)")
    if fam[mod.FAMILY]["reach"] != "TESTABLE":
        refuse("family %s is %s: nothing to register" % (mod.FAMILY, fam[mod.FAMILY]["reach"]))
    if fam[mod.FAMILY]["feature_hash"] != feature_hash(mod):
        refuse("the family's feature() changed since family-begin")
    names = args.variants or sorted(mod.VARIANTS)
    new = [v for v in names if (mod.FAMILY, v) not in var]
    check_caps(work, adding_variants=len(new))
    for v in names:
        h = variant_hash(mod, v)
        if (mod.FAMILY, v) in var:
            if var[(mod.FAMILY, v)]["code_hash"] != h:
                refuse("%s/%s is registered under %s and now hashes %s - a re-edit is a new variant" % (
                    mod.FAMILY, v, var[(mod.FAMILY, v)]["code_hash"][:12], h[:12]))
            print("already registered %s/%s %s" % (mod.FAMILY, v, h[:12]))
            continue
        ledger_append(work, dict(kind="register", family=mod.FAMILY, variant=v, code_hash=h, text=mod.VARIANTS[v][0],
                                 hyp_kind=mod.KIND))
        print("registered %s/%s %s" % (mod.FAMILY, v, h[:12]))


def _prepare(args, work, mod, names):
    rows, fam, var = registrations(work)
    for v in names:
        r = var.get((mod.FAMILY, v))
        if r is None:
            refuse("%s/%s is not registered" % (mod.FAMILY, v))
        if r["code_hash"] != variant_hash(mod, v):
            refuse("%s/%s changed since it was registered" % (mod.FAMILY, v))
    if fam[mod.FAMILY]["feature_hash"] != feature_hash(mod):
        refuse("the family's feature() changed since family-begin")
    return {"%s/%s" % (mod.FAMILY, v): (mod.__vg_path__, v) for v in names}


def cmd_grade(args, work):
    man, oracle, corpus, tiers = startup(work, need_corpus=False, workers=args.workers)
    mod = load_hyp(args.hyp)
    names = args.variants or sorted(mod.VARIANTS)
    variants = _prepare(args, work, mod, names)
    res = run_grade(work, man, [mod], variants, cluster_windows(tiers), args.workers)
    out = {}
    for vkey in variants:
        vals, uvals, cvals, clvals = collect(tiers, res, vkey)
        r = evaluate(tiers, vals, uvals, cvals, clvals, {"tune"})
        ok, why = tune_pass(r)
        br = blast_radius(tiers, res, vkey, sealed_detail=False)
        fam, v = vkey.split("/", 1)
        summary = dict(kind="grade", family=fam, variant=v, code_hash=variant_hash(mod, v), tool=tool_hash(),
                       model=model_code_hash(), scope="tune", tune_pass=ok, why=why,
                       counts={k: (len(x) if isinstance(x, list) else x) for k, x in r.items()},
                       fixes=r["fixes"], notes_fixes=r["notes_fixes"], pristine_breaks=r["pristine_breaks"][:40],
                       fitted_breaks=r["fitted_breaks"][:40], fitted_breaks_excused=r["fitted_breaks_excused"][:40],
                       catalog_breaks=r["catalog_breaks"][:40], clusters_lost=r["clusters_lost"],
                       clusters_gained=r["clusters_gained"], blast=br)
        ledger_append(work, summary)
        out[vkey] = summary
        print("%-40s %s  net %+d  fixes %d (notes-confirmed %d)  pristine breaks %d  fitted %d (+%d excused)  "
              "catalog %d  worse %d  clusters %d->%d%s" % (
                  vkey, "TUNE-PASS" if ok else "tune-fail", r["net"], len(r["fixes"]), len(r["notes_fixes"]),
                  len(r["pristine_breaks"]), len(r["fitted_breaks"]), len(r["fitted_breaks_excused"]),
                  len(r["catalog_breaks"]), len(r["worse"]), r["cluster_base_agree"], r["cluster_variant_agree"],
                  "" if ok else "  [" + "; ".join(why) + "]"))
        print("   blast radius (every block): %s" % br)
    A = atomic()
    A.write_json(os.path.join(work.grades, "%s-%s.json" % (mod.FAMILY, time.strftime("%Y%m%d-%H%M%S"))), out, indent=1)


def cmd_reveal(args, work):
    man, oracle, corpus, tiers = startup(work, need_corpus=False, workers=args.workers)
    mod = load_hyp(args.hyp)
    variants = _prepare(args, work, mod, [args.variant])
    rows = ledger_rows(work)
    reveals = [r for r in rows if r["kind"] == "reveal"]
    if len(reveals) >= GATE["max_reveals"]:
        refuse("the sealed hold-out has had its %d reveals" % GATE["max_reveals"])
    vkey = "%s/%s" % (mod.FAMILY, args.variant)
    graded = [r for r in rows if r["kind"] == "grade" and r["family"] == mod.FAMILY and r["variant"] == args.variant
              and r["code_hash"] == variant_hash(mod, args.variant)]
    if not graded or not graded[-1]["tune_pass"]:
        refuse("%s has not passed the tune gate under its registered hash - a reveal is only for a tune pass" % vkey)
    res = run_grade(work, man, [mod], variants, cluster_windows(tiers), args.workers)
    vals, uvals, cvals, clvals = collect(tiers, res, vkey)
    sealed = evaluate(tiers, vals, uvals, cvals, clvals, {"sealed"})
    whole = evaluate(tiers, vals, uvals, cvals, clvals, {"tune", "sealed"})
    ok, why = full_pass(sealed, whole)
    br = blast_radius(tiers, res, vkey, sealed_detail=True)
    if ok and mod.KIND == "parse":
        why.append("parse-level: stage 2 (patched scratch converter + clean-room) must reproduce it before it wins")
    row = ledger_append(work, dict(kind="reveal", family=mod.FAMILY, variant=args.variant, code_hash=variant_hash(mod, args.variant),
                                   n=len(reveals) + 1, gate_pass=ok, why=why,
                                   sealed={k: (len(x) if isinstance(x, list) else x) for k, x in sealed.items()},
                                   whole={k: (len(x) if isinstance(x, list) else x) for k, x in whole.items()},
                                   whole_fixes=whole["fixes"], whole_notes_fixes=whole["notes_fixes"], blast=br))
    print(json.dumps(row, indent=1))


def cmd_null(args, work):
    """Random structural predicates, +/-1 event per matching hold, through the same full gate."""
    import numpy as np
    man, oracle, corpus, tiers = startup(work, workers=args.workers)
    ch, ex = tiers["charts"], tiers["excluded"]
    # per-hold structural features over the population, the catalog set and the upstream blocks
    units = []                                           # (kind, name) per graded unit
    feats, owner = [], []
    NAMES = ["len", "headden", "tailden", "rate", "xbpm", "xtick", "tick0", "tailstop", "headstop", "excl",
             "stagger", "taillat", "headbpm", "tailrow", "scroll0"]

    def dcls(x):
        d = x.denominator
        return {1: 0, 2: 1, 4: 2, 8: 3}.get(d, 4 if d & (d - 1) == 0 else (5 if d % 3 == 0 else 6))

    def rcls(r):
        return {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 6: 5, 8: 6, 12: 7}.get(r, 8 if r >= 16 else 9)

    def lbin(L):
        for i, lim in enumerate((Fraction(1, 4), Fraction(1, 2), Fraction(1), Fraction(2), Fraction(4))):
            if L <= lim:
                return i
        return 5

    def hold_feats(b):
        blk = Block(b)
        inp = base_inputs(b)
        sp = Spans(inp.tick)
        tick_b = sorted(a for a, _, _ in sp.items if a > 0)
        zero = [(a, e) for a, e, r in sp.items if r == 0]
        bpm = blk.pairs("BPMS")
        bpm_b = sorted(x for x, _ in bpm if x > 0)
        sd = {x for x, v in blk.pairs("STOPS") + blk.pairs("DELAYS") if v != 0}
        s0 = blk.spans_of("SCROLLS", lambda v: v == 0)
        heldl = inp.held
        hs = [h for h, _ in heldl]
        cnt = [0] * len(heldl)
        rh = blk.real_holds
        for h, t in rh:
            i = bisect.bisect_right(hs, h) - 1
            if i >= 0:
                cnt[i] += 1
        rowset = inp.tap_rows | inp.head_rows
        out = []
        for h, t in rh:
            i = bisect.bisect_right(hs, h) - 1
            inside = lambda xs: bisect.bisect_right(xs, h) < bisect.bisect_left(xs, t)
            rt = sp.rate_at(t)
            out.append((lbin(t - h), dcls(h), dcls(t), rcls(sp.rate_at(h)), int(inside(bpm_b)), int(inside(tick_b)),
                        int(any(a < t and (e is None or e > h) for a, e in zero)), int(t in sd), int(h in sd),
                        int(any(a < t and e > h for a, e in inp.excl)), int(i >= 0 and cnt[i] >= 2),
                        int(rt > 0 and (t * rt).denominator == 1), int(h in set(bpm_b)), int(t in rowset),
                        int(in_spans(h, s0))))
        return out

    holdcl = []                                          # the tier-A cluster a hold's head lies in, or -1
    cl_by_chart = defaultdict(list)
    for k, cl in enumerate(tiers["clusters"]):
        cl_by_chart[cl["chart"]].append((k, Fraction(cl["b0"]), Fraction(cl["b1"])))
    for n, row in sorted(ch.items()):
        if n in ex or "error" in row:
            continue
        b = corpus.block(row["csha"], row["tag"])
        f = hold_feats(b)
        units.append(("c", n))
        feats += f
        owner += [len(units) - 1] * len(f)
        for h, t in Block(b).real_holds:
            holdcl.append(next((k for k, b0, b1 in cl_by_chart.get(n, ()) if b0 <= h <= b1), -1))
        if row.get("upstream") and not row["pristine"]:
            ub = corpus.block(row["upstream"]["csha"], row["tag"])
            if ub is not None and "error" not in ub:
                f = hold_feats(ub)
                units.append(("u", n))
                feats += f
                owner += [len(units) - 1] * len(f)
                holdcl += [-1] * len(f)
    for n, row in sorted(tiers["catalog"].items()):
        b = corpus.block(row["csha"], row["tag"])
        f = hold_feats(b)
        units.append(("k", n))
        feats += f
        owner += [len(units) - 1] * len(f)
        holdcl += [-1] * len(f)
    FX = np.array(feats, dtype=np.int16)
    HC = np.array(holdcl, dtype=np.int32)
    NCL = len(tiers["clusters"])
    OW = np.array(owner, dtype=np.int32)
    U = len(units)
    conds = [(fi, v) for fi in range(len(NAMES)) for v in sorted(set(FX[:, fi].tolist()))]
    masks = {cv: FX[:, cv[0]] == cv[1] for cv in conds}
    rnd = random.Random(args.seed)
    rules = [(cv,) for cv in conds] + [(a, b) for a, b in itertools.combinations(conds, 2) if a[0] != b[0]]
    triples = [t for t in itertools.combinations(conds, 3) if len({x[0] for x in t}) == 3]
    rnd.shuffle(triples)
    rules += triples[:args.triples]
    unit_index = {u: i for i, u in enumerate(units)}
    # vectors over the population charts, so a rule that breaks anything is dismissed in numpy;
    # only a rule with no break and a fix goes through evaluate(), the gate's own function
    cn = [n for (k, n) in units if k == "c"]
    ci = np.array([unit_index[("c", n)] for n in cn])
    ui = np.array([unit_index.get(("u", n), -1) for n in cn])
    base = np.array([ch[n]["implied"] for n in cn])
    want = np.array([ch[n]["expected"] for n in cn])
    exact = base == want
    prist = np.array([bool(ch[n]["pristine"]) for n in cn])
    upimp = np.array([(ch[n].get("upstream") or {}).get("implied") if (ch[n].get("upstream") or {}).get("implied") is not None
                      else -10 ** 9 for n in cn])
    notes = np.array([bool(ch[n]["notes_confirmed_near"]) for n in cn])
    packs = np.array([ch[n]["pack"] for n in cn])
    ki = np.array([unit_index[("k", n)] for n in sorted(tiers["catalog"])], dtype=np.int64)
    passers = []
    tally = Counter()
    for rule in rules:
        m = masks[rule[0]]
        for e in rule[1:]:
            m = m & masks[e]
        if not m.any():
            continue
        per = np.bincount(OW[m], minlength=U)
        hc = HC[m]
        percl = np.bincount(hc[hc >= 0], minlength=NCL) if NCL else []
        pc = per[ci]
        for d in (1, -1):
            tally["rules"] += 1
            changed = pc > 0
            if (exact & prist & changed).any() or (len(ki) and (per[ki] > 0).any()):
                continue
            fitted = exact & ~prist & changed
            up_new = np.where(ui >= 0, upimp + d * per[np.maximum(ui, 0)], -10 ** 9)
            if (fitted & (up_new != want)).any():
                continue
            tally["0 breaks"] += 1
            fixes = ~exact & (base + d * pc == want)
            nf = fixes & notes
            if nf.sum() >= GATE["min_fixes"] and len(set(packs[nf].tolist())) >= GATE["min_packs"]:
                tally["0 breaks, >= 3 notes-confirmed fixes in >= 2 packs"] += 1
            if not fixes.any():
                continue
            vals, uvals, cvals = {}, {}, {}
            for (k, n), i in unit_index.items():
                if k == "c":
                    vals[n] = ch[n]["implied"] + d * int(per[i])
                elif k == "u":
                    uvals[n] = ch[n]["upstream"]["implied"] + d * int(per[i]) if ch[n]["upstream"]["implied"] is not None else None
                else:
                    cvals[n] = tiers["catalog"][n]["expected"] + d * int(per[i])
            clvals = {k: cl["ticks"] + d * int(percl[k]) for k, cl in enumerate(tiers["clusters"])}
            tune = evaluate(tiers, vals, uvals, cvals, clvals, {"tune"})
            ok_t, _ = tune_pass(tune)
            if ok_t:
                tally["tune pass"] += 1
            sealed = evaluate(tiers, vals, uvals, cvals, clvals, {"sealed"})
            whole = evaluate(tiers, vals, uvals, cvals, clvals, {"tune", "sealed"})
            ok, why = full_pass(sealed, whole)
            if ok:
                tally["full gate pass"] += 1
            if ok_t and ok:
                passers.append(dict(rule=[(NAMES[f], v) for f, v in rule], delta=d, fixes=whole["fixes"][:8]))
    row = ledger_append(work, dict(kind="null", seed=args.seed, rules=tally["rules"], tally=dict(tally), passers=len(passers),
                                   passer_rules=passers[:20], features=NAMES, units=U))
    print(json.dumps(dict(tally=dict(tally), passers=len(passers), examples=passers[:10]), indent=1))
    print("VERDICT: %s" % ("PASS (0 random rules pass the gate)" if not passers else "FAIL: %d random rules pass" % len(passers)))


def cmd_status(args, work):
    rows = ledger_rows(work)
    rows_, fam, var = registrations(work)
    print("ledger rows %d; families %d (%d testable); variants registered %d of %d; reveals %d of %d" % (
        len(rows), len(fam), sum(1 for f in fam.values() if f["reach"] == "TESTABLE"), len(var), GATE["max_variants"],
        sum(1 for r in rows if r["kind"] == "reveal"), GATE["max_reveals"]))
    for r in rows:
        if r["kind"] in ("freeze", "family", "reveal", "null", "stop"):
            print(" ", r["at"], r["kind"], {k: v for k, v in r.items() if k in ("family", "variant", "reach", "why", "gate_pass",
                                                                               "passers", "rules", "tiers_sha")})
        elif r["kind"] == "grade":
            print(" ", r["at"], "grade", r["family"], r["variant"], r["code_hash"][:12], "tune_pass=%s" % r["tune_pass"],
                  "net %+d" % r["counts"]["net"])


def cmd_family_end(args, work):
    """Close a family: its net is the best tune net (fixes - breaks) of its graded variants. Three
    TESTABLE families in a row with no positive net stop the bucket (a stop row); an UNTESTABLE
    family spent nothing and neither extends nor breaks the streak."""
    mod = load_hyp(args.hyp)
    rows, fam, var = registrations(work)
    if mod.FAMILY not in fam:
        refuse("family %s was never begun" % mod.FAMILY)
    if any(r["kind"] == "family-end" and r["family"] == mod.FAMILY for r in rows):
        refuse("family %s is already closed" % mod.FAMILY)
    reach = fam[mod.FAMILY]["reach"]
    grades = [r for r in rows if r["kind"] == "grade" and r["family"] == mod.FAMILY]
    reveals = [r for r in rows if r["kind"] == "reveal" and r["family"] == mod.FAMILY]
    best = max((r["counts"]["net"] for r in grades), default=0)
    zero = reach == "TESTABLE" and best <= 0 and not any(r["gate_pass"] for r in reveals)
    ledger_append(work, dict(kind="family-end", family=mod.FAMILY, reach=reach, graded=len(grades), best_tune_net=best,
                             zero_net=zero, winner=any(r["gate_pass"] for r in reveals)))
    rows = ledger_rows(work)
    ends = [r for r in rows if r["kind"] == "family-end" and r["reach"] == "TESTABLE"]
    streak = 0
    for r in reversed(ends):
        if not r["zero_net"]:
            break
        streak += 1
    print("family %s closed: %s, %d variant(s) graded, best tune net %+d%s; zero-net streak %d of %d" % (
        mod.FAMILY, reach, len(grades), best, " (zero net)" if zero else "", streak, GATE["stop_streak"]))
    if any(r["gate_pass"] for r in reveals):
        ledger_append(work, dict(kind="stop", why="a winner: %s" % mod.FAMILY))
        print("STOP: a variant cleared the gate - bring it to the owner")
    elif streak >= GATE["stop_streak"]:
        ledger_append(work, dict(kind="stop", why="%d families in a row with zero net fixes" % streak))
        print("STOP: %d testable families in a row with zero net fixes" % streak)


def cmd_stop(args, work):
    ledger_append(work, dict(kind="stop", why=args.why))
    print("stopped: " + args.why)


# ================================================================ stage 2: the patched scratch converter

def _stage2_init(scratch):
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    sys.path.insert(0, scratch)
    import piu_annotate
    if not os.path.abspath(piu_annotate.__file__).startswith(os.path.abspath(scratch)):
        raise RuntimeError("the scratch converter did not load from %s" % scratch)
    try:
        from loguru import logger
        logger.remove()
    except Exception:
        pass


def cmd_stage2(args, work):
    """Write the rule into a SCRATCH copy of the converter's modules (never the clone), convert
    every block through it, and compare with the model's variant totals; with --clean-room, also a
    second implementation written from the rule's text alone. Refuses unless the scratch copy is
    what loaded."""
    import shutil
    import tempfile
    man, oracle, corpus, tiers = startup(work, workers=args.workers)
    if args.hyp == "BASE":                       # the machinery's own check: an unpatched (or identity) copy
        mod, variants, vkey = None, {}, "base"
    else:
        mod = load_hyp(args.hyp)
        variants = _prepare(args, work, mod, [args.variant])
        vkey = "%s/%s" % (mod.FAMILY, args.variant)
    spec = importlib.util.spec_from_file_location("vg_patch", os.path.abspath(args.patch))
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    import corpus_grade as CG
    pin = CG.converter_pin()
    scratch = os.path.join(ROOT, "work", "variants-1-scratch", "conv-" + sha_file(os.path.abspath(args.patch))[:12])
    if os.path.exists(scratch):
        shutil.rmtree(scratch)
    for rel in pin["files"]:
        src = os.path.join(CONVERTER, *rel.split("/"))
        dst = os.path.join(scratch, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, encoding="utf-8") as f:
            text = f.read()
        if rel.endswith("formats/ssc_to_chartstruct.py"):
            text = patch.PATCH(text)
        with open(dst, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    before = fork_state()
    res = run_grade(work, man, [mod] if mod else [], variants, {}, args.workers)
    # convert every head/import file through the scratch copy, in workers that must load it
    from multiprocessing import Pool
    jobs = []
    for f in man["files"]:
        jobs.append((f["rel"], f["csha"], f["which"]))
    uniq = {}
    for rel, csha, which in jobs:
        uniq.setdefault(csha, (rel, which))
    head_tree, imp_tree = CG.Tree("HEAD"), CG.Tree(IMPORT_COMMIT)
    items = []
    for csha, (rel, which) in sorted(uniq.items()):
        data = (head_tree if which == "head" else imp_tree).read(rel)
        items.append((csha, rel, data))
    diffs, n = [], 0
    with Pool(min(args.workers, GATE["max_workers"]), initializer=_stage2_init, initargs=(scratch,)) as pool:
        for csha, blocks in pool.imap_unordered(_stage2_convert, items, chunksize=4):
            for (tag, idx, reach), tot in blocks.items():
                n += 1
                mine = (res.get(csha) or {}).get((tag, idx, reach), {}).get(vkey)
                if mine != tot:
                    diffs.append((uniq[csha][0], tag, idx, mine, tot))
    after = fork_state()
    clean = None
    if args.clean_room:
        spec = importlib.util.spec_from_file_location("vg_clean", os.path.abspath(args.clean_room))
        cr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cr)
        cdiffs, cn = [], 0
        for csha, f in corpus.files.items():
            for b in f["blocks"]:
                if "error" in b:
                    continue
                cn += 1
                mine = (res.get(csha) or {}).get((b["tag"], b["index"], b["reachable"]), {}).get(vkey)
                theirs = cr.count(b)
                if mine != theirs:
                    cdiffs.append((f["rel"], b["tag"], b["index"], mine, theirs))
        clean = dict(blocks=cn, differ=len(cdiffs), examples=cdiffs[:10])
    ok = not diffs and before == after and (clean is None or clean["differ"] == 0)
    row = ledger_append(work, dict(kind="stage2", family=mod.FAMILY if mod else "BASE", variant=args.variant,
                                   code_hash=variant_hash(mod, args.variant) if mod else None,
                                   patch_sha=sha_file(os.path.abspath(args.patch)), scratch=scratch, blocks=n,
                                   differ=len(diffs), examples=[list(map(str, d)) for d in diffs[:10]], clean_room=clean,
                                   fork_unchanged=before == after, ok=ok))
    print(json.dumps(row, indent=1))


def _stage2_convert(item):
    csha, rel, data = item
    import tempfile
    from piu_annotate.formats.sscfile import SongSSC
    from piu_annotate.formats import ssc_to_chartstruct as C
    fd, path = tempfile.mkstemp(suffix=".ssc", prefix="vg2-")
    out = {}
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        song = SongSSC(path, "PLACEHOLDER_PACK_DONOTUSE")
        seen = set()
        for i, sc in enumerate(song.stepcharts):
            tag = "%s_%s" % (sc.data.get("DESCRIPTION", ""), sc.data.get("SONGTYPE", ""))
            reach = tag not in seen
            seen.add(tag)
            try:
                r = C.stepchart_ssc_to_chartstruct(sc)
            except Exception:
                continue
            if r[0] is None:
                continue
            df, ht, _ = r
            out[(tag, i, reach)] = int(df["Line"].str.contains("1", regex=False).sum()) + int(sum(round(x[2]) for x in ht))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return csha, out


# ================================================================ main

def main():
    ap = argparse.ArgumentParser(description="converter variant grader (report-only)")
    ap.add_argument("--work", default=DEFAULT_WORK)
    ap.add_argument("--workers", type=int, default=3)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("jobs")
    p.add_argument("--out", required=True)
    p.add_argument("--shards", type=int, default=4)
    p = sub.add_parser("dump")
    p.add_argument("--shard")
    sub.add_parser("index")
    sub.add_parser("selftest")
    p = sub.add_parser("freeze")
    p.add_argument("--force", action="store_true")
    p.add_argument("--salt")
    p = sub.add_parser("family-begin")
    p.add_argument("hyp")
    for name in ("register", "grade"):
        p = sub.add_parser(name)
        p.add_argument("hyp")
        p.add_argument("variants", nargs="*")
    p = sub.add_parser("family-end")
    p.add_argument("hyp")
    p = sub.add_parser("reveal")
    p.add_argument("hyp")
    p.add_argument("variant")
    p = sub.add_parser("null")
    p.add_argument("--seed", type=int, default=20260927)
    p.add_argument("--triples", type=int, default=20000)
    p = sub.add_parser("stage2")
    p.add_argument("hyp")
    p.add_argument("variant")
    p.add_argument("--patch", required=True)
    p.add_argument("--clean-room")
    sub.add_parser("status")
    p = sub.add_parser("stop")
    p.add_argument("why")
    args = ap.parse_args()
    work = Work(os.path.abspath(args.work))
    try:
        {"jobs": cmd_jobs, "dump": cmd_dump, "index": cmd_index, "selftest": cmd_selftest, "freeze": cmd_freeze,
         "family-begin": cmd_family_begin, "register": cmd_register, "grade": cmd_grade, "reveal": cmd_reveal,
         "null": cmd_null, "stage2": cmd_stage2, "status": cmd_status, "stop": cmd_stop,
         "family-end": cmd_family_end}[args.cmd](args, work)
    except (MemoryError, OSError) as ex:
        refuse("the machine stopped it: %s: %s" % (type(ex).__name__, ex), TEMPFAIL)


if __name__ == "__main__":
    main()
