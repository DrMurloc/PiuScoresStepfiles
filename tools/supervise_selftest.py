# Drills for the loop rails (supervise.py, loopcommit.py, .githooks/pre-push), with toy jobs
# only: python sleeps and marks, no footage, no decoding, no real chart files.
#
#   supervise_selftest.py [--dir <scratch>] [--only name,name] [--list]
#
# Every drill runs against its own PSF_RAILS_STATE folder under --dir (default
# work/rails-selftest/<timestamp>), so the real slot pool, commit lock and runs are never
# touched, and the git drills use throwaway repositories under the same folder. Game detection
# is pointed at a name that is not running (or at python.exe, or at a renamed copy of ping.exe,
# for the gaming drills), so the result does not depend on whether the owner is playing. Takes a
# few minutes; prints PASS or FAIL per drill and exits with the number of failures. The folder
# is kept for inspection.
#
# Drills that need jobs to overlap do not rely on timing: their toy jobs wait at a barrier until
# the expected number have started (a cold venv launcher has taken 40 s to start one), so a slow
# machine cannot make a correct pool look wrong, while a pool that lets too many run is still
# caught, because the extra jobs start inside the same window.
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import supervise as S  # noqa: E402

ROOT, TOOLS = S.ROOT, S.TOOLS
SUP = os.path.join(TOOLS, "supervise.py")
LC = os.path.join(TOOLS, "loopcommit.py")
HOOK = os.path.join(ROOT, ".githooks", "pre-push")
PY = S.PY
FLAGS = (S.CREATE_NO_WINDOW | S.BELOW_NORMAL) if S.IS_WIN else 0
BARRIER_WAIT_S = 180

TOY = r'''
import json, os, subprocess, sys, time
mode, out = sys.argv[1], sys.argv[2]
jid = os.environ.get("PSF_JOB", "nojob")
safe = "".join(c if c.isalnum() else "_" for c in jid)
def mark(kind, **kw):
    p = os.path.join(out, f"{safe}.{os.getpid()}.{kind}.json")
    with open(p + ".tmp", "w") as fh:
        json.dump({"job": jid, "kind": kind, "t": time.time(), "pid": os.getpid(), **kw}, fh)
    os.replace(p + ".tmp", p)
GC = "import os,sys,time; open(sys.argv[1] + '.tmp','w').write(str(os.getpid())); os.replace(sys.argv[1] + '.tmp', sys.argv[1]); time.sleep(600)"
def grandchild(flags=0):
    f = os.path.join(out, f"{safe}.gc")
    subprocess.Popen([sys.executable, "-c", GC, f], creationflags=flags)
    for _ in range(400):
        if os.path.exists(f):
            try:
                return int(open(f).read())
            except (OSError, ValueError):     # a scanner can hold a file that was just renamed into place
                pass
        time.sleep(0.05)
def started():
    return sum(1 for f in os.listdir(out) if f.endswith(".start.json"))
if mode == "sleep":
    mark("start"); time.sleep(float(sys.argv[3])); mark("end")
elif mode == "hold":                  # start, wait until K jobs have started (or a cap), linger, end
    k, cap, linger = int(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
    mark("start")
    end = time.time() + cap
    while started() < k and time.time() < end:
        time.sleep(0.05)
    met = started() >= k
    time.sleep(linger)
    mark("end", barrier=met)
elif mode == "ticker":                # wait until K have started, then n ticks of dt s, each a new empty file
    n, dt, k, cap = int(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]), float(sys.argv[6])
    mark("start")
    end = time.time() + cap
    while started() < k and time.time() < end:
        time.sleep(0.05)
    for i in range(1, n + 1):
        time.sleep(dt)
        open(os.path.join(out, f"{safe}.tick.{i}"), "w").close()
    mark("end")
elif mode == "tree":
    mark("start", gc=grandchild()); time.sleep(600)
elif mode == "orphan":
    mark("start", gc=grandchild(0x00000200)); mark("end")      # exits at once; its grandchild keeps running
elif mode == "locked":
    mark("enter"); time.sleep(float(sys.argv[3])); mark("exit")
elif mode == "lockrun":               # meet K at a barrier, wait for a go file ('-': none), then hold the commit lock
    k, cap, go, lock_timeout, hold, sup = int(sys.argv[3]), float(sys.argv[4]), sys.argv[5], sys.argv[6], sys.argv[7], sys.argv[8]
    mark("start")
    end = time.time() + cap
    while started() < k and time.time() < end:
        time.sleep(0.05)
    while go != "-" and not os.path.exists(go) and time.time() < end:
        time.sleep(0.05)
    t0 = time.time()
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", sup, "lock-exec", "--timeout", lock_timeout, "--",
                        sys.executable, "-X", "utf8", "-B", __file__, "locked", out, hold])
    mark("end", rc=r.returncode, waited=time.time() - t0)
    print("VERDICT:", "LOCKED" if r.returncode == 0 else "LOCK_REFUSED", flush=True)
    sys.exit(r.returncode)
elif mode == "mutexspin":             # take and drop a rails mutex (40 ms held, 10 ms free) until a stop file exists
    tools, mutex, stop, cap = sys.argv[3], sys.argv[4], sys.argv[5], float(sys.argv[6])
    sys.path.insert(0, tools)
    import supervise as S
    mark("start")
    end, n = time.time() + cap, 0
    while not os.path.exists(stop) and time.time() < end:
        with S.FileMutex(mutex):
            time.sleep(0.04)
        n += 1
        time.sleep(0.01)
    mark("end", holds=n)
elif mode == "exitseq":               # exit with the n-th code of a comma list on the job's n-th attempt
    mark("start")
    n = sum(1 for f in os.listdir(out) if f.startswith(safe + ".") and f.endswith(".start.json")
            and f[len(safe) + 1:-len(".start.json")].isdigit())
    codes = [int(c) for c in sys.argv[3].split(",")]
    sys.exit(codes[min(n, len(codes)) - 1])
elif mode == "until":                 # start, then wait for a file (or a cap)
    stop, cap = sys.argv[3], float(sys.argv[4])
    mark("start")
    end = time.time() + cap
    while not os.path.exists(stop) and time.time() < end:
        time.sleep(0.05)
    mark("end")
'''

# Runs supervise.py with Supervisor.step replaced by one that raises a plain bug (not an OSError)
# once any job has been running a moment: a supervisor defect, planted without a hook in the tool.
BUG = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import supervise as S
real = S.Supervisor.step
def step(self):
    if any(time.time() - r.start > 0.5 for r in self.running):
        raise RuntimeError("bug planted by supervise_selftest")
    return real(self)
S.Supervisor.step = step
sys.exit(S.main(sys.argv[2:]))
'''

# Runs supervise.py with the job-object assignment delayed 0.5 s after each launch (a supervisor
# descheduled under load), and records every process each job's job object ever held.
LATE_ASSIGN = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
import supervise as S
record, seen = sys.argv[2], {}
real_assign = S.ProcJob.assign
def assign(self, proc):
    time.sleep(0.5)
    return real_assign(self, proc)
S.ProcJob.assign = assign
real_step = S.Supervisor.step
def step(self):
    for r in self.running:
        if r.pjob:
            seen.setdefault(r.job["id"], set()).update(r.pjob.pids())
    with open(record + ".tmp", "w") as fh:
        json.dump({k: sorted(v) for k, v in seen.items()}, fh)
    os.replace(record + ".tmp", record)
    return real_step(self)
S.Supervisor.step = step
sys.exit(S.main(sys.argv[3:]))
'''

# Runs loopcommit.py with a post-commit check that always finds a problem.
BADCHECK = r'''
import sys
sys.path.insert(0, sys.argv[1])
import loopcommit as L
real = L.verify_commit
def verify(top, old, expected, allowed=None):
    new, problems = real(top, old, expected, allowed)
    return new, problems + ["problem planted by supervise_selftest"]
L.verify_commit = verify
sys.exit(L.main(sys.argv[2:]))
'''

# Runs a copied supervise.py with `git worktree remove` failing after the pre-checks pass.
WTFAIL = r'''
import subprocess, sys
sys.path.insert(0, sys.argv[1])
import supervise as S
real = S.git
def git(*args, **kw):
    if args[:2] == ("worktree", "remove"):
        return subprocess.CompletedProcess(["git", *args], 1, "", "planted failure by supervise_selftest")
    return real(*args, **kw)
S.git = git
sys.exit(S.main(sys.argv[2:]))
'''


