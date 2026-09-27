# The only way a loop commits, and the only way a loop's commits are taken back.
#
#   loopcommit.py commit --run <run> -m "<subject>" [--body TEXT | --body-file F|-] [--repo PATH]
#                        [--lock-timeout S] [--allow-branch] -- <path> [<path> ...]
#   loopcommit.py revert-run <run> --base <sha> [--reason TEXT] [--repo PATH] [--dry-run]
#   loopcommit.py list-run <run> --base <sha> [--repo PATH]
#   loopcommit.py pass begin --run <run> [--repo PATH]
#   loopcommit.py pass gate  --run <run> --declared N [--workers N] [--audit-no-decode] [--repo PATH]
#   loopcommit.py pass show  --run <run>
#
# A COMMIT PASS is how a loop ships stepfile edits: `pass begin` records HEAD as the pass base in
# work/runs/<run>/pass.json; the loop commits (commit, below, one chart per commit); `pass gate`
# runs `corpus_grade.py gate --base <that base> --head <HEAD> --declared N` - which also trace-audits
# every ship - and acts on it:
#   PASS        the pass is closed (exit 0);
#   FAIL        the run is halted (work/runs/<run>/STOP, with the failures), the pass is marked failed
#               (from then on `commit` refuses for this run), and this run's Loop-Run commits after the
#               base are reverted with revert-run (exit 4; `pass show` says whether every revert applied);
#   REFUSED     (the gate's exit 2: drift, an oracle not frozen, an internal error) the run is halted,
#               nothing is reverted, and the pass stays open (exit 2);
#   RETRY LATER (the gate's exit 75, or a gate that ended with no report of this attempt) the pass
#               stays open (exit 75): the next `pass gate` gates the SAME base again.
# `pass begin` refuses while a pass is open with commits after its base: a new pass would take a
# base that already holds them, and they would never be gated. The declared count is fixed at a
# pass's first gate. Every attempt's gate output and JSON report are kept beside pass.json, and
# finished passes are appended to passes.jsonl. One pass command runs per run at a time.
#
# commit: takes the one machine-wide commit lock (supervise.py's work/.commit.lock), stages
# exactly the declared paths (files or folders, relative to the repository root), and refuses
# when the index already holds a staged change outside them, when a declared path has nothing
# to commit, when HEAD is detached, or when the branch is main/master (and, without
# --allow-branch, anything outside loops/*). The message gets a "Loop-Run: <run>" trailer and
# the Co-Authored-By trailer (a byte-order mark PowerShell put on --body-file or stdin is
# dropped). After `git commit -F <msg> -- <paths>` it checks git's return code, that HEAD
# advanced by exactly one commit on top of the old HEAD, that the commit touched exactly the
# staged set and nothing outside the declared paths, and that the trailer reads back. A failed check undoes that one commit with `git reset --soft` (the changes stay
# staged) and exits 3 — it never leaves a commit it could not verify. Before staging anything it
# checks the converter: when the run has a manifest (work/runs/<run>/manifest.json, written by
# supervise.py), the converter's source hash must equal the one the run began with, and when
# sources/oracle-manifest.json freezes a converter pin, the converter must match it (unless the
# run was started --converter-unpinned) — the loop-bucket rule that the pin is checked at every
# commit pass. A mismatch refuses the commit and reverts nothing.
#
# Exit codes: 0 committed (a pass: begun, passed, shown); 2 refused (nothing was committed: a
# refusal above, the run's last pass gate failed, the commit lock not taken within --lock-timeout
# (time this process was awake: a supervisor freezing the job while it waits does not use it up),
# a path outside the repository or on another drive; for `pass gate` also the gate refusing, which
# halts the run); 3 a post-commit check failed and the commit was undone (its changes left
# staged); 4 `pass gate` FAILED (run halted, its commits after the base reverted); 75 `pass gate`
# not judged - retry later, the pass stays open (supervise.py defers a loopcommit.py job on 75 by
# default); 1 an unexpected error, with a traceback.
#
# Why: the loops' earlier commit code (extract_repair.py, tick_repair.py) ran a bare
# `git commit` without a pathspec and ignored its return code, in a checkout several loops
# could share. Anything another process had staged went into the chart's commit, and a failed
# commit looked like a success.
#
# revert-run: reverts only the commits between --base and HEAD whose Loop-Run trailer names
# <run>, newest first, stopping at the base and never touching any other commit (another run's,
# the owner's, a merge). Each revert applies the commit's own reversed binary diff to the index
# (`git apply --index -R`, which applies all of it or nothing) and commits it with
# "Loop-Revert: <run>" and "Reverts: <sha>" trailers. It deliberately does NOT carry Loop-Run:
# otherwise a second revert-run would revert the reverts. Commits already reverted are skipped,
# so running it twice is a no-op. If a reversal no longer applies (a later commit rewrote the
# same lines), it stops there and says so; the reverts before it stay committed. A revert commit
# that fails its post-commit check is undone with `git reset --soft` like any other (exit 3, the
# reversal left staged for inspection).
import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import supervise as S  # noqa: E402

