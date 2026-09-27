# The corpus grade, and the gate every loop commits through.
#
# Grades EVERY certified chart - the population the repair loops draw, built by corpus_map from
# the committed certification ledgers - through piu-annotate's converter: taps + hold ticks
# against the certified judged count. A chart is exact when they are equal. Then it ratchets:
#
#   PROTECTED    exact when the import commit a23cee5's blocks are graded under the current
#                oracle (the corpus as upstream published it), or promoted since by a
#                sources/protected-promotions.jsonl row whose block_sha is the chart's current
#                block (its interior passed a covered, FLAT trace audit). A row in
#                sources/demotions.jsonl takes the import protection away; a promotion of a
#                block no demotion names gives it back.
#   PROVISIONAL  every other exact chart: exact by our edits, interior not proven.
#
#   python -X utf8 -B tools/corpus_grade.py grade [--rev <commit>] [--oracle-rev <commit>] [--out <path>|-]
#   python -X utf8 -B tools/corpus_grade.py gate --base <rev> [--head <rev> | --worktree] [--oracle-pass] [--declared N]
#                                                [--json <path>] [--audit-no-decode]
#   python -X utf8 -B tools/corpus_grade.py freeze [--repin]      (writes sources/oracle-manifest.json)
#   python -X utf8 -B tools/corpus_grade.py conflicts [--write]   (builds sources/oracle-conflict.json)
#   python -X utf8 -B tools/corpus_grade.py selfcheck             (guards' block split == the converter's)
#   common: [--workers N] (default 6)  [--no-cache]  [--cache-dir <dir>]  [--unpinned]
#           [--stall-timeout S] (default 600)
#
# EXIT CODES: 0 done (the gate: PASS); 1 the gate FAILs (selfcheck: a mismatch); 2 REFUSED - the
# tool cannot judge until something is fixed (an oracle or converter that is not the manifest's, an
# oracle edited without a freeze, a revision that does not resolve, a converter without the
# lattice, an incomplete oracle tree, an internal error); 75 (EX_TEMPFAIL) REFUSED, RETRY LATER -
# the machine, not the work, stopped the judgement (a pool starved or a worker hung past
# --stall-timeout, a MemoryError or OSError, a converter that answered two ways, a ship audit the
# machine failed). Only 75 means "the same command may succeed later"; supervise.py retries it by
# default, and never 2.
#
# grade --rev reads the commit's .ssc files as git blobs (never the working tree); without --rev
# it grades the working tree. Only the blocks come from --rev: the oracle (who is certified, at
# what count) is still the working tree's unless --oracle-rev names a commit too.
# The output JSON is deterministic - sorted, no timings (timings go to stderr) - so two grades of
# one tree are byte-identical.
#
# THE ORACLE is the set of files that decide who is certified and at what count (ORACLE_DATA)
# plus the policy files the gate enforces (ORACLE_POLICY). sources/oracle-manifest.json holds
# the sha256 of each (CRLF read as LF, so a CRLF checkout and an LF blob agree) and the CONVERTER
# PIN: the sha256 over every piu_annotate module the conversion loads (see converter_pin). grade
# and gate refuse to run when the working tree's oracle or the installed converter differs from
# the manifest; `freeze` rewrites the manifest (the converter pin only with --repin, which is a
# commit of its own). Only the committed ledgers count: work/certification-tail.json is the
# live file result_reader appends to, and a row there is not oracle until it is promoted into
# sources/ by an oracle commit.
#
# THE GATE grades --base and --head (default: HEAD - the commits a pass made; --worktree grades the
# working tree instead, for a check before committing), each under its own tree's oracle, prints
# every transition (a chart's exactness, block, header, count, population or PROTECTED tier
# changing), audits every SHIP - a chart exact at the head whose block or file header the change
# edited: GAINED, or EDITED-EXACT (a PROTECTED chart's re-edit too, where a promotion row lets it
# through) - with tools/trace_audit.py (a GAINED chart against the import commit, so its whole
# interior since upstream is judged; an EDITED-EXACT one against --base, the change alone; an
# --oracle-pass audits nothing, since any stepfile edit fails it), and exits 1 when
#   - a chart leaves exact without a sources/demotions.jsonl row naming it and its block_sha
#     before the change (with a reason and evidence; a quarantined chart's row also needs the
#     owner's yes in an "owner" field);
#   - demotions.jsonl gains a row with no "owner" field (the owner's yes, written into the row):
#     a demotion is the owner's call, never a loop's, whatever reason and evidence it gives;
#   - a PROTECTED chart leaves exact at all, or its block or file header changes while it stays
#     exact (unless a promotion row names the new block). Protection is judged at the base, so
#     demoting a PROTECTED chart is a commit of its own, before the change that breaks it;
#   - the oracle hash or the converter pin differs between base and head (unless --oracle-pass,
#     for commits that change only the oracle - and then any file under simfiles/ that differs
#     between base and head fails, certified or not);
#   - an owner-revisit chart's block or header no longer hashes to what owner-revisit.json records;
#   - a chart in the ORACLE_CONFLICT set becomes exact (halt for review, take no credit);
#   - demotions.jsonl or protected-promotions.jsonl lost or rewrote a line (both are append-only);
#   - --declared N is given and the net change in exact charts is not N;
#   - a ship's trace audit is not FLAT with every edit covered (and no OFF in the whole trace):
#     UNCOVERED and UNAUDITED do not ship, OFF does not ship. A ship whose judged events are the
#     audit base's (the block differs in nothing the converter judges) passes: there is no edit.
# It exits 2 when it cannot judge (converter or oracle drift at the head, a revision that does
# not resolve, an audit that loaded another converter), and 75 when the machine stopped it (a
# conversion or a ship audit that hit MemoryError or OSError, a worker that died or hung past
# --stall-timeout, a converter that answers differently twice). It writes nothing but --json and
# the trace audit's own scratch (work/rails-audit-scratch/: clocks, blobs, overlays), and it never
# reads a grade file to decide anything. With the default head (HEAD) it says when the working
# tree differs from HEAD under simfiles/ or sources/: those edits are not what it judged.
import argparse
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import corpus_map  # noqa: E402
import guards      # noqa: E402

CONVERTER = os.environ.get("PIU_ANNOTATE_ROOT", r"C:\Users\jonec\repos\piu-annotate")
IMPORT_COMMIT = "a23cee5"          # "simfiles/ is the source of truth: full corpus committed"
MANIFEST = "sources/oracle-manifest.json"
ORACLE_DATA = [
    "sources/census-final.json",                    # census judged counts
    "sources/certification-2026-08-30.json",        # census certification (eye-verified)
    "sources/certification-corpus-2026-09-10.json", # corpus certification (result_reader)
    "sources/p1-note-counts-2026-07-04.json",       # Phoenix 1 catalog counts (the conflict set)
    "sources/ssc-map-tail.json",                    # chart -> key + .ssc beyond the census
    "sources/ssc-map.json",                         # chart -> key + .ssc, the census
    "sources/tail-2026-09-08.json",                 # the catalog sweep (fallback expected counts)
    "sources/video-map.json",                       # the census video map (chart identity)
]
ORACLE_POLICY = [
    "sources/oracle-conflict.json",                 # charts that halt the gate instead of scoring
    "sources/owner-revisit.json",                   # charts no loop may touch, with block hashes
    "sources/quarantine.json",                      # exact in total, wrong inside: owner review
]
DEMOTIONS = "sources/demotions.jsonl"
PROMOTIONS = "sources/protected-promotions.jsonl"
# Before 2026-09-27 the tail map lived only in the gitignored work/; a revision older than its
# move into sources/ is read with the working copy, and the output says so.
LEGACY = {"sources/ssc-map-tail.json": "work/ssc-map-tail.json"}
DEFAULT_CACHE = os.path.join(ROOT, "work", "corpus-grade-cache")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def log(msg):
    print("[corpus_grade] " + msg, file=sys.stderr, flush=True)


TEMPFAIL = 75                      # sysexits' EX_TEMPFAIL: the machine stopped the judgement; try again later


def refuse(msg, code=2):
    """Cannot judge until something is fixed (exit 2): never retried by supervise."""
    print("REFUSED: " + msg, flush=True)
    sys.exit(code)


def later(msg):
    """The machine, not the work, stopped the judgement (exit 75): the same command may succeed later."""
    print("REFUSED, RETRY LATER (exit %d): %s" % (TEMPFAIL, msg), flush=True)
    sys.exit(TEMPFAIL)


def lf(data):
    """Bytes as git stores them with autocrlf: CRLF read as LF."""
    return data.replace(b"\r\n", b"\n")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_lines(pairs):
    return hashlib.sha256("".join("%s\t%s\n" % kv for kv in sorted(pairs.items())).encode("utf-8")).hexdigest()


