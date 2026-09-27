# The rails every unattended loop runs on: a supervisor that runs a loop's jobs (one subprocess
# per chart) for days on the owner's own PC, which he also games on, without corrupting the
# shared caches, each other, or main. Owner go: 2026-09-27 (loop buckets, #1 "Rails").
#
#   supervise.py run <run> --jobs <jobs.jsonl> [--timeout S] [--parallel N] [--grace S]
#                          [--threads 1|2] [--min-free-gb G] [--retry nonzero,timeout,launch-error]
#                          [--transient-budget S] [--detach] [--accept-pin-change]
#                          [--converter-unpinned]
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
# - Slots are counted, not numbered: while Wow.exe runs (one Toolhelp32 process snapshot every
#   15 s; tasklist, ~6 s here, only as the fallback) the limit drops from 6 to 2, and a
#   numbered pool would let a new job take a free low number while four high ones still decode.
#   Counting and creating happen under an OS byte-range lock (released by the kernel when its
#   holder dies, so it can never go stale); a slot file whose owner AND child are both dead is
#   recovered by PID liveness, with the process creation time checked so a reused PID does not
#   keep a dead slot alive.
# - The limit binds jobs already running, not just new launches: when it falls below the slots
#   held (the game starts, or `slots --max` is lowered), every supervisor ranks the live slots
#   machine-wide by when they were taken, and freezes its own jobs that rank past the limit —
#   every process in the job object is suspended (NtSuspendProcess), so a frozen decoder uses no
#   CPU while the owner plays. Frozen jobs keep their slots, so nothing new launches; they thaw
#   oldest first as running jobs finish or the game exits, and time spent frozen does not count
#   against their timeout. A slot taken in-process through decode_slot() cannot be frozen, so it
#   ranks first. A job without a job object cannot be frozen as a whole, so it is killed and
#   queued again instead. A game check that fails counts as the game running (fail closed).
# - A freeze never strands a lock. The supervisor freezes only while it holds every rails mutex
#   itself (the commit lock's, the slot pool's, rails-events'), so a frozen process is inside
#   none of them; and a job whose processes hold the commit lock is not frozen at all until it
#   lets go (the pool runs one past its limit for that long): frozen, it would hold every loop's
#   commits and gate-failure reverts for as long as the owner plays. A lock or mutex wait counts
#   only the time its process was awake, so a job frozen while waiting is not refused the moment
#   it thaws.
# - A supervisor error does not end a multi-day run: an OSError or subprocess timeout inside a
#   step (a full disk, a file an antivirus holds past the retries) is logged and
#   retried with backoff for --transient-budget seconds; past that, or on any other exception,
#   the run ends as "crashed" (exit 5) with the traceback in events.jsonl and supervisor.log,
#   its running jobs killed and left unfinished — never as "finished".
# - Every child runs in its own Windows job object (kill-on-close) as well as under taskkill /T:
#   the piu-annotate venv's python.exe is a launcher that starts the real interpreter as a
#   child, and a tool may start ffmpeg or a pool of its own. The child is created suspended and
#   resumed only once it is in the job, so the real interpreter can never start outside it (a
#   supervisor descheduled between the two under load would otherwise lose it every time). The
#   job object reaps what
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
# FAIL by exit code (TIMEOUT, STOPPED, HALTED, CRASHED, PREEMPTED and LAUNCH_ERROR are the
# supervisor's own).
# Children see PSF_RUN, PSF_JOB, PSF_RUN_DIR and PSF_SLOT_HELD=1 when they hold a slot (so a
# child that asks decode_slot() for one does not deadlock against its own supervisor).
#
# Resume: re-running a run id re-reads its frozen jobs.jsonl and skips every job whose latest
# ledger row finished (outcome exit, timeout or launch-error); --retry re-runs the named kinds.
# A job killed by STOP, a halt, a crash or a preemption, or running when a supervisor died, has
# no finished row and runs again.
#
# Exit codes of `run`: 0 finished (every job has a finished row, whatever its verdict),
# 3 stopped, 4 halted, 5 crashed.
#
# PSF_RAILS_STATE relocates all of the shared state above (for the self-test only);
# PSF_GAME_EXES overrides the game list and PSF_GAME_POLL_S how often it is checked (15 s);
# PSF_CONVERTER_REPO points at another converter clone.
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
import traceback
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
GAME_POLL_S = float(os.environ.get("PSF_GAME_POLL_S") or 15)
GAME_CHECK_FAILED = "(game check failed)"   # what an unanswered game check counts as: a game running
MIN_FREE_GB = 40             # GiB free on C: (and on work/'s drive) below which launches pause; never lower
GRACE_S = 600                # after a STOP, running jobs get this long before taskkill /T
DEFAULT_TIMEOUT_S = 7200
TRANSIENT_BUDGET_S = 1800    # how long one supervisor error may persist before the run crashes
RETRY_BASE_S, RETRY_MAX_S = 5.0, 300.0
POLL_S = 0.5
SLOT_RETRY_S = 2.0
PREEMPT_EVERY_S = 1.0
QUIESCE_TIMEOUT_S = 5.0      # how long a freeze waits for the rails mutexes before trying again next round
AWAKE_GAP_S = 2.0            # a lock wait's poll gap longer than its poll plus this was spent frozen (or asleep)
DISK_EVERY_S = 30
HEARTBEAT_EVERY_S = 30
ACTIVE_STATES = {"running", "waiting-slot", "paused-disk", "stopping", "suspended", "retrying"}
FINISHED_OUTCOMES = {"exit", "timeout", "launch-error"}
RETRY_KINDS = {"nonzero", "timeout", "launch-error"}
EXIT_STOPPED, EXIT_HALTED, EXIT_CRASHED = 3, 4, 5
TRANSIENT = (OSError, subprocess.SubprocessError)   # TimeoutError is an OSError
NEVER_IMPORT = {"download_videos", "run_corpus", "catalog_sweep", "video_refresh_sql"}  # preflight compiles these only

