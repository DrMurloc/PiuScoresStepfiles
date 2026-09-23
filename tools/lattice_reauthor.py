# Our repairs, re-graded under the converter's tick lattice (2026-09-23).
#
# Every repair in this repo was accepted because piu-annotate's converter derived the certified
# count from it. On 2026-09-23 the converter stopped over-counting (HOLD_TICK_MODEL = "lattice",
# docs/EVIDENCE-RULES.md "A staggered release is not a tick"), and a repair fitted to the old
# arithmetic is now off by the old arithmetic's error. This tool finds those repairs and puts
# each back on its own evidence:
#
#   * a repair that AUTHORED the block's #TICKCOUNTS (the counter loop's targets, finale
#     closures, windows) is re-authored: the per-region counts it wrote - measured where the
#     counter bracketed a region, closure or window shares elsewhere, exactly what its commit
#     recorded - are read back under the old arithmetic and made the targets of author_ticks
#     under the new one, so every region keeps its count and only the rates that produce it move;
#   * a repair that only edited notes on the upstream schedule (the extraction loop's releases
#     and holds, a phantom removed) was accepted by the same over-count: it is re-graded as it
#     stands, and if it no longer closes it is reverted to the upstream block, which the loops
#     then survey again under the right arithmetic.
#
# Nothing ships unless the converter derives the certified count, and on a re-authored block
# every region lands on its recorded count.
#
#   python -X utf8 tools/lattice_reauthor.py survey              every certified chart our commits changed
#   python -X utf8 tools/lattice_reauthor.py apply [--only "<chart>"] [--dry-run]
import json
import os
import re
import subprocess
import sys
import textwrap
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edit_notes           # noqa: E402
import extract_repair as E  # noqa: E402   (puts piu-annotate on the path, and refuses an old converter)
import tick_repair as T     # noqa: E402
import author_ticks         # noqa: E402   (patch: the TICKCOUNTS writer)
from piu_annotate.formats import ssc_to_chartstruct as C  # noqa: E402
from piu_annotate.formats.sscfile import StepchartSSC     # noqa: E402

ROOT = E.ROOT
SEED = "a23cee5"            # simfiles/ as the public mirror had it: the corpus before any repair of ours
REPORT = os.path.join(ROOT, "work", "lattice-reauthor.json")
TMP = os.path.join(ROOT, "work", "lattice-reauthor")
TRAILER = E.TRAILER


def git(*args, check=False):
    p = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout


def norm(text):
    return text.replace("\r\n", "\n")


def block_section(text, tag):
    sections, i = edit_notes.find_block(norm(text), tag)
    return sections[i]


def tag_value(section, name):
    m = re.search(r"#%s:(.*?);" % name, section, re.S)
    return re.sub(r"\s+", "", m.group(1)) if m else None


def notes_of(section):
    m = re.search(r"#NOTES:(.*?);", section, re.S)
    return "\n".join(l.strip() for l in (m.group(1) if m else "").split("\n") if l.strip() and not l.strip().startswith("//"))


def with_block(text, tag, section):
    """The song file's text with one block replaced, in the file's own line endings."""
    crlf = "\r\n" in text
    sections, i = edit_notes.find_block(norm(text), tag)
    sections[i] = section
    out = "#NOTEDATA:;".join(sections)
    return out.replace("\n", "\r\n") if crlf else out


def grade(text, tag, key, hold_ticks=None):
    os.makedirs(TMP, exist_ok=True)
    p = os.path.join(TMP, "grade-%s.ssc" % key)
    open(p, "w", encoding="utf-8", newline="").write(text)
    return E.load_block(p, tag, hold_ticks)


def history(rel, tag):
    """The commits after the seed that changed this block, oldest first."""
    shas = git("log", "--format=%h", "--reverse", SEED + "..HEAD", "--", rel).split()
    out, prev = [], None
    try:
        prev = block_section(git("show", "%s:%s" % (SEED, rel)), tag)
    except SystemExit:
        prev = None
    for sha in shas:
        try:
            cur = block_section(git("show", "%s:%s" % (sha, rel)), tag)
        except SystemExit:
            continue
        if cur != prev:
            out.append((sha, git("log", "-1", "--format=%s", sha).strip()))
        prev = cur
    return out