def git(*args, text=True, input=None):
    p = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, input=input,
                       text=text, encoding="utf-8" if text else None)
    return p.returncode, (p.stdout if text else p.stdout), (p.stderr if text else p.stderr.decode("utf-8", "replace"))


def resolve(rev):
    rc, out, err = git("rev-parse", "--verify", "--quiet", rev + "^{commit}")
    if rc != 0:
        refuse("revision %r does not resolve to a commit" % rev)
    return out.strip()


# ---------------------------------------------------------------- trees: a commit or the working tree

class Tree:
    """Files of one state of the repo: a commit's blobs (rev given) or the working tree."""

    def __init__(self, rev=None):
        self.rev = resolve(rev) if rev else None
        self.label = self.rev or "WORKTREE"
        self.legacy = []
        self._blobs = None

    def _index(self):
        if self._blobs is None:
            rc, out, err = git("ls-tree", "-r", "-z", self.rev, text=False)
            if rc != 0:
                refuse("git ls-tree %s failed: %s" % (self.rev, err.strip()))
            self._blobs = {}
            for rec in out.split(b"\0"):
                if rec:
                    meta, path = rec.split(b"\t", 1)
                    mode, kind, sha = meta.split(b" ")
                    if kind == b"blob":
                        self._blobs[path.decode("utf-8")] = sha.decode()
        return self._blobs

    def read_many(self, paths):
        """{path: bytes or None}. Paths are repo-relative with forward slashes."""
        out = {}
        if self.rev is None:
            for p in paths:
                full = os.path.join(ROOT, *p.split("/"))
                if os.path.isfile(full):
                    with open(full, "rb") as f:
                        out[p] = f.read()
                else:
                    out[p] = None
            return out
        idx = self._index()
        want = [p for p in paths if p in idx]
        for p in paths:
            out[p] = None
        if want:
            shas = [idx[p] for p in want]
            rc, data, err = git("cat-file", "--batch", text=False, input=("\n".join(shas) + "\n").encode())
            if rc != 0:
                refuse("git cat-file failed: %s" % err.strip())
            pos = 0
            for p, s in zip(want, shas):
                nl = data.index(b"\n", pos)
                head = data[pos:nl].split(b" ")
                if head[0].decode() != s or head[1] != b"blob":
                    refuse("git cat-file returned %r for %s" % (data[pos:nl][:80], p))
                size = int(head[2])
                out[p] = data[nl + 1:nl + 1 + size]
                pos = nl + 1 + size + 1
        return out

    def read(self, path):
        return self.read_many([path])[path]

    def read_oracle(self, path):
        data = self.read(path)
        if data is None and path in LEGACY:
            legacy = os.path.join(ROOT, *LEGACY[path].split("/"))
            if os.path.isfile(legacy):
                with open(legacy, "rb") as f:
                    data = f.read()
                self.legacy.append("%s <- %s" % (path, LEGACY[path]))
        return data


# ---------------------------------------------------------------- the oracle

def _json(data, default):
    return json.loads(data.decode("utf-8-sig")) if data is not None else default


def _jsonl(data):
    rows, bad = [], []
    if data is None:
        return rows, bad
    for i, line in enumerate(lf(data).decode("utf-8-sig").split("\n")):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                bad.append(i + 1)
    return rows, bad


class Oracle:
    """Everything the grade reads that is not a stepfile, from one Tree."""

    def __init__(self, tree):
        self.tree = tree
        raw = {p: tree.read_oracle(p) for p in ORACLE_DATA + ORACLE_POLICY}
        self.files = {p: (sha_bytes(lf(d)) if d is not None else "absent") for p, d in raw.items()}
        self.hash = sha_lines(self.files)
        missing = [p for p in ORACLE_DATA if raw[p] is None]
        if missing:
            refuse("%s has no %s" % (tree.label, ", ".join(missing)))
        self.census_cert = corpus_map.ledger_entries(_json(raw["sources/certification-2026-08-30.json"], {}))
        cert = corpus_map.merge_certification([
            corpus_map.ledger_entries(_json(raw["sources/certification-corpus-2026-09-10.json"], {})),
            self.census_cert])
        self.cert = cert
        self.smap = corpus_map.merge_chart_map(_json(raw["sources/ssc-map-tail.json"], []),
                                               _json(raw["sources/ssc-map.json"], []))
        self.population = corpus_map.certified_charts(cert, self.smap, _json(raw["sources/tail-2026-09-08.json"], {}),
                                                      _json(raw["sources/census-final.json"], []))
        self.catalog = _json(raw["sources/p1-note-counts-2026-07-04.json"], {}).get("charts", [])
        self.owner_revisit = _json(raw["sources/owner-revisit.json"], {}).get("charts", [])
        self.conflict = {c["chart"]: c for c in _json(raw["sources/oracle-conflict.json"], {}).get("charts", [])}
        self.quarantine = {c["chart"]: c for c in _json(raw["sources/quarantine.json"], {}).get("charts", [])}
        self.demotions, self.demotions_bad = _jsonl(tree.read(DEMOTIONS))
        self.promotions, self.promotions_bad = _jsonl(tree.read(PROMOTIONS))
        self.manifest = _json(tree.read(MANIFEST), None)


def check_manifest(oracle, pin, unpinned=False):
    """Refuse unless this tree's oracle files and the installed converter are the manifest's."""
    m = oracle.manifest
    if m is None:
        if unpinned:
            log("no %s in %s: running UNPINNED (--unpinned)" % (MANIFEST, oracle.tree.label))
            return
        refuse("no %s in %s - freeze one (corpus_grade.py freeze), or pass --unpinned" % (MANIFEST, oracle.tree.label))
    problems = []
    listed = m.get("oracle", {})
    for p in sorted(set(listed) | set(oracle.files)):
        if listed.get(p) != oracle.files.get(p):
            problems.append("%s: manifest %s, file %s" % (p, str(listed.get(p))[:12], str(oracle.files.get(p))[:12]))
    if m.get("converter", {}).get("pin") != pin["pin"]:
        problems.append("converter pin: manifest %s, installed %s (%s)" % (
            str(m.get("converter", {}).get("pin"))[:12], pin["pin"][:12],
            ", ".join(sorted(f for f in set(pin["files"]) | set(m.get("converter", {}).get("files", {}))
                             if pin["files"].get(f) != m.get("converter", {}).get("files", {}).get(f)))))
    if problems:                                         # --unpinned covers a missing manifest only
        refuse("the oracle in %s is not the one %s pins:\n  %s" % (oracle.tree.label, MANIFEST, "\n  ".join(problems)))


# ---------------------------------------------------------------- the converter and its pin

def load_converter(root=CONVERTER):
    if root not in sys.path:
        sys.path.insert(0, root)
    from piu_annotate.formats import sscfile                                   # noqa: F401
    from piu_annotate.formats import ssc_to_chartstruct as C
    if getattr(C, "HOLD_TICK_MODEL", "legacy") != "lattice":
        refuse("piu-annotate's converter does not count hold ticks by the tick lattice - check out the "
               "piuscores-windows-port branch of https://github.com/DrMurloc/piu-annotate")
    return C


def loaded_converter_files():
    """{path relative to the package's parent: sha256} for every piu_annotate module loaded."""
    import piu_annotate
    base = os.path.dirname(os.path.dirname(os.path.abspath(piu_annotate.__file__)))
    out = {}
    for name, mod in list(sys.modules.items()):
        if name == "piu_annotate" or name.startswith("piu_annotate."):
            f = getattr(mod, "__file__", None)
            if f:
                with open(f, "rb") as fh:
                    out[os.path.relpath(os.path.abspath(f), base).replace(os.sep, "/")] = sha_bytes(lf(fh.read()))
    return out


def converter_pin():
    """The CONVERTER PIN: sha256 over (relative path, sha256) of every piu_annotate module the
    conversion loads - today piu_annotate/__init__.py, utils.py, formats/__init__.py,
    formats/notelines.py, formats/sscfile.py and formats/ssc_to_chartstruct.py. The set is what
    Python actually imported, not a list kept by hand; a worker that finds a module outside it
    after converting stops the grade. numpy/pandas/python versions are recorded in the manifest
    for the reader but are not part of the pin."""
    load_converter()
    files = loaded_converter_files()
    return dict(pin=sha_lines(files), files=files)


def environment():
    import numpy
    import pandas
    rc = subprocess.run(["git", "-C", CONVERTER, "rev-parse", "HEAD"], capture_output=True, text=True)
    return dict(python=sys.version.split()[0], numpy=numpy.__version__, pandas=pandas.__version__,
                converter_head=rc.stdout.strip() if rc.returncode == 0 else None)


# ---------------------------------------------------------------- conversion (worker processes)

_W = {}


def _converter_modules():
    return {n for n in sys.modules if n == "piu_annotate" or n.startswith("piu_annotate.")}


