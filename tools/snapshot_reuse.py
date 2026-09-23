# Prepare a release folder that reuses the previous release's chartstructs and limb predictions,
# for every chart whose stepfile block has not changed since the previous snapshot's commit.
# docs/SNAPSHOT.md, "Rebuilding for a handful of charts", is the method; this does its steps 1-2
# from git instead of a hand-written list:
#
#   1. copy the previous release's chartstruct CSVs at both levels (<release>/*.csv and
#      <release>/lgbm-120524/*.csv) and the two __cs_to_manual_json.yaml files;
#   2. delete, at both levels, the CSV of every chart whose block differs from the block at the
#      previous snapshot's commit - by any byte, notes or TICKCOUNTS or timing - so ingest and
#      prediction redo exactly those, and blast_radius sees every edit move its chart.
#
# Everything else is reused; stages 4-9 of run-pipeline-union.sh then run over the whole corpus,
# and stage 4 re-derives every chart's hold ticks from its .ssc with the installed converter.
#
#   python -X utf8 tools/snapshot_reuse.py <previous snapshot commit> <previous release> <new release> [--dry-run]
#   e.g.  python -X utf8 tools/snapshot_reuse.py 8fe4b5a p2-092226 p2-092326
import csv
import json
import os
import re
import shutil
import subprocess
import sys

csv.field_size_limit(1 << 30)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS = r"C:\Users\jonec\repos\piu-annotate\artifacts\chartstructs"
LGBM = "lgbm-120524"


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def blocks(text):
    """(DESCRIPTION, SONGTYPE) -> the block sections carrying it, line endings normalized. A tag
    a block does not carry comes from the song header, as it does for the chartstruct."""
    sections = text.replace("\r\n", "\n").split("#NOTEDATA:;")
    head = sections[0]
    out = {}
    for sec in sections[1:]:
        def tag(name):
            m = re.search(r"#%s:(.*?);" % name, sec, re.S) or re.search(r"#%s:(.*?);" % name, head, re.S)
            return m.group(1).strip() if m else ""
        out.setdefault((tag("DESCRIPTION"), tag("SONGTYPE")), []).append(sec)
    return out


def changed_blocks(since):
    """{(simfiles-relative path, DESCRIPTION, SONGTYPE)} whose block differs from `since`."""
    out = set()
    for rel in git("diff", "--name-only", since, "--", "simfiles").splitlines():
        if not rel.lower().endswith(".ssc"):
            continue
        path = os.path.join(ROOT, *rel.split("/"))
        now = blocks(open(path, encoding="utf-8", errors="replace").read()) if os.path.exists(path) else {}
        was = blocks(git("show", "%s:%s" % (since, rel)))
        for key in set(now) | set(was):
            if now.get(key) != was.get(key):
                out.add((rel[len("simfiles/"):], key[0], key[1]))
    return out


def metadata(path):
    with open(path, encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        head = next(r)
        row = next(r)
    return json.loads(row[head.index("Metadata")])


def main():
    since, prev, new = sys.argv[1:4]
    dry = "--dry-run" in sys.argv
    changed = changed_blocks(since)
    print("%d block(s) changed since %s" % (len(changed), since))
    src, dst = os.path.join(CS, prev), os.path.join(CS, new)
    if not dry:
        if os.path.exists(dst):
            sys.exit("%s exists - refusing to overwrite a release folder" % dst)
        os.makedirs(os.path.join(dst, LGBM))
    n, gone, matched = 0, [], set()
    for sub in ("", LGBM):
        for f in sorted(os.listdir(os.path.join(src, sub))):
            if not (f.endswith(".csv") or f.endswith(".yaml")):
                continue
            if f.endswith(".csv"):
                meta = metadata(os.path.join(src, sub, f))
                rel = meta["ssc_file"].replace("\\", "/").split("simfiles/")[-1]
                block = (rel, meta.get("DESCRIPTION", "").strip(), meta.get("SONGTYPE", "").strip())
                if block in changed:
                    gone.append((sub, f))
                    matched.add(block)
                    continue
            if not dry:
                shutil.copy2(os.path.join(src, sub, f), os.path.join(dst, sub, f))
            n += 1
    top = sorted(f for sub, f in gone if not sub)
    print("copied %d file(s); %d chart(s) left out at both levels, for ingest and prediction to redo:" % (n, len(top)))
    for f in top:
        print("   ", f)
    lone = sorted(changed - matched)
    print("%d changed block(s) have no chart in %s (not in any charts list):" % (len(lone), prev))
    for b in lone:
        print("    %s  %s_%s" % b)


if __name__ == "__main__":
    main()
