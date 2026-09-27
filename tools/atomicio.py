# Writes that cannot leave a half-written file behind, and loads that treat one as missing.
#
# Every cache and report under work/ used to be written with `json.dump(x, open(path, "w"))`
# or its pickle / npz / jsonl equivalent. open(..., "w") truncates the file BEFORE a byte of the
# new content exists, so a process killed at that moment - a timeout, a closed terminal, a
# machine that slept - leaves a 0-byte or truncated file under the real name, and every later
# reader trips over it. That is not hypothetical: two 0-byte receptor field caches left by a
# probe that patched json.dump after the file had been opened broke Another Truth D19 and
# Emperor S16 in every tool, and a killed survey leaves its resume report unreadable.
#
# Here a write goes to a private temp file in the SAME directory, is flushed to disk, and is
# then renamed over the target with os.replace, which is atomic on one volume: a reader sees the
# old file or the new one, never a partial one. On Windows the rename fails while any other
# process has the target open, so it is retried with backoff rather than given up on.
#
# The helpers write exactly the bytes the call they replace wrote - write_json(p, x, **kw) is
# json.dump(x, open(p, "w"), **kw) down to the text-mode newline translation - so a report or
# cache written through them is byte-identical to one written before.
#
# A long stream (a counter scan, one line per frame for minutes) cannot be buffered whole, so
# StreamWriter writes <name>.partial and renames it into place only when the stream completes,
# then writes <name>.done.json: its line count, size and sha256, plus whatever the producer
# records about how it was made. A file with that sidecar is complete and checkable; a legacy
# file without one is trusted unless it is structurally broken.
#
# Loaders (load_json, load_pickle, load_npz, read_jsonl) return None for a missing file AND for
# a 0-byte, truncated or unloadable one, saying so on stderr, so the caller rebuilds it.
#
#   python -X utf8 -B tools/atomicio.py drill <scratch dir> [--rounds N] [--modes naive,atomic,pickle,stream]
#       the crash drill: writers killed mid-write, the target checked after every kill
import contextlib
import hashlib
import itertools
import json
import os
import pickle
import sys
import threading
import time

RETRIES = 60          # os.replace attempts while a reader holds the target (Windows)
BACKOFF = 0.02        # s, doubled per attempt up to BACKOFF_MAX: about 25 s in all
BACKOFF_MAX = 0.5
_seq = itertools.count()
_retries = [0]        # replaces that needed more than one attempt (the drill reports it)


def _tmp_for(path):
    d, b = os.path.split(os.path.abspath(path))
    return os.path.join(d, ".%s.%d.%d.%d.tmp" % (b, os.getpid(), threading.get_ident() % 100000, next(_seq)))


def replace(src, dst):
    """os.replace, retried while Windows refuses it because another process has dst open."""
    delay = BACKOFF
    for attempt in range(RETRIES):
        try:
            os.replace(src, dst)
            if attempt:
                _retries[0] += 1
            return
        except PermissionError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)


def remove(path):
    """os.remove of a file that may not be there, retried while Windows refuses it because another
    process has it open."""
    delay = BACKOFF
    for attempt in range(RETRIES):
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)


@contextlib.contextmanager
def atomic_open(path, mode="w", **open_kwargs):
    """open() for writing, except the file appears under `path` only once the block completes.

    The same mode, encoding and newline arguments open() takes, so the bytes are the ones a plain
    open(path, mode) would have produced. An exception inside the block discards the temp file
    and leaves any existing target untouched."""
    if not any(c in mode for c in "wx"):
        raise ValueError("atomic_open writes a whole file; mode %r is not a write mode" % mode)
    mode = mode.replace("x", "w")
    tmp = _tmp_for(path)
    f = open(tmp, mode, **open_kwargs)
    try:
        yield f
        f.flush()
        os.fsync(f.fileno())
        f.close()
        replace(tmp, path)
    except BaseException:
        f.close()
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_text(path, text, encoding=None, newline=None):
    with atomic_open(path, "w", encoding=encoding, newline=newline) as f:
        f.write(text)