def _worker_init(root):
    if os.name == "nt":                                  # the machine is shared: BelowNormal
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    load_converter(root)
    try:
        from loguru import logger
        logger.remove()                                  # "Failed to find ..." goes into the row
    except Exception:
        pass
    # never raise here: a failing initializer makes the pool respawn workers forever. The pin
    # travels back with every result and the parent refuses on a mismatch.
    _W["pin"] = sha_lines(loaded_converter_files())
    _W["modules"] = _converter_modules()


def convert_one(job):
    """(path, tag, rel) -> ({taps, ticks, implied}, {error} or {transient}, worker's converter
    pin, modules loaded outside the pin). The arithmetic is tick_verify's. MemoryError and OSError
    say something about the machine, not the file: they come back as `transient`, which the
    parent never caches and refuses on."""
    path, tag, rel = job
    from piu_annotate.formats.sscfile import StepchartSSC
    from piu_annotate.formats.ssc_to_chartstruct import stepchart_ssc_to_chartstruct
    try:
        sc = StepchartSSC.from_song_ssc_file(path, tag)
        if sc is None:
            res = dict(error="block not found")
        else:
            out = stepchart_ssc_to_chartstruct(sc)       # (df, ticks, msg); (None, msg) on failure
            if out[0] is None:
                res = dict(error=("convert failed: %s" % out[-1]).replace(path, rel)[:120])
            else:
                df, ht, msg = out
                taps = int(df["Line"].str.contains("1", regex=False).sum())
                ticks = int(sum(round(x[2]) for x in ht))
                res = dict(taps=taps, ticks=ticks, implied=taps + ticks)
    except (MemoryError, OSError) as ex:
        res = dict(transient=("%s: %s" % (type(ex).__name__, ex)).replace(path, rel)[:120])
    except Exception as ex:
        res = dict(error=("%s: %s" % (type(ex).__name__, ex)).replace(path, rel)[:120])
    return res, _W.get("pin"), sorted(_converter_modules() - _W.get("modules", set()))


CONVERT_VERSION = sha_bytes((inspect.getsource(convert_one)).encode("utf-8"))


def content_sha(content):
    """The conversion cache's key for a file: sha256 with CRLF and CR read as LF. The converter
    opens files in text mode (universal newlines), so newline style never changes its answer."""
    return sha_bytes(content.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))


class Converter:
    """Converts (content, tag) pairs, deduplicated by content, through a worker pool, with an
    optional on-disk cache keyed by (converter pin, convert_one's source, content sha, tag).

    Only a count is cached. An error row is converted again on every run, and once more in a
    fresh worker before it is believed (the two must agree, or the run refuses): the converter
    swallows its own exceptions while building the beat map, so a MemoryError there reads as an
    ordinary failure, and a cached one would stay a wrong "not exact" until someone deleted it.
    A `transient` result (MemoryError or OSError in convert_one) refuses the run outright, and a
    pool that delivers no result for `stall` seconds (a killed or hung worker loses its task
    without a word) refuses it too - either way exit 75 (retry later), never a verdict. A worker
    on another converter is exit 2: that is drift, and waiting does not fix it."""

    def __init__(self, pin, workers=6, cache_dir=DEFAULT_CACHE, use_cache=True, stall=600):
        self.pin, self.workers, self.cache_dir, self.use_cache = pin, workers, cache_dir, use_cache
        self.stall = stall
        self.memo = {}
        self.stats = dict(converted=0, cached=0)

    def _key(self, csha, tag):
        return hashlib.sha256(("%s\n%s\n%s\n%s" % (self.pin, CONVERT_VERSION, csha, tag)).encode("utf-8")).hexdigest()

    def _cache_path(self, key):
        return os.path.join(self.cache_dir, key[:2], key + ".json")

    def _cache_get(self, key):
        if not self.use_cache:
            return None
        try:
            with open(self._cache_path(key), encoding="utf-8") as f:
                d = json.load(f)
            res = d["result"] if d.get("key") == key else None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None                                  # missing, 0-byte or torn: rebuild
        # only a count is ever cached: anything else under a matching key (an error row, a count
        # whose parts do not add up) is not believed, and is converted again
        if not (isinstance(res, dict) and all(isinstance(res.get(k), int) and not isinstance(res.get(k), bool)
                                              for k in ("taps", "ticks", "implied"))
                and res["implied"] == res["taps"] + res["ticks"]):
            return None
        return res

    def _cache_put(self, key, result):
        if not self.use_cache:
            return
        path = self._cache_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(key=key, result=result), f)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        try:
            os.remove(tmp)
        except OSError:
            pass

    def run(self, items):
        """items: [(content sha, content bytes, tag, rel)] -> {(content sha, tag): result}."""
        todo, out = {}, {}
        for csha, content, tag, rel in items:
            k = (csha, tag)
            if k in out or k in todo:
                continue
            if k in self.memo:
                out[k] = self.memo[k]
                continue
            hit = self._cache_get(self._key(csha, tag))
            if hit is not None:
                out[k] = hit
                self.stats["cached"] += 1
            else:
                todo[k] = (content, rel)
        if todo:
            t0 = time.time()
            tmpdir = tempfile.mkdtemp(prefix="corpus-grade-")
            try:
                jobs, back = [], {}
                for (csha, tag), (content, rel) in sorted(todo.items()):
                    path = os.path.join(tmpdir, csha + ".ssc")
                    if not os.path.exists(path):
                        with open(path, "wb") as f:
                            f.write(content)
                    jobs.append((path, tag, rel))
                    back[(path, tag)] = (csha, tag)
                first = self._pool(jobs, self.workers)
                again = [j for j in jobs if "error" in first[j]]
                if again:                                # believe an error only when it repeats
                    second = self._pool(again, 1)
                    moved = [j[2] for j in again if second[j] != first[j]]
                    if moved:                    # a swallowed MemoryError that did not repeat: the machine
                        later("the converter answered differently on a second try for %d block(s), so nothing is "
                               "judged: %s" % (len(moved), "; ".join("%s: %s -> %s" % (j[2], first[j], second[j])
                                                                     for j in again if second[j] != first[j])[:600]))
                for job in jobs:
                    k = back[(job[0], job[1])]
                    out[k] = first[job]
                    if "implied" in first[job]:
                        self._cache_put(self._key(*k), first[job])
                self.stats["converted"] += len(jobs)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
            log("converted %d blocks in %.1fs on %d workers%s" % (len(todo), time.time() - t0, self.workers,
                                                                  " (%d error(s) converted twice)" % len(again) if again else ""))
        self.memo.update(out)
        return out

    def _pool(self, jobs, workers):
        """{job: result} for every job, or a refusal: a worker with another pin or extra modules,
        a transient result, or no result for `stall` seconds (the pool is terminated on the way out)."""
        from multiprocessing import Pool, TimeoutError as PoolTimeout
        results = {}
        with Pool(workers, initializer=_worker_init, initargs=(CONVERTER,)) as pool:
            it = pool.imap(convert_one, jobs)                # chunksize 1: a chunked imap has no timeout
            for job in jobs:
                try:
                    res, wpin, extra = it.next(timeout=self.stall)
                except PoolTimeout:
                    later("no conversion result for %ds after %d of %d blocks, waiting on %s (a worker was killed "
                           "or hung) - nothing is judged" % (self.stall, len(results), len(jobs), job[2]))
                if wpin != self.pin:
                    refuse("a worker's converter pin %s is not the parent's %s" % (str(wpin)[:12], self.pin[:12]))
                if extra:
                    refuse("the conversion loaded piu_annotate modules outside the pin: %s" % ", ".join(extra))
                results[job] = res
        transient = [(j[2], results[j]["transient"]) for j in jobs if "transient" in results[j]]
        if transient:
            later("the machine, not the file, failed %d conversion(s) - nothing cached, nothing judged; run again: %s"
                   % (len(transient), "; ".join("%s: %s" % t for t in transient)[:600]))
        return results


# ---------------------------------------------------------------- grading

_FACTS = {}


def block_facts(content, tag):
    """(block_sha, header_sha) of the block the converter would pick for `tag` (the first
    block carrying it), or Nones. One guards.file_index per distinct file content."""
    if content is None:
        return None, None
    k = sha_bytes(content)
    if k not in _FACTS:
        _FACTS[k] = guards.file_index(content)
    ix = _FACTS[k]
    return next((s for t, s in ix["blocks"] if t == tag), None), ix["header_sha"]