class Drill:
    def __init__(self, base, name):
        self.name = name
        self.base = base
        self.dir = os.path.join(base, name)
        self.state = os.path.join(self.dir, "state")
        self.out = os.path.join(self.dir, "marks")
        os.makedirs(self.out, exist_ok=True)
        os.makedirs(self.state, exist_ok=True)
        self.toy = os.path.join(base, "toy.py")
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PSF_RAILS_STATE=self.state,
                        PSF_GAME_EXES="no-such-game-for-selftest.exe")
        self.problems = []

    def expect(self, ok, what):
        if not ok:
            self.problems.append(what)
        return ok

    def jobs(self, name, specs):
        path = os.path.join(self.dir, f"{name}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for s in specs:
                fh.write(json.dumps(s) + "\n")
        return path

    def toyjob(self, jid, *args, **kw):
        return {"id": jid, "cmd": ["{py}", self.toy, args[0], self.out, *map(str, args[1:])], **kw}

    def sup(self, *args, env=None, wrapper=None):
        # wrapper: a script that imports supervise from TOOLS, plants a fault, and runs its main()
        cmd = PY + ([wrapper, TOOLS] if wrapper else [SUP]) + list(args)
        return subprocess.run(cmd, env=env or self.env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=FLAGS, timeout=600)

    def sup_bg(self, *args, env=None):
        log = open(os.path.join(self.dir, f"sup-{len(os.listdir(self.dir))}.log"), "w")
        return subprocess.Popen(PY + [SUP, *args], env=env or self.env, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=FLAGS)

    def script(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def marks(self, kind=None):
        rows = []
        for f in os.listdir(self.out):
            if f.endswith(".json"):
                path = os.path.join(self.out, f)
                r = S._retry(lambda: json.load(open(path)))    # a scanner can hold a just-renamed file
                if kind is None or r["kind"] == kind:
                    rows.append(r)
        return rows

    def ticks(self):
        best = {}
        for f in os.listdir(self.out):
            parts = f.split(".tick.")
            if len(parts) == 2 and parts[1].isdigit():
                best[parts[0]] = max(best.get(parts[0], 0), int(parts[1]))
        return best

    def run_dir(self, run):
        return os.path.join(self.state, "runs", run)

    def ledger(self, run):
        return [r for r in S.read_jsonl(os.path.join(self.run_dir(run), "ledger.jsonl")) if r.get("kind") == "job"]

    def events(self, run):
        return S.read_jsonl(os.path.join(self.run_dir(run), "events.jsonl"))

    def heartbeat(self, run):
        return S.read_json(os.path.join(self.run_dir(run), "heartbeat.json")) or {}


def wait_for(pred, timeout=60, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return pred()


def max_overlap(marks, start="start", end="end"):
    ev = []
    by = {}
    for m in marks:
        by.setdefault((m["job"], m["pid"]), {})[m["kind"]] = m["t"]
    for d in by.values():
        if start in d:
            ev.append((d[start], 1))
            ev.append((d.get(end, float("inf")), -1))
    ev.sort(key=lambda e: (e[0], e[1]))
    cur = best = 0
    for _, delta in ev:
        cur += delta
        best = max(best, cur)
    return best


def dead(pid):
    return not S.proc_alive(pid)


def kill_tree(pid):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, creationflags=FLAGS)


def slot_files(state):
    folder = os.path.join(state, ".slots")
    return [f for f in os.listdir(folder) if f.startswith("slot-")] if os.path.isdir(folder) else []


def barrier(d, limit, n, peak, what):
    """The shared verdict of the pool drills: never more than the limit; exactly the limit once the
    jobs have met at their barrier (if they never met, the machine was too slow to show it)."""
    met = [m.get("barrier") for m in d.marks("end")]
    d.expect(peak <= limit, f"{what}: peak {peak} > {limit}: the pool let too many run at once")
    d.expect(len(met) == n and all(met), f"{what}: inconclusive: the jobs did not all meet at their barrier "
                                         f"within {BARRIER_WAIT_S}s ({sum(map(bool, met))}/{len(met)} met)")
    d.expect(peak == limit, f"{what}: peak {peak}, expected exactly {limit}")


# ---------------------------------------------------------------- drills

def d_slot_limit(d):
    """8 queued jobs, --parallel 8: never more than 6 at once (and 6 when they wait for each other)."""
    path = d.jobs("j", [d.toyjob(f"s{i}", "hold", 6, BARRIER_WAIT_S, 1.0) for i in range(8)])
    r = d.sup("run", "slots8", "--jobs", path, "--parallel", "8")
    rows = d.ledger("slots8")
    peak = max_overlap(d.marks())
    d.expect(r.returncode == 0, f"supervisor exit {r.returncode}: {r.stdout[-400:]}")
    d.expect(len(rows) == 8 and all(x["verdict"] == "OK" for x in rows), f"ledger {[(x['job'], x['verdict']) for x in rows]}")
    barrier(d, 6, 8, peak, "one supervisor")
    return f"8 jobs, parallel 8, peak {peak} concurrent"


def d_slot_two_supervisors(d):
    """Two supervisors with 8 jobs each share one machine-wide pool of 6."""
    a = d.sup_bg("run", "pa", "--jobs", d.jobs("a", [d.toyjob(f"a{i}", "hold", 6, BARRIER_WAIT_S, 1.0) for i in range(8)]),
                 "--parallel", "8")
    b = d.sup_bg("run", "pb", "--jobs", d.jobs("b", [d.toyjob(f"b{i}", "hold", 6, BARRIER_WAIT_S, 1.0) for i in range(8)]),
                 "--parallel", "8")
    ra, rb = a.wait(600), b.wait(600)
    peak = max_overlap(d.marks())
    d.expect(ra == 0 and rb == 0, f"exit codes {ra}, {rb}")
    d.expect(len(d.ledger("pa")) == 8 and len(d.ledger("pb")) == 8, "not every job finished")
    barrier(d, 6, 16, peak, "two supervisors")
    return f"2 supervisors x 8 jobs, combined peak {peak}"


def d_slot_gaming(d):
    """While a listed game runs (python.exe stands in for Wow.exe), the pool drops to 2."""
    env = dict(d.env, PSF_GAME_EXES="python.exe")
    path = d.jobs("j", [d.toyjob(f"g{i}", "hold", 2, BARRIER_WAIT_S, 1.0) for i in range(5)])
    r = d.sup("run", "gaming", "--jobs", path, "--parallel", "6", env=env)
    peak = max_overlap(d.marks())
    d.expect(r.returncode == 0, f"exit {r.returncode}")
    barrier(d, 2, 5, peak, "gaming")
    d.expect((d.heartbeat("gaming").get("slots") or {}).get("gaming") == ["python.exe"], "heartbeat does not name the game")
    return f"gaming: peak {peak}"


def d_gaming_preempt(d):
    """The game starting mid-run freezes the 4 newest of 6 running jobs (exactly 2 keep running),
    thaws them oldest first, and time spent frozen does not count against a job's timeout."""
    game = os.path.join(d.dir, "psfselftestgame.exe")
    shutil.copy(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE"), game)
    env = dict(d.env, PSF_GAME_EXES="psfselftestgame.exe", PSF_GAME_POLL_S="1")
    # each job needs 16 s of running once all six have started; the last two spend ~32 s frozen, so
    # they outlive a 36 s timeout only if frozen time is (wrongly) counted against it
    timeout = 36
    p = d.sup_bg("run", "freeze", "--jobs", d.jobs("j", [d.toyjob(f"f{i}", "ticker", 64, 0.25, 6, BARRIER_WAIT_S,
                                                                  timeout=timeout) for i in range(6)]),
                 "--parallel", "6", env=env)
    ready = wait_for(lambda: len(d.ticks()) == 6 and all(v >= 2 for v in d.ticks().values()), BARRIER_WAIT_S)
    d.expect(ready, f"the six jobs never all ran before the game started: {d.ticks()}")
    g = subprocess.Popen([game, "-n", "90", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=FLAGS)

    def frozen():
        return [r["job"] for r in d.heartbeat("freeze").get("running", []) if r.get("suspended")]
    got = wait_for(lambda: len(frozen()) == 4, 30)
    hb = d.heartbeat("freeze")
    order = [r["job"] for r in sorted(hb.get("running", []), key=lambda r: r["start_ts"])]
    status = d.sup("status", "freeze", env=env).stdout
    advancing = []
    for _ in range(3):                             # three 1.5 s windows while the game runs
        a = d.ticks()
        time.sleep(1.5)
        b = d.ticks()
        advancing.append(sorted(j for j in b if b[j] > a.get(j, 0)))
    d.expect(got, f"4 jobs were not frozen within 30 s of the game starting: frozen {frozen()}")
    d.expect(sorted(frozen()) == sorted(order[2:]), f"frozen {frozen()}, expected the four newest {order[2:]}")
    d.expect(all(len(w) <= 2 for w in advancing), f"more than 2 jobs made progress while gaming: {advancing}")
    d.expect(advancing and advancing[0] == sorted(order[:2]), f"progressing {advancing}, expected the two oldest {order[:2]}")
    d.expect("FROZEN" in status, f"status does not show the frozen jobs:\n{status}")
    rc = p.wait(240)
    g.kill()
    g.wait(30)
    rows = {x["job"]: x for x in d.ledger("freeze")}
    ev = [e["event"] for e in d.events("freeze")]
    d.expect(rc == 0 and len(rows) == 6 and all(x["outcome"] == "exit" and x["verdict"] == "OK" for x in rows.values()),
             f"exit {rc}; rows {[(x['job'], x['outcome'], x['verdict']) for x in rows.values()]}")
    last = [rows.get(j, {}) for j in order[4:]]
    d.expect(all(x.get("duration_s", 0) > timeout and x.get("suspended_s", 0) > 10 for x in last),
             f"the last two did not outlive their {timeout}s timeout on frozen time: "
             f"{[(x.get('job'), x.get('duration_s'), x.get('suspended_s')) for x in last]}")
    d.expect(all(rows.get(j, {}).get("suspended_s") == 0 for j in order[:2]), "the two oldest were frozen")
    d.expect(ev.count("suspended") == 4 and ev.count("resumed") == 4, f"events {ev}")
    return (f"frozen {len(frozen() or order[2:])} newest, 2 oldest kept running; the last two ran "
            f"{[x.get('duration_s') for x in last]}s wall ({[x.get('suspended_s') for x in last]}s frozen) under a {timeout}s timeout")


def d_preempt_stop(d):
    """Lowering `slots --max` mid-run freezes jobs too; a STOP kills frozen jobs at once and gives
    only the running one its grace."""
    cfg = os.path.join(d.state, ".slots", "config.json")
    p = d.sup_bg("run", "pstop", "--jobs", d.jobs("j", [d.toyjob(f"p{i}", "ticker", 400, 0.25, 3, BARRIER_WAIT_S)
                                                        for i in range(3)]), "--parallel", "3", "--grace", "4")
    ready = wait_for(lambda: len(d.ticks()) == 3 and all(v >= 2 for v in d.ticks().values()), BARRIER_WAIT_S)
    d.expect(ready, "the three jobs never all ran")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w") as fh:
        json.dump({"max": 1}, fh)
    got = wait_for(lambda: sum(1 for r in d.heartbeat("pstop").get("running", []) if r.get("suspended")) == 2, 30)
    d.expect(got, "lowering max to 1 did not freeze 2 of 3 running jobs")
    pids = [m["pid"] for m in d.marks("start")]
    t_stop = time.time()
    d.sup("stop", "pstop")
    rc = p.wait(120)
    rows = d.ledger("pstop")
    ev = d.events("pstop")
    names = [e["event"] for e in ev]
    killed_frozen = [e for e in ev if e["event"] == "stop-kills-frozen"]
    d.expect(rc == 3, f"exit {rc}, expected 3 (stopped)")
    d.expect(len(rows) == 3 and all(x["outcome"] == "stopped" for x in rows), f"rows {[(x['job'], x['outcome']) for x in rows]}")
    d.expect(len(killed_frozen) == 2 and "grace-expired" in names
             and names.index("grace-expired") > max(names.index("stop-kills-frozen"), 0),
             f"events {names}")
    d.expect(wait_for(lambda: all(dead(pid) for pid in pids), 20), "a job outlived the STOP")
    os.remove(cfg)
    return f"max 1 froze 2 of 3; STOP killed both frozen at once, the running one after its grace ({time.time() - t_stop:.1f}s)"


def set_max(d, value):
    """Lower (or with None restore) the pool's limit, as `slots --max` does and a game starting does."""
    cfg = os.path.join(d.state, ".slots", "config.json")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    if value is None:
        if os.path.exists(cfg):
            S._retry(lambda: os.remove(cfg))           # a supervisor reading it holds it open for a moment
    else:
        S.write_json(cfg, {"max": value})


def running_row(d, run, job):
    return next((r for r in d.heartbeat(run).get("running", []) if r["job"] == job), None)


def d_freeze_lock_holder(d):
    """A job holding the commit lock when the limit drops is not frozen until it lets go (the pool
    runs one past its limit meanwhile), so the oldest job still gets the lock and commits: a frozen
    holder would refuse every loop's commits and reverts for as long as the game runs."""
    go = os.path.join(d.dir, "go")
    hold = 12
    specs = [d.toyjob("p0", "lockrun", 3, BARRIER_WAIT_S, go, 45, 0.3, SUP),          # oldest: commits later
             d.toyjob("p1", "hold", 3, BARRIER_WAIT_S, 15),                           # frozen
             d.toyjob("p2", "lockrun", 3, BARRIER_WAIT_S, "-", 30, hold, SUP)]        # newest: holds the lock
    p = d.sup_bg("run", "lockfreeze", "--jobs", d.jobs("j", specs), "--parallel", "3")
    entered = wait_for(lambda: [m for m in d.marks("enter") if m["job"] == "p2"], BARRIER_WAIT_S)
    d.expect(entered, "p2 never took the commit lock")
    set_max(d, 1)

    def settled():
        p1, p2 = running_row(d, "lockfreeze", "p1"), running_row(d, "lockfreeze", "p2")
        return p1 and p2 and p1.get("suspended") and p2.get("lock_pinned") and not p2.get("suspended")
    pinned = wait_for(settled, 20)
    status = d.sup("status", "lockfreeze").stdout
    open(go, "w").close()
    rc = p.wait(240)
    set_max(d, None)
    rows = {x["job"]: x for x in d.ledger("lockfreeze")}
    marks = {(m["job"], m["kind"]): m for m in d.marks()}
    held_for = (marks.get(("p2", "exit"), {}).get("t", 0) - marks.get(("p2", "enter"), {}).get("t", 0))
    ev = d.events("lockfreeze")
    deferred = [e for e in ev if e["event"] == "freeze-deferred" and e.get("job") == "p2"]
    d.expect(pinned, f"with the limit at 1, p1 was not frozen while p2 (holding the lock) kept running: "
                     f"{d.heartbeat('lockfreeze').get('running')}")
    d.expect("holds the commit lock" in status, f"status does not say why p2 runs past the limit:\n{status}")
    d.expect(rc == 0 and len(rows) == 3, f"exit {rc}, rows {sorted(rows)}")
    d.expect(rows.get("p0", {}).get("verdict") == "LOCKED" and rows.get("p2", {}).get("verdict") == "LOCKED",
             f"verdicts {[(j, x.get('verdict')) for j, x in rows.items()]}: a job lost its commit to a frozen lock holder")
    d.expect(0 < held_for < hold + 4, f"p2 held the lock {held_for:.1f}s for a {hold}s hold: it was frozen holding it")
    d.expect(deferred and "commit lock" in deferred[0].get("reason", ""), f"no freeze-deferred event for p2: {[e['event'] for e in ev]}")
    d.expect(rows.get("p1", {}).get("suspended_s", 0) > 0 and rows.get("p0", {}).get("suspended_s") == 0,
             f"frozen time {[(j, x.get('suspended_s')) for j, x in rows.items()]}")
    return (f"limit 1: p1 frozen, p2 left running while it held the lock ({held_for:.1f}s for a {hold}s hold), "
            f"p0 then took it in {marks.get(('p0', 'end'), {}).get('waited', 0):.1f}s: LOCKED")


def d_freeze_mutex(d):
    """A job is never frozen inside a rails mutex: the supervisor holds them all while it freezes.
    The newest job takes and drops the commit lock's mutex (held 80% of the time); it is frozen and
    thawed ten times, and after each freeze the mutex must be free at once."""
    stop = os.path.join(d.dir, "stop")
    mutex = os.path.join(d.state, ".commit.lock.mutex")
    specs = [d.toyjob("old", "until", stop, BARRIER_WAIT_S + 120),
             d.toyjob("spin", "mutexspin", TOOLS, mutex, stop, BARRIER_WAIT_S + 120)]
    p = d.sup_bg("run", "mutexfreeze", "--jobs", d.jobs("j", specs), "--parallel", "2")
    d.expect(wait_for(lambda: len(d.marks("start")) == 2, BARRIER_WAIT_S), "the two jobs never both started")
    time.sleep(1.0)
    results = []
    for _ in range(10):
        set_max(d, 1)
        frozen = wait_for(lambda: (running_row(d, "mutexfreeze", "spin") or {}).get("suspended"), 15)
        if not frozen:
            results.append("not frozen")
            break
        t0 = time.time()
        try:
            with S.FileMutex(mutex, timeout=3):
                results.append(round(time.time() - t0, 2))
        except TimeoutError:
            results.append("HELD")
        set_max(d, None)
        wait_for(lambda: not (running_row(d, "mutexfreeze", "spin") or {}).get("suspended"), 15)
        time.sleep(0.3)
    open(stop, "w").close()
    rc = p.wait(120)
    holds = [m.get("holds", 0) for m in d.marks("end") if m["job"] == "spin"]
    d.expect(len(results) == 10 and all(isinstance(x, float) for x in results),
             f"after a freeze the mutex was not free at once: {results} (HELD = the frozen job was inside it)")
    d.expect(rc == 0 and holds and holds[0] > 50, f"exit {rc}; the spinning job took the mutex {holds} times")
    return f"10 freezes of a job holding the mutex 80% of the time; free after each in {results} s"


def d_frozen_lock_wait(d):
    """A job frozen while it waits for the commit lock is not refused the moment it thaws: a lock
    wait counts only the time its process was awake (frozen 16 s, then 2 s more, under a 10 s --timeout)."""
    go, release = os.path.join(d.dir, "go"), os.path.join(d.dir, "release")
    lock = os.path.join(d.state, ".commit.lock")
    p = d.sup_bg("run", "lockwait", "--jobs", d.jobs("j", [d.toyjob("w", "lockrun", 1, BARRIER_WAIT_S, go, 10, 0.2, SUP)]))
    d.expect(wait_for(lambda: d.marks("start"), BARRIER_WAIT_S), "the job never started")
    holder = subprocess.Popen(PY + [SUP, "lock-exec", "--run", "holder", "--", *PY, "-c",
                                    f"import os,time; [time.sleep(0.05) for _ in iter(lambda: os.path.exists({release!r}), True)]"],
                              env=d.env, creationflags=FLAGS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    d.expect(wait_for(lambda: (S.read_json(lock) or {}).get("child"), 60), "the outside holder never took the lock")
    open(go, "w").close()
    log = os.path.join(d.run_dir("lockwait"), "logs", S.log_name("w"))
    waiting = wait_for(lambda: os.path.exists(log) and "waiting for the commit lock" in open(log, encoding="utf-8", errors="replace").read(),
                       BARRIER_WAIT_S)
    d.expect(waiting, "the job never started waiting for the lock")
    set_max(d, 0)
    frozen = wait_for(lambda: (running_row(d, "lockwait", "w") or {}).get("suspended"), 15)
    d.expect(frozen, "the waiting job was not frozen")
    time.sleep(16)
    set_max(d, None)
    thawed = wait_for(lambda: not (running_row(d, "lockwait", "w") or {}).get("suspended"), 15)
    time.sleep(2)
    open(release, "w").close()
    rc = p.wait(120)
    holder.wait(60)
    rows = d.ledger("lockwait")
    end = [m for m in d.marks("end") if m["job"] == "w"]
    d.expect(thawed, "the job was not thawed")
    d.expect(rc == 0 and rows and rows[0]["verdict"] == "LOCKED",
             f"exit {rc}, verdict {rows[0]['verdict'] if rows else None}: the thawed job was refused the lock "
             "for time it spent frozen")
    waited = end[0].get("waited", 0) if end else 0
    d.expect(waited > 17, f"the job waited only {waited:.1f}s of wall time: the drill did not freeze it past its timeout")
    return f"frozen past its 10 s lock timeout, waited {waited:.1f}s of wall time, then took the lock: LOCKED"


def d_late_assign(d):
    """Children start suspended and run only once they are in their job object: with the assignment
    delayed 0.5 s (a supervisor descheduled under load), the real interpreter the venv launcher
    starts is still inside the job."""
    late = d.script("late.py", LATE_ASSIGN)
    record = os.path.join(d.dir, "jobpids.json")
    # the toys wait for each other and linger 3 s: the launch step itself takes seconds (four delayed
    # assignments), and a toy that ended before the first snapshot after it would show an empty job
    path = d.jobs("j", [d.toyjob(f"a{i}", "hold", 4, BARRIER_WAIT_S, 3.0) for i in range(4)])
    r = d.sup(record, "run", "late", "--jobs", path, "--parallel", "4", wrapper=late)
    seen = json.load(open(record)) if os.path.exists(record) else {}
    starts = {m["job"]: m["pid"] for m in d.marks("start")}
    rows = d.ledger("late")
    outside = sorted(j for j, pid in starts.items() if pid not in seen.get(j, []))
    d.expect(r.returncode == 0 and len(rows) == 4 and all(x["verdict"] == "OK" and x["job_object"] for x in rows),
             f"exit {r.returncode}; rows {[(x['job'], x['verdict'], x['job_object']) for x in rows]}: {r.stdout[-300:]}")
    d.expect(len(starts) == 4 and not outside, f"the real interpreter ran outside its job object in {outside} "
                                              f"(interpreters {starts}, job objects held {seen})")
    return f"4 launches with a 0.5 s late assignment: every interpreter inside its job ({sum(map(len, seen.values()))} processes seen)"


def d_jobs_bom(d):
    """A jobs file PowerShell wrote (a byte-order mark, CRLF lines) runs, as does a BOM'd .json list
    and a BOM'd slots config."""
    bom = "﻿"
    jl = os.path.join(d.dir, "bom.jsonl")
    with open(jl, "w", encoding="utf-8", newline="") as fh:
        fh.write(bom + "".join(json.dumps(d.toyjob(f"b{i}", "sleep", 0.1)) + "\r\n" for i in range(2)))
    js = os.path.join(d.dir, "bom.json")
    with open(js, "w", encoding="utf-8", newline="") as fh:
        fh.write(bom + json.dumps([d.toyjob("c0", "sleep", 0.1)]) + "\r\n")
    r1 = d.sup("run", "bomjsonl", "--jobs", jl)
    r2 = d.sup("run", "bomjson", "--jobs", js)
    cfg = os.path.join(d.state, ".slots", "config.json")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w", encoding="utf-8", newline="") as fh:
        fh.write(bom + '{"max": 1}\r\n')
    slots = d.sup("slots")
    os.remove(cfg)
    d.expect(r1.returncode == 0 and len(d.ledger("bomjsonl")) == 2, f"BOM jsonl: exit {r1.returncode} {r1.stderr[-300:]}")
    d.expect(r2.returncode == 0 and len(d.ledger("bomjson")) == 1, f"BOM json: exit {r2.returncode} {r2.stderr[-300:]}")
    d.expect(slots.stdout.startswith("0/1 "), f"a BOM'd slots config was not honored: {slots.stdout[:200]}")
    return "BOM + CRLF jsonl, BOM .json list and BOM slots config all read"


def d_stop_run(d):
    """A run STOP is honored within one job: the running job finishes, nothing else starts."""
    path = d.jobs("j", [d.toyjob(f"t{i}", "sleep", 2.0) for i in range(6)])
    p = d.sup_bg("run", "stopme", "--jobs", path, "--parallel", "1")
    wait_for(lambda: d.marks("start"), BARRIER_WAIT_S)
    d.sup("stop", "stopme", "--reason", "selftest")
    rc = p.wait(120)
    rows = d.ledger("stopme")
    starts = d.marks("start")
    d.expect(rc == 3, f"exit {rc}, expected 3 (stopped)")
    d.expect(len(starts) == 1 and len(rows) == 1 and rows[0]["outcome"] == "exit", f"{len(starts)} started, ledger {rows}")
    d.expect(d.heartbeat("stopme").get("state") == "stopped", f"heartbeat {d.heartbeat('stopme').get('state')}")
    refused = d.sup("run", "stopme")
    d.expect(refused.returncode == 1 and "STOP" in (refused.stderr + refused.stdout),
             f"a run with STOP present: exit {refused.returncode} (documented: 1, refused to start)")
    d.sup("stop", "stopme", "--clear")
    # the global STOP, on a second run
    p = d.sup_bg("run", "stopall", "--jobs", d.jobs("k", [d.toyjob(f"u{i}", "sleep", 2.0) for i in range(4)]), "--parallel", "1")
    wait_for(lambda: len(d.marks("start")) >= 2, BARRIER_WAIT_S)
    d.sup("stop")
    rc2 = p.wait(120)
    rows2 = d.ledger("stopall")
    d.expect(rc2 == 3 and len(rows2) == 1, f"global STOP: exit {rc2}, {len(rows2)} finished")
    d.sup("stop", "--clear")
    return f"run STOP: {len(rows)} of 6 ran; global STOP: {len(rows2)} of 4 ran"


def d_stop_grace_kill(d):
    """After the grace period, STOP kills the running job and its grandchild (taskkill /T + job object)."""
    path = d.jobs("j", [d.toyjob("long", "tree")])
    t0 = time.time()
    p = d.sup_bg("run", "grace", "--jobs", path, "--grace", "2")
    m = wait_for(lambda: d.marks("start"), BARRIER_WAIT_S)
    d.sup("stop", "grace")
    rc = p.wait(120)
    rows = d.ledger("grace")
    if not d.expect(m, f"the toy never started its grandchild; ledger {rows}"):
        return "no start mark"
    gc, child = m[0]["gc"], m[0]["pid"]
    d.expect(rc == 3, f"exit {rc}")
    d.expect(rows and rows[0]["outcome"] == "stopped" and rows[0]["verdict"] == "STOPPED", f"ledger {rows}")
    d.expect(wait_for(lambda: dead(child) and dead(gc), 20), f"child {child} or grandchild {gc} survived")
    return f"killed after grace, {time.time() - t0:.1f}s total; child and grandchild dead"


def d_timeout(d):
    """A job past its timeout is killed with its grandchild; a job that exits leaving an orphan has it reaped."""
    path = d.jobs("j", [d.toyjob("hang", "tree", timeout=10), d.toyjob("orphaner", "orphan")])
    r = d.sup("run", "timeouts", "--jobs", path, "--parallel", "2")
    rows = {x["job"]: x for x in d.ledger("timeouts")}
    starts = {x["job"]: x for x in d.marks("start")}
    d.expect(r.returncode == 0, f"exit {r.returncode}")
    hang, orph = rows.get("hang", {}), rows.get("orphaner", {})
    d.expect(hang.get("outcome") == "timeout" and 10 <= hang.get("duration_s", 0) < 40, f"hang row {hang}")
    d.expect(orph.get("outcome") == "exit" and orph.get("orphans_killed", 0) >= 1, f"orphan row {orph}")
    if d.expect("hang" in starts and "orphaner" in starts, f"a toy never started before its timeout: {sorted(starts)}"):
        d.expect(wait_for(lambda: dead(starts["hang"]["pid"]) and dead(starts["hang"]["gc"]), 20), "timed-out tree survived")
        d.expect(wait_for(lambda: dead(starts["orphaner"]["gc"]), 20), "the orphaned grandchild survived")
    return f"timeout killed after {hang.get('duration_s')}s; {orph.get('orphans_killed')} orphan(s) reaped"


def d_resume(d):
    """Kill -9 a supervisor mid-run; re-running the run id skips every finished job."""
    path = d.jobs("j", [d.toyjob(f"r{i}", "sleep", 1.0) for i in range(5)])
    p = d.sup_bg("run", "resume", "--jobs", path, "--parallel", "1")
    wait_for(lambda: len(d.ledger("resume")) >= 2 and len(d.marks("start")) >= 3, BARRIER_WAIT_S)
    kill_tree(p.pid)
    p.wait(30)
    finished_before = {x["job"] for x in d.ledger("resume")}
    status = d.sup("status", "resume")
    d.expect("DEAD" in status.stdout, f"status did not call the killed supervisor dead:\n{status.stdout}")
    r = d.sup("run", "resume")
    rows = d.ledger("resume")
    per_job = {}
    for x in rows:
        per_job[x["job"]] = per_job.get(x["job"], 0) + 1
    starts = {}
    for m in d.marks("start"):
        starts[m["job"]] = starts.get(m["job"], 0) + 1
    d.expect(r.returncode == 0, f"resume exit {r.returncode}: {r.stdout[-300:]}")
    d.expect(sorted(per_job) == [f"r{i}" for i in range(5)] and all(v == 1 for v in per_job.values()),
             f"ledger rows per job {per_job}")
    d.expect(all(starts.get(j) == 1 for j in finished_before), f"a finished job ran again: {starts}")
    again = d.sup("run", "resume")
    d.expect(again.returncode == 0 and len(d.ledger("resume")) == 5, "a third run re-ran something")
    other = d.jobs("other", [d.toyjob("zz", "sleep", 0.1)])
    diff = d.sup("run", "resume", "--jobs", other)
    d.expect(diff.returncode != 0 and "different job list" in diff.stderr, "a changed job list was accepted")
    return f"{len(finished_before)} finished before the kill were skipped; in-flight job re-ran; 5 rows, one each"


def d_retry_later(d):
    """An exit code a job calls "later" (retry_exit, and 75 by default for tools/corpus_grade.py and
    tools/loopcommit.py) is a deferral, not a result: queued again after retry_after, up to
    retry_limit, then final. The grade's 2 (a refusal waiting does not fix) is final at once."""
    grade = os.path.join(d.dir, "corpus_grade.py")      # toys under the tools' names: the default rule
    shutil.copyfile(d.toy, grade)
    lcommit = os.path.join(d.dir, "loopcommit.py")
    shutil.copyfile(d.toy, lcommit)
    specs = [d.toyjob("later-ok", "exitseq", "2,2,0", retry_exit=[2], retry_after=1),
             {"id": "grade-later", "cmd": ["{py}", grade, "exitseq", d.out, "75,1"], "retry_after": 1},
             {"id": "grade-refuses", "cmd": ["{py}", grade, "exitseq", d.out, "2,0"], "retry_after": 1},
             {"id": "pass-later", "cmd": ["{py}", lcommit, "exitseq", d.out, "75,0"], "retry_after": 1},
             d.toyjob("exhausted", "exitseq", "2,2,2,2", retry_exit=[2], retry_after=0.5, retry_limit=2),
             d.toyjob("plain-fail", "exitseq", "2")]
    path = d.jobs("j", specs)
    r = d.sup("run", "later", "--jobs", path, "--parallel", "2")
    rows = {}
    for x in d.ledger("later"):
        rows.setdefault(x["job"], []).append(x)
    seq = {j: [(x["outcome"], x["exit_code"], x["verdict"]) for x in v] for j, v in rows.items()}
    d.expect(r.returncode == 0, f"exit {r.returncode}: {r.stdout[-300:]}{r.stderr[-300:]}")
    d.expect(seq.get("later-ok") == [("deferred", 2, "RETRY_LATER"), ("deferred", 2, "RETRY_LATER"), ("exit", 0, "OK")],
             f"later-ok: {seq.get('later-ok')}")
    d.expect(seq.get("grade-later") == [("deferred", 75, "RETRY_LATER"), ("exit", 1, "FAIL")],
             f"a corpus_grade.py exit 75 was not deferred by default: {seq.get('grade-later')}")
    d.expect(seq.get("grade-refuses") == [("exit", 2, "FAIL")],
             f"a corpus_grade.py exit 2 (a refusal) was deferred instead of final: {seq.get('grade-refuses')}")
    d.expect(seq.get("pass-later") == [("deferred", 75, "RETRY_LATER"), ("exit", 0, "OK")],
             f"a loopcommit.py exit 75 was not deferred by default: {seq.get('pass-later')}")
    d.expect(seq.get("exhausted") == [("deferred", 2, "RETRY_LATER"), ("deferred", 2, "RETRY_LATER"), ("exit", 2, "RETRY_EXHAUSTED")],
             f"exhausted: {seq.get('exhausted')}")
    d.expect(seq.get("plain-fail") == [("exit", 2, "FAIL")], f"a plain exit 2 was deferred: {seq.get('plain-fail')}")
    ts = sorted(m["t"] for m in d.marks("start") if m["job"] == "later-ok")
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    d.expect(len(gaps) == 2 and min(gaps) >= 0.95, f"relaunched sooner than retry_after 1 s: gaps {gaps}")
    again = d.sup("run", "later")
    d.expect(again.returncode == 0 and len(d.ledger("later")) == sum(len(v) for v in rows.values()),
             "a resume re-ran a finished job")
    bad = d.jobs("bad", [d.toyjob("x", "sleep", 0.1, retry_exit=[0])])
    rb = d.sup("run", "badjobs", "--jobs", bad)
    d.expect(rb.returncode != 0 and "retry_exit" in rb.stderr, "retry_exit [0] was accepted")
    return ("deferred 2,2 then OK; corpus_grade.py's and loopcommit.py's 75 deferred by default, the grade's 2 final "
            "at once; exhausted after 2; a plain 2 is FAIL")


def d_crash(d):
    """A supervisor error is never 'finished': a transient one is retried and the run completes; one
    that persists past --transient-budget, or a plain bug, ends the run as crashed (exit 5), its
    running jobs killed and unfinished, no slot leaked, and a resume finishes the work."""
    # 1. transient: logs/ is a file, so every launch fails with an OSError until it is removed
    os.makedirs(d.run_dir("tc"), exist_ok=True)
    blocker = os.path.join(d.run_dir("tc"), "logs")
    open(blocker, "w").close()
    p = d.sup_bg("run", "tc", "--jobs", d.jobs("tc", [d.toyjob(f"c{i}", "sleep", 0.3) for i in range(2)]),
                 "--transient-budget", "300")
    seen = wait_for(lambda: "transient-error" in [e["event"] for e in d.events("tc")], BARRIER_WAIT_S)
    retrying = wait_for(lambda: d.heartbeat("tc").get("state") == "retrying", 30)
    shown = d.sup("status", "tc").stdout
    os.remove(blocker)
    rc = p.wait(180)
    ev = [e["event"] for e in d.events("tc")]
    d.expect(seen and retrying, f"no transient-error / retrying state: events {ev}, heartbeat {d.heartbeat('tc').get('state')}")
    d.expect("retrying since" in shown, f"status did not show the retry:\n{shown}")
    d.expect(rc == 0 and d.heartbeat("tc").get("state") == "finished" and len(d.ledger("tc")) == 2 and "recovered" in ev,
             f"transient: exit {rc}, state {d.heartbeat('tc').get('state')}, {len(d.ledger('tc'))} rows, events {ev}")
    # 2. the same error past the budget: crashed, never finished, and no slot left behind
    os.makedirs(d.run_dir("tp"), exist_ok=True)
    open(os.path.join(d.run_dir("tp"), "logs"), "w").close()
    r = d.sup("run", "tp", "--jobs", d.jobs("tp", [d.toyjob(f"q{i}", "sleep", 0.3) for i in range(3)]),
              "--transient-budget", "4")
    st = d.sup("status", "tp").stdout
    hb = d.heartbeat("tp")
    crash_ev = [e for e in d.events("tp") if e["event"] == "crash"]
    log = open(os.path.join(d.run_dir("tp"), "supervisor.log"), encoding="utf-8").read() \
        if os.path.exists(os.path.join(d.run_dir("tp"), "supervisor.log")) else ""
    d.expect(r.returncode == 5, f"persistent: exit {r.returncode}, expected 5 (crashed)")
    d.expect(hb.get("state") == "crashed" and "crashed" in st and "finished" not in st,
             f"persistent: heartbeat {hb.get('state')}, status:\n{st}")
    d.expect(crash_ev and "Traceback" in crash_ev[0].get("traceback", "") and "CRASHED" in log and "Traceback" in log,
             "the traceback is not in events.jsonl and supervisor.log")
    d.expect(not slot_files(d.state), f"slot files left behind: {slot_files(d.state)}")
    # 3. a plain bug with jobs running: they are killed, recorded 'crashed', and run again on resume
    bug = d.script("bug.py", BUG)
    path = d.jobs("tb", [d.toyjob(f"b{i}", "sleep", 2.0) for i in range(2)])
    r = d.sup("run", "tb", "--jobs", path, "--parallel", "2", wrapper=bug)
    rows = d.ledger("tb")
    pids = [x["pid"] for x in rows]
    d.expect(r.returncode == 5 and d.heartbeat("tb").get("state") == "crashed", f"bug: exit {r.returncode}, "
             f"state {d.heartbeat('tb').get('state')}: {r.stdout[-300:]}")
    d.expect(len(rows) == 2 and all(x["outcome"] == "crashed" and x["verdict"] == "CRASHED" for x in rows),
             f"bug: rows {[(x['job'], x['outcome']) for x in rows]}")
    d.expect(wait_for(lambda: all(dead(pid) for pid in pids), 20), "a job outlived the crash")
    again = d.sup("run", "tb")
    rows = d.ledger("tb")
    d.expect(again.returncode == 0 and d.heartbeat("tb").get("state") == "finished"
             and sorted(x["outcome"] for x in rows) == ["crashed", "crashed", "exit", "exit"],
             f"resume after the crash: exit {again.returncode}, rows {[(x['job'], x['outcome']) for x in rows]}")
    return "transient error retried then finished; persistent one crashed at its budget (exit 5, no slot left); a bug crashed with its jobs killed, and the resume finished them"


def d_commit_lock(d):
    """Two supervisors whose jobs all take the commit lock: the holds never overlap."""
    def spec(prefix):
        return [{"id": f"{prefix}{i}", "slot": False,
                 "cmd": ["{py}", SUP, "lock-exec", "--run", "{run}", "--", "{py}", d.toy, "locked", d.out, "0.4"]}
                for i in range(4)]
    a = d.sup_bg("run", "la", "--jobs", d.jobs("a", spec("a")), "--parallel", "4")
    b = d.sup_bg("run", "lb", "--jobs", d.jobs("b", spec("b")), "--parallel", "4")
    ra, rb = a.wait(300), b.wait(300)
    marks = d.marks()
    peak = max_overlap(marks, "enter", "exit")
    holds = len([m for m in marks if m["kind"] == "exit"])
    waited = sum("waiting for the commit lock" in open(os.path.join(d.run_dir(r), "logs", f)).read()
                 for r in ("la", "lb") for f in os.listdir(os.path.join(d.run_dir(r), "logs")))
    d.expect(ra == 0 and rb == 0, f"exit codes {ra}, {rb}")
    d.expect(holds == 8, f"{holds} of 8 lock holds completed")
    d.expect(peak == 1, f"{peak} holders at once")
    d.expect(waited >= 4, f"only {waited} jobs ever waited: the drill did not contend")
    return f"8 holds from 2 supervisors, max 1 at a time, {waited} waited"


def d_stale_lock(d):
    """A lock or slot whose holder was killed is recovered by the next acquirer; a lock-exec killed
    alone keeps the lock while the command it started still runs."""
    holder = subprocess.Popen(PY + [SUP, "lock-exec", "--run", "victim", "--", *PY, "-c", "import time; time.sleep(600)"],
                              env=d.env, creationflags=FLAGS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lock = os.path.join(d.state, ".commit.lock")
    rec = wait_for(lambda: S.read_json(lock), 60)
    kill_tree(holder.pid)
    holder.wait(30)
    t0 = time.time()
    got = d.sup("lock-exec", "--timeout", "30", "--", *PY, "-c", "print('acquired')")
    took = time.time() - t0
    events = S.read_jsonl(os.path.join(d.state, "rails-events.jsonl"))
    d.expect(got.returncode == 0 and "acquired" in got.stdout, f"lock-exec after the kill: {got.returncode} {got.stderr[-300:]}")
    d.expect(any(e["event"] == "stale-lock-recovered" and e["holder"].get("pid") == rec["pid"] for e in events),
             "no stale-lock-recovered event naming the killed holder")
    d.expect(not os.path.exists(lock), "the lock file was not released")
    # a 0-byte lock (a crash between create and write) is recovered too
    open(lock, "w").close()
    got2 = d.sup("lock-exec", "--timeout", "30", "--", *PY, "-c", "print('acquired')")
    d.expect(got2.returncode == 0, "a 0-byte lock file wedged the lock")
    # lock-exec killed without its tree: the child it started is named in the lock and holds it
    holder = subprocess.Popen(PY + [SUP, "lock-exec", "--run", "victim2", "--", *PY, "-c", "import time; time.sleep(600)"],
                              env=d.env, creationflags=FLAGS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rec = wait_for(lambda: (S.read_json(lock) or {}).get("child") and S.read_json(lock), 60)
    if d.expect(rec, "lock-exec never named its child in the lock"):
        subprocess.run(["taskkill", "/F", "/PID", str(rec["pid"])], capture_output=True, creationflags=FLAGS)
        d.expect(wait_for(lambda: dead(rec["pid"]), 20), "lock-exec did not die")
        blocked = d.sup("lock-exec", "--timeout", "3", "--", *PY, "-c", "print('acquired')")
        d.expect(blocked.returncode == 2 and "acquired" not in blocked.stdout and "nothing was run" in blocked.stderr,
                 f"the lock was handed on while lock-exec's child still ran: {blocked.returncode} {blocked.stdout}{blocked.stderr}")
        kill_tree(rec["child"])
        got3 = d.sup("lock-exec", "--timeout", "30", "--", *PY, "-c", "print('acquired')")
        d.expect(got3.returncode == 0 and "acquired" in got3.stdout, "the lock was not recovered once the child died")
    holder.wait(30)
    # a slot whose supervisor dies: kill only the supervisor process (no /T); the job object's
    # kill-on-close must take its child down, and the next acquirer recovers the slot
    p = d.sup_bg("run", "slotvictim", "--jobs", d.jobs("j", [d.toyjob("held", "sleep", 600)]))
    m = wait_for(lambda: d.marks("start"), BARRIER_WAIT_S)
    hb = wait_for(lambda: d.heartbeat("slotvictim").get("pid"), 60)
    subprocess.run(["taskkill", "/F", "/PID", str(hb)], capture_output=True, creationflags=FLAGS)
    p.wait(30)
    d.expect(wait_for(lambda: dead(m[0]["pid"]), 20), "the job outlived its killed supervisor")
    slots = d.sup("slots")
    events = S.read_jsonl(os.path.join(d.state, "rails-events.jsonl"))
    d.expect(slots.stdout.startswith("0/"), f"slot not recovered: {slots.stdout}")
    d.expect(any(e["event"] == "stale-slot-recovered" for e in events), "no stale-slot-recovered event")
    return (f"commit lock recovered {took:.1f}s after its holder was killed; 0-byte lock recovered; a lock-exec killed "
            "alone kept the lock until its child died; slot recovered")


def d_disk_pause(d):
    """Below the free-space floor the run pauses (does not fail) and resumes when there is room;
    the floor can be raised but never lowered below 40 GiB."""
    os.makedirs(os.path.join(d.state, ".slots"), exist_ok=True)
    cfg = os.path.join(d.state, ".slots", "config.json")
    with open(cfg, "w") as fh:
        json.dump({"min_free_gb": 10 ** 9}, fh)
    p = d.sup_bg("run", "disk", "--jobs", d.jobs("j", [d.toyjob(f"d{i}", "sleep", 0.5) for i in range(2)]),
                 "--min-free-gb", "1")
    paused = wait_for(lambda: d.heartbeat("disk").get("state") == "paused-disk", BARRIER_WAIT_S)
    time.sleep(2)
    d.expect(paused and not d.marks(), "did not pause, or launched while paused")
    with open(cfg, "w") as fh:
        json.dump({}, fh)                          # back to the run's own floor, which --min-free-gb 1 could not lower
    rc = p.wait(120)
    free = S.free_gb()
    d.expect(rc == 0 and len(d.ledger("disk")) == 2,
             f"did not resume and finish (exit {rc}; {free} GiB free, and resuming needs 40)")
    ev = [e["event"] for e in d.events("disk")]
    d.expect("paused-disk" in ev and "resumed-disk" in ev, f"events {ev}")
    manifest = S.read_json(os.path.join(d.run_dir("disk"), "manifest.json")) or {}
    floor = manifest.get("attempts", [{}])[-1].get("options", {}).get("min_free_gb")
    d.expect(floor == 40, f"--min-free-gb 1 ran with floor {floor}, expected 40")
    off = d.sup("slots", "--min-free-gb", "0")
    d.expect((S.read_json(cfg) or {}).get("min_free_gb") == 40 and "raised" in off.stderr,
             f"`slots --min-free-gb 0` stored {S.read_json(cfg)}: {off.stderr}")
    return f"paused at a raised floor, resumed at 40 GiB ({free} free); --min-free-gb 1 and slots --min-free-gb 0 both held at 40"


def d_pin_drift(d):
    """A converter source change mid-run halts the run; resuming refuses the changed pin; the
    frozen-pin comparison matches corpus_grade's definition."""
    conv = os.path.join(d.dir, "conv")
    shutil.copytree(os.path.join(S.CONVERTER_REPO, "piu_annotate"), os.path.join(conv, "piu_annotate"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    env = dict(d.env, PSF_CONVERTER_REPO=conv)
    path = d.jobs("j", [d.toyjob(f"p{i}", "sleep", 3.0) for i in range(4)])
    p = d.sup_bg("run", "drift", "--jobs", path, "--parallel", "1", env=env)
    wait_for(lambda: d.marks("start"), BARRIER_WAIT_S)
    with open(os.path.join(conv, "piu_annotate", "formats", "ssc_to_chartstruct.py"), "a") as fh:
        fh.write("\n# drift planted by supervise_selftest\n")
    rc = p.wait(120)
    rows = d.ledger("drift")
    d.expect(rc == 4, f"exit {rc}, expected 4 (halted)")
    d.expect(d.heartbeat("drift").get("state") == "halted", "heartbeat not halted")
    d.expect(len(rows) <= 1, f"{len(rows)} jobs recorded after the drift")
    r = d.sup("run", "drift", env=env)
    # refused twice over now that sources/oracle-manifest.json freezes a pin: the drifted copy is not
    # the frozen converter, and (past that, with --converter-unpinned) not the one the run began with
    d.expect(r.returncode != 0 and "not the one frozen" in r.stderr, f"resume accepted a converter off the frozen pin: {r.stderr[-300:]}")
    r = d.sup("run", "drift", "--converter-unpinned", env=env)
    d.expect(r.returncode != 0 and "changed since this run began" in r.stderr, "resume accepted a changed converter")
    # the frozen pin, computed here independently the way corpus_grade.converter_pin does it
    import hashlib
    pkg = os.path.join(S.CONVERTER_REPO, "piu_annotate")
    rels = ["piu_annotate/__init__.py", "piu_annotate/utils.py", "piu_annotate/formats/__init__.py",
            "piu_annotate/formats/notelines.py", "piu_annotate/formats/sscfile.py", "piu_annotate/formats/ssc_to_chartstruct.py"]
    files = {r: hashlib.sha256(open(os.path.join(S.CONVERTER_REPO, *r.split("/")), "rb").read().replace(b"\r\n", b"\n")).hexdigest()
             for r in rels}
    pin = hashlib.sha256("".join("%s\t%s\n" % kv for kv in sorted(files.items())).encode("utf-8")).hexdigest()
    manifest = os.path.join(d.dir, "oracle-manifest.json")
    with open(manifest, "w") as fh:
        json.dump({"converter": {"pin": pin, "files": files}}, fh)
    good = S.frozen_converter_pin(pkg, manifest)
    files["piu_annotate/utils.py"] = "0" * 64
    with open(manifest, "w") as fh:
        json.dump({"converter": {"pin": pin, "files": files}}, fh)
    bad = S.frozen_converter_pin(os.path.join(conv, "piu_annotate"), manifest)
    d.expect(good and good["ok"], f"the real converter did not match its own frozen pin: {good}")
    # the manifest is committed now: its absence, or a manifest with no pin, is a failure, not a pass
    missing = S.frozen_converter_pin(pkg, os.path.join(d.dir, "no-such-manifest.json"))
    d.expect(not missing["ok"] and "missing" in (missing.get("why") or ""), f"a missing manifest passed: {missing}")
    pinless = os.path.join(d.dir, "pinless-manifest.json")
    with open(pinless, "w") as fh:
        json.dump({"oracle": {}}, fh)
    nopin = S.frozen_converter_pin(pkg, pinless)
    d.expect(not nopin["ok"] and "no converter pin" in (nopin.get("why") or ""), f"a pinless manifest passed: {nopin}")
    d.expect(bad and not bad["ok"] and bad["differs"] == ["piu_annotate/formats/ssc_to_chartstruct.py", "piu_annotate/utils.py"],
             f"the drifted copy was not caught by the frozen pin: {bad}")
    return f"halted with {len(rows)} job recorded; resume refused the new pin; frozen pin matched, and caught the drift"


def d_detach(d):
    """--detach returns before the run is done, and the run finishes without the process that started it."""
    path = d.jobs("j", [d.toyjob(f"x{i}", "sleep", 3.0) for i in range(3)])
    t0 = time.time()
    r = d.sup("run", "bg", "--jobs", path, "--detach", "--parallel", "1")
    returned = time.time() - t0
    rows_at_return = len(d.ledger("bg"))
    d.expect(r.returncode == 0, f"detach failed: {r.stdout}{r.stderr}")
    d.expect(rows_at_return < 3, f"--detach returned only after the run was done ({rows_at_return} rows)")
    hb = wait_for(lambda: d.heartbeat("bg").get("pid") and d.heartbeat("bg"), BARRIER_WAIT_S)
    d.expect(hb, "no heartbeat from the detached supervisor")
    done = wait_for(lambda: d.heartbeat("bg").get("state") == "finished", BARRIER_WAIT_S)
    d.expect(done and len(d.ledger("bg")) == 3, "the detached run did not finish")
    log_path = os.path.join(d.run_dir("bg"), "supervisor.log")
    # the heartbeat says finished a moment before the end line is written: wait for it, do not race it
    logged = wait_for(lambda: (lambda t: " start " in t and " end " in t)(open(log_path, encoding="utf-8").read()), 30)
    d.expect(logged, "the detached supervisor did not log its start and end")
    return f"returned in {returned:.1f}s with {rows_at_return}/3 done; detached pid {(hb or {}).get('pid')} finished 3 jobs"


def git(repo, *args, check=True):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=FLAGS)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def new_repo(path, branch="loops/test"):
    os.makedirs(path)
    git(path, "init", "-q", "-b", branch)
    git(path, "config", "user.email", "selftest@example.invalid")
    git(path, "config", "user.name", "selftest")
    git(path, "config", "core.autocrlf", "false")
    return path


def write(repo, rel, text):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def d_loopcommit(d):
    """loopcommit commits exactly the declared paths and refuses everything else, with exit 2."""
    repo = new_repo(os.path.join(d.dir, "repo"))
    for f in ("a.txt", "b.txt", "d.txt", "dir/x.txt"):
        write(repo, f, f"{f} v1\n")
    write(repo, ".gitignore", "ignored/\n")
    git(repo, "add", "--", "a.txt", "b.txt", "d.txt", "dir/x.txt", ".gitignore")
    git(repo, "commit", "-q", "-m", "base", "--", "a.txt", "b.txt", "d.txt", "dir/x.txt", ".gitignore")

    def lc(*args, script=LC):
        pre = [TOOLS] if script != LC else []
        return subprocess.run(PY + [script, *pre, *args], env=d.env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", creationflags=FLAGS)
    head = lambda: git(repo, "rev-parse", "HEAD")      # noqa: E731
    base = head()
    git(repo, "branch", "main")                        # the rails the passes are held to
    write(repo, "a.txt", "a v2\n")
    r = lc("commit", "--repo", repo, "--run", "R0", "-m", "no pass", "--", "a.txt")
    d.expect(r.returncode == 2 and "no open pass" in r.stderr and head() == base,
             f"a commit outside any pass: {r.returncode} {r.stderr[-300:]}")
    for run in ("R1", "R8", "R9"):
        r = lc("pass", "begin", "--run", run, "--repo", repo)
        d.expect(r.returncode == 0, f"pass begin {run}: {r.returncode} {r.stderr[-300:]}")
    write(repo, "b.txt", "b v2\n")
    git(repo, "add", "--", "b.txt")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "a only", "--", "a.txt")
    d.expect(r.returncode == 2 and "outside the declared paths" in r.stderr and head() == base,
             f"committed with an undeclared staged path: {r.returncode} {r.stderr}")
    git(repo, "reset", "-q", "--", "b.txt")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "a only", "--body", "#TICKCOUNTS stays", "--", "a.txt")
    files = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").split()
    d.expect(r.returncode == 0 and files == ["a.txt"], f"declared-only commit touched {files}: {r.stderr}")
    d.expect("#TICKCOUNTS stays" in git(repo, "log", "-1", "--format=%B"), "a '#' body line was stripped")
    d.expect(git(repo, "status", "--porcelain", "--", "b.txt") == "M b.txt", "b.txt should still be modified and uncommitted")
    h = head()
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "nothing", "--", "d.txt")
    d.expect(r.returncode == 2 and "nothing to commit" in r.stderr and head() == h, "an unchanged declared path was accepted")
    write(repo, "ignored/z.txt", "z\n")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "ignored", "--", "ignored/z.txt")
    d.expect(r.returncode == 2 and head() == h, "an ignored path was committed")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "outside", "--", os.path.join(d.dir, "elsewhere.txt"))
    d.expect(r.returncode == 2 and head() == h, "a path outside the repo was accepted")
    drive = os.path.splitdrive(repo)[0].upper()
    other = ("Q:" if drive != "Q:" else "R:") + r"\elsewhere.txt"
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "other drive", "--", other)
    d.expect(r.returncode == 2 and "another drive" in r.stderr and head() == h,
             f"a path on another drive: exit {r.returncode} {r.stderr[-300:]}")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "spoof", "--body", "Loop-Run: R9", "--", "b.txt")
    d.expect(r.returncode == 2 and head() == h, "a body carrying Loop-Run was accepted")
    # what only the owner changes: the rails' code and the ratchet's ledgers, declared by name or reached by a folder
    write(repo, "tools/corpus_grade.py", "# a loop's own gate\n")
    write(repo, "sources/demotions.jsonl", '{"chart": "X S1", "block_sha": "' + "0" * 64 + '", "reason": "r", "evidence": "e"}\n')
    write(repo, "sources/report.json", "{}\n")
    for decl in (["tools/corpus_grade.py"], ["sources"], ["sources/demotions.jsonl", "b.txt"]):
        r = lc("commit", "--repo", repo, "--run", "R1", "-m", "owner-only", "--", *decl)
        d.expect(r.returncode == 2 and "only the owner" in r.stderr and head() == h
                 and git(repo, "diff", "--cached", "--name-only") == "",
                 f"an owner-only path {decl}: exit {r.returncode}, staged {git(repo, 'diff', '--cached', '--name-only')!r}: "
                 f"{r.stderr[-300:]}")
    for f in ("tools/corpus_grade.py", "sources/demotions.jsonl", "sources/report.json"):
        os.remove(os.path.join(repo, f))
    git(repo, "checkout", "-q", "main")
    hm = head()
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "on main", "--", "b.txt")
    d.expect(r.returncode == 2 and "main" in r.stderr and head() == hm, "committed on main")
    git(repo, "checkout", "-q", "loops/test")
    d.expect(head() == h, "back on loops/test at another commit")
    # the commit lock not taken in time: refused (2), not a traceback
    holder = subprocess.Popen(PY + [SUP, "lock-exec", "--run", "other", "--", *PY, "-c", "import time; time.sleep(600)"],
                              env=d.env, creationflags=FLAGS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(lambda: (S.read_json(os.path.join(d.state, ".commit.lock")) or {}).get("child"), 60)
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "lock busy", "--lock-timeout", "2", "--", "b.txt")
    kill_tree(holder.pid)
    holder.wait(30)
    d.expect(r.returncode == 2 and "nothing was committed" in r.stderr and "Traceback" not in r.stderr and head() == h,
             f"commit-lock timeout: exit {r.returncode} {r.stderr[-300:]}")
    # the converter pin: a run whose manifest names another converter hash may not commit
    conv_hash, _ = S.converter_hash(S.converter_dir())
    for run, digest in (("R8", conv_hash), ("R9", "0" * 64)):
        S.write_json(os.path.join(d.state, "runs", run, "manifest.json"),
                     {"run": run, "pins": {"converter": {"py_sha256": digest}}, "attempts": []})
    r = lc("commit", "--repo", repo, "--run", "R9", "-m", "drifted", "--", "b.txt")
    d.expect(r.returncode == 2 and "changed since run R9 began" in r.stderr and head() == h,
             f"a commit under a changed converter: exit {r.returncode} {r.stderr[-300:]}")
    r = lc("commit", "--repo", repo, "--run", "R8", "-m", "b under the run's converter", "--", "b.txt")
    d.expect(r.returncode == 0 and head() != h, f"a commit under the run's own converter was refused: {r.stderr[-300:]}")
    h = head()
    # a commit that fails its post-commit check is undone, its changes left staged (exit 3)
    badcheck = d.script("badcheck.py", BADCHECK)
    write(repo, "a.txt", "a v3\n")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "fails its check", "--", "a.txt", script=badcheck)
    d.expect(r.returncode == 3 and head() == h and git(repo, "diff", "--cached", "--name-only") == "a.txt",
             f"a commit failing its check: exit {r.returncode}, HEAD moved {head() != h}, staged "
             f"{git(repo, 'diff', '--cached', '--name-only')!r}: {r.stderr[-300:]}")
    git(repo, "reset", "-q", "--", "a.txt")
    write(repo, "dir/x.txt", "x v2\n")
    write(repo, "dir/y.txt", "y v1\n")
    os.remove(os.path.join(repo, "d.txt"))
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "folder and a delete", "--", "dir", "d.txt")
    files = sorted(git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").split())
    d.expect(r.returncode == 0 and files == ["d.txt", "dir/x.txt", "dir/y.txt"], f"folder commit touched {files}: {r.stderr}")
    trailer = git(repo, "log", "-1", "--format=%(trailers:key=Loop-Run,valueonly)")
    d.expect(trailer == "R1", f"trailer {trailer!r}")
    d.expect("Co-Authored-By: Claude Opus 5.5" in git(repo, "log", "-1", "--format=%B"), "no Co-Authored-By trailer")
    # a body file PowerShell wrote (BOM, CRLF), and the same body piped to stdin with a BOM
    body = os.path.join(d.dir, "body.txt")
    with open(body, "w", encoding="utf-8", newline="") as fh:
        fh.write("﻿#TICKCOUNTS first line\r\nsecond line\r\n")
    write(repo, "a.txt", "a v4\n")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "bom body", "--body-file", body, "--", "a.txt")
    msg = git(repo, "log", "-1", "--format=%B")
    d.expect(r.returncode == 0 and "﻿" not in msg and "\n#TICKCOUNTS first line" in msg,
             f"a BOM'd body file: exit {r.returncode}, message {msg[:120]!r}: {r.stderr[-200:]}")
    write(repo, "a.txt", "a v5\n")
    piped = subprocess.run(PY + [LC, "commit", "--repo", repo, "--run", "R1", "-m", "bom stdin", "--body-file", "-", "--", "a.txt"],
                           env=d.env, input="﻿piped body\n".encode("utf-8"), capture_output=True, creationflags=FLAGS)
    msg = git(repo, "log", "-1", "--format=%B")
    d.expect(piped.returncode == 0 and "﻿" not in msg and "\npiped body" in msg,
             f"a BOM on stdin: exit {piped.returncode}, message {msg[:120]!r}")
    return ("refused (exit 2): no open pass, undeclared staged, unchanged, ignored, outside, other drive, spoofed "
            "trailer, owner-only paths (by name or through a folder, nothing left staged), main, lock timeout, changed "
            "converter; failed check undone (exit 3); committed exactly a file, a folder and a delete; a BOM'd body file "
            "or stdin leaves no BOM in the message")