def write_bytes(path, data):
    with atomic_open(path, "wb") as f:
        f.write(data)


def write_json(path, obj, encoding=None, newline=None, **dump_kwargs):
    """json.dump(obj, open(path, "w", encoding=encoding, newline=newline), **dump_kwargs), atomically."""
    with atomic_open(path, "w", encoding=encoding, newline=newline) as f:
        json.dump(obj, f, **dump_kwargs)


def write_pickle(path, obj, **dump_kwargs):
    with atomic_open(path, "wb") as f:
        pickle.dump(obj, f, **dump_kwargs)


def write_npz(path, compressed=False, **arrays):
    """np.savez(path, **arrays) (or savez_compressed), atomically. Written through a file object,
    so numpy never appends a second .npz to the name."""
    import numpy as np
    with atomic_open(path, "wb") as f:
        (np.savez_compressed if compressed else np.savez)(f, **arrays)


def write_meta(path, **meta):
    """The provenance sidecar <path>.meta.json of a cache: the full parameter set and the code
    stamp it was built under (tools/cachekey.py), and when. Provenance never fails the caller: the
    cache itself is already in place, and its name is what keys it."""
    meta.setdefault("written", time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        write_json(path + ".meta.json", meta, encoding="utf-8", indent=1, sort_keys=True, default=repr)
    except (OSError, TypeError, ValueError) as ex:
        print("[atomicio] %s: provenance sidecar not written (%s)" % (path, ex), file=sys.stderr, flush=True)


# ---------------------------------------------------------------- streams

class StreamWriter:
    """A long line-oriented file (a counter scan) written as <path>.partial and renamed into place
    only on completion, with <path>.done.json recording its line count, size and sha256.

        with StreamWriter(path, encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row) + "\\n")
            out.meta.update(stopped="end of video")

    Leaving the block by an exception removes the partial and leaves any existing file as it was;
    a process killed outright leaves <path>.partial behind and never touches <path>."""

    def __init__(self, path, encoding=None, newline=None, **meta):
        self.path = path
        self.partial = path + ".partial"
        self.meta = dict(meta)
        self.lines = 0
        self._f = open(self.partial, "w", encoding=encoding, newline=newline)

    def write(self, s):
        self._f.write(s)
        self.lines += s.count("\n")

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.commit()
        else:
            self.abort()
        return False

    def commit(self):
        """Seal the stream. The order is what keeps every moment readable: the old sidecar goes
        first (an old file with no sidecar is a legacy file, trusted when it parses), then the
        rename (a new file with no sidecar, likewise), then the new sidecar. There is no instant
        at which a file sits beside a sidecar describing some other file."""
        self._f.flush()
        os.fsync(self._f.fileno())
        self._f.close()
        size, sha, lines = file_digest(self.partial)
        remove(done_path(self.path))
        replace(self.partial, self.path)
        write_json(done_path(self.path), dict(self.meta, complete=True, lines=lines, bytes=size, sha256=sha,
                                              finished=time.strftime("%Y-%m-%dT%H:%M:%S")),
                   encoding="utf-8", indent=1, sort_keys=True)

    def abort(self):
        self._f.close()
        try:
            os.remove(self.partial)
        except OSError:
            pass


def done_path(path):
    return path + ".done.json"


def file_digest(path):
    """(bytes, sha256 hex, newline count) of a file."""
    h, n, lines = hashlib.sha256(), 0, 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
            lines += chunk.count(b"\n")
    return n, h.hexdigest(), lines


# ---------------------------------------------------------------- loading

def _broken(path, why, quiet=False):
    if not quiet:
        print("[atomicio] %s: %s - treated as missing, so it is rebuilt" % (path, why), file=sys.stderr, flush=True)
    return None


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def load_json(path, required=(), quiet=False, **open_kwargs):
    """The file's JSON, or None when it is missing, empty, truncated or lacks a required key."""
    n = _size(path)
    if n is None:
        return None
    if n == 0:
        return _broken(path, "0 bytes", quiet)
    try:
        with open(path, **({"encoding": "utf-8"} | open_kwargs)) as f:
            obj = json.load(f)
    except (ValueError, UnicodeDecodeError) as ex:
        return _broken(path, "unreadable JSON (%s)" % f"{ex}"[:80], quiet)
    missing = [k for k in required if not isinstance(obj, dict) or k not in obj]
    if missing:
        return _broken(path, "no %s" % ", ".join(missing), quiet)
    return obj


def load_pickle(path, quiet=False):
    n = _size(path)
    if n is None:
        return None
    if n == 0:
        return _broken(path, "0 bytes", quiet)
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (EOFError, pickle.UnpicklingError, ValueError, TypeError, AttributeError, IndexError, MemoryError) as ex:
        return _broken(path, "unloadable pickle (%s: %s)" % (type(ex).__name__, f"{ex}"[:60]), quiet)


def load_npz(path, required=(), quiet=False):
    """{name: array} for every array in the archive, read eagerly so a bad member fails here and
    not in the caller; None when missing, empty, unloadable or short of a required array."""
    import zipfile
    import zlib
    import numpy as np
    n = _size(path)
    if n is None:
        return None
    if n == 0:
        return _broken(path, "0 bytes", quiet)
    try:
        with np.load(path, allow_pickle=False) as z:
            out = {k: z[k] for k in z.files}
    except PermissionError:
        raise
    except (zipfile.BadZipFile, zlib.error, ValueError, OSError, EOFError, KeyError) as ex:
        return _broken(path, "unloadable npz (%s: %s)" % (type(ex).__name__, f"{ex}"[:60]), quiet)
    missing = [k for k in required if k not in out]
    if missing:
        return _broken(path, "no %s" % ", ".join(missing), quiet)
    return out


def jsonl_status(path):
    """(status, detail) of a line-per-record stream: "missing", "ok", or "broken" with why.

    With a <path>.done.json sidecar the file must match it (size, line count and sha256): a file
    replaced after its sidecar was written is not the file the sidecar describes. Without one it is
    a legacy file, trusted unless empty or a line does not parse (the tail a killed writer leaves)."""
    n = _size(path)
    if n is None:
        return "missing", None
    if n == 0:
        return "broken", "0 bytes"
    side = load_json(done_path(path), quiet=True)
    if side is not None:
        if side.get("bytes") != n:
            return "broken", "%d bytes, its completion sidecar says %s" % (n, side.get("bytes"))
        size, sha, lines = file_digest(path)
        if sha != side.get("sha256") or lines != side.get("lines"):
            return "broken", "content does not match its completion sidecar"
        return "ok", "sealed"
    return "ok", "legacy"


def read_jsonl(path, quiet=False, **open_kwargs):
    """Every line's JSON, or None when the stream is missing, empty, fails its sidecar, or has a
    line that does not parse."""
    st, why = jsonl_status(path)
    if st == "missing":
        return None
    if st == "broken":
        return _broken(path, why, quiet)
    rows = []
    with open(path, **({"encoding": "utf-8"} | open_kwargs)) as f:
        for k, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                return _broken(path, "line %d does not parse (a writer killed mid-line?)" % k, quiet)
    return rows


def jsonl_ok(path):
    """Whether a stream exists and reads cleanly (see read_jsonl)."""
    return read_jsonl(path, quiet=True) is not None


# ---------------------------------------------------------------- read-only phases

def forbid_writes(allow=()):
    """From here on, refuse every file write, rename and delete in this process, except under the
    paths in `allow`. A read-only phase that runs under this hook cannot truncate a shared cache
    by accident - which patching json.dump cannot promise, since open(..., "w") has already
    truncated the file by the time json.dump is called. Irreversible for the process.

    Paths are compared after resolving links and junctions, so work/ reached through a junction
    is the same place as the directory it points at."""
    allow = [os.path.normcase(os.path.realpath(a)) for a in allow]
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

    def allowed(p):
        if isinstance(p, int):              # an already-open descriptor (stdout and the like)
            return True
        if not isinstance(p, (str, bytes, os.PathLike)):
            return False
        p = os.path.normcase(os.path.realpath(os.fsdecode(p)))
        d, b = os.path.split(p)
        # an allowed file may be written atomically: its temp sibling is allowed with it
        return p == os.path.normcase(os.devnull) or any(
            p == a or p.startswith(a + os.sep)
            or (d == os.path.dirname(a) and b.startswith("." + os.path.basename(a) + ".") and b.endswith(".tmp"))
            for a in allow)

    def hook(event, args):
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wxa+")) or \
                      (mode is None and isinstance(flags, int) and flags & write_flags)
            if writing and not allowed(path):
                raise PermissionError("read-only phase: refused to open %s for writing" % (path,))
        elif event in ("os.remove", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "os.truncate",
                       "os.link", "os.symlink", "shutil.rmtree", "shutil.move"):
            if not all(allowed(a) for a in args[:2] if isinstance(a, (str, bytes, os.PathLike))):
                raise PermissionError("read-only phase: refused %s%r" % (event, tuple(args[:2])))
    sys.addaudithook(hook)


# ---------------------------------------------------------------- the crash drill

def _drill_payload(version, size):
    # ~size bytes of JSON that says which write it came from on every line
    return {"version": version, "rows": [[version, k, "x" * 40] for k in range(size // 60)]}


def _drill_writer(path, mode, first, size):
    """Child process: write versions first, first+1, ... until killed."""
    v = first
    while True:
        obj = _drill_payload(v, size)
        if mode == "atomic":
            write_json(path, obj, indent=1)
        elif mode == "naive":
            json.dump(obj, open(path, "w"), indent=1)
        elif mode == "pickle":
            write_pickle(path, obj)
        elif mode == "stream":
            with StreamWriter(path, encoding="utf-8", version=v) as out:
                for row in obj["rows"]:
                    out.write(json.dumps(row) + "\n")
        print(v, flush=True)
        v += 1


def _drill_check(path, mode):
    """(verdict, version or why) of what a kill left at `path`: "absent" (no file - which drill()
    accepts only before any write has completed), "whole" (exactly one complete write), or
    "PARTIAL"."""
    if mode == "stream":
        st, why = jsonl_status(path)
        if st == "missing":
            return "absent", None
        rows = read_jsonl(path, quiet=True)
        if rows is None:
            return "PARTIAL", why
        vs = {r[0] for r in rows}
        if len(vs) == 1 and len(rows) == len(_drill_payload(0, DRILL_SIZE)["rows"]):
            return "whole", vs.pop()
        return "PARTIAL", "mixed or short"
    obj = load_pickle(path, quiet=True) if mode == "pickle" else load_json(path, quiet=True)
    if obj is None:
        return ("absent", None) if not os.path.exists(path) else ("PARTIAL", "%d bytes that do not load" % os.path.getsize(path))
    if obj == _drill_payload(obj.get("version"), DRILL_SIZE):
        return "whole", obj["version"]
    return "PARTIAL", "loads but is not one write"


DRILL_SIZE = 1_500_000
MODES = ("naive", "atomic", "pickle", "stream")


def drill(scratch, rounds=40, modes=MODES):
    """Kill writers mid-write (TerminateProcess: no finally, no flush) and look at what they leave.
    Round r's writer writes versions r*1000, r*1000+1, ..., so a whole file after a kill is either
    OLD (an earlier round's last complete write) or NEW (a write this writer finished). The naive
    open(path, "w") writer is the control: the drill has to be able to catch a partial file, or
    passing it proves nothing."""
    import random
    import subprocess
    os.makedirs(scratch, exist_ok=True)
    rnd = random.Random(20260927)
    results = {}
    for mode in modes:
        path = os.path.join(scratch, "drill-%s.%s" % (mode, "pkl" if mode == "pickle" else "jsonl" if mode == "stream" else "json"))
        tally = {"old": 0, "new": 0, "absent": 0, "PARTIAL": 0}
        last, why = None, []
        for r in range(rounds):
            p = subprocess.Popen([sys.executable, "-X", "utf8", "-B", os.path.abspath(__file__), "_drill-writer", path, mode,
                                  str(r * 1000), str(DRILL_SIZE)], stdout=subprocess.PIPE, text=True)
            time.sleep(rnd.uniform(0.2, 2.0))
            p.kill()
            p.wait()
            verdict, v = _drill_check(path, mode)
            if verdict == "absent" and last is not None:
                verdict, v = "PARTIAL", "the file vanished after version %d had been written" % last
            if verdict == "whole":
                verdict = "new" if v >= r * 1000 else "old"
                if last is not None and v < last:
                    verdict = "PARTIAL"          # went backwards: an older write replaced a newer one
                    v = "version %d after %d" % (v, last)
                else:
                    last = v
            tally[verdict] += 1
            if verdict == "PARTIAL":
                why.append(v)
        leftovers = [f for f in os.listdir(scratch) if f.startswith(".drill-%s." % mode) or f == os.path.basename(path) + ".partial"]
        results[mode] = dict(tally, leftover_temp_files=len(leftovers))
        print("%-7s %2d kills: old %2d, new %2d, absent %2d, PARTIAL %2d; temp/partial files the kills left: %d%s" % (
            mode, rounds, tally["old"], tally["new"], tally["absent"], tally["PARTIAL"], len(leftovers),
            ("  (" + "; ".join(str(w) for w in why[:3]) + ")") if why else ""), flush=True)
    # a reader holding the target open while the writer replaces it: Windows refuses the rename
    # until the reader lets go, which is what the retry is for
    path = os.path.join(scratch, "drill-contended.json")
    write_json(path, _drill_payload(0, 200_000), indent=1)
    stop, seen = threading.Event(), {"reads": 0, "bad": 0}

    def reader():
        while not stop.is_set():
            try:
                with open(path, encoding="utf-8") as f:
                    obj = json.load(f)
                    time.sleep(0.002)
                seen["reads"] += 1
                if obj != _drill_payload(obj["version"], 200_000):
                    seen["bad"] += 1
            except (ValueError, KeyError):
                seen["bad"] += 1
            except OSError:
                pass
    th = threading.Thread(target=reader)
    th.start()
    before = _retries[0]
    for v in range(1, 101):
        write_json(path, _drill_payload(v, 200_000), indent=1)
    stop.set()
    th.join()
    results["contended"] = dict(writes=100, retried=_retries[0] - before, reads=seen["reads"], bad_reads=seen["bad"])
    print("contended: 100 atomic writes under a busy reader, %d needed a retried rename, %d reads, %d bad" % (
        _retries[0] - before, seen["reads"], seen["bad"]), flush=True)
    ok = all(results[m]["PARTIAL"] == 0 for m in modes if m != "naive") and results["contended"]["bad_reads"] == 0 \
        and ("naive" not in modes or results["naive"]["PARTIAL"] > 0)
    print("DRILL %s" % ("PASS - the naive writer left partial files and the atomic ones never did" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["drill"]:
        rounds = int(sys.argv[sys.argv.index("--rounds") + 1]) if "--rounds" in sys.argv else 40
        modes = sys.argv[sys.argv.index("--modes") + 1].split(",") if "--modes" in sys.argv else MODES
        sys.exit(drill(sys.argv[2], rounds, modes))
    elif sys.argv[1:2] == ["_drill-writer"]:
        _drill_writer(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
    else:
        sys.exit("usage: atomicio.py drill <scratch dir> [--rounds N] [--modes naive,atomic,pickle,stream]")
