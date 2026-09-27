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
            return int(open(f).read())
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
                with open(os.path.join(self.out, f)) as fh:
                    r = json.load(fh)
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
    d.expect(refused.returncode != 0 and "STOP" in (refused.stderr + refused.stdout), "a run with STOP present started")
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
    log = open(os.path.join(d.run_dir("bg"), "supervisor.log"), encoding="utf-8").read()
    d.expect(" start " in log and " end " in log, "the detached supervisor did not log its start and end")
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
    write(repo, "a.txt", "a v2\n")
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
    git(repo, "checkout", "-q", "-b", "main")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "on main", "--", "b.txt")
    d.expect(r.returncode == 2 and "main" in r.stderr and head() == h, "committed on main")
    git(repo, "checkout", "-q", "loops/test")
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
    return ("refused (exit 2): undeclared staged, unchanged, ignored, outside, other drive, spoofed trailer, main, "
            "lock timeout, changed converter; failed check undone (exit 3); committed exactly a file, a folder and a delete")


def d_revert_run(d):
    """revert-run reverts only this run's trailered commits after the base, newest first."""
    repo = new_repo(os.path.join(d.dir, "repo"))

    def lc(command, *args, script=LC):              # --repo before the args: everything after -- is a path
        pre = [TOOLS] if script != LC else []
        return subprocess.run(PY + [script, *pre, command, "--repo", repo, *args], env=d.env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", creationflags=FLAGS)

    def loop(run, msg, **files):
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
    write(main, ".gitignore", "work/\nvideos/\n")
    write(main, "work/sentinel.txt", "keep\n")
    write(main, "work/deep/a.txt", "keep\n")
    write(main, "videos/v.mp4", "not a video\n")
    git(main, "add", "--", "tools/supervise.py", ".gitignore")
    git(main, "commit", "-q", "-m", "seed", "--", "tools/supervise.py", ".gitignore")
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
          ("stop_run", d_stop_run), ("stop_grace_kill", d_stop_grace_kill), ("timeout", d_timeout),
          ("resume", d_resume), ("crash", d_crash), ("commit_lock", d_commit_lock), ("stale_lock", d_stale_lock),
          ("disk_pause", d_disk_pause), ("pin_drift", d_pin_drift), ("detach", d_detach),
          ("loopcommit", d_loopcommit), ("revert_run", d_revert_run), ("hook", d_hook), ("junction", d_junction),
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
