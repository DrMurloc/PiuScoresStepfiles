# The only way a loop commits, and the only way a loop's commits are taken back.
#
#   loopcommit.py commit --run <run> -m "<subject>" [--body TEXT | --body-file F|-] [--repo PATH]
#                        [--lock-timeout S] [--allow-branch] -- <path> [<path> ...]
#   loopcommit.py revert-run <run> --base <sha> [--reason TEXT] [--repo PATH] [--dry-run]
#   loopcommit.py list-run <run> --base <sha> [--repo PATH]
#
# commit: takes the one machine-wide commit lock (supervise.py's work/.commit.lock), stages
# exactly the declared paths (files or folders, relative to the repository root), and refuses
# when the index already holds a staged change outside them, when a declared path has nothing
# to commit, when HEAD is detached, or when the branch is main/master (and, without
# --allow-branch, anything outside loops/*). The message gets a "Loop-Run: <run>" trailer and
# the Co-Authored-By trailer. After `git commit -F <msg> -- <paths>` it checks git's return
# code, that HEAD advanced by exactly one commit on top of the old HEAD, that the commit
# touched exactly the staged set and nothing outside the declared paths, and that the trailer
# reads back. A failed check undoes that one commit with `git reset --soft` (the changes stay
# staged) and exits 3 — it never leaves a commit it could not verify.
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
# same lines), it stops there and says so; the reverts before it stay committed.
import argparse
import os
import subprocess
import sys
import tempfile

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
        rel = os.path.relpath(full, top).replace(os.sep, "/")
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
        body = sys.stdin.read() if args.body_file == "-" else open(args.body_file, encoding="utf-8").read()
    body = body.strip()
    if any(line.strip().startswith(OUR_TRAILERS) for line in body.splitlines()):
        raise Refused(f"the body may not carry {', '.join(OUR_TRAILERS)} lines; those trailers are loopcommit's to write")
    paths = args.paths[1:] if args.paths[:1] == ["--"] else args.paths
    if not paths:
        raise Refused("declare the paths to commit after --")
    top = toplevel(args.repo)
    decl = declare(top, paths)
    branch = branch_guard(top, args.allow_branch)

    with S.commit_lock(run=run, purpose=f"loopcommit {branch}", timeout=args.lock_timeout):
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
            if new != old and g(top, "rev-parse", f"{new}^").stdout.strip() == old:
                g(top, "reset", "-q", "--soft", old)
                problems.append(f"commit {new[:10]} undone with reset --soft; its changes are still staged")
            raise Refused("post-commit check failed: " + "; ".join(problems))
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
    run = args.run
    top = toplevel(args.repo)
    branch = branch_guard(top, args.allow_branch)
    with S.commit_lock(run=run, purpose=f"revert-run {branch}", timeout=args.lock_timeout):
        base, commits, mine, reverted = run_log(top, args.base, run)
        todo = [c for c in mine if c["sha"] not in reverted]           # newest first (topo order)
        print(f"{len(mine)} commit(s) of run {run} after {base[:10]}; {len(mine) - len(todo)} already reverted; "
              f"{len(todo)} to revert; {len(commits) - len(mine)} other commit(s) left alone")
        if args.dry_run:
            for c in todo:
                print(f"  would revert {c['sha'][:10]} {c['subject']}")
            return 0
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
                       + (f"{args.reason.strip()}\n\n" if args.reason else "")
                       + f"Loop-Revert: {run}\nReverts: {sha}\n{args.co_author}\n")
            must(commit_with(top, message, files), "git commit")
            new, problems = verify_commit(top, old, files)
            if problems:
                raise Refused(f"post-commit check of the revert of {sha[:10]} failed: " + "; ".join(problems))
            done += 1
            print(f"{new[:10]} reverts {sha[:10]} {c['subject']}")
    return 0


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

    args = ap.parse_args(argv)
    try:
        return args.fn(args) or 0
    except Refused as e:
        print(f"loopcommit: refused: {e}", file=sys.stderr)
        return 3 if "post-commit" in str(e) else 2


if __name__ == "__main__":
    sys.exit(main())