IS_WIN = os.name == "nt"
BELOW_NORMAL = 0x00004000
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_SUSPENDED = 0x00000004
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
    # Many processes write this log; an append is not atomic across processes on Windows, so
    # the append is serialized. It is a log: failing to write it must never fail the lock or
    # slot operation that is reporting.
    rec = {"t": now_iso(), "event": event, "pid": os.getpid(), **kw}
    try:
        try:
            with FileMutex(RAILS_LOG + ".mutex", timeout=10):
                append_jsonl(RAILS_LOG, rec)
        except TimeoutError:
            append_jsonl(RAILS_LOG, rec)
    except OSError as e:
        print(f"rails-events.jsonl not written ({e}): {json.dumps(rec, ensure_ascii=False)}", file=sys.stderr, flush=True)


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

    _PID_LIST_MAX = 512

    class _PidList(ctypes.Structure):                  # JOBOBJECT_BASIC_PROCESS_ID_LIST
        _fields_ = [("Assigned", W.DWORD), ("InList", W.DWORD), ("Ids", ctypes.c_size_t * _PID_LIST_MAX)]

    # NtSuspendProcess/NtResumeProcess suspend or resume every thread of a process in one call
    # (what Process Explorer and psutil use); Win32 has no documented whole-process suspend.
    _ntdll = ctypes.WinDLL("ntdll")
    _NtSuspendProcess = _ntdll.NtSuspendProcess
    _NtSuspendProcess.restype, _NtSuspendProcess.argtypes = ctypes.c_long, [W.HANDLE]
    _NtResumeProcess = _ntdll.NtResumeProcess
    _NtResumeProcess.restype, _NtResumeProcess.argtypes = ctypes.c_long, [W.HANDLE]
    _SUSPEND_ACCESS = 0x0800 | 0x1000                  # PROCESS_SUSPEND_RESUME | QUERY_LIMITED_INFORMATION

    class _ProcessEntry(ctypes.Structure):             # PROCESSENTRY32W
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                    ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", W.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    _CreateToolhelp32Snapshot = _fn("CreateToolhelp32Snapshot", W.HANDLE, W.DWORD, W.DWORD)
    _Process32FirstW = _fn("Process32FirstW", W.BOOL, W.HANDLE, ctypes.POINTER(_ProcessEntry))
    _Process32NextW = _fn("Process32NextW", W.BOOL, W.HANDLE, ctypes.POINTER(_ProcessEntry))

    def _snapshot_images():
        """Every running image name from one Toolhelp32 snapshot: the names tasklist prints, in
        milliseconds instead of the ~6 s tasklist takes here with a few hundred processes."""
        snap = _CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            raise OSError(f"CreateToolhelp32Snapshot failed (error {ctypes.get_last_error()})")
        try:
            entry, names = _ProcessEntry(), set()
            entry.dwSize = ctypes.sizeof(entry)
            ok = _Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                names.add(entry.szExeFile.lower())
                ok = _Process32NextW(snap, ctypes.byref(entry))
            return names
        finally:
            _CloseHandle(snap)

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
    """A kill-on-close Windows job object holding one child and everything it starts; it can
    freeze the whole tree (suspend) and thaw it (resume)."""

    def __init__(self):
        self.h = _CreateJobObjectW(None, None) if IS_WIN else None
        self.frozen = {}                               # pid -> creation time, of the processes this froze
        self.unfreezable = set()                       # pids it could not open or suspend (not retried)
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

    def pids(self):
        if not self.h:
            return []
        buf = _PidList()
        ok = _QueryInformationJobObject(self.h, 3, ctypes.byref(buf), ctypes.sizeof(buf), None)
        if not ok and ctypes.get_last_error() != 234:  # ERROR_MORE_DATA: the list holds what fit
            return []
        return [int(buf.Ids[i]) for i in range(min(buf.InList, _PID_LIST_MAX))]

    def unfrozen(self):
        """Processes in the job this has not frozen: after a freeze, one the job was starting as
        it was being frozen."""
        return [pid for pid in self.pids() if pid not in self.frozen and pid not in self.unfreezable]

    def suspend(self):
        """Suspend every process in the job not already frozen; returns how many it froze. Called
        again while frozen, it catches a process the job started as it was being frozen."""
        n = 0
        for pid in self.unfrozen():
            h = _OpenProcess(_SUSPEND_ACCESS, False, pid)
            if not h:
                self.unfreezable.add(pid)
                continue
            try:
                born = _filetime(h)
                if _NtSuspendProcess(h) == 0:
                    self.frozen[pid] = born
                    n += 1
                else:
                    self.unfreezable.add(pid)
            finally:
                _CloseHandle(h)
        return n

    def resume(self):
        """Resume exactly the processes this froze that are still in the job (same PID and same
        creation time); returns how many it thawed."""
        inside, n = set(self.pids()), 0
        for pid, born in list(self.frozen.items()):
            del self.frozen[pid]
            if pid not in inside:
                continue
            h = _OpenProcess(_SUSPEND_ACCESS, False, pid)
            if not h:
                continue
            try:
                if _filetime(h) == born and _NtResumeProcess(h) == 0:
                    n += 1
            finally:
                _CloseHandle(h)
        return n

    def terminate(self):
        if self.h:
            _TerminateJobObject(self.h, 1)

    def close(self):
        if self.h:
            _CloseHandle(self.h)
            self.h = None


def resume_created(proc):
    """Start a child created with CREATE_SUSPENDED (every thread of it, through the process handle
    Popen keeps; Popen closes the thread handle). Returns the NTSTATUS: 0 when it runs."""
    return _NtResumeProcess(W.HANDLE(int(proc._handle)))


def kill_tree(proc, pjob=None):
    # Never raises: a taskkill that hangs or fails still leaves the job object and
    # TerminateProcess to take the tree down.
    if IS_WIN:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            quiet(["taskkill", "/T", "/F", "/PID", str(proc.pid)], timeout=60)
        if pjob:
            pjob.terminate()
    with contextlib.suppress(OSError):
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
    """Every running image name, lowercased: one Toolhelp32 snapshot, or tasklist when the snapshot
    fails. Raises when neither answers (an empty list counts as no answer: System is always
    running), so a caller can never mistake 'unknown' for 'no game'."""
    if not IS_WIN:
        return set()
    try:
        names = _snapshot_images()
        if len(names) > 1:
            return names
    except OSError:
        pass
    r = quiet(["tasklist", "/FO", "CSV", "/NH"], timeout=60)
    names = {line.split('","')[0].strip('"').lower() for line in r.stdout.splitlines() if line.startswith('"')}
    if r.returncode != 0 or not names:
        raise OSError(f"tasklist exit {r.returncode}, {len(names)} processes listed: {r.stderr.strip()[:200]}")
    return names


_game = {"t": 0.0, "hits": [], "failed": False}


def games_running(max_age=None):
    """The configured game images now running. Fails closed: when the check itself fails, the
    answer is [GAME_CHECK_FAILED], which lowers the limit exactly as a running game does."""
    if time.time() - _game["t"] > (GAME_POLL_S if max_age is None else max_age):
        try:
            names = running_images()
            hits, failed = sorted(e for e in GAME_EXES if e in names), None
        except TRANSIENT as e:
            hits, failed = [GAME_CHECK_FAILED], f"{type(e).__name__}: {e}"
        if bool(failed) != _game["failed"]:            # log the transitions, not every poll
            rails_event("game-check-failed" if failed else "game-check-recovered", error=failed)
        _game.update(t=time.time(), hits=hits, failed=bool(failed))
    return _game["hits"]


# ---------------------------------------------------------------- locks

