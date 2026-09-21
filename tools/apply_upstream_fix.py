# Transplants a fix the upstream transcribers made to ONE block of a stepfile into our copy
# of that file, touching nothing else: only the note rows that differ are rewritten, in
# place, and only the tag entries that differ are swapped. Every other byte of our file -
# the other blocks, our own repairs, line endings, the mirror's extra tags - stays as it is,
# so `git diff` shows the fix and nothing more.
#
#   python -X utf8 tools/apply_upstream_fix.py --ours <our.ssc> --new <upstream_fixed.ssc>
#          --block D26 [--old <upstream_before.ssc>] [--tags TICKCOUNTS,...] [--apply]
#
# Without --apply it only reports. With --old, our block must still equal the upstream
# block the fix was made to; if it has diverged (a repair of ours) the tool refuses rather
# than overwrite it. Without --old the difference is ours -> new, which is only right when
# our block is known to be the untouched upstream one - the report is there to be read.
#
# The substitution is positional (measure, row): it refuses a measure whose row count
# changed, because then "which row" is a judgement and belongs to edit_notes.py.
import argparse
import re
import sys


BOM = b"\xef\xbb\xbf"


def read(path):
    # surrogateescape: whatever bytes the file holds come back out unchanged
    return open(path, "rb").read().decode("utf-8-sig", errors="surrogateescape")


def blocks(text):
    """[(start, end)] character spans of each #NOTEDATA block."""
    starts = [m.start() for m in re.finditer(r"#NOTEDATA:\s*;", text)]
    return [(s, starts[i + 1] if i + 1 < len(starts) else len(text)) for i, s in enumerate(starts)]


def tag(block, name):
    """(value_start, value_end) of #NAME:...; inside a block's text, or None."""
    m = re.search(r"#" + re.escape(name) + r":(.*?);", block, re.S)
    return (m.start(1), m.end(1)) if m else None


def value(block, name):
    span = tag(block, name)
    return block[span[0]:span[1]] if span else None


def find_block(text, desc, stepstype=None):
    hits = []
    for s, e in blocks(text):
        b = text[s:e]
        d = (value(b, "DESCRIPTION") or "").strip()
        if d.upper() == desc.upper() and (stepstype is None or (value(b, "STEPSTYPE") or "").strip() == stepstype):
            hits.append((s, e))
    if len(hits) != 1:
        sys.exit(f"block {desc!r}: {len(hits)} matches (need exactly one; pass --stepstype to narrow)")
    return hits[0]


def is_row(line):
    t = line.strip()
    return bool(t) and not t.startswith(",") and not t.startswith("//")


def grid(notes):
    """[[row, ...] per measure], comments and blank lines ignored."""
    out = [[]]
    for line in notes.splitlines():
        t = line.split("//")[0].strip()
        if not t:
            continue
        if t.startswith(","):
            out.append([])
            t = t[1:].strip()
            if not t:
                continue
        out[-1].append(t)
    return out


def entries(v):
    return [x for x in re.sub(r"\s+", "", v or "").split(",") if x]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--old")
    ap.add_argument("--block", required=True, help="the block's #DESCRIPTION, e.g. D26")
    ap.add_argument("--stepstype")
    ap.add_argument("--tags", default="", help="comma-separated tags whose changed entries to transplant")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    ours = read(a.ours)
    s, e = find_block(ours, a.block, a.stepstype)
    mine = ours[s:e]
    new_text = read(a.new)
    ns, ne = find_block(new_text, a.block)
    new = new_text[ns:ne]
    base = mine
    if a.old:
        old_text = read(a.old)
        os_, oe = find_block(old_text, a.block)
        base = old_text[os_:oe]
        if grid(value(base, "NOTES")) != grid(value(mine, "NOTES")):
            sys.exit("REFUSED: our block's notes are not the upstream block this fix was made to - it has "
                     "diverged (a repair of ours?). Reconcile by hand with edit_notes.py.")

    g_base, g_new = grid(value(base, "NOTES")), grid(value(new, "NOTES"))
    if len(g_base) != len(g_new):
        sys.exit(f"REFUSED: measure count changes ({len(g_base)} -> {len(g_new)})")
    subs = {}
    for mi, (x, y) in enumerate(zip(g_base, g_new)):
        if x == y:
            continue
        if len(x) != len(y):
            sys.exit(f"REFUSED: measure {mi} changes its row count ({len(x)} -> {len(y)})")
        for ri, (p, q) in enumerate(zip(x, y)):
            if p != q:
                if len(p) != len(q):
                    sys.exit(f"REFUSED: measure {mi} row {ri} changes width ({p} -> {q})")
                subs[(mi, ri)] = (p, q)
    print(f"{a.block}: {len(subs)} note row(s) differ")
    for (mi, ri), (p, q) in sorted(subs.items()):
        beat = mi * 4 + 4 * ri / len(g_base[mi])
        print(f"   measure {mi:>3} row {ri:>3} (beat {beat:g}):  {p}  ->  {q}")

    # rewrite the rows in place, walking our block's raw NOTES text line by line
    n0, n1 = tag(mine, "NOTES")
    out, mi, ri, done = [], 0, 0, 0
    for line in mine[n0:n1].splitlines(keepends=True):
        body = line.split("//")[0]
        t = body.strip()
        if t.startswith(","):
            mi, ri = mi + 1, 0
            t = t[1:].strip()
        if t:
            if (mi, ri) in subs:
                p, q = subs[(mi, ri)]
                if t != p or line.count(p) != 1:
                    sys.exit(f"REFUSED: measure {mi} row {ri} reads {t!r} in our file, expected {p!r}")
                line = line.replace(p, q)
                done += 1
            ri += 1
        out.append(line)
    if done != len(subs):
        sys.exit(f"REFUSED: placed {done} of {len(subs)} rows")
    patched = mine[:n0] + "".join(out) + mine[n1:]

    for name in [t for t in a.tags.split(",") if t]:
        b_e, n_e = entries(value(base, name)), entries(value(new, name))
        gone, came = [x for x in b_e if x not in n_e], [x for x in n_e if x not in b_e]
        print(f"#{name}: {gone} -> {came}")
        if len(gone) != len(came):
            sys.exit(f"REFUSED: #{name} adds or removes entries; edit it by hand")
        t0, t1 = tag(patched, name)
        body = patched[t0:t1]
        for g, c in zip(gone, came):
            if body.count(g) != 1:
                sys.exit(f"REFUSED: #{name} entry {g!r} occurs {body.count(g)} times in our block")
            body = body.replace(g, c)
        patched = patched[:t0] + body + patched[t1:]

    # the result must now carry exactly the upstream notes (and the named tags' entries)
    if grid(value(patched, "NOTES")) != g_new:
        sys.exit("REFUSED: patched notes do not equal the upstream fix")
    for name in [t for t in a.tags.split(",") if t]:
        if entries(value(patched, name)) != entries(value(new, name)):
            sys.exit(f"REFUSED: patched #{name} does not equal the upstream fix")
    if not a.apply:
        print("dry run - pass --apply to write")
        return
    had_bom = open(a.ours, "rb").read(3) == BOM
    data = (ours[:s] + patched + ours[e:]).encode("utf-8", errors="surrogateescape")
    open(a.ours, "wb").write((BOM if had_bom else b"") + data)
    print(f"wrote {a.ours}")


if __name__ == "__main__":
    main()