CO_AUTHOR = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
OUR_TRAILERS = ("Loop-Run:", "Loop-Revert:", "Reverts:")


class Refused(Exception):
    pass


def g(repo, *args, data=None, binary=False):
    kw = {} if binary else dict(text=True, encoding="utf-8", errors="replace")
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, input=data, creationflags=S.QUIET, **kw)


def must(r, what):
    if r.returncode != 0:
        err = r.stderr if isinstance(r.stderr, str) else r.stderr.decode("utf-8", "replace")
        raise Refused(f"{what} failed (git exit {r.returncode}): {err.strip()}")
    return r.stdout.strip() if isinstance(r.stdout, str) else r.stdout


def names(repo, *args):
    out = must(g(repo, *args, "-z"), "git " + " ".join(args[:2]))
    return [p for p in out.split("\0") if p]


def staged(repo):
    return names(repo, "diff", "--cached", "--name-only", "--no-renames")


def touched(repo, sha):
    return names(repo, "diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", sha)


def toplevel(repo):
    return os.path.normpath(must(g(repo, "rev-parse", "--show-toplevel"), "git rev-parse --show-toplevel"))


def head(repo):
    return must(g(repo, "rev-parse", "HEAD"), "git rev-parse HEAD")


def branch_guard(top, allow_branch):
    r = g(top, "symbolic-ref", "--quiet", "--short", "HEAD")
    if r.returncode != 0:
        raise Refused("HEAD is detached; loops commit on a loops/* branch")
    branch = r.stdout.strip()
    if branch in ("main", "master"):
        raise Refused(f"refusing to commit on {branch}: loops commit only on their own loops/* branch")
    if not branch.startswith("loops/") and not allow_branch:
        raise Refused(f"refusing to commit on {branch}: not a loops/* branch (--allow-branch overrides)")
    return branch


def declare(top, paths):
    out = []
    for p in paths:
        full = os.path.normpath(p if os.path.isabs(p) else os.path.join(top, p))
        try:
            rel = os.path.relpath(full, top).replace(os.sep, "/")
        except ValueError:                             # another drive: relpath cannot even express it
            raise Refused(f"{p!r} is not a path inside the repository (it is on another drive)")
        if rel == "." or rel.startswith("../") or rel == "..":
            raise Refused(f"{p!r} is not a path inside the repository (the whole tree is never a declared path)")
        out.append(rel.rstrip("/"))
    return sorted(set(out))


def covered(path, decl):
    return any(path == d or path.startswith(d + "/") for d in decl)