class AwakeClock:
    """Time spent waiting, counting only the time this process was awake: a gap between two polls
    far longer than the poll is time it spent frozen by a supervisor (or the machine asleep), and
    a job frozen while it waited for a lock must not be refused the moment it thaws."""

    def __init__(self, poll):
        self.cap, self.waited, self.last = poll + AWAKE_GAP_S, 0.0, time.time()

    def tick(self):
        now = time.time()
        self.waited += min(max(0.0, now - self.last), self.cap)
        self.last = now
        return self.waited


class FileMutex:
    """An OS byte-range lock. The kernel drops it when its holder dies, so it never goes stale;
    it guards the few-millisecond read-check-write of the PID lock files and the slot pool."""

    def __init__(self, path, timeout=120):
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        clock = AwakeClock(0.02)
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
                if clock.tick() > self.timeout:
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
        clock, said = AwakeClock(poll), False
        while True:
            ok, cur = self.try_acquire(**info)
            if ok:
                return cur
            if not quiet_wait and not said:
                print(f"waiting for the {self.name}: held by pid {cur.get('pid')} (run {cur.get('run')}, "
                      f"since {cur.get('since')})", file=sys.stderr, flush=True)
                said = True
            waited = clock.tick()
            if timeout is not None and waited > timeout:
                raise TimeoutError(f"{self.name} still held by pid {cur.get('pid')} after {timeout}s")
            if stop_run is not False and stop_reason(stop_run):
                raise StopRequested(stop_reason(stop_run))
            time.sleep(poll)

    def set_child(self, pid):
        """Name the process doing the locked work, so the lock stays held while it runs even if
        the process that took the lock is killed without its tree."""
        with FileMutex(self.mutex):
            cur = read_json(self.path)
            if not cur or cur.get("token") != self.mine["token"]:
                raise OSError(f"the {self.name} is no longer ours: {cur}")
            self.mine.update(child=pid, child_created=proc_created(pid))
            write_json(self.path, self.mine)

    def release(self):
        # Never raises: the work under the lock is done by now, and a release that fails leaves
        # a lock naming a process that is about to exit, which the next acquirer recovers.
        if not self.mine:
            return
        try:
            with FileMutex(self.mutex):
                cur = read_json(self.path)
                if cur and cur.get("token") == self.mine["token"]:
                    _retry(lambda: os.remove(self.path))
                else:
                    rails_event("lock-lost", lock=self.name, mine=self.mine, found=cur)
        except OSError as e:
            rails_event("lock-release-failed", lock=self.name, mine=self.mine, error=f"{type(e).__name__}: {e}")
            print(f"warning: the {self.name} was not released ({e}); it is recovered as stale once this "
                  "process exits", file=sys.stderr, flush=True)
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


# Every FileMutex the rails take, in the one order anything takes more than one of them in
# (PidLock.try_acquire logs to rails-events inside the commit-lock mutex, live_slots(recover=True)
# inside the slot-pool mutex; nothing takes them the other way round).
RAILS_MUTEXES = (COMMIT_LOCK + ".mutex", os.path.join(SLOTS, ".mutex"), RAILS_LOG + ".mutex")


@contextlib.contextmanager
def rails_quiesced(timeout=QUIESCE_TIMEOUT_S):
    """Hold every rails mutex at once. A process suspended inside this is inside none of them, and
    cannot take or give up the commit lock while it is held, so the lock file is the truth about
    who holds it. Raises TimeoutError when one stays held (the caller tries again later); never
    call rails_event() inside it — this process already holds that log's mutex."""
    with contextlib.ExitStack() as stack:
        for path in RAILS_MUTEXES:
            stack.enter_context(FileMutex(path, timeout=timeout))
        yield


def commit_lock_pids():
    """The live processes the commit lock names: its taker and, for lock-exec, the child doing the
    locked work. Empty when it is free, unreadable (which the next acquirer recovers) or dead."""
    rec = read_json(COMMIT_LOCK)
    if not rec or "_unreadable" in rec:
        return set()
    out = set()
    for pid, created in ((rec.get("pid"), rec.get("created")), (rec.get("child"), rec.get("child_created"))):
        with contextlib.suppress(TypeError, ValueError):
            if pid and proc_alive(int(pid), created):
                out.add(int(pid))
    return out


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
    try:
        floor = free_floor(float(cfg["min_free_gb"])) if cfg.get("min_free_gb") is not None else None
    except (TypeError, ValueError):
        floor = None
    return {"max": clamp(cfg.get("max", SLOT_MAX), SLOT_MAX, SLOT_MAX),
            "gaming_max": clamp(cfg.get("gaming_max", SLOT_MAX_GAMING), SLOT_MAX_GAMING, SLOT_MAX_GAMING),
            "min_free_gb": floor}


def free_floor(gb):
    """The free-space floor may be raised, never lowered below MIN_FREE_GB (the owner's 40 GB)."""
    return max(float(MIN_FREE_GB), float(gb))


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


def try_acquire_slot(run=None, job=None, suspendable=False):
    # Frozen slots count: while a game has jobs frozen, nothing new launches until the frozen
    # ones have thawed and finished.
    limit, hits = slot_limit()                         # the game check runs outside the mutex
    with FileMutex(os.path.join(SLOTS, ".mutex")):
        if len(live_slots(recover=True)) >= limit:
            return None
        rec = me_record(run=run, job=job, child=None, child_created=None, limit=limit, gaming=hits,
                        suspendable=bool(suspendable))
        path = os.path.join(SLOTS, f"slot-{os.getpid()}-{rec['token'][:12]}.json")
        write_json(path, rec)
    return Slot(path, rec)


@contextlib.contextmanager
def decode_slot(run=None, job=None, poll=SLOT_RETRY_S):
    """For a tool that decodes in-process: `with supervise.decode_slot(): ...`. A no-op inside a
    supervised job that already holds one (PSF_SLOT_HELD=1). Raises StopRequested on STOP.
    Such a slot cannot be frozen when the game starts, so it ranks ahead of supervised jobs,
    which freeze around it; a tool holding one should keep each hold short."""
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


def frozen_converter_pin(pkg, manifest_path=None):
    """The converter against the pin frozen in sources/oracle-manifest.json, when the manifest
    carries one (corpus_grade.py's CONVERTER PIN: sha256 over "<path>\\t<sha256>\\n" lines, sorted,
    for the modules the conversion loads, each file's sha256 taken with CRLF read as LF, paths
    relative to the package's parent). None when there is no frozen pin to compare with.
    py_sha256 above covers every .py and so also catches a change to a module the conversion
    does not load; this answers the other question — is this the frozen converter at all."""
    m = read_json(manifest_path or ORACLE_MANIFEST)
    conv = (m or {}).get("converter") if m and "_unreadable" not in m else None
    if not isinstance(conv, dict) or not isinstance(conv.get("pin"), str) or not isinstance(conv.get("files"), dict):
        return None
    base, pairs = os.path.dirname(pkg), {}
    for rel in conv["files"]:
        try:
            with open(os.path.join(base, *rel.split("/")), "rb") as fh:
                pairs[rel] = hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()
        except OSError:
            pairs[rel] = "missing"
    pin = hashlib.sha256("".join(f"{k}\t{v}\n" for k, v in sorted(pairs.items())).encode("utf-8")).hexdigest()
    return {"frozen": conv["pin"], "current": pin, "ok": pin == conv["pin"],
            "differs": sorted(k for k, v in pairs.items() if v != conv["files"][k])}


