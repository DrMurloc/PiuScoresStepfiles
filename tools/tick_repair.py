# The tick loop. Where the extraction loop found the screen showing the file's notes and holds
# and the count still off (the "ticks, not notes" parks), the combo counter says WHICH hold
# region judged more or fewer ticks than the file gives it, and by how many. This tool prices
# every hold region of the file from the counter, aimed by the extraction loop's alignment (the
# file's own notes matched on screen to a few milliseconds) rather than a flash-fitted offset,
# and authors exactly the regions the counter measured:
#
#   * a region priced N where the file derives M gets the single integer #TICKCOUNTS rate over
#     its own span under which the converter derives N, the file's own rate restored at the
#     region's end (docs/EVIDENCE-RULES.md "No per-beat tick rate": the game's ticks are
#     authored, so a measured count IS the schedule for that span);
#   * where no single rate reaches N and the region ends on one release row, the release moves
#     by one of the block's own rows toward N - but only when the rail the extraction saw ends
#     on that side of the file's release, so the grid never moves against the video;
#   * a region the counter could not read is left exactly as the file has it, and the report
#     says why.
#
# HOW A REGION IS READ. The counter is a running count of judged events, so between two judged
# events it is flat: a plateau. A region is priced from the plateau just before its first hold
# and the plateau just after its last release, each read as the value the frames on it agree on,
# and the region's judged ticks are that climb less the file's own events between the two
# plateaus. Two regions with no readable plateau between them (a pair, a drill) are priced as
# one cluster. On a full-combo play the counter never falls, so only the longest non-decreasing
# chain of confident reads is believed - a dropped hundred, a 9 read as 5 or a rail's leading 1
# falls off that chain instead of pricing a hold - and every plateau must sit within a few
# events of the file's own cumulative count, which is what a near-miss chart's counter shows.
# The display lag between a judgement and the counter's step is measured on the chart's own
# isolated taps rather than assumed.
#
# THE GATE. A chart ships only when (1) the priced clusters' differences sum to the file's whole
# deficit against the certified count, so every edit is a measured number and the unread
# regions are, in total, right as they stand; (2) on a play with GOODs, BADs or MISSes (result
# screen maxcombo below the judged count) EVERY region was priced - a GOOD neither breaks nor
# increments the counter (docs/EVIDENCE-RULES.md), so an unread region could hide the tick it
# took; (3) the converter derives the price on every edited cluster, the file's own ticks on
# every other, and the certified count in total. Anything else parks with the region table.
#
#   python -X utf8 tools/tick_repair.py survey [--shard i/n] [--only "<chart>"] [--limit N]
#                                             [--near N] [--redo] [--redo-verdict V,V] [--no-scan]
#   python -X utf8 tools/tick_repair.py commit [--dry-run] [--only "<chart>"]
#
# The worklist is the extraction loop's census (sources/extract-loop-2026-09-22.json): its parks
# whose extraction cleared the bar, nearest the count first; --near N (default 10) keeps those
# within N of the count, which is where a plateau can be checked against the file's own count.
# A chart whose extraction candidate applied edits is priced and authored on that candidate, so
# one commit carries both. Reports: work/tick-loop-report[.i].json (resumable); candidates:
# work/tick-loop/<key>.ssc. The counter scan (work/combo/<vid>.<band>.jsonl, combo_reader) is
# made on demand unless --no-scan, at about 1.3x real time per video.
import bisect
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import author_ticks     # noqa: E402  (patch: the TICKCOUNTS writer)
import corpus_map       # noqa: E402
import edit_notes       # noqa: E402
import extract_repair as E  # noqa: E402   (puts piu-annotate on the path, refuses an old converter)
import note_extract     # noqa: E402
from piu_annotate.formats import ssc_to_chartstruct as _C  # noqa: E402

ROOT = E.ROOT
PY = E.PY
OUT = os.path.join(ROOT, "work", "tick-loop")
CENSUS = os.path.join(ROOT, "sources", "extract-loop-2026-09-22.json")
TRAILER = E.TRAILER
SPAN = 0.60     # s: how far before/after a region its plateau may be sought (the file's events between are subtracted)
JIT = 0.035     # s: a read whose cut is this close to a judged event is not used - the lag's jitter
CONF = 0.60     # the reader's confidence floor; lower poisons the reads (EVIDENCE-RULES)
FRAMES = 2      # a plateau needs this many reads agreeing on its value
SHARE = 0.60    # and that value must carry this share of the plateau's reads
LAG0 = 0.10     # s: the display lag assumed when the chart's own taps cannot measure it
RATE_MAX = 128  # ticks per beat the rate search will go to
TAIL_ROWS = 1   # how many of the block's own rows a release may move
WINDOW_REGIONS = 4   # a cluster authored as one may hold this many regions...
WINDOW_SECONDS = 4.0 # ...over this long: a window's total is measured, its interior is not
NEAR = 10       # the default --near: how far from the count a chart may be to be priced this way


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


# ---------------------------------------------------------------- the worklist

def census_path():
    """The extraction loop's census to take the worklist from: --census, else the newest committed."""
    if arg("--census"):
        return arg("--census")
    runs = sorted(f for f in os.listdir(os.path.join(ROOT, "sources")) if re.match(r"extract-loop-\d{4}-\d\d-\d\d\.json$", f))
    return os.path.join(ROOT, "sources", runs[-1]) if runs else CENSUS


def worklist():
    """The extraction loop's parks that read the screen well, with the file each should start from."""
    census = json.load(open(census_path(), encoding="utf-8"))["charts"]
    allc = E.charts()
    jobs = []
    for r in census:
        x = r.get("extraction")
        if r.get("verdict") != "PARK" or not x or x["recall"] < E.RECALL_BAR or x["precision"] < E.PRECISION_BAR:
            continue
        c = allc.get(r["chart"])
        if not c or not c.get("expected"):
            continue
        cand = os.path.join(ROOT, *r["candidate"].split("/")) if r.get("candidate") and r.get("applied") else None
        if cand and (not os.path.exists(cand) or "implied" not in (r.get("after") or {})):
            cand = None
        implied = (r["after"] if cand else r["file"])["implied"]
        jobs.append(dict(c, base=cand, dist=implied - r["expected"], census=r))
    # full-combo plays first: on those every region can be read on its own and a partial
    # accounting closes; a play with breaks needs every region read before anything ships
    cert = corpus_map.certification()
    for j in jobs:
        s = (cert.get(j["vid"]) or {}).get(j["side"]) or {}
        try:
            j["clean"] = int(str(s.get("maxcombo")).strip()) == int(s.get("judged"))
        except (ValueError, TypeError):
            j["clean"] = False
    jobs.sort(key=lambda j: (not j["clean"], abs(j["dist"]), j["chart"]))
    return jobs


