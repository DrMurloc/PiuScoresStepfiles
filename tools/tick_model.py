# The hold-tick count as the game judges it, against the converter's old arithmetic, tested on
# what the combo counter measured. The old converter (piu_annotate ssc_to_chartstruct,
# hold_ticks="legacy") accrues rate x beats over each hold segment, rounds it, adds a tick on
# every release row that starts no hold and takes one off for every tap row inside a hold. The
# game judges the TICK LATTICE: a hold's head row is one judged event (a tap row already is one),
# and then every lattice point - a multiple of 1/rate on the beat grid - that falls after a head
# and up to a release, with any hold held across it, is one judged event however many holds are
# held, unless a tap or head row sits on that point, in which case that row is the event. Two
# consequences the old arithmetic gets wrong: a release while another hold stays held earns it a
# second tick (docs/EVIDENCE-RULES.md, "A staggered release is not a tick"), and an interior it
# rounds up the lattice counts whole.
#
# Since 2026-09-23 the converter itself counts by the lattice (HOLD_TICK_MODEL = "lattice" in the
# piuscores-windows-port branch of piu-annotate). This file keeps an independent implementation
# of the same model on the converter's own rows, which is what the converter was checked against.
#
#   python -X utf8 tools/tick_model.py test                    every priced cluster of the tick loop's reports
#   python -X utf8 tools/tick_model.py census [--shard i/n]    every certified chart: exact under which arithmetic
import glob
import json
import os
import sys
from collections import Counter
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_repair as E   # noqa: E402
import tick_repair as T      # noqa: E402
from piu_annotate.formats import ssc_to_chartstruct as C          # noqa: E402
from piu_annotate.formats.sscfile import StepchartSSC             # noqa: E402

ROOT = E.ROOT


def snap(b):
    """An exact beat (the converter's own rule: the nearest fraction with a small denominator)."""
    return Fraction(b).limit_denominator(10000)


def holds_of(rows, ncols):
    """Every hold as (head beat, tail beat, column), from the converter's own rows."""
    out, open_ = [], {}
    for r in rows:
        b = snap(r["b"])
        for c, ch in enumerate(r["line"][:ncols]):
            if ch == "2":
                open_[c] = b
            elif ch == "3" and c in open_:
                out.append((open_.pop(c), b, c))
    return out


def lattice(sched, b0, b1):
    """The lattice points in (b0, b1]: multiples of 1/rate, the rate in effect at the point."""
    pts = set()
    entries = sorted((snap(b), Fraction(r).limit_denominator(64)) for b, r in sched)
    if not entries or entries[0][0] > 0:
        entries = [(Fraction(0), Fraction(1))] + entries
    for k, (sb, r) in enumerate(entries):
        se = entries[k + 1][0] if k + 1 < len(entries) else None      # this rate holds on [sb, se)
        if r <= 0:
            continue
        step = 1 / r
        lo, hi = max(sb, b0), (b1 if se is None else min(b1, se))
        if hi < lo:
            continue
        p = int(lo / step) * step
        while p <= hi:
            if p > b0 and p >= sb and (se is None or p < se):
                pts.add(p)
            p += step
    return pts


def rate_at(sched, b):
    r = 1.0
    for sb, sr in sched:
        if sb <= b + 1e-9:
            r = sr
    return Fraction(r).limit_denominator(64)


def model_region(rows, ncols, sched, t0, t1, anchor="grid"):
    """The game's judged hold events over one region [t0, t1] of the converter's rows.

    anchor="grid": the ticks are the beat grid's multiples of 1/rate (StepMania's checkpoint
    positions); anchor="head": each hold ticks at its own head + k/rate, coincident ticks of
    two holds judged once. The two agree whenever a head sits on the grid."""
    inside = [r for r in rows if t0 - 1e-3 <= r["t"] <= t1 + 1e-3]
    if not inside:
        return 0
    b0, b1 = snap(inside[0]["b"]), snap(inside[-1]["b"])
    holds = [(h, t, c) for h, t, c in holds_of(rows, ncols) if b0 <= h and t <= b1]
    taps = {snap(r["b"]) for r in inside if "1" in r["line"]}
    heads = {snap(r["b"]) for r in inside if "2" in r["line"]}
    events = len(heads - taps)                        # a head row is one event unless a tap row already is
    if anchor == "grid":
        pts = {p for p in lattice(sched, b0, b1) if any(h < p <= t for h, t, _ in holds)}
    else:
        pts = set()
        for h, t, _ in holds:
            r = rate_at(sched, h)
            if r <= 0:
                continue
            p = h + 1 / r
            while p <= t:
                pts.add(p); p += 1 / r
    return events + sum(1 for p in pts if p not in taps and p not in heads)


def chart_model(blk, sched, anchor="grid"):
    return sum(model_region(blk["rows"], blk["ncols"], sched, t0, t1, anchor) for t0, t1, _ in blk["regions"])


