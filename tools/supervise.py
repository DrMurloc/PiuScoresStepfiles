# The rails every unattended loop runs on: a supervisor that runs a loop's jobs (one subprocess
# per chart) for days on the owner's own PC, which he also games on, without corrupting the
# shared caches, each other, or main. Owner go: 2026-09-27 (loop buckets, #1 "Rails").
#
#   supervise.py run <run> --jobs <jobs.jsonl> [--timeout S] [--parallel N] [--grace S]
#                          [--threads 1|2] [--min-free-gb G] [--retry nonzero,timeout,launch-error]
#                          [--detach] [--accept-pin-change]
#   supervise.py status [<run> ...] [--json]
#   supervise.py stop [<run>] [--reason TEXT] [--clear]
#   supervise.py slots [--max N] [--gaming-max N] [--min-free-gb G]
#   supervise.py lock-exec [--run R] [--timeout S] -- <cmd ...>
#   supervise.py commitlock [--break] [--force]
#   supervise.py mainlock take --note TEXT | release | show
#   supervise.py worktree <name> --base <rev> [--no-preflight]
#   supervise.py worktree-remove <name> [--delete-branch] [--force-branch]
#   supervise.py preflight [--videos] [--open-videos]
#   supervise.py pins
#
# Everything shared lives under work/ (a junction to the main checkout's work/ in a loop
# worktree, so every worktree sees the same files):
#   work/.slots/        the machine-wide decode-slot pool: one slot-*.json per held slot
#   work/.commit.lock   the ONE commit lock every loop commits under (tools/loopcommit.py)
#   work/.main.lock     held by whoever is merging into main; .githooks/pre-push refuses pushes
#   work/STOP           stops every loop;  work/runs/<run>/STOP stops one
#   work/runs/<run>/    manifest.json, jobs.jsonl (frozen), ledger.jsonl (append-only),
#                       events.jsonl, heartbeat.json, supervisor.log, logs/<job>.log
#   work/rails-events.jsonl   machine-wide log of stale slots and locks recovered
#
# Why each piece exists:
# - Slots are counted, not numbered: while Wow.exe runs the limit drops from 6 to 2, and a
#   numbered pool would let a new job take a free low number while four high ones still decode.
#   Counting and creating happen under an OS byte-range lock (released by the kernel when its
#   holder dies, so it can never go stale); a slot file whose owner AND child are both dead is
#   recovered by PID liveness, with the process creation time checked so a reused PID does not
#   keep a dead slot alive.
# - Every child runs in its own Windows job object (kill-on-close) as well as under taskkill /T:
#   the piu-annotate venv's python.exe is a launcher that starts the real interpreter as a
#   child, and a tool may start ffmpeg or a pool of its own. The job object reaps what
#   taskkill's parent-PID walk misses (an orphan whose parent already exited), and a child that
#   exits leaving a grandchild running has the grandchild killed and counted in the ledger.
# - Children run BELOW_NORMAL with CREATE_NO_WINDOW (a detached supervisor has no console, so a
#   plain child would pop a console window over the game), with OMP/BLAS thread caps, and with
#   tools/childsite/ on PYTHONPATH, whose sitecustomize caps OpenCV at --threads: this OpenCV
#   build ignores every thread environment variable and starts one worker per core.
# - Keep-awake is SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED) on the supervisor's
#   main thread, cleared on exit; the machine still needs AC power (it sleeps after 3 minutes
#   on battery whatever a process asks).
# - The converter's source hash and the oracle manifest's hash are pinned at the start of a run
#   and re-checked before every launch; drift halts the run (running jobs are killed and left
#   unfinished in the ledger) without reverting anything, and resuming refuses a changed pin
#   unless told otherwise, because one run must not mix two converters.
# - Detached mode relaunches this script with CREATE_NO_WINDOW|CREATE_NEW_PROCESS_GROUP so it
#   outlives the terminal and the chat session that started it. It stays inside the Claude
#   desktop app's process container (the venv's base interpreter lives in that app's
#   virtualized AppData and cannot start outside it), so quitting the app may end a run; the
#   ledger makes that a resume, not a loss.
#
# Jobs file: JSON lines (or a .json list), one object per job:
#   {"id": "<unique>", "cmd": ["{py}", "{tools}/tick_verify.py", "Slam D24"],
#    "cwd": "<relative to the worktree, optional>", "timeout": <s, optional>,
#    "slot": true|false (takes a decode slot, default true), "env": {..optional..},
#    "meta": <free-form, optional>}
# "{py}" as a whole argument expands to this interpreter with -X utf8 -B; {root}, {tools},
# {run}, {run_dir} and {job} are substituted inside arguments. A job may print a line
# "VERDICT: <word>" and the last one becomes its ledger verdict; otherwise the verdict is OK or
# FAIL by exit code (TIMEOUT, STOPPED, HALTED and LAUNCH_ERROR are the supervisor's own).
# Children see PSF_RUN, PSF_JOB, PSF_RUN_DIR and PSF_SLOT_HELD=1 when they hold a slot (so a
# child that asks decode_slot() for one does not deadlock against its own supervisor).
#
# Resume: re-running a run id re-reads its frozen jobs.jsonl and skips every job whose latest
# ledger row finished (outcome exit, timeout or launch-error); --retry re-runs the named kinds.
# A job killed by STOP or a halt, or running when a supervisor died, has no finished row and
# runs again.
#
# PSF_RAILS_STATE relocates all of the shared state above (for the self-test only);
# PSF_GAME_EXES overrides the game list; PSF_CONVERTER_REPO points at another converter clone.
import argparse
import contextlib
import ctypes
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
STATE = os.path.abspath(os.environ.get("PSF_RAILS_STATE") or os.path.join(ROOT, "work"))
RUNS = os.path.join(STATE, "runs")
SLOTS = os.path.join(STATE, ".slots")
COMMIT_LOCK = os.path.join(STATE, ".commit.lock")
MAIN_LOCK = os.path.join(STATE, ".main.lock")
GLOBAL_STOP = os.path.join(STATE, "STOP")
RAILS_LOG = os.path.join(STATE, "rails-events.jsonl")
CHILDSITE = os.path.join(TOOLS, "childsite")
CONVERTER_REPO = os.environ.get("PSF_CONVERTER_REPO") or r"C:\Users\jonec\repos\piu-annotate"
ORACLE_MANIFEST = os.path.join(ROOT, "sources", "oracle-manifest.json")
PY = [sys.executable, "-X", "utf8", "-B"]

SLOT_MAX = 6                 # decode slots, machine-wide, never more
SLOT_MAX_GAMING = 2          # while a game below is running
GAME_EXES = [e.strip().lower() for e in (os.environ.get("PSF_GAME_EXES") or "Wow.exe,WowClassic.exe").split(",") if e.strip()]
MIN_FREE_GB = 40             # GiB free on C: (and on work/'s drive) below which launches pause
GRACE_S = 600                # after a STOP, running jobs get this long before taskkill /T
DEFAULT_TIMEOUT_S = 7200
POLL_S = 0.5
SLOT_RETRY_S = 2.0
DISK_EVERY_S = 30
HEARTBEAT_EVERY_S = 30
ACTIVE_STATES = {"running", "waiting-slot", "paused-disk", "stopping"}
FINISHED_OUTCOMES = {"exit", "timeout", "launch-error"}
RETRY_KINDS = {"nonzero", "timeout", "launch-error"}
NEVER_IMPORT = {"download_videos", "run_corpus", "catalog_sweep", "video_refresh_sql"}  # preflight compiles these only

IS_WIN = os.name == "nt"
BELOW_NORMAL = 0x00004000
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
QUIET = CREATE_NO_WINDOW if IS_WIN else 0


# ---------------------------------------------------------------- files

def now_iso(t=None):
    return datetime.datetime.fromtimestamp(time.time() if t is None else t).astimezone().isoformat(timespec="seconds")


