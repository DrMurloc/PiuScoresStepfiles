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
#
# --whole-block takes their entire block instead - for a fix that re-encodes the timing map,
# where no row-for-row substitution exists. Their NOTES and every timing, scroll and metadata
# tag come across; the tags that NAME the chart stay ours (DESCRIPTION, METER, DIFFICULTY,
# CHARTNAME - the chart's key and the meter the ingest matches on must not move), as do the
# mirror's own CHARTSTYLE/LASTSECONDHINT and any tag only our block carries. --new-block names
# their label when it differs from ours (a Phoenix 2 re-rate: our D25 is their D24). After
# writing, it re-reads both files with the pipeline's parser and refuses - restoring our
# bytes - unless the transplanted block's judged events and timing equal theirs exactly.
# That mode needs the piu-annotate venv.
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


KEEP = ("DESCRIPTION", "METER", "DIFFICULTY", "CHARTNAME", "CHARTSTYLE", "LASTSECONDHINT")


def set_tag(block, name, val, eol):
    """#NAME:val; replaced in place, or added after #DESCRIPTION when the block lacks it."""
    span = tag(block, name)
    if span:
        return block[:span[0]] + val + block[span[1]:]
    d = tag(block, "DESCRIPTION")
    at = block.index(";", d[1]) + 1
    return block[:at] + f"{eol}#{name}:{val};" + block[at:]


def transplant(mine, new, eol):
    """Their block, carrying our labels and whatever tags only we have."""
    out = new.replace("\r\n", "\n").replace("\r", "\n").replace("\n", eol)
    for name in dict.fromkeys(re.findall(r"#([A-Z0-9_]+):", mine)):
        if name != "NOTEDATA" and (name in KEEP or tag(out, name) is None):
            out = set_tag(out, name, value(mine, name), eol)
    return out


def same_chart(ours_path, desc, new_path, new_desc):
    """The block in our written file against theirs, through the pipeline's own parser: the
    judged events and the six converter tags must be equal. Prints the converter's totals."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, r"C:\Users\jonec\repos\piu-annotate")
    from piu_annotate.formats.sscfile import SongSSC
    import pack_census as pc

    def block(path, d):
        hits = [sc for sc in SongSSC(path, "x").stepcharts if (sc.get("DESCRIPTION") or "").strip().upper() == d.upper()]
        return hits[0] if len(hits) == 1 else sys.exit(f"{path}: {len(hits)} blocks labelled {d!r}")
    o, t = pc.info(block(ours_path, desc)), pc.info(block(new_path, new_desc))
    for label, b in (("ours now", o), ("theirs", t)):
        taps, ticks, implied, msg = pc.convert(b["sc"])
        print(f"   {label:<9} taps {taps} + ticks {ticks} = implied {implied}  ({msg})")
    return o["events"] == t["events"] and o["timing"] == t["timing"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--old")
    ap.add_argument("--block", required=True, help="the block's #DESCRIPTION, e.g. D26")
    ap.add_argument("--stepstype")
    ap.add_argument("--tags", default="", help="comma-separated tags whose changed entries to transplant")
    ap.add_argument("--new-block", help="their label for the block, when it differs from ours (default: --block)")
    ap.add_argument("--whole-block", action="store_true", help="take their whole block, keeping our labels")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    ours = read(a.ours)
    s, e = find_block(ours, a.block, a.stepstype)
    mine = ours[s:e]
    new_text = read(a.new)
    theirs = a.new_block or a.block
    ns, ne = find_block(new_text, theirs)
    new = new_text[ns:ne]
    base = mine
    if a.old:
        old_text = read(a.old)
        os_, oe = find_block(old_text, a.block)
        base = old_text[os_:oe]
        if grid(value(base, "NOTES")) != grid(value(mine, "NOTES")):
            sys.exit("REFUSED: our block's notes are not the upstream block this fix was made to - it has "
                     "diverged (a repair of ours?). Reconcile by hand with edit_notes.py.")

    if a.whole_block:
        eol = "\r\n" if "\r\n" in ours else "\n"
        patched = transplant(mine, new, eol)
        g_mine, g_new = grid(value(mine, "NOTES")), grid(value(new, "NOTES"))
        moved = sum(1 for x, y in zip(g_mine, g_new) if x != y) + abs(len(g_mine) - len(g_new))
        names = [t for t in dict.fromkeys(re.findall(r"#([A-Z0-9_]+):", patched)) if t != "NOTEDATA"]
        changed = [t for t in names if value(patched, t) != value(mine, t)]
        print(f"{a.block} <- their {theirs}: whole block; measures {len(g_mine)} -> {len(g_new)}, "
              f"{moved} differ; tags that change: {changed}")
        for t in KEEP:
            if value(mine, t) is not None and value(patched, t) != value(mine, t):
                sys.exit(f"REFUSED: #{t} did not stay ours")
        if not a.apply:
            print("dry run - pass --apply to write")
            return
        original = open(a.ours, "rb").read()
        data = (ours[:s] + patched + ours[e:]).encode("utf-8", errors="surrogateescape")
        open(a.ours, "wb").write((BOM if original[:3] == BOM else b"") + data)
        if same_chart(a.ours, a.block, a.new, theirs):
            print(f"wrote {a.ours}: the block now reads as theirs, judged event for event")
        else:
            open(a.ours, "wb").write(original)
            sys.exit("REFUSED: the transplanted block does not read as theirs - our bytes restored")
        return

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