def pins(full=False):
    out = {"converter": None, "oracle": {"path": os.path.relpath(ORACLE_MANIFEST, ROOT).replace(os.sep, "/"),
                                         "sha256": sha256_file(ORACLE_MANIFEST)}}
    pkg = converter_dir()
    if pkg:
        digest, n = converter_hash(pkg)
        conv = {"path": pkg, "py_sha256": digest, "files": n}
        if full:
            conv["frozen_pin"] = frozen_converter_pin(pkg)
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
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as e:
        raise SystemExit(f"{path}: cannot read the jobs file: {e}")
    if path.lower().endswith(".json"):
        try:
            items = json.loads(text)
        except ValueError as e:
            raise SystemExit(f"{path}: not JSON: {e}")
        items = items.get("jobs") if isinstance(items, dict) else items
    else:
        items = []
        for n, line in enumerate(text.splitlines(), 1):
            if line.strip() and not line.lstrip().startswith("#"):
                try:
                    items.append(json.loads(line))
                except ValueError as e:
                    raise SystemExit(f"{path} line {n}: not JSON: {e}")
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
KILL_VERDICT = {"timeout": "TIMEOUT", "stopped": "STOPPED", "halted": "HALTED", "launch-error": "LAUNCH_ERROR",
                "crashed": "CRASHED", "preempted": "PREEMPTED"}


# ---------------------------------------------------------------- the supervisor

class Running:
    def __init__(self, **kw):
        self.suspended_at, self.suspended_s, self.suspends = None, 0.0, 0
        self.lock_pinned_since = None                  # past the limit but left running: it holds the commit lock
        self.orphans, self.killed_as = 0, None
        self.__dict__.update(kw)


class Crashed(Exception):
    pass