def _retry(fn, tries=100, delay=0.05):
    # Windows refuses to replace or remove a file another process has open for a moment
    # (a status reader, an antivirus scan); that is a wait, not a failure.
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        _retry(lambda: os.replace(tmp, path))
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def write_json(path, obj):
    write_atomic(path, json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def read_json(path):
    """None when the file is missing; {"_unreadable": why} when it is there but empty or corrupt."""
    try:
        text = _retry(lambda: open(path, encoding="utf-8").read())
    except FileNotFoundError:
        return None
    except OSError as e:
        return {"_unreadable": str(e)}
    try:
        value = json.loads(text)
    except ValueError as e:
        return {"_unreadable": f"{len(text)} bytes: {e}"}
    return value if isinstance(value, dict) else {"_unreadable": "not a JSON object"}


def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n"

    def write():
        with open(path, "a+b") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell():
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":     # a torn row from a crash mid-append: never glue onto it
                    fh.write(b"\n")
            fh.write(line.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
    _retry(write)


def read_jsonl(path):
    rows = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return rows
    with fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass                    # a torn row; the job it described simply runs again
    return rows


def sha256_file(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return None


def rails_event(event, **kw):
    append_jsonl(RAILS_LOG, {"t": now_iso(), "event": event, "pid": os.getpid(), **kw})


def quiet(cmd, timeout=120, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=QUIET, timeout=timeout, cwd=cwd)


def git(*args, cwd=ROOT, timeout=300):
    return quiet(["git", *args], timeout=timeout, cwd=cwd)


# ---------------------------------------------------------------- processes (Win32)

if IS_WIN:
    import msvcrt
    from ctypes import wintypes as W

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def _fn(name, restype, *argtypes):
        f = getattr(_k32, name)
        f.restype, f.argtypes = restype, list(argtypes)
        return f

    _OpenProcess = _fn("OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
    _CloseHandle = _fn("CloseHandle", W.BOOL, W.HANDLE)
    _GetExitCodeProcess = _fn("GetExitCodeProcess", W.BOOL, W.HANDLE, ctypes.POINTER(W.DWORD))
    _GetProcessTimes = _fn("GetProcessTimes", W.BOOL, W.HANDLE, *[ctypes.POINTER(W.FILETIME)] * 4)
    _SetThreadExecutionState = _fn("SetThreadExecutionState", W.DWORD, W.DWORD)
    _GetCurrentProcess = _fn("GetCurrentProcess", W.HANDLE)
    _SetPriorityClass = _fn("SetPriorityClass", W.BOOL, W.HANDLE, W.DWORD)
    _CreateJobObjectW = _fn("CreateJobObjectW", W.HANDLE, ctypes.c_void_p, W.LPCWSTR)
    _SetInformationJobObject = _fn("SetInformationJobObject", W.BOOL, W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD)
    _AssignProcessToJobObject = _fn("AssignProcessToJobObject", W.BOOL, W.HANDLE, W.HANDLE)
    _TerminateJobObject = _fn("TerminateJobObject", W.BOOL, W.HANDLE, W.UINT)
    _QueryInformationJobObject = _fn("QueryInformationJobObject", W.BOOL, W.HANDLE, ctypes.c_int,
                                     ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD))

    class _BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", W.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [("Basic", _BasicLimit), ("Io", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _Accounting(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                    ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                    ("TotalPageFaultCount", W.DWORD), ("TotalProcesses", W.DWORD),
                    ("ActiveProcesses", W.DWORD), ("TotalTerminatedProcesses", W.DWORD)]

    def _filetime(h):
        c, e, k, u = W.FILETIME(), W.FILETIME(), W.FILETIME(), W.FILETIME()
        if not _GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        return (c.dwHighDateTime << 32) | c.dwLowDateTime


def proc_created(pid):
    """The process's creation time (FILETIME ticks), so a recycled PID is not mistaken for it."""
    if not IS_WIN or not pid:
        return None
    h = _OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        return _filetime(h)
    finally:
        _CloseHandle(h)


def proc_alive(pid, created=None):
    if not pid:
        return False
    if not IS_WIN:
        try:
            os.kill(int(pid), 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    h = _OpenProcess(0x1000, False, int(pid))
    if not h:
        return ctypes.get_last_error() == 5            # ACCESS_DENIED: it exists, we just may not look
    try:
        code = W.DWORD()
        if _GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:   # STILL_ACTIVE
            return False
        if created:
            born = _filetime(h)
            if born is not None and born != created:
                return False                           # the PID now belongs to someone else
        return True
    finally:
        _CloseHandle(h)


class ProcJob:
    """A kill-on-close Windows job object holding one child and everything it starts."""

    def __init__(self):
        self.h = _CreateJobObjectW(None, None) if IS_WIN else None
        if not self.h:
            return
        info = _ExtendedLimit()
        info.Basic.LimitFlags = 0x2000 | 0x20          # KILL_ON_JOB_CLOSE | PRIORITY_CLASS
        info.Basic.PriorityClass = BELOW_NORMAL
        if not _SetInformationJobObject(self.h, 9, ctypes.byref(info), ctypes.sizeof(info)):
            info.Basic.LimitFlags = 0x2000             # the priority limit can need a privilege
            _SetInformationJobObject(self.h, 9, ctypes.byref(info), ctypes.sizeof(info))

    def assign(self, proc):
        return bool(self.h) and bool(_AssignProcessToJobObject(self.h, W.HANDLE(int(proc._handle))))

    def active(self):
        if not self.h:
            return 0
        acc = _Accounting()
        ok = _QueryInformationJobObject(self.h, 1, ctypes.byref(acc), ctypes.sizeof(acc), None)
        return acc.ActiveProcesses if ok else 0

    def terminate(self):
        if self.h:
            _TerminateJobObject(self.h, 1)

    def close(self):
        if self.h:
            _CloseHandle(self.h)
            self.h = None


def kill_tree(proc, pjob=None):
    if IS_WIN:
        quiet(["taskkill", "/T", "/F", "/PID", str(proc.pid)], timeout=60)
        if pjob:
            pjob.terminate()
    else:
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=30)


def keep_awake(on):
    if not IS_WIN:
        return False
    return bool(_SetThreadExecutionState(0x80000000 | (0x1 if on else 0)))   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED


def lower_own_priority():
    if IS_WIN:
        _SetPriorityClass(_GetCurrentProcess(), BELOW_NORMAL)


def running_images():
    out = quiet(["tasklist", "/FO", "CSV", "/NH"], timeout=60).stdout if IS_WIN else ""
    return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line.startswith('"')}


_game = {"t": 0.0, "hits": []}


def games_running(max_age=15):
    if time.time() - _game["t"] > max_age:
        names = running_images()
        _game.update(t=time.time(), hits=sorted(e for e in GAME_EXES if e in names))
    return _game["hits"]


# ---------------------------------------------------------------- locks

class FileMutex:
    """An OS byte-range lock. The kernel drops it when its holder dies, so it never goes stale;
    it guards the few-millisecond read-check-write of the PID lock files and the slot pool."""

    def __init__(self, path, timeout=120):
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        deadline = time.time() + self.timeout
        while True:
            try:
                if IS_WIN:
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.time() > deadline:
                    os.close(self.fd)
                    raise TimeoutError(f"{self.path} stayed locked for {self.timeout}s")
                time.sleep(0.02)

    def __exit__(self, *exc):
        try:
            if IS_WIN:
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


def me_record(**kw):
    return {"pid": os.getpid(), "created": proc_created(os.getpid()), "host": socket.gethostname(),
            "since": now_iso(), "since_ts": time.time(), "token": uuid.uuid4().hex, "cwd": os.getcwd(), **kw}


def holder_alive(rec):
    if not rec or "_unreadable" in rec:
        return False
    return proc_alive(rec.get("pid"), rec.get("created")) or proc_alive(rec.get("child"), rec.get("child_created"))


class PidLock:
    """A lock file naming its holder's PID (and creation time). A dead holder's lock is recovered
    by the next acquirer, under the mutex, and logged to rails-events.jsonl."""

    def __init__(self, path, name):
        self.path, self.name, self.mutex, self.mine = path, name, path + ".mutex", None

    def holder(self):
        return read_json(self.path)

    def try_acquire(self, **info):
        with FileMutex(self.mutex):
            cur = read_json(self.path)
            if cur is not None:
                if holder_alive(cur):
                    return False, cur
                rails_event("stale-lock-recovered", lock=self.name, path=self.path, holder=cur)
                _retry(lambda: os.remove(self.path))
            rec = me_record(**info)
            write_json(self.path, rec)
            self.mine = rec
            return True, rec

    def acquire(self, timeout=None, poll=0.25, quiet_wait=False, stop_run=False, **info):
        start, said = time.time(), False
        while True:
            ok, cur = self.try_acquire(**info)
            if ok:
                return cur
            if not quiet_wait and not said:
                print(f"waiting for the {self.name}: held by pid {cur.get('pid')} (run {cur.get('run')}, "
                      f"since {cur.get('since')})", file=sys.stderr, flush=True)
                said = True
            if timeout is not None and time.time() - start > timeout:
                raise TimeoutError(f"{self.name} still held by pid {cur.get('pid')} after {timeout}s")
            if stop_run is not False and stop_reason(stop_run):
                raise StopRequested(stop_reason(stop_run))
            time.sleep(poll)

    def release(self):
        if not self.mine:
            return
        with FileMutex(self.mutex):
            cur = read_json(self.path)
            if cur and cur.get("token") == self.mine["token"]:
                _retry(lambda: os.remove(self.path))
            else:
                rails_event("lock-lost", lock=self.name, mine=self.mine, found=cur)
        self.mine = None


class StopRequested(Exception):
    pass


@contextlib.contextmanager
def commit_lock(run=None, purpose="", timeout=None):
    """The one lock every loop commits under. `with supervise.commit_lock(run): ...`"""
    lock = PidLock(COMMIT_LOCK, "commit lock")
    lock.acquire(timeout=timeout, run=run, purpose=purpose)
    try:
        yield lock.mine
    finally:
        lock.release()


def stop_reason(run=None):
    if os.path.exists(GLOBAL_STOP):
        return "global STOP (" + GLOBAL_STOP + ")"
    if run and os.path.exists(os.path.join(RUNS, run, "STOP")):
        return "run STOP (" + os.path.join(RUNS, run, "STOP") + ")"
    return None


# ---------------------------------------------------------------- the decode-slot pool

def slot_config():
    cfg = read_json(os.path.join(SLOTS, "config.json")) or {}
    if "_unreadable" in cfg:
        cfg = {}

    def clamp(v, hi, default):
        try:
            return max(0, min(int(v), hi))
        except (TypeError, ValueError):
            return default
    return {"max": clamp(cfg.get("max", SLOT_MAX), SLOT_MAX, SLOT_MAX),
            "gaming_max": clamp(cfg.get("gaming_max", SLOT_MAX_GAMING), SLOT_MAX_GAMING, SLOT_MAX_GAMING),
            "min_free_gb": cfg.get("min_free_gb")}


def slot_limit():
    cfg, hits = slot_config(), games_running()
    return (min(cfg["max"], cfg["gaming_max"]) if hits else cfg["max"]), hits


def live_slots(recover=False):
    out = []
    try:
        names = sorted(os.listdir(SLOTS))
    except FileNotFoundError:
        return out
    for name in names:
        if not (name.startswith("slot-") and name.endswith(".json")):
            continue
        path = os.path.join(SLOTS, name)
        rec = read_json(path)
        if rec is None:
            continue
        if holder_alive(rec):
            out.append((path, rec))
        elif recover:
            rails_event("stale-slot-recovered", slot=name, holder=rec)
            with contextlib.suppress(FileNotFoundError):
                _retry(lambda: os.remove(path))
    return out


class Slot:
    def __init__(self, path, rec):
        self.path, self.rec = path, rec

    def set_child(self, pid):
        self.rec.update(child=pid, child_created=proc_created(pid))
        write_json(self.path, self.rec)

    def release(self):
        with contextlib.suppress(FileNotFoundError):
            _retry(lambda: os.remove(self.path))


def try_acquire_slot(run=None, job=None):
    limit, hits = slot_limit()                         # tasklist runs outside the mutex: it is slow
    with FileMutex(os.path.join(SLOTS, ".mutex")):
        if len(live_slots(recover=True)) >= limit:
            return None
        rec = me_record(run=run, job=job, child=None, child_created=None, limit=limit, gaming=hits)
        path = os.path.join(SLOTS, f"slot-{os.getpid()}-{rec['token'][:12]}.json")
        write_json(path, rec)
    return Slot(path, rec)


@contextlib.contextmanager
def decode_slot(run=None, job=None, poll=SLOT_RETRY_S):
    """For a tool that decodes in-process: `with supervise.decode_slot(): ...`. A no-op inside a
    supervised job that already holds one (PSF_SLOT_HELD=1). Raises StopRequested on STOP."""
    if os.environ.get("PSF_SLOT_HELD") == "1":
        yield None
        return
    run = run or os.environ.get("PSF_RUN")
    while True:
        slot = try_acquire_slot(run, job)
        if slot:
            break
        if stop_reason(run):
            raise StopRequested(stop_reason(run))
        time.sleep(poll)
    try:
        yield slot
    finally:
        slot.release()


# ---------------------------------------------------------------- pins, disk, git state

def converter_dir():
    pkg = os.path.join(CONVERTER_REPO, "piu_annotate")
    if os.path.isdir(pkg):
        return pkg
    import importlib.util
    spec = importlib.util.find_spec("piu_annotate")
    return os.path.dirname(spec.origin) if spec and spec.origin else None


def converter_hash(pkg):
    # sha256 over every .py under the piu_annotate package: posix relative path, NUL, bytes, NUL,
    # in sorted path order. Catches a converter change that keeps the lattice flag.
    h, n = hashlib.sha256(), 0
    for base, dirs, files in os.walk(pkg):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for f in sorted(files):
            if f.endswith(".py"):
                full = os.path.join(base, f)
                rel = os.path.relpath(full, pkg).replace(os.sep, "/")
                with open(full, "rb") as fh:
                    h.update(rel.encode() + b"\0" + fh.read() + b"\0")
                n += 1
    return h.hexdigest(), n


def pins(full=False):
    out = {"converter": None, "oracle": {"path": os.path.relpath(ORACLE_MANIFEST, ROOT).replace(os.sep, "/"),
                                         "sha256": sha256_file(ORACLE_MANIFEST)}}
    pkg = converter_dir()
    if pkg:
        digest, n = converter_hash(pkg)
        conv = {"path": pkg, "py_sha256": digest, "files": n}
        if full:
            src = os.path.join(pkg, "formats", "ssc_to_chartstruct.py")
            try:
                conv["lattice"] = bool(re.search(r"""^HOLD_TICK_MODEL\s*=\s*["']lattice["']""",
                                                 open(src, encoding="utf-8").read(), re.M))
            except OSError:
                conv["lattice"] = None
            repo = os.path.dirname(pkg)
            head = git("rev-parse", "HEAD", cwd=repo)
            conv["git_head"] = head.stdout.strip() if head.returncode == 0 else None
            # .py only: the clone tracks __pycache__/*.pyc, which any import rewrites
            st = git("status", "--porcelain", "--", ":(glob)piu_annotate/**/*.py", cwd=repo)
            conv["git_dirty"] = bool(st.stdout.strip()) if st.returncode == 0 else None
        out["converter"] = conv
    return out


def pin_key(p):
    return ((p.get("converter") or {}).get("py_sha256"), (p.get("oracle") or {}).get("sha256"))


def free_gb():
    drives = {"C:\\"} if IS_WIN else {"/"}
    drives.add(os.path.splitdrive(os.path.realpath(STATE))[0] + "\\" if IS_WIN else STATE)
    vals = [shutil.disk_usage(d).free for d in drives if os.path.exists(d)]
    return round(min(vals) / 1024 ** 3, 1) if vals else None


def tool_state():
    def one(*a):
        r = git(*a)
        return r.stdout.strip() if r.returncode == 0 else None
    dirty = git("status", "--porcelain", "--", "tools")
    return {"head": one("rev-parse", "HEAD"), "tools_tree": one("rev-parse", "HEAD:tools"),
            "tools_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
            "branch": one("branch", "--show-current"), "worktree": ROOT}


# ---------------------------------------------------------------- jobs

RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
JOB_KEYS = {"id", "cmd", "cwd", "timeout", "slot", "env", "meta"}


def load_jobs(path):
    text = open(path, encoding="utf-8").read()
    if path.lower().endswith(".json"):
        items = json.loads(text)
        items = items.get("jobs") if isinstance(items, dict) else items
    else:
        items = [json.loads(line) for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not isinstance(items, list) or not items:
        raise SystemExit(f"{path}: no jobs")
    seen, jobs = set(), []
    for i, j in enumerate(items, 1):
        where = f"{path} job {i}"
        if not isinstance(j, dict):
            raise SystemExit(f"{where}: not an object")
        extra = set(j) - JOB_KEYS
        if extra:
            raise SystemExit(f"{where}: unknown keys {sorted(extra)} (allowed: {sorted(JOB_KEYS)})")
        jid = j.get("id")
        if not isinstance(jid, str) or not jid.strip() or any(ord(c) < 32 for c in jid):
            raise SystemExit(f"{where}: 'id' must be a non-empty single-line string")
        if jid in seen:
            raise SystemExit(f"{where}: duplicate id {jid!r}")
        seen.add(jid)
        cmd = j.get("cmd")
        if not (isinstance(cmd, str) and cmd.strip()) and not (isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd)):
            raise SystemExit(f"{where} ({jid}): 'cmd' must be a string or a list of strings")
        if "timeout" in j and not (isinstance(j["timeout"], (int, float)) and j["timeout"] > 0):
            raise SystemExit(f"{where} ({jid}): 'timeout' must be a positive number of seconds")
        if "slot" in j and not isinstance(j["slot"], bool):
            raise SystemExit(f"{where} ({jid}): 'slot' must be true or false")
        if "env" in j and not (isinstance(j["env"], dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in j["env"].items())):
            raise SystemExit(f"{where} ({jid}): 'env' must map strings to strings")
        if "cwd" in j and not isinstance(j["cwd"], str):
            raise SystemExit(f"{where} ({jid}): 'cwd' must be a string")
        jobs.append(j)
    return jobs


def jobs_text(jobs):
    return "".join(json.dumps(j, sort_keys=True, ensure_ascii=False) + "\n" for j in jobs)


def log_name(jid):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", jid)[:80] + "-" + hashlib.sha1(jid.encode()).hexdigest()[:8] + ".log"


def expand(job, run, rdir):
    subs = {"{root}": ROOT, "{tools}": TOOLS, "{run}": run, "{run_dir}": rdir, "{job}": job["id"]}

    def s(x):
        for k, v in subs.items():
            x = x.replace(k, v)
        return x
    cmd = job["cmd"]
    if isinstance(cmd, str):
        return s(cmd.replace("{py}", subprocess.list2cmdline(PY)))
    out = []
    for a in cmd:
        out += PY if a == "{py}" else [s(a)]
    return out


def child_env(job, run, rdir, slot, threads):
    env = dict(os.environ)
    t = str(threads)
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
              "VECLIB_MAXIMUM_THREADS", "OPENCV_FOR_THREADS_NUM", "PSF_CV_THREADS"):
        env[k] = t
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PSF_RUN=run, PSF_JOB=job["id"], PSF_RUN_DIR=rdir)
    if slot:
        env["PSF_SLOT_HELD"] = "1"
    else:
        env.pop("PSF_SLOT_HELD", None)
    env["PYTHONPATH"] = CHILDSITE + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.update(job.get("env") or {})
    return env