def test():
    recs = [r for f in glob.glob(os.path.join(ROOT, "work", "tick-loop-report*.json")) for r in json.load(open(f, encoding="utf-8"))]
    allc = E.charts()
    tally, rows_out = Counter(), []
    for r in recs:
        if not r.get("clusters"):
            continue
        c = allc.get(r["chart"])
        if not c:
            continue
        base = r.get("base", "file")
        ssc = os.path.join(ROOT, *base.split(" ", 2)[2].split("/")) if base != "file" else os.path.join(ROOT, "simfiles", *c["ssc_rel"].split("/"))
        tag = E.block_tag(c["key"])
        blk = E.load_block(ssc, tag)
        if not blk or blk.get("error"):
            continue
        sched = T.schedule(open(ssc, encoding="utf-8", newline="").read(), tag)
        regions = T.regions_of(blk)
        for cl in r["clusters"]:
            if cl.get("price") is None:
                continue
            g = sum(model_region(blk["rows"], blk["ncols"], sched, regions[k]["t0"], regions[k]["t1"], "grid") for k in cl["regions"])
            h = sum(model_region(blk["rows"], blk["ncols"], sched, regions[k]["t0"], regions[k]["t1"], "head") for k in cl["regions"])
            key = "+".join(n for n, v in (("converter", cl["ticks"]), ("grid", g), ("head", h)) if v == cl["price"]) or "none"
            tally[key] += 1
            if cl["ticks"] != cl["price"]:
                rows_out.append((r["chart"][:30], str(cl["regions"][:3]), cl["ticks"], g, h, cl["price"], key, r["play"]["clean"]))
    print("priced clusters:", sum(tally.values()), "| which rule matches the counter:", dict(tally.most_common()))
    for row in rows_out[:30]:
        print("  %-30s %-12s conv %4d grid %4d head %4d price %4d  %-20s clean=%s" % row)


VARIANTS = {
    "lattice": dict(exclude_fakes=True, head_needs_rate=False),          # the converter's default
    "fakes-judged": dict(exclude_fakes=False, head_needs_rate=False),
    "head-needs-rate": dict(exclude_fakes=True, head_needs_rate=True),
}


def census():
    """Every certified chart through the converter: the old arithmetic, the lattice and its
    variants (points inside a FAKES range judged or not; a head under TICKCOUNTS 0 judged or
    not), and the independent model below on the same rows, region by region."""
    i, n = (int(x) for x in (T.arg("--shard") or "0/1").split("/"))
    allc = sorted(E.charts().values(), key=lambda c: c["chart"])[i::n]
    keep = dict(C.LATTICE_OPTIONS)
    out = []
    for c in allc:
        try:
            ssc = os.path.join(ROOT, "simfiles", *c["ssc_rel"].split("/")); tag = E.block_tag(c["key"])
            legacy = E.load_block(ssc, tag, hold_ticks="legacy")
            if not legacy or legacy.get("error"):
                continue
            row = dict(chart=c["chart"], expected=c["expected"], in_tail=c["in_tail"], legacy=legacy["implied"])
            for name, opts in VARIANTS.items():
                C.LATTICE_OPTIONS.update(opts)
                blk = E.load_block(ssc, tag)
                row[name] = blk["implied"]
                if name == "lattice":
                    sched = T.schedule(open(ssc, encoding="utf-8", newline="").read(), tag)
                    row["model"] = blk["taps"] + chart_model(blk, sched, "grid")
                    row["region_mismatch"] = sum(1 for t0, t1, tk in blk["regions"]
                                                 if model_region(blk["rows"], blk["ncols"], sched, t0, t1) != tk)
            C.LATTICE_OPTIONS.update(keep)
            out.append(row)
        except Exception as ex:
            C.LATTICE_OPTIONS.update(keep)
            out.append(dict(chart=c["chart"], error=str(ex)[:100]))
    json.dump(out, open(os.path.join(ROOT, "work", "tick-model-census.%d.json" % i), "w"), indent=1)
    summarize(out)


def summarize(out):
    ok = [o for o in out if "error" not in o]
    for rule in ["legacy"] + list(VARIANTS) + ["model"]:
        print("%-16s exact %4d of %d | breaks %3d of legacy's exact | fixes %3d | within 5: %4d" % (
            rule, sum(1 for o in ok if o[rule] == o["expected"]), len(ok),
            sum(1 for o in ok if o["legacy"] == o["expected"] != o[rule]), sum(1 for o in ok if o[rule] == o["expected"] != o["legacy"]),
            sum(1 for o in ok if 0 < abs(o[rule] - o["expected"]) <= 5)))
    print("converter vs model: charts differing %d, regions differing %d" % (
        sum(1 for o in ok if o["lattice"] != o["model"]), sum(o["region_mismatch"] for o in ok)))
    print("errors", len(out) - len(ok))


if __name__ == "__main__":
    if sys.argv[1:2] == ["test"]:
        test()
    elif sys.argv[1:2] == ["census"]:
        census()
    elif sys.argv[1:2] == ["summary"]:
        summarize([r for f in sorted(glob.glob(os.path.join(ROOT, "work", "tick-model-census.*.json")))
                   for r in json.load(open(f, encoding="utf-8"))])
    else:
        sys.exit("usage: tick_model.py test | census [--shard i/n] | summary")