class Supervisor:
    def __init__(self, run, rdir, jobs, opts, base_pins, log_is_stdout=False):
        self.run, self.rdir, self.jobs, self.opts = run, rdir, jobs, opts
        self.base = pin_key(base_pins)
        self.ledger = os.path.join(rdir, "ledger.jsonl")
        self.events = os.path.join(rdir, "events.jsonl")
        self.hb_path = os.path.join(rdir, "heartbeat.json")
        self.log_path, self.log_is_stdout = os.path.join(rdir, "supervisor.log"), log_is_stdout
        self.running, self.last, self.attempts = [], {}, {}
        for r in read_jsonl(self.ledger):
            if r.get("kind") == "job":
                self.last[r["job"]] = r
                self.attempts[r["job"]] = self.attempts.get(r["job"], 0) + 1
        self.queue = [j for j in jobs if not self.finished(j["id"])]
        self.skipped = len(jobs) - len(self.queue)
        self.state, self.stop_since, self.stop_src, self.halt, self.crash = "running", None, None, None, None
        self.paused, self.disk_t, self.free = False, 0.0, None
        self.slot_t, self.preempt_t, self.hb_t, self.hb_state, self.started = 0.0, 0.0, 0.0, None, time.time()
        self.unreleased = []                           # slots whose release failed; retried every step
        self.trouble = None                            # while a step keeps failing: since, tries, error
        self.quiesce_blocked = None                    # while a freeze cannot take the rails mutexes: since

    def finished(self, jid):
        """Whether a resume skips this job (its latest row finished, and --retry does not name it)."""
        r = self.last.get(jid)
        if not r or r.get("outcome") not in FINISHED_OUTCOMES:
            return False
        if r["outcome"] == "exit":
            return not (r.get("exit_code") != 0 and "nonzero" in self.opts.retry)
        return r["outcome"] not in self.opts.retry

    def done(self, jid):
        return (self.last.get(jid) or {}).get("outcome") in FINISHED_OUTCOMES

    def event(self, event, **kw):
        append_jsonl(self.events, {"t": now_iso(), "event": event, "run": self.run, "pid": os.getpid(), **kw})
        print(f"{now_iso()} {event} {json.dumps(kw, ensure_ascii=False) if kw else ''}", flush=True)

    def event_safe(self, event, **kw):
        # for the retry and crash paths, which must not die on their own log line
        try:
            self.event(event, **kw)
        except Exception as e:  # noqa: BLE001
            with contextlib.suppress(Exception):
                print(f"{now_iso()} {event} (events.jsonl not written: {type(e).__name__}: {e})", flush=True)

    def log_text(self, text):
        """Into supervisor.log whether or not this supervisor is detached (a detached one's stdout
        already is that log)."""
        with contextlib.suppress(Exception):
            print(text, flush=True)
        if not self.log_is_stdout:
            with contextlib.suppress(OSError):
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(text if text.endswith("\n") else text + "\n")

    def heartbeat(self, force=False):
        now = time.time()
        if not force and self.state == self.hb_state and now - self.hb_t < HEARTBEAT_EVERY_S:
            return
        verdicts = {}
        done = 0
        for j in self.jobs:
            if self.done(j["id"]):
                done += 1
                v = self.last[j["id"]].get("verdict")
                verdicts[v] = verdicts.get(v, 0) + 1
        limit, hits = slot_limit()
        live = [rec for _, rec in live_slots()]
        write_json(self.hb_path, {
            "run": self.run, "pid": os.getpid(), "created": proc_created(os.getpid()), "host": socket.gethostname(),
            "state": self.state, "updated": now_iso(now), "updated_ts": now, "started": now_iso(self.started),
            "total": len(self.jobs), "completed": done, "queued": len(self.queue), "skipped_at_start": self.skipped,
            "running": [{"job": r.job["id"], "pid": r.proc.pid, "since": now_iso(r.start), "start_ts": r.start,
                         "slot": bool(r.slot), "suspended": r.suspended_at is not None,
                         "suspended_s": round(r.suspended_s + (now - r.suspended_at if r.suspended_at else 0.0), 1),
                         "lock_pinned": r.lock_pinned_since is not None}
                        for r in self.running],
            "verdicts": verdicts, "last": max(self.last.values(), key=lambda r: r.get("end", ""), default=None),
            "slots": {"used": len(live), "suspended": sum(1 for s in live if s.get("suspended")),
                      "limit": limit, "gaming": hits},
            "free_gb": self.free, "stop": self.stop_src, "halt": self.halt, "grace_s": self.opts.grace,
            "crash": self.crash, "trouble": self.trouble,
        })
        self.hb_t, self.hb_state = now, self.state

    def heartbeat_safe(self):
        try:
            self.heartbeat(force=True)
        except Exception as e:  # noqa: BLE001
            with contextlib.suppress(Exception):
                print(f"{now_iso()} heartbeat not written: {type(e).__name__}: {e}", flush=True)

    # ------------------------------------------------ slots

    def release_slot(self, slot):
        try:
            slot.release()
        except OSError as e:
            self.unreleased.append(slot)
            self.event_safe("slot-release-deferred", slot=os.path.basename(slot.path), error=f"{type(e).__name__}: {e}")

    def retry_releases(self):
        for slot in list(self.unreleased):
            slot.release()                             # still failing: a transient error for main()
            self.unreleased.remove(slot)

    # ------------------------------------------------ jobs

    def dequeue(self, job):
        if self.queue and self.queue[0] is job:
            self.queue.pop(0)
        else:
            self.queue.remove(job)

    def launch(self, job, slot):
        """Start one job. Once its child exists it is tracked and off the queue before anything
        else can fail; an error before that gives the slot back and leaves the job queued."""
        jid = job["id"]
        logf = None
        try:
            cmd = expand(job, self.run, self.rdir)
            cwd = os.path.join(ROOT, job["cwd"]) if job.get("cwd") else ROOT
            log = os.path.join(self.rdir, "logs", log_name(jid))
            os.makedirs(os.path.dirname(log), exist_ok=True)
            logf = open(log, "ab")
            attempt = self.attempts.get(jid, 0) + 1
            shown = cmd if isinstance(cmd, str) else subprocess.list2cmdline(cmd)
            logf.write(f"\n===== {now_iso()} attempt {attempt} of {jid}: {shown}\n".encode("utf-8"))
            logf.flush()
            offset = logf.tell()
            env = child_env(job, self.run, self.rdir, slot, self.opts.threads)
        except BaseException:
            if logf:
                with contextlib.suppress(OSError):
                    logf.close()
            if slot:
                self.release_slot(slot)
            raise
        self.attempts[jid] = attempt
        start = time.time()
        try:
            # created suspended, and resumed only once it is in its job object: the venv's python.exe
            # is a launcher, and started at once it could start the real interpreter before the
            # assignment, outside the job (unfreezable, unreaped, uncounted)
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                    creationflags=(BELOW_NORMAL | CREATE_NO_WINDOW | CREATE_SUSPENDED) if IS_WIN else 0)
        except OSError as e:
            with contextlib.suppress(OSError):
                logf.write(f"launch failed: {e}\n".encode("utf-8"))
            with contextlib.suppress(OSError):
                logf.close()
            r = Running(job=job, proc=None, pjob=None, slot=slot, start=start, attempt=attempt,
                        log=log, offset=offset, logf=None, assigned=False)
            try:
                self.record(r, "launch-error", None)
            except BaseException:                      # the row was not written: the job stays queued
                if slot:
                    self.release_slot(slot)
                raise
            self.dequeue(job)
            return
        r = Running(job=job, proc=proc, pjob=None, slot=slot, start=start, attempt=attempt, log=log, offset=offset,
                    logf=logf, assigned=False, deadline=start + float(job.get("timeout") or self.opts.timeout))
        self.dequeue(job)
        self.running.append(r)
        if IS_WIN:
            status = None
            try:
                r.pjob = ProcJob()
                r.assigned = r.pjob.assign(proc)
            finally:
                status = resume_created(proc)          # whatever happened above, never leave it suspended
            if status != 0:
                self.event_safe("launch-unresumed", job=jid, pid=proc.pid, ntstatus=f"0x{status & 0xFFFFFFFF:08X}")
                self.kill(r, "launch-error")
                return
        if slot:
            try:
                slot.set_child(proc.pid)
            except OSError as e:
                self.event_safe("slot-child-unrecorded", job=jid, error=f"{type(e).__name__}: {e}")

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
        """Write the job's ledger row, then let go of it. Raises only when the row itself could not
        be written, and then the job is still tracked and is recorded again on the next step."""
        end = time.time()
        if r.pjob:
            n = r.pjob.active()
            if n:
                r.pjob.terminate()                     # a grandchild outliving its job would decode unslotted
                r.orphans += n
            r.pjob.close()
        if r.logf:
            with contextlib.suppress(OSError):
                r.logf.close()
            r.logf = None
        frozen_s = r.suspended_s + (end - r.suspended_at if r.suspended_at is not None else 0.0)
        row = {"kind": "job", "run": self.run, "job": r.job["id"], "attempt": r.attempt,
               "start": now_iso(r.start), "end": now_iso(end), "duration_s": round(end - r.start, 3),
               "exit_code": rc, "outcome": outcome, "verdict": self.verdict(r, outcome, rc),
               "slot": bool(r.slot), "pid": r.proc.pid if r.proc else None,
               "log": os.path.relpath(r.log, self.rdir).replace(os.sep, "/"),
               "orphans_killed": r.orphans, "job_object": r.assigned,
               "suspended_s": round(frozen_s, 3), "suspends": r.suspends}
        append_jsonl(self.ledger, row)             # durable before the slot is given back
        if r in self.running:
            self.running.remove(r)
        self.last[r.job["id"]] = row
        if outcome == "preempted":
            self.queue.insert(0, r.job)                # it runs again as soon as the pool allows
        if r.slot:
            self.release_slot(r.slot)
        with contextlib.suppress(*TRANSIENT):
            self.heartbeat(force=True)                 # otherwise the next step writes it

    def kill(self, r, outcome):
        r.killed_as = outcome                          # kept if the row fails to write, so a retry says why
        kill_tree(r.proc, r.pjob)
        self.record(r, outcome, r.proc.returncode)

    # ------------------------------------------------ the limit binds running jobs

    def preempt(self, now):
        """Freeze this supervisor's jobs that rank past the slot limit, thaw the ones back inside it.
        The rank is machine-wide: live slots ordered by when they were taken, the in-process ones
        (which cannot be frozen) first; so every supervisor reaches the same answer on its own."""
        mine = [r for r in self.running if r.slot and not r.killed_as]
        if not mine or now - self.preempt_t < PREEMPT_EVERY_S:
            return
        self.preempt_t = now
        limit, hits = slot_limit()
        live = [rec for _, rec in live_slots()]
        fixed = [rec for rec in live if not rec.get("suspendable")]
        movable = sorted((rec for rec in live if rec.get("suspendable")),
                         key=lambda rec: (rec.get("since_ts") or 0.0, str(rec.get("token"))))
        allowed = {rec.get("token") for rec in movable[:max(0, limit - len(fixed))]}
        known = {rec.get("token") for rec in live}
        why = {"limit": limit, "gaming": hits, "slots_live": len(live)}
        fresh, stragglers = [], []
        for r in mine:
            token = r.slot.rec.get("token")
            if token not in known:                     # our own slot file is unreadable: never freeze on that
                continue
            if token in allowed:
                if r.suspended_at is not None:
                    self.thaw(r, now, why)
                r.lock_pinned_since = None             # back inside the limit
            elif r.suspended_at is None:
                fresh.append(r)
            elif r.pjob.unfrozen():
                stragglers.append(r)                   # a process the job was starting as it was being frozen
        if fresh or stragglers:
            self.freeze(fresh, stragglers, now, why)

    def freeze(self, fresh, stragglers, now, why):
        """Freeze the jobs in `fresh`, and catch what the frozen `stragglers` were starting as they
        froze. It all happens holding every rails mutex (rails_quiesced), so no process is frozen
        inside one, and a job whose processes hold the commit lock is left running until it lets
        go: frozen, it would hold every loop's commits and gate-failure reverts for as long as the
        game runs. The pool runs one past its limit for the length of that commit."""
        for r in [r for r in fresh if not (r.pjob and r.assigned)]:
            self.event("preempted", job=r.job["id"], reason="no job object to freeze its tree in: killed, and queued again", **why)
            self.kill(r, "preempted")
            fresh.remove(r)
        if not fresh and not stragglers:
            return
        froze, pinned, loose = [], [], []
        try:
            with rails_quiesced():                     # nothing in here may call rails_event()
                holders = commit_lock_pids()
                for r in fresh:
                    if holders & set(r.pjob.pids()):
                        pinned.append(r)
                    else:
                        froze.append((r, r.pjob.suspend()))
                for r in stragglers:
                    if holders & set(r.pjob.pids()):
                        loose.append(r)                # a process it was starting took the lock: it must run
                    else:
                        r.pjob.suspend()
        except TimeoutError as e:                      # a mutex stayed held: freeze nothing now, try next round
            if self.quiesce_blocked is None:
                self.quiesce_blocked = now
                self.event("freeze-deferred", jobs=[r.job["id"] for r in fresh + stragglers],
                           reason=f"a rails mutex stayed held: {e}", **why)
            return
        t = time.time()
        if self.quiesce_blocked is not None:
            self.event("freeze-unblocked", after_s=round(t - self.quiesce_blocked, 1))
            self.quiesce_blocked = None
        for r, n in froze:
            pinned_s = t - r.lock_pinned_since if r.lock_pinned_since is not None else None
            r.lock_pinned_since = None
            r.suspended_at, r.suspends = t, r.suspends + 1
            r.slot.rec["suspended"] = now_iso(t)
            with contextlib.suppress(OSError):
                write_json(r.slot.path, r.slot.rec)
            extra = {"lock_pinned_s": round(pinned_s, 1)} if pinned_s is not None else {}
            self.event("suspended", job=r.job["id"], processes=n, **extra, **why)
        for r in loose:
            self.thaw(r, t, dict(why, reason="took the commit lock as it was being frozen"))
        for r in pinned + loose:
            if r.lock_pinned_since is None:
                r.lock_pinned_since = t
                self.event("freeze-deferred", job=r.job["id"],
                           reason="it holds the commit lock: it runs past the limit until it lets go", **why)
        self.hb_t = 0.0                                # the heartbeat says so at the end of this step

    def thaw(self, r, now, why):
        n = r.pjob.resume()
        frozen_for = now - r.suspended_at
        r.deadline += frozen_for                       # time spent frozen is not the job's to answer for
        r.suspended_s += frozen_for
        r.suspended_at = None
        r.slot.rec.pop("suspended", None)
        with contextlib.suppress(OSError):
            write_json(r.slot.path, r.slot.rec)
        self.hb_t = 0.0
        self.event("resumed", job=r.job["id"], processes=n, frozen_s=round(frozen_for, 1), **why)

    # ------------------------------------------------ the loop

    def step(self):
        now = time.time()
        self.retry_releases()
        for r in list(self.running):
            if r.killed_as:                            # killed, but its row was not written
                self.record(r, r.killed_as, r.proc.returncode)
                continue
            rc = r.proc.poll()
            if rc is not None:
                self.record(r, "exit", rc)
            elif r.suspended_at is None and now > r.deadline:
                self.event("timeout", job=r.job["id"], after_s=round(now - r.start, 1), frozen_s=round(r.suspended_s, 1))
                self.kill(r, "timeout")

        self.preempt(now)

        src = stop_reason(self.run)
        if src and self.stop_since is None:
            self.stop_since, self.stop_src = now, src
            self.event("stop-seen", source=src, running=[r.job["id"] for r in self.running],
                       queued=len(self.queue), grace_s=self.opts.grace)
        if self.stop_since is not None:
            for r in [r for r in self.running if r.suspended_at is not None]:
                self.event("stop-kills-frozen", job=r.job["id"])   # frozen, it could not finish in the grace
                self.kill(r, "stopped")
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
                    job, slot = self.queue[0], None
                    if job.get("slot", True):
                        if time.time() - self.slot_t < SLOT_RETRY_S:
                            waiting = True
                            break
                        slot = try_acquire_slot(self.run, job["id"], suspendable=True)
                        if slot is None:
                            self.slot_t, waiting = time.time(), True
                            break
                    try:
                        drift = pin_key(pins())            # re-checked before every launch
                    except BaseException:
                        if slot:
                            self.release_slot(slot)
                        raise
                    if drift != self.base:
                        if slot:
                            self.release_slot(slot)
                        self.halt = {"expected": self.base, "found": drift}
                        self.event("halt", reason="converter or oracle manifest changed mid-run", **self.halt)
                        break
                    self.launch(job, slot)
        if self.halt is not None:
            for r in list(self.running):
                self.kill(r, "halted")

        frozen = [r for r in self.running if r.suspended_at is not None]
        self.state = ("halted" if self.halt is not None else "stopping" if self.stop_since is not None
                      else "suspended" if self.running and len(frozen) == len(self.running)
                      else "paused-disk" if self.paused else "waiting-slot" if waiting and not self.running
                      else "running")
        self.heartbeat()
        return bool(self.running) or (bool(self.queue) and self.stop_since is None and self.halt is None)

    def nap(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_since is None and stop_reason(self.run):
                return                                 # the next step handles the STOP at once
            time.sleep(min(POLL_S, max(0.0, end - time.time())))

    def transient(self, e):
        """One step failed with an OSError or a subprocess timeout: log it and back off, unless it
        has persisted past --transient-budget, which makes it a crash."""
        now = time.time()
        t = self.trouble = self.trouble or {"since": now_iso(now), "since_ts": now, "tries": 0}
        t["tries"] += 1
        t["error"] = f"{type(e).__name__}: {e}"
        persisted = now - t["since_ts"]
        self.event_safe("transient-error", error=t["error"], tries=t["tries"], for_s=round(persisted, 1),
                        traceback=traceback.format_exc())
        if persisted >= self.opts.transient_budget:
            raise Crashed(f"a supervisor error persisted {persisted:.0f}s, past --transient-budget "
                          f"{self.opts.transient_budget:g}s: {t['error']}") from e
        self.state = "retrying"
        self.heartbeat_safe()
        self.nap(min(RETRY_BASE_S * 2 ** min(t["tries"] - 1, 16), RETRY_MAX_S))

    def crashed(self, e):
        tb = traceback.format_exc()
        self.crash = {"at": now_iso(), "error": f"{type(e).__name__}: {e}"}
        self.event_safe("crash", error=self.crash["error"], traceback=tb, killing=[r.job["id"] for r in self.running])
        self.log_text(f"{now_iso()} CRASHED; the run ends here and its unfinished jobs run again on resume.\n{tb}")
        for r in list(self.running):
            try:
                self.kill(r, "crashed")
            except Exception:  # noqa: BLE001 - the process exits next, and the job object takes the tree
                with contextlib.suppress(Exception):
                    if r.pjob:
                        r.pjob.terminate()
                with contextlib.suppress(Exception):
                    if r.slot:
                        r.slot.release()
        for slot in list(self.unreleased):
            with contextlib.suppress(Exception):
                slot.release()

    def main(self):
        awake = keep_awake(True)
        self.event("start", jobs=len(self.jobs), queued=len(self.queue), skipped=self.skipped,
                   parallel=self.opts.parallel, keep_awake=awake)
        code = 0
        try:
            while True:
                try:
                    more = self.step()
                except TRANSIENT as e:
                    self.transient(e)
                    continue
                if self.trouble:
                    self.event("recovered", after_s=round(time.time() - self.trouble["since_ts"], 1),
                               tries=self.trouble["tries"], error=self.trouble["error"])
                    self.trouble = None
                if not more:
                    break
                time.sleep(POLL_S)
        except KeyboardInterrupt:
            self.event_safe("interrupted", killing=[r.job["id"] for r in self.running])
            for r in list(self.running):
                with contextlib.suppress(Exception):
                    self.kill(r, "stopped")
            self.stop_since = self.stop_since or time.time()
            self.stop_src = self.stop_src or "keyboard interrupt"
        except Exception as e:  # noqa: BLE001 - a crash is recorded as one, never as "finished"
            self.crashed(e)
        finally:
            keep_awake(False)
            complete = not self.queue and not self.running and all(self.done(j["id"]) for j in self.jobs)
            if self.crash is not None:
                self.state, code = "crashed", EXIT_CRASHED
            elif self.halt is not None:
                self.state, code = "halted", EXIT_HALTED
            elif self.stop_since is not None and not complete:
                self.state, code = "stopped", EXIT_STOPPED
            elif complete:
                self.state = "finished"
            else:                                      # not reachable by construction; never call it finished
                self.crash = {"at": now_iso(), "error": f"the loop ended with {len(self.queue)} queued and "
                                                        f"{len(self.running)} running jobs"}
                self.state, code = "crashed", EXIT_CRASHED
            self.heartbeat_safe()
            self.event_safe("end", state=self.state, remaining=len(self.queue), code=code)
        return code


# ---------------------------------------------------------------- commands

def cmd_run(args):
    run = args.run
    if not RUN_ID.match(run):
        raise SystemExit(f"run id {run!r}: letters, digits, '.', '_' and '-' only")
    args.retry = {k.strip() for k in (args.retry or "").split(",") if k.strip()}
    if args.retry - RETRY_KINDS:
        raise SystemExit(f"--retry takes {sorted(RETRY_KINDS)}")
    if args.transient_budget < 0:
        raise SystemExit("--transient-budget is seconds, 0 or more")
    floor = free_floor(args.min_free_gb)
    if floor != args.min_free_gb:
        print(f"--min-free-gb {args.min_free_gb:g} raised to {floor:g}: the free-space floor is never below "
              f"{MIN_FREE_GB} GiB", file=sys.stderr)
    args.min_free_gb = floor
    rdir = os.path.join(RUNS, run)
    src = stop_reason(run)
    if src:
        raise SystemExit(f"refusing to start {run}: {src} is present. Clear it with "
                         f"`supervise.py stop {'' if 'global' in src else run} --clear` when you mean to.")
    pkg = converter_dir()
    fz = frozen_converter_pin(pkg) if pkg else None
    if fz and not fz["ok"] and not args.converter_unpinned:
        raise SystemExit(f"refusing to start {run}: the converter at {pkg} is not the one frozen in "
                         f"{os.path.relpath(ORACLE_MANIFEST, ROOT)} (pin {fz['frozen'][:12]}, found {fz['current'][:12]}; "
                         f"differs: {', '.join(fz['differs'])}). Loops run the frozen converter; --converter-unpinned "
                         "runs a deliberate candidate anyway and records that in the run manifest.")
    # the jobs file is read and checked before anything is created, so a bad one leaves no run folder
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
    os.makedirs(rdir, exist_ok=True)

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
            "converter_unpinned": bool(args.converter_unpinned),
            "options": {"timeout": args.timeout, "parallel": args.parallel, "grace": args.grace,
                        "threads": args.threads, "min_free_gb": args.min_free_gb, "retry": sorted(args.retry),
                        "transient_budget": args.transient_budget}})
        write_json(mpath, manifest)
        lower_own_priority()
        return Supervisor(run, rdir, jobs, args, cur, log_is_stdout=bool(args._detached)).main()
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
    for _ in range(240):                               # a cold venv launcher has taken 40 s to start
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
    total = manifest.get("jobs") or hb.get("total")
    if state in ACTIVE_STATES and not alive:
        state = f"DEAD (last {state})"
    elif state == "finished" and total is not None and done < total:
        state = f"INCOMPLETE (says finished, {done}/{total} have a finished row)"   # never read as complete
    age = round(time.time() - hb["updated_ts"]) if hb.get("updated_ts") else None
    return {"run": run, "state": state, "pid": hb.get("pid"), "alive": alive,
            "total": total, "completed": done, "verdicts": verdicts,
            "running": hb.get("running", []) if alive else [], "heartbeat_age_s": age,
            "updated": hb.get("updated"), "stop": stop_reason(run), "halt": hb.get("halt"),
            "crash": hb.get("crash"), "trouble": hb.get("trouble") if alive else None,
            "attempts": len(manifest.get("attempts", []))}