def d_revert_run(d):
    """revert-run reverts only this run's trailered commits after the base, newest first."""
    repo = new_repo(os.path.join(d.dir, "repo"))

    def lc(command, *args, script=LC):              # --repo before the args: everything after -- is a path
        pre = [TOOLS] if script != LC else []
        return subprocess.run(PY + [script, *pre, command, "--repo", repo, *args], env=d.env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", creationflags=FLAGS)

    begun = set()

    def loop(run, msg, **files):
        if run not in begun:                            # a loop commits only inside an open pass
            b = subprocess.run(PY + [LC, "pass", "begin", "--run", run, "--repo", repo], env=d.env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", creationflags=FLAGS)
            if b.returncode != 0:
                raise RuntimeError(b.stderr)
            begun.add(run)
        for rel, text in files.items():
            if text is None:
                os.remove(os.path.join(repo, rel))
            else:
                write(repo, rel, text)
        r = lc("commit", "--run", run, "-m", msg, "--", *files)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)

    def manual(msg, **files):
        for rel, text in files.items():
            write(repo, rel, text)
        git(repo, "add", "--", *files)
        git(repo, "commit", "-q", "-m", msg, "--", *files)

    def tree():
        return {f: open(os.path.join(repo, f), encoding="utf-8").read()
                for f in sorted(git(repo, "ls-files").split())}
    manual("seed", a="a0\n", b="b0\n", d="d0\n", g="g0\n")
    git(repo, "branch", "main")
    loop("R1", "R1 before the base", d="d1\n")                  # must survive: it is not after the base
    base = git(repo, "rev-parse", "HEAD")
    at_base = tree()
    loop("R1", "R1 first", a="a1\n")
    manual("owner's own commit", b="b-owner\n")
    loop("R2", "R2 other run", e="e-r2\n")
    loop("R1", "R1 second", a="a2\n", f="f-new\n")
    loop("R1", "R1 third", g=None)                               # a delete
    before = git(repo, "rev-list", "--count", "HEAD")
    r = lc("revert-run", "R1", "--base", base)
    after = tree()
    expected = dict(at_base, b="b-owner\n", e="e-r2\n")
    d.expect(r.returncode == 0, f"revert-run failed: {r.stderr}")
    d.expect(after == expected, f"tree after revert {after}, expected {expected}")
    d.expect(int(git(repo, "rev-list", "--count", "HEAD")) == int(before) + 3, "revert-run did not add exactly 3 commits")
    reverts = git(repo, "log", "-3", "--format=%(trailers:key=Loop-Revert,valueonly,separator=%x2C)|"
                                     "%(trailers:key=Loop-Run,valueonly,separator=%x2C)|%s")
    rows = [x.split("|") for x in reverts.splitlines()]
    d.expect(len(rows) == 3 and all(x[0] == "R1" and x[1] == "" for x in rows),
             f"revert commits must carry Loop-Revert and no Loop-Run: {rows}")
    order = [x[2] for x in rows]
    d.expect(order == ['Revert "R1 first"', 'Revert "R1 second"', 'Revert "R1 third"'],
             f"not reverted newest first: {order}")
    h = git(repo, "rev-parse", "HEAD")
    again = lc("revert-run", "R1", "--base", base)
    d.expect(again.returncode == 0 and git(repo, "rev-parse", "HEAD") == h and "0 to revert" in again.stdout,
             f"second revert-run was not a no-op: {again.stdout}{again.stderr}")
    loop("R3", "R3 edits g2", h="h-r3\n")
    manual("owner edits the same line", h="h-owner\n")
    h = git(repo, "rev-parse", "HEAD")
    conflict = lc("revert-run", "R3", "--base", base)
    d.expect(conflict.returncode == 2 and "no longer applies" in conflict.stderr and git(repo, "rev-parse", "HEAD") == h
             and git(repo, "status", "--porcelain") == "", f"conflicting revert: {conflict.returncode} {conflict.stderr}")
    bad = lc("revert-run", "R1", "--base", "0000000000000000000000000000000000000000")
    d.expect(bad.returncode == 2, "a bogus base was accepted")
    # a revert commit that fails its post-commit check is undone like any other (exit 3)
    loop("R4", "R4 adds i", i="i-r4\n")
    h = git(repo, "rev-parse", "HEAD")
    badcheck = d.script("badcheck.py", BADCHECK)
    failed = lc("revert-run", "R4", "--base", base, script=badcheck)
    staged = git(repo, "diff", "--cached", "--name-status")
    d.expect(failed.returncode == 3 and git(repo, "rev-parse", "HEAD") == h and staged == "D\ti",
             f"a revert failing its check: exit {failed.returncode}, HEAD moved {git(repo, 'rev-parse', 'HEAD') != h}, "
             f"staged {staged!r}: {failed.stderr[-300:]}")
    return ("3 R1 commits reverted newest first; R2, the owner's and pre-base commits untouched; rerun no-op; "
            "conflict stops cleanly; a revert failing its check is undone (exit 3)")


# A toy tools/corpus_grade.py for the pass drill's throwaway repository (loopcommit's `pass gate`
# runs the repository's own grade): each call is logged and answered from a plan, one word per call.
# It imports a tools/ module of its own (toyhelper: the gate's code, which a loop may change) and,
# if it can find one, psf_selftest_probe - which only a PYTHONPATH the loop set could supply.
PASS_GATE = r'''
import json, os, sys
import toyhelper
try:
    import psf_selftest_probe
except ImportError:
    psf_selftest_probe = None
a = sys.argv[1:]
def opt(k):
    return a[a.index(k) + 1] if k in a else None
with open(os.environ["PASS_ENV"], "a") as fh:
    fh.write(json.dumps(dict(pythonpath=os.environ.get("PYTHONPATH"), pycache=sys.pycache_prefix,
                             probe=psf_selftest_probe is not None, helper=toyhelper.X)) + "\n")
with open(os.environ["PASS_LOG"], "a") as fh:
    fh.write(json.dumps(a) + "\n")
plan = open(os.environ["PASS_PLAN"]).read().split()
n = sum(1 for _ in open(os.environ["PASS_LOG"]))
what = plan[min(n, len(plan)) - 1]
rep = dict(base=opt("--base"), head=opt("--head"), net=int(opt("--declared")),
           failures=["DECLARED: planted by supervise_selftest"] if what == "FAIL" else [])
if what in ("PASS", "FAIL"):
    rep["verdict"] = what
    with open(opt("--json"), "w") as fh:
        json.dump(rep, fh)
if what == "REFUSE":
    print("REFUSED: planted by supervise_selftest")
print(what)
sys.exit(dict(PASS=0, FAIL=1, LATER=75, REFUSE=2, KILLED=1)[what])
'''


def d_pass(d):
    """A commit pass: every gate runs on the recorded base; a new pass cannot start over an open one;
    75 and a report-less exit keep it open; FAIL halts the run and reverts only its commits after the base."""
    repo = new_repo(os.path.join(d.dir, "repo"))
    write(repo, "tools/corpus_grade.py", PASS_GATE)
    write(repo, "tools/toyhelper.py", "X = 1\n")
    for f in ("a.txt", "b.txt", "c.txt"):
        write(repo, f, f"{f} v1\n")
    git(repo, "add", "--", "tools/corpus_grade.py", "tools/toyhelper.py", "a.txt", "b.txt", "c.txt")
    git(repo, "commit", "-q", "-m", "seed", "--", "tools/corpus_grade.py", "tools/toyhelper.py", "a.txt", "b.txt", "c.txt")
    git(repo, "branch", "main")                        # the rails the passes are held to
    plan, glog = os.path.join(d.dir, "plan.txt"), os.path.join(d.dir, "gate-calls.jsonl")
    elog = os.path.join(d.dir, "gate-env.jsonl")
    env = dict(d.env, PASS_PLAN=plan, PASS_LOG=glog, PASS_ENV=elog)

    def lc(*args, extra=None):
        return subprocess.run(PY + [LC, *args], env=dict(env, **(extra or {})), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=FLAGS)

    def p(sub, run, *args, extra=None):
        return lc("pass", sub, "--run", run, "--repo", repo, *args, extra=extra)

    def plain(msg, trailer=None, **files):             # a commit made around loopcommit
        for rel, text in files.items():
            write(repo, rel, text)
        git(repo, "add", "--", *files)
        git(repo, "commit", "-q", "-m", msg + (f"\n\nLoop-Run: {trailer}" if trailer else ""), "--", *files)

    def commit(run, msg, **files):
        for rel, text in files.items():
            write(repo, rel, text)
        return lc("commit", "--repo", repo, "--run", run, "-m", msg, "--", *files)

    def gate_plan(*steps):
        with open(plan, "w") as fh:
            fh.write(" ".join(steps))
        if os.path.exists(glog):
            os.remove(glog)

    def calls():
        return [json.loads(x) for x in open(glog)] if os.path.exists(glog) else []

    def state(run):
        return S.read_json(os.path.join(d.state, "runs", run, "pass.json")) or {}

    def text(rel):
        return open(os.path.join(repo, rel), encoding="utf-8").read()
    head = lambda: git(repo, "rev-parse", "HEAD")        # noqa: E731
    stop = lambda run: os.path.join(d.state, "runs", run, "STOP")    # noqa: E731

    r = p("gate", "RP", "--declared", "0")
    d.expect(r.returncode == 2 and "no open pass" in r.stderr, f"a gate with no pass begun: {r.returncode} {r.stderr[-200:]}")
    base = head()
    r = p("begin", "RP")
    d.expect(r.returncode == 0 and state("RP").get("base") == base, f"begin: {r.returncode} {state('RP')} {r.stderr[-200:]}")
    r = p("begin", "RP")
    d.expect(r.returncode == 0 and "already open" in r.stdout, f"a second begin with nothing committed: {r.returncode} {r.stdout}")
    d.expect(commit("RP", "RP one", **{"a.txt": "a v2\n"}).returncode == 0, "the pass's first commit failed")
    r = p("begin", "RP")
    d.expect(r.returncode == 2 and "not gated" in r.stderr and state("RP").get("base") == base,
             f"a new pass began over an open one with commits: {r.returncode} {r.stderr[-200:]}")
    gate_plan("LATER", "KILLED", "PASS")
    r = p("gate", "RP", "--declared", "1")
    d.expect(r.returncode == 75 and state("RP").get("state") == "open", f"gate said later: {r.returncode} {state('RP').get('state')}")
    r = p("gate", "RP", "--declared", "0")
    d.expect(r.returncode == 2 and "declared" in r.stderr and len(calls()) == 1,
             f"a retry changing its declared count: {r.returncode} {r.stderr[-200:]}")
    d.expect(commit("RP", "RP two", **{"b.txt": "b v2\n"}).returncode == 0, "the pass's second commit failed")
    h = head()
    r = p("gate", "RP", "--declared", "1")
    d.expect(r.returncode == 75 and head() == h and not os.path.exists(stop("RP")),
             f"a gate that exited 1 with no report was taken as a verdict: {r.returncode}, STOP {os.path.exists(stop('RP'))}")
    r = p("gate", "RP", "--declared", "1")
    d.expect(r.returncode == 0 and state("RP").get("state") == "passed", f"gate PASS: {r.returncode} {state('RP').get('state')}")
    cs = calls()
    d.expect(len(cs) == 3 and all(c[c.index("--base") + 1] == base for c in cs) and cs[-1][cs[-1].index("--head") + 1] == h,
             f"the retries did not gate the recorded base {base[:10]} at HEAD: {cs}")
    hist = S.read_jsonl(os.path.join(d.state, "runs", "RP", "passes.jsonl"))
    d.expect(len(hist) == 1 and hist[0].get("state") == "passed", f"passes.jsonl: {hist}")

    # a failing pass: the run's commits after its base are reverted, the owner's are not, the run halts
    base2 = head()
    d.expect(p("begin", "RP").returncode == 0, "a new pass after a passed one did not begin")
    d.expect(commit("RP", "RP three", **{"a.txt": "a v3\n", "c.txt": "c v2\n"}).returncode == 0, "RP three failed")
    write(repo, "b.txt", "b-owner\n")
    git(repo, "add", "--", "b.txt")
    git(repo, "commit", "-q", "-m", "the owner's own commit", "--", "b.txt")
    d.expect(commit("RP", "RP four", **{"a.txt": "a v4\n"}).returncode == 0, "RP four failed")
    gate_plan("FAIL")
    r = p("gate", "RP", "--declared", "1")
    st = state("RP")
    d.expect(r.returncode == 4 and os.path.exists(stop("RP")) and "FAILED" in open(stop("RP"), encoding="utf-8").read(),
             f"a failed gate: exit {r.returncode}, STOP {os.path.exists(stop('RP'))}: {r.stderr[-300:]}")
    d.expect((text("a.txt"), text("b.txt"), text("c.txt")) == ("a v2\n", "b-owner\n", "c.txt v1\n"),
             f"after the revert: a {text('a.txt')!r} b {text('b.txt')!r} c {text('c.txt')!r}")
    d.expect(st.get("state") == "failed" and (st.get("revert") or {}).get("reverted") == 2, f"pass record: {st}")
    d.expect(git(repo, "log", "-1", "--format=%(trailers:key=Loop-Revert,valueonly)") == "RP", "the reverts are not on the branch")
    h = head()
    r = commit("RP", "RP five", **{"c.txt": "c v9\n"})
    d.expect(r.returncode == 2 and "pass gate failed" in r.stderr and head() == h,
             f"a halted run committed: {r.returncode} {r.stderr[-200:]}")
    git(repo, "checkout", "-q", "--", "c.txt")
    r = p("begin", "RP")
    d.expect(r.returncode == 2 and "STOP" in r.stderr, f"a pass began under the run's STOP: {r.returncode} {r.stderr[-200:]}")

    # a gate that refuses (drift, an oracle not frozen): the run halts, nothing is reverted, the pass stays open
    d.expect(p("begin", "RQ").returncode == 0, "RQ begin failed")
    d.expect(commit("RQ", "RQ one", **{"c.txt": "c v3\n"}).returncode == 0, "RQ one failed")
    h = head()
    gate_plan("REFUSE")
    r = p("gate", "RQ", "--declared", "0")
    d.expect(r.returncode == 2 and os.path.exists(stop("RQ")) and head() == h and state("RQ").get("state") == "open",
             f"a refused gate: exit {r.returncode}, STOP {os.path.exists(stop('RQ'))}, HEAD moved {head() != h}, "
             f"state {state('RQ').get('state')}")

    # a commit outside a pass - before `pass begin`, or after the pass closed - is refused: it would sit
    # under the next pass's base, and no gate would ever look at it
    h = head()
    r = commit("RC", "RC before its pass", **{"c.txt": "c rc0\n"})
    d.expect(r.returncode == 2 and "no open pass" in r.stderr and head() == h,
             f"a commit before pass begin: {r.returncode} {r.stderr[-200:]}")
    git(repo, "checkout", "-q", "--", "c.txt")
    d.expect(p("begin", "RC").returncode == 0, "RC begin failed")
    d.expect(commit("RC", "RC one", **{"c.txt": "c rc1\n"}).returncode == 0, "RC one failed")
    gate_plan("PASS")
    d.expect(p("gate", "RC", "--declared", "0").returncode == 0 and state("RC").get("state") == "passed", "RC's gate did not pass")
    h = head()
    r = commit("RC", "RC after its pass", **{"c.txt": "c rc2\n"})
    d.expect(r.returncode == 2 and "no open pass" in r.stderr and head() == h,
             f"a commit after the pass passed: {r.returncode} {r.stderr[-200:]}")
    git(repo, "checkout", "-q", "--", "c.txt")
    # a Loop-Run commit that went around loopcommit: no pass begins over it
    plain("RC around loopcommit", trailer="RC", **{"c.txt": "c rc3\n"})
    r = p("begin", "RC")
    d.expect(r.returncode == 2 and "no pass gated" in r.stderr, f"a pass began over an ungated commit: {r.returncode} {r.stderr[-300:]}")

    # the gate's own code: a loop's change to a module the gate imports makes a TOOLS-ONLY pass (nothing
    # to judge, not gated); a stepfile pass over it is refused (2, halted, nothing reverted) until main has it
    gate_plan("PASS")
    d.expect(p("begin", "RT").returncode == 0, "RT begin failed")
    d.expect(commit("RT", "RT: the loop's own helper", **{"tools/toyhelper.py": "X = 2\n"}).returncode == 0, "RT helper commit failed")
    r = p("gate", "RT", "--declared", "0")
    st = state("RT")
    d.expect(r.returncode == 0 and st.get("state") == "passed" and st.get("tools_only") and not calls(),
             f"a tools-only pass: exit {r.returncode}, state {st.get('state')}, gate called {len(calls())}x: {r.stdout[-300:]}{r.stderr[-300:]}")
    r = p("begin", "RT")
    d.expect(r.returncode == 0 and "not main's" in r.stdout and "toyhelper.py" in r.stdout, f"begin over changed gate code: {r.stdout}")
    d.expect(commit("RT", "RT: a stepfile", **{"simfiles/s.ssc": "#NOTES:1;\n"}).returncode == 0, "RT stepfile commit failed")
    h = head()
    r = p("gate", "RT", "--declared", "0")
    d.expect(r.returncode == 2 and "toyhelper.py" in r.stderr and not calls() and head() == h and os.path.exists(stop("RT"))
             and state("RT").get("state") == "open",
             f"a stepfile pass over changed gate code: exit {r.returncode}, gate called {len(calls())}x, HEAD moved {head() != h}, "
             f"STOP {os.path.exists(stop('RT'))}, state {state('RT').get('state')}: {r.stderr[-300:]}")
    git(repo, "branch", "-f", "main", "HEAD")          # the owner merges that code into main and clears the STOP
    os.remove(stop("RT"))
    r = p("gate", "RT", "--declared", "0")
    d.expect(r.returncode == 0 and len(calls()) == 1 and state("RT").get("state") == "passed",
             f"the same pass once main has the code: exit {r.returncode}, gate called {len(calls())}x: {r.stderr[-300:]}")
    d.expect(p("begin", "RU").returncode == 0, "RU begin failed")
    d.expect(commit("RU", "RU: helper again", **{"tools/toyhelper.py": "X = 3\n"}).returncode == 0, "RU helper commit failed")
    gate_plan("PASS")
    r = p("gate", "RU", "--declared", "1")
    d.expect(r.returncode == 4 and text("tools/toyhelper.py") == "X = 2\n" and state("RU").get("state") == "failed" and not calls(),
             f"a tools-only pass declaring a ship: exit {r.returncode}, helper {text('tools/toyhelper.py')!r}, "
             f"state {state('RU').get('state')}: {r.stderr[-300:]}")

    # a planted tools/json.py (the gate imports json) in the working tree: refused before anything runs
    d.expect(p("begin", "RW").returncode == 0, "RW begin failed")
    d.expect(commit("RW", "RW: a stepfile", **{"simfiles/w.ssc": "#NOTES:2;\n"}).returncode == 0, "RW stepfile commit failed")
    write(repo, "tools/json.py", "raise SystemExit('planted json')\n")
    r = p("gate", "RW", "--declared", "0")
    d.expect(r.returncode == 2 and "tools/json.py" in r.stderr and not calls(),
             f"a planted tools/json.py: exit {r.returncode}, gate called {len(calls())}x: {r.stderr[-300:]}")
    os.remove(os.path.join(repo, "tools", "json.py"))
    os.remove(stop("RW"))
    # a loop's PYTHONPATH never reaches the gate, and bytecode is looked up only in the gate's own empty folder
    evil = os.path.join(d.dir, "evil")
    write(evil, "psf_selftest_probe.py", "X = 1\n")
    if os.path.exists(elog):
        os.remove(elog)
    r = p("gate", "RW", "--declared", "0", extra={"PYTHONPATH": evil})
    seen = [json.loads(x) for x in open(elog)] if os.path.exists(elog) else []
    d.expect(r.returncode == 0 and len(seen) == 1 and not seen[0]["probe"] and seen[0]["pythonpath"] is None
             and seen[0]["pycache"] and not os.path.exists(seen[0]["pycache"]),
             f"the gate's environment: exit {r.returncode}, {seen}: {r.stderr[-300:]}")

    # an owner-only path committed around loopcommit (a demotion the loop wrote itself): refused before anything runs
    d.expect(p("begin", "RO").returncode == 0, "RO begin failed")
    plain("RO demotes a chart", trailer="RO", **{"sources/demotions.jsonl": '{"chart": "X S1"}\n'})
    gate_plan("PASS")
    r = p("gate", "RO", "--declared", "0")
    d.expect(r.returncode == 2 and "only the owner" in r.stderr and not calls() and os.path.exists(stop("RO")),
             f"an owner-only path in the pass: exit {r.returncode}, gate called {len(calls())}x: {r.stderr[-300:]}")
    # ... or changed in the working tree only, where the gate's audit would read it
    d.expect(p("begin", "RD").returncode == 0, "RD begin failed")
    d.expect(commit("RD", "RD: a harmless file", **{"d.txt": "d rd\n"}).returncode == 0, "RD commit failed")
    write(repo, "sources/footage-corrupt.json", '{"videos": []}\n')
    r = p("gate", "RD", "--declared", "0")
    d.expect(r.returncode == 2 and "in the working tree sources/footage-corrupt.json" in r.stderr and not calls(),
             f"an owner-only file changed in the working tree: exit {r.returncode}, gate called {len(calls())}x: {r.stderr[-300:]}")
    os.remove(os.path.join(repo, "sources", "footage-corrupt.json"))
    return ("no-pass gate refused; begin idempotent until a commit, then refused; 75 and a report-less exit 1 kept the "
            "pass open and re-gated its base; FAIL halted and reverted 2 of the run's commits (the owner's kept), "
            "then refused its commits and a new pass; a refusing gate halted with nothing reverted; commits before "
            "begin and after a closed pass refused, and no pass begins over an ungated one; a tools-only pass passed "
            "ungated, a stepfile pass over it refused until main had the code, then gated; a planted tools/json.py, "
            "an owner-only path committed or changed in the working tree refused; the gate ran without the loop's PYTHONPATH and with an empty pycache prefix")


def d_hook(d):
    """The pre-push hook refuses while work/.main.lock exists, and only then."""
    remote = os.path.join(d.dir, "remote.git")
    git(d.dir, "init", "-q", "--bare", "-b", "main", remote)
    repo = new_repo(os.path.join(d.dir, "clone"), branch="main")
    os.makedirs(os.path.join(repo, ".githooks"))
    shutil.copy(HOOK, os.path.join(repo, ".githooks", "pre-push"))
    git(repo, "config", "core.hooksPath", ".githooks")
    git(repo, "remote", "add", "origin", remote)
    write(repo, "a.txt", "a\n")
    git(repo, "add", "--", "a.txt")
    git(repo, "commit", "-q", "-m", "a", "--", "a.txt")
    env = dict(d.env, PSF_RAILS_STATE=os.path.join(repo, "work"))
    # loop activity (runs, slots, the commit lock) must not block a push
    os.makedirs(os.path.join(repo, "work", "runs", "someloop"))
    write(repo, "work/.commit.lock", json.dumps({"pid": os.getpid(), "run": "someloop"}))
    ok = subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, capture_output=True, text=True, creationflags=FLAGS)
    d.expect(ok.returncode == 0, f"push blocked by loop activity: {ok.stderr}")
    take = subprocess.run(PY + [SUP, "mainlock", "take", "--note", "selftest merge"], env=env, capture_output=True,
                          text=True, creationflags=FLAGS)
    d.expect(take.returncode == 0 and os.path.exists(os.path.join(repo, "work", ".main.lock")), f"mainlock take: {take.stderr}")
    write(repo, "a.txt", "a2\n")
    git(repo, "commit", "-q", "-m", "a2", "--", "a.txt")
    refused = subprocess.run(["git", "push", "origin", "main"], cwd=repo, capture_output=True, text=True, creationflags=FLAGS)
    d.expect(refused.returncode != 0 and "REFUSED" in refused.stderr and "selftest merge" in refused.stderr,
             f"push while the main lock is held: {refused.returncode} {refused.stderr}")
    d.expect(git(remote, "rev-parse", "main") != git(repo, "rev-parse", "HEAD"), "the refused push reached the remote")
    subprocess.run(PY + [SUP, "mainlock", "release"], env=env, capture_output=True, creationflags=FLAGS)
    ok2 = subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, capture_output=True, text=True, creationflags=FLAGS)
    d.expect(ok2.returncode == 0 and git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD"),
             f"push after release: {ok2.stderr}")
    return "pushed with loop activity; refused with the lock (and said why); pushed after release"