def grade_tree(blocks, oracle, conv):
    """Every certified chart of `oracle`, converted from `blocks` (a Tree). -> {chart: row}."""
    pop = oracle.population
    jobs = {}
    for name, c in pop.items():
        try:
            tag = guards.tag_of(c["key"])
        except ValueError:
            tag = None
        jobs[name] = (c, tag, "simfiles/" + c["ssc_rel"])
    contents = blocks.read_many(sorted({j[2] for j in jobs.values()}))
    cshas = {rel: content_sha(d) for rel, d in contents.items() if d is not None}
    items = [(cshas[rel], contents[rel], tag, rel) for c, tag, rel in jobs.values() if tag and contents[rel] is not None]
    results = conv.run(items)
    rows = {}
    for name in sorted(jobs):
        c, tag, rel = jobs[name]
        content = contents[rel]
        row = dict(chart=name, key=c["key"], ssc_rel=c["ssc_rel"], tag=tag, vid=c["vid"], side=c["side"],
                   expected=int(c["expected"]) if c.get("expected") not in (None, "") else None)
        if tag is None:
            row["error"] = "key carries no block tag"
        elif content is None:
            row["error"] = "no file at this revision"
        else:
            res = results[(cshas[rel], tag)]
            row.update(res)
            row["block_sha"], row["header_sha"] = block_facts(content, tag)
        row["exact"] = row.get("implied") is not None and row["implied"] == row["expected"]
        rows[name] = row
    return rows


def valid_demotion(r):
    return (isinstance(r, dict) and isinstance(r.get("chart"), str) and HEX64.match(str(r.get("block_sha", "")))
            and str(r.get("reason", "")).strip() and str(r.get("evidence", "")).strip())


def valid_promotion(r):
    return (isinstance(r, dict) and isinstance(r.get("chart"), str) and HEX64.match(str(r.get("block_sha", "")))
            and r.get("audit") == "FLAT" and r.get("covered") is True)


def assign_tiers(rows, import_exact, oracle):
    demoted = {}
    for r in oracle.demotions:
        if valid_demotion(r):
            demoted.setdefault(r["chart"], set()).add(r["block_sha"])
    promoted = {}
    for r in oracle.promotions:
        if valid_promotion(r):
            promoted.setdefault(r["chart"], set()).add(r["block_sha"])
    for name, row in rows.items():
        cur = row.get("block_sha")
        by = None
        if cur and cur in promoted.get(name, ()) and cur not in demoted.get(name, ()):
            by = "promotion"
        elif name in import_exact and name not in demoted:
            by = "import"
        row["protected_by"] = by
        row["tier"] = "PROTECTED" if by else ("PROVISIONAL" if row["exact"] else None)
        flags = []
        if name in demoted:
            flags.append("demoted")
        if name in oracle.conflict:
            flags.append("oracle_conflict")
        if any(name in (e.get("chart"), e.get("key")) or row["key"] == e.get("key") for e in oracle.owner_revisit):
            flags.append("owner_revisit")
        if name in oracle.quarantine:
            flags.append("quarantine")
        row["flags"] = flags
    return rows


class Grader:
    def __init__(self, args, pin):
        self.args, self.pin = args, pin
        self.conv = Converter(pin["pin"], workers=args.workers, cache_dir=args.cache_dir, use_cache=not args.no_cache,
                              stall=args.stall_timeout)
        self.import_tree = None

    def import_exact(self, oracle):
        if self.import_tree is None:
            self.import_tree = Tree(IMPORT_COMMIT)
            verify_import(self.import_tree.rev)
        rows = grade_tree(self.import_tree, oracle, self.conv)
        return {n for n, r in rows.items() if r["exact"]}

    def grade(self, blocks, oracle):
        rows = grade_tree(blocks, oracle, self.conv)
        imp = self.import_exact(oracle)
        return assign_tiers(rows, imp, oracle), imp


def verify_import(sha):
    """a23cee5 must be the commit that brought in the corpus: simfiles/ exists there and not
    in its parent."""
    rc1, _, _ = git("rev-parse", "--verify", "--quiet", sha + ":simfiles")
    rc2, _, _ = git("rev-parse", "--verify", "--quiet", sha + "^:simfiles")
    if rc1 != 0 or rc2 == 0:
        refuse("%s is not the import commit (simfiles/ must first appear there)" % sha)


def blocks_digest(rows):
    return sha_lines({n: "%s %s" % (r.get("block_sha"), r.get("header_sha")) for n, r in rows.items()})


def summarize(rows, imp):
    ex = [r for r in rows.values() if r["exact"]]
    return dict(certified=len(rows), exact=len(ex),
                protected=sum(1 for r in ex if r["tier"] == "PROTECTED"),
                provisional=sum(1 for r in ex if r["tier"] == "PROVISIONAL"),
                protected_by_import=sum(1 for r in ex if r["protected_by"] == "import"),
                protected_by_promotion=sum(1 for r in ex if r["protected_by"] == "promotion"),
                protected_not_exact=sorted(n for n, r in rows.items() if r["tier"] == "PROTECTED" and not r["exact"]),
                exact_at_import=len(imp),
                errors=sum(1 for r in rows.values() if "error" in r),
                exact_oracle_conflict=sum(1 for r in ex if "oracle_conflict" in r["flags"]),
                exact_quarantine=sum(1 for r in ex if "quarantine" in r["flags"]))


def dump(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def write_atomic(path, text):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def cmd_grade(args):
    t0 = time.time()
    pin = converter_pin()
    otree = Tree(args.oracle_rev)
    oracle = Oracle(otree)
    check_manifest(oracle, pin, args.unpinned)
    if otree.rev is None and os.path.exists(corpus_map.TAIL_CERT):
        tail = corpus_map.ledger_entries(corpus_map._load(corpus_map.TAIL_CERT, {}))
        corpus = corpus_map.ledger_entries(_json(otree.read("sources/certification-corpus-2026-09-10.json"), {}))
        extra = sum(1 for vid, e in tail.items() if corpus.get(vid) != e)
        if extra:
            log("work/certification-tail.json differs from the committed corpus ledger on %d videos - "
                "not oracle until an oracle commit promotes it" % extra)
    blocks = Tree(args.rev)
    g = Grader(args, pin)
    rows, imp = g.grade(blocks, oracle)
    out = dict(tool="corpus_grade", blocks=blocks.label, oracle=otree.label, oracle_hash=oracle.hash,
               converter_pin=pin["pin"], import_commit=g.import_tree.rev, blocks_digest=blocks_digest(rows),
               legacy_oracle_reads=sorted(set(otree.legacy)), summary=summarize(rows, imp),
               charts=[rows[n] for n in sorted(rows)])
    s = out["summary"]
    say = sys.stderr if args.out == "-" else sys.stdout      # with --out -, stdout carries the JSON alone
    print("%s: %d certified, %d exact (%d PROTECTED: %d import + %d promotion; %d PROVISIONAL), %d exact at %s, %d errors"
          % (blocks.label[:12], s["certified"], s["exact"], s["protected"], s["protected_by_import"],
             s["protected_by_promotion"], s["provisional"], s["exact_at_import"], IMPORT_COMMIT, s["errors"]), file=say)
    if s["protected_not_exact"]:
        print("  PROTECTED but not exact: %s" % ", ".join(s["protected_not_exact"]), file=say)
    if args.out == "-":
        sys.stdout.write(dump(out))
    elif args.out:
        write_atomic(args.out, dump(out))
        print("wrote " + args.out)
    log("grade took %.1fs (%d converted, %d from cache)" % (time.time() - t0, g.conv.stats["converted"], g.conv.stats["cached"]))


# ---------------------------------------------------------------- the gate

def git_blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _newlines(data):
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def simfiles_listing(tree):
    """{path: blob id or None} of every file under simfiles/: a commit's blobs, or the working
    tree's tracked and untracked (not ignored) files that exist on disk (None: read the bytes)."""
    if tree.rev is not None:
        return {p: s for p, s in tree._index().items() if p.startswith("simfiles/")}
    rc, out, err = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "simfiles", text=False)
    if rc != 0:
        refuse("git ls-files simfiles failed: %s" % err.strip())
    paths = {p.decode("utf-8") for p in out.split(b"\0") if p}
    return {p: None for p in sorted(paths) if os.path.isfile(os.path.join(ROOT, *p.split("/")))}


def simfiles_changes(base, head):
    """[(path, "added"|"removed"|"changed")] for every file under simfiles/ that differs between
    two trees, newline style aside. Two commits compare blob ids. Against the working tree a
    file is unchanged when its bytes, or its bytes with CRLF read as LF, are the commit's blob;
    otherwise both sides are read and compared with CRLF and CR read as LF."""
    lb, lh = simfiles_listing(base), simfiles_listing(head)
    out = [(p, "removed") for p in sorted(set(lb) - set(lh))] + [(p, "added") for p in sorted(set(lh) - set(lb))]
    both = sorted(set(lb) & set(lh))
    if base.rev is not None and head.rev is not None:
        return sorted(out + [(p, "changed") for p in both if lb[p] != lh[p]])
    commit, work, ids = (base, head, lb) if head.rev is None else (head, base, lh)
    local = work.read_many(both)
    doubt = [p for p in both if ids[p] not in (git_blob_id(local[p]), git_blob_id(lf(local[p])))]
    blobs = commit.read_many(doubt)
    out += [(p, "changed") for p in doubt if _newlines(blobs[p]) != _newlines(local[p])]
    return sorted(out)