def cmd_status(args):
    runs = args.runs or (sorted(os.listdir(RUNS), key=lambda r: os.path.getmtime(os.path.join(RUNS, r)))
                         if os.path.isdir(RUNS) else [])
    summaries = [run_summary(r) for r in runs if os.path.isdir(os.path.join(RUNS, r))]
    limit, hits = slot_limit()
    slots = [rec for _, rec in live_slots()]
    machine = {"slots_used": len(slots), "slots_limit": limit, "gaming": hits,
               "slots": [{k: s.get(k) for k in ("pid", "child", "run", "job", "since", "suspended")} for s in slots],
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
        print(f"  slot: pid {s['pid']} child {s['child']} run {s['run']} job {s['job']} since {s['since']}"
              + (f"  FROZEN since {s['suspended']}" if s.get("suspended") else ""))
    for s in summaries:
        verd = ", ".join(f"{k} {v}" for k, v in sorted(s["verdicts"].items(), key=lambda kv: -kv[1]))
        print(f"\n{s['run']}: {s['state']}  {s['completed']}/{s['total']} done"
              + (f"  pid {s['pid']}" if s["alive"] else "")
              + (f"  heartbeat {s['heartbeat_age_s']}s ago" if s["heartbeat_age_s"] is not None else "")
              + (f"  attempts {s['attempts']}" if s["attempts"] > 1 else ""))
        if verd:
            print(f"  verdicts: {verd}")
        for r in s["running"]:
            print(f"  running: {r['job']} (pid {r['pid']}, since {r['since']})"
                  + (f"  FROZEN ({r.get('suspended_s')}s so far)" if r.get("suspended") else "")
                  + ("  past the limit: holds the commit lock" if r.get("lock_pinned") else ""))
        if s["stop"]:
            print(f"  {s['stop']}")
        if s["halt"]:
            print(f"  HALTED: {s['halt']}")
        if s["crash"]:
            print(f"  CRASHED {s['crash'].get('at')}: {s['crash'].get('error')} (traceback in events.jsonl and supervisor.log)")
        if s["trouble"]:
            print(f"  retrying since {s['trouble'].get('since')} ({s['trouble'].get('tries')} tries): {s['trouble'].get('error')}")
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
    if args.run:
        hb = read_json(os.path.join(RUNS, args.run, "heartbeat.json")) or {}
        grace = hb.get("grace_s")
        when = (f"{grace:g} s (its --grace)" if isinstance(grace, (int, float)) else "the run's --grace")
    else:
        when = f"each run's --grace (default {GRACE_S:g} s)"
    print(f"created {path}: no new job starts; jobs frozen for a game are killed now, and running jobs get "
          f"{when} before they are killed")
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
            cfg["min_free_gb"] = free_floor(args.min_free_gb)     # may raise the floor, never lower it
            if cfg["min_free_gb"] != args.min_free_gb:
                print(f"--min-free-gb {args.min_free_gb:g} raised to {cfg['min_free_gb']:g}: the floor is never "
                      f"below {MIN_FREE_GB} GiB", file=sys.stderr)
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
    lock = PidLock(COMMIT_LOCK, "commit lock")
    try:
        lock.acquire(timeout=args.timeout, run=args.run, purpose="lock-exec")
    except TimeoutError as e:
        print(f"lock-exec: {e}; nothing was run", file=sys.stderr)
        return 2
    try:
        with subprocess.Popen(cmd) as proc:
            try:
                # the child is named in the lock, so killing lock-exec alone (no /T) does not free
                # the lock while its command still runs
                lock.set_child(proc.pid)
            except OSError as e:
                print(f"lock-exec: the child could not be named in the lock ({e})", file=sys.stderr)
            try:
                return proc.wait()
            except BaseException:
                proc.kill()
                raise
    finally:
        lock.release()


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
    print(f"created {wt} on {branch} at {base.stdout.strip()[:10]}", flush=True)
    for sub in ("work", "videos"):
        link, target = os.path.join(wt, sub), os.path.join(main, sub)
        link_junction(link, target)
        print(f"  {sub}/ -> {target} (junction)", flush=True)
    if args.no_preflight:
        return 0
    own = os.path.join(wt, "tools", "supervise.py")
    if not os.path.exists(own):
        print(f"no preflight: {args.base} predates tools/supervise.py, so the new worktree has none to run")
        return 1
    return subprocess.call(PY + [own, "preflight"], cwd=wt)


def link_junction(link, target):
    r = quiet(["cmd", "/c", "mklink", "/J", link, target])
    if r.returncode != 0 or not same_dir(link, target):
        raise SystemExit(f"junction {link} -> {target} failed: {r.stdout}{r.stderr}")


def cmd_worktree_remove(args):
    main = main_checkout()
    wt = os.path.normpath(os.path.join(os.path.dirname(main), "psf-wt", args.name))
    if os.path.normcase(wt) not in worktrees() or same_dir(wt, main):
        raise SystemExit(f"{wt} is not a linked worktree of this repository")
    # Everything git worktree remove would refuse over is checked BEFORE a junction is touched:
    # a loop worktree left without its junctions would have its tools create a real, unshared work/.
    st = git("status", "--porcelain", "--untracked-files=all", cwd=wt)
    if st.returncode != 0:
        raise SystemExit(f"git status failed in {wt}; nothing was changed:\n{st.stderr}")
    if st.stdout.strip():
        raise SystemExit(f"{wt} has uncommitted or untracked files, which git worktree remove refuses; nothing was "
                         f"changed:\n{st.stdout.rstrip()}")
    for block in git("worktree", "list", "--porcelain", cwd=main).stdout.split("\n\n"):
        lines = block.splitlines()
        if lines and os.path.normcase(os.path.normpath(lines[0].split(" ", 1)[-1])) == os.path.normcase(wt) \
                and any(line == "locked" or line.startswith("locked ") for line in lines):
            raise SystemExit(f"{wt} is locked (git worktree unlock it first); nothing was changed")
    unlinked = []
    for sub in ("work", "videos"):
        link = os.path.join(wt, sub)
        if not os.path.lexists(link):
            continue
        if not os.path.isjunction(link):
            raise SystemExit(f"{link} is a real directory, not a junction: refusing to remove this worktree")
        target = os.path.join(main, sub)
        before = len(os.listdir(target))
        os.rmdir(link)                                 # removes the junction itself, never what it points at
        unlinked.append((link, target))
        after = len(os.listdir(target))
        if after != before:
            raise SystemExit(f"{target} changed from {before} to {after} entries while unlinking: stopping")
        print(f"unlinked {link} ({target} intact: {after} entries)")
    r = git("worktree", "remove", wt, cwd=main)
    if r.returncode != 0:
        for link, target in unlinked:                  # put the worktree back as it was
            link_junction(link, target)
            print(f"re-linked {link} -> {target}")
        raise SystemExit(f"git worktree remove failed; the worktree is left in place with its junctions:\n{r.stderr}")
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
    p.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB,
                   help=f"pause launches below this many GiB free on C: (raised to {MIN_FREE_GB} if lower)")
    p.add_argument("--retry", default="", help="re-run finished jobs of these kinds on resume: nonzero,timeout,launch-error")
    p.add_argument("--transient-budget", type=float, default=TRANSIENT_BUDGET_S,
                   help="seconds one supervisor OSError/subprocess timeout may keep recurring (retried with backoff) "
                        "before the run ends as crashed")
    p.add_argument("--detach", action="store_true", help="relaunch detached (outlives this terminal) and return")
    p.add_argument("--accept-pin-change", action="store_true", help="resume although the converter/oracle hash changed")
    p.add_argument("--converter-unpinned", action="store_true",
                   help="run although the converter is not the one frozen in sources/oracle-manifest.json (a deliberate "
                        "candidate converter); recorded in the run manifest")
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