def d_junction(d):
    """Unlinking a junction (worktree-remove's first step) leaves its target's contents alone."""
    target = os.path.join(d.dir, "shared")
    os.makedirs(os.path.join(target, "deep"))
    write(target, "sentinel.txt", "keep me\n")
    write(target, "deep/also.txt", "keep me too\n")
    wt = os.path.join(d.dir, "wt")
    os.makedirs(wt)
    link = os.path.join(wt, "work")
    r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, text=True, creationflags=FLAGS)
    d.expect(r.returncode == 0 and os.path.isjunction(link), f"mklink /J failed: {r.stdout}{r.stderr}")
    d.expect(os.path.exists(os.path.join(link, "sentinel.txt")), "junction does not resolve")
    os.rmdir(link)
    d.expect(not os.path.lexists(link), "junction still there")
    d.expect(open(os.path.join(target, "sentinel.txt")).read() == "keep me\n"
             and os.path.exists(os.path.join(target, "deep", "also.txt")), "unlinking the junction touched its target")
    return "junction unlinked, target intact"


def d_worktree(d):
    """worktree/worktree-remove in a throwaway repository: a worktree git would refuse to remove
    keeps its junctions; a failed removal puts them back; a clean one is removed, targets intact."""
    main = new_repo(os.path.join(d.dir, "main"), branch="main")
    os.makedirs(os.path.join(main, "tools"))
    shutil.copy(SUP, os.path.join(main, "tools", "supervise.py"))
    shutil.copy(os.path.join(TOOLS, "shadowcheck.py"), os.path.join(main, "tools", "shadowcheck.py"))  # supervise imports it first
    write(main, ".gitignore", "work/\nvideos/\n")
    write(main, "work/sentinel.txt", "keep\n")
    write(main, "work/deep/a.txt", "keep\n")
    write(main, "videos/v.mp4", "not a video\n")
    git(main, "add", "--", "tools/supervise.py", "tools/shadowcheck.py", ".gitignore")
    git(main, "commit", "-q", "-m", "seed", "--", "tools/supervise.py", "tools/shadowcheck.py", ".gitignore")
    own = os.path.join(main, "tools", "supervise.py")
    wt = os.path.join(d.dir, "psf-wt", "t1")

    def run(*args, script=own, pre=()):
        return subprocess.run(PY + [script, *pre, *args], cwd=main, env=d.env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=FLAGS)

    def linked():
        return all(os.path.isjunction(os.path.join(wt, s)) and S.same_dir(os.path.join(wt, s), os.path.join(main, s))
                   for s in ("work", "videos"))

    def intact():
        return (open(os.path.join(main, "work", "sentinel.txt")).read() == "keep\n"
                and os.path.exists(os.path.join(main, "work", "deep", "a.txt"))
                and os.path.exists(os.path.join(main, "videos", "v.mp4")))
    r = run("worktree", "t1", "--base", "HEAD", "--no-preflight")
    d.expect(r.returncode == 0 and linked(), f"worktree create: {r.returncode} {r.stdout}{r.stderr}")
    write(wt, "untracked.txt", "junk\n")
    r = run("worktree-remove", "t1", "--delete-branch")
    d.expect(r.returncode != 0 and "nothing was changed" in r.stderr and linked() and intact(),
             f"untracked file: exit {r.returncode}, linked {linked()}: {r.stdout}{r.stderr}")
    os.remove(os.path.join(wt, "untracked.txt"))
    git(main, "worktree", "lock", wt)
    r = run("worktree-remove", "t1")
    d.expect(r.returncode != 0 and "locked" in r.stderr and linked(), f"locked worktree: {r.returncode} {r.stderr}")
    git(main, "worktree", "unlock", wt)
    wtfail = d.script("wtfail.py", WTFAIL)
    r = run("worktree-remove", "t1", script=wtfail, pre=(os.path.join(main, "tools"),))
    d.expect(r.returncode != 0 and "re-linked" in r.stdout and linked() and intact(),
             f"a failed git worktree remove did not restore the junctions: {r.returncode} {r.stdout}{r.stderr}")
    r = run("worktree-remove", "t1", "--delete-branch")
    branches = git(main, "branch", "--list", "loops/t1")
    d.expect(r.returncode == 0 and not os.path.exists(wt) and not branches and intact(),
             f"clean removal: exit {r.returncode}, exists {os.path.exists(wt)}, branch {branches!r}: {r.stdout}{r.stderr}")
    return "untracked and locked worktrees refused before unlinking; a failed removal re-linked; clean removal left the shared folders intact"