def append_only(before, after):
    """True when `after` (bytes or None) keeps every line of `before` in order at its start."""
    b = [l for l in lf(before or b"").decode("utf-8").split("\n") if l.strip()]
    a = [l for l in lf(after or b"").decode("utf-8").split("\n") if l.strip()]
    return a[:len(b)] == b


def worktree_drift():
    """Paths under simfiles/ or sources/ where the working tree differs from HEAD (untracked included)."""
    rc, out, err = git("--no-optional-locks", "status", "--porcelain", "-z", "--untracked-files=all", "--",
                       "simfiles", "sources", text=False)
    if rc != 0:
        refuse("git status failed: %s" % err.strip())
    return sorted({rec[3:].decode("utf-8", "replace") for rec in out.split(b"\0") if len(rec) > 3 and rec[2:3] == b" "})


# ---------------------------------------------------------------- the ships' trace audit

# the trace audit's words for "the audited block derives the audit base's judged events": no edit
NO_EDIT_BASES = ("the block and song header are the base's", "the blocks differ but derive the same judged events")


def audit_ships(ships, head, args):
    """{chart: {"record": <trace_audit record>} | {"error": why} | {"transient": why}} for each
    (row, head row, audit base rev) - run in a child process (tools/trace_audit.py loads the footage
    stack and audit hooks this process should not carry), on the head's own file and the audit base's."""
    jobs = [dict(chart=h["chart"], key=h["key"], ssc_rel=h["ssc_rel"], vid=h["vid"], side=h["side"],
                 expected=h["expected"], head_rev=head.rev, base_rev=arev) for row, h, arev in ships]
    tmpdir = tempfile.mkdtemp(prefix="corpus-gate-audit-")
    try:
        jpath, opath = os.path.join(tmpdir, "jobs.json"), os.path.join(tmpdir, "audits.json")
        write_atomic(jpath, dump(jobs))
        cmd = [sys.executable, "-X", "utf8", "-B", os.path.abspath(__file__), "audit-ships", "--jobs", jpath, "--out", opath]
        if args.audit_no_decode:
            cmd.append("--no-decode")
        t0 = time.time()
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = (p.stdout + p.stderr).strip()[-600:]
        if p.returncode == TEMPFAIL:
            later("the ship audit could not run on this machine just now: " + tail)
        if p.returncode != 0 or not os.path.isfile(opath):
            refuse("the ship audit did not run (exit %d): %s" % (p.returncode, tail))
        with open(opath, encoding="utf-8") as f:
            done = json.load(f)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    # the audit loads more of piu_annotate than a conversion does; every module the pin names must
    # be the pinned one
    theirs = done.get("converter_files") or {}
    moved = sorted(f for f, s in args._pin_files.items() if theirs.get(f) != s)
    if moved:
        refuse("the ship audit loaded another converter than the grade (%s) - nothing is judged" % ", ".join(moved))
    log("audited %d ship(s) in %.1fs (trace_audit %s)" % (len(jobs), time.time() - t0, str(done.get("audit_version"))[:8]))
    return {a["chart"]: a for a in done["audits"]}, done.get("audit_version")


def ship_verdict(res, h, t):
    """(True | False | None, text) for one ship's audit: True it may ship, False it may not, None
    the machine stopped the audit (not judged)."""
    if "transient" in res:
        return None, "the audit hit %s on this machine" % res["transient"]
    if "error" in res:
        return False, "UNAUDITED - the audit raised %s" % res["error"]
    rec = res["record"]
    if rec.get("block_sha") != h.get("block_sha"):
        return False, "UNAUDITED - the audit read block %s, the grade %s" % (str(rec.get("block_sha"))[:12], str(h.get("block_sha"))[:12])
    if "file" in rec and rec["file"].get("implied") != h.get("implied"):
        return False, "UNAUDITED - the audit counts %s judged events, the grade %s" % (rec["file"].get("implied"), h.get("implied"))
    edits = rec.get("edits") or []
    if not edits and rec.get("base") in NO_EDIT_BASES:
        return True, "no judged event differs from the audit base (%s)" % rec["base"]
    if not edits:
        return False, "UNAUDITED - no edit found against the audit base, yet the %s chart changed: %s" % (t, rec.get("reason"))
    whole = (rec.get("whole") or {}).get("verdict")
    if rec.get("verdict") == "FLAT" and whole != "OFF" and all(e.get("verdict") == "FLAT" and e.get("covered") for e in edits):
        return True, "FLAT, %d edit(s), every one covered" % len(edits)
    bad = [e for e in edits if not (e.get("verdict") == "FLAT" and e.get("covered"))]
    return False, "%s - %s (%d of %d edit(s) not FLAT and covered)" % (
        rec.get("verdict"), str(rec.get("reason"))[:240], len(bad), len(edits))


