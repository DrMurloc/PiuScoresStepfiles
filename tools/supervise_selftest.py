# Drills for the loop rails (supervise.py, loopcommit.py, .githooks/pre-push), with toy jobs
# only: python sleeps and marks, no footage, no decoding, no real chart files.
#
#   supervise_selftest.py [--dir <scratch>] [--only name,name] [--list]
#
# Every drill runs against its own PSF_RAILS_STATE folder under --dir (default
# work/rails-selftest/<timestamp>), so the real slot pool, commit lock and runs are never
# touched, and the git drills use throwaway repositories under the same folder. Game detection
# is pointed at a name that is not running (or at python.exe for the gaming drill), so the
# result does not depend on whether the owner is playing. Takes about two minutes; prints PASS
# or FAIL per drill and exits with the number of failures. The folder is kept for inspection.
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
if mode == "sleep":
    mark("start"); time.sleep(float(sys.argv[3])); mark("end")
elif mode == "tree":
    mark("start", gc=grandchild()); time.sleep(600)
elif mode == "orphan":
    mark("start", gc=grandchild(0x00000200)); mark("end")      # exits at once; its grandchild keeps running
elif mode == "locked":
    mark("enter"); time.sleep(float(sys.argv[3])); mark("exit")
'''


class Drill:
    def __init__(self, base, name):
        self.name = name
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

    def sup(self, *args, env=None):
        return subprocess.run(PY + [SUP, *args], env=env or self.env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=FLAGS, timeout=600)

    def sup_bg(self, *args, env=None):
        log = open(os.path.join(self.dir, f"sup-{len(os.listdir(self.dir))}.log"), "w")
        return subprocess.Popen(PY + [SUP, *args], env=env or self.env, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=FLAGS)

    def marks(self, kind=None):
        rows = []
        for f in os.listdir(self.out):
            if f.endswith(".json"):
                with open(os.path.join(self.out, f)) as fh:
                    r = json.load(fh)
                if kind is None or r["kind"] == kind:
                    rows.append(r)
        return rows

    def run_dir(self, run):
        return os.path.join(self.state, "runs", run)

    def ledger(self, run):
        return [r for r in S.read_jsonl(os.path.join(self.run_dir(run), "ledger.jsonl")) if r.get("kind") == "job"]

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


# ---------------------------------------------------------------- drills

def d_slot_limit(d):
    """8 queued jobs, --parallel 8: never more than 6 at once."""
    path = d.jobs("j", [d.toyjob(f"s{i}", "sleep", 2.5) for i in range(8)])
    r = d.sup("run", "slots8", "--jobs", path, "--parallel", "8")
    rows = d.ledger("slots8")
    peak = max_overlap(d.marks())
    d.expect(r.returncode == 0, f"supervisor exit {r.returncode}: {r.stdout[-400:]}")
    d.expect(len(rows) == 8 and all(x["verdict"] == "OK" for x in rows), f"ledger {[(x['job'], x['verdict']) for x in rows]}")
    d.expect(peak == 6, f"peak concurrency {peak}, expected exactly 6 (the pool, not --parallel, must be the limit)")
    return f"8 jobs, parallel 8, peak {peak} concurrent"


def d_slot_two_supervisors(d):
    """Two supervisors with 8 jobs each share one machine-wide pool of 6."""
    a = d.sup_bg("run", "pa", "--jobs", d.jobs("a", [d.toyjob(f"a{i}", "sleep", 2.0) for i in range(8)]), "--parallel", "8")
    b = d.sup_bg("run", "pb", "--jobs", d.jobs("b", [d.toyjob(f"b{i}", "sleep", 2.0) for i in range(8)]), "--parallel", "8")
    ra, rb = a.wait(300), b.wait(300)
    peak = max_overlap(d.marks())
    d.expect(ra == 0 and rb == 0, f"exit codes {ra}, {rb}")
    d.expect(len(d.ledger("pa")) == 8 and len(d.ledger("pb")) == 8, "not every job finished")
    d.expect(peak == 6, f"combined peak {peak}, expected 6")
    return f"2 supervisors x 8 jobs, combined peak {peak}"


def d_slot_gaming(d):
    """While a listed game runs (python.exe stands in for Wow.exe), the pool drops to 2."""
    env = dict(d.env, PSF_GAME_EXES="python.exe")
    path = d.jobs("j", [d.toyjob(f"g{i}", "sleep", 1.5) for i in range(5)])
    r = d.sup("run", "gaming", "--jobs", path, "--parallel", "6", env=env)
    peak = max_overlap(d.marks())
    d.expect(r.returncode == 0, f"exit {r.returncode}")
    d.expect(peak == 2, f"peak {peak} while 'gaming', expected 2")
    d.expect((d.heartbeat("gaming").get("slots") or {}).get("gaming") == ["python.exe"], "heartbeat does not name the game")
    return f"gaming: peak {peak}"


def d_stop_run(d):
    """A run STOP is honored within one job: the running job finishes, nothing else starts."""
    path = d.jobs("j", [d.toyjob(f"t{i}", "sleep", 2.0) for i in range(6)])
    p = d.sup_bg("run", "stopme", "--jobs", path, "--parallel", "1")
    wait_for(lambda: d.marks("start"), 60)
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
    wait_for(lambda: len(d.marks("start")) >= 2, 60)
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
    m = wait_for(lambda: d.marks("start"), 60)
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
    path = d.jobs("j", [d.toyjob("hang", "tree", timeout=3), d.toyjob("orphaner", "orphan")])
    r = d.sup("run", "timeouts", "--jobs", path, "--parallel", "2")
    rows = {x["job"]: x for x in d.ledger("timeouts")}
    starts = {x["job"]: x for x in d.marks("start")}
    d.expect(r.returncode == 0, f"exit {r.returncode}")
    hang, orph = rows.get("hang", {}), rows.get("orphaner", {})
    d.expect(hang.get("outcome") == "timeout" and 3 <= hang.get("duration_s", 0) < 15, f"hang row {hang}")
    d.expect(orph.get("outcome") == "exit" and orph.get("orphans_killed", 0) >= 1, f"orphan row {orph}")
    d.expect(wait_for(lambda: dead(starts["hang"]["pid"]) and dead(starts["hang"]["gc"]), 20), "timed-out tree survived")
    d.expect(wait_for(lambda: dead(starts["orphaner"]["gc"]), 20), "the orphaned grandchild survived")
    return f"timeout killed after {hang.get('duration_s')}s; {orph.get('orphans_killed')} orphan(s) reaped"


def d_resume(d):
    """Kill -9 a supervisor mid-run; re-running the run id skips every finished job."""
    path = d.jobs("j", [d.toyjob(f"r{i}", "sleep", 1.0) for i in range(5)])
    p = d.sup_bg("run", "resume", "--jobs", path, "--parallel", "1")
    wait_for(lambda: len(d.ledger("resume")) >= 2 and len(d.marks("start")) >= 3, 60)
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
    """A lock or slot whose holder was killed is recovered by the next acquirer."""
    holder = subprocess.Popen(PY + [SUP, "lock-exec", "--run", "victim", "--", *PY, "-c", "import time; time.sleep(600)"],
                              env=d.env, creationflags=FLAGS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lock = os.path.join(d.state, ".commit.lock")
    rec = wait_for(lambda: S.read_json(lock), 30)
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
    # a slot whose supervisor dies: kill only the supervisor process (no /T); the job object's
    # kill-on-close must take its child down, and the next acquirer recovers the slot
    p = d.sup_bg("run", "slotvictim", "--jobs", d.jobs("j", [d.toyjob("held", "sleep", 600)]))
    m = wait_for(lambda: d.marks("start"), 60)
    hb = wait_for(lambda: d.heartbeat("slotvictim").get("pid"), 30)
    subprocess.run(["taskkill", "/F", "/PID", str(hb)], capture_output=True, creationflags=FLAGS)
    p.wait(30)
    d.expect(wait_for(lambda: dead(m[0]["pid"]), 20), "the job outlived its killed supervisor")
    slots = d.sup("slots")
    events = S.read_jsonl(os.path.join(d.state, "rails-events.jsonl"))
    d.expect(slots.stdout.startswith("0/"), f"slot not recovered: {slots.stdout}")
    d.expect(any(e["event"] == "stale-slot-recovered" for e in events), "no stale-slot-recovered event")
    return f"commit lock recovered {took:.1f}s after its holder was killed; 0-byte lock recovered; slot recovered"


def d_disk_pause(d):
    """Below the free-space floor the run pauses (does not fail) and resumes when there is room."""
    os.makedirs(os.path.join(d.state, ".slots"), exist_ok=True)
    S_cfg = os.path.join(d.state, ".slots", "config.json")
    with open(S_cfg, "w") as fh:
        json.dump({"min_free_gb": 10 ** 9}, fh)
    p = d.sup_bg("run", "disk", "--jobs", d.jobs("j", [d.toyjob(f"d{i}", "sleep", 0.5) for i in range(2)]))
    paused = wait_for(lambda: d.heartbeat("disk").get("state") == "paused-disk", 30)
    time.sleep(2)
    d.expect(paused and not d.marks(), "did not pause, or launched while paused")
    with open(S_cfg, "w") as fh:
        json.dump({"min_free_gb": 1}, fh)
    rc = p.wait(120)
    d.expect(rc == 0 and len(d.ledger("disk")) == 2, f"did not resume and finish (exit {rc})")
    ev = [e["event"] for e in S.read_jsonl(os.path.join(d.run_dir("disk"), "events.jsonl"))]
    d.expect("paused-disk" in ev and "resumed-disk" in ev, f"events {ev}")
    return "paused at the floor, resumed when it was lowered"


def d_pin_drift(d):
    """A converter source change mid-run halts the run; resuming refuses the changed pin."""
    conv = os.path.join(d.dir, "conv")
    shutil.copytree(os.path.join(S.CONVERTER_REPO, "piu_annotate"), os.path.join(conv, "piu_annotate"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    env = dict(d.env, PSF_CONVERTER_REPO=conv)
    path = d.jobs("j", [d.toyjob(f"p{i}", "sleep", 3.0) for i in range(4)])
    p = d.sup_bg("run", "drift", "--jobs", path, "--parallel", "1", env=env)
    wait_for(lambda: d.marks("start"), 60)
    with open(os.path.join(conv, "piu_annotate", "formats", "ssc_to_chartstruct.py"), "a") as fh:
        fh.write("\n# drift planted by supervise_selftest\n")
    rc = p.wait(120)
    rows = d.ledger("drift")
    d.expect(rc == 4, f"exit {rc}, expected 4 (halted)")
    d.expect(d.heartbeat("drift").get("state") == "halted", "heartbeat not halted")
    d.expect(len(rows) <= 1, f"{len(rows)} jobs recorded after the drift")
    r = d.sup("run", "drift", env=env)
    d.expect(r.returncode != 0 and "changed since this run began" in r.stderr, "resume accepted a changed converter")
    return f"halted with {len(rows)} job recorded; resume refused the new pin"


def d_detach(d):
    """--detach returns at once and the run finishes without the process that started it."""
    path = d.jobs("j", [d.toyjob(f"x{i}", "sleep", 1.5) for i in range(3)])
    t0 = time.time()
    r = d.sup("run", "bg", "--jobs", path, "--detach", "--parallel", "1")
    returned = time.time() - t0
    hb = d.heartbeat("bg")
    d.expect(r.returncode == 0 and hb.get("pid"), f"detach failed: {r.stdout}{r.stderr}")
    d.expect(returned < 20, f"--detach took {returned:.1f}s to return")
    done = wait_for(lambda: d.heartbeat("bg").get("state") == "finished", 90)
    d.expect(done and len(d.ledger("bg")) == 3, "the detached run did not finish")
    log = open(os.path.join(d.run_dir("bg"), "supervisor.log"), encoding="utf-8").read()
    d.expect(" start " in log and " end " in log, "the detached supervisor did not log its start and end")
    return f"returned in {returned:.1f}s; detached pid {hb.get('pid')} finished 3 jobs"


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
    """loopcommit commits exactly the declared paths and refuses everything else."""
    repo = new_repo(os.path.join(d.dir, "repo"))
    for f in ("a.txt", "b.txt", "d.txt", "dir/x.txt"):
        write(repo, f, f"{f} v1\n")
    write(repo, ".gitignore", "ignored/\n")
    git(repo, "add", "--", "a.txt", "b.txt", "d.txt", "dir/x.txt", ".gitignore")
    git(repo, "commit", "-q", "-m", "base", "--", "a.txt", "b.txt", "d.txt", "dir/x.txt", ".gitignore")

    def lc(*args):
        return subprocess.run(PY + [LC, *args], env=d.env, capture_output=True, text=True, encoding="utf-8",
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
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "spoof", "--body", "Loop-Run: R9", "--", "b.txt")
    d.expect(r.returncode == 2 and head() == h, "a body carrying Loop-Run was accepted")
    git(repo, "checkout", "-q", "-b", "main")
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "on main", "--", "b.txt")
    d.expect(r.returncode == 2 and "main" in r.stderr and head() == h, "committed on main")
    git(repo, "checkout", "-q", "loops/test")
    write(repo, "dir/x.txt", "x v2\n")
    write(repo, "dir/y.txt", "y v1\n")
    os.remove(os.path.join(repo, "d.txt"))
    r = lc("commit", "--repo", repo, "--run", "R1", "-m", "folder and a delete", "--", "dir", "d.txt")
    files = sorted(git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").split())
    d.expect(r.returncode == 0 and files == ["d.txt", "dir/x.txt", "dir/y.txt"], f"folder commit touched {files}: {r.stderr}")
    trailer = git(repo, "log", "-1", "--format=%(trailers:key=Loop-Run,valueonly)")
    d.expect(trailer == "R1", f"trailer {trailer!r}")
    d.expect("Co-Authored-By: Claude Opus 5.5" in git(repo, "log", "-1", "--format=%B"), "no Co-Authored-By trailer")
    return "refused: undeclared staged, unchanged, ignored, outside, spoofed trailer, main; committed exactly a file, a folder and a delete"


def d_revert_run(d):
    """revert-run reverts only this run's trailered commits after the base, newest first."""
    repo = new_repo(os.path.join(d.dir, "repo"))

    def lc(command, *args):                           # --repo before the args: everything after -- is a path
        return subprocess.run(PY + [LC, command, "--repo", repo, *args], env=d.env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=FLAGS)

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
    return "3 R1 commits reverted newest first; R2, the owner's and pre-base commits untouched; rerun no-op; conflict stops cleanly"


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


DRILLS = [("slot_limit", d_slot_limit), ("slot_two_supervisors", d_slot_two_supervisors),
          ("slot_gaming", d_slot_gaming), ("stop_run", d_stop_run), ("stop_grace_kill", d_stop_grace_kill),
          ("timeout", d_timeout), ("resume", d_resume), ("commit_lock", d_commit_lock), ("stale_lock", d_stale_lock),
          ("disk_pause", d_disk_pause), ("pin_drift", d_pin_drift), ("detach", d_detach),
          ("loopcommit", d_loopcommit), ("revert_run", d_revert_run), ("hook", d_hook), ("junction", d_junction)]


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