# ---------------------------------------------------------------- the counter

def reads_for(vid, band, mc, scan_ok):
    """The counter reads for a video's band: (video time, value), confident, in range, sorted."""
    path = os.path.join(ROOT, "work", "combo", "%s.%s.jsonl" % (vid, band))
    if not os.path.exists(path) and scan_ok:
        subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "tools", "combo_reader.py"), "--scan", vid, "side=" + band],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    if not os.path.exists(path):
        return None
    reads = []
    for line in open(path, encoding="utf-8"):
        t, v, c = json.loads(line)
        if v is not None and c >= CONF and 4 <= v <= mc:
            reads.append((float(t), int(v)))
    return sorted(reads)


def chain(reads):
    """The longest non-decreasing chain of reads: what a counter that never falls can have shown.
    Everything off it - a dropped hundred, a 9 read as 5, a rail's leading 1 - is a misread."""
    if not reads:
        return []
    vals, back, idx = [], [None] * len(reads), []
    for i, (_, v) in enumerate(reads):
        k = bisect.bisect_right(vals, v)
        back[i] = idx[k - 1] if k else None
        if k == len(idx):
            idx.append(i); vals.append(v)
        else:
            idx[k] = i; vals[k] = v
    out, i = [], idx[-1]
    while i is not None:
        out.append(reads[i]); i = back[i]
    return out[::-1]


def runs(reads):
    """A play with breaks: the reads cut at every fall the counter holds for five frames (a reset),
    each run then filtered to its own non-decreasing chain. Returns [(t, v, run index)] - a
    region is priced only from two readings of ONE run, since across a reset the counter has
    restarted and the two values say nothing about each other."""
    out, run, cur = [], 0, []
    i = 0
    while i < len(reads):
        t, v = reads[i]
        if cur and v < cur[-1][1] - 3 and all(reads[j][1] < cur[-1][1] - 3 for j in range(i, min(i + 5, len(reads)))):
            out += [(a, b, run) for a, b in chain(cur)]
            run, cur = run + 1, []
        cur.append((t, v)); i += 1
    out += [(a, b, run) for a, b in chain(cur)]
    return out


class Clock:
    """chart_time = a + b * video_time, from the extraction loop's alignment."""
    def __init__(self, a, b, lag=LAG0):
        self.a, self.b, self.lag = a, b, lag

    def chart(self, T):
        return self.a + self.b * T

    def video(self, t):
        return (t - self.a) / self.b

    def cut(self, T):
        """The chart time up to which a read at video time T has counted the judgements."""
        return self.chart(T - self.lag)