def commit_with(top, message, pathspec):
    fd, msgfile = tempfile.mkstemp(prefix="loopcommit-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(message)
        # "whitespace", not "strip": a stepfile commit body starts lines with #TICKCOUNTS or
        # #NOTEDATA, and strip would silently delete them as comments
        return g(top, "commit", "-q", "--cleanup=whitespace", "-F", msgfile, "--", *pathspec)
    finally:
        os.remove(msgfile)


def pin_problems(run):
    """Why the converter may not be committed under right now (empty when it may)."""
    conv = S.pins()["converter"] or {}
    pkg = S.converter_dir()
    manifest = S.read_json(os.path.join(S.RUNS, run, "manifest.json"))
    manifest = manifest if manifest and "_unreadable" not in manifest else None
    problems = []
    if manifest:
        began = ((manifest.get("pins") or {}).get("converter") or {}).get("py_sha256")
        if began and began != conv.get("py_sha256"):
            problems.append(f"the converter changed since run {run} began (source hash {began[:12]} -> "
                            f"{str(conv.get('py_sha256'))[:12]})")
    unpinned = bool(manifest) and any(a.get("converter_unpinned") for a in manifest.get("attempts", []))
    fz = S.frozen_converter_pin(pkg) if pkg else {"ok": False, "why": "no piu_annotate converter found"}
    if not fz["ok"] and not unpinned:
        problems.append(fz["why"])
    return problems


def undo(top, old, new, problems):
    """Take back a commit that failed its post-commit check, if it sits directly on the old HEAD."""
    if new != old and g(top, "rev-parse", f"{new}^").stdout.strip() == old:
        r = g(top, "reset", "-q", "--soft", old)
        problems.append(f"commit {new[:10]} undone with reset --soft; its changes are still staged" if r.returncode == 0
                        else f"commit {new[:10]} could NOT be undone (git reset exit {r.returncode}): {r.stderr.strip()}")
    return problems


def verify_commit(top, old, expected_files, allowed=None):
    new = head(top)
    problems = []
    if new == old:
        problems.append("HEAD did not advance")
    else:
        parent = g(top, "rev-parse", f"{new}^").stdout.strip()
        if parent != old:
            problems.append(f"HEAD's parent is {parent[:10]}, not the old HEAD {old[:10]}")
        files = set(touched(top, new))
        if files != set(expected_files):
            problems.append(f"the commit touched {sorted(files)}, expected {sorted(expected_files)}")
        if allowed is not None and any(not covered(f, allowed) for f in files):
            problems.append(f"the commit touched undeclared paths {sorted(f for f in files if not covered(f, allowed))}")
    return new, problems


def cmd_commit(args):
    run = args.run
    if not S.RUN_ID.match(run):
        raise Refused(f"run id {run!r}: letters, digits, '.', '_' and '-' only")
    subject = args.message.strip()
    if not subject or "\n" in subject:
        raise Refused("-m takes a one-line subject; the body goes in --body or --body-file")
    body = args.body or ""
    if args.body_file:
        body = sys.stdin.read() if args.body_file == "-" else open(args.body_file, encoding="utf-8-sig").read()
    body = body.lstrip("\ufeff").strip()               # PowerShell 5.1 writes a BOM into files and native stdin
    if any(line.strip().startswith(OUR_TRAILERS) for line in body.splitlines()):
        raise Refused(f"the body may not carry {', '.join(OUR_TRAILERS)} lines; those trailers are loopcommit's to write")
    paths = args.paths[1:] if args.paths[:1] == ["--"] else args.paths
    if not paths:
        raise Refused("declare the paths to commit after --")
    top = toplevel(args.repo)
    decl = declare(top, paths)
    branch = branch_guard(top, args.allow_branch)

    with S.commit_lock(run=run, purpose=f"loopcommit {branch}", timeout=args.lock_timeout):
        halted = pass_halted(run)                       # read under the lock a failing gate reverts under
        if halted:
            raise Refused(halted)
        pins_wrong = pin_problems(run)
        if pins_wrong:
            raise Refused("; ".join(pins_wrong) + ". A converter mismatch halts the loop; nothing was committed or reverted")
        old = head(top)
        outside = [p for p in staged(top) if not covered(p, decl)]
        if outside:
            raise Refused(f"the index already holds staged changes outside the declared paths: {outside[:10]}"
                          f"{' ...' if len(outside) > 10 else ''}; unstage them or declare them")
        added = g(top, "add", "--", *decl)
        if added.returncode != 0:                      # e.g. an ignored path: stage nothing of it
            g(top, "reset", "-q", "--", *decl)
            must(added, "git add")
        now = staged(top)
        outside = [p for p in now if not covered(p, decl)]
        idle = [d for d in decl if not any(covered(p, [d]) for p in now)]
        if outside or idle:
            g(top, "reset", "-q", "--", *decl)
            raise Refused((f"staging reached undeclared paths {outside}; " if outside else "")
                          + (f"declared paths with nothing to commit: {idle}" if idle else ""))
        message = f"{subject}\n\n" + (f"{body}\n\n" if body else "") + f"Loop-Run: {run}\n{args.co_author}\n"
        must(commit_with(top, message, decl), "git commit")
        new, problems = verify_commit(top, old, now, decl)
        if not problems:
            back = g(top, "log", "-1", "--format=%(trailers:key=Loop-Run,valueonly)", new).stdout.strip()
            if back != run:
                problems.append(f"the Loop-Run trailer reads back as {back!r}")
        if problems:
            raise Refused("post-commit check failed: " + "; ".join(undo(top, old, new, problems)))
    print(f"{new[:10]} {subject}  [{len(now)} file(s); Loop-Run: {run}]")
    return 0


def run_log(top, base, run):
    if g(top, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        raise Refused(f"--base {base!r} is not a commit")
    base = g(top, "rev-parse", f"{base}^{{commit}}").stdout.strip()
    if g(top, "merge-base", "--is-ancestor", base, "HEAD").returncode != 0:
        raise Refused(f"--base {base[:10]} is not an ancestor of HEAD")
    fmt = "%H%x01%P%x01%s%x01" + "%x01".join(f"%(trailers:key={k},valueonly,separator=%x02)"
                                              for k in ("Loop-Run", "Loop-Revert", "Reverts"))
    out = must(g(top, "log", "--topo-order", f"--format={fmt}%x00", f"{base}..HEAD"), "git log")
    commits = []
    for rec in out.split("\0"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, parents, subject, lr, lrev, revs = rec.split("\x01")
        split = lambda v: [x.strip() for x in v.split("\x02") if x.strip()]    # noqa: E731
        commits.append({"sha": sha, "parents": parents.split(), "subject": subject,
                        "loop_run": split(lr), "loop_revert": split(lrev), "reverts": split(revs)})
    mine = [c for c in commits if c["loop_run"] == [run]]
    reverted = {s for c in commits if run in c["loop_revert"] for s in c["reverts"]}
    return base, commits, mine, reverted


def cmd_list_run(args):
    top = toplevel(args.repo)
    base, commits, mine, reverted = run_log(top, args.base, args.run)
    print(f"{len(commits)} commits after {base[:10]}; {len(mine)} carry Loop-Run: {args.run}")
    for c in mine:
        print(f"  {c['sha'][:10]} {'(reverted) ' if c['sha'] in reverted else ''}{c['subject']}")
    return 0


def cmd_revert_run(args):
    top = toplevel(args.repo)
    branch = branch_guard(top, args.allow_branch)
    revert_run(top, args.run, args.base, branch, args.reason, args.lock_timeout, args.co_author, dry_run=args.dry_run)
    return 0


def revert_run(top, run, base_arg, branch, reason, lock_timeout, co_author, dry_run=False):
    """revert-run's work (also a failed pass gate's): -> (reverted now, the run's commits after the
    base). Raises Refused where revert-run refuses, with the reverts before it committed."""
    with S.commit_lock(run=run, purpose=f"revert-run {branch}", timeout=lock_timeout):
        base, commits, mine, reverted = run_log(top, base_arg, run)
        todo = [c for c in mine if c["sha"] not in reverted]           # newest first (topo order)
        print(f"{len(mine)} commit(s) of run {run} after {base[:10]}; {len(mine) - len(todo)} already reverted; "
              f"{len(todo)} to revert; {len(commits) - len(mine)} other commit(s) left alone")
        if dry_run:
            for c in todo:
                print(f"  would revert {c['sha'][:10]} {c['subject']}")
            return 0, mine
        if staged(top):
            raise Refused("the index holds staged changes; revert-run starts from a clean index")
        done = 0
        for c in todo:
            sha = c["sha"]
            if len(c["parents"]) != 1:
                raise Refused(f"{sha[:10]} is a merge commit; revert-run does not revert merges")
            files = touched(top, sha)
            dirty = g(top, "status", "--porcelain", "--untracked-files=all", "--", *files).stdout.strip()
            if dirty:
                raise Refused(f"uncommitted changes on files {sha[:10]} touched:\n{dirty}\n({done} revert(s) committed)")
            patch = must(g(top, "diff", "--binary", "--no-renames", "--full-index", f"{sha}^", sha, binary=True), "git diff")
            r = g(top, "apply", "--index", "-R", "--whitespace=nowarn", data=patch, binary=True)
            if r.returncode != 0:
                raise Refused(f"the reversal of {sha[:10]} ({c['subject']}) no longer applies — a later commit changed "
                              f"the same lines. Nothing of it was applied; {done} revert(s) before it are committed.\n"
                              + r.stderr.decode("utf-8", "replace").strip())
            now = staged(top)
            if set(now) != set(files):
                raise Refused(f"reversing {sha[:10]} staged {sorted(now)}, expected {sorted(files)}; left staged for inspection")
            old = head(top)
            message = (f'Revert "{c["subject"]}"\n\nThis reverts commit {sha}, a Loop-Run: {run} commit.\n\n'
                       + (f"{reason.strip()}\n\n" if reason else "")
                       + f"Loop-Revert: {run}\nReverts: {sha}\n{co_author}\n")
            must(commit_with(top, message, files), "git commit")
            new, problems = verify_commit(top, old, files)
            if problems:
                raise Refused(f"post-commit check of the revert of {sha[:10]} failed: " + "; ".join(undo(top, old, new, problems))
                              + f"; left staged for inspection ({done} revert(s) before it are committed)")
            done += 1
            print(f"{new[:10]} reverts {sha[:10]} {c['subject']}")
    return done, mine


# ---------------------------------------------------------------- commit passes

PASS_FILE, PASS_HISTORY = "pass.json", "passes.jsonl"
PASS_FAILED = 4                      # the gate failed: the run's commits after the base reverted, the run halted
TEMPFAIL = S.TEMPFAIL                # 75: not judged (the machine stopped the gate); the pass stays open


def check_run(run):
    if not S.RUN_ID.match(run):
        raise Refused(f"run id {run!r}: letters, digits, '.', '_' and '-' only")
    return run


def pass_paths(run):
    rdir = os.path.join(S.RUNS, run)
    return rdir, os.path.join(rdir, PASS_FILE), os.path.join(rdir, PASS_HISTORY)


def read_pass(path):
    cur = S.read_json(path)
    if cur is not None and "_unreadable" in cur:
        raise Refused(f"{path} does not read ({cur['_unreadable']}); a pass record is never guessed at - "
                      "repair or remove it by hand")
    return cur


@contextlib.contextmanager
def pass_lock(run, timeout):
    """One pass command per run at a time (a begin racing a gate would re-base the gate's pass)."""
    lock = S.PidLock(os.path.join(S.RUNS, run, "pass.lock"), f"pass lock of {run}")
    lock.acquire(timeout=timeout, run=run, purpose="loopcommit pass")
    try:
        yield
    finally:
        lock.release()


def pass_halted(run):
    """Why this run may not commit (its last pass gate failed and reverted it), or None."""
    cur = read_pass(pass_paths(run)[1])
    if cur and cur.get("state") == "failed":
        return (f"run {run}'s pass gate failed ({str(cur.get('base'))[:10]}..{str(cur.get('head'))[:10]}, "
                f"{cur.get('closed')}): the run is halted and its commits after the base were reverted; nothing "
                f"commits for it until the owner clears its STOP and a new pass begins")
    return None


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def cmd_pass_begin(args):
    run = check_run(args.run)
    top = toplevel(args.repo)
    branch = branch_guard(top, args.allow_branch)
    rdir, pfile, _ = pass_paths(run)
    os.makedirs(rdir, exist_ok=True)
    with pass_lock(run, args.lock_timeout):
        cur = read_pass(pfile)
        tip = head(top)
        if cur and cur.get("state") == "open":
            if cur.get("base") == tip and not cur.get("gates") and cur.get("branch") == branch and same_path(cur.get("repo", ""), top):
                print(f"pass already open for run {run} at {tip[:10]} with nothing committed since: it is this pass")
                return 0
            raise Refused(f"run {run} has an open pass from base {str(cur.get('base'))[:10]} ({cur.get('began')}) that "
                          f"is not gated yet: gate it (`loopcommit.py pass gate --run {run} --declared N`). A new pass "
                          "would take a base that already holds its commits, and they would never be gated")
        src = S.stop_reason(run)
        if src:
            raise Refused(f"{src} is present: no pass begins while the run is stopped or halted (clearing it is the owner's call)")
        rec = dict(run=run, state="open", base=tip, branch=branch, repo=top, began=S.now_iso(), gates=[])
        S.write_json(pfile, rec)
    print(f"pass open for run {run}: base {tip} on {branch}")
    return 0


def cmd_pass_show(args):
    cur = read_pass(pass_paths(check_run(args.run))[1])
    print(json.dumps(cur or {}, indent=1, sort_keys=True, ensure_ascii=False))
    return 0


def cmd_pass_gate(args):
    run = check_run(args.run)
    top = toplevel(args.repo)
    branch = branch_guard(top, args.allow_branch)
    rdir, pfile, hist = pass_paths(run)
    with pass_lock(run, args.lock_timeout):
        cur = read_pass(pfile)
        if not cur or cur.get("state") != "open":
            raise Refused(f"run {run} has no open pass ({'its last pass ' + str(cur.get('state')) if cur else 'none was begun'}): "
                          f"`loopcommit.py pass begin --run {run}` takes the base before a pass commits")
        if cur.get("branch") != branch or not same_path(cur.get("repo", ""), top):
            raise Refused(f"run {run}'s open pass was begun in {cur.get('repo')} on {cur.get('branch')}, not {top} on {branch}")
        base = cur["base"]
        if g(top, "merge-base", "--is-ancestor", base, "HEAD").returncode != 0:
            raise Refused(f"the pass base {base[:10]} is no longer an ancestor of HEAD (the branch was rewritten); nothing gated")
        if cur.get("declared") is not None and cur["declared"] != args.declared:
            raise Refused(f"this pass declared {cur['declared']:+d} at its first gate, and a retry gates the same claim "
                          f"(--declared {cur['declared']})")
        cur["declared"] = args.declared
        tip = head(top)
        n = len(cur.get("gates") or []) + 1
        stem = os.path.join(rdir, f"pass-{base[:10]}-gate{n}")
        report, logf = stem + ".json", stem + ".log"
        with contextlib.suppress(FileNotFoundError):
            os.remove(report)                          # only this attempt's report is believed
        cmd = S.PY + [os.path.join(top, "tools", "corpus_grade.py"), "gate", "--base", base, "--head", tip,
                      "--declared", str(args.declared), "--json", report]
        if args.audit_no_decode:
            cmd.append("--audit-no-decode")
        if args.workers:
            cmd += ["--workers", str(args.workers)]
        t0 = time.time()
        r = subprocess.run(cmd, cwd=top, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=S.QUIET)
        S.write_atomic(logf, r.stdout + (f"\n--- stderr ---\n{r.stderr}" if r.stderr.strip() else ""))
        sys.stdout.write(r.stdout)
        sys.stdout.flush()
        rep = S.read_json(report)
        fresh = bool(rep) and "_unreadable" not in rep and rep.get("base") == base and rep.get("head") == tip
        verdict = rep.get("verdict") if fresh else None
        cur.setdefault("gates", []).append(dict(n=n, at=S.now_iso(), head=tip, exit=r.returncode, verdict=verdict,
                                                report=report, log=logf, seconds=round(time.time() - t0, 1)))
        if r.returncode == 0 and verdict == "PASS":
            cur.update(state="passed", closed=S.now_iso(), head=tip, net=rep.get("net"))
            S.write_json(pfile, cur)
            S.append_jsonl(hist, cur)
            print(f"pass PASSED: run {run}, {base[:10]}..{tip[:10]}, net {rep.get('net'):+d} as declared")
            return 0
        if r.returncode == 1 and verdict == "FAIL":
            why = "; ".join(rep.get("failures") or [])
            # halt first (no new job starts, and no job of the run commits once the state says failed),
            # then take back this run's commits after the base
            S.write_json(os.path.join(rdir, "STOP"), {"at": S.now_iso(), "by_pid": os.getpid(), "reason":
                         f"loopcommit pass gate FAILED ({base[:10]}..{tip[:10]}), this run's commits after the base "
                         f"reverted: {why[:1500]}"})
            cur.update(state="failed", closed=S.now_iso(), head=tip, failures=rep.get("failures"), revert="pending")
            S.write_json(pfile, cur)
            try:
                done, mine = revert_run(top, run, base, branch, f"The pass gate failed: {why[:800]}", args.lock_timeout,
                                        args.co_author)
                files = sorted({f for c in mine for f in touched(top, c["sha"])})
                left = [p for p in must(g(top, "diff", "--name-only", "-z", "--no-renames", base, "HEAD", "--", *files),
                                        "git diff").split("\0") if p] if files else []
                cur["revert"] = dict(ok=True, reverted=done, commits=len(mine), still_differ_from_base=left)
                tail = (f"{done} commit(s) reverted" + (f"; {len(left)} of their file(s) still differ from the base "
                                                        f"(another commit touched them): {left[:10]}" if left else ""))
            except (Refused, TimeoutError) as e:
                cur["revert"] = dict(ok=False, error=str(e))
                tail = f"the revert did NOT complete: {e}"
            S.write_json(pfile, cur)
            S.append_jsonl(hist, cur)
            print(f"pass FAILED: run {run} halted (its STOP is written); {tail}", file=sys.stderr)
            return PASS_FAILED
        if r.returncode == 2:
            refusal = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("REFUSED")), r.stdout.strip()[-300:])
            S.write_json(os.path.join(rdir, "STOP"), {"at": S.now_iso(), "by_pid": os.getpid(), "reason":
                         f"loopcommit pass gate: the gate refused ({refusal[:600]}); nothing reverted, the pass at base "
                         f"{base[:10]} stays open - once fixed, clear this STOP and gate the same base again"})
            S.write_json(pfile, cur)
            print(f"pass NOT JUDGED and the run halted: the gate refused ({refusal[:300]}); nothing reverted, the pass "
                  f"stays open at base {base[:10]}", file=sys.stderr)
            return 2
        # 75, or an exit with no report of this attempt to believe (a gate killed mid-run): not judged
        S.write_json(pfile, cur)
        print(f"pass NOT JUDGED (gate exit {r.returncode}{'' if verdict else ', no report from this attempt'}): the pass "
              f"stays open at base {base[:10]}; gate it again (`loopcommit.py pass gate --run {run} --declared "
              f"{args.declared}`), never begin a new pass over it", file=sys.stderr)
        return TEMPFAIL


def main(argv=None):
    ap = argparse.ArgumentParser(description="Commit (and revert) a loop's work under the commit lock.")
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--repo", default=S.ROOT, help="repository (worktree) to act in; default: this tool's own")
        p.add_argument("--lock-timeout", type=float, default=1800, help="seconds to wait for the commit lock")
        p.add_argument("--allow-branch", action="store_true", help="allow a branch outside loops/* (never main)")
        p.add_argument("--co-author", default=CO_AUTHOR)

    p = sub.add_parser("commit")
    p.add_argument("--run", required=True)
    p.add_argument("-m", "--message", required=True, help="one-line subject")
    p.add_argument("--body")
    p.add_argument("--body-file")
    p.add_argument("paths", nargs=argparse.REMAINDER)
    common(p)
    p.set_defaults(fn=cmd_commit)

    p = sub.add_parser("revert-run")
    p.add_argument("run")
    p.add_argument("--base", required=True)
    p.add_argument("--reason")
    p.add_argument("--dry-run", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_revert_run)

    p = sub.add_parser("list-run")
    p.add_argument("run")
    p.add_argument("--base", required=True)
    common(p)
    p.set_defaults(fn=cmd_list_run)

    p = sub.add_parser("pass", help="a commit pass: begin (take the base), gate (grade, audit, revert on FAIL), show")
    psub = p.add_subparsers(dest="pass_command", required=True)
    q = psub.add_parser("begin")
    q.add_argument("--run", required=True)
    common(q)
    q.set_defaults(fn=cmd_pass_begin)
    q = psub.add_parser("gate")
    q.add_argument("--run", required=True)
    q.add_argument("--declared", type=int, required=True, help="the net exact charts this pass ships")
    q.add_argument("--workers", type=int, help="the grade's worker processes (its default is 6)")
    q.add_argument("--audit-no-decode", action="store_true", help="passed on to the gate")
    common(q)
    q.set_defaults(fn=cmd_pass_gate)
    q = psub.add_parser("show")
    q.add_argument("--run", required=True)
    common(q)
    q.set_defaults(fn=cmd_pass_show)

    args = ap.parse_args(argv)
    try:
        return args.fn(args) or 0
    except Refused as e:
        print(f"loopcommit: refused: {e}", file=sys.stderr)
        return 3 if "post-commit" in str(e) else 2
    except TimeoutError as e:                          # the commit lock (or its mutex) was not taken in time
        print(f"loopcommit: refused: {e}; nothing was committed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