def survey():
    allc = E.charts()
    rows = []
    changed_files = set(git("diff", "--name-only", SEED, "HEAD", "--", "simfiles").splitlines())
    for name, c in sorted(allc.items()):
        rel = "simfiles/" + c["ssc_rel"]
        if rel not in changed_files or not c.get("expected"):
            continue
        tag, key = E.block_tag(c["key"]), c["key"]
        text = open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8", newline="").read()
        try:
            seed_text = git("show", "%s:%s" % (SEED, rel))
            seed_sec = block_section(seed_text, tag)
        except SystemExit:
            continue
        cur_sec = block_section(text, tag)
        if norm(cur_sec) == norm(seed_sec):
            continue
        now_l, now_g = E.load_block(os.path.join(ROOT, *rel.split("/")), tag), E.load_block(os.path.join(ROOT, *rel.split("/")), tag, "legacy")
        seed_l = grade(with_block(text, tag, seed_sec), tag, key)
        seed_g = grade(with_block(text, tag, seed_sec), tag, key, "legacy")
        r = dict(chart=name, key=key, rel=rel, tag=tag, expected=c["expected"],
                 notes_changed=notes_of(cur_sec) != notes_of(seed_sec),
                 ticks_changed=tag_value(cur_sec, "TICKCOUNTS") != tag_value(seed_sec, "TICKCOUNTS"),
                 other_tags=sorted(t for t in ("BPMS", "WARPS", "FAKES", "STOPS", "DELAYS", "OFFSET")
                                   if tag_value(cur_sec, t) != tag_value(seed_sec, t)),
                 now=dict(legacy=now_g and now_g.get("implied"), lattice=now_l and now_l.get("implied")),
                 seed=dict(legacy=seed_g and seed_g.get("implied"), lattice=seed_l and seed_l.get("implied")),
                 commits=history(rel, tag))
        rows.append(r)
        print("%-44s legacy %5s lattice %5s (expected %5d) | seed legacy %5s lattice %5s | notes %s ticks %s %s| %d commit(s)" % (
            name[:44], r["now"]["legacy"], r["now"]["lattice"], r["expected"], r["seed"]["legacy"], r["seed"]["lattice"],
            "Y" if r["notes_changed"] else "-", "Y" if r["ticks_changed"] else "-", ("other " + ",".join(r["other_tags"]) + " ") if r["other_tags"] else "",
            len(r["commits"])), flush=True)
    json.dump(rows, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    exact_now = [r for r in rows if r["now"]["lattice"] == r["expected"]]
    broken = [r for r in rows if r["now"]["legacy"] == r["expected"] != r["now"]["lattice"]]
    print("\n%d certified charts our commits changed | exact under the lattice %d | exact under legacy only %d" % (len(rows), len(exact_now), len(broken)))
    print("of those broken: ticks authored %d (notes too %d) | notes only %d | seed exact under the lattice %d" % (
        sum(1 for r in broken if r["ticks_changed"]), sum(1 for r in broken if r["ticks_changed"] and r["notes_changed"]),
        sum(1 for r in broken if not r["ticks_changed"]), sum(1 for r in broken if r["seed"]["lattice"] == r["expected"])))


class Counts:
    """The converter's own per-region lattice counts for any #TICKCOUNTS on one block, without
    re-running the conversion: the segments do not depend on the schedule, so the converter's
    post-loop count (lattice_hold_ticks, then merge_holdticks) is all a new schedule changes."""

    def __init__(self, path, tag):
        sc = StepchartSSC.from_song_ssc_file(path, tag)
        self.ctx = {}
        C.stepchart_ssc_to_chartstruct(sc, context=self.ctx)
        legacy_ctx = {}
        C.stepchart_ssc_to_chartstruct(sc, hold_ticks="legacy", context=legacy_ctx)
        self.base = {}
        for b, r in sorted(self.ctx["holdticks"].items()):
            self.base[exact(b)] = r
        merged = C.merge_holdticks(self.fresh())
        self.region_of, bounds = [], []
        for seg in merged:
            st, en = round(float(seg.start_time), 4), round(float(seg.end_time), 4)
            if bounds and st <= bounds[-1][3] + 1e-6:
                bounds[-1][1] = max(bounds[-1][1], seg.end_beat); bounds[-1][3] = max(bounds[-1][3], en)
            else:
                bounds.append([seg.start_beat, seg.end_beat, st, en])
            self.region_of.append(len(bounds) - 1)
        # a region's span is where its JUDGED holds are: a segment the loop opened on a fake
        # hold's head can run a region's start many beats before any hold a rate acts on
        spans = [(a, b) for a, b, _, _ in bounds]
        self.times = [(s, e) for _, _, s, e in bounds]
        self.bounds = []
        for a, b in spans:
            inside = [(h, t) for h, t in self.ctx["real_holds"] if a - 1e-9 <= h and t <= b + 1e-9]
            self.bounds.append((min(h for h, _ in inside), max(t for _, t in inside)) if inside else (a, b))
        self.legacy = self.aggregate(C.merge_holdticks(legacy_ctx["segments"]))

    def fresh(self):
        return [C.HoldTick(s.start_time, s.end_time, 0, s.start_beat, s.end_beat) for s in self.ctx["segments"]]

    def aggregate(self, merged):
        out = [0] * len(self.bounds)
        for k, seg in enumerate(merged):
            out[self.region_of[k]] += int(round(seg.ticks))
        return out

    def counts(self, entries):
        segs = self.fresh()
        C.lattice_hold_ticks(segs, self.ctx["real_holds"], self.ctx["df"], C.BeatToValueDict(dict(entries)),
                             self.ctx["warps"], self.ctx["fakes"])
        return self.aggregate(C.merge_holdticks(segs))


def exact(b):
    """A schedule beat as the converter reads it (C._frac), so 73.583333 as written and the row
    at 73 + 7/12 are one key, not two a hair apart."""
    return float(C._frac(b))


def rate_at(entries, beat):
    r = 1.0
    for b in sorted(entries):
        if b <= beat + 1e-9:
            r = entries[b]
    return r


def with_region(entries, b0, b1, rates):
    """The schedule with one region's span [b0, b1) rewritten to `rates` [(beat, rate)] and the
    rate in effect at b1 left as it was, so nothing outside the region moves."""
    b0, b1 = exact(b0), exact(b1)
    keep = {b: r for b, r in entries.items() if not (b0 <= b < b1)}
    if b1 not in keep:
        keep[b1] = rate_at(entries, b1)
    for b, r in rates:
        keep[exact(b)] = float(r)
    return keep


def solve(cnt, targets):
    """For every region off its target, the smallest change inside it that lands it: one rate
    over the region, the nearest to the rate it had first; failing that, two rates split at one
    of a few points inside it. Regions are independent - a region's count depends only on the
    schedule inside it - so every off region is searched at once, one conversion per trial."""
    now = cnt.counts(cnt.base)
    off = [i for i, (c, t) in enumerate(zip(now, targets)) if c != t]
    plan = {}
    if not off:
        return plan, now

    def trial(choice):
        entries = dict(cnt.base)
        for i, rates in choice.items():
            b0, b1 = cnt.bounds[i]
            entries = with_region(entries, b0, b1, rates)
        return cnt.counts(entries)

    # one rate over the region
    cands = {}
    for i in off:
        b0, b1 = cnt.bounds[i]
        guess = targets[i] / max(b1 - b0, 1e-6)
        ref = rate_at(cnt.base, b0) if rate_at(cnt.base, b0) > 0 else guess
        pool = sorted(set(range(max(0, int(guess) - 8), int(guess) + 10)) | {int(round(ref))}, key=lambda r: (abs(r - ref), r))
        cands[i] = [[(b0, r)] for r in pool]
    for k in range(max(len(v) for v in cands.values())):
        todo = [i for i in off if i not in plan and k < len(cands[i])]
        if not todo:
            break
        got = trial({i: cands[i][k] for i in todo})
        for i in todo:
            if got[i] == targets[i]:
                plan[i] = cands[i][k]
    # every single rate up to twice the density the target needs: a region whose heads sit on
    # a lattice counts fewer points at the rates that land on them, so the count is not monotone
    left = [i for i in off if i not in plan]
    scan = {}
    if left:
        top = {i: int(2 * targets[i] / max(cnt.bounds[i][1] - cnt.bounds[i][0], 1e-6)) + 12 for i in left}
        for k in range(max(top.values()) + 1):
            todo = [i for i in left if k <= top[i]]
            got = trial({i: [(cnt.bounds[i][0], k)] for i in todo})
            for i in todo:
                scan.setdefault(i, {})[k] = got[i]
        for i in left:
            ref = rate_at(cnt.base, cnt.bounds[i][0])
            hits = [r for r, c in scan[i].items() if c == targets[i]]
            if hits:
                plan[i] = [(cnt.bounds[i][0], min(hits, key=lambda r: abs(r - ref)))]
    # two rates, split inside the region at sixteenths of a beat: the pairs of rates whose counts
    # bracket the target, nearest each other first, so moving the split walks the count between them
    left = [i for i in off if i not in plan]
    if left:
        cands = {}
        for i in left:
            b0, b1 = cnt.bounds[i]
            span = b1 - b0
            grid = [k / 16 for k in range(int(b0 * 16) + 1, int(b1 * 16) + 1) if b0 + 1e-9 < k / 16 < b1 - 1e-9]
            grid = sorted(set(grid) | {b0 + span * k / 8 for k in range(1, 8)})
            step = max(1, len(grid) // 64)
            splits = grid[::step]
            lo = [r for r, c in scan[i].items() if c < targets[i]]
            hi = [r for r, c in scan[i].items() if c > targets[i]]
            pairs = sorted(((a, b) for a in lo for b in hi), key=lambda p: (abs(p[0] - p[1]), p[0] + p[1]))[:8]
            combos = []
            for a, b in pairs:
                for c in splits:
                    combos.append([(b0, a), (c, b)])
                    combos.append([(b0, b), (c, a)])
            cands[i] = combos
        for k in range(max(len(v) for v in cands.values())):
            todo = [i for i in left if i not in plan and k < len(cands[i])]
            if not todo:
                break
            got = trial({i: cands[i][k] for i in todo})
            for i in todo:
                if got[i] == targets[i]:
                    plan[i] = cands[i][k]
    final = trial(plan)
    return plan, final


DOMINANT = 0.5    # a region carrying this share of the chart's hold events is the closure the repair priced
NEAR = 3.0        # s: otherwise the head events come from regions this close (a counter window's width)


def head_floor(cnt, targets):
    """Targets every region can reach. The game judges a hold's head whatever its TICKCOUNT (the
    upstream corpus: in all ten charts where a rate-0 head decides the count, judging it is the
    exact reading), so a region cannot count fewer events than its heads - the old arithmetic
    let a rate-0 hold count none, and the repairs that split an unobserved remainder (a storm
    priced by closure, blind micro-holds sharing a pool by a uniform prior) put zero on some
    holds. Each such region is raised to its heads, and the difference comes off the closure:
    the one region carrying half the chart's hold events if there is one (the storm or bomb the
    repair priced by closure), otherwise the nearest regions in time (the pool it was split from),
    never taking a region below its own heads. Returns the targets and every move."""
    floors = cnt.counts({0.0: 0.0})
    new = list(targets)
    raised = [i for i in range(len(new)) if new[i] < floors[i]]
    moves = []
    if not raised:
        return new, moves, floors
    mids = [(a + b) / 2 for a, b in cnt.times]
    big = max(range(len(new)), key=lambda k: new[k])
    dominant = new[big] >= DOMINANT * sum(targets)
    for i in raised:
        need = floors[i] - new[i]
        new[i] = floors[i]
        while need:
            if dominant and new[big] > floors[big]:
                j = big
            else:
                # one event at a time from whichever region nearby carries the most above its own
                # heads, so the correction spreads over the biggest neighbours instead of emptying one
                pool = [j for j in range(len(new)) if j not in raised and new[j] > floors[j]]
                near = [j for j in pool if abs(mids[j] - mids[i]) <= NEAR] or pool
                if not near:
                    return None, moves, floors
                j = max(near, key=lambda j: (new[j] - floors[j], -abs(mids[j] - mids[i])))
            new[j] -= 1
            need -= 1
            moves.append((i, j, 1))
    return new, moves, floors


def fmt(v):
    return "%d" % round(v) if abs(v - round(v)) < 1e-9 else ("%.6f" % v).rstrip("0").rstrip(".")


def reauthor(r, dry):
    """Re-author an authored #TICKCOUNTS so every region keeps the count the repair recorded."""
    src = os.path.join(ROOT, *r["rel"].split("/"))
    text = open(src, encoding="utf-8", newline="").read()
    os.makedirs(TMP, exist_ok=True)
    work = os.path.join(TMP, r["key"] + ".ssc")
    open(work, "w", encoding="utf-8", newline="").write(text)
    cnt = Counts(work, r["tag"])
    recorded = cnt.legacy
    if sum(recorded) + E.load_block(work, r["tag"])["taps"] != r["expected"]:
        return dict(result="skip", why="not exact under the old arithmetic either")
    targets, moves, floors = head_floor(cnt, recorded)
    if targets is None:
        return dict(result="park", why="the regions' heads alone exceed what the closure can give up")
    plan, final = solve(cnt, targets)
    devs = [(i, targets[i], final[i]) for i in range(len(targets)) if final[i] != targets[i]]
    res = dict(regions=len(targets), moved=len(plan), unsolved=len(devs),
               plan={"%.4f-%.4f" % cnt.bounds[i]: rates for i, rates in plan.items()},
               heads=[dict(raised="%.3f-%.3f" % cnt.bounds[i], giver="%.3f-%.3f" % cnt.bounds[j], n=n,
                           giver_before=recorded[j], giver_after=targets[j]) for i, j, n in moves],
               devs=[("%.3f-%.3f" % cnt.bounds[i], t, f) for i, t, f in devs][:12])
    if devs:
        res.update(result="park", why="%d of %d regions cannot land on their recorded count with one or two rates (first %s: target %d, closest %d)" % (
            len(devs), len(targets), res["devs"][0][0], devs[0][1], devs[0][2]))
        return res
    entries = dict(cnt.base)
    for i, rates in plan.items():
        entries = with_region(entries, cnt.bounds[i][0], cnt.bounds[i][1], rates)
    tc = ",\n".join("%.6f=%s" % (b, fmt(v)) for b, v in sorted(entries.items()))
    new_text, ok = author_ticks.patch(norm(text), r["tag"], tc)
    if "\r\n" in text:
        new_text = new_text.replace("\n", "\r\n")
    open(work, "w", encoding="utf-8", newline="").write(new_text)
    before_l = E.load_block(src, r["tag"])
    after = E.load_block(work, r["tag"])
    got = [tk for _, _, tk in after["regions"]]
    if after["implied"] != r["expected"] or got != targets:
        res.update(result="park", why="the written schedule does not re-derive: implied %d, %d region(s) off" % (
            after["implied"], sum(1 for a, b in zip(got, targets) if a != b)))
        return res
    res.update(result="reauthored", text=new_text, before=dict(legacy=sum(targets) + after["taps"], lattice=before_l["implied"]),
               after=dict(taps=after["taps"], ticks=after["ticks"], implied=after["implied"]))
    return res


def para(text):
    return textwrap.fill(" ".join(text.split()), width=96)


def span_key(span):
    return float(span.split("-")[0])


def message_reauthor(r, res):
    lines = ["Re-author %s hold ticks under the tick lattice" % r["chart"], ""]
    lines.append(para(
        "piu-annotate's converter now counts hold ticks by the tick lattice (HOLD_TICK_MODEL; "
        "docs/EVIDENCE-RULES.md, \"A staggered release is not a tick\"). This block's #TICKCOUNTS was "
        "authored by %s to make the old arithmetic derive the judged %d, and under the lattice the same "
        "schedule derives %d." % (", ".join(sha for sha, _ in r["commits"]) or "an earlier repair", r["expected"], res["before"]["lattice"])))
    lines.append("")
    lines.append(para(
        "Its %d hold regions keep exactly the counts that repair recorded%s - measured where the counter "
        "bracketed a region, closure or window shares elsewhere, as its commit says - read back under the "
        "old arithmetic. The %d region(s) the lattice counts differently get a new rate over their own span, "
        "the rate after each left as it was; every other region's schedule is untouched. No new evidence, "
        "and none lost:" % (res["regions"], " (but for the heads below)" if res.get("heads") else "", res["moved"])))
    plan = sorted(res["plan"].items(), key=lambda kv: span_key(kv[0]))
    for span, rates in plan[:40]:
        lines.append("  beats %s: %s" % (span, ", then ".join("%s per beat from %.4f" % (fmt(rt), b) for b, rt in rates)))
    if len(plan) > 40:
        lines.append("  ... and %d more" % (len(plan) - 40))
    if res.get("heads"):
        raised = len({m["raised"] for m in res["heads"]})
        lines.append("")
        lines.append(para(
            "One change the new arithmetic forces: %d hold region(s) this repair recorded below their own "
            "heads - zero events, which a rate-0 hold counted under the old arithmetic. The game judges a "
            "hold's head whatever its tick rate (docs/EVIDENCE-RULES.md: in all ten upstream charts where "
            "that decides the count, judging the head is the exact reading), so each now carries its heads, "
            "and the %d event(s) come off the closure the repair priced them from - the region carrying the "
            "chart's remainder, or one at a time from the largest regions within three seconds of the pool they "
            "were split from - never below a region's own heads:" % (raised, sum(m["n"] for m in res["heads"]))))
        givers = {}
        for m in res["heads"]:
            g = givers.setdefault(m["giver"], dict(n=0, before=m["giver_before"], after=m["giver_after"]))
            g["n"] += m["n"]
        givers = sorted(givers.items(), key=lambda kv: span_key(kv[0]))
        for span, g in givers[:30]:
            lines.append("  beats %s gives %d (%d -> %d)" % (span, g["n"], g["before"], g["after"]))
        if len(givers) > 30:
            lines.append("  ... and %d more" % (len(givers) - 30))
    lines.append("")
    lines.append(para(
        "Before: %d under the old arithmetic, %d under the lattice. After: taps %d + ticks %d = %d, the "
        "judged count exactly (tick_verify), every region on its target." % (
            res["before"]["legacy"], res["before"]["lattice"], res["after"]["taps"], res["after"]["ticks"], res["after"]["implied"])))
    return "\n".join(lines) + TRAILER


def message_revert(r, why):
    lines = ["Revert %s to the upstream block: %s" % (r["chart"], why), ""]
    lines.append(para(
        "piu-annotate's converter now counts hold ticks by the tick lattice (HOLD_TICK_MODEL; "
        "docs/EVIDENCE-RULES.md, \"A staggered release is not a tick\"). Under it this block, as repaired "
        "by %s, derives %d against the judged %d; the upstream block (seed %s) derives %d." % (
            ", ".join(sha for sha, _ in r["commits"]), r["now"]["lattice"], r["expected"], SEED, r["seed"]["lattice"])))
    lines.append("")
    if r["seed"]["lattice"] == r["expected"]:
        lines.append(para(
            "The upstream file was right: the repair closed a gap the old arithmetic opened (it put the "
            "upstream block %+d off), so it goes." % (r["seed"]["legacy"] - r["expected"])))
    else:
        lines.append(para(
            "The repair edited notes on the upstream schedule and was accepted because the old arithmetic "
            "closed on it; under the right arithmetic it does not, so it is not a repair. The upstream block "
            "returns, and the extraction and tick loops survey this chart again under the lattice, where the "
            "same footage evidence decides afresh."))
    lines.append("")
    lines.append("Reverted:")
    for sha, subj in r["commits"]:
        lines.append("  %s %s" % (sha, subj[:84]))
    return "\n".join(lines) + TRAILER


def apply():
    only, dry = T.arg("--only"), "--dry-run" in sys.argv
    rows = json.load(open(REPORT, encoding="utf-8"))
    todo = [r for r in rows if r["now"]["legacy"] == r["expected"] != r["now"]["lattice"] and (not only or r["chart"] == only)]
    if git("status", "--short", "--", "simfiles").strip() and not dry:
        sys.exit("simfiles/ has uncommitted changes - refusing")
    tally, log = Counter(), []
    for r in todo:
        src = os.path.join(ROOT, *r["rel"].split("/"))
        text = open(src, encoding="utf-8", newline="").read()
        seed_sec = block_section(git("show", "%s:%s" % (SEED, r["rel"])), r["tag"])
        if r["seed"]["lattice"] == r["expected"]:
            action, why = "revert", "exact under the tick lattice"
        elif not r["ticks_changed"]:
            action, why = "revert", "the repair's note edits do not close under the tick lattice"
        else:
            action, why = "reauthor", None
        if action == "revert":
            new_text = with_block(text, r["tag"], seed_sec)
            check = grade(new_text, r["tag"], r["key"])
            res = dict(result="reverted", implied=check["implied"])
            msg = message_revert(r, why)
        else:
            res = reauthor(r, dry)
            if res["result"] != "reauthored":
                tally[res["result"]] += 1
                log.append(dict(chart=r["chart"], **{k: v for k, v in res.items() if k != "text"}))
                print("  %-44s %s: %s" % (r["chart"][:44], res["result"].upper(), res.get("why")), flush=True)
                continue
            new_text, msg = res["text"], message_reauthor(r, res)
        tally[res["result"]] += 1
        log.append(dict(chart=r["chart"], action=action, **{k: v for k, v in res.items() if k != "text"}))
        if dry:
            print("  %-44s would %s -> %s" % (r["chart"][:44], action, res.get("implied")), flush=True)
            continue
        if not E.same_outside(open(src, encoding="utf-8", newline="").read(), new_text, r["tag"]):
            print("  %-44s the file changed outside this block - skipped" % r["chart"][:44]); continue
        open(src, "w", encoding="utf-8", newline="").write(new_text)
        tv = subprocess.run([E.PY, "-X", "utf8", os.path.join(ROOT, "tools", "tick_verify.py"), "--file", src, "--block", r["tag"], str(r["expected"])],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        if action == "reauthor" and "MATCH" not in tv:
            git("checkout", "HEAD", "--", r["rel"])
            print("  %-44s tick_verify disagreed in place (%s) - restored" % (r["chart"][:44], tv.strip().splitlines()[0] if tv.strip() else "")); continue
        git("add", "--", r["rel"])
        subprocess.run(["git", "commit", "-q", "-F", "-"], cwd=ROOT, input=msg, text=True, encoding="utf-8")
        sha = git("rev-parse", "--short", "HEAD").strip()
        log[-1]["commit"] = sha
        print("  %s %-44s %s (%s)" % (sha, r["chart"][:44], action, (tv.strip().splitlines() or [""])[0]), flush=True)
    json.dump(log, open(os.path.join(ROOT, "work", "lattice-reauthor-apply.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n%s" % dict(tally))


if __name__ == "__main__":
    if sys.argv[1:2] == ["survey"]:
        survey()
    elif sys.argv[1:2] == ["apply"]:
        apply()
    else:
        sys.exit("usage: lattice_reauthor.py survey | apply [--only <chart>] [--dry-run]")