def measure_lag(reads, taps, regions, clock):
    """How long after a judgement the counter steps, from the chart's own isolated taps: each tap
    with nothing judged within a quarter second either side, against the counter's next step."""
    spans = [(r["t0"], r["t1"]) for r in regions]
    allt = sorted(taps)
    steps = [t1 for (t0, v0, r0), (t1, v1, r1) in zip(reads, reads[1:]) if v1 > v0 and r0 == r1]
    lags = []
    for k, t in enumerate(allt):
        if (k and t - allt[k - 1] < 0.25) or (k + 1 < len(allt) and allt[k + 1] - t < 0.25):
            continue
        if any(s0 - 0.25 < t < s1 + 0.25 for s0, s1 in spans):
            continue
        T = clock.video(t)
        j = bisect.bisect_left(steps, T - 0.02)
        if j < len(steps) and steps[j] - T <= 0.30:
            lags.append(steps[j] - T)
    if len(lags) < 15:
        return LAG0, len(lags)
    lags.sort()
    return round(lags[len(lags) // 2], 3), len(lags)


def read_window(reads, clock, lo, hi, events, F):
    """What the counter shows against the file's own running count over a stretch of chart time:
    each read whose cut falls in [lo, hi] and clear of every judged event by JIT carries
    value - F(cut), which on a counter that saw what the file says is one constant. The value
    most of those reads agree on is the stretch's reading; a stretch whose reads disagree is not
    read at all. Returns (cut, value, file count there, that constant, frames agreeing, of)."""
    win = []
    for t, v, run in reads:
        cut = clock.cut(t)
        if not lo <= cut <= hi:
            continue
        j = bisect.bisect_left(events, cut - JIT)
        if j < len(events) and events[j] <= cut + JIT:
            continue
        win.append((cut, v, v - F(cut), run))
    if len(win) < FRAMES:
        return None
    err, n = Counter(e for _, _, e, _ in win).most_common(1)[0]
    if n < FRAMES or n / len(win) < SHARE:
        return None
    hits = [w for w in win if w[2] == err]
    if len({w[3] for w in hits}) != 1:
        return None
    cut, v, _, run = hits[len(hits) // 2]
    return dict(cut=round(cut, 3), value=v, file=F(cut), err=err, frames=n, of=len(win), run=run)


def price_clusters(regions, taps, reads, clock, clean, tol, judged=None):
    """Each region's judged ticks from the counter either side of it; regions with nothing
    readable between them are priced together, as one cluster.

    The counter is a running count of judged events, so on a play that counted every event a
    read minus the file's own count up to the same instant is the file's cumulative error there,
    and it changes only inside a region whose ticks the file has wrong. The stretch before a
    region (back to the previous region, at most SPAN) and the stretch after it (up to the next
    region) are each read that way; the change between the two is the cluster's own error, and
    its ticks plus that change its price. On a full-combo play every reading is also held to the
    file's count: a read further from it than the chart's whole deficit could explain is a
    misread, not a price. Reads within JIT of a judged event are never used, since which side of
    the event they fall on is what the display lag cannot settle."""
    events = sorted(taps + [x for r in regions for x in (r["t0"], r["t1"])])
    taps_s = sorted(taps)
    ends = sorted((r["t1"], r["ticks"]) for r in regions)

    def F(cut):
        """The file's own count of judged events up to a cut: tap rows, plus the ticks of every
        region that has ended."""
        return bisect.bisect_right(taps_s, cut) + sum(tk for t1, tk in ends if t1 <= cut)

    def stretch(lo, hi):
        if hi - lo < 2 * JIT:
            return None
        p = read_window(reads, clock, lo, hi, events, F)
        if p and clean and abs(p["err"]) > tol:
            p["why"] = "the read %d is %+d off the file's count of %d there" % (p["value"], p["err"], p["file"])
        return p

    n = len(regions)
    # each region is read on the stretch NEAREST to it, at most SPAN away and never past its
    # neighbour: a reading taken right after the previous region and carried across a minute of
    # taps to the next one charges every tap error in between to that region (Cutie Song S11's
    # last hold was priced from a plateau 57 s before it)
    befores = [stretch(max(regions[i - 1]["t1"] if i else -1e9, regions[i]["t0"] - SPAN), regions[i]["t0"]) for i in range(n)]
    afters = [stretch(regions[i]["t1"], min(regions[i + 1]["t0"] if i + 1 < n else 1e9, regions[i]["t1"] + SPAN)) for i in range(n)]
    between = [afters[i] if afters[i] and not afters[i].get("why") else befores[i + 1] for i in range(n - 1)]
    first, last = befores[0], afters[-1]
    if clean and judged is not None:
        # Two readings a full-combo play fixes without a frame (EVIDENCE-RULES, the structural
        # anchor): before anything is judged the counter is 0, and after the last event it rests
        # at maxcombo, which on a full combo IS the judged count. The game draws nothing below 4
        # and a final plateau is often a digit misread with nothing after it to contradict it
        # (ASDF D10's 497 reads 457), so where the frames give nothing usable at either end, the
        # anchor is the reading - and a cluster priced off it is priced by closure, and says so.
        if (not first or first.get("why")) and F(regions[0]["t0"] - JIT) <= 3:
            cut = regions[0]["t0"] - JIT
            first = dict(cut=round(cut, 3), value=F(cut), file=F(cut), err=0, frames=0, of=0,
                         anchor="the game draws no counter below 4, and the file's first %d tap(s) are on screen" % F(cut))
        if (not last or last.get("why")) and not any(t > regions[-1]["t1"] + 1e-6 for t in taps_s):
            # only when the last hold is the chart's last event: with taps after it, the anchor would
            # charge any tap the file has wrong after the hold to the hold (Conflict S6, 2026-09-23)
            end = regions[-1]["t1"] + JIT
            last = dict(cut=round(end, 3), value=judged, file=F(end), err=judged - F(end), frames=0, of=0, anchor="a full combo rests at the judged count after the last event")
    befores[0], afters[-1] = first, last

    def ok(p):
        return bool(p) and not p.get("why")

    # a gap long enough to be read from both ends is read from both, and the two must agree:
    # a plateau the reader mangled (a 9 as 5) shows as one reading off the other's constant
    disputed = set()
    for i in range(n - 1):
        x, y = afters[i], befores[i + 1]
        if ok(x) and ok(y) and abs(x["cut"] - y["cut"]) > 1e-6 and x["err"] != y["err"]:
            disputed.add(i)
            why = "the two readings between them disagree (%d at %.2fs against the file's %d, %d at %.2fs against %d)" % (
                x["value"], x["cut"], x["file"], y["value"], y["cut"], y["file"])
            afters[i] = dict(x, why=why); befores[i + 1] = dict(y, why=why); between[i] = afters[i]
    clusters, cur = [], [0]
    for i in range(1, n):
        # a reading between two regions separates them; none, and they are read together
        if ok(between[i - 1]) or (i - 1) in disputed:
            clusters.append(cur); cur = [i]
        else:
            cur.append(i)
    clusters.append(cur)
    out = []
    for members in clusters:
        i0, i1 = members[0], members[-1]
        # the reading nearest the cluster on each side; failing that, the same gap read from
        # its other end (the stretch after the previous region, before the next)
        # the reading nearest the cluster on each side; failing that, the same gap read from its
        # other end - but only if that reading is itself within SPAN of the cluster. A reading
        # further off carries every tap between it and the cluster into the price, and a tap the
        # file has wrong there is then charged to the hold (Conflict S6's "before" sat 11 s early)
        b = befores[i0]
        if not ok(b) and i0 and ok(afters[i0 - 1]) and regions[i0]["t0"] - afters[i0 - 1]["cut"] <= SPAN:
            b = afters[i0 - 1]
        a = afters[i1]
        if not ok(a) and i1 + 1 < n and ok(befores[i1 + 1]) and befores[i1 + 1]["cut"] - regions[i1]["t1"] <= SPAN:
            a = befores[i1 + 1]
        rec = dict(regions=members, t0=regions[i0]["t0"], t1=regions[i1]["t1"], b0=regions[i0]["b0"], b1=regions[i1]["b1"],
                   ticks=sum(regions[k]["ticks"] for k in members), ends=regions[i1]["ends"], chained=regions[i1]["chained"],
                   before=b, after=a, price=None, why=None)
        if not b or not a:
            rec["why"] = "no reading " + ("before" if not b else "") + (" and " if not b and not a else "") + ("after" if not a else "")
        elif b.get("why") or a.get("why"):
            rec["why"] = b.get("why") or a.get("why")
        elif b.get("run", 0) != a.get("run", 0):
            rec["why"] = "the combo broke between the readings (run %d -> run %d)" % (b["run"], a["run"])
        elif a["value"] < b["value"]:
            rec["why"] = "the counter falls between the readings (%d -> %d)" % (b["value"], a["value"])
        elif rec["ticks"] + (a["err"] - b["err"]) < 0:
            rec["why"] = "the readings price it below zero (%d), so one of them is a misread" % (rec["ticks"] + a["err"] - b["err"])
        else:
            rec["diff"] = a["err"] - b["err"]
            rec["price"] = rec["ticks"] + rec["diff"]
            rec["climb"], rec["between"] = a["value"] - b["value"], (a["file"] - b["file"]) - rec["ticks"]
            # (until 2026-09-23 a shortfall of exactly the cluster's extra release rows was tagged
            # as the converter's staggered-release tick; the converter counts by the lattice now)
        out.append(rec)
    # Two adjacent clusters whose differences point opposite ways share one reading that is off:
    # a misread of that plateau, not two opposite errors in adjacent holds. Cleaner S13 read 25
    # for 29, 185 for 189, 405 for 409 (a units 9 as 5, which the chain cannot see when the
    # plateau is the first frame of that value) and priced the holds either side -4 and +4 four
    # times over; Iolite Sky D21 read 5 for 9 and priced its first two holds -5 and +4, which the
    # authoring then met with rates of 4 and 27. The magnitudes need not match - one of the two
    # holds may carry a real difference of its own - so any opposite-signed pair refuses both.
    for k in range(len(out) - 1):
        x, y = out[k], out[k + 1]
        if x.get("diff") and y.get("diff") and x["diff"] * y["diff"] < 0:
            why = "the reading between them (%d at %.2fs, the file's count there %d) prices them %+d and %+d - a misread of that plateau" % (
                x["after"]["value"], x["after"]["cut"], x["after"]["file"], x["diff"], y["diff"])
            for z in (x, y):
                z.update(price=None, diff=None, why=why, pattern=None)
    return out


# ---------------------------------------------------------------- the file

def exact(b):
    """A schedule beat as the converter reads it: 73.583333 as written and the row at 73 + 7/12
    are one beat, and one key here, not two a hair apart."""
    return float(_C._frac(b))


def schedule(text, tag):
    """The block's #TICKCOUNTS as sorted (beat, rate); the song header's when the block has none.
    Beats are exact (see exact), the later of two written a hair apart winning, as in the converter."""
    sections, i = edit_notes.find_block(text, tag)
    m = re.search(r"#TICKCOUNTS:(.*?);", sections[i], re.S) or re.search(r"#TICKCOUNTS:(.*?);", sections[0], re.S)
    entries = {}
    for part in sorted((p for p in (m.group(1) if m else "").replace("\n", "").replace("\r", "").split(",") if "=" in p),
                       key=lambda p: float(p.split("=")[0])):
        b, r = part.split("=")
        entries[exact(float(b))] = float(r)
    return sorted(entries.items())


def rate_at(sched, beat):
    r = 1.0
    for b, v in sched:
        if b <= beat + 1e-9:
            r = v
    return r


def fmt_rate(r):
    return "%d" % round(r) if abs(r - round(r)) < 1e-9 else "%g" % r


def regions_of(blk):
    """The converter's hold segments merged into regions: [t0, t1], beats, ticks, and what ends each."""
    _, holds = E.file_events(blk["rows"], blk["ncols"])
    times = [r["t"] for r in blk["rows"]]

    def beat_of(t):
        """The beat of the row at a region boundary (the converter's own row times)."""
        j = min(range(len(times)), key=lambda k: abs(times[k] - t)) if times else None
        return blk["rows"][j]["b"] if j is not None and abs(times[j] - t) < 1e-3 else None

    regs = []
    beats = blk.get("region_beats") or [(beat_of(t0), beat_of(t1)) for t0, t1, _ in blk["regions"]]
    for (t0, t1, tk), (b0, b1) in zip(blk["regions"], beats):
        regs.append(dict(t0=round(t0, 4), t1=round(t1, 4), b0=b0, b1=b1, ticks=tk,
                         segments=sum(1 for a, b, _ in blk["segments"] if a >= t0 - 1e-6 and b <= t1 + 1e-6)))
    for r in regs:
        ends = [h for h in holds if abs(h["tail"] - r["t1"]) < 1e-4]
        r["ends"] = [dict(col=h["col"], head_beat=h["head_beat"], tail_beat=h["tail_beat"]) for h in ends]
        r["chained"] = any(abs(h["head"] - r["t1"]) < 1e-4 for h in holds)
    return regs


def convert(text, key, tag):
    """The candidate text through the converter, as load_block sees it."""
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, "tmp-%s.ssc" % key)
    open(tmp, "w", encoding="utf-8", newline="").write(text)
    blk = E.load_block(tmp, tag)
    if not blk or blk.get("error"):
        return None
    return blk


def span_ticks(blk, t0, t1):
    """The converter's ticks over every region inside [t0, t1], or None if the span's regions changed."""
    inside = [tk for a, b, tk in blk["regions"] if a >= t0 - 1e-3 and b <= t1 + 1e-3]
    return sum(inside) if inside else None


def write_schedule(text, tag, entries):
    """The text with the block's #TICKCOUNTS set to `entries` {exact beat: rate}. An entry the
    schedule already had, at the same beat and rate, keeps its own text, so the diff shows only
    what changed."""
    old = {}
    sections, i = edit_notes.find_block(text.replace("\r\n", "\n"), tag)
    m = re.search(r"#TICKCOUNTS:(.*?);", sections[i], re.S) or re.search(r"#TICKCOUNTS:(.*?);", sections[0], re.S)
    for part in (m.group(1) if m else "").replace("\r", "").replace("\n", "").split(","):
        if "=" in part:
            b, r = part.split("=")
            old[exact(float(b))] = (float(r), part.strip())
    out = []
    for b, v in sorted(entries.items()):
        if b in old and abs(old[b][0] - v) < 1e-9:
            out.append(old[b][1])
        else:
            out.append("%.6f=%s" % (b, fmt_rate(v)))
    new, ok = author_ticks.patch(text.replace("\r\n", "\n"), tag, ",\n".join(out))
    if not ok:
        raise RuntimeError("block not found for TICKCOUNTS")
    return new.replace("\n", "\r\n") if "\r\n" in text else new


def rate_cluster(text, key, tag, cl, target):
    """A schedule over the cluster's span under which the converter derives `target` events for
    it, or None: the single integer rate nearest the one it has, found by scanning every rate up
    to twice the density the target needs (a region whose heads sit on a lattice counts fewer
    points at the rates that land on them, so the count is not monotone and bisection misses);
    failing that, two rates split on a sixteenth-beat grid between the pair whose counts bracket
    the target. Counted with the converter's own post-loop step (lattice_reauthor.Counts)."""
    import lattice_reauthor as L
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, "tmp-%s.ssc" % key)
    open(tmp, "w", encoding="utf-8", newline="").write(text)
    cnt = L.Counts(tmp, tag)
    b0, b1 = exact(cl["b0"]), exact(cl["b1"])
    idx = [k for k, (a, b) in enumerate(cnt.bounds) if a >= b0 - 1e-6 and b <= b1 + 1e-6]
    if not idx:
        return None

    def total(rates):
        cs = cnt.counts(L.with_region(dict(cnt.base), b0, b1, rates))
        return sum(cs[k] for k in idx)

    ref = L.rate_at(cnt.base, b0)
    top = min(4 * RATE_MAX, int(2 * target / max(b1 - b0, 1e-6)) + 12)
    scan = {r: total([(b0, r)]) for r in range(top + 1)}
    hits = [r for r, v in scan.items() if v == target]
    plan = [(b0, min(hits, key=lambda r: abs(r - ref)))] if hits else None
    if plan is None:
        lo = [r for r, v in scan.items() if v < target]
        hi = [r for r, v in scan.items() if v > target]
        pairs = sorted(((a, b) for a in lo for b in hi), key=lambda p: (abs(p[0] - p[1]), p[0] + p[1]))[:8]
        grid = [k / 16 for k in range(int(b0 * 16) + 1, int(b1 * 16) + 1) if b0 < k / 16 < b1]
        grid = grid[::max(1, len(grid) // 64)]
        for a, b in pairs:
            for c in grid:
                for rates in ([(b0, a), (c, b)], [(b0, b), (c, a)]):
                    if total(rates) == target:
                        plan = rates
                        break
                if plan:
                    break
            if plan:
                break
    if plan is None:
        return None
    return write_schedule(text, tag, L.with_region(dict(cnt.base), b0, b1, plan)), plan, ref


def tail_candidates(text, tag, cl):
    """The block's own rows on either side of the cluster's release row."""
    sections, i = edit_notes.find_block(text, tag)
    _, measures = edit_notes.parse_notes(sections[i])
    old = Fraction(cl["ends"][0]["tail_beat"]).limit_denominator(192)
    mi = int(old // 4)
    if mi >= len(measures):
        return []
    step = Fraction(4, len(measures[mi]))
    # the measure's own rows, and the half-row between them (the extraction loop's tail moves
    # land on any lattice line; a half-row is the finest this loop will go)
    return sorted({old + k * step for k in range(-TAIL_ROWS, TAIL_ROWS + 1) if k} | {old + k * step / 2 for k in (-1, 1)}, key=lambda x: abs(x - old))


def try_tail(text, key, tag, cl, target, pad, width, obs_tail):
    """Move the cluster's release row by one of the block's rows so the converter derives
    `target`, if the rail the extraction saw ends on that side of the file's release."""
    if len(cl["regions"]) != 1:
        return None, "it is a cluster of %d regions" % len(cl["regions"])
    if not cl["ends"] or cl["chained"]:
        return None, "the region does not end on a plain release row"
    tails = {Fraction(e["tail_beat"]).limit_denominator(192) for e in cl["ends"]}
    if len(tails) != 1:
        return None, "its holds release on different rows"
    old = tails.pop()
    want = -1 if target < cl["ticks"] else 1
    for e in cl["ends"]:
        o = obs_tail.get((e["col"], round(e["head_beat"], 6)))
        if o is None:
            return None, "col %d: the extraction saw no solid rail for the hold that ends it" % e["col"]
        if (o - cl["t1"]) * want <= 0.0:
            return None, "col %d: the rail on screen ends %+.0f ms from the file's release, not on the side the count wants" % (e["col"], 1000 * (o - cl["t1"]))
    for nb in sorted(tail_candidates(text, tag, cl), key=lambda x: abs(x - old)):
        if (nb - old) * want <= 0:
            continue
        edits = [dict(kind="tail", col=e["col"] + pad, head=str(Fraction(e["head_beat"]).limit_denominator(192)), old=str(old), tail=str(nb),
                      grid=nb.denominator, old_t=cl["t1"], tail_t=None) for e in cl["ends"]]
        cand, done, skipped, _ = E.apply(text, tag, edits, pad, width)
        if skipped or len(done) != len(edits):
            continue
        blk = convert(cand, key, tag)
        if not blk:
            continue
        # the moved release must leave the region's start where it was and land on the price
        if span_ticks(blk, cl["t0"], cl["t1"] + 10.0) is None:
            continue
        got = next((tk for a, b, tk in blk["regions"] if abs(a - cl["t0"]) < 1e-3), None)
        if got == target:
            for d in done:
                d["tail_t"] = next((r["t"] for r in blk["rows"] if abs(r["b"] - float(nb)) < 1e-6), None)
            return (cand, done), None
    return None, "no release move of %d row reaches %d" % (TAIL_ROWS, target)


# ---------------------------------------------------------------- one chart

def survey_chart(job, scan_ok=True):
    name, key, tag = job["chart"], job["key"], E.block_tag(job["key"])
    ssc = job["base"] or os.path.join(ROOT, "simfiles", *job["ssc_rel"].split("/"))
    expected = job["expected"]
    rec = dict(chart=name, key=key, ssc_rel=job["ssc_rel"], vid=job["vid"], side=job["side"], shape=job["shape"],
               expected=expected, base=("extraction candidate " + os.path.relpath(ssc, ROOT).replace(os.sep, "/")) if job["base"] else "file", verdict="PARK")
    blk = E.load_block(ssc, tag)
    if not blk or blk.get("error"):
        return {**rec, "reason": "file: " + ((blk or {}).get("error") or "block not found")}
    rec["file"] = dict(taps=blk["taps"], ticks=blk["ticks"], implied=blk["implied"], width=blk["width"], regions=len(blk["regions"]))
    D = expected - blk["implied"]
    rec["deficit"] = D
    if D == 0:
        return {**rec, "verdict": "EXACT", "reason": "already exact at %d" % expected}
    if not blk["regions"]:
        return {**rec, "reason": "the file has no holds, so there is nothing for the counter to price"}

    # the play
    cert = corpus_map.certification()[job["vid"]]
    side = cert.get(job["side"]) or {}
    try:
        judged, mc = int(side["judged"]), int(str(side["maxcombo"]).strip())
    except (KeyError, ValueError, TypeError):
        return {**rec, "reason": "no maxcombo on the result screen"}
    other = cert.get("2p" if job["side"] == "1p" else "1p") or {}
    band = "C" if not other.get("judged") else ("L" if job["side"] == "1p" else "R")
    n_off = sum(int(str(side.get(k) or 0).strip() or 0) for k in ("good", "bad", "miss"))
    clean = mc == judged
    rec["play"] = dict(judged=judged, maxcombo=mc, clean=clean, good_bad_miss=n_off, band=band)

    # the alignment, from the file's own notes on screen
    notes, meta = note_extract.extract(name, quiet=True)
    ncols = blk["ncols"]
    fnotes, fholds = E.file_events(blk["rows"], ncols)
    a, b, n_fit, seed = E.align(notes, fnotes, ncols)
    clock = Clock(a, b)
    rec["alignment"] = dict(offset=round(-a / b if b else -a, 3), clock=round(100 * (b - 1), 4), fitted_on=n_fit)
    pairs, extra, missing, errs = E.match(notes, fnotes, ncols, a, b)
    obs_tail = {}
    for i, c, (ft, fb, sym) in pairs:
        n = notes[i]
        if sym == "2" and n.get("hold_end") is not None and n.get("rail_len", 0) >= E.RAIL_LEN and n.get("rail_occ", 0) >= E.RAIL_OCC:
            obs_tail[(c, round(fb, 6))] = clock.chart(n["hold_end"])

    # the counter
    raw = reads_for(job["vid"], band, mc, scan_ok)
    if not raw:
        return {**rec, "reason": "no counter scan for %s band %s" % (job["vid"], band)}
    if clean:
        reads = [(t, v, 0) for t, v in chain(raw)]
    else:
        # across a break the counter restarts, so the two readings of a region must come from one run
        reads = runs(raw)
    regions = regions_of(blk)
    taps = [r["t"] for r in blk["rows"] if "1" in r["line"]]
    lag, n_lag = measure_lag(reads, taps, regions, clock)
    clock.lag = lag
    rec["reads"] = dict(confident=len(raw), on_chain=len(reads), lag=lag, lag_taps=n_lag)
    tol = max(8, 3 * abs(D) + 5)
    clusters = price_clusters(regions, taps, reads, clock, clean, tol, judged if clean else None)
    # what the tick lattice gives each priced cluster (tools/tick_model.py): where it agrees with
    # the counter and the converter does not, the file is right and the converter's arithmetic is
    # what is off - that is tagged, and never authored around
    import tick_model
    sched0 = schedule(open(ssc, encoding="utf-8", newline="").read(), tag)
    for c in clusters:
        if c.get("price") is None:
            continue
        c["model"] = sum(tick_model.model_region(blk["rows"], ncols, sched0, regions[k]["t0"], regions[k]["t1"]) for k in c["regions"])
        if c["model"] == c["price"] != c["ticks"]:
            c["pattern"] = (c.get("pattern") + " (the tick lattice agrees)") if c.get("pattern") else \
                "converter arithmetic: the tick lattice gives %d, the converter %d, the counter %d" % (c["model"], c["ticks"], c["price"])
    priced = [c for c in clusters if c["price"] is not None]
    unpriced = [c for c in clusters if c["price"] is None]
    S = sum(c["diff"] for c in priced)
    rec["clusters"] = [dict(regions=c["regions"], t0=c["t0"], t1=c["t1"], b0=c["b0"], b1=c["b1"], ticks=c["ticks"], price=c["price"],
                            diff=c.get("diff"), why=c["why"], before=c["before"], after=c["after"], climb=c.get("climb"), between=c.get("between"),
                            pattern=c.get("pattern"), model=c.get("model"))
                       for c in clusters]
    rec["patterns"] = dict(Counter(c["pattern"].split(":")[0] for c in clusters if c.get("pattern")))
    rec["arithmetic"] = dict(priced=sum(1 for c in clusters if c.get("price") is not None),
                             converter_right=sum(1 for c in clusters if c.get("price") is not None and c["ticks"] == c["price"]),
                             lattice_right=sum(1 for c in clusters if c.get("price") is not None and c.get("model") == c["price"]),
                             neither=sum(1 for c in clusters if c.get("price") is not None and c["ticks"] != c["price"] and c.get("model") != c["price"]))
    rec.update(regions=len(regions), priced=len(priced), priced_regions=sum(len(c["regions"]) for c in priced), unpriced=len(unpriced),
               unpriced_why=dict(Counter(c["why"].split(" (")[0].split(": the read")[0] for c in unpriced)), diff_sum=S,
               differing=sum(1 for c in priced if c["diff"]))
    if not priced:
        return {**rec, "reason": "none of the %d hold regions could be read from the counter (%s)" % (len(regions), rec["unpriced_why"])}
    if S != D:
        return {**rec, "reason": "priced %d of %d regions; their differences sum to %+d against a deficit of %+d - %s" % (
            rec["priced_regions"], len(regions), S, D, "the rest is in regions the counter could not read" if unpriced else "the counter and the count disagree")}
    if not clean and unpriced:
        return {**rec, "reason": "closes on %d of %d regions, but the play has %d GOOD/BAD/MISS (maxcombo %d of %d judged) - an unread region could hide one" % (
            rec["priced_regions"], len(regions), n_off, mc, judged)}

    # authoring: the single rate first, the block's own row second, nothing else
    text = open(ssc, encoding="utf-8", newline="").read()
    pad = (ncols - blk["width"]) // 2
    edits = []
    for c in priced:
        if not c["diff"]:
            continue
        if c.get("pattern"):
            # the difference is the converter's own arithmetic, not the file: a tail move that
            # happened to land on the price would be a grid edit against the video, and a rate
            # bent to absorb it would have to be unbent when the converter is corrected
            return {**rec, "reason": "region at %.2fs priced %d against the file's %d - %s; not authored around" % (c["t0"], c["price"], c["ticks"], c["pattern"])}
        if len(c["regions"]) > WINDOW_REGIONS or c["t1"] - c["t0"] > WINDOW_SECONDS:
            # a window's total is measured; its interior is not, and one rate over a long run of
            # holds redistributes every one of them to shave a tick (Bluish Rose D14: 25 regions
            # over 67 s re-rated 16 -> 15 to lose one tick - an exact total, a fabricated interior)
            return {**rec, "reason": "cluster of %d regions over %.0f s (%.2f-%.2fs) priced %d against the file's %d as one - the interior is unobservable at this resolution" % (
                len(c["regions"]), c["t1"] - c["t0"], c["t0"], c["t1"], c["price"], c["ticks"])}
        got = rate_cluster(text, key, tag, c, c["price"])
        if got is not None:
            text, plan, ref = got
            edits.append(dict(kind="rate", cluster=c["t0"], b0=c["b0"], b1=c["b1"], old=fmt_rate(ref),
                              new=", then ".join("%s from beat %.4f" % (fmt_rate(r), b) for b, r in plan) if len(plan) > 1 else fmt_rate(plan[0][1]),
                              ticks=c["ticks"], price=c["price"]))
            continue
        got, why = try_tail(text, key, tag, c, c["price"], pad, blk["width"], obs_tail)
        if got:
            text, done = got
            for d in done:
                edits.append(dict(d, cluster=c["t0"], ticks=c["ticks"], price=c["price"],
                                  rail_end=round(obs_tail[(d["col"] - pad, round(float(Fraction(d["head"])), 6))], 3)))
            continue
        return {**rec, "reason": "region at %.2fs priced %d against the file's %d: no single rate reaches it and %s%s" % (
            c["t0"], c["price"], c["ticks"], why, (" (" + c["pattern"] + ")") if c.get("pattern") else "")}
    rec["edits"] = edits
    after = convert(text, key, tag)
    if not after:
        return {**rec, "reason": "the authored candidate did not convert"}
    rec["after"] = dict(taps=after["taps"], ticks=after["ticks"], implied=after["implied"])
    wrong = [c for c in clusters if span_ticks(after, c["t0"], c["t1"] if not any(e["kind"] == "tail" and e["cluster"] == c["t0"] for e in edits) else c["t1"] + 10.0)
             != (c["price"] if c["price"] is not None else c["ticks"])]
    if wrong:
        return {**rec, "reason": "authored, but %d region(s) did not land where the counter put them (first at %.2fs)" % (len(wrong), wrong[0]["t0"])}
    if after["implied"] != expected:
        return {**rec, "reason": "authored to every price, yet the converter derives %d against %d" % (after["implied"], expected)}
    os.makedirs(OUT, exist_ok=True)
    cand = os.path.join(OUT, key + ".ssc")
    open(cand, "w", encoding="utf-8", newline="").write(text)
    rec["candidate"] = os.path.relpath(cand, ROOT).replace(os.sep, "/")
    return {**rec, "verdict": "SHIP", "reason": "%s -> taps %d + ticks %d = %d, exact (%d of %d regions read)" % (
        summary(edits), after["taps"], after["ticks"], after["implied"], rec["priced_regions"], len(regions))}


def summary(edits):
    c = Counter(e["kind"] for e in edits)
    parts = []
    if c["rate"]:
        parts.append("%d hold region%s re-ticked from the counter" % (c["rate"], "" if c["rate"] == 1 else "s"))
    if c["tail"]:
        parts.append("%d release%s moved a row" % (c["tail"], "" if c["tail"] == 1 else "s"))
    return ", ".join(parts) or "no edit"


# ---------------------------------------------------------------- survey and commit

def report_path(shard):
    return os.path.join(ROOT, "work", "tick-loop-report%s.json" % (("." + shard.split("/")[0]) if shard else ""))


def survey():
    note_extract.CACHE = True
    only, limit, shard, near = arg("--only"), arg("--limit"), arg("--shard"), int(arg("--near", NEAR))
    jobs = [j for j in worklist() if (not only or j["chart"] == only) and abs(j["dist"]) <= near]
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        jobs = jobs[i::n]
    if limit:
        jobs = jobs[:int(limit)]
    path = report_path(shard)
    prior = {r["chart"]: r for r in json.load(open(path, encoding="utf-8"))} if os.path.exists(path) and "--redo" not in sys.argv else {}
    if arg("--redo-verdict"):
        prior = {k: v for k, v in prior.items() if v.get("verdict") not in arg("--redo-verdict").split(",")}
    if arg("--redo-reason"):            # e.g. --redo-reason "no counter scan": those charts run again
        prior = {k: v for k, v in prior.items() if arg("--redo-reason") not in (v.get("reason") or "")}
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    for i, job in enumerate(jobs, 1):
        if job["chart"] in prior:
            continue
        t1 = time.time()
        try:
            rec = survey_chart(job, scan_ok="--no-scan" not in sys.argv)
        except Exception as ex:
            rec = dict(chart=job["chart"], key=job["key"], verdict="FAIL", reason=f"{type(ex).__name__}: {ex}"[:160])
        rec["dist"] = job["dist"]
        rec["seconds"] = round(time.time() - t1, 1)
        prior[job["chart"]] = rec
        print("[%d/%d] %-5s %-46s %s (%ss)" % (i, len(jobs), rec["verdict"], job["chart"][:46], rec.get("reason", "")[:100], rec["seconds"]), flush=True)
        json.dump(list(prior.values()), open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n%d charts in %.0fs; verdicts %s" % (len(jobs), time.time() - t0, dict(Counter(r["verdict"] for r in prior.values()))))


def message(rec):
    x, al, p, rd = rec["census"], rec["alignment"], rec["play"], rec["reads"]
    lines = ["Fix %s hold ticks from the combo counter: %s" % (rec["chart"], summary(rec["edits"])), ""]
    lines.append("Evidence: the certified chart video %s (%s, band %s), result screen judged %d, maxcombo %d%s." % (
        rec["vid"], rec["side"], p["band"], p["judged"], p["maxcombo"],
        " - a full combo, so every judged event moved the counter and the counter never fell" if p["clean"]
        else " with %d GOOD/BAD/MISS, so every hold region had to be read" % p["good_bad_miss"]))
    lines.append("The video clock comes from tools/note_extract.py matching the file's own notes on screen (%.1f%% of" % (100 * x["extraction"]["recall"]))
    lines.append("them found, offset %+.3fs, clock %+.4f%%, fitted on %d notes); tools/combo_reader.py read the counter" % (al["offset"], al["clock"], al["fitted_on"]))
    lines.append("(%d confident reads, %d on the counter's non-decreasing chain, display lag %.3fs measured on %d isolated" % (rd["confident"], rd["on_chain"], rd["lag"], rd["lag_taps"]))
    lines.append("taps), and tools/tick_repair.py priced each of the file's %d hold regions from the counter's plateaus" % rec["regions"])
    lines.append("either side of it: the climb between them, less the file's own events between the plateaus.")
    lines.append("%d of %d regions were read; their differences from the file sum to the whole deficit (%+d), so the" % (rec["priced_regions"], rec["regions"], rec["deficit"]))
    lines.append("%d unread region(s) stay as the file has them." % (rec["regions"] - rec["priced_regions"]) if rec["unpriced"] else "every region was read.")
    lines.append("")
    if rec["base"] != "file":
        lines.append("Starts from the extraction loop's candidate for this chart (its edits, each something the screen showed):")
        for d in E.applied(x):
            lines.append("  " + E.edit_line(d))
        lines.append("")
    lines.append("Regions the counter priced differently from the file:")
    by_t0 = {c["t0"]: c for c in rec["clusters"]}
    for e in rec["edits"]:
        c = by_t0[e["cluster"]]
        read = "counter %d at %.2fs (file's count there %d) -> %d at %.2fs (%d): climb %d, %d of it the file's own taps and other holds, %d ticks judged; the file derived %d" % (
            c["before"]["value"], c["before"]["cut"], c["before"]["file"], c["after"]["value"], c["after"]["cut"], c["after"]["file"],
            c["climb"], c["between"], c["price"], c["ticks"])
        for which in ("before", "after"):
            if c[which].get("anchor"):
                read += "; the %s value is not a read but closure: %s" % (which, c[which]["anchor"])
        if e["kind"] == "rate":
            lines.append("  beats %.3f-%.3f (%.2f-%.2fs, %d region%s): %s -> TICKCOUNTS %s per beat over the span (was %s)%s" % (
                e["b0"], e["b1"], c["t0"], c["t1"], len(c["regions"]), "" if len(c["regions"]) == 1 else "s", read, e["new"], e["old"],
                "; the total over the window is measured, the split between its regions is the rate's" if len(c["regions"]) > 1 else ""))
        else:
            lines.append("  col %d beat %s (%.2f-%.2fs): %s -> release moved %s -> %s (%.2f -> %.2fs); the rail on screen ends at %.2fs, on that side of the file's release" % (
                e["col"], e["head"], c["t0"], c["t1"], read, e["old"], e["tail"], e["old_t"], e["tail_t"], e["rail_end"]))
    lines.append("")
    lines.append("Before: taps %d + ticks %d = %d. After: taps %d + ticks %d = %d, the judged count exactly (tick_verify)," % (
        rec["file"]["taps"], rec["file"]["ticks"], rec["file"]["implied"], rec["after"]["taps"], rec["after"]["ticks"], rec["after"]["implied"]))
    lines.append("with every priced region deriving its measured count. No frame was read by eye.")
    return "\n".join(lines) + TRAILER


def commit():
    only, dry = arg("--only"), "--dry-run" in sys.argv
    census = {r["chart"]: r for r in json.load(open(census_path(), encoding="utf-8"))["charts"]}
    files = sorted(f for f in os.listdir(os.path.join(ROOT, "work")) if f.startswith("tick-loop-report") and f.endswith(".json"))
    recs = []
    for f in files:
        recs += json.load(open(os.path.join(ROOT, "work", f), encoding="utf-8"))
    ships = [r for r in recs if r.get("verdict") == "SHIP" and not r.get("commit") and (not only or r["chart"] == only)]
    print("%d SHIP verdict(s) to commit" % len(ships))
    if E.git("status", "--short", "--", "simfiles").strip():
        sys.exit("simfiles/ has uncommitted changes - refusing")
    for r in ships:
        ssc = os.path.join(ROOT, "simfiles", *r["ssc_rel"].split("/"))
        cand = os.path.join(ROOT, *r["candidate"].split("/"))
        if not os.path.exists(cand):
            print("  %s: candidate missing, skipped" % r["chart"]); continue
        if not E.same_outside(open(ssc, encoding="utf-8", newline="").read(), open(cand, encoding="utf-8", newline="").read(), E.block_tag(r["key"])):
            print("  %s: the file changed outside this block since the candidate was written (another chart of the same "
                  "song was repaired) - re-run the survey for it and commit again" % r["chart"]); continue
        shutil.copyfile(cand, ssc)
        out = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "tools", "tick_verify.py"), "--file", ssc, "--block", E.block_tag(r["key"]), str(r["expected"])],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        if "MATCH" not in out:
            E.git("checkout", "HEAD", "--", ssc)
            print("  %s: tick_verify did not agree in place (%s) - reverted" % (r["chart"], out.strip().splitlines()[0] if out.strip() else "no output")); continue
        if dry:
            E.git("checkout", "HEAD", "--", ssc)
            print("  would commit %s: %s" % (r["chart"], r["reason"])); continue
        E.git("add", "--", ssc)
        subprocess.run(["git", "commit", "-q", "-F", "-"], cwd=ROOT, input=message({**r, "census": census[r["chart"]]}), text=True, encoding="utf-8")
        r["commit"] = E.git("rev-parse", "--short", "HEAD").strip()
        print("  %s %s: %s" % (r["commit"], r["chart"], r["reason"]))
    if not dry:
        done = {r["chart"]: r for r in ships if r.get("commit")}
        for f in files:
            p = os.path.join(ROOT, "work", f)
            rows = json.load(open(p, encoding="utf-8"))
            json.dump([done.get(x["chart"], x) for x in rows], open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["survey"]:
        survey()
    elif sys.argv[1:2] == ["commit"]:
        commit()
    else:
        sys.exit("usage: tick_repair.py survey [...] | commit [--dry-run]")