def cmd_audit_ships(args):
    """The gate's child: trace_audit.audit_chart on each ship, one JSON file out. Exit 0 with a
    result per ship (a raise is that ship's error, MemoryError/OSError its `transient`), 75 when
    the machine stopped the audit before any ship, 2 otherwise."""
    with open(args.jobs, encoding="utf-8") as f:
        jobs = json.load(f)
    load_converter()                                     # before trace_audit: its imports then find this converter
    import trace_audit as TA
    TA.DECODE = not args.no_decode
    import_rev = resolve(TA.IMPORT_REV)
    out = []
    TA.sweep_overlays()
    try:
        for j in jobs:
            c = {k: j[k] for k in ("chart", "key", "ssc_rel", "vid", "side", "expected")}
            try:
                new_path = TA.blob_path(j["head_rev"], j["ssc_rel"]) if j.get("head_rev") else \
                    os.path.join(ROOT, "simfiles", *j["ssc_rel"].split("/"))
                base_path = TA.blob_path(j["base_rev"], j["ssc_rel"])
                if new_path is None or not os.path.isfile(new_path):
                    out.append(dict(chart=c["chart"], error="no file %s at the head" % j["ssc_rel"]))
                    continue
                # no file at the import is the audit's own "no base block" (the chart is judged
                # whole); no file at any other base cannot be told to audit_chart, which would
                # quietly take the import's file instead
                if base_path is None and j["base_rev"] != import_rev:
                    out.append(dict(chart=c["chart"], error="no file %s at the audit base %s" % (j["ssc_rel"], j["base_rev"][:12])))
                    continue
                rec = TA.audit_chart(c, new_path=new_path, base_path=base_path)
                out.append(dict(chart=c["chart"], base_rev=j["base_rev"], record=rec))
            except (MemoryError, OSError) as ex:
                out.append(dict(chart=c["chart"], transient="%s: %s" % (type(ex).__name__, str(ex)[:200])))
            except Exception as ex:
                out.append(dict(chart=c["chart"], error="%s: %s" % (type(ex).__name__, str(ex)[:200])))
    finally:
        TA.sweep_overlays()
    doc = dict(converter_files=loaded_converter_files(), audit_version=TA.AUDIT_VERSION, decode=TA.DECODE, audits=out)
    write_atomic(args.out, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def cmd_gate(args):
    t0 = time.time()
    pin = converter_pin()
    args._pin_files = pin["files"]
    base, head = Tree(args.base), Tree(None if args.worktree else (args.head or "HEAD"))
    ob, oh = Oracle(base), Oracle(head)
    check_manifest(oh, pin, args.unpinned)             # the head must be graded by what it pins
    fails, notes = [], []
    if not args.worktree and not args.head:
        drift = worktree_drift()
        if drift:
            notes.append("the working tree differs from HEAD in %d path(s) under simfiles/ or sources/ (%s%s): the gate "
                         "judged HEAD - the commits - not those; --worktree grades the working tree" % (
                             len(drift), ", ".join(drift[:5]), " ..." if len(drift) > 5 else ""))
    g = Grader(args, pin)
    rb, ib = g.grade(base, ob)
    rh, ih = g.grade(head, oh)

    # oracle and pin
    base_pin = (ob.manifest or {}).get("converter", {}).get("pin")
    head_pin = (oh.manifest or {}).get("converter", {}).get("pin")
    oracle_changed = ob.hash != oh.hash
    pin_changed = base_pin != head_pin
    if oracle_changed or pin_changed:
        what = []
        if oracle_changed:
            what.append("oracle %s -> %s (%s)" % (ob.hash[:12], oh.hash[:12], ", ".join(
                p for p in sorted(oh.files) if ob.files.get(p) != oh.files.get(p))))
        if pin_changed:
            what.append("converter pin %s -> %s" % (str(base_pin)[:12], str(head_pin)[:12]))
        if args.oracle_pass:
            notes.append("oracle pass: " + "; ".join(what))
        else:
            fails.append("ORACLE: " + "; ".join(what) + " (an oracle change is its own commit: --oracle-pass)")
    for tree in (base, head):
        if tree.legacy:
            notes.append("%s read %s" % (tree.label[:12], "; ".join(sorted(set(tree.legacy)))))

    # an oracle pass carries no stepfile edits: any file under simfiles/ that differs, certified
    # or not, in the population on both sides or on one, fails it
    stepfiles = simfiles_changes(base, head) if args.oracle_pass else []
    if stepfiles:
        charts_in = {}
        for r in list(rb.values()) + list(rh.values()):
            charts_in.setdefault("simfiles/" + r["ssc_rel"], set()).add(r["chart"])
        for p, how in stepfiles[:20]:
            fails.append("ORACLE PASS EDITS A STEPFILE: %s %s%s" % (
                p, how, "; certified here: " + ", ".join(sorted(charts_in[p])) if p in charts_in else ""))
        if len(stepfiles) > 20:
            fails.append("ORACLE PASS EDITS A STEPFILE: and %d more file(s) under simfiles/" % (len(stepfiles) - 20))

    # append-only ledgers
    for path in (DEMOTIONS, PROMOTIONS):
        if not append_only(base.read(path), head.read(path)):
            fails.append("LEDGER: %s lost or rewrote a line between base and head (append-only)" % path)
    if oh.demotions_bad or oh.promotions_bad:
        fails.append("LEDGER: unparseable line(s) at the head: demotions %s, promotions %s" % (oh.demotions_bad, oh.promotions_bad))
    # a demotion is the owner's call: every row the change adds carries his yes in an "owner" field,
    # whoever wrote it - otherwise a loop could write its own reason and evidence, pass UNPROTECTED in
    # one pass and break the chart in the next
    had = {json.dumps(r, sort_keys=True) for r in ob.demotions}
    for r in oh.demotions:
        if json.dumps(r, sort_keys=True) not in had and not (isinstance(r, dict) and str(r.get("owner", "")).strip()):
            fails.append("LEDGER: %s adds a demotion of %s with no \"owner\" field - only the owner demotes, and his yes "
                         "is written into the row" % (DEMOTIONS, r.get("chart") if isinstance(r, dict) else repr(r)[:60]))

    # transitions
    dem_rows = {}
    for r in oh.demotions + ob.demotions:
        if valid_demotion(r):
            dem_rows.setdefault((r["chart"], r["block_sha"]), r)
    conflict = set(ob.conflict) | set(oh.conflict)
    quarantine = set(ob.quarantine) | set(oh.quarantine)
    promo_head = {(r["chart"], r["block_sha"]) for r in oh.promotions if valid_promotion(r)}
    trans, ships = [], []
    for name in sorted(set(rb) | set(rh)):
        b, h = rb.get(name), rh.get(name)
        bx, hx = bool(b and b["exact"]), bool(h and h["exact"])
        edited = bool(b and h and (b.get("block_sha"), b.get("header_sha")) != (h.get("block_sha"), h.get("header_sha")))
        prot_b, prot_h = bool(b and b["tier"] == "PROTECTED"), bool(h and h["tier"] == "PROTECTED")
        t = None
        if bx and not hx:
            t = "LOST" if h else "LEFT-EXACT"
        elif hx and not bx:
            t = "GAINED" if b else "ENTERED-EXACT"
        elif bx and hx and edited:
            t = "EDITED-EXACT"
        elif edited:
            t = "EDITED-OFF"
        elif b and h and b.get("expected") != h.get("expected"):
            t = "EXPECTED-CHANGED"
        elif b is None or h is None:
            t = "ENTERED" if b is None else "LEFT"
        elif prot_b != prot_h:                             # a tier change with nothing else: a ledger row
            t = "UNPROTECTED" if prot_b else "PROMOTED"
        if not t:
            continue
        row = dict(chart=name, transition=t, tier_base=b and b["tier"], tier_head=h and h["tier"],
                   before=b and dict(implied=b.get("implied"), expected=b["expected"], block_sha=b.get("block_sha"), error=b.get("error")),
                   after=h and dict(implied=h.get("implied"), expected=h["expected"], block_sha=h.get("block_sha"), error=h.get("error")),
                   verdict="ok")
        if t in ("LOST", "LEFT-EXACT"):
            dem = dem_rows.get((name, b.get("block_sha")))
            if prot_b:
                row["verdict"] = "FAIL: a PROTECTED chart left exact (demote it in a commit of its own first)"
            elif dem is None:
                row["verdict"] = "FAIL: left exact with no demotions.jsonl row for block %s" % str(b.get("block_sha"))[:12]
            elif name in quarantine and not str(dem.get("owner", "")).strip():
                row["verdict"] = "FAIL: a quarantined chart's demotion needs the owner's yes (\"owner\" field)"
            else:
                row["verdict"] = "ok: demoted (%s)" % str(dem.get("reason"))[:60]
        elif t == "EDITED-EXACT" and prot_b:
            if (name, h.get("block_sha")) in promo_head and h.get("header_sha") == b.get("header_sha"):
                row["verdict"] = "ok: PROTECTED block re-audited (promotion row)"
            else:
                row["verdict"] = "FAIL: a PROTECTED chart's %s changed" % (
                    "block" if b.get("block_sha") != h.get("block_sha") else "file header")
        elif t in ("GAINED", "ENTERED-EXACT") and name in conflict:
            row["verdict"] = "FAIL: ORACLE_CONFLICT chart became exact - halt for review, no credit"
        elif t == "UNPROTECTED":
            new = [r for r in oh.demotions if valid_demotion(r) and r["chart"] == name and r not in ob.demotions]
            dem = dem_rows.get((name, b.get("block_sha"))) or (new[0] if new else None)
            if dem is not None and name in quarantine and not str(dem.get("owner", "")).strip():
                row["verdict"] = "FAIL: a quarantined chart's demotion needs the owner's yes (\"owner\" field)"
            elif dem is not None:
                row["verdict"] = "ok: demoted (%s)" % str(dem.get("reason"))[:60]
            elif oracle_changed:
                row["verdict"] = "ok: not exact at %s under the new oracle" % IMPORT_COMMIT
            else:
                row["verdict"] = "FAIL: a PROTECTED chart lost its protection with no demotions.jsonl row"
        elif t == "PROMOTED":
            if h.get("protected_by") == "promotion":
                run = next((r.get("run") for r in oh.promotions if valid_promotion(r) and r["chart"] == name
                            and r["block_sha"] == h.get("block_sha")), None)
                row["verdict"] = "ok: promotion row (%s)" % str(run)[:60]
            else:
                row["verdict"] = "ok: exact at %s under the new oracle" % IMPORT_COMMIT
        if row["verdict"].startswith("FAIL"):
            fails.append("%s %s: %s" % (t, name, row["verdict"][6:]))
        elif edited and t in ("GAINED", "EDITED-EXACT") and not args.oracle_pass:
            # a ship: exact at the head in a block or header this change edited. A GAINED chart is
            # audited against the import (its whole interior since upstream, as the audit ledger
            # judges it); an EDITED-EXACT one against --base (only this change - the chart shipped before)
            ships.append((row, h, g.import_tree.rev if t == "GAINED" else base.rev))
        trans.append(row)

    # every ship's interior against the combo counter: FLAT and covered, or it does not ship
    unjudged, audit_version = [], None
    if ships:
        results, audit_version = audit_ships(ships, head, args)
        for row, h, arev in ships:
            res = results.get(row["chart"]) or dict(error="the audit returned nothing for this chart")
            ok, text = ship_verdict(res, h, row["transition"])
            label = ("import %s" % arev[:12]) if arev == g.import_tree.rev else ("base %s" % arev[:12])
            rec = res.get("record") or {}
            row["audit"] = dict(base=arev, verdict=rec.get("verdict") if rec else ("NOT JUDGED" if ok is None else "UNAUDITED"),
                                ok=ok, text=text, reason=rec.get("reason") or res.get("error") or res.get("transient"),
                                edits=[{k: e.get(k) for k in ("lo", "hi", "kind", "basis", "verdict", "covered", "reason")}
                                       for e in rec.get("edits") or []],
                                whole=(rec.get("whole") or {}).get("verdict"))
            if ok is None:
                unjudged.append("%s: %s" % (row["chart"], text))
                row["verdict"] = "NOT JUDGED: trace audit vs %s - %s" % (label, text)
            elif ok:
                row["verdict"] = (row["verdict"] + "; " if row["verdict"] != "ok" else "ok: ") + "trace audit vs %s: %s" % (label, text)
            else:
                row["verdict"] = "FAIL: trace audit vs %s: %s - OFF, UNCOVERED and UNAUDITED do not ship" % (label, text)
                fails.append("AUDIT %s %s: %s" % (row["transition"], row["chart"], row["verdict"][6:]))

    # owner revisit: the recorded hashes are the accepted state
    seen = set()
    for e in oh.owner_revisit + ob.owner_revisit:
        if e.get("chart") in seen:
            continue
        seen.add(e.get("chart"))
        rel = e.get("ssc_rel") or (oh.smap.get(e.get("chart")) or {}).get("ssc_rel")
        key = e.get("key") or (oh.smap.get(e.get("chart")) or {}).get("key")
        rec = next((x for x in oh.owner_revisit if x.get("chart") == e.get("chart")), None)
        if not rel or not key or rec is None or not rec.get("block_sha") or not rec.get("header_sha"):
            fails.append("OWNER-REVISIT %s: no recorded block_sha/header_sha at the head to hold it to" % e.get("chart"))
            continue
        cur = head.read("simfiles/" + rel)
        bs, hs = block_facts(cur, e.get("block") or guards.tag_of(key))
        if (bs, hs) != (rec["block_sha"], rec["header_sha"]):
            fails.append("OWNER-REVISIT %s: %s changed (recorded %s/%s, now %s/%s) - do not re-open, re-fix or flag" % (
                e["chart"], "block" if bs != rec["block_sha"] else "file header", rec["block_sha"][:12],
                rec["header_sha"][:12], str(bs)[:12], str(hs)[:12]))

    exact_b = sum(1 for r in rb.values() if r["exact"])
    exact_h = sum(1 for r in rh.values() if r["exact"])
    net = exact_h - exact_b
    if args.declared is not None and net != args.declared:
        fails.append("DECLARED: net change in exact charts is %+d, declared %+d" % (net, args.declared))

    # report
    order = ["LOST", "LEFT-EXACT", "GAINED", "ENTERED-EXACT", "EDITED-EXACT", "EDITED-OFF", "EXPECTED-CHANGED",
             "UNPROTECTED", "PROMOTED", "ENTERED", "LEFT"]
    print("gate %s -> %s  (import %s, oracle %s -> %s, pin %s)" % (base.label[:12], head.label[:12], g.import_tree.rev[:12],
                                                                 ob.hash[:12], oh.hash[:12], pin["pin"][:12]))
    print("  exact %d -> %d (net %+d), PROTECTED %d -> %d" % (
        exact_b, exact_h, net, sum(1 for r in rb.values() if r["exact"] and r["tier"] == "PROTECTED"),
        sum(1 for r in rh.values() if r["exact"] and r["tier"] == "PROTECTED")))
    for kind in order:
        rows = [r for r in trans if r["transition"] == kind]
        if not rows:
            continue
        print("  %s (%d)" % (kind, len(rows)))
        for r in rows:
            bf, af = r["before"] or {}, r["after"] or {}
            print("    %-44s %s -> %s of %s/%s  [%s -> %s]  %s" % (
                r["chart"][:44], bf.get("implied", bf.get("error")), af.get("implied", af.get("error")),
                bf.get("expected"), af.get("expected"), r["tier_base"], r["tier_head"], r["verdict"]))
    audited = [r for r in trans if r.get("audit")]
    if audited:
        print("  SHIPS AUDITED (%d; tools/trace_audit.py %s%s)" % (len(audited), str(audit_version)[:8],
                                                                 ", no decoding" if args.audit_no_decode else ""))
        for r in audited:
            a = r["audit"]
            print("    %-44s %s vs %s" % (r["chart"][:44], a["verdict"], a["base"][:12]))
            for e in a["edits"][:12]:
                print("      edit %s-%s %s: %s%s - %s" % (e.get("lo"), e.get("hi"), e.get("basis") or e.get("kind") or "",
                                                         e.get("verdict"), "" if e.get("covered") else " (not covered)",
                                                         str(e.get("reason"))[:160]))
    for n in notes:
        print("  note: " + n)
    verdict = "FAIL" if fails else ("NOT JUDGED" if unjudged else "PASS")
    for f in fails:
        print("  FAIL " + f)
    for u in unjudged:
        print("  NOT JUDGED " + u)
    print(verdict)
    if args.json:
        rep = dict(tool="corpus_grade gate", base=base.label, head=head.label, import_commit=g.import_tree.rev,
                   oracle_base=ob.hash, oracle_head=oh.hash, converter_pin=pin["pin"], oracle_pass=bool(args.oracle_pass),
                   declared=args.declared, exact_base=exact_b, exact_head=exact_h, net=net, transitions=trans,
                   stepfiles_changed=[dict(path=p, change=how) for p, how in stepfiles],
                   ships_audited=len(audited), audit_version=audit_version,
                   failures=fails, not_judged=unjudged, notes=notes, verdict=verdict)
        write_atomic(args.json, dump(rep))
    log("gate took %.1fs (%d converted, %d from cache)" % (time.time() - t0, g.conv.stats["converted"], g.conv.stats["cached"]))
    if unjudged and not fails:
        later("the trace audit of %d ship(s) was stopped by the machine (%s); gate the same base again"
              % (len(unjudged), "; ".join(unjudged)[:400]))
    sys.exit(1 if fails else 0)


# ---------------------------------------------------------------- freeze

def cmd_freeze(args):
    pin = converter_pin()
    tree = Tree(None)
    oracle = Oracle(tree)
    if tree.legacy:
        refuse("the oracle is incomplete in the working tree: " + "; ".join(tree.legacy))
    old = oracle.manifest or {}
    old_pin = old.get("converter", {}).get("pin")
    if old_pin and old_pin != pin["pin"] and not args.repin:
        refuse("the installed converter (%s) is not the pinned one (%s); --repin to move the pin, as a commit of its own"
               % (pin["pin"][:12], old_pin[:12]))
    conv = dict(old.get("converter", {})) if (old_pin == pin["pin"] and not args.repin) else {}
    conv.update(pin=pin["pin"], files=pin["files"], hold_tick_model="lattice")
    if args.repin or not old_pin:
        conv["environment"] = environment()
    m = dict(purpose="The frozen oracle: the sha256 (CRLF read as LF) of every file the corpus grade reads to decide who "
                     "is certified and at what count, the policy files its gate enforces, and the converter pin. "
                     "tools/corpus_grade.py grade and gate refuse to run when the working tree or the installed "
                     "converter differs from this. Rewrite it with `corpus_grade.py freeze` in an oracle commit "
                     "(never together with stepfile edits); `--repin` moves the converter pin, as a commit of its own.",
             oracle_hash=oracle.hash, oracle=oracle.files, converter=conv)
    changed = sorted(p for p in set(oracle.files) | set(old.get("oracle", {})) if oracle.files.get(p) != old.get("oracle", {}).get(p))
    write_atomic(os.path.join(ROOT, *MANIFEST.split("/")), dump(m))
    print("froze %s: oracle %s, converter pin %s; changed: %s" % (MANIFEST, oracle.hash[:12], pin["pin"][:12],
                                                                ", ".join(changed + (["converter pin"] if old_pin != pin["pin"] else [])) or "nothing"))


# ---------------------------------------------------------------- the ORACLE_CONFLICT set

_NAME = re.compile(r"^(.*) ([SD])(\d+)$")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def converter_inputs(data):
    """{tag: fingerprint} of every block: STEPSTYPE plus the seven tags the converter reads
    (NOTES, BPMS, STOPS, DELAYS, WARPS, FAKES, TICKCOUNTS), header inherited, LF-normalized.
    Two blocks with one fingerprint are twins: the grade cannot tell them apart."""
    header, blocks = guards.split_blocks(data)
    head = guards._kv(header)
    out = []
    for b in blocks:
        d = dict(head)
        d.update(guards._kv(b))
        fp = "\x1f".join(re.sub(r"\s+", " ", d.get(k, "")).strip()
                         for k in ("STEPSTYPE", "NOTES", "BPMS", "STOPS", "DELAYS", "WARPS", "FAKES", "TICKCOUNTS"))
        out.append(("%s_%s" % (d.get("DESCRIPTION", ""), d.get("SONGTYPE", "")), fp))
    return out


def build_conflicts(oracle, rows, tree):
    """The charts whose certification the grade cannot trust, from the data alone:
       same_side - a video certifies two or more charts on ONE side (one result screen per side).
                   Where the census ledger (eye-verified) certifies one of them on that side, the
                   census chart is the video's and only the others are listed;
       catalog   - the certified count is not the chart's Phoenix 1 catalog count while the file
                   already converts to that catalog count (the video likely shows another chart);
       twin      - the chart's block has a twin in its file with identical converter inputs."""
    reasons = {}

    def add(name, kind, detail):
        reasons.setdefault(name, []).append(dict(kind=kind, detail=detail))

    videos = []
    for vid in sorted(oracle.cert):
        by = {}
        for n, c in sorted((oracle.cert[vid].get("charts") or {}).items()):
            if c.get("verdict") == "CERTIFIED":
                by.setdefault(c.get("side") or "1p", []).append(n)
        census = {n for n, c in ((oracle.census_cert.get(vid) or {}).get("charts") or {}).items()
                  if c.get("verdict") == "CERTIFIED"}
        for side, names in sorted(by.items()):
            if len(names) > 1:
                verified = sorted(set(names) & census)
                videos.append(dict(vid=vid, side=side, charts=names, census_verified=verified))
                for n in names:
                    if n in verified:
                        continue
                    add(n, "same_side", "video %s certifies %s on %s%s" % (
                        vid, " + ".join(names), side,
                        "; the census (eye-verified) says the screen is %s's" % " + ".join(verified) if verified else ""))

    cat = {}
    for c in oracle.catalog:
        if c.get("p1_notes") and c.get("type", "")[:1] in "SD":
            for lvl_key in ("p1_level", "p2_level"):
                cat.setdefault((lvl_key, norm(c["song"]), c["type"][0], c.get(lvl_key)), []).append(c)
    for name in sorted(rows):
        r = rows[name]
        m = _NAME.match(name)
        if not m or r.get("implied") is None:
            continue
        k = (norm(m.group(1)), m.group(2), int(m.group(3)))
        hits = cat.get(("p1_level",) + k) or cat.get(("p2_level",) + k) or []
        if len(hits) != 1:
            continue
        c = hits[0]
        if r["expected"] != c["p1_notes"] and r["implied"] == c["p1_notes"]:
            p2 = ""                                       # the catalog export carries no P2 counts today
            if c.get("p2_notes"):
                p2 = " (the certified count %s its Phoenix 2 count)" % ("is" if c["p2_notes"] == r["expected"] else "is not")
            add(name, "catalog", "certified %d on %s, but the Phoenix 1 catalog lists %d and the file already converts to %d%s"
                % (r["expected"], r["vid"], c["p1_notes"], c["p1_notes"], p2))

    rels = sorted({r["ssc_rel"] for r in rows.values()})
    contents = tree.read_many(["simfiles/" + rel for rel in rels])
    fps = {rel: converter_inputs(contents["simfiles/" + rel]) for rel in rels if contents["simfiles/" + rel] is not None}
    for name in sorted(rows):
        r = rows[name]
        blocks = fps.get(r["ssc_rel"])
        if not blocks or not r.get("tag"):
            continue
        mine = next((fp for tag, fp in blocks if tag == r["tag"]), None)
        twins = [tag for tag, fp in blocks if fp == mine and tag != r["tag"]]
        if mine is not None and twins:
            add(name, "twin", "block %s has identical converter inputs to %s in %s" % (r["tag"], " + ".join(twins), r["ssc_rel"]))

    return dict(
        purpose="ORACLE_CONFLICT: certified charts the corpus grade cannot score honestly. The gate halts (exit 1) when one "
                "of them becomes exact, instead of taking the credit - the fix is an identity or certification review, not "
                "a stepfile edit. Built from data by `tools/corpus_grade.py conflicts --write`; see docs/TOOLS.md.",
        rules=dict(same_side="a video certifies two or more charts on one side (a result screen shows one total per side)",
                   catalog="certified count != the chart's Phoenix 1 catalog count (sources/p1-note-counts, matched by song, "
                           "type and level) while the file already converts to the catalog count",
                   twin="another block of the file has identical STEPSTYPE, NOTES, BPMS, STOPS, DELAYS, WARPS, FAKES and "
                        "TICKCOUNTS (header inherited): byte-identical to the converter, e.g. HIDDEN / INFOBAR twins"),
        built_from=dict(oracle_data={p: oracle.files[p] for p in ORACLE_DATA}, blocks_digest=blocks_digest(rows)),
        charts=[dict(chart=n, in_population=n in rows, reasons=reasons[n]) for n in sorted(reasons)],
        videos=videos)


def cmd_conflicts(args):
    pin = converter_pin()
    tree = Tree(None)
    oracle = Oracle(tree)
    g = Grader(args, pin)
    rows = grade_tree(tree, oracle, g.conv)
    doc = build_conflicts(oracle, rows, tree)
    from collections import Counter
    kinds = Counter(x["kind"] for c in doc["charts"] for x in c["reasons"])
    print("%d charts in ORACLE_CONFLICT (%s); %d videos certify two charts on one side; %d of the charts are exact now"
          % (len(doc["charts"]), ", ".join("%s %d" % kv for kv in sorted(kinds.items())), len(doc["videos"]),
             sum(1 for c in doc["charts"] if rows.get(c["chart"], {}).get("exact"))))
    for c in doc["charts"]:
        print("  %-44s %s" % (c["chart"][:44], "; ".join(x["kind"] for x in c["reasons"])))
    if args.write:
        write_atomic(os.path.join(ROOT, "sources", "oracle-conflict.json"), dump(doc))
        print("wrote sources/oracle-conflict.json")


# ---------------------------------------------------------------- selfcheck

def cmd_selfcheck(args):
    """guards splits every file into the blocks the converter sees, with the same tags."""
    load_converter()
    from piu_annotate.formats.sscfile import SongSSC
    bad = 0
    files = sorted(os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, "/")
                   for d, _, fs in os.walk(os.path.join(ROOT, "simfiles")) for f in fs if f.endswith(".ssc"))
    for rel in files:
        path = os.path.join(ROOT, *rel.split("/"))
        with open(path, "rb") as f:
            data = f.read()
        mine = guards.block_tags(data)
        try:
            theirs = [sc.data["DESCRIPTION"] + "_" + sc.data["SONGTYPE"] for sc in SongSSC(path, "X").stepcharts]
        except Exception as ex:
            theirs = ["<%s>" % type(ex).__name__]
        if mine != theirs:
            bad += 1
            print("MISMATCH %s: guards %d blocks, converter %d" % (rel, len(mine), len(theirs)))
    print("%d files: %d agree, %d differ" % (len(files), len(files) - bad, bad))
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description="Grade every certified chart; gate a commit pass on the grade.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workers", type=int, default=6)
    common.add_argument("--no-cache", action="store_true")
    common.add_argument("--cache-dir", default=DEFAULT_CACHE)
    common.add_argument("--stall-timeout", type=int, default=600,
                        help="seconds without a conversion result before the run refuses (a killed or hung worker)")
    common.add_argument("--unpinned", action="store_true", help="run without (or despite) the oracle manifest")
    p = sub.add_parser("grade", parents=[common])
    p.add_argument("--rev")
    p.add_argument("--oracle-rev")
    p.add_argument("--out")
    p = sub.add_parser("gate", parents=[common])
    p.add_argument("--base", required=True)
    heads = p.add_mutually_exclusive_group()
    heads.add_argument("--head", help="the commit to judge (default HEAD: the commits a pass made)")
    heads.add_argument("--worktree", action="store_true",
                       help="judge the working tree instead of a commit (a check before committing, never a pass's gate)")
    p.add_argument("--oracle-pass", action="store_true")
    p.add_argument("--declared", type=int)
    p.add_argument("--json")
    p.add_argument("--audit-no-decode", action="store_true",
                   help="a ship whose clock needs the footage decoded audits UNCOVERED (and fails) instead")
    p = sub.add_parser("audit-ships")                    # the gate's child process (see audit_ships)
    p.add_argument("--jobs", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--no-decode", action="store_true")
    p = sub.add_parser("freeze", parents=[common])
    p.add_argument("--repin", action="store_true")
    p = sub.add_parser("conflicts", parents=[common])
    p.add_argument("--write", action="store_true")
    sub.add_parser("selfcheck", parents=[common])
    args = ap.parse_args()
    if not sys.flags.utf8_mode:
        refuse("run with -X utf8: the converter reads .ssc files in the default encoding")
    try:
        dict(grade=cmd_grade, gate=cmd_gate, freeze=cmd_freeze, conflicts=cmd_conflicts, selfcheck=cmd_selfcheck,
             **{"audit-ships": cmd_audit_ships})[args.cmd](args)
    except SystemExit:
        raise
    except BaseException as ex:                          # exit 1 means FAIL; a crash is not a verdict
        import traceback
        traceback.print_exc()
        if isinstance(ex, (MemoryError, OSError)):       # the machine (a file held, memory short): later
            later("internal error: %s: %s" % (type(ex).__name__, ex))
        refuse("internal error: %s: %s" % (type(ex).__name__, ex))


if __name__ == "__main__":
    main()