VERDICT_RE = re.compile(rb"^VERDICT[:=][ \t]*(\S[^\r\n]*?)[ \t]*\r?$", re.M)
KILL_VERDICT = {"timeout": "TIMEOUT", "stopped": "STOPPED", "halted": "HALTED", "launch-error": "LAUNCH_ERROR"}


# ---------------------------------------------------------------- the supervisor

class Running:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Supervisor:
    def __init__(self, run, rdir, jobs, opts, base_pins):
        self.run, self.rdir, self.jobs, self.opts = run, rdir, jobs, opts
        self.base = pin_key(base_pins)
        self.ledger = os.path.join(rdir, "ledger.jsonl")
        self.events = os.path.join(rdir, "events.jsonl")
        self.hb_path = os.path.join(rdir, "heartbeat.json")
        self.running, self.last, self.attempts = [], {}, {}
        for r in read_jsonl(self.ledger):
            if r.get("kind") == "job":
                self.last[r["job"]] = r
                self.attempts[r["job"]] = self.attempts.get(r["job"], 0) + 1
        self.queue = [j for j in jobs if not self.finished(j["id"])]
        self.skipped = len(jobs) - len(self.queue)
        self.state, self.stop_since, self.stop_src, self.halt = "running", None, None, None
        self.paused, self.disk_t, self.free = False, 0.0, None
        self.slot_t, self.hb_t, self.hb_state, self.started = 0.0, 0.0, None, time.time()

    def finished(self, jid):
        r = self.last.get(jid)
        if not r or r.get("outcome") not in FINISHED_OUTCOMES:
            return False
        if r["outcome"] == "exit":
            return not (r.get("exit_code") != 0 and "nonzero" in self.opts.retry)
        return r["outcome"] not in self.opts.retry

    def event(self, event, **kw):
        append_jsonl(self.events, {"t": now_iso(), "event": event, "run": self.run, "pid": os.getpid(), **kw})
        print(f"{now_iso()} {event} {json.dumps(kw, ensure_ascii=False) if kw else ''}", flush=True)

    def heartbeat(self, force=False):
        now = time.time()
        if not force and self.state == self.hb_state and now - self.hb_t < HEARTBEAT_EVERY_S:
            return
        verdicts = {}
        done = 0
        for j in self.jobs:
            if self.finished(j["id"]):
                done += 1
                v = self.last[j["id"]].get("verdict")
                verdicts[v] = verdicts.get(v, 0) + 1
        limit, hits = slot_limit()
        write_json(self.hb_path, {
            "run": self.run, "pid": os.getpid(), "created": proc_created(os.getpid()), "host": socket.gethostname(),
            "state": self.state, "updated": now_iso(now), "updated_ts": now, "started": now_iso(self.started),
            "total": len(self.jobs), "completed": done, "queued": len(self.queue), "skipped_at_start": self.skipped,
            "running": [{"job": r.job["id"], "pid": r.proc.pid, "since": now_iso(r.start), "slot": bool(r.slot)} for r in self.running],
            "verdicts": verdicts, "last": max(self.last.values(), key=lambda r: r.get("end", ""), default=None),
            "slots": {"used": len(live_slots()), "limit": limit, "gaming": hits}, "free_gb": self.free,
            "stop": self.stop_src, "halt": self.halt, "grace_s": self.opts.grace,
        })
        self.hb_t, self.hb_state = now, self.state

    def launch(self, job, slot):
        jid = job["id"]
        attempt = self.attempts.get(jid, 0) + 1
        self.attempts[jid] = attempt
        cmd = expand(job, self.run, self.rdir)
        cwd = os.path.join(ROOT, job["cwd"]) if job.get("cwd") else ROOT
        log = os.path.join(self.rdir, "logs", log_name(jid))
        os.makedirs(os.path.dirname(log), exist_ok=True)
        logf = open(log, "ab")
        shown = cmd if isinstance(cmd, str) else subprocess.list2cmdline(cmd)
        logf.write(f"\n===== {now_iso()} attempt {attempt} of {jid}: {shown}\n".encode("utf-8"))
        logf.flush()
        offset = logf.tell()
        start = time.time()
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=child_env(job, self.run, self.rdir, slot, self.opts.threads),
                                    stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                    creationflags=(BELOW_NORMAL | CREATE_NO_WINDOW) if IS_WIN else 0)
        except OSError as e:
            logf.write(f"launch failed: {e}\n".encode("utf-8"))
            logf.close()
            self.record(Running(job=job, proc=None, pjob=None, slot=slot, start=start, attempt=attempt,
                                log=log, offset=offset, logf=None, assigned=False), "launch-error", None)
            return
        pjob = ProcJob() if IS_WIN else None
        assigned = pjob.assign(proc) if pjob else False
        if slot:
            slot.set_child(proc.pid)
        self.running.append(Running(job=job, proc=proc, pjob=pjob, slot=slot, start=start, attempt=attempt,
                                    log=log, offset=offset, logf=logf, assigned=assigned,
                                    deadline=start + float(job.get("timeout") or self.opts.timeout)))

    def verdict(self, r, outcome, rc):
        if outcome != "exit":
            return KILL_VERDICT[outcome]
        try:
            with open(r.log, "rb") as fh:
                fh.seek(max(r.offset, os.path.getsize(r.log) - 65536))
                found = VERDICT_RE.findall(fh.read())
        except OSError:
            found = []
        if found:
            return found[-1].decode("utf-8", "replace")[:200]
        return "OK" if rc == 0 else "FAIL"

    def record(self, r, outcome, rc):
        end = time.time()
        orphans = 0
        if r.pjob:
            orphans = r.pjob.active()
            if orphans:
                r.pjob.terminate()                    # a grandchild outliving its job would decode unslotted
            r.pjob.close()
        if r.logf:
            r.logf.close()
        row = {"kind": "job", "run": self.run, "job": r.job["id"], "attempt": r.attempt,
               "start": now_iso(r.start), "end": now_iso(end), "duration_s": round(end - r.start, 3),
               "exit_code": rc, "outcome": outcome, "verdict": self.verdict(r, outcome, rc),
               "slot": bool(r.slot), "pid": r.proc.pid if r.proc else None,
               "log": os.path.relpath(r.log, self.rdir).replace(os.sep, "/"),
               "orphans_killed": orphans, "job_object": r.assigned}
        append_jsonl(self.ledger, row)             # durable before the slot is given back
        if r.slot:
            r.slot.release()
        if r in self.running:
            self.running.remove(r)
        self.last[r.job["id"]] = row
        self.heartbeat(force=True)

    def kill(self, r, outcome):
        kill_tree(r.proc, r.pjob)
        self.record(r, outcome, r.proc.returncode)

    def step(self):
        now = time.time()
        for r in list(self.running):
            rc = r.proc.poll()
            if rc is not None:
                self.record(r, "exit", rc)
            elif now > r.deadline:
                self.event("timeout", job=r.job["id"], after_s=round(now - r.start, 1))
                self.kill(r, "timeout")

        src = stop_reason(self.run)
        if src and self.stop_since is None:
            self.stop_since, self.stop_src = now, src
            self.event("stop-seen", source=src, running=[r.job["id"] for r in self.running],
                       queued=len(self.queue), grace_s=self.opts.grace)
        if self.stop_since is not None and self.running and now - self.stop_since >= self.opts.grace:
            self.event("grace-expired", killing=[r.job["id"] for r in self.running])
            for r in list(self.running):
                self.kill(r, "stopped")

        waiting = False
        if self.stop_since is None and self.halt is None and self.queue:
            if now - self.disk_t >= DISK_EVERY_S:
                self.disk_t, self.free = now, free_gb()
                floor = slot_config()["min_free_gb"]
                floor = self.opts.min_free_gb if floor is None else floor
                low = self.free is not None and self.free < floor
                if low != self.paused:
                    self.paused = low
                    self.event("paused-disk" if low else "resumed-disk", free_gb=self.free, floor_gb=floor)
            if not self.paused:
                while self.queue and len(self.running) < self.opts.parallel:
                    drift = pin_key(pins())
                    if drift != self.base:
                        self.halt = {"expected": self.base, "found": drift}
                        self.event("halt", reason="converter or oracle manifest changed mid-run", **self.halt)
                        break
                    job, slot = self.queue[0], None
                    if job.get("slot", True):
                        if time.time() - self.slot_t < SLOT_RETRY_S:
                            waiting = True
                            break
                        slot = try_acquire_slot(self.run, job["id"])
                        if slot is None:
                            self.slot_t, waiting = time.time(), True
                            break
                    self.queue.pop(0)
                    self.launch(job, slot)
        if self.halt is not None:
            for r in list(self.running):
                self.kill(r, "halted")

        self.state = ("halted" if self.halt is not None else "stopping" if self.stop_since is not None
                      else "paused-disk" if self.paused else "waiting-slot" if waiting and not self.running
                      else "running")
        self.heartbeat()
        return bool(self.running) or (bool(self.queue) and self.stop_since is None and self.halt is None)

    def main(self):
        awake = keep_awake(True)
        self.event("start", jobs=len(self.jobs), queued=len(self.queue), skipped=self.skipped,
                   parallel=self.opts.parallel, keep_awake=awake)
        code = 0
        try:
            while self.step():
                time.sleep(POLL_S)
        except KeyboardInterrupt:
            self.event("interrupted", killing=[r.job["id"] for r in self.running])
            for r in list(self.running):
                self.kill(r, "stopped")
            self.stop_since = self.stop_since or time.time()
            self.stop_src = self.stop_src or "keyboard interrupt"
        finally:
            keep_awake(False)
            if self.halt is not None:
                self.state, code = "halted", 4
            elif self.stop_since is not None and (self.queue or any(
                    self.last.get(j["id"], {}).get("outcome") == "stopped" for j in self.jobs)):
                self.state, code = "stopped", 3
            else:
                self.state = "finished"
            self.heartbeat(force=True)
            self.event("end", state=self.state, remaining=len(self.queue))
        return code