DRILLS = [("slot_limit", d_slot_limit), ("slot_two_supervisors", d_slot_two_supervisors),
          ("slot_gaming", d_slot_gaming), ("gaming_preempt", d_gaming_preempt), ("preempt_stop", d_preempt_stop),
          ("freeze_lock_holder", d_freeze_lock_holder), ("freeze_mutex", d_freeze_mutex),
          ("frozen_lock_wait", d_frozen_lock_wait), ("late_assign", d_late_assign), ("jobs_bom", d_jobs_bom),
          ("stop_run", d_stop_run), ("stop_grace_kill", d_stop_grace_kill), ("timeout", d_timeout),
          ("resume", d_resume), ("retry_later", d_retry_later), ("crash", d_crash), ("commit_lock", d_commit_lock), ("stale_lock", d_stale_lock),
          ("disk_pause", d_disk_pause), ("pin_drift", d_pin_drift), ("detach", d_detach),
          ("loopcommit", d_loopcommit), ("revert_run", d_revert_run), ("pass", d_pass), ("hook", d_hook),
          ("junction", d_junction),
          ("worktree", d_worktree)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "work", "rails-selftest", time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for name, fn in DRILLS:
            print(f"{name}: {fn.__doc__}")
        return 0
    only = set(args.only.split(",")) if args.only else None
    unknown = (only or set()) - {name for name, _ in DRILLS}
    if unknown:
        raise SystemExit(f"no drill named {sorted(unknown)}")
    base = os.path.abspath(args.dir)
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "toy.py"), "w", encoding="utf-8") as fh:
        fh.write(TOY)
    print(f"selftest folder: {base}")
    fails = 0
    for name, fn in DRILLS:
        if only and name not in only:
            continue
        d = Drill(base, name)
        t0 = time.time()
        try:
            detail = fn(d)
        except Exception as e:                          # a drill that crashes is a failure, not a stop
            detail = f"crashed: {type(e).__name__}: {e}"
            d.problems.append(detail)
        ok = not d.problems
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:22s} {time.time() - t0:5.1f}s  {detail}", flush=True)
        for p in d.problems:
            print(f"        - {p}", flush=True)
    print(f"{fails} failure(s)")
    return fails


if __name__ == "__main__":
    sys.exit(main())
