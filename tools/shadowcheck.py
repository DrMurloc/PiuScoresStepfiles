# Refuses to run the rails while anything under tools/ would answer to the name of a real module.
#
# Python puts a script's own folder first on sys.path, and the rails insert tools/ at the front
# again, so a tools/<name>.py named after a library the gate imports (directly or transitively:
# tempfile, logging, tqdm, win32_setctime...) is loaded in the library's place, inside the very
# process that judges a pass. A helper that happens to carry such a name would crash the gate at
# best; a shadow that re-exports the real module could rewrite a FAIL into a PASS.
#
# guard() lists every top-level importable entry under tools/ (NAME.py, NAME.pyc, NAME.pyd and the
# other import suffixes, and NAME/ folders with an __init__), then asks a clean, isolated
# interpreter (python -I: no script folder, no PYTHON* environment, no user site) which of those
# names it can import without tools/. Any it can is a shadow, and the calling script exits before
# it imports anything else. A name collision under tools/ is never legitimate, so there is no
# allowlist.
#
# Call it FIRST in every rails entry point, before any other import:
#     import os, sys                        # both are loaded before the script's folder is on the path
#     sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
#     import shadowcheck; shadowcheck.guard("corpus_grade", exit_code=2)
# This module imports only os and sys at module level for the same reason; everything else it needs
# is imported while tools/ is off sys.path.
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
_CHECKED = set()                    # tools dirs already checked in this process

_CHILD = r"""
import importlib.util, json, sys
out = []
for n in json.loads(sys.stdin.read()):
    if n in sys.stdlib_module_names or n in sys.builtin_module_names:
        out.append([n, "stdlib"])
        continue
    try:
        spec = importlib.util.find_spec(n)
    except Exception:
        spec = None
    if spec is not None:
        out.append([n, spec.origin or "namespace package"])
print(json.dumps(out))
"""


def _norm(p):
    return os.path.normcase(os.path.abspath(p or os.curdir))


def importable_names(tools_dir=TOOLS, suffixes=None):
    """Every top-level name an import would find in tools_dir (module files and regular packages)."""
    suffixes = sorted(suffixes or [], key=len, reverse=True)
    names = set()
    for entry in os.listdir(tools_dir):
        path = os.path.join(tools_dir, entry)
        if os.path.isdir(path):
            if entry.isidentifier() and os.path.isfile(os.path.join(path, "__init__.py")):
                names.add(entry)
            continue
        for suf in suffixes:
            if entry.endswith(suf):
                stem = entry[: -len(suf)]
                if stem.isidentifier():
                    names.add(stem)
                break
    return sorted(names)


def shadows(tools_dir=TOOLS):
    """[(name, what it shadows)] for names under tools_dir that a clean interpreter imports elsewhere."""
    saved = list(sys.path)
    here = _norm(tools_dir)
    sys.path[:] = [p for p in sys.path if _norm(p) != here]
    try:
        import importlib.machinery
        import json
        import subprocess
        import tempfile
        names = importable_names(tools_dir, importlib.machinery.all_suffixes())
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.run([sys.executable, "-I", "-c", _CHILD], input=json.dumps(names),
                                  capture_output=True, text=True, cwd=cwd, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError("the clean interpreter failed: " + (proc.stderr or proc.stdout).strip()[-400:])
        return [tuple(x) for x in json.loads(proc.stdout)]
    finally:
        sys.path[:] = saved


def guard(tool, exit_code=2, tools_dir=TOOLS):
    """Exit with exit_code, naming every shadow, if tools_dir holds one; otherwise return quietly."""
    if _norm(tools_dir) in _CHECKED:
        return
    try:
        found = shadows(tools_dir)
    except Exception as exc:  # cannot tell: refuse rather than judge with an unknown tools/ tree
        print("REFUSED: %s cannot check tools/ for shadowed module names: %s" % (tool, exc), flush=True)
        sys.exit(exit_code)
    if found:
        print("REFUSED: %s will not run while tools/ shadows a real module - remove or rename: %s" % (
            tool, "; ".join("tools/%s (would replace %s)" % (n, w) for n, w in found)), flush=True)
        sys.exit(exit_code)
    _CHECKED.add(_norm(tools_dir))