# ---------------------------------------------------------------- commands

def cmd_run(args):
    run = args.run
    if not RUN_ID.match(run):
        raise SystemExit(f"run id {run!r}: letters, digits, '.', '_' and '-' only")
    args.retry = {k.strip() for k in (args.retry or "").split(",") if k.strip()}
    if args.retry - RETRY_KINDS:
        raise SystemExit(f"--retry takes {sorted(RETRY_KINDS)}")
    rdir = os.path.join(RUNS, run)
    src = stop_reason(run)
    if src:
        raise SystemExit(f"refusing to start {run}: {src} is present. Clear it with "
                         f"`supervise.py stop {'' if 'global' in src else run} --clear` when you mean to.")
    os.makedirs(rdir, exist_ok=True)
    frozen = os.path.join(rdir, "jobs.jsonl")
    if args.jobs:
        jobs = load_jobs(args.jobs)
        text = jobs_text(jobs)
        if os.path.exists(frozen):
            if open(frozen, encoding="utf-8").read() != text:
                raise SystemExit(f"{run} was frozen with a different job list ({frozen}); a run id names one "
                                 "job list, so start a new run id")
        else:
            write_atomic(frozen, text)
    elif os.path.exists(frozen):
        jobs = load_jobs(frozen)
        text = jobs_text(jobs)
    else:
        raise SystemExit(f"{run} has no frozen job list yet: pass --jobs")

    run_lock = PidLock(os.path.join(rdir, "supervisor.lock"), f"run lock of {run}")
    held = run_lock.holder()
    if held and holder_alive(held):
        raise SystemExit(f"{run} is already supervised by pid {held.get('pid')} since {held.get('since')}")
    if args.detach:
        return detach(args, rdir)

    if args._detached:
        logf = open(os.path.join(rdir, "supervisor.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = logf
    ok, held = run_lock.try_acquire(run=run)
    if not ok:
        raise SystemExit(f"{run} is already supervised by pid {held.get('pid')}")
    try:
        mpath = os.path.join(rdir, "manifest.json")
        manifest = read_json(mpath)
        cur = pins(full=True)
        if manifest is None or "_unreadable" in manifest:
            manifest = {"run": run, "created": now_iso(), "jobs_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "jobs": len(jobs), "jobs_source": os.path.abspath(args.jobs) if args.jobs else None,
                        "pins": cur, "attempts": []}
        elif pin_key(manifest.get("pins") or {}) != pin_key(cur) and not args.accept_pin_change:
            raise SystemExit(f"{run}: the converter or oracle manifest changed since this run began "
                             f"({pin_key(manifest.get('pins') or {})} -> {pin_key(cur)}); one run must not mix "
                             "them. Start a new run id, or pass --accept-pin-change if you mean it.")
        manifest["attempts"].append({
            "started": now_iso(), "pid": os.getpid(), "host": socket.gethostname(), "argv": sys.argv[1:],
            "python": sys.executable, "detached": bool(args._detached), "tool": tool_state(), "pins": cur,
            "options": {"timeout": args.timeout, "parallel": args.parallel, "grace": args.grace,
                        "threads": args.threads, "min_free_gb": args.min_free_gb, "retry": sorted(args.retry)}})
        write_json(mpath, manifest)
        lower_own_priority()
        return Supervisor(run, rdir, jobs, args, cur).main()
    finally:
        run_lock.release()


def detach(args, rdir):
    # The child starts in ROOT, so a relative --jobs path would miss; the list is frozen by now
    # anyway, and the child re-reads the frozen copy when given none.
    argv, rest = [], iter(sys.argv[1:])
    for a in rest:
        if a == "--detach":
            continue
        if a == "--jobs":
            next(rest, None)
            continue
        if a.startswith("--jobs="):
            continue
        argv.append(a)
    argv.append("--_detached")
    cmd = PY + [os.path.abspath(__file__)] + argv
    flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | BELOW_NORMAL
    t0 = time.time()
    kw = dict(cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    try:
        proc = subprocess.Popen(cmd, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **kw)
    except OSError:                                    # the enclosing job forbids breakaway
        proc = subprocess.Popen(cmd, creationflags=flags, **kw)
    hb_path = os.path.join(rdir, "heartbeat.json")
    for _ in range(60):
        hb = read_json(hb_path) or {}
        if hb.get("updated_ts", 0) >= t0 - 1 and proc_alive(hb.get("pid"), hb.get("created")):
            print(f"{args.run}: detached supervisor pid {hb['pid']} is {hb.get('state')}, "
                  f"{hb.get('completed')}/{hb.get('total')} done")
            break
        if proc.poll() is not None:
            print(f"{args.run}: the detached supervisor exited at once (code {proc.returncode}); "
                  f"see {os.path.join(rdir, 'supervisor.log')}", file=sys.stderr)
            return 1
        time.sleep(0.5)
    else:
        print(f"{args.run}: launched (launcher pid {proc.pid}); no heartbeat yet")
    print(f"  log:    {os.path.join(rdir, 'supervisor.log')}\n  status: supervise.py status {args.run}\n"
          f"  stop:   supervise.py stop {args.run}")
    return 0


def run_summary(run):
    rdir = os.path.join(RUNS, run)
    hb = read_json(os.path.join(rdir, "heartbeat.json")) or {}
    manifest = read_json(os.path.join(rdir, "manifest.json")) or {}
    last = {}
    for r in read_jsonl(os.path.join(rdir, "ledger.jsonl")):
        if r.get("kind") == "job":
            last[r["job"]] = r
    verdicts, done = {}, 0
    for r in last.values():
        if r.get("outcome") in FINISHED_OUTCOMES:
            done += 1
            verdicts[r.get("verdict")] = verdicts.get(r.get("verdict"), 0) + 1
    state = hb.get("state") or "never-started"
    alive = proc_alive(hb.get("pid"), hb.get("created")) if hb else False
    if state in ACTIVE_STATES and not alive:
        state = f"DEAD (last {state})"
    age = round(time.time() - hb["updated_ts"]) if hb.get("updated_ts") else None
    return {"run": run, "state": state, "pid": hb.get("pid"), "alive": alive,
            "total": manifest.get("jobs") or hb.get("total"), "completed": done, "verdicts": verdicts,
            "running": hb.get("running", []) if alive else [], "heartbeat_age_s": age,
            "updated": hb.get("updated"), "stop": stop_reason(run), "halt": hb.get("halt"),
            "attempts": len(manifest.get("attempts", []))}


def cmd_status(args):
    runs = args.runs or (sorted(os.listdir(RUNS), key=lambda r: os.path.getmtime(os.path.join(RUNS, r)))
                         if os.path.isdir(RUNS) else [])
    summaries = [run_summary(r) for r in runs if os.path.isdir(os.path.join(RUNS, r))]
    limit, hits = slot_limit()
    slots = [rec for _, rec in live_slots()]
    machine = {"slots_used": len(slots), "slots_limit": limit, "gaming": hits,
               "slots": [{k: s.get(k) for k in ("pid", "child", "run", "job", "since")} for s in slots],
               "commit_lock": read_json(COMMIT_LOCK), "main_lock": read_json(MAIN_LOCK),
               "global_stop": os.path.exists(GLOBAL_STOP), "free_gb": free_gb(), "state_dir": STATE}
    if args.json:
        print(json.dumps({"machine": machine, "runs": summaries}, indent=1, ensure_ascii=False))
        return 0
    print(f"slots {len(slots)}/{limit}" + (f" (gaming: {', '.join(hits)})" if hits else "")
          + f"   free {machine['free_gb']} GiB   global STOP: {'YES' if machine['global_stop'] else 'no'}")
    cl = machine["commit_lock"]
    print("commit lock: " + ("free" if not cl else f"pid {cl.get('pid')} run {cl.get('run')} since {cl.get('since')}"
                             + ("" if holder_alive(cl) else " (holder dead: stale)")))
    ml = machine["main_lock"]
    print("main lock:   " + ("free" if not ml else f"HELD: {ml.get('note')} ({ml.get('since')})"))
    for s in machine["slots"]:
        print(f"  slot: pid {s['pid']} child {s['child']} run {s['run']} job {s['job']} since {s['since']}")
    for s in summaries:
        verd = ", ".join(f"{k} {v}" for k, v in sorted(s["verdicts"].items(), key=lambda kv: -kv[1]))
        print(f"\n{s['run']}: {s['state']}  {s['completed']}/{s['total']} done"
              + (f"  pid {s['pid']}" if s["alive"] else "")
              + (f"  heartbeat {s['heartbeat_age_s']}s ago" if s["heartbeat_age_s"] is not None else "")
              + (f"  attempts {s['attempts']}" if s["attempts"] > 1 else ""))
        if verd:
            print(f"  verdicts: {verd}")
        for r in s["running"]:
            print(f"  running: {r['job']} (pid {r['pid']}, since {r['since']})")
        if s["stop"]:
            print(f"  {s['stop']}")
        if s["halt"]:
            print(f"  HALTED: {s['halt']}")
    return 0


def cmd_stop(args):
    if args.run:
        rdir = os.path.join(RUNS, args.run)
        if not os.path.isdir(rdir):
            raise SystemExit(f"no run {args.run} under {RUNS}")
        path = os.path.join(rdir, "STOP")
    else:
        path = GLOBAL_STOP
    if args.clear:
        if os.path.exists(path):
            os.remove(path)
            print(f"cleared {path}")
        else:
            print(f"no {path}")
        return 0
    write_json(path, {"at": now_iso(), "by_pid": os.getpid(), "reason": args.reason or ""})
    print(f"created {path}: no new job starts; running jobs get {GRACE_S // 60} minutes (the run's --grace) "
          "before they are killed")
    return 0


def cmd_slots(args):
    if args.max is not None or args.gaming_max is not None or args.min_free_gb is not None:
        cfg_path = os.path.join(SLOTS, "config.json")
        cfg = read_json(cfg_path) or {}
        cfg = {} if "_unreadable" in cfg else cfg
        if args.max is not None:
            cfg["max"] = max(0, min(args.max, SLOT_MAX))
        if args.gaming_max is not None:
            cfg["gaming_max"] = max(0, min(args.gaming_max, SLOT_MAX_GAMING))
        if args.min_free_gb is not None:
            cfg["min_free_gb"] = args.min_free_gb
        write_json(cfg_path, cfg)
        print(f"wrote {cfg_path}: {cfg}")
    with FileMutex(os.path.join(SLOTS, ".mutex")):
        live = live_slots(recover=True)
    limit, hits = slot_limit()
    print(f"{len(live)}/{limit} slots held" + (f" (gaming: {', '.join(hits)})" if hits else "") + f"; config {slot_config()}")
    for _, rec in live:
        print(f"  pid {rec.get('pid')} child {rec.get('child')} run {rec.get('run')} job {rec.get('job')} since {rec.get('since')}")
    return 0


def cmd_lock_exec(args):
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        raise SystemExit("lock-exec needs a command after --")
    with commit_lock(run=args.run, purpose="lock-exec", timeout=args.timeout):
        return subprocess.call(cmd)


def cmd_commitlock(args):
    cur = read_json(COMMIT_LOCK)
    if not cur:
        print("commit lock: free")
        return 0
    alive = holder_alive(cur)
    print(f"commit lock: pid {cur.get('pid')} run {cur.get('run')} purpose {cur.get('purpose')} since "
          f"{cur.get('since')} ({'alive' if alive else 'DEAD: stale'})")
    if args.break_ and (not alive or args.force):
        with FileMutex(COMMIT_LOCK + ".mutex"):
            if read_json(COMMIT_LOCK) == cur:
                os.remove(COMMIT_LOCK)
                rails_event("lock-broken", lock="commit lock", holder=cur, forced=alive)
                print("removed")
    elif args.break_:
        print("its holder is alive; --force removes it anyway (only if you know that process is wedged)")
        return 1
    return 0


def cmd_mainlock(args):
    if args.action == "show":
        cur = read_json(MAIN_LOCK)
        print("main lock: free" if cur is None else f"main lock HELD: {json.dumps(cur, ensure_ascii=False)}")
        return 0 if cur is None else 1
    if args.action == "take":
        if not args.note:
            raise SystemExit("mainlock take needs --note saying who is merging what")
        os.makedirs(STATE, exist_ok=True)
        try:
            fd = os.open(MAIN_LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            print(f"main lock already held: {open(MAIN_LOCK, encoding='utf-8').read().strip()}", file=sys.stderr)
            return 1
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"note": args.note, "since": now_iso(), "host": socket.gethostname(),
                       "user": os.environ.get("USERNAME") or os.environ.get("USER"), "pid": os.getpid()}, fh)
            fh.write("\n")
        print(f"took {MAIN_LOCK}; pushes are refused until `supervise.py mainlock release`")
        return 0
    if os.path.exists(MAIN_LOCK):
        print(f"released: {open(MAIN_LOCK, encoding='utf-8').read().strip()}")
        os.remove(MAIN_LOCK)
    else:
        print("main lock was not held")
    return 0


# ---------------------------------------------------------------- worktrees and preflight

def main_checkout():
    out = git("worktree", "list", "--porcelain")
    if out.returncode != 0:
        raise SystemExit(out.stderr)
    return os.path.normpath(out.stdout.splitlines()[0].split(" ", 1)[1])


def worktrees():
    out = git("worktree", "list", "--porcelain").stdout
    return [os.path.normcase(os.path.normpath(line.split(" ", 1)[1])) for line in out.splitlines() if line.startswith("worktree ")]


def same_dir(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def cmd_worktree(args):
    name = args.name
    if not RUN_ID.match(name):
        raise SystemExit(f"worktree name {name!r}: letters, digits, '.', '_' and '-' only")
    main = main_checkout()
    wt = os.path.join(os.path.dirname(main), "psf-wt", name)
    branch = f"loops/{name}"
    if os.path.exists(wt):
        raise SystemExit(f"{wt} already exists")
    if git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        raise SystemExit(f"branch {branch} already exists")
    base = git("rev-parse", "--verify", f"{args.base}^{{commit}}")
    if base.returncode != 0:
        raise SystemExit(f"base {args.base!r} is not a commit")
    r = git("worktree", "add", "-b", branch, wt, base.stdout.strip(), cwd=main)
    if r.returncode != 0:
        raise SystemExit(f"git worktree add failed:\n{r.stderr}")
    print(f"created {wt} on {branch} at {base.stdout.strip()[:10]}")
    for sub in ("work", "videos"):
        link, target = os.path.join(wt, sub), os.path.join(main, sub)
        r = quiet(["cmd", "/c", "mklink", "/J", link, target])
        if r.returncode != 0 or not same_dir(link, target):
            raise SystemExit(f"junction {link} -> {target} failed: {r.stdout}{r.stderr}")
        print(f"  {sub}/ -> {target} (junction)")
    if args.no_preflight:
        return 0
    own = os.path.join(wt, "tools", "supervise.py")
    if not os.path.exists(own):
        print(f"no preflight: {args.base} predates tools/supervise.py, so the new worktree has none to run")
        return 1
    return subprocess.call(PY + [own, "preflight"], cwd=wt)


def cmd_worktree_remove(args):
    main = main_checkout()
    wt = os.path.normpath(os.path.join(os.path.dirname(main), "psf-wt", args.name))
    if os.path.normcase(wt) not in worktrees() or same_dir(wt, main):
        raise SystemExit(f"{wt} is not a linked worktree of this repository")
    for sub in ("work", "videos"):
        link = os.path.join(wt, sub)
        if not os.path.lexists(link):
            continue
        if not os.path.isjunction(link):
            raise SystemExit(f"{link} is a real directory, not a junction: refusing to remove this worktree")
        target = os.path.join(main, sub)
        before = len(os.listdir(target))
        os.rmdir(link)                                 # removes the junction itself, never what it points at
        after = len(os.listdir(target))
        if after != before:
            raise SystemExit(f"{target} changed from {before} to {after} entries while unlinking: stopping")
        print(f"unlinked {link} ({target} intact: {after} entries)")
    r = git("worktree", "remove", wt, cwd=main)
    if r.returncode != 0:
        raise SystemExit(f"git worktree remove failed (left in place):\n{r.stderr}")
    print(f"removed worktree {wt}")
    if args.delete_branch:
        branch = f"loops/{args.name}"
        r = git("branch", "-D" if args.force_branch else "-d", branch, cwd=main)
        print(r.stdout.strip() or r.stderr.strip())
        return r.returncode
    return 0


IMPORT_PROBE = r"""
import contextlib, importlib, io, json, os, re, sys
tools, converter = sys.argv[1], sys.argv[2]
never = set(sys.argv[3].split(","))
sys.path.insert(0, converter)
sys.path.insert(0, tools)
res = {}
for f in sorted(os.listdir(tools)):
    if not f.endswith(".py"):
        continue
    name, path = f[:-3], os.path.join(tools, f)
    src = open(path, encoding="utf-8", errors="replace").read()
    guarded = re.search(r"__name__\s*==\s*['\"]__main__['\"]", src) is not None
    try:
        compile(src, path, "exec")
        if name in never or (not guarded and "sys.argv" in src):
            res[name] = "compiled"
            continue
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            importlib.import_module(name)
        res[name] = "imported"
    except SystemExit as e:
        res[name] = f"FAIL exit {e.code}"
    except BaseException as e:
        res[name] = f"FAIL {type(e).__name__}: {str(e)[:200]}"
print("PROBE" + json.dumps(res))
"""

CONVERTER_PROBE = r"""
import sys
sys.path.insert(0, sys.argv[1])
from piu_annotate.formats import ssc_to_chartstruct as C
from piu_annotate.formats.sscfile import StepchartSSC
print("PROBE" + getattr(C, "HOLD_TICK_MODEL", "legacy"))
"""


def cmd_preflight(args):
    fails = []

    def check(ok, what):
        print(("ok    " if ok else "FAIL  ") + what)
        if not ok:
            fails.append(what)
    main = main_checkout()
    linked = not same_dir(ROOT, main)
    for sub in ("work", "videos"):
        p = os.path.join(ROOT, sub)
        if linked:
            check(os.path.isjunction(p) and same_dir(p, os.path.join(main, sub)),
                  f"{sub}/ is a junction to {os.path.join(main, sub)}")
        else:
            check(os.path.isdir(p), f"{sub}/ exists (main checkout)")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    conv_repo = os.path.dirname(converter_dir() or CONVERTER_REPO)
    r = subprocess.run(PY + ["-c", CONVERTER_PROBE, conv_repo], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, creationflags=QUIET, cwd=ROOT, timeout=300)
    model = r.stdout.split("PROBE")[-1].strip() if "PROBE" in r.stdout else None
    check(r.returncode == 0 and model == "lattice",
          f"converter imports from {conv_repo} and counts ticks by the lattice (HOLD_TICK_MODEL = {model!r})"
          + ("" if r.returncode == 0 else f": {r.stderr.strip()[-300:]}"))
    p = pins(full=True)
    conv = p["converter"] or {}
    print(f"      converter py_sha256 {conv.get('py_sha256')} ({conv.get('files')} files, git {str(conv.get('git_head'))[:10]}"
          f"{', DIRTY' if conv.get('git_dirty') else ''}); oracle manifest {p['oracle']['sha256'] or 'absent'}")
    r = subprocess.run(PY + ["-c", IMPORT_PROBE, TOOLS, conv_repo, ",".join(sorted(NEVER_IMPORT))], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, creationflags=QUIET, cwd=ROOT, timeout=900)
    try:
        res = json.loads(r.stdout.split("PROBE")[-1])
    except ValueError:
        res = {"(probe)": f"FAIL {r.stderr.strip()[-300:]}"}
    bad = {k: v for k, v in res.items() if v.startswith("FAIL")}
    check(not bad, f"tools import: {sum(v == 'imported' for v in res.values())} imported, "
                   f"{sum(v == 'compiled' for v in res.values())} scripts compiled")
    for k, v in bad.items():
        print(f"      {k}: {v}")
    st = tool_state()
    print(f"      branch {st['branch']} at {str(st['head'])[:10]}{'; tools/ has uncommitted changes' if st['tools_dirty'] else ''}")
    hooks = git("config", "--get", "core.hooksPath").stdout.strip()
    print(f"      core.hooksPath = {hooks or '(unset: the pre-push main-lock guard is off)'}")
    print(f"      free {free_gb()} GiB; slots {len(live_slots())}/{slot_limit()[0]}; STOP {'present' if stop_reason() else 'absent'}")
    if args.videos or args.open_videos:
        vids = sorted({v["vid"] for v in json.load(open(os.path.join(ROOT, "sources", "video-map.json"), encoding="utf-8"))
                       if v.get("download", True)})
        have = {os.path.splitext(f)[0]: os.path.join(ROOT, "videos", f) for f in os.listdir(os.path.join(ROOT, "videos"))
                if not f.endswith((".part", ".ytdl"))}
        missing = [v for v in vids if v not in have or os.path.getsize(have[v]) == 0]
        check(not missing, f"video-map videos present and non-empty: {len(vids) - len(missing)}/{len(vids)}"
                           + (f" (missing {missing[:5]})" if missing else ""))
        if args.open_videos:
            import cv2
            broken = []
            for v in vids:
                if v in have:
                    cap = cv2.VideoCapture(have[v])
                    ok = cap.isOpened() and cap.read()[0]
                    cap.release()
                    if not ok:
                        broken.append(v)
            check(not broken, f"video-map videos open and decode a frame: {len(vids) - len(broken)}/{len(vids)}"
                              + (f" (broken {broken[:5]})" if broken else ""))
    print("preflight " + ("PASSED" if not fails else f"FAILED ({len(fails)})"))
    return 0 if not fails else 1


def cmd_pins(args):
    print(json.dumps(pins(full=True), indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="The rails unattended loops run on (see the header of this file).")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run (or resume) a loop's jobs")
    p.add_argument("run")
    p.add_argument("--jobs", help="jobs file (JSON lines or a .json list); frozen into the run on first use")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="per-job timeout in seconds (a job's own 'timeout' wins)")
    p.add_argument("--parallel", type=int, default=SLOT_MAX, help="jobs this run keeps in flight (the slot pool caps it machine-wide)")
    p.add_argument("--grace", type=float, default=GRACE_S, help="seconds running jobs get after a STOP before taskkill /T")
    p.add_argument("--threads", type=int, choices=(1, 2), default=2, help="OMP/BLAS/OpenCV threads per child")
    p.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB, help="pause launches below this many GiB free on C:")
    p.add_argument("--retry", default="", help="re-run finished jobs of these kinds on resume: nonzero,timeout,launch-error")
    p.add_argument("--detach", action="store_true", help="relaunch detached (outlives this terminal) and return")
    p.add_argument("--accept-pin-change", action="store_true", help="resume although the converter/oracle hash changed")
    p.add_argument("--_detached", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("status", help="summarize runs from their ledgers and heartbeats")
    p.add_argument("runs", nargs="*")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("stop", help="create (or --clear) work/STOP or a run's STOP")
    p.add_argument("run", nargs="?")
    p.add_argument("--reason")
    p.add_argument("--clear", action="store_true")
    p.set_defaults(fn=cmd_stop)

    p = sub.add_parser("slots", help="show the decode-slot pool; --max/--gaming-max/--min-free-gb set its config")
    p.add_argument("--max", type=int)
    p.add_argument("--gaming-max", type=int)
    p.add_argument("--min-free-gb", type=float)
    p.set_defaults(fn=cmd_slots)

    p = sub.add_parser("lock-exec", help="run a command holding the commit lock")
    p.add_argument("--run")
    p.add_argument("--timeout", type=float)
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_lock_exec)

    p = sub.add_parser("commitlock", help="show the commit lock; --break removes a dead holder's")
    p.add_argument("--break", dest="break_", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_commitlock)

    p = sub.add_parser("mainlock", help="take/release/show work/.main.lock (the pre-push hook's guard)")
    p.add_argument("action", choices=("take", "release", "show"))
    p.add_argument("--note")
    p.set_defaults(fn=cmd_mainlock)

    p = sub.add_parser("worktree", help="create ../psf-wt/<name> on loops/<name> with work/ and videos/ junctions")
    p.add_argument("name")
    p.add_argument("--base", required=True)
    p.add_argument("--no-preflight", action="store_true")
    p.set_defaults(fn=cmd_worktree)

    p = sub.add_parser("worktree-remove", help="unlink the junctions, then remove ../psf-wt/<name>")
    p.add_argument("name")
    p.add_argument("--delete-branch", action="store_true")
    p.add_argument("--force-branch", action="store_true", help="delete the branch even if unmerged (git branch -D)")
    p.set_defaults(fn=cmd_worktree_remove)

    p = sub.add_parser("preflight", help="check junctions, the converter, and that every tool imports")
    p.add_argument("--videos", action="store_true", help="also check every video-map video is present")
    p.add_argument("--open-videos", action="store_true", help="also open each one and decode a frame (slow)")
    p.set_defaults(fn=cmd_preflight)

    p = sub.add_parser("pins", help="print the converter and oracle-manifest pins")
    p.set_defaults(fn=cmd_pins)

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
