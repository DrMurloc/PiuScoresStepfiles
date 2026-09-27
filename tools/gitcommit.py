# A commit that proves it happened, and happened to exactly the files it names.
#
# The loops' commit passes used to run `git add <file>` and then a bare `git commit` and read
# `git rev-parse HEAD` afterwards, with no return code looked at anywhere. A commit git refused
# (a hook, a lock left by another process, nothing staged) went unnoticed and the report recorded
# whatever HEAD happened to be as that chart's commit; a bare `git commit` also takes along
# anything else that was staged in the checkout at the time, by anyone.
#
# commit_exactly() commits with a pathspec (`git commit -- <paths>` takes those paths' content and
# nothing else from the index), then checks that git returned 0, that HEAD moved by exactly one
# commit on top of the HEAD it started from, and that the new commit touches exactly the declared
# paths. Anything else raises CommitError, and the caller stops its pass - except NothingToCommit:
# the declared paths already match HEAD (the candidate landed another way), which a caller skips.
# Pathspecs are literal (GIT_LITERAL_PATHSPECS): a song folder named with [..] or * is a name,
# never a glob that could match a sibling.
import os
import subprocess


class CommitError(RuntimeError):
    pass


class NothingToCommit(CommitError):
    pass


def _env():
    return dict(os.environ, GIT_LITERAL_PATHSPECS="1")


def git(root, *args, input=None):
    """git's stdout; CommitError when it exits non-zero."""
    p = subprocess.run(["git"] + list(args), cwd=root, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", input=input, env=_env())
    if p.returncode:
        raise CommitError("`git %s` exited %d: %s" % (" ".join(args[:4]), p.returncode, (p.stderr or p.stdout).strip()[:400]))
    return p.stdout


def rel(root, path):
    p = path if os.path.isabs(path) else os.path.join(root, path)
    return os.path.relpath(os.path.abspath(p), os.path.abspath(root)).replace(os.sep, "/")


def commit_exactly(root, paths, message):
    """Commit `paths` (absolute, or relative to root) with `message`; return the new short sha.
    Raises CommitError unless git returned 0, HEAD advanced by one commit onto the HEAD it started
    from, and that commit touches exactly `paths`."""
    declared = sorted({rel(root, p) for p in paths})
    before = git(root, "rev-parse", "HEAD").strip()
    git(root, "add", "--", *declared)
    same = subprocess.run(["git", "diff", "--cached", "--quiet", "HEAD", "--", *declared], cwd=root,
                          capture_output=True, env=_env())
    if same.returncode == 0:
        raise NothingToCommit("%s already match HEAD %s: nothing to commit" % (", ".join(declared), before[:10]))
    if same.returncode != 1:
        raise CommitError("`git diff --cached --quiet HEAD` exited %d: %s" % (same.returncode, same.stderr.decode("utf-8", "replace")[:300]))
    git(root, "commit", "-q", "-F", "-", "--", *declared, input=message)
    after = git(root, "rev-parse", "HEAD").strip()
    if after == before:
        raise CommitError("git commit returned 0 but HEAD is still %s" % before[:10])
    parent = git(root, "rev-parse", after + "^").strip()
    if parent != before:
        raise CommitError("HEAD moved from %s to %s, which is not one commit on top of it (parent %s) - "
                          "something else committed in this checkout meanwhile" % (before[:10], after[:10], parent[:10]))
    touched = sorted(x for x in git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", after).split("\0") if x)
    if sorted(os.path.normcase(x) for x in touched) != sorted(os.path.normcase(x) for x in declared):
        raise CommitError("commit %s touched %s; declared %s" % (after[:10], touched, declared))
    return git(root, "rev-parse", "--short", after).strip()
